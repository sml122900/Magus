"""세 책장(사람 소유) 저장. LocalStore에 섞어 쓰는 믹스인이다.

원본: data/users/<user_id>/shelf/{melchior,casper,balthasar}/…
인덱스: refs·ref_passages·ideas·style_entries 행과, 검색용 chunks·chunks_fts.
청크는 원본에서 언제든 다시 만들 수 있다. 임베딩(BLOB)은 파생값이라 재생성 뒤에는 비어 있고,
임베딩 제공자가 설정돼 있으면 magus.search.embed_missing이 다시 채운다.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from magus.balthasar.style import search_text as style_search_text
from magus.floors import COMMON
from magus.ids import safe_id, utcnow
from magus.store.base import (
    WEB_ONLY_LANES, Author, Chunk, Idea, Lane, Passage, Ref, RefStatus, StyleEntry, TrashItem, TrashKind,
)
from magus.store.fileio import locked, read_json, read_text, write_json, write_text
from magus.store.floors import Layout
from magus.textindex import chunk_text, index_text

# 생각 파일에서 값이 없으면 쓰지 않는 키(#92 전 코드로 되돌려도 그 파일을 그대로 읽도록).
# "floor"(#93)는 언제나 적는다. 층 전 코드로 되돌릴 때는 magus floors revert로 먼저 뗀다.
OPTIONAL_IDEA_KEYS = ("title", "title_by", "edited_at", "edited_by")


def _in(floors: Iterable[str] | None, column: str = "floor") -> tuple[str, list[str]]:
    """floors 거르기 SQL 조각과 값. None이면 거르지 않는다."""
    if floors is None:
        return "", []
    values = list(dict.fromkeys(floors))
    return (f" AND {column} IN ({','.join('?' * len(values))})", values) if values else (" AND 0", [])
_REF_KEY = re.compile(r"[a-z0-9가-힣一-鿿㐀-䶿][a-z0-9가-힣一-鿿㐀-䶿_-]{0,79}")


def safe_ref_key(key: str) -> str:
    if not _REF_KEY.fullmatch(key):
        raise ValueError(f"ref key={key!r}: 소문자 영문·숫자·한글·한자·_·-, 80자 이하")
    return key


class ShelfMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock

    def _user_dir(self, user_id: str) -> Path: ...  # LocalStore가 구현한다
    # FloorMixin이 구현한다
    _layout: Callable[[str], Layout]
    _known: Callable[[str, Layout], set[str]]
    place: Callable[[str, str, str | None], str]
    # CategoryMixin이 구현한다(메서드 껍데기를 두면 MRO에서 진짜를 가리므로 주석만 둔다)
    _trashed_categories: Callable[[str], list[tuple[str, str, dict[str, Any], str]]]
    _restore_category: Callable[[str, str, str | None], list[str]]
    _restore_category_item: Callable[[str, str], list[str]]

    # ---- Melchior: 문헌 --------------------------------------------------------------

    def _melchior_dir(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "melchior"

    @locked
    def get_ref(self, user_id: str, key: str, *, floors: Iterable[str] | None = None) -> Ref | None:
        where, values = _in(floors)
        row = self._db.execute(f"SELECT * FROM refs WHERE user_id = ? AND key = ?{where}", (user_id, key, *values)).fetchone()
        return _ref(row) if row else None

    @locked
    def resolve_ref(self, user_id: str, key: str, *, floors: Iterable[str] | None = None) -> Ref | None:
        floors = list(floors) if floors is not None else None
        if ref := self.get_ref(user_id, key, floors=floors):
            return ref
        where, values = _in(floors, "r.floor")
        row = self._db.execute(
            f"SELECT r.* FROM refs r, json_each(r.aliases) a WHERE r.user_id = ? AND a.value = ?{where} ORDER BY r.key LIMIT 1",
            (user_id, key, *values),
        ).fetchone()
        return _ref(row) if row else None

    @locked
    def list_refs(self, user_id: str, status: RefStatus | None = None, *, floors: Iterable[str] | None = None) -> list[Ref]:
        where, values = _in(floors)
        sql, args = f"SELECT * FROM refs WHERE user_id = ?{where}", [user_id, *values]
        if status:
            sql, args = sql + " AND status = ?", [*args, status]
        return [_ref(r) for r in self._db.execute(sql + " ORDER BY key", args)]

    @locked
    def get_passages(self, user_id: str, key: str) -> list[Passage]:
        rows = self._db.execute(
            "SELECT p.text, p.reason, p.locator FROM ref_passages p JOIN refs r ON r.id = p.ref_id "
            "WHERE r.user_id = ? AND r.key = ? ORDER BY p.id",
            (user_id, key),
        )
        return [Passage(r["text"], r["reason"], r["locator"]) for r in rows]

    @locked
    def put_ref(
        self, user_id: str, ref: Ref, passages: list[Passage] | None = None, full_text: str | None = None
    ) -> Ref:
        key = safe_ref_key(ref.key)
        rdir = self._melchior_dir(user_id) / key
        old = read_json(rdir / "bib.json") if (rdir / "bib.json").exists() else {}
        known = self._known(user_id, self._layout(user_id))
        # 층: 준 것(호출자가 place로 정한 층), 없으면 지금 꽂힌 층, 새 문헌이면 위에서부터 문헌이 꽂힌 첫 층(#93)
        floor = (next((f for f in (ref.floor, old.get("floor")) if isinstance(f, str) and f in known), None)
                 or self.place(user_id, "refs", None))
        if full_text is not None:
            write_text(rdir / "full.txt", full_text)
        if passages is not None:
            write_json(rdir / "passages.json", [asdict(p) for p in passages])
        write_json(
            rdir / "bib.json",
            {
                "key": key,
                "status": ref.status,
                "aliases": list(dict.fromkeys(ref.aliases)),
                "bib": ref.bib,
                "file_path": ref.file_path,
                "created_at": ref.created_at or old.get("created_at") or utcnow(),
                "updated_at": utcnow(),
                "floor": floor,
            },
        )
        with self._db:
            self._index_ref(user_id, rdir)
        stored = self.get_ref(user_id, key)
        assert stored is not None
        return stored

    def _index_ref(self, user_id: str, rdir: Path, floor: str | None = None) -> None:
        """floor: reindex가 배치에서 정해 준 층(파일에 층이 없거나 모르는 층일 때). None이면 파일의 층."""
        record = read_json(rdir / "bib.json")
        full = read_text(rdir / "full.txt")
        passages = read_json(rdir / "passages.json") if (rdir / "passages.json").exists() else []
        ref_id = self._db.execute(
            """
            INSERT INTO refs (user_id, key, aliases, bib, status, has_fulltext, file_path, created_at, updated_at, floor)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, key) DO UPDATE SET
                aliases = excluded.aliases, bib = excluded.bib, status = excluded.status,
                has_fulltext = excluded.has_fulltext, file_path = excluded.file_path, updated_at = excluded.updated_at,
                floor = excluded.floor
            RETURNING id
            """,
            (
                user_id,
                record["key"],
                json.dumps(record.get("aliases", []), ensure_ascii=False),
                json.dumps(record.get("bib", {}), ensure_ascii=False),
                record.get("status", "unverified"),
                int(bool(full.strip())),
                record.get("file_path"),
                record.get("created_at") or utcnow(),
                record.get("updated_at"),
                floor or str(record.get("floor") or COMMON),
            ),
        ).fetchone()[0]
        self._db.execute("DELETE FROM ref_passages WHERE ref_id = ?", (ref_id,))
        self._db.executemany(
            "INSERT INTO ref_passages (user_id, ref_id, text, reason, locator) VALUES (?, ?, ?, ?, ?)",
            [(user_id, ref_id, p["text"], p.get("reason", ""), p.get("locator")) for p in passages],
        )
        self._replace_chunks(user_id, "ref", record["key"], "ref_picked", [p["text"] for p in passages])
        self._replace_chunks(user_id, "ref", record["key"], "ref_full", chunk_text(full) if full.strip() else [])
        self._replace_chunks(user_id, "ref", record["key"], "ref_bib", [bib_text(record)])  # 웹 책장 검색 전용

    # ---- Casper: 영감 ----------------------------------------------------------------

    def _casper_dir(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "casper"

    @locked
    def add_ideas(self, user_id: str, ideas: list[Idea]) -> list[Idea]:
        stored = []
        default = self.place(user_id, "ideas", None) if any(i.floor is None for i in ideas) else None
        for idea in ideas:
            safe_id(idea.id, "idea id")
            idea = replace(idea, created_at=idea.created_at or utcnow(), floor=idea.floor or default)
            # 제목이 없으면 title·title_by 키를 쓰지 않는다: 제목 전(#92 전) 코드로 되돌려도 파일을 그대로 읽는다
            record = {k: v for k, v in asdict(idea).items() if not (k in OPTIONAL_IDEA_KEYS and v is None)}
            write_json(self._casper_dir(user_id) / f"{idea.id}.json", record)
            stored.append(idea)
        with self._db:
            for idea in stored:
                self._index_idea(user_id, idea)
        return stored

    def _index_idea(self, user_id: str, idea: Idea) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO ideas (id, user_id, text, kind, origin, author, parent_id, created_at, title, title_by, "
            "edited_at, edited_by, floor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (idea.id, user_id, idea.text, idea.kind, idea.origin, idea.author, idea.parent_id, idea.created_at, idea.title,
             idea.title_by, idea.edited_at, idea.edited_by, idea.floor or COMMON),
        )
        lane: Lane = "idea_me" if idea.author == "me" else "idea_ai"
        text = f"{idea.title}\n{idea.text}" if idea.title else idea.text  # 제목(#92)도 찾는다
        self._replace_chunks(user_id, "idea", idea.id, lane, chunk_text(text))

    @locked
    def get_ideas(self, user_id: str, ids: list[str]) -> dict[str, Idea]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._db.execute(f"SELECT * FROM ideas WHERE user_id = ? AND id IN ({marks})", (user_id, *ids))
        return {r["id"]: _idea(r) for r in rows}

    @locked
    def list_ideas(self, user_id: str, author: Author | None = None, *, floors: Iterable[str] | None = None) -> list[Idea]:
        where, values = _in(floors)
        sql, args = f"SELECT * FROM ideas WHERE user_id = ?{where}", [user_id, *values]
        if author:
            sql, args = sql + " AND author = ?", [*args, author]
        return [_idea(r) for r in self._db.execute(sql + " ORDER BY id", args)]

    # ---- Balthasar: 문체 -------------------------------------------------------------

    def _balthasar_dir(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "balthasar"

    @locked
    def add_style(self, user_id: str, entry: StyleEntry) -> StyleEntry:
        safe_id(entry.id, "style id")
        entry = replace(entry, created_at=entry.created_at or utcnow(), floor=entry.floor or self.place(user_id, "styles", None))
        write_json(self._balthasar_dir(user_id) / f"{entry.id}.json", asdict(entry))
        with self._db:
            self._index_style(user_id, entry)
        return entry

    def _index_style(self, user_id: str, entry: StyleEntry) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO style_entries (id, user_id, passage, reason, work, tags, created_at, tags_by, floor) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entry.id, user_id, entry.passage, entry.reason, entry.work, json.dumps(entry.tags, ensure_ascii=False),
             entry.created_at, entry.tags_by, entry.floor or COMMON),
        )
        # 문체 검색의 대상은 reason + tags다. passage를 색인하면 문체가 아니라 주제가 검색된다.
        # work(출전)는 키워드 색인에만 더한다: "유홍준 그 문장"처럼 출전으로 찾는 경우가 있다(사용자 결정 #24).
        self._replace_chunks(
            user_id, "style", entry.id, "style", [style_search_text(entry.reason, entry.tags)], fts_extra=entry.work or ""
        )
        # 웹 책장 검색 전용 레인(구절·출전). style_search는 이 레인을 보지 않으므로 위의 원칙은 그대로다.
        self._replace_chunks(user_id, "style", entry.id, "style_passage", [f"{entry.passage}\n{entry.work or ''}".strip()])

    @locked
    def get_styles(self, user_id: str, ids: list[str]) -> dict[str, StyleEntry]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._db.execute(f"SELECT * FROM style_entries WHERE user_id = ? AND id IN ({marks})", (user_id, *ids))
        return {r["id"]: _style(r) for r in rows}

    @locked
    def list_styles(self, user_id: str, *, floors: Iterable[str] | None = None) -> list[StyleEntry]:
        where, values = _in(floors)
        return [_style(r) for r in self._db.execute(f"SELECT * FROM style_entries WHERE user_id = ?{where} ORDER BY id",
                                                    (user_id, *values))]

    # ---- 휴지통(생각·문체, #88) -------------------------------------------------------
    # 지우지 않고 trash/shelf/<casper|balthasar>/<id>.json으로 옮긴다. 파일에 "_trash"(시각·이유·함께 옮긴 생각)를 덧붙인다.
    # shelf/ 밖이라 reindex·검색·목록·웹에서 빠진다. 되살리면 "_trash"를 떼고 제자리로 돌려 다시 색인한다.

    def _trash_dir(self, user_id: str, kind: TrashKind) -> Path:  # 생각·문체만
        return self._user_dir(user_id) / "trash" / "shelf" / ("casper" if kind == "idea" else "balthasar")

    def _shelf_dir(self, user_id: str, kind: TrashKind) -> Path:
        return self._casper_dir(user_id) if kind == "idea" else self._balthasar_dir(user_id)

    def _move_to_trash(self, user_id: str, kind: TrashKind, item_id: str, mark: dict[str, Any]) -> dict[str, Any]:
        src = self._shelf_dir(user_id, kind) / f"{item_id}.json"
        data = read_json(src)
        write_json(self._trash_dir(user_id, kind) / f"{item_id}.json", {**data, "_trash": mark})  # 먼저 쓰고 지운다
        src.unlink()
        table = "style_entries" if kind == "style" else "ideas"
        self._db.execute(f"DELETE FROM {table} WHERE user_id = ? AND id = ?", (user_id, item_id))
        self._drop_chunks(user_id, kind, item_id)
        return data

    @locked
    def trash_idea(self, user_id: str, idea_id: str, note: str) -> list[Idea]:
        safe_id(idea_id, "idea id")
        if not (self._casper_dir(user_id) / f"{idea_id}.json").exists():
            return []
        replies = [i.id for i in self.list_ideas(user_id) if i.parent_id == idea_id]
        at, moved = utcnow(), []
        with self._db:
            for item, with_id in [(idea_id, None), *((r, idea_id) for r in replies)]:
                mark = {"at": at, "note": note, **({"with": with_id} if with_id else {})}
                moved.append(Idea(**self._move_to_trash(user_id, "idea", item, mark)))
        return moved

    @locked
    def trash_style(self, user_id: str, style_id: str, note: str) -> StyleEntry | None:
        safe_id(style_id, "style id")
        if not (self._balthasar_dir(user_id) / f"{style_id}.json").exists():
            return None
        with self._db:
            return StyleEntry(**self._move_to_trash(user_id, "style", style_id, {"at": utcnow(), "note": note}))

    @locked
    def list_trash(self, user_id: str) -> list[TrashItem]:
        items = []
        for kind in ("idea", "style"):
            for path in sorted(self._trash_dir(user_id, kind).glob("*.json")):  # type: ignore[arg-type]
                data = read_json(path)
                mark = data.get("_trash") or {}
                items.append(TrashItem(kind, path.stem, mark.get("at", ""), mark.get("note", ""),  # type: ignore[arg-type]
                                       str(data.get("text") or data.get("passage") or "")[:80], mark.get("with")))
        for kind, item_id, data, at in self._trashed_categories(user_id):  # 카테고리 통째·카테고리 항목(#92)
            mark = data.get("_trash") or {}
            preview = (f"카테고리 「{data.get('name', '')}」" if kind == "category"
                       else str(data.get("title") or data.get("content") or "")[:80])
            items.append(TrashItem(kind, item_id, at, mark.get("note", ""), preview))  # type: ignore[arg-type]
        return sorted(items, key=lambda i: i.trashed_at, reverse=True)

    @locked
    def restore_trash(self, user_id: str, kind: TrashKind, item_id: str, *, name: str | None = None) -> list[str]:
        if kind == "category":
            return self._restore_category(user_id, item_id, name)
        if kind == "category_item":
            return self._restore_category_item(user_id, item_id)
        safe_id(item_id, f"{kind} id")
        trash = self._trash_dir(user_id, kind)
        if not (trash / f"{item_id}.json").exists():
            raise ValueError(f"휴지통에 {kind} {item_id}가 없다")
        names = [item_id] + ([p.stem for p in sorted(trash.glob("*.json")) if (read_json(p).get("_trash") or {}).get("with") == item_id]
                             if kind == "idea" else [])
        layout = self._layout(user_id)
        known = self._known(user_id, layout)
        with self._db:
            for name in names:
                data = {k: v for k, v in read_json(trash / f"{name}.json").items() if k != "_trash"}
                if data.get("floor") not in known:  # 층이 없거나 그사이 사라진 층이면 그 종류가 꽂힌 첫 층으로
                    data["floor"] = layout.fallback("ideas" if kind == "idea" else "styles")
                write_json(self._shelf_dir(user_id, kind) / f"{name}.json", data)
                (trash / f"{name}.json").unlink()
                if kind == "idea":
                    self._index_idea(user_id, Idea(**data))
                else:
                    self._index_style(user_id, StyleEntry(**data))
        return names

    def _reindex_shelf(self, user_id: str) -> None:
        """층이 없거나 모르는 층(휴지통으로 간 작업물)이면 배치에서 정한 층으로 색인한다(파일은 그대로, #93)."""
        layout = self._layout(user_id)
        known = self._known(user_id, layout)

        def floor(data: dict[str, Any], kind: str) -> str:
            return data["floor"] if data.get("floor") in known else layout.fallback(kind)

        for bib in sorted(self._melchior_dir(user_id).glob("*/bib.json")):
            self._index_ref(user_id, bib.parent, floor(read_json(bib), "refs"))
        for path in sorted(self._casper_dir(user_id).glob("*.json")):
            data = read_json(path)
            self._index_idea(user_id, Idea(**{**data, "floor": floor(data, "ideas")}))
        for path in sorted(self._balthasar_dir(user_id).glob("*.json")):
            data = read_json(path)
            self._index_style(user_id, StyleEntry(**{**data, "floor": floor(data, "styles")}))

    # ---- 검색 청크 -------------------------------------------------------------------

    def _replace_chunks(
        self, user_id: str, owner_type: str, owner_id: str, lane: Lane, texts: list[str], fts_extra: str = ""
    ) -> None:
        """fts_extra: 키워드 색인에만 더하는 글(임베딩 대상인 chunks.text에는 넣지 않는다). 문체 표본의 work(출전)."""
        old = [
            r[0]
            for r in self._db.execute(
                "SELECT id FROM chunks WHERE user_id = ? AND owner_type = ? AND owner_id = ? AND lane = ?",
                (user_id, owner_type, owner_id, lane),
            )
        ]
        if old:
            marks = ",".join("?" * len(old))
            self._db.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", old)
            self._db.execute(f"DELETE FROM chunks WHERE id IN ({marks})", old)
        for text in texts:
            chunk_id = self._db.execute(
                "INSERT INTO chunks (user_id, owner_type, owner_id, lane, text) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (user_id, owner_type, owner_id, lane, text),
            ).fetchone()[0]
            tokens = index_text(f"{text}\n{fts_extra}" if fts_extra else text)
            self._db.execute("INSERT INTO chunks_fts (rowid, tokens) VALUES (?, ?)", (chunk_id, tokens))

    def _drop_chunks(self, user_id: str, owner_type: str, owner_id: str) -> None:
        """그 항목의 청크를 레인과 관계없이 모두 뺀다(휴지통)."""
        old = [r[0] for r in self._db.execute(
            "SELECT id FROM chunks WHERE user_id = ? AND owner_type = ? AND owner_id = ?", (user_id, owner_type, owner_id))]
        if old:
            marks = ",".join("?" * len(old))
            self._db.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", old)
            self._db.execute(f"DELETE FROM chunks WHERE id IN ({marks})", old)

    @locked
    def search_substring(self, user_id: str, lanes: list[Lane], needle: str, limit: int) -> list[Chunk]:
        marks = ",".join("?" * len(lanes))
        rows = self._db.execute(
            f"SELECT id, owner_type, owner_id, lane, text FROM chunks "
            f"WHERE user_id = ? AND lane IN ({marks}) AND instr(lower(text), lower(?)) > 0 ORDER BY id DESC LIMIT ?",
            (user_id, *lanes, needle, limit),
        )
        return [Chunk(r["id"], r["owner_type"], r["owner_id"], r["lane"], r["text"]) for r in rows]

    @locked
    def search_fts(self, user_id: str, lanes: list[Lane], match: str, limit: int) -> list[Chunk]:
        marks = ",".join("?" * len(lanes))
        rows = self._db.execute(
            f"""
            SELECT c.id, c.owner_type, c.owner_id, c.lane, c.text, bm25(chunks_fts) AS rank
              FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
             WHERE chunks_fts MATCH ? AND c.user_id = ? AND c.lane IN ({marks})
             ORDER BY rank LIMIT ?
            """,
            (match, user_id, *lanes, limit),
        )
        return [Chunk(r["id"], r["owner_type"], r["owner_id"], r["lane"], r["text"], -r["rank"]) for r in rows]

    @locked
    def search_vector(self, user_id: str, lanes: list[Lane], vector: list[float], limit: int) -> list[Chunk]:
        marks = ",".join("?" * len(lanes))
        rows = self._db.execute(
            f"SELECT id, owner_type, owner_id, lane, text, embedding FROM chunks "
            f"WHERE user_id = ? AND lane IN ({marks}) AND embedding IS NOT NULL",
            (user_id, *lanes),
        ).fetchall()
        query = np.asarray(vector, dtype=np.float32)
        rows = [r for r in rows if len(r["embedding"]) == query.nbytes]
        if not rows or not query.any():
            return []
        matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32).reshape(len(rows), -1)
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
        scores = (matrix @ query) / np.where(norms == 0, 1, norms)
        top = np.argsort(-scores)[:limit]
        return [
            Chunk(rows[i]["id"], rows[i]["owner_type"], rows[i]["owner_id"], rows[i]["lane"], rows[i]["text"],
                  float(scores[i]))
            for i in top
        ]

    @locked
    def chunks_missing_embedding(self, user_id: str, limit: int = 256) -> list[Chunk]:
        skip = ",".join("?" * len(WEB_ONLY_LANES))
        rows = self._db.execute(
            "SELECT id, owner_type, owner_id, lane, text FROM chunks WHERE user_id = ? AND embedding IS NULL "
            f"AND lane NOT IN ({skip}) ORDER BY id LIMIT ?",
            (user_id, *WEB_ONLY_LANES, limit),
        )
        return [Chunk(r["id"], r["owner_type"], r["owner_id"], r["lane"], r["text"]) for r in rows]

    @locked
    def set_embeddings(self, user_id: str, vectors: dict[int, list[float]]) -> None:
        with self._db:
            self._db.executemany(
                "UPDATE chunks SET embedding = ? WHERE id = ? AND user_id = ?",
                [(np.asarray(v, dtype=np.float32).tobytes(), cid, user_id) for cid, v in vectors.items()],
            )


