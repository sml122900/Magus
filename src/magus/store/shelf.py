"""문헌(사람마다 key 하나) 저장과 검색 청크. LocalStore에 섞어 쓰는 믹스인이다.

원본: data/users/<user_id>/shelf/melchior/<key>/{bib.json, passages.json, full.txt}
  bib.json의 "book"은 그 문헌이 글로 보이는 책(카테고리 id, #96), "floor"는 그 책의 프로젝트다.
#96 전의 생각(shelf/casper)·문체(shelf/balthasar)는 이전(magus maps apply)으로 책의 글이 됐다. 그 옛 파일은 magus.book_migrate만 읽는다.
인덱스: refs·ref_passages 행과, 검색용 chunks·chunks_fts.
청크는 원본에서 언제든 다시 만들 수 있다. 임베딩(BLOB)은 파생값이라 재생성 뒤에는 비어 있고,
임베딩 제공자가 설정돼 있으면 magus.search.embed_missing이 다시 채운다.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from magus.category.rules import DEFAULT_COLORS
from magus.contexts import DEFAULTS, LEGACY_CONTEXT, find_saved
from magus.floors import COMMON
from magus.ids import utcnow
from magus.store.base import WEB_ONLY_LANES, Chunk, Context, Lane, Passage, Ref, RefStatus, TrashItem, TrashKind
from magus.store.fileio import locked, read_json, read_text, write_json, write_text
from magus.store.floors import Layout
from magus.textindex import chunk_text, index_text

SOURCE_BOOK_NAME = "참고문헌"  # 문헌이 든 책이 없는 프로젝트에 참고문헌을 가져올 때 만드는 책(컨텍스트 「논문」, #96)


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
    def list_refs(self, user_id: str, status: RefStatus | None = None, *, floors: Iterable[str] | None = None,
                  book: str | None = None) -> list[Ref]:
        where, values = _in(floors)
        sql, args = f"SELECT * FROM refs WHERE user_id = ?{where}", [user_id, *values]
        if status:
            sql, args = sql + " AND status = ?", [*args, status]
        if book is not None:
            sql, args = sql + " AND book = ?", [*args, book]
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
        # 책(#96): 준 책 → 지금 책 → 준 프로젝트(없으면 「내 서재」)의 문헌 책(없으면 「참고문헌」을 만든다). 프로젝트는 그 책의 것
        book = next((b for b in (ref.book, old.get("book")) if isinstance(b, str) and self._book_floor_of(user_id, b)), None)
        if book is None:
            known = self._known(user_id, self._layout(user_id))
            target = (ref.floor if ref.floor in known else old.get("floor") if old.get("floor") in known
                      else self.default_project(user_id))
            book = self.source_book(user_id, target, create=True)
            assert book is not None
        floor = self._book_floor_of(user_id, book)
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
                "book": book,
                **({"moved": old["moved"]} if isinstance(old.get("moved"), dict) else {}),  # 공용으로 옮긴 기록은 그대로(#93-a)
                **({"scrap": True} if old.get("scrap") is True else {}),  # 스크랩(별표)은 저자의 표시라 그대로(set_scrap만 바꾼다)
            },
        )
        with self._db:
            self._index_ref(user_id, rdir)
        stored = self.get_ref(user_id, key)
        assert stored is not None
        return stored

    @locked
    def default_project(self, user_id: str) -> str:
        """프로젝트를 말하지 않았을 때 문헌이 갈 프로젝트: 프로젝트가 하나면 그것, 아니면 「내 서재」(옛 규칙과 같다, #93)."""
        works = sorted(self._known(user_id, self._layout(user_id)) - {COMMON})
        return works[0] if len(works) == 1 else COMMON

    def _book_floor_of(self, user_id: str, book: str) -> str | None:
        """책(카테고리 id)의 프로젝트. 없는 책이면 None."""
        row = self._db.execute("SELECT floor FROM categories WHERE user_id = ? AND id = ?", (user_id, book)).fetchone()
        return str(row[0]) if row else None

    @locked
    def source_book(self, user_id: str, floor: str, *, create: bool = False) -> str | None:
        """그 프로젝트에서 문헌·참고문헌 항목이 든 책(가장 많이 든 책, 같으면 먼저 만든 책).
        없고 create면 「참고문헌」 책(컨텍스트 「논문」)을 만든다(지도에는 이름이 같은 새 노드, 가운데와 이음)."""
        row = self._db.execute(
            "SELECT c.id FROM categories c JOIN refs r ON r.user_id = c.user_id AND r.book = c.id "
            "WHERE c.user_id = ? AND c.floor = ? GROUP BY c.id ORDER BY COUNT(*) DESC, c.created_at, c.id LIMIT 1",
            (user_id, floor)).fetchone()
        if row or not create:
            return str(row[0]) if row else None
        taken = {r[0] for r in self._db.execute("SELECT name_key FROM categories WHERE user_id = ? AND floor = ?", (user_id, floor))}
        name, n = SOURCE_BOOK_NAME, 2
        while name.replace(" ", "").lower() in taken:
            name, n = f"{SOURCE_BOOK_NAME} {n}", n + 1
        saved = find_saved(self.list_saved_contexts(user_id), "논문")  # type: ignore[attr-defined]
        paper = saved or next(c for c in DEFAULTS if c.id == LEGACY_CONTEXT["refs"])
        made = self.create_category(user_id, name, "blank", DEFAULT_COLORS["refs"], (), floor,  # type: ignore[attr-defined]
                                    contexts=(Context(paper.name, paper.text),))
        return str(made.id)

    @locked
    def set_ref_book(self, user_id: str, key: str, book: str, reason: str | None = None) -> Ref:
        """문헌 한 편을 다른 책으로(프로젝트도 그 책의 것). reason을 주면 옮긴 시각·원래 프로젝트·이유를 남긴다(#93-a)."""
        floor = self._book_floor_of(user_id, book)
        path = self._melchior_dir(user_id) / safe_ref_key(key) / "bib.json"
        if floor is None or not path.exists():
            raise ValueError(f"책 {book!r} 또는 문헌 {key!r}가 없다")
        data = read_json(path)
        before = data.get("floor")
        data.update({"book": book, "floor": floor, "updated_at": utcnow()})
        if reason:  # 저자가 알 수 있게 옮긴 시각·원래 프로젝트·이유를 남긴다(#93-a 더함)
            data["moved"] = {"at": utcnow(), "from": str(before or ""), "to": floor, "reason": reason}
        write_json(path, data)
        with self._db:
            self._index_ref(user_id, path.parent)
        found = self.get_ref(user_id, key)
        assert found is not None
        return found

    @locked
    def set_ref_status(self, user_id: str, key: str, status: str, via: str = "chat") -> Ref:
        """원문 확인 표시만 바꾼다(저자가 한 것: #97 웹 체크 → 2026-10-09부터 대화의 category_edit checked). 쓸 부분·전문·서지는 그대로.
        누가 언제 어디서 바꿨는지 bib.json "status_by"에 남긴다(옛 코드는 이 키를 읽지 않는다)."""
        if status not in ("verified", "unverified"):
            raise ValueError(f"status={status!r}")
        path = self._melchior_dir(user_id) / safe_ref_key(key) / "bib.json"
        if not path.exists():
            raise ValueError(f"문헌 {key!r}가 없다")
        data = read_json(path)
        if data.get("status") != status:
            data.update({"status": status, "updated_at": utcnow(), "status_by": {"by": "author", "at": utcnow(), "via": via}})
            write_json(path, data)
            with self._db:
                self._index_ref(user_id, path.parent)
        found = self.get_ref(user_id, key)
        assert found is not None
        return found

    @locked
    def add_passages(self, user_id: str, key: str, passages: list[Passage]) -> tuple[int, int]:
        """문헌 글에 쓸 부분을 더한다(#100). passages.json만 고치고(같은 대목은 한 번) bib.json·원문 확인 표시는 그대로. (더한 수, 모두)."""
        rdir = self._melchior_dir(user_id) / safe_ref_key(key)
        if not (rdir / "bib.json").exists():
            raise ValueError(f"문헌 {key!r}가 없다")
        old = self.get_passages(user_id, key)
        seen = {p.text.strip() for p in old}
        new = []
        for p in passages:
            if p.text.strip() and p.text.strip() not in seen:
                seen.add(p.text.strip())
                new.append(p)
        if new:
            write_json(rdir / "passages.json", [asdict(p) for p in [*old, *new]])
            with self._db:
                self._index_ref(user_id, rdir)
        return len(new), len(old) + len(new)

    @locked
    def set_scrap(self, user_id: str, owner: str, on: bool) -> bool:
        """스크랩(별표) 켜고 끄기(2026-10-09). 파일의 표시 하나("scrap": true, 끄면 키를 뺀다)만 바꾸고 고친 시각은 그대로 둔다."""
        if not owner.startswith("ref:"):
            book, _, item = owner.partition("/")
            return self.patch_category_item(user_id, book, item, {"scrap": True if on else None}, touch=False).scrap  # type: ignore[attr-defined]
        path = self._melchior_dir(user_id) / safe_ref_key(owner[4:]) / "bib.json"
        if not path.exists():
            raise ValueError(f"문헌 {owner[4:]!r}가 없다")
        data = read_json(path)
        if (data.get("scrap") is True) != on:
            if on:
                data["scrap"] = True
            else:
                data.pop("scrap", None)
            write_json(path, data)
            with self._db:
                self._index_ref(user_id, path.parent)
        return on

    @locked
    def set_ref_memo(self, user_id: str, key: str, memo: str) -> Ref:
        """문헌 글의 본문(메모, bib.memo)만 바꾼다(2026-10-09 웹의 글 고치기). 서지·쓸 부분·전문·원문 확인 표시와
        그 기록(status_by)·옮긴 기록은 파일에서 그대로다(put_ref는 bib.json을 다시 쓰므로 여기서는 쓰지 않는다)."""
        path = self._melchior_dir(user_id) / safe_ref_key(key) / "bib.json"
        if not path.exists():
            raise ValueError(f"문헌 {key!r}가 없다")
        data = read_json(path)
        bib = dict(data.get("bib") or {})
        if (bib.get("memo") or "") != memo:
            bib.pop("memo", None)
            data.update({"bib": {**bib, **({"memo": memo} if memo else {})}, "updated_at": utcnow()})
            write_json(path, data)
            with self._db:
                self._index_ref(user_id, path.parent)
        found = self.get_ref(user_id, key)
        assert found is not None
        return found

    def _index_ref(self, user_id: str, rdir: Path, floor: str | None = None) -> None:
        """floor: reindex가 배치에서 정해 준 프로젝트(파일에 없거나 모르는 프로젝트일 때). None이면 파일의 것."""
        record = read_json(rdir / "bib.json")
        full = read_text(rdir / "full.txt")
        passages = read_json(rdir / "passages.json") if (rdir / "passages.json").exists() else []
        ref_id = self._db.execute(
            """
            INSERT INTO refs (user_id, key, aliases, bib, status, has_fulltext, file_path, created_at, updated_at, floor, moved, book,
                              scrap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, key) DO UPDATE SET
                aliases = excluded.aliases, bib = excluded.bib, status = excluded.status,
                has_fulltext = excluded.has_fulltext, file_path = excluded.file_path, updated_at = excluded.updated_at,
                floor = excluded.floor, moved = excluded.moved, book = excluded.book, scrap = excluded.scrap
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
                json.dumps(record["moved"], ensure_ascii=False) if isinstance(record.get("moved"), dict) else None,
                str(record["book"]) if record.get("book") else None,
                int(record.get("scrap") is True),
            ),
        ).fetchone()[0]
        self._db.execute("DELETE FROM ref_passages WHERE ref_id = ?", (ref_id,))
        self._db.executemany(
            "INSERT INTO ref_passages (user_id, ref_id, text, reason, locator) VALUES (?, ?, ?, ?, ?)",
            [(user_id, ref_id, p["text"], p.get("reason", ""), p.get("locator")) for p in passages],
        )
        self._replace_chunks(user_id, "ref", record["key"], "ref_picked", [p["text"] for p in passages])
        self._replace_chunks(user_id, "ref", record["key"], "ref_full", chunk_text(full) if full.strip() else [])
        names = [a.name for a in self.list_attachments(user_id, f"ref:{record['key']}")]  # type: ignore[attr-defined]
        found = self._attachment_texts(user_id, f"ref:{record['key']}")  # type: ignore[attr-defined]  # 첨부 글자(#100)
        self._replace_chunks(user_id, "ref", record["key"], "attach_text", [c for _, c in found], parts=[a for a, _ in found])
        self._replace_chunks(user_id, "ref", record["key"], "ref_bib",  # 웹 책장 검색 전용. 첨부 파일 이름도(2026-10-09)
                             [bib_text(record) + ("\n첨부: " + ", ".join(names) if names else "")])

    @locked
    def list_trash(self, user_id: str) -> list[TrashItem]:
        items = []
        for kind, item_id, data, at in self._trashed_categories(user_id):  # 책 통째·글(#92, #96: 옛 생각·문체도 글)
            mark = data.get("_trash") or {}
            preview = (f"책 「{data.get('name', '')}」" if kind == "category"
                       else str(data.get("title") or data.get("content") or "")[:80])
            items.append(TrashItem(kind, item_id, at, mark.get("note", ""), preview, mark.get("with"),  # type: ignore[arg-type]
                                   title=bool(data.get("title"))))
        for ref, data in self._trashed_nodes(user_id):  # type: ignore[attr-defined]  # 지도의 노드(#95)
            mark = data.get("_trash") or {}
            books = len(data.get("books") or [])  # 책째 옮긴 노드(#97)면 책 수
            preview = "연결 노드" if data.get("link") else f"노드 「{data.get('name', '')}」" + (f" · 책 {books}권" if books else "")
            items.append(TrashItem("node", ref, mark.get("at", ""), mark.get("note", ""), preview))
        for owner, att, mark in self._trashed_attachments(user_id):  # type: ignore[attr-defined]  # 글에서 뺀 첨부(2026-10-09)
            items.append(TrashItem("attachment", f"{owner}/{att.id}", str(mark.get("at", "")), str(mark.get("note", "")), att.name,
                                   owner=owner))
        return sorted(items, key=lambda i: i.trashed_at, reverse=True)

    @locked
    def restore_trash(self, user_id: str, kind: TrashKind, item_id: str, *, name: str | None = None) -> list[str]:
        if kind == "category":
            return self._restore_category(user_id, item_id, name)
        if kind == "category_item":
            return self._restore_category_item(user_id, item_id)
        if kind == "node":
            return self._restore_node(user_id, item_id)  # type: ignore[attr-defined]
        if kind == "attachment":
            return self._restore_attachment(user_id, item_id)  # type: ignore[attr-defined]
        raise ValueError(f"휴지통 종류를 모른다: {kind!r}")

    def _reindex_shelf(self, user_id: str) -> None:
        """문헌. 프로젝트가 없거나 모르는 프로젝트(휴지통으로 간 작업물)면 배치에서 정한 프로젝트로 색인한다(파일은 그대로, #93)."""
        layout = self._layout(user_id)
        known = self._known(user_id, layout)
        for bib in sorted(self._melchior_dir(user_id).glob("*/bib.json")):
            data = read_json(bib)
            self._index_ref(user_id, bib.parent, data["floor"] if data.get("floor") in known else layout.fallback("refs"))

    # ---- 검색 청크 -------------------------------------------------------------------

    def _replace_chunks(
        self, user_id: str, owner_type: str, owner_id: str, lane: Lane, texts: list[str], fts_extra: str = "",
        parts: list[str] | None = None,
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
        for n, text in enumerate(texts):
            chunk_id = self._db.execute(
                "INSERT INTO chunks (user_id, owner_type, owner_id, lane, text, part) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (user_id, owner_type, owner_id, lane, text, parts[n] if parts else None),
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
        """글자 그대로 포함(대소문자 무시). 최근 글부터(글·문헌 글의 만든 시각, 그 밖은 뒤에)."""
        marks = ",".join("?" * len(lanes))
        rows = self._db.execute(
            f"""
            SELECT c.id, c.owner_type, c.owner_id, c.lane, c.text, c.part, COALESCE(i.created_at, r.created_at, '') AS at
              FROM chunks c
              LEFT JOIN category_items i ON c.owner_type = 'category' AND i.user_id = c.user_id
                   AND i.category_id = substr(c.owner_id, 1, instr(c.owner_id, '/') - 1)
                   AND i.id = substr(c.owner_id, instr(c.owner_id, '/') + 1)
              LEFT JOIN refs r ON c.owner_type = 'ref' AND r.user_id = c.user_id AND r.key = c.owner_id
             WHERE c.user_id = ? AND c.lane IN ({marks}) AND instr(lower(c.text), lower(?)) > 0
             ORDER BY at DESC, c.id DESC LIMIT ?
            """,
            (user_id, *lanes, needle, limit),
        )
        return [Chunk(r["id"], r["owner_type"], r["owner_id"], r["lane"], r["text"], part=r["part"]) for r in rows]

    @locked
    def search_fts(self, user_id: str, lanes: list[Lane], match: str, limit: int) -> list[Chunk]:
        marks = ",".join("?" * len(lanes))
        rows = self._db.execute(
            f"""
            SELECT c.id, c.owner_type, c.owner_id, c.lane, c.text, c.part, bm25(chunks_fts) AS rank
              FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
             WHERE chunks_fts MATCH ? AND c.user_id = ? AND c.lane IN ({marks})
             ORDER BY rank LIMIT ?
            """,
            (match, user_id, *lanes, limit),
        )
        return [Chunk(r["id"], r["owner_type"], r["owner_id"], r["lane"], r["text"], -r["rank"], r["part"]) for r in rows]

    @locked
    def search_vector(self, user_id: str, lanes: list[Lane], vector: list[float], limit: int) -> list[Chunk]:
        marks = ",".join("?" * len(lanes))
        rows = self._db.execute(
            f"SELECT id, owner_type, owner_id, lane, text, embedding, part FROM chunks "
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
                  float(scores[i]), rows[i]["part"])
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
        moved=json.loads(r["moved"]) if r["moved"] else None,
        book=r["book"],
        scrap=bool(r["scrap"]),
    )
