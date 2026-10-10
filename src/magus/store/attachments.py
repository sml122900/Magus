"""글의 첨부 파일 저장(사용자 요청 #97, 2026-10-08). LocalStore에 섞어 쓰는 믹스인이다.

원본(사용자 폴더 안이라 백업(restic)에 그대로 들어간다. 인덱스는 없고 폴더를 읽는다):
  data/users/<user_id>/shelf/categories/<책 id>/files/<글 id>/<첨부 id>/<파일 이름>   # 글
  data/users/<user_id>/shelf/melchior/<key>/files/<첨부 id>/<파일 이름>              # 문헌 글
  …/<첨부 id>/.thumb/thumb.jpg   # 사진의 썸네일(2026-10-09, magus.thumbs). 파생값이라 지워도 다시 만든다. 첨부 목록은 파일만 센다
첨부 id(new_id, 시간순)는 서버가 만든다. 경로에는 이름이 아니라 이 id로 들어가므로 이름으로 다른 곳을 가리킬 수 없다.
글·책을 휴지통으로 옮기면 첨부도 함께 간다(책은 폴더째, 글은 trash/shelf/category-items/<책 id>/files/<글 id>/).
첨부 하나를 빼면 지우지 않고 옮긴다:
  data/users/<user_id>/trash/shelf/attachments/<책 id>/<글 id>/<첨부 id>/   (문헌 글은 attachments/ref/<key>/<첨부 id>/)
  …/<첨부 id>.trash.json = {at, note}. 프로젝트 휴지통 화면에서 되살리면 그 글로 돌아간다(2026-10-09, 휴지통 종류 attachment).
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
from typing import IO

from magus.ids import new_id, safe_id, utcnow
from magus.store.base import Attachment
from magus.store.fileio import locked, read_json, write_data, write_json

PART = ".part"  # 받는 도중의 임시 파일(목록에 보이지 않는다)


_extracting: set[str] = set()  # 지금 첨부 글자를 뽑고 있는 사용자(프로세스 안)
_extracting_lock = threading.Lock()


def _claim(user_id: str) -> bool:
    with _extracting_lock:
        if user_id in _extracting:
            return False
        _extracting.add(user_id)
        return True


def _release(user_id: str) -> None:
    with _extracting_lock:
        _extracting.discard(user_id)


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
    def put_attachment(self, user_id: str, owner: str, name: str, data: bytes | IO[bytes]) -> Attachment:
        """data: 내용(bytes) 또는 받은 업로드의 임시 파일(처음부터 흘려 쓴다, 점검 5-a)."""
        folder = self._owner_dir(user_id, owner, must_exist=True)
        if folder is None:
            raise ValueError("첨부할 글이 없다")
        if Path(name).name != name or name in ("", ".", ".."):
            raise ValueError(f"파일 이름이 아니다: {name!r}")
        target = folder / new_id() / name
        target.parent.mkdir(parents=True, exist_ok=False)
        tmp = target.with_name(f".{secrets.token_hex(4)}{PART}")
        write_data(tmp, data)
        os.replace(tmp, target)  # 받는 도중에 끊겨도 반쪽 파일이 목록에 보이지 않는다
        found = self._one(target.parent)
        assert found is not None
        self._attachments_changed(user_id, owner)
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
        from magus.thumbs import THUMB_DIR, THUMB_NAME, failed, make_thumb, thumbnailable  # noqa: PLC0415

        hit = self.attachment_path(user_id, owner, attachment_id)
        if hit is None or not thumbnailable(hit[1].name):
            return None
        thumb = hit[0].parent / THUMB_DIR / THUMB_NAME
        if thumb.is_file():
            return thumb
        if failed(thumb):  # 전에 못 만든 그림(너무 큼·망가짐)은 볼 때마다 다시 풀지 않는다(2026-10-09)
            return None
        return thumb if make_thumb(hit[0], thumb) else None

    @locked
    def trash_attachment(self, user_id: str, owner: str, attachment_id: str, note: str) -> bool:
        folder = self._owner_dir(user_id, owner, must_exist=True)
        src = folder / safe_id(attachment_id, "attachment id") if folder else None
        if src is None or self._one(src) is None:
            return False
        target = self._attachment_trash_dir(user_id, owner) / attachment_id
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        write_json(target.parent / f"{attachment_id}.trash.json", {"at": utcnow(), "note": note})
        self._attachments_changed(user_id, owner)
        return True

    @locked
    def replace_attachment(self, user_id: str, owner: str, attachment_id: str, name: str, data: bytes | IO[bytes],
                           note: str) -> tuple[Attachment, str]:
        """같은 첨부 id 자리에 새 파일을 둔다(문서 업데이트, 2026-10-10): 글 안의 순서·링크·대화의 '첨부:<id>'가 그대로다.
        이전 파일(과 뽑아 둔 글자·썸네일)은 새 휴지통 id로 첨부 휴지통에 간다. 되살리면 그 글에 첨부 하나로 돌아온다.
        새 파일을 다 받은 뒤에 옮기므로 받는 도중에 끊기면 이전 파일이 그대로다. (새 첨부, 휴지통 id)."""
        folder = self._owner_dir(user_id, owner, must_exist=True)
        src = folder / safe_id(attachment_id, "attachment id") if folder else None
        if src is None or self._one(src) is None:
            raise ValueError("바꿀 첨부가 없다")
        if Path(name).name != name or name in ("", ".", ".."):
            raise ValueError(f"파일 이름이 아니다: {name!r}")
        tmp = src.parent / f".{src.name}.{secrets.token_hex(4)}{PART}"  # 글 폴더의 숨은 파일(첨부 목록은 하위 폴더만 본다)
        write_data(tmp, data)
        trash_id = new_id()
        target = self._attachment_trash_dir(user_id, owner) / trash_id
        target.parent.mkdir(parents=True, exist_ok=True)
        try:  # 이전 파일과 파생 폴더(.text·.thumb)를 폴더째 한 번에 옮긴다. 못 옮기면 아무것도 바뀌지 않는다
            shutil.move(str(src), str(target))
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        src.mkdir()
        os.replace(tmp, src / name)
        write_json(target.parent / f"{trash_id}.trash.json", {"at": utcnow(), "note": note})
        self._attachments_changed(user_id, owner)
        found = self._one(src)
        assert found is not None
        return found, trash_id

    def _attachment_trash_dir(self, user_id: str, owner: str) -> Path:
        """뺀 첨부가 가는 폴더(글: attachments/<책 id>/<글 id>, 문헌 글: attachments/ref/<key>)."""
        from magus.store.shelf import safe_ref_key  # noqa: PLC0415

        root = self._user_dir(user_id) / "trash" / "shelf" / "attachments"
        if owner.startswith("ref:"):
            return root / "ref" / safe_ref_key(owner[4:])
        book, _, item = owner.partition("/")
        return root / safe_id(book, "book id") / safe_id(item, "item id")

    def _trashed_attachments(self, user_id: str) -> list[tuple[str, Attachment, dict]]:
        """휴지통의 첨부(하나씩 뺀 것) (owner, 첨부, 기록{at, note}). 글째 옮긴 첨부는 글과 함께라 여기에 없다."""
        root = self._user_dir(user_id) / "trash" / "shelf" / "attachments"
        out: list[tuple[str, Attachment, dict]] = []
        for mark in sorted(root.glob("*/*/*.trash.json")):
            found = self._one(mark.with_name(mark.name.removesuffix(".trash.json")))
            if found is None:
                continue
            first, second = mark.parent.parent.name, mark.parent.name
            out.append((f"ref:{second}" if first == "ref" else f"{first}/{second}", found, read_json(mark)))
        return out

    def _restore_attachment(self, user_id: str, ref: str) -> list[str]:
        """ref = "<owner>/<첨부 id>". 그 글로 돌려놓는다. 글이 없으면(휴지통에 있으면) ValueError — 글을 먼저 되살린다."""
        owner, _, att = ref.rpartition("/")
        att = safe_id(att, "attachment id")
        src = self._attachment_trash_dir(user_id, owner) / att
        if self._one(src) is None:
            raise ValueError(f"휴지통에 첨부 {ref}가 없다")
        folder = self._owner_dir(user_id, owner, must_exist=True)
        if folder is None:
            raise ValueError("그 첨부의 글이 없다(글을 먼저 되살린다)", "item")
        if (folder / att).exists():
            raise ValueError(f"첨부 {att}가 이미 그 글에 있다")
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(folder / att))
        src.with_name(f"{att}.trash.json").unlink(missing_ok=True)
        self._attachments_changed(user_id, owner)
        return [ref]

    def _attachment_texts(self, user_id: str, owner: str) -> list[tuple[str, str]]:
        """그 글의 첨부에서 뽑아 둔 글자를 색인할 조각으로 [(첨부 id, 조각)]. 아직 뽑지 않았거나 글자 없음은 뺀다(#100)."""
        from magus.extract import read_text  # noqa: PLC0415
        from magus.textindex import chunk_text  # noqa: PLC0415

        folder = self._owner_dir(user_id, owner, must_exist=False)
        out: list[tuple[str, str]] = []
        for att in self.list_attachments(user_id, owner) if folder is not None else []:  # type: ignore[attr-defined]
            text = read_text(folder / att.id, att.name)
            if text:
                out += [(att.id, piece) for piece in chunk_text(text)]
        return out

    def attachment_text(self, user_id: str, owner: str, attachment_id: str, *, make: bool = True,
                        deadline: float | None = None) -> tuple[dict | None, str | None]:
        """(상태, 글자). 뽑는 동안 저장소 잠금을 잡지 않는다(파일 하나를 읽고 .text/에 쓸 뿐이다). 뽑은 뒤 색인만 잠금 안에서."""
        from magus import extract as ex  # noqa: PLC0415

        hit = self.attachment_path(user_id, owner, attachment_id)  # type: ignore[attr-defined]
        if hit is None or not ex.extractable(hit[1].name):
            return None, None
        att_dir = hit[0].parent
        status = ex.read_status(att_dir)
        if make and ex.due(status, hit[1].name) and _claim(user_id):  # 없음·옛 VERSION 상태(그때 뽑지 않던 형식)·때가 된 '나중에'
            try:  # 사용자마다 한 번에 하나만 뽑는다(점검 7-e: 새로 고침·동시 요청이 20초씩 겹쳤다)
                result = ex.extract(hit[0], ex.DEADLINE if deadline is None else deadline)
                status = ex.save(att_dir, hit[1].name, result)
            finally:
                _release(user_id)
            ex.log.info("extract status=%s chars=%d ms=%d", status["status"], status["chars"], status["ms"])
            with self._lock:
                self._attachments_changed(user_id, owner)
        return status, ex.read_text(att_dir, hit[1].name) if status else None

    @locked
    def find_attachment(self, user_id: str, attachment_id: str) -> tuple[str, Attachment] | None:
        att = safe_id(attachment_id, "attachment id")
        shelf = self._user_dir(user_id) / "shelf"
        for folder in (shelf / "categories").glob(f"*/files/*/{att}"):  # <책>/files/<글>/<첨부 id>
            book, item = folder.parents[2].name, folder.parent.name
            if (shelf / "categories" / book / "items" / f"{item}.json").is_file() and (a := self._one(folder)):
                return f"{book}/{item}", a
        for folder in (shelf / "melchior").glob(f"*/files/{att}"):
            if (folder.parents[1] / "bib.json").is_file() and (a := self._one(folder)):
                return f"ref:{folder.parents[1].name}", a
        return None

    def extract_all(self, user_id: str, *, force: bool = False) -> dict[str, int]:
        """그 사용자의 모든 첨부(휴지통 빼고) 글자 뽑기(배포 때 한 번에, `magus extract`·`magus warm-cache`). 이미 뽑은 것은 force가 아니면
        건너뛴다. 형식을 늘린 뒤(2026-10-11)에는 새로 뽑게 된 형식(hwp 등)의 이미 올라간 첨부가 상태가 없으므로 여기서 뽑힌다.
        돌려주는 것은 개수뿐(이름·내용 없음)."""
        from magus import extract as ex  # noqa: PLC0415

        counts = {"대상": 0, "뽑음": 0, "앞부분만": 0, "글자 없음": 0, "실패": 0, "나중에": 0, "이미": 0, "형식 아님": 0}
        names = {"ok": "뽑음", "truncated": "앞부분만", "empty": "글자 없음", "failed": "실패", "later": "나중에"}
        shelf = self._user_dir(user_id) / "shelf"
        owners: list[tuple[str, Path]] = []
        for folder in sorted((shelf / "categories").glob("*/files/*/*")):
            book, item = folder.parents[2].name, folder.parent.name
            if (shelf / "categories" / book / "items" / f"{item}.json").is_file():
                owners.append((f"{book}/{item}", folder))
        for folder in sorted((shelf / "melchior").glob("*/files/*")):
            if (folder.parents[1] / "bib.json").is_file():
                owners.append((f"ref:{folder.parents[1].name}", folder))
        for owner, folder in owners:
            att = self._one(folder)
            if att is None:
                continue
            if not ex.extractable(att.name):
                counts["형식 아님"] += 1
                continue
            counts["대상"] += 1
            old = ex.read_status(folder)
            again = old is not None and (force or ex.stale(old, att.name))
            if old is not None and old["status"] != "later" and not again:
                counts["이미"] += 1
                continue
            if again:
                (folder / ex.TEXT_DIR / ex.STATUS_FILE).unlink()
            status, _ = self.attachment_text(user_id, owner, att.id)
            counts[names.get((status or {}).get("status", "failed"), "실패")] += 1
        return counts

    def _attachments_changed(self, user_id: str, owner: str) -> None:
        """첨부가 늘거나 줄면 그 글의 색인을 다시 만든다(첨부 이름도 찾는다). CategoryMixin·ShelfMixin이 채운다."""

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

    def trashed_item_attachments(self, user_id: str, book: str, item: str) -> list[str]:
        """휴지통에 있는 글의 첨부 이름(올린 순서. 프로젝트 휴지통 화면의 '첨부 N개 함께'와 제목 없는 글의 보일 제목)."""
        folder = self._user_dir(user_id) / "trash" / "shelf" / "category-items" / safe_id(book, "book id") / "files" / safe_id(item, "item id")
        found = [self._one(d) for d in sorted(folder.iterdir()) if d.is_dir()] if folder.is_dir() else []
        return [a.name for a in found if a is not None]

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
