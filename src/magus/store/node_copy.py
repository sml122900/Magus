"""노드를 다른 프로젝트로 복사(2026-10-11 묶음 5, 연결 노드 대신. 웹만). LocalStore에 섞어 쓰는 믹스인이다.

- 복사하는 것: 그 노드의 책(이름·색·컨텍스트·칸), 글(파일 그대로: 제목·내용·누가·시각·태그·스크랩·응답 관계), 첨부(파일과 .text·.thumb),
  노드의 이름·색·컨텍스트. 받는 프로젝트에 선 없이 따로 놓인 노드로 만든다(빈자리).
- 복사본은 원본과 따로 산다: 책·첨부는 새 id(첨부는 사용자 전체에서 '첨부:<id>'로 찾으므로 겹치면 안 된다, 올린 순서 그대로).
  글 id는 새 책 안에서 그대로라 응답 관계(parent_id)가 이어진다.
- 같은 이름의 노드가 있으면 「이름 (복사)」, 같은 이름의 책이 있으면 책도 「이름 (복사)」(길이에 맞춰 앞을 줄인다).
- 막는 것(MapError code): copy_center(가운데 노드), copy_link(연결 노드), copy_refs(문헌 글이 든 책: 문헌은 사람마다 한 권),
  copy_docs(올린 문서에서 만든 문서: 그 올린 문서에 매여 있다), copy_same(같은 프로젝트), nodes_full, books_full, too_big(용량).
"""

from __future__ import annotations

import re
import secrets
import shutil
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from magus.category.rules import MAX_CATEGORIES, NAME_MAX
from magus.category.rules import name_key as book_key
from magus.ids import new_id, utcnow
from magus.maps import CENTER, NODE_NAME_MAX, name_key
from magus.store.base import MapNode
from magus.store.fileio import locked, read_json, write_json
from magus.store.maps import MapError, free_slot

COPY = " (복사)"


def _copy_name(name: str, taken: set[str], width: int, key: Callable[[str], str]) -> str:
    """이름이 겹치지 않으면 그대로, 겹치면 「이름 (복사)」, 그래도 겹치면 「이름 (복사 2)」… 길이(width)에 맞춰 앞을 줄인다."""
    if key(name) not in taken:
        return name
    for n in range(1, 100):
        tail = COPY if n == 1 else f" (복사 {n})"
        candidate = name[: max(1, width - len(tail))] + tail
        if key(candidate) not in taken:
            return candidate
    raise MapError("name_taken", "같은 이름이 너무 많다", name=name)


class NodeCopyMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]
    _editable: Callable[..., Any]
    _node: Callable[..., Any]
    _room: Callable[..., Any]
    _node_books: Callable[..., Any]
    _write_map: Callable[..., Any]
    _known: Callable[..., set[str]]
    _layout: Callable[[str], Any]
    _reindex_category: Callable[[str, Path, set[str]], None]
    get_map: Callable[..., Any]
    usage_bytes: Callable[[str], int]

    def node_copy_block(self, user_id: str, floor: str, node_id: str) -> tuple[str, str] | None:
        """복사할 수 없으면 (까닭 코드, 책 이름), 할 수 있으면 None(웹이 노드 설정에 한 줄로 보인다)."""
        _, data = self._editable(user_id, floor)
        node = self._node(data, node_id)
        if node_id == CENTER:
            return "copy_center", ""
        if "link" in node:
            return "copy_link", ""
        cats, docs, blocked, refs_book = self._node_books(user_id, node)
        if blocked:
            return ("copy_refs" if blocked == "has_refs" else "copy_center"), refs_book
        if docs:
            return "copy_docs", ""
        return None

    @locked
    def copy_node(self, user_id: str, floor: str, node_id: str, to_floor: str, *, max_user_bytes: int | None = None) -> MapNode:
        """floor의 노드를 to_floor로 복사한다(선 없이 따로 놓인 노드). 새 노드를 돌려준다. 막히면 MapError."""
        if to_floor == floor:
            raise MapError("copy_same", "같은 프로젝트로는 복사하지 않는다")
        _, data = self._editable(user_id, floor)
        node = self._node(data, node_id)
        if (why := self.node_copy_block(user_id, floor, node_id)) is not None:
            raise MapError(why[0], "이 노드는 복사하지 않는다", name=why[1])
        cats, _, _, _ = self._node_books(user_id, node)
        _, target = self._editable(user_id, to_floor)
        self._room(target)
        mine = int(self._db.execute("SELECT COUNT(*) FROM categories WHERE user_id = ?", (user_id,)).fetchone()[0])
        if mine + len(cats) > MAX_CATEGORIES:
            raise MapError("books_full", f"책은 {MAX_CATEGORIES}권까지다", books=len(cats))
        shelf = self._user_dir(user_id) / "shelf" / "categories"
        size = sum(p.stat().st_size for c in cats for p in (shelf / c).rglob("*") if p.is_file())
        if max_user_bytes is not None and self.usage_bytes(user_id) + size > max_user_bytes:
            raise MapError("too_big", "저장 용량이 모자란다", size=size)
        taken_books = {r[0] for r in self._db.execute("SELECT name_key FROM categories WHERE user_id = ? AND floor = ?", (user_id, to_floor))}
        taken_nodes = {name_key(n["name"]) for n in target["nodes"] if "link" not in n and n["id"] != CENTER}
        made: list[Path] = []
        new_books: list[str] = []
        try:
            for cid in cats:  # 파일을 먼저 모두 복사한다(중간에 실패하면 복사한 것만 지운다)
                new = new_id()
                record = read_json(shelf / cid / "category.json")
                name = _copy_name(str(record.get("name") or cid), taken_books, NAME_MAX, book_key)
                taken_books.add(book_key(name))
                shutil.copytree(shelf / cid, shelf / new, ignore=shutil.ignore_patterns("category.json", "files"))
                made.append(shelf / new)
                now = utcnow()
                kept = {k: v for k, v in record.items() if k != "legacy"}  # 이전 되돌리기 표시(옛 기본 책)는 원본에만
                write_json(shelf / new / "category.json", {**kept, "id": new, "name": name, "floor": to_floor,
                                                            "created_at": now, "updated_at": now})
                self._copy_files(shelf / cid / "files", shelf / new / "files")
                new_books.append(new)
            x, y = free_slot(target["nodes"])
            nid = "n-" + new_id()
            copied: dict[str, Any] = {"id": nid, "name": _copy_name(str(node.get("name") or "노드"), taken_nodes, NODE_NAME_MAX, name_key),
                                      "x": x, "y": y, "books": new_books}
            if node.get("color"):
                copied["color"] = node["color"]
            if node.get("contexts"):
                copied["contexts"] = node["contexts"]
            target["nodes"].append(copied)  # 선 없이 따로(저자가 '선 잇기'로 잇는다)
            self._write_map(user_id, to_floor, target)
        except Exception:
            for path in made:
                shutil.rmtree(path, ignore_errors=True)
            raise
        known = self._known(user_id, self._layout(user_id))
        with self._db:
            for new in new_books:
                self._reindex_category(user_id, shelf / new, known)
        found = self.get_map(user_id, to_floor)
        result = found.node(nid) if found else None
        assert result is not None
        return result

    @staticmethod
    def _copy_files(src: Path, dst: Path) -> None:
        """files/<글 id>/<첨부 id>/ → 새 첨부 id로(올린 순서 그대로). 첨부 폴더 안의 .text·.thumb도 함께."""
        if not src.is_dir():
            return
        stamp = re.sub(r"\D", "", utcnow())
        n = 0
        for item in sorted(d for d in src.iterdir() if d.is_dir()):
            for att in sorted(d for d in item.iterdir() if d.is_dir()):
                shutil.copytree(att, dst / item.name / f"{stamp}-{n:03d}{secrets.token_hex(2)[:3]}")
                n += 1
