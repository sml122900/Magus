"""책(#92 '저자가 만든 카테고리' → #96 모든 책)과 책장 설정 저장. LocalStore에 섞어 쓰는 믹스인이다.

#96부터 종류(생각·문체·문헌·모음 책)가 없다. 올린 문서가 든 책(가운데 노드)과 문서 책 말고는 모든 책이 여기의 '카테고리'이고,
글(항목)이 쌓인다. 옛 생각·문체는 이전으로 이 글이 됐다. 문헌(서지·원문 확인)은 Ref로 저장되고 refs.book으로 이 책에 함께 보인다.

원본(사람이 읽는 json, 모두 schema_version을 단다):
  data/users/<user_id>/shelf/categories/<카테고리 id>/category.json
  data/users/<user_id>/shelf/categories/<카테고리 id>/items/<항목 id>.json
  data/users/<user_id>/shelf/settings.json                       # 기본 카테고리 책 색, 내 색, 제목 기본값
휴지통(지우지 않고 옮긴다, "_trash"를 덧붙인다):
  data/users/<user_id>/trash/shelf/categories/<카테고리 id>/       # 카테고리 통째(항목 포함)
  data/users/<user_id>/trash/shelf/category-items/<카테고리 id>/<항목 id>.json
  data/users/<user_id>/trash/shelf/category-items/<카테고리 id>/files/<항목 id>/   # 그 글의 첨부(#97)
인덱스: categories·category_items 행과 검색 청크(레인 category, owner_id "<카테고리 id>/<항목 id>").
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from magus.category.rules import (
    DEFAULT_COLORS, HEX, ITEM_SCHEMA, MAX_MY_COLORS, SCHEMA_VERSION, TITLE_MODES, name_key,
)
from magus.contexts import from_record, to_record
from magus.floors import COMMON
from magus.ids import new_id, safe_id, utcnow
from magus.store.base import Category, CategoryItem, Context, EditConflict, Passage, ShelfSettings, edit_stamp
from magus.store.fileio import locked, read_json, write_json
from magus.textindex import chunk_text


class CategoryMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock

    # LocalStore·ShelfMixin이 구현한다(껍데기 메서드는 MRO에서 진짜를 가릴 수 있어 주석만 둔다)
    _user_dir: Callable[[str], Path]
    _replace_chunks: Callable[..., None]
    _guard: Callable[..., object]  # LocalStore: 파일 하나 색인, 실패하면 그것만 건너뜀(2026-10-09)
    _drop_chunks: Callable[[str, str, str], None]
    _layout: Callable[[str], Any]  # FloorMixin
    _known: Callable[[str, Any], set[str]]
    _check_floor: Callable[[str, Any, str], str]
    _move_item_files: Callable[..., None]  # AttachmentMixin(#97: 글의 첨부도 함께 휴지통으로)

    def _categories_dir(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "categories"

    def _category_dir(self, user_id: str, category_id: str) -> Path:
        return self._categories_dir(user_id) / safe_id(category_id, "category id")

    # ---- 카테고리 ---------------------------------------------------------------------------

    @locked
    def list_categories(self, user_id: str, *, floors: Iterable[str] | None = None) -> list[Category]:
        where, values = "", []
        if floors is not None:
            values = list(dict.fromkeys(floors))
            where = f" AND c.floor IN ({','.join('?' * len(values))})" if values else " AND 0"
        rows = self._db.execute(f"{_COUNTED} WHERE c.user_id = ?{where} ORDER BY c.created_at, c.id", (user_id, *values))
        return [_category(r) for r in rows]

    @locked
    def get_category(self, user_id: str, category_id: str) -> Category | None:
        row = self._db.execute(f"{_COUNTED} WHERE c.user_id = ? AND c.id = ?", (user_id, category_id)).fetchone()
        return _category(row) if row else None

    @locked
    def create_category(self, user_id: str, name: str, template: str, color: str, fields: tuple[str, ...],
                        floor: str | None = None, node: str | None = None, *, contexts: tuple[Context, ...] = (),
                        category_id: str | None = None, created_at: str | None = None) -> Category:
        """node: 꽂을 노드(#95). 없으면 이름이 같은 노드, 그것도 없으면 이름이 같은 새 노드(가운데와 이음).
        category_id·created_at은 이전(#96: 옛 기본 책을 책으로)만 준다."""
        if not HEX.fullmatch(color):
            raise ValueError(f"색은 #RRGGBB: {color!r}")
        floor = self._check_floor(user_id, self._layout(user_id), floor or COMMON)
        self.ensure_maps(user_id)  # type: ignore[attr-defined]  # 지도를 먼저 적고(이 책 없이), 만든 뒤 그 지도에 꽂는다
        if self._db.execute("SELECT 1 FROM categories WHERE user_id = ? AND floor = ? AND name_key = ?",
                            (user_id, floor, name_key(name))).fetchone():
            raise ValueError(f"'{name}' 책이 이미 있다")
        now = utcnow()
        made = created_at or now
        category = Category(safe_id(category_id, "category id") if category_id else new_id(), name, template, color.lower(),
                            tuple(fields), made, made, floor=floor, contexts=tuple(contexts))
        if (self._category_dir(user_id, category.id) / "category.json").exists():
            raise ValueError(f"책 {category.id}가 이미 있다")
        write_json(self._category_dir(user_id, category.id) / "category.json", _category_record(category))
        with self._db:
            self._index_category(user_id, category)
        self._persist_map(user_id, floor, {category.id: node} if node else None)  # type: ignore[attr-defined]
        return category

    @locked
    def update_category(self, user_id: str, category_id: str, *, name: str | None = None, color: str | None = None) -> Category:
        current = self.get_category(user_id, category_id)
        if current is None:
            raise ValueError(f"카테고리 {category_id}가 없다")
        if color is not None and not HEX.fullmatch(color):
            raise ValueError(f"색은 #RRGGBB: {color!r}")
        if name is not None and name_key(name) != name_key(current.name):
            clash = self._db.execute("SELECT name FROM categories WHERE user_id = ? AND floor = ? AND name_key = ? AND id != ?",
                                     (user_id, current.floor, name_key(name), category_id)).fetchone()
            if clash:
                raise ValueError(f"'{clash[0]}' 책이 이미 있다")
        changed = replace(current, name=name or current.name, color=(color or current.color).lower(), updated_at=utcnow())
        path = self._category_dir(user_id, category_id) / "category.json"
        write_json(path, {**read_json(path), **_category_record(changed)})
        with self._db:
            self._index_category(user_id, changed)
        return replace(changed, items=current.items, sources=current.sources, verified=current.verified)

    @locked
    def trash_category(self, user_id: str, category_id: str, note: str) -> Category | None:
        """책을 통째로 휴지통에. 문헌·참고문헌 항목이 든 책은 옮기지 않는다(ValueError: 인용 점검이 보는 기록이라)."""
        current = self.get_category(user_id, category_id)
        if current is None:
            return None
        if current.sources:
            raise ValueError(f"「{current.name}」에는 문헌·참고문헌 항목이 {current.sources}편 있어 휴지통으로 옮기지 않는다")
        src = self._category_dir(user_id, category_id)
        target = self._user_dir(user_id) / "trash" / "shelf" / "categories" / category_id
        if target.exists():  # 같은 id가 휴지통에 이미 있으면(되살린 뒤 다시 옮김) 옛것을 시각 이름으로 비켜 둔다
            target.rename(target.with_name(f"{category_id}-{utcnow().replace(':', '').replace('.', '')}"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        record = read_json(target / "category.json")
        write_json(target / "category.json", {**record, "_trash": {"at": utcnow(), "note": note}})
        with self._db:
            for item in self._db.execute("SELECT id FROM category_items WHERE user_id = ? AND category_id = ?",
                                         (user_id, category_id)).fetchall():
                self._drop_chunks(user_id, "category", f"{category_id}/{item[0]}")
            self._db.execute("DELETE FROM category_items WHERE user_id = ? AND category_id = ?", (user_id, category_id))
            self._db.execute("DELETE FROM categories WHERE user_id = ? AND id = ?", (user_id, category_id))
        return current

    def _restore_category(self, user_id: str, category_id: str, name: str | None) -> list[str]:
        """휴지통의 카테고리를 제자리로. 같은 이름이 이미 있으면 ValueError(name으로 새 이름)."""
        safe_id(category_id, "category id")
        src = self._user_dir(user_id) / "trash" / "shelf" / "categories" / category_id
        if not (src / "category.json").exists():
            raise ValueError(f"휴지통에 category {category_id}가 없다")
        record = {k: v for k, v in read_json(src / "category.json").items() if k != "_trash"}
        record["name"] = name or record["name"]
        if record.get("floor") not in self._known(user_id, self._layout(user_id)):
            record["floor"] = COMMON  # 층이 없거나 그사이 사라진 층이면 공용으로
        clash = self._db.execute("SELECT name FROM categories WHERE user_id = ? AND floor = ? AND name_key = ?",
                                 (user_id, record["floor"], name_key(record["name"]))).fetchone()
        if clash:
            raise ValueError(f"'{clash[0]}' 책이 이미 있어 되살리지 못했다. --name으로 새 이름을 준다")
        dst = self._category_dir(user_id, category_id)
        if dst.exists():
            raise ValueError(f"카테고리 {category_id} 폴더가 이미 있다")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        write_json(dst / "category.json", record)
        with self._db:
            self._reindex_category(user_id, dst, {record["floor"]})
        return [category_id]

    # ---- 항목 -------------------------------------------------------------------------------

    @locked
    def put_category_item(self, user_id: str, item: CategoryItem) -> CategoryItem:
        safe_id(item.id, "item id")
        cdir = self._category_dir(user_id, item.category_id)
        if not (cdir / "category.json").exists():
            raise ValueError(f"카테고리 {item.category_id}가 없다")
        path = cdir / "items" / f"{item.id}.json"
        now = utcnow()
        old = read_json(path) if path.exists() else {}
        item = replace(item, created_at=old.get("created_at") or item.created_at or now, updated_at=now)
        # 이 코드가 모르는 칸(앞으로 더할 표시 등)은 그대로 둔다. 고쳐 저장해도 파일에 있던 것이 사라지지 않게(2026-10-09 글 고치기)
        keep = {k: v for k, v in old.items() if k not in _ITEM_KEYS}
        write_json(path, {**_item_record(item), **keep})
        with self._db:
            self._index_item(user_id, item)
        return item

    @locked
    def patch_category_item(self, user_id: str, category_id: str, item_id: str, changes: dict[str, Any], *,
                            touch: bool = True, if_updated_at: str | None = None) -> CategoryItem:
        """글 파일에서 준 칸만 바꾼다(2026-10-09 웹의 글 고치기·스크랩). 나머지 칸(누가·이유·위치·쓸 부분·태그·칸·장·응답 관계 등)은
        파일에서 바이트까지 그대로 둔다. 값이 None이면 그 칸을 뺀다(제목·제목 지은 사람은 null로 남긴다: 원래 늘 있는 칸).
        touch=False면 updated_at도 그대로(스크랩은 글을 고친 것이 아니다).
        if_updated_at: 고치기 시작할 때 본 '마지막 저장 시각'. 그 뒤에 다른 저장이 있었으면 EditConflict(덮어쓰지 않는다)."""
        path = self._category_dir(user_id, category_id) / "items" / f"{safe_id(item_id, 'item id')}.json"
        if not path.exists():
            raise ValueError(f"글 {category_id}/{item_id}가 없다")
        data = read_json(path)
        if if_updated_at is not None and edit_stamp(data) != if_updated_at:
            raise EditConflict(f"글 {category_id}/{item_id}가 그사이 저장됐다")
        for key, value in changes.items():
            if value is None and key not in ("title", "title_by"):
                data.pop(key, None)
            else:
                data[key] = value
        if touch:
            data["updated_at"] = utcnow()
        write_json(path, data)
        item = _item_from_record(category_id, data)
        with self._db:
            self._index_item(user_id, item)
        return item

    @locked
    def list_category_items(self, user_id: str, category_id: str | None = None) -> list[CategoryItem]:
        sql, args = "SELECT * FROM category_items WHERE user_id = ?", [user_id]
        if category_id is not None:
            sql, args = sql + " AND category_id = ?", [*args, category_id]
        return [_item(r) for r in self._db.execute(sql + " ORDER BY id", args)]

    @locked
    def get_category_item(self, user_id: str, category_id: str, item_id: str) -> CategoryItem | None:
        row = self._db.execute("SELECT * FROM category_items WHERE user_id = ? AND category_id = ? AND id = ?",
                               (user_id, category_id, item_id)).fetchone()
        return _item(row) if row else None

    @locked
    def trashed_item_project(self, user_id: str, category_id: str, item_id: str) -> str | None:
        """휴지통에 있는 글이면 그 책의 프로젝트(휴지통 화면 주소에 쓴다). 글만 옮겼든 책·노드째 옮겼든. 휴지통에 없으면 None."""
        try:
            safe_id(category_id, "category id")
            safe_id(item_id, "item id")
        except ValueError:
            return None
        trash = self._user_dir(user_id) / "trash" / "shelf"
        alone = trash / "category-items" / category_id / f"{item_id}.json"
        with_book = trash / "categories" / category_id / "items" / f"{item_id}.json"
        if not alone.exists() and not with_book.exists():
            return None
        for meta in (self._category_dir(user_id, category_id) / "category.json", trash / "categories" / category_id / "category.json"):
            if meta.exists():
                return str(read_json(meta).get("floor") or COMMON)
        return COMMON

    @locked
    def trash_category_item(self, user_id: str, category_id: str, item_id: str, note: str) -> CategoryItem | None:
        """글 하나를 휴지통에. 이 글에 응답한 글(같은 책, parent_id)도 함께 옮긴다(옛 생각 휴지통 #88과 같다)."""
        moved = self.trash_item_with_replies(user_id, category_id, item_id, note)
        return moved[0] if moved else None

    @locked
    def trash_item_with_replies(self, user_id: str, category_id: str, item_id: str, note: str) -> list[CategoryItem]:
        """[그 글, 함께 옮긴 응답 글…]. 없으면 []."""
        safe_id(item_id, "item id")
        src = self._category_dir(user_id, category_id) / "items" / f"{item_id}.json"
        if not src.exists():
            return []
        replies = [r[0] for r in self._db.execute(
            "SELECT id FROM category_items WHERE user_id = ? AND category_id = ? AND parent_id = ? ORDER BY id",
            (user_id, category_id, item_id))]
        at, out = utcnow(), []
        for one, with_id in [(item_id, None), *((r, item_id) for r in replies)]:
            path = self._category_dir(user_id, category_id) / "items" / f"{one}.json"
            if not path.exists():
                continue
            data = read_json(path)
            target = self._user_dir(user_id) / "trash" / "shelf" / "category-items" / category_id / f"{one}.json"
            mark = {"at": at, "note": note, **({"with": with_id} if with_id else {})}
            write_json(target, {**data, "_trash": mark})  # 먼저 쓰고 지운다
            path.unlink()
            self._move_item_files(user_id, category_id, one, to_trash=True)
            with self._db:
                self._db.execute("DELETE FROM category_items WHERE user_id = ? AND category_id = ? AND id = ?",
                                 (user_id, category_id, one))
                self._drop_chunks(user_id, "category", f"{category_id}/{one}")
            out.append(_item_from_record(category_id, data))
        return out

    def _restore_category_item(self, user_id: str, ref: str) -> list[str]:
        """휴지통의 글을 제자리로. 함께 옮겨진 응답 글(_trash.with)도 함께 되살린다."""
        category_id, _, item_id = ref.partition("/")
        safe_id(category_id, "category id")
        safe_id(item_id, "item id")
        trash = self._user_dir(user_id) / "trash" / "shelf" / "category-items" / category_id
        if not (trash / f"{item_id}.json").exists():
            raise ValueError(f"휴지통에 category_item {ref}가 없다")
        if not (self._category_dir(user_id, category_id) / "category.json").exists():
            raise ValueError(f"책 {category_id}가 없다(책을 먼저 되살린다)")
        names = [item_id] + [p.stem for p in sorted(trash.glob("*.json"))
                             if (read_json(p).get("_trash") or {}).get("with") == item_id]
        for name in names:
            src = trash / f"{name}.json"
            data = {k: v for k, v in read_json(src).items() if k != "_trash"}
            write_json(self._category_dir(user_id, category_id) / "items" / f"{name}.json", data)
            src.unlink()
            self._move_item_files(user_id, category_id, name, to_trash=False)
            with self._db:
                self._index_item(user_id, _item_from_record(category_id, data))
        return [f"{category_id}/{n}" for n in names]

    def _trashed_categories(self, user_id: str) -> list[tuple[str, str, dict[str, Any], str]]:
        """(kind, id, 표시 미리보기용 레코드, 시각) — list_trash가 쓴다."""
        out = []
        root = self._user_dir(user_id) / "trash" / "shelf"
        for path in sorted((root / "categories").glob("*/category.json")):
            data = read_json(path)
            out.append(("category", path.parent.name, data, str((data.get("_trash") or {}).get("at", ""))))
        for path in sorted((root / "category-items").glob("*/*.json")):
            data = read_json(path)
            out.append(("category_item", f"{path.parent.name}/{path.stem}", data, str((data.get("_trash") or {}).get("at", ""))))
        return out

    # ---- 책장 설정 ---------------------------------------------------------------------------

    def _settings_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "settings.json"

    @locked
    def get_shelf_settings(self, user_id: str) -> ShelfSettings:
        path = self._settings_path(user_id)
        data = read_json(path) if path.exists() else {}
        return _settings(data)

    @locked
    def save_shelf_settings(self, user_id: str, settings: ShelfSettings) -> ShelfSettings:
        clean = _settings({"colors": settings.colors, "my_colors": list(settings.my_colors), "title_default": settings.title_default})
        write_json(self._settings_path(user_id), {
            "schema_version": SCHEMA_VERSION,
            "colors": clean.colors,
            "my_colors": list(clean.my_colors),
            "title_default": clean.title_default,
        })
        return clean

    # ---- 인덱스 ------------------------------------------------------------------------------

    def _index_category(self, user_id: str, c: Category) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO categories (id, user_id, name, name_key, template, color, fields, schema_version, created_at, updated_at,"
            " floor, contexts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (c.id, user_id, c.name, name_key(c.name), c.template, c.color, json.dumps(list(c.fields), ensure_ascii=False),
             SCHEMA_VERSION, c.created_at, c.updated_at, c.floor, json.dumps(to_record(c.contexts), ensure_ascii=False)),
        )

    def _index_item(self, user_id: str, item: CategoryItem) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO category_items (id, user_id, category_id, title, title_by, content, fields, author, tags, chapters,"
            " schema_version, created_at, updated_at, edited_at, edited_by, reason, location, passages, parent_id, origin, kind, tags_by,"
            " scrap) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, user_id, item.category_id, item.title, item.title_by, item.content,
             json.dumps(item.fields, ensure_ascii=False), item.author, json.dumps(list(item.tags), ensure_ascii=False),
             json.dumps([list(c) for c in item.chapters]), ITEM_SCHEMA, item.created_at, item.updated_at, item.edited_at,
             item.edited_by, item.reason, item.where, json.dumps([_passage(p) for p in item.passages], ensure_ascii=False),
             item.parent_id, item.origin, item.kind, item.tags_by, int(item.scrap)),
        )
        # 글의 모든 칸을 찾는다(#96: 옛 문체는 이유·태그만 찾았지만, 이제 무엇을 볼지는 컨텍스트가 정한다). 첨부 파일 이름도(2026-10-09)
        names = [a.name for a in self.list_attachments(user_id, f"{item.category_id}/{item.id}")]  # type: ignore[attr-defined]
        text = "\n".join([item.title or "", item.content, item.reason or "", item.where or "",
                          *(p.text for p in item.passages), *(f"{k}: {v}" for k, v in item.fields.items() if v), " ".join(item.tags),
                          *(["첨부: " + ", ".join(names)] if names else [])])
        self._replace_chunks(user_id, "category", f"{item.category_id}/{item.id}", "category", chunk_text(text.strip()))
        found = self._attachment_texts(user_id, f"{item.category_id}/{item.id}")  # type: ignore[attr-defined]  # 첨부 글자(#100)
        self._replace_chunks(user_id, "category", f"{item.category_id}/{item.id}", "attach_text", [c for _, c in found],
                             parts=[a for a, _ in found])

    def _attachments_changed(self, user_id: str, owner: str) -> None:
        """첨부가 늘거나 줄면 그 글(또는 문헌 글)의 색인을 파일에서 다시 만든다(첨부 이름을 찾게, 2026-10-09)."""
        if owner.startswith("ref:"):
            rdir = self._melchior_dir(user_id) / owner[4:]  # type: ignore[attr-defined]
            if (rdir / "bib.json").exists():
                with self._db:
                    self._index_ref(user_id, rdir)  # type: ignore[attr-defined]
            return
        book, _, item = owner.partition("/")
        path = self._category_dir(user_id, book) / "items" / f"{item}.json"
        if path.exists():
            with self._db:
                self._index_item(user_id, _item_from_record(book, read_json(path)))

    def _reindex_category(self, user_id: str, cdir: Path, known: set[str]) -> None:
        record = read_json(cdir / "category.json")
        category = _category_from_record(record, cdir.name)
        if category.floor not in known:  # 층이 없거나 모르는 층(휴지통으로 간 작업물)이면 공용(파일은 그대로, #93)
            category = replace(category, floor=COMMON)
        self._index_category(user_id, category)
        for path in sorted((cdir / "items").glob("*.json")):  # 깨진 글 파일은 그것만 건너뛴다(2026-10-09 점검 12-b)
            self._guard(path, lambda p=path: self._index_item(user_id, _item_from_record(category.id, read_json(p))))

    def _reindex_categories(self, user_id: str) -> None:
        known = self._known(user_id, self._layout(user_id))
        for path in sorted(self._categories_dir(user_id).glob("*/category.json")):
            self._guard(path, self._reindex_category, user_id, path.parent, known)


# ---- 파일 ↔ 객체 ----------------------------------------------------------------------------

_COUNTED = (
    "SELECT c.*, (SELECT COUNT(*) FROM category_items i WHERE i.user_id = c.user_id AND i.category_id = c.id) AS n, "
    "(SELECT COUNT(*) FROM refs r WHERE r.user_id = c.user_id AND r.book = c.id) AS s, "
    "(SELECT COUNT(*) FROM refs r WHERE r.user_id = c.user_id AND r.book = c.id AND r.status = 'verified') AS v "
    "FROM categories c"
)


def _category_record(c: Category) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "id": c.id, "name": c.name, "template": c.template, "color": c.color,
            "fields": list(c.fields), "created_at": c.created_at, "updated_at": c.updated_at, "floor": c.floor,
            **({"contexts": to_record(c.contexts)} if c.contexts else {})}


def _category_from_record(r: dict[str, Any], folder: str) -> Category:
    color = str(r.get("color") or "")
    return Category(folder, str(r.get("name") or folder), str(r.get("template") or "blank"),
                    color.lower() if HEX.fullmatch(color) else "#3b4652", tuple(str(f) for f in r.get("fields") or ()),
                    str(r.get("created_at") or ""), str(r.get("updated_at") or r.get("created_at") or ""),
                    floor=str(r.get("floor") or COMMON), contexts=from_record(r.get("contexts")))


def _passage(p: Passage) -> dict[str, str]:
    return {"text": p.text, **({"reason": p.reason} if p.reason else {}), **({"where": p.locator} if p.locator else {})}


def _passages(raw: Any) -> tuple[Passage, ...]:
    return tuple(Passage(str(p.get("text") or ""), str(p.get("reason") or ""), p.get("where") or p.get("locator") or None)
                 for p in (raw if isinstance(raw, list) else []) if isinstance(p, dict) and str(p.get("text") or "").strip())


# 글 파일에서 값이 없으면 쓰지 않는 칸(#96에서 더한 칸). 그래서 옛 칸만 쓴 글은 옛 형식 그대로다
_OPTIONAL = ("reason", "where", "parent_id", "origin", "kind", "tags_by")
# 이 코드가 글 파일에 쓰는 칸 전부. 이 밖의 칸은 put_category_item이 그대로 둔다
_ITEM_KEYS = frozenset(("schema_version", "id", "title", "title_by", "content", "fields", "author", "tags", "chapters",
                        "created_at", "updated_at", "edited_at", "edited_by", "passages", "scrap", *_OPTIONAL))


def item_changes(old: CategoryItem, new: CategoryItem, keys: set[str]) -> dict[str, Any]:
    """고치기(2026-10-09 점검 10-b): keys(파일의 칸 이름) 중 old와 new가 다른 칸만 파일 형식으로. patch_category_item에 그대로 준다.
    새 칸(이유·쓸 부분 등)이 생기면 형식 버전도 함께."""
    before, after = _item_record(old), _item_record(new)
    out = {k: after.get(k) for k in keys if after.get(k) != before.get(k)}
    if out and int(after.get("schema_version") or 0) > int(before.get("schema_version") or 0):
        out["schema_version"] = after["schema_version"]
    return out


def _item_record(item: CategoryItem) -> dict[str, Any]:
    extra: dict[str, Any] = {k: getattr(item, k) for k in _OPTIONAL if getattr(item, k)}
    if item.passages:
        extra["passages"] = [_passage(p) for p in item.passages]
    return {"schema_version": ITEM_SCHEMA if extra else SCHEMA_VERSION, "id": item.id, "title": item.title,
            "title_by": item.title_by, "content": item.content, "fields": item.fields, "author": item.author,
            "tags": list(item.tags), "chapters": [{"project": p, "number": n} for p, n in item.chapters],
            "created_at": item.created_at, "updated_at": item.updated_at,
            **({"edited_at": item.edited_at, "edited_by": item.edited_by} if item.edited_by else {}), **extra,
            **({"scrap": True} if item.scrap else {})}  # 스크랩은 표시 하나(형식 버전은 그대로, 옛 코드는 이 키를 읽지 않는다)


def _item_from_record(category_id: str, r: dict[str, Any]) -> CategoryItem:
    return CategoryItem(
        id=str(r["id"]), category_id=category_id, content=str(r.get("content") or ""),
        author="ai" if r.get("author") == "ai" else "me", title=r.get("title") or None,
        title_by=r.get("title_by") if r.get("title_by") in ("ai", "author") else None,
        fields={str(k): str(v) for k, v in (r.get("fields") or {}).items()}, tags=tuple(str(t) for t in r.get("tags") or ()),
        chapters=tuple((str(c["project"]), int(c["number"])) for c in r.get("chapters") or ()),
        created_at=str(r.get("created_at") or ""), updated_at=str(r.get("updated_at") or r.get("created_at") or ""),
        edited_at=r.get("edited_at") or None, edited_by=r.get("edited_by") if r.get("edited_by") in ("author", "ai") else None,
        reason=str(r["reason"]) if r.get("reason") else None, where=str(r["where"]) if r.get("where") else None,
        passages=_passages(r.get("passages")), parent_id=str(r["parent_id"]) if r.get("parent_id") else None,
        origin=str(r["origin"]) if r.get("origin") else None, kind=str(r["kind"]) if r.get("kind") else None,
        tags_by=r.get("tags_by") if r.get("tags_by") in ("ai", "author") else None, scrap=r.get("scrap") is True,
    )


def _category(r: sqlite3.Row) -> Category:
    return Category(r["id"], r["name"], r["template"], r["color"], tuple(json.loads(r["fields"])), r["created_at"],
                    r["updated_at"], r["n"], r["floor"], from_record(json.loads(r["contexts"] or "[]")), r["s"], r["v"])


def _item(r: sqlite3.Row) -> CategoryItem:
    return CategoryItem(
        id=r["id"], category_id=r["category_id"], content=r["content"], author=r["author"], title=r["title"],
        title_by=r["title_by"], fields=json.loads(r["fields"]), tags=tuple(json.loads(r["tags"])),
        chapters=tuple((str(p), int(n)) for p, n in json.loads(r["chapters"])), created_at=r["created_at"],
        updated_at=r["updated_at"], edited_at=r["edited_at"], edited_by=r["edited_by"], reason=r["reason"], where=r["location"],
        passages=_passages(json.loads(r["passages"] or "[]")), parent_id=r["parent_id"], origin=r["origin"], kind=r["kind"],
        tags_by=r["tags_by"], scrap=bool(r["scrap"]),
    )


def _settings(data: dict[str, Any]) -> ShelfSettings:
    """파일에서 읽은 값을 거른다: 색은 #rrggbb만, 기본 카테고리 이름만, 내 색은 최대 12개, 제목 기본값은 셋 중 하나."""
    colors = {k: str(v).lower() for k, v in (data.get("colors") or {}).items()
              if k in DEFAULT_COLORS and isinstance(v, str) and HEX.fullmatch(v)}
    mine = [str(v).lower() for v in data.get("my_colors") or () if isinstance(v, str) and HEX.fullmatch(v)]
    mode = data.get("title_default") if data.get("title_default") in TITLE_MODES else "ask"
    return ShelfSettings(colors, tuple(dict.fromkeys(mine))[:MAX_MY_COLORS], mode)
