"""받은함(inbox): 사용자가 올린 파일을 두는 곳. `data/users/<user_id>/inbox/`.

- 원격 모드에서 파일은 웹 업로드로만 들어온다. 도구의 경로 인자(book_import·ref_add·idea_add_conversation)는
  받은함의 **파일 이름**을 받는다. 서버의 다른 파일을 읽게 하는 경로는 받지 않는다.
- 로컬(stdio) 모드는 개발용이라, 받은함에 없으면 로컬 경로(절대 또는 FILES_DIR 기준)도 받는다.
  이 차이는 `FileResolver` 한 곳에만 있다.
- 한도: 업로드 한 개 크기, 사용자별 저장 용량. 넘으면 무엇이 얼마인지 밝힌 오류를 낸다.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from magus.ids import local_time
from magus.paths import resolve_input
from magus.store import Store
from magus.store.base import InboxFile

INBOX_TYPES = {".docx": "원고(book_import)", ".pdf": "원고·논문(book_import, ref_add)",
               ".md": "대화 기록(idea_add_conversation)", ".txt": "논문 전문(ref_add)"}
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}


class LimitError(ValueError):
    """한도 초과. 메시지에 무엇이 얼마인지 쓴다."""


def mb(n: int) -> str:
    return f"{n / 1_000_000:,.1f} MB"


def size_text(n: int) -> str:
    """파일 크기 표시: 1MB 미만은 KB(최소 1 KB)."""
    return mb(n) if n >= 1_000_000 else f"{max(1, round(n / 1000)):,} KB"


def safe_filename(name: str) -> str:
    """받은함 파일 이름. 폴더 구분자·상대 경로·숨김 파일·제어 문자를 막고, 형식은 docx·pdf·md·txt만 받는다."""
    clean = unicodedata.normalize("NFC", name.strip())
    if (
        not clean
        or clean.startswith(".")
        or _BAD.search(clean)
        or len(clean.encode("utf-8")) > 200
        or Path(clean).stem.upper() in _RESERVED
    ):
        raise ValueError(f"파일 이름으로 쓸 수 없다: {name!r} (폴더 구분자·특수 문자 없이, 200바이트 이하)")
    if Path(clean).suffix.lower() not in INBOX_TYPES:
        raise ValueError(f"받을 수 있는 형식은 {', '.join(INBOX_TYPES)}이다: {name!r}")
    return clean


def save_upload(store: Store, user_id: str, name: str, data: bytes, max_upload: int, max_user: int) -> InboxFile:
    clean = safe_filename(name)
    if len(data) > max_upload:
        raise LimitError(f"파일이 너무 크다: {mb(len(data))} (한 개 한도 {mb(max_upload)})")
    replaced = next((f.size for f in store.list_inbox(user_id) if f.name == clean), 0)
    used = store.usage_bytes(user_id)
    if used - replaced + len(data) > max_user:
        raise LimitError(
            f"저장 용량 한도를 넘는다: 지금 {mb(used)} + 새 파일 {mb(len(data))} > 한도 {mb(max_user)}. "
            "설정의 '올린 파일'에서 안 쓰는 파일을 지우세요."
        )
    return store.put_inbox(user_id, clean, data)


class FileResolver:
    """도구의 파일 인자 → 읽을 로컬 경로와 기록용 이름. 받은함 이름이 먼저다."""

    def __init__(self, store: Store, files_root: Path | None = None, local_paths: bool = False):
        self.store, self.files_root, self.local_paths = store, files_root, local_paths

    def __call__(self, user_id: str, name: str) -> tuple[Path, str]:
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


def describe(files: list[InboxFile], used: int, limit: int) -> str:
    head = f"올린 파일 {len(files)}개 · 사용 {mb(used)} / 한도 {mb(limit)}"
    if not files:
        return head + "\n올린 파일이 없다. 저자는 웹 책장(원고 책·문헌 책)이나 설정의 '올린 파일'에서 올린다(로컬 개발: magus inbox --add <파일>)."
    lines = [
        f"- {f.name} · {size_text(f.size)} · {local_time(f.modified)} · {INBOX_TYPES.get(Path(f.name).suffix.lower(), '')}"
        for f in files
    ]
    return "\n".join([head, *lines, "도구에는 파일 이름만 준다(예: book_import(path=\"원고.docx\"))."])


ResolveFile = Callable[[str, str], tuple[Path, str]]


def build_tools(store: Store, current_user: Callable[[], str], max_user_bytes: int) -> list:
    from mcp.server.mcpserver.tools import Tool

    def files_list() -> str:
        user = current_user()
        return describe(store.list_inbox(user), store.usage_bytes(user), max_user_bytes)

    return [
        Tool.from_function(
            files_list,
            name="files_list",
            description=(
                "저자가 웹에서 올린 파일 목록: 이름, 크기, 올린 시각, 쓰임. "
                "book_import·ref_add·idea_add_conversation의 파일 인자에는 여기 나온 **이름만** 준다."
            ),
            structured_output=False,
        )
    ]
