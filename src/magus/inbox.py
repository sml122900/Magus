"""받은함(inbox): 사용자가 올린 파일을 두는 곳. `data/users/<user_id>/inbox/`.

- 원격 모드에서 파일은 웹 업로드로만 들어온다. 도구의 경로 인자(book_import·category_put의 file·idea_add_conversation)는
  받은함의 **파일 이름**을 받는다. 서버의 다른 파일을 읽게 하는 경로는 받지 않는다.
- 로컬(stdio) 모드는 개발용이라, 받은함에 없으면 로컬 경로(절대 또는 FILES_DIR 기준)도 받는다.
  이 차이는 `FileResolver` 한 곳에만 있다.
- 한도: 업로드 한 개 크기, 사용자별 저장 용량. 넘으면 무엇이 얼마인지 밝힌 오류를 낸다.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import IO

from magus.ids import STAMP, local_time
from magus.paths import resolve_input
from magus.store.fileio import data_size
from magus.store import Store
from magus.store.base import InboxFile

INBOX_TYPES = {".docx": "올린 문서(book_import)", ".pdf": "올린 문서·논문(book_import, category_put file)",
               ".md": "대화 기록(idea_add_conversation)", ".txt": "논문 전문(category_put file)"}
ATTACHED = "첨부:"  # 게시판 글의 첨부를 도구의 파일 인자로 줄 때의 이름 앞머리(2026-10-09)
ATTACHED_SHOWN = 20  # files_list에 보이는 게시판 첨부 수(새것부터)
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')  # \x7f(DEL)도(점검 5-d, 첨부 이름과 같게)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}


class LimitError(ValueError):
    """한도 초과. 메시지에 무엇이 얼마인지 쓴다."""


def mb(n: int) -> str:
    return f"{n / 1_000_000:,.1f} MB"


def size_text(n: int) -> str:
    """파일 크기 표시: 1MB 미만은 KB(최소 1 KB)."""
    return mb(n) if n >= 1_000_000 else f"{max(1, round(n / 1000)):,} KB"


def has_format_chars(name: str) -> bool:
    """보이지 않는 서식 문자(유니코드 Cf: 오른쪽→왼쪽 U+202E·폭 없는 공백 U+200B 등)가 있으면 True.
    화면의 이름을 속일 수 있다(‮gnp.exe.png가 'png.exe…'처럼 보임, 점검 5-d)."""
    return any(unicodedata.category(ch) == "Cf" for ch in name)


def safe_filename(name: str) -> str:
    """받은함 파일 이름. 폴더 구분자·상대 경로·숨김 파일·제어 문자를 막고, 형식은 docx·pdf·md·txt만 받는다."""
    clean = unicodedata.normalize("NFC", name.strip())
    if (
        not clean
        or clean.startswith(".")
        or _BAD.search(clean)
        or has_format_chars(clean)
        or len(clean.encode("utf-8")) > 200
        or Path(clean).stem.upper() in _RESERVED
    ):
        raise ValueError(f"파일 이름으로 쓸 수 없다: {name!r} (폴더 구분자·특수 문자 없이, 200바이트 이하)")
    if Path(clean).suffix.lower() not in INBOX_TYPES:
        raise ValueError(f"받을 수 있는 형식은 {', '.join(INBOX_TYPES)}이다: {name!r}")
    return clean


def save_upload(store: Store, user_id: str, name: str, data: bytes | IO[bytes], max_upload: int, max_user: int) -> InboxFile:
    """data: 내용 또는 받은 업로드의 임시 파일(흘려 쓴다, 점검 5-a)."""
    clean = safe_filename(name)
    size = data_size(data)
    if size > max_upload:
        raise LimitError(f"파일이 너무 크다: {mb(size)} (한 개 한도 {mb(max_upload)})")
    replaced = next((f.size for f in store.list_inbox(user_id) if f.name == clean), 0)
    used = store.usage_bytes(user_id)
    if used - replaced + size > max_user:
        raise LimitError(
            f"저장 용량 한도를 넘는다: 지금 {mb(used)} + 새 파일 {mb(size)} > 한도 {mb(max_user)}. "
            "설정의 '올린 파일'에서 안 쓰는 파일을 지우세요."
        )
    return store.put_inbox(user_id, clean, data)


class FileResolver:
    """도구의 파일 인자 → 읽을 로컬 경로와 기록용 이름. 받은함 이름이 먼저다."""

    def __init__(self, store: Store, files_root: Path | None = None, local_paths: bool = False):
        self.store, self.files_root, self.local_paths = store, files_root, local_paths

    def __call__(self, user_id: str, name: str) -> tuple[Path, str]:
        if name.startswith(ATTACHED):  # 게시판 글의 첨부(2026-10-09): '첨부:<첨부 id>'(files_list에 보인다)
            if hit := attached_file(self.store, user_id, name[len(ATTACHED):].strip()):
                return hit
            raise FileNotFoundError(f"게시판 첨부에 {name!r}이 없다. files_list로 이름을 확인한다.")
        try:
            clean: str | None = safe_filename(name)
        except ValueError:
            clean = None  # 경로처럼 생긴 이름(폴더 구분자 등)은 받은함 이름이 아니다
        if clean and (path := self.store.inbox_path(user_id, clean)):
            return path, f"inbox/{clean}"
        if self.local_paths:  # 로컬(stdio) 개발용: 절대 경로나 FILES_DIR 기준 상대 경로
            path = resolve_input(name, self.files_root)
            return path, str(path)
        raise FileNotFoundError(f"올린 파일에 {name!r}이 없다. files_list로 이름을 확인하거나, 저자에게 웹 책장에서 먼저 올려 달라고 한다.")


def attached_file(store: Store, user_id: str, attachment_id: str) -> tuple[Path, str] | None:
    """첨부 id → (읽을 경로, 기록용 이름 = 사용자 폴더 기준 상대 경로). 도구가 읽는 형식(INBOX_TYPES)만."""
    for owner, a in store.file_attachments(user_id, tuple(INBOX_TYPES)):
        if a.id == attachment_id and (hit := store.attachment_path(user_id, owner, a.id)):
            book, _, item = owner.partition("/")
            rel = f"shelf/melchior/{owner[4:]}/files" if owner.startswith("ref:") else f"shelf/categories/{book}/files/{item}"
            return hit[0], f"{rel}/{a.id}/{a.name}"
    return None


MANUSCRIPT_TYPES = (".docx", ".pdf")  # 수정본으로 올릴 수 있는 파일
_SHA: dict[tuple[str, int, float], str] = {}  # (경로, 크기, 고친 시각) → sha256. 프로세스 안에서만(파생값)


def file_sha(path: Path) -> str:
    """파일의 sha256(같은 파일이면 다시 읽지 않는다)."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime)
    if key not in _SHA:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while block := f.read(1024 * 1024):
                digest.update(block)
        _SHA[key] = digest.hexdigest()
    return _SHA[key]


