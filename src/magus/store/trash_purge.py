"""휴지통 비우기(2026-10-11 묶음 3, docs/decisions/2026-10-11-batch.md). LocalStore에 섞어 쓰는 믹스인이다.

- 영구 삭제: 휴지통의 그 항목 파일을 지운다(첨부 폴더 안 .text·.thumb, 프로젝트 폴더 안 .cache 인용 캐시도 함께). 되살릴 수 없다.
  백업(restic)에는 남아 있다. 휴지통에 옮길 때 이미 색인에서 빠졌으므로 색인은 그대로다(시험으로 본다).
- 함께 지우는 것: 되살릴 길이 없어지는 것. 노드 → 그 노드와 함께 옮긴 책에서 먼저 버린 글·첨부, 글 → 함께 옮긴 응답 글·첨부와
  그 글에서 먼저 뺀 첨부, 책 → 그 책에서 먼저 버린 글·첨부.
- 새로 보이는 휴지통: 책 설정의 🗑로 옮긴 만든 문서(trash/shelf/documents/<id>/)와 올린 문서
  (trash/<프로젝트>-<시각>/, 올린 문서 휴지통·다시 가져오기). 이름이 그 꼴이 아니거나 project.json이 없는 폴더(운영자가 둔 것)는 건드리지 않는다.
- 경로는 모두 사용자 휴지통(users/<id>/trash/) 안에서만 푼다. 밖으로 풀리면 ValueError.
- 원고 프로젝트 삭제 보호(2026-10-14): 올린 문서가 든 휴지통 프로젝트와 휴지통의 올린 문서(trash_guard)는 이름을 그대로 적어야
  (confirm_name) 영구 삭제한다. 영구 삭제한 일은 활동 기록(.activity.log)에 남는다.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from magus.activity import PURGE, logged
from magus.ids import safe_id
from magus.store.base import TrashedExtra, UploadGuard, same_name
from magus.store.fileio import locked, read_json
from magus.store.project_trash import MANIFEST, last_edition, safe_pid

PURGE_KINDS = ("node", "category_item", "attachment", "category", "document", "manuscript", "project", "inbox")
_MS = re.compile(r"^(?P<pid>[A-Za-z0-9_\-]{1,64})-(?P<stamp>\d{4}-\d{2}-\d{2}T\d{6,9}Z)$")
_MOVED_ASIDE = re.compile(r"^(?P<id>.+?)-\d{4}-\d{2}-\d{2}T\d{6,9}Z$")  # 같은 id를 다시 휴지통에 넣을 때 비켜 둔 옛 폴더


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def _stamp_iso(stamp: str) -> str:
    """'2026-10-03T043504847Z' → '2026-10-03T04:35:04.847Z'(정렬·표시용)."""
    day, _, rest = stamp.partition("T")
    digits = rest.rstrip("Z")
    return f"{day}T{digits[0:2]}:{digits[2:4]}:{digits[4:6]}.{digits[6:9] or '000'}Z"


class TrashPurgeMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]

    def _trash_dir(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "trash"

    def _inside(self, user_id: str, path: Path) -> Path:
        base = self._trash_dir(user_id).resolve()
        resolved = path.resolve()
        if base not in resolved.parents:
            raise ValueError("휴지통 밖의 경로다")
        return path

    def _remove(self, user_id: str, *paths: Path) -> int:
        """휴지통 안의 파일·폴더를 지운다. 지운 바이트 수."""
        freed = 0
        for path in paths:
            if not path.exists():
                continue
            self._inside(user_id, path)
            freed += _size(path)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        return freed

    # ---- 새로 보이는 휴지통 ------------------------------------------------------------------

    @locked
    def list_trashed_documents(self, user_id: str) -> list[TrashedExtra]:
        """책 설정의 🗑로 옮긴 만든 문서(올린 문서에서 만든 읽기용 문서)."""
        out = []
        for meta in sorted((self._trash_dir(user_id) / "shelf" / "documents").glob("*/document.json")):
            data = read_json(meta)
            mark = data.get("_trash") or {}
            versions = data.get("versions") or []
            out.append(TrashedExtra("document", meta.parent.name, str(data.get("floor") or data.get("project_id") or ""),
                                    str(data.get("title") or meta.parent.name), str(mark.get("at") or data.get("updated_at") or ""),
                                    f"{len(versions)}번째까지" if len(versions) > 1 else ""))
        return out

    @locked
    def list_trashed_manuscripts(self, user_id: str) -> list[TrashedExtra]:
        """휴지통으로 옮긴 올린 문서(trash/<프로젝트>-<시각>/: 장·확인 요청·결정·수정본 원본)."""
        out = []
        for folder in sorted(p for p in self._trash_dir(user_id).iterdir() if p.is_dir()) if self._trash_dir(user_id).is_dir() else []:
            found = _MS.match(folder.name)
            if not found or not (folder / "project.json").is_file():
                continue
            data = read_json(folder / "project.json")
            note = read_json(folder / "trash-note.json") if (folder / "trash-note.json").is_file() else {}
            chapters = len(list((folder / "book").glob("ch-*.md")))
            out.append(TrashedExtra("manuscript", folder.name, found.group("pid"), str(data.get("title") or found.group("pid")),
                                    str(note.get("at") or _stamp_iso(found.group("stamp"))), f"{chapters}장" if chapters else ""))
        return out

    @locked
    def trashed_books(self, user_id: str) -> dict[str, tuple[str, str, int]]:
        """책째 휴지통으로 옮긴 책(책 설정의 🗑, trash/shelf/categories/): 휴지통 폴더 이름 → (프로젝트, 책 이름, 글 수)."""
        out = {}
        for meta in sorted((self._trash_dir(user_id) / "shelf" / "categories").glob("*/category.json")):
            data = read_json(meta)
            out[meta.parent.name] = (str(data.get("floor") or ""), str(data.get("name") or meta.parent.name),
                                     len(list((meta.parent / "items").glob("*.json"))))
        return out

    # ---- 영구 삭제 ---------------------------------------------------------------------------

    @locked
    def trash_guard(self, user_id: str, kind: str, item_id: str) -> UploadGuard | None:
        """휴지통의 프로젝트(올린 문서가 들었던 것)·올린 문서면 보호 정보(이름·장 수·마지막 수정본), 아니면 None."""
        trash = self._trash_dir(user_id)
        if kind == "project" and safe_pid(item_id) and (trash / "projects" / item_id / MANIFEST).is_file():
            data = read_json(trash / "projects" / item_id / MANIFEST)
            pid = str(data.get("project_id") or "")
            chapters = int(data.get("chapters") or 0)
            edition = int(data.get("edition") or 0) or (
                last_edition(trash / "projects" / item_id / "files" / "projects" / pid / "project.json") if safe_pid(pid) else 0)
            name = str(data.get("title") or pid)
            return UploadGuard("project", name, chapters, edition) if chapters or edition else None
        if kind == "manuscript" and _MS.match(item_id) and (trash / item_id / "project.json").is_file():
            folder = trash / item_id
            chapters = len(list((folder / "book").glob("ch-*.md")))
            edition = last_edition(folder / "project.json")
            name = str(read_json(folder / "project.json").get("title") or _MS.match(item_id).group("pid"))  # type: ignore[union-attr]
            return UploadGuard("manuscript", name, chapters, edition) if chapters or edition else None
        return None

    @logged(PURGE, lambda args: args[0], lambda args, kw, result: args[1])
    @locked
    def purge_trash(self, user_id: str, kind: str, item_id: str, *, confirm_name: str | None = None) -> int:
        """휴지통의 항목 하나를 영구 삭제한다. 지운 바이트 수. 없으면 ValueError("missing").
        올린 문서가 든 것은 confirm_name이 그 이름이어야 한다(아니면 ValueError("name", 이름))."""
        trash = self._trash_dir(user_id)
        shelf = trash / "shelf"
        guard = self.trash_guard(user_id, kind, item_id)
        if guard and not same_name(confirm_name, guard.name):
            raise ValueError("name", guard.name)
        if kind == "node":
            floor, _, stem = item_id.partition("/")
            safe_id(floor, "project id")
            safe_id(stem, "node id")
            record = shelf / "nodes" / floor / f"{stem}.json"
            if not record.is_file():
                raise ValueError("missing")
            cats = [str(c) for c in (read_json(record).get("_trash") or {}).get("categories") or [] if isinstance(c, str)]
            freed = self._remove(user_id, record, shelf / "nodes" / floor / stem)
            for cid in cats:  # 그 노드와 함께 옮긴 책에서 먼저 버린 글·첨부(책이 없어 되살릴 길이 없다)
                safe_id(cid, "book id")
                freed += self._remove(user_id, shelf / "category-items" / cid, shelf / "attachments" / cid)
            self._prune(user_id, shelf / "nodes" / floor)
            return freed
        if kind == "category_item":
            book, _, item = item_id.partition("/")
            safe_id(book, "book id")
            safe_id(item, "item id")
            folder = shelf / "category-items" / book
            if not (folder / f"{item}.json").is_file():
                raise ValueError("missing")
            replies = [p for p in folder.glob("*.json") if (read_json(p).get("_trash") or {}).get("with") == item]
            paths = [folder / f"{item}.json", *replies]
            paths += [folder / "files" / name for name in (item, *(p.stem for p in replies))]
            paths += sorted((folder / "files").glob(f"{item}-*"))  # 휴지통을 두 번 오가며 비켜 둔 옛 첨부 폴더
            paths += [shelf / "attachments" / book / item]  # 그 글에서 먼저 뺀 첨부(글이 없어 되살릴 길이 없다)
            freed = self._remove(user_id, *paths)
            self._prune(user_id, folder)
            return freed
        if kind == "attachment":
            owner, _, att = item_id.rpartition("/")
            safe_id(att, "attachment id")
            if owner.startswith("ref:"):
                from magus.store.shelf import safe_ref_key  # noqa: PLC0415

                folder = shelf / "attachments" / "ref" / safe_ref_key(owner[4:])
            else:
                book, _, item = owner.partition("/")
                folder = shelf / "attachments" / safe_id(book, "book id") / safe_id(item, "item id")
            if not (folder / f"{att}.trash.json").is_file() and not (folder / att).is_dir():
                raise ValueError("missing")
            freed = self._remove(user_id, folder / att, folder / f"{att}.trash.json")
            self._prune(user_id, folder)
            return freed
        if kind == "category":
            safe_id(item_id, "book id")
            folder = shelf / "categories" / item_id
            if not (folder / "category.json").is_file():
                raise ValueError("missing")
            aside = _MOVED_ASIDE.match(item_id)
            book = aside.group("id") if aside else item_id
            freed = self._remove(user_id, folder)
            if not (self._user_dir(user_id) / "shelf" / "categories" / book).exists():  # 그 책에서 먼저 버린 글·첨부
                freed += self._remove(user_id, shelf / "category-items" / book, shelf / "attachments" / book)
            return freed
        if kind == "document":
            safe_id(item_id, "document id")
            folder = shelf / "documents" / item_id
            if not (folder / "document.json").is_file():
                raise ValueError("missing")
            return self._remove(user_id, folder)
        if kind == "manuscript":
            if not _MS.match(item_id) or not (trash / item_id / "project.json").is_file():
                raise ValueError("missing")
            return self._remove(user_id, trash / item_id)
        if kind == "project":
            safe_id(item_id, "trash id")
            folder = trash / "projects" / item_id
            if not (folder / "manifest.json").is_file():
                raise ValueError("missing")
            return self._remove(user_id, folder)
        if kind == "inbox":
            safe_id(item_id, "trash id")
            folder = trash / "inbox" / item_id
            mark = trash / "inbox" / f"{item_id}.trash.json"
            if not folder.is_dir() and not mark.is_file():
                raise ValueError("missing")
            return self._remove(user_id, folder, mark)
        raise ValueError(f"휴지통 종류를 모른다: {kind!r}")

    def _prune(self, user_id: str, folder: Path) -> None:
        """비운 뒤 남은 빈 폴더(files/ 포함)만 치운다."""
        if not folder.is_dir():
            return
        for sub in sorted((d for d in folder.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
            if not any(sub.iterdir()):
                sub.rmdir()
        if not any(folder.iterdir()):
            self._inside(user_id, folder)
            folder.rmdir()
