"""저자가 만든 카테고리(#92)와 책장 설정 저장. LocalStore에 섞어 쓰는 믹스인이다.

원본(사람이 읽는 json, 모두 schema_version을 단다):
  data/users/<user_id>/shelf/categories/<카테고리 id>/category.json
  data/users/<user_id>/shelf/categories/<카테고리 id>/items/<항목 id>.json
  data/users/<user_id>/shelf/settings.json                       # 기본 카테고리 책 색, 내 색, 제목 기본값
휴지통(지우지 않고 옮긴다, "_trash"를 덧붙인다):
  data/users/<user_id>/trash/shelf/categories/<카테고리 id>/       # 카테고리 통째(항목 포함)
  data/users/<user_id>/trash/shelf/category-items/<카테고리 id>/<항목 id>.json
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
    DEFAULT_COLORS, HEX, MAX_MY_COLORS, SCHEMA_VERSION, TITLE_MODES, name_key,
)
from magus.floors import COMMON
from magus.ids import new_id, safe_id, utcnow
from magus.store.base import Category, CategoryItem, ShelfSettings
from magus.store.fileio import locked, read_json, write_json
from magus.textindex import chunk_text


class CategoryMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock

    # LocalStore·ShelfMixin이 구현한다(껍데기 메서드는 MRO에서 진짜를 가릴 수 있어 주석만 둔다)
    _user_dir: Callable[[str], Path]
    _replace_chunks: Callable[..., None]
    _drop_chunks: Callable[[str, str, str], None]
    _layout: Callable[[str], Any]  # FloorMixin
    _known: Callable[[str, Any], set[str]]
    _check_floor: Callable[[str, Any, str], str]

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
        rows = self._db.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM category_items i WHERE i.user_id = c.user_id AND i.category_id = c.id) AS n "
            f"FROM categories c WHERE c.user_id = ?{where} ORDER BY c.created_at, c.id",
            (user_id, *values),
        )
        return [_category(r) for r in rows]

    @locked
    def get_category(self, user_id: str, category_id: str) -> Category | None:
        row = self._db.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM category_items i WHERE i.user_id = c.user_id AND i.category_id = c.id) AS n "
            "FROM categories c WHERE c.user_id = ? AND c.id = ?",
            (user_id, category_id),
        ).fetchone()
        return _category(row) if row else None

    @locked
    def create_category(self, user_id: str, name: str, template: str, color: str, fields: tuple[str, ...],
                        floor: str | None = None) -> Category:
        if not HEX.fullmatch(color):
            raise ValueError(f"색은 #RRGGBB: {color!r}")
        floor = self._check_floor(user_id, self._layout(user_id), floor or COMMON)
        if self._db.execute("SELECT 1 FROM categories WHERE user_id = ? AND floor = ? AND name_key = ?",
                            (user_id, floor, name_key(name))).fetchone():
            raise ValueError(f"'{name}' 카테고리가 이미 있다")
        now = utcnow()
        category = Category(new_id(), name, template, color.lower(), tuple(fields), now, now, floor=floor)
        write_json(self._category_dir(user_id, category.id) / "category.json", _category_record(category))
        with self._db:
            self._index_category(user_id, category)
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
                raise ValueError(f"'{clash[0]}' 카테고리가 이미 있다")
        changed = replace(current, name=name or current.name, color=(color or current.color).lower(), updated_at=utcnow())
        path = self._category_dir(user_id, category_id) / "category.json"
        write_json(path, {**read_json(path), **_category_record(changed)})
        with self._db:
            self._index_category(user_id, changed)
        return replace(changed, items=current.items)

    @locked
    def trash_category(self, user_id: str, category_id: str, note: str) -> Category | None:
        current = self.get_category(user_id, category_id)
        if current is None:
            return None
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
            raise ValueError(f"'{clash[0]}' 카테고리가 이미 있어 되살리지 못했다. --name으로 새 이름을 준다")
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
        created = read_json(path).get("created_at") if path.exists() else None
        item = replace(item, created_at=created or item.created_at or now, updated_at=now)
        write_json(path, _item_record(item))
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
    def trash_category_item(self, user_id: str, category_id: str, item_id: str, note: str) -> CategoryItem | None:
        safe_id(item_id, "item id")
        src = self._category_dir(user_id, category_id) / "items" / f"{item_id}.json"
        if not src.exists():
            return None
        data = read_json(src)
        target = self._user_dir(user_id) / "trash" / "shelf" / "category-items" / category_id / f"{item_id}.json"
        write_json(target, {**data, "_trash": {"at": utcnow(), "note": note}})  # 먼저 쓰고 지운다
        src.unlink()
        with self._db:
            self._db.execute("DELETE FROM category_items WHERE user_id = ? AND category_id = ? AND id = ?",
                             (user_id, category_id, item_id))
            self._drop_chunks(user_id, "category", f"{category_id}/{item_id}")
        return _item_from_record(category_id, data)

    def _restore_category_item(self, user_id: str, ref: str) -> list[str]:
        category_id, _, item_id = ref.partition("/")
        safe_id(category_id, "category id")
        safe_id(item_id, "item id")
        src = self._user_dir(user_id) / "trash" / "shelf" / "category-items" / category_id / f"{item_id}.json"
        if not src.exists():
            raise ValueError(f"휴지통에 category_item {ref}가 없다")
        if not (self._category_dir(user_id, category_id) / "category.json").exists():
            raise ValueError(f"카테고리 {category_id}가 없다(카테고리를 먼저 되살린다)")
        data = {k: v for k, v in read_json(src).items() if k != "_trash"}
        write_json(self._category_dir(user_id, category_id) / "items" / f"{item_id}.json", data)
        src.unlink()
        with self._db:
            self._index_item(user_id, _item_from_record(category_id, data))
        return [ref]

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
            " floor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (c.id, user_id, c.name, name_key(c.name), c.template, c.color, json.dumps(list(c.fields), ensure_ascii=False),
             SCHEMA_VERSION, c.created_at, c.updated_at, c.floor),
        )

    def _index_item(self, user_id: str, item: CategoryItem) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO category_items (id, user_id, category_id, title, title_by, content, fields, author, tags, chapters,"
            " schema_version, created_at, updated_at, edited_at, edited_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, user_id, item.category_id, item.title, item.title_by, item.content,
             json.dumps(item.fields, ensure_ascii=False), item.author, json.dumps(list(item.tags), ensure_ascii=False),
             json.dumps([list(c) for c in item.chapters]), SCHEMA_VERSION, item.created_at, item.updated_at, item.edited_at,
             item.edited_by),
        )
        text = "\n".join([item.title or "", item.content, *(f"{k}: {v}" for k, v in item.fields.items() if v), " ".join(item.tags)])
        self._replace_chunks(user_id, "category", f"{item.category_id}/{item.id}", "category", chunk_text(text.strip()))

    def _reindex_category(self, user_id: str, cdir: Path, known: set[str]) -> None:
        record = read_json(cdir / "category.json")
        category = _category_from_record(record, cdir.name)
        if category.floor not in known:  # 층이 없거나 모르는 층(휴지통으로 간 작업물)이면 공용(파일은 그대로, #93)
            category = replace(category, floor=COMMON)
        self._index_category(user_id, category)
        for path in sorted((cdir / "items").glob("*.json")):
            self._index_item(user_id, _item_from_record(category.id, read_json(path)))

    def _reindex_categories(self, user_id: str) -> None:
        known = self._known(user_id, self._layout(user_id))
        for path in sorted(self._categories_dir(user_id).glob("*/category.json")):
            self._reindex_category(user_id, path.parent, known)


# ---- 파일 ↔ 객체 ----------------------------------------------------------------------------

def _category_record(c: Category) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "id": c.id, "name": c.name, "template": c.template, "color": c.color,
            "fields": list(c.fields), "created_at": c.created_at, "updated_at": c.updated_at, "floor": c.floor}


def _category_from_record(r: dict[str, Any], folder: str) -> Category:
    color = str(r.get("color") or "")
    return Category(folder, str(r.get("name") or folder), str(r.get("template") or "blank"),
                    color.lower() if HEX.fullmatch(color) else "#3b4652", tuple(str(f) for f in r.get("fields") or ()),
                    str(r.get("created_at") or ""), str(r.get("updated_at") or r.get("created_at") or ""),
                    floor=str(r.get("floor") or COMMON))


def _item_record(item: CategoryItem) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "id": item.id, "title": item.title, "title_by": item.title_by,
            "content": item.content, "fields": item.fields, "author": item.author, "tags": list(item.tags),
            "chapters": [{"project": p, "number": n} for p, n in item.chapters],
            "created_at": item.created_at, "updated_at": item.updated_at,
            **({"edited_at": item.edited_at, "edited_by": item.edited_by} if item.edited_by else {})}


def _item_from_record(category_id: str, r: dict[str, Any]) -> CategoryItem:
    return CategoryItem(
        id=str(r["id"]), category_id=category_id, content=str(r.get("content") or ""),
        author="ai" if r.get("author") == "ai" else "me", title=r.get("title") or None,
        title_by=r.get("title_by") if r.get("title_by") in ("ai", "author") else None,
        fields={str(k): str(v) for k, v in (r.get("fields") or {}).items()}, tags=tuple(str(t) for t in r.get("tags") or ()),
        chapters=tuple((str(c["project"]), int(c["number"])) for c in r.get("chapters") or ()),
        created_at=str(r.get("created_at") or ""), updated_at=str(r.get("updated_at") or r.get("created_at") or ""),
        edited_at=r.get("edited_at") or None, edited_by=r.get("edited_by") if r.get("edited_by") in ("author", "ai") else None,
    )


def _category(r: sqlite3.Row) -> Category:
    return Category(r["id"], r["name"], r["template"], r["color"], tuple(json.loads(r["fields"])), r["created_at"],
                    r["updated_at"], r["n"], r["floor"])


def _item(r: sqlite3.Row) -> CategoryItem:
    return CategoryItem(
        id=r["id"], category_id=r["category_id"], content=r["content"], author=r["author"], title=r["title"],
        title_by=r["title_by"], fields=json.loads(r["fields"]), tags=tuple(json.loads(r["tags"])),
        chapters=tuple((str(p), int(n)) for p, n in json.loads(r["chapters"])), created_at=r["created_at"],
        updated_at=r["updated_at"], edited_at=r["edited_at"], edited_by=r["edited_by"],
    )


def _settings(data: dict[str, Any]) -> ShelfSettings:
    """파일에서 읽은 값을 거른다: 색은 #rrggbb만, 기본 카테고리 이름만, 내 색은 최대 12개, 제목 기본값은 셋 중 하나."""
    colors = {k: str(v).lower() for k, v in (data.get("colors") or {}).items()
              if k in DEFAULT_COLORS and isinstance(v, str) and HEX.fullmatch(v)}
    mine = [str(v).lower() for v in data.get("my_colors") or () if isinstance(v, str) and HEX.fullmatch(v)]
    mode = data.get("title_default") if data.get("title_default") in TITLE_MODES else "ask"
    return ShelfSettings(colors, tuple(dict.fromkeys(mine))[:MAX_MY_COLORS], mode)