def imported_editions(store: Store, user_id: str) -> dict[str, str]:
    """sha256 → 그 파일로 만든 판('수정본 E2(「제목」)', '처음 올린 문서 E1(…)'). 올린 파일 목록에서 이미 가져온 것을 보이려고(점검 16-1)."""
    out: dict[str, str] = {}
    for project in store.list_projects(user_id):
        for e in store.list_editions(user_id, project.id):
            if e.sha256:
                name = f"수정본 E{e.number}" if e.number > 1 else "처음 올린 문서 E1"
                out[e.sha256] = f"{name}(「{project.title[:40]}」)"
    return out


def attached_lines(store: Store, user_id: str) -> list[str]:
    """files_list의 게시판 첨부 줄: '첨부:<id>' · 파일 이름 · 크기 · 올린 시각 · 어느 책의 어느 글(최근 ATTACHED_SHOWN개)."""
    from magus.attachments import shown_title  # noqa: PLC0415  (magus.attachments가 이 모듈을 가져온다)

    found = store.file_attachments(user_id, tuple(INBOX_TYPES))
    if not found:
        return []
    names = {c.id: c.name for c in store.list_categories(user_id)}
    imported = imported_editions(store, user_id)
    lines = []
    for owner, a in found[:ATTACHED_SHOWN]:
        if owner.startswith("ref:"):
            where = f"문헌 글 {owner[4:]}"
        else:
            book, _, item = owner.partition("/")
            post = store.get_category_item(user_id, book, item)
            files = [x.name for x in store.list_attachments(user_id, owner)] if post else []
            title = (shown_title(post.title, files) or post.content[:30]) if post else item  # 제목이 없으면 첫 첨부 이름
            where = f"「{names.get(book, book)}」 책의 글 「{title}」"
        hit = store.attachment_path(user_id, owner, a.id)
        done = imported.get(file_sha(hit[0])) if hit and Path(a.name).suffix.lower() in MANUSCRIPT_TYPES else None
        lines.append(f"- {ATTACHED}{a.id} · {a.name} · {size_text(a.size)} · {local_time(a.at, STAMP)} · {where}"
                     + (f" · 이미 가져옴: {done}" if done else ""))
    more = f" 중 최근 {ATTACHED_SHOWN}개" if len(found) > ATTACHED_SHOWN else ""
    return [f"게시판 첨부 문서 {len(found)}개{more}(새것부터):", *lines]