def bib_text(record: dict[str, Any]) -> str:
    """문헌 서지를 한 덩어리 글로(웹 책장 검색 전용 레인 ref_bib): key, 저자, 연도, 제목, 실린 곳, 한글 표기."""
    bib = record.get("bib") or {}
    parts = [record.get("key", ""), *(str(v) for v in bib.values() if isinstance(v, (str, int))), *record.get("aliases", [])]
    return "\n".join(p for p in dict.fromkeys(parts) if p)


def _style(r: sqlite3.Row) -> StyleEntry:
    return StyleEntry(
        id=r["id"], passage=r["passage"], reason=r["reason"], tags=json.loads(r["tags"]), work=r["work"],
        created_at=r["created_at"], tags_by=r["tags_by"], floor=r["floor"],
    )


def _idea(r: sqlite3.Row) -> Idea:
    return Idea(
        id=r["id"], text=r["text"], kind=r["kind"], author=r["author"], origin=r["origin"], parent_id=r["parent_id"],
        created_at=r["created_at"], title=r["title"], title_by=r["title_by"], edited_at=r["edited_at"], edited_by=r["edited_by"],
        floor=r["floor"],
    )


def _ref(r: sqlite3.Row) -> Ref:
    bib: dict[str, Any] = json.loads(r["bib"])
    return Ref(
        key=r["key"],
        status=r["status"],
        bib=bib,
        aliases=tuple(json.loads(r["aliases"])),
        has_fulltext=bool(r["has_fulltext"]),
        file_path=r["file_path"],
        created_at=r["created_at"],
        floor=r["floor"],
        updated_at=r["updated_at"] or r["created_at"],
    )
