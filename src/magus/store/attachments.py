"""글의 첨부 파일 저장(사용자 요청 #97, 2026-10-08). LocalStore에 섞어 쓰는 믹스인이다.

원본(사용자 폴더 안이라 백업(restic)에 그대로 들어간다. 인덱스는 없고 폴더를 읽는다):
  data/users/<user_id>/shelf/categories/<책 id>/files/<글 id>/<첨부 id>/<파일 이름>   # 글
  data/users/<user_id>/shelf/melchior/<key>/files/<첨부 id>/<파일 이름>              # 문헌 글
  …/<첨부 id>/.thumb/thumb.jpg   # 사진의 썸네일(2026-10-09, magus.thumbs). 파생값이라 지워도 다시 만든다. 첨부 목록은 파일만 센다
첨부 id(new_id, 시간순)는 서버가 만든다. 경로에는 이름이 아니라 이 id로 들어가므로 이름으로 다른 곳을 가리킬 수 없다.
글·책을 휴지통으로 옮기면 첨부도 함께 간다(책은 폴더째, 글은 trash/shelf/category-items/<책 id>/files/<글 id>/).
첨부 하나를 빼면 지우지 않고 옮긴다:
  data/users/<user_id>/trash/shelf/attachments/<책 id>/<글 id>/<첨부 id>/   (문헌 글은 attachments/ref/<key>/<첨부 id>/)
기존 파일 형식(category.json·items/*.json·bib.json)은 바꾸지 않는다. 옛 코드는 files/ 폴더를 읽지 않을 뿐이다.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from magus.ids import new_id, safe_id, utcnow
from magus.store.base import Attachment
from magus.store.fileio import locked, write_json

PART = ".part"  # 받는 도중의 임시 파일(목록에 보이지 않는다)


class AttachmentMixin:
    root: Path
    _db: sqlite3.Connection
    _lock: threading.RLock
    _user_dir: Callable[[str], Path]

    def _owner_dir(self, user_id: str, owner: str, *, must_exist: bool) -> Path | None:
        """owner → 그 글의 첨부 폴더. 글(또는 문헌)이 없으면 None(must_exist) 또는 폴더만 계산."""
        from magus.store.shelf import safe_ref_key  # noqa: PLC0415  (순환 import 피함)

        shelf = self._user_dir(user_id) / "shelf"
        if owner.startswith("ref:"):
            key = safe_ref_key(owner[4:])
            base = shelf / "melchior" / key
            exists = (base / "bib.json").is_file()
            return base / "files" if exists or not must_exist else None
        book, sep, item = owner.partition("/")
        if not sep:
            raise ValueError(f"첨부의 글을 알 수 없다: {owner!r}")
        cdir = shelf / "categories" / safe_id(book, "book id")
        exists = (cdir / "items" / f"{safe_id(item, 'item id')}.json").is_file()
        return cdir / "files" / item if exists or not must_exist else None

    @staticmethod
    def _one(folder: Path) -> Attachment | None:
        files = [p for p in folder.iterdir() if p.is_file() and not p.name.endswith(PART)] if folder.is_dir() else []
        if len(files) != 1:
            return None
        stat = files[0].stat()
        at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return Attachment(folder.name, files[0].name, stat.st_size, at)

    @locked
    def list_attachments(self, user_id: str, owner: str) -> list[Attachment]:
        folder = self._owner_dir(user_id, owner, must_exist=False)
        if folder is None or not folder.is_dir():
            return []
        out = [self._one(d) for d in sorted(folder.iterdir()) if d.is_dir()]
        return [a for a in out if a is not None]

    @locked
    def put_attachment(self, user_id: str, owner: str, name: str, data: bytes) -> Attachment:
        folder = self._owner_dir(user_id, owner, must_exist=True)
        if folder is None:
            raise ValueError("첨부할 글이 없다")
        if Path(name).name != name or name in ("", ".", ".."):
            raise ValueError(f"파일 이름이 아니다: {name!r}")
        target = folder / new_id() / name
        target.parent.mkdir(parents=True, exist_ok=False)
        tmp = target.with_name(f".{secrets.token_hex(4)}{PART}")
        tmp.write_bytes(data)
        os.replace(tmp, target)  # 받는 도중에 끊겨도 반쪽 파일이 목록에 보이지 않는다
        found = self._one(target.parent)
        assert found is not None
        return found

    @locked
    def attachment_path(self, user_id: str, owner: str, attachment_id: str) -> tuple[Path, Attachment] | None:
        folder = self._owner_dir(user_id, owner, must_exist=True)
        if folder is None:
            return None
        found = self._one(folder / safe_id(attachment_id, "attachment id"))
        return (folder / found.id / found.name, found) if found else None

    def attachment_thumb(self, user_id: str, owner: str, attachment_id: str) -> Path | None:
        """사진 첨부의 썸네일 경로(없으면 그 자리에서 만든다). 사진이 아니거나 만들지 못하면 None(화면은 원본을 쓴다).
        그림을 줄이는 동안 저장소 잠금을 잡지 않는다(파일 하나를 읽고 다른 이름으로 쓸 뿐이다)."""
        from magus.thumbs import THUMB_DIR, THUMB_NAME, make_thumb, thumbnailable  # noqa: PLC0415

        hit = self.attachment_path(user_id, owner, attachment_id)
        if hit is None or not thumbnailable(hit[1].name):
            return None
        thumb = hit[0].parent / THUMB_DIR / THUMB_NAME
        if thumb.is_file() or make_thumb(hit[0], thumb):
            return thumb
        return None

    @locked
    def trash_attachment(self, user_id: str, owner: str, attachment_id: str, note: str) -> bool:
        folder = self._owner_dir(user_id, owner, must_exist=True)
        src = folder / safe_id(attachment_id, "attachment id") if folder else None
        if src is None or self._one(src) is None:
            return False
        rel = ["ref", owner[4:]] if owner.startswith("ref:") else owner.split("/", 1)
        target = self._user_dir(user_id) / "trash" / "shelf" / "attachments" / Path(*rel) / attachment_id
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        write_json(target.parent / f"{attachment_id}.trash.json", {"at": utcnow(), "note": note})
        return True

    @locked
    def file_attachments(self, user_id: str, suffixes: tuple[str, ...]) -> list[tuple[str, Attachment]]:
        shelf = self._user_dir(user_id) / "shelf"
        found: list[tuple[str, Attachment]] = []
        for folder in (shelf / "categories").glob("*/files/*/*"):  # <책>/files/<글>/<첨부 id>
            book, item = folder.parents[2].name, folder.parent.name
            if (shelf / "categories" / book / "items" / f"{item}.json").is_file() and (a := self._one(folder)):
                found.append((f"{book}/{item}", a))
        for folder in (shelf / "melchior").glob("*/files/*"):  # <key>/files/<첨부 id>
            if (folder.parents[1] / "bib.json").is_file() and (a := self._one(folder)):
                found.append((f"ref:{folder.parents[1].name}", a))
        return sorted(((o, a) for o, a in found if Path(a.name).suffix.lower() in suffixes), key=lambda x: x[1].id, reverse=True)

    def trashed_item_attachments(self, user_id: str, book: str, item: str) -> int:
        """휴지통에 있는 글의 첨부 수(프로젝트 휴지통 화면의 '첨부 N개 함께')."""
        folder = self._user_dir(user_id) / "trash" / "shelf" / "category-items" / safe_id(book, "book id") / "files" / safe_id(item, "item id")
        return sum(1 for d in folder.iterdir() if d.is_dir() and self._one(d)) if folder.is_dir() else 0

    # 글 휴지통·되살리기 때 첨부도 함께(CategoryMixin이 부른다)
    def _move_item_files(self, user_id: str, book: str, item: str, *, to_trash: bool) -> None:
        live = self._user_dir(user_id) / "shelf" / "categories" / book / "files" / item
        trashed = self._user_dir(user_id) / "trash" / "shelf" / "category-items" / book / "files" / item
        src, dst = (live, trashed) if to_trash else (trashed, live)
        if not src.is_dir():
            return
        if dst.exists():  # 같은 글이 휴지통을 두 번 오가면 옛것을 시각 이름으로 비켜 둔다(지우지 않는다)
            dst.rename(dst.with_name(f"{item}-{utcnow().replace(':', '').replace('.', '')}"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