def describe(files: list[InboxFile], used: int, limit: int, attached: list[str] | None = None,
             done: dict[str, str] | None = None) -> str:
    """done: 올린 파일 이름 → 이미 가져온 판('수정본 E2(「제목」)' 등)."""
    head = f"올린 파일 {len(files)}개 · 사용 {mb(used)} / 한도 {mb(limit)}"
    lines = [
        f"- {f.name} · {size_text(f.size)} · {local_time(f.modified, STAMP)} · {INBOX_TYPES.get(Path(f.name).suffix.lower(), '')}"
        + (f" · 이미 가져옴: {done[f.name]}" if done and f.name in done else "")
        for f in files
    ]
    if not files and not attached:
        return head + "\n올린 파일이 없다. 저자는 책의 게시판에 글을 쓰며 첨부하거나 내 정보의 '올린 파일'에서 올린다(로컬 개발: magus inbox --add <파일>)."
    return "\n".join([head, *lines, *(attached or []),
                      "도구의 파일 인자에는 여기 나온 이름만 준다(예: book_import(path=\"문서.docx\"), 게시판 첨부는 path=\"첨부:<id>\")."])


ResolveFile = Callable[[str, str], tuple[Path, str]]


def build_tools(store: Store, current_user: Callable[[], str], max_user_bytes: int) -> list:
    from mcp.server.mcpserver.tools import Tool

    def files_list() -> str:
        user = current_user()
        files = store.list_inbox(user)
        imported = imported_editions(store, user)
        done = {}
        for f in files:
            if Path(f.name).suffix.lower() in MANUSCRIPT_TYPES and imported and (path := store.inbox_path(user, f.name)):
                if hit := imported.get(file_sha(path)):
                    done[f.name] = hit
        return describe(files, store.usage_bytes(user), max_user_bytes, attached_lines(store, user), done)

    return [
        Tool.from_function(
            files_list,
            name="files_list",
            description=(
                "저자가 웹에서 올린 파일과 게시판 글에 첨부한 문서(docx·pdf·md·txt) 목록: 이름, 크기, 올린 시각, 쓰임·어느 글. "
                "book_import·category_put(file)·idea_add_conversation의 파일 인자에는 여기 나온 **이름만** 준다(게시판 첨부는 '첨부:<id>')."
            ),
            structured_output=False,
        )
    ]
