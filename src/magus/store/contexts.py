"""컨텍스트 저장(#96). LocalStore에 섞어 쓰는 믹스인이다.

원본(사람이 읽는 json):
  data/users/<user_id>/shelf/contexts.json    # 자주 쓰는 컨텍스트 {"schema_version": 1, "items": [{id, name, text, created_at, updated_at}]}
  책의 컨텍스트: 카테고리 category.json · 프로젝트 project.json(가운데 노드의 올린 문서가 든 책) · 문서 document.json의 "contexts"
  노드의 컨텍스트: 지도 파일(shelf/maps/<프로젝트>.json) 노드의 "contexts"(MapMixin.set_node_contexts)
contexts.json이 없으면 처음 제공하는 넷(magus.contexts.DEFAULTS)으로 보인다. 읽기는 아무것도 쓰지 않고, 처음 고칠 때 넷과 함께 적는다.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from magus.contexts import CONTEXTS_SCHEMA, DEFAULTS, MAX_SAVED, clean_context, clean_contexts, name_key, to_record
from magus.ids import new_id, utcnow
from magus.store.base import Context, SavedContext
from magus.store.fileio import locked, read_json, write_json


class ContextMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]
    _project_dir: Callable[[str, str], Path]

    def _contexts_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "shelf" / "contexts.json"

    @locked
    def list_saved_contexts(self, user_id: str) -> list[SavedContext]:
        path = self._contexts_path(user_id)
        if not path.exists():
            return list(DEFAULTS)
        out = []
        for item in (read_json(path).get("items") or []):
            if isinstance(item, dict) and str(item.get("text") or "").strip() and item.get("id"):
                out.append(SavedContext(str(item["id"]), " ".join(str(item.get("name") or "").split()), str(item["text"]).strip(),
                                        str(item.get("created_at") or ""), str(item.get("updated_at") or "")))
        return out

    def _write_saved(self, user_id: str, items: list[SavedContext]) -> None:
        write_json(self._contexts_path(user_id), {
            "schema_version": CONTEXTS_SCHEMA,
            "items": [{"id": c.id, "name": c.name, "text": c.text, "created_at": c.created_at, "updated_at": c.updated_at}
                      for c in items],
        })

    @locked
    def save_saved_context(self, user_id: str, context: SavedContext) -> SavedContext:
        clean = clean_context(context.name, context.text)
        if not clean.name:
            raise ValueError("자주 쓰는 컨텍스트에는 이름이 있어야 한다.")
        items = self.list_saved_contexts(user_id)
        if any(name_key(c.name) == name_key(clean.name) and c.id != context.id for c in items):
            raise ValueError(f"「{clean.name}」 컨텍스트가 이미 있다. 다른 이름을 짓는다.")
        now = utcnow()
        index = next((n for n, c in enumerate(items) if c.id == context.id), None) if context.id else None
        if index is None:
            if len(items) >= MAX_SAVED:
                raise ValueError(f"자주 쓰는 컨텍스트는 {MAX_SAVED}개까지다. 쓰지 않는 것을 지운 뒤 더한다.")
            saved = SavedContext("ctx-" + new_id(), clean.name, clean.text, now, now)
            items.append(saved)
        else:
            saved = replace(items[index], name=clean.name, text=clean.text, updated_at=now)
            items[index] = saved
        self._write_saved(user_id, items)
        return saved

    @locked
    def delete_saved_context(self, user_id: str, context_id: str) -> bool:
        items = self.list_saved_contexts(user_id)
        kept = [c for c in items if c.id != context_id]
        if len(kept) == len(items):
            return False
        self._write_saved(user_id, kept)  # 붙여 둔 사본은 그대로다(노드·책의 컨텍스트는 사본)
        return True

    @locked
    def set_book_contexts(self, user_id: str, key: str, contexts: tuple[Context, ...]) -> None:
        """책의 컨텍스트를 바꾼다(빈 것이면 뗀다). key: 카테고리 id · ms.<프로젝트> · doc.<문서 id>."""
        contexts = clean_contexts(contexts)
        record = json.dumps(to_record(contexts), ensure_ascii=False)
        base, _, rest = key.partition(".")
        now = utcnow()
        if base == "ms" and rest:
            path = self._project_dir(user_id, rest) / "project.json"
            if not path.exists():
                raise ValueError(f"프로젝트 {rest!r}가 없다")
            data = {k: v for k, v in read_json(path).items() if k != "contexts"}
            write_json(path, {**data, **({"contexts": to_record(contexts)} if contexts else {})})
            with self._db:
                self._db.execute("UPDATE projects SET contexts = ? WHERE user_id = ? AND id = ?", (record, user_id, rest))
            return
        if base == "doc" and rest:
            path = self._user_dir(user_id) / "shelf" / "documents" / rest / "document.json"
            table, ident = "documents", rest
        else:
            path = self._user_dir(user_id) / "shelf" / "categories" / key / "category.json"
            table, ident = "categories", key
        if not path.exists() or "/" in ident or "\\" in ident or ".." in ident:
            raise ValueError(f"책 {key!r}가 없다")
        write_json(path, {**read_json(path), "contexts": to_record(contexts), "updated_at": now})
        with self._db:
            self._db.execute(f"UPDATE {table} SET contexts = ?, updated_at = ? WHERE user_id = ? AND id = ?",
                             (record, now, user_id, ident))
