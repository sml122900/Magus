"""글의 첨부 파일(사용자 요청 #97, 2026-10-08): 받는 형식, 파일 이름 다듬기, 저자에게 보이는 종류 이름.

- 글 하나에 파일을 여러 개 붙인다. 저장은 그 사용자 폴더 안(magus.store.attachments)이라 백업에 그대로 들어간다.
- 파일 이름은 폴더 이름을 떼고(브라우저가 붙이는 C:\\fakepath\\ 등) 폴더 구분자·상대 경로·숨김·제어 문자를 막는다.
  저장 경로에는 이름 대신 서버가 만든 id 폴더를 쓰므로 이름으로 다른 곳을 가리킬 수 없다.
- 크기 한도는 MAX_ATTACH_MB(기본 20), 사용자 전체는 MAX_USER_MB(받은함·원고와 함께).
- 웹에서 바로 여는(inline) 것은 브라우저가 안전하게 그리는 그림과 PDF뿐이다. 나머지는 내려받기로만 준다(SVG·HTML은 받지 않는다).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from magus.category.rules import TITLE_MAX
from magus.inbox import mb, size_text

# 확장자 → (저자에게 보이는 종류, 미디어 타입, 브라우저에서 바로 열기)
ATTACH_TYPES: dict[str, tuple[str, str, bool]] = {
    ".pdf": ("PDF", "application/pdf", True),
    ".docx": ("문서", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
    ".doc": ("문서", "application/msword", False),
    ".hwp": ("문서", "application/x-hwp", False),
    ".hwpx": ("문서", "application/hwp+zip", False),
    ".odt": ("문서", "application/vnd.oasis.opendocument.text", False),
    ".rtf": ("문서", "application/rtf", False),
    ".txt": ("문서", "text/plain; charset=utf-8", False),
    ".md": ("문서", "text/markdown; charset=utf-8", False),
    ".csv": ("표", "text/csv; charset=utf-8", False),
    ".xlsx": ("표", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False),
    ".xls": ("표", "application/vnd.ms-excel", False),
    ".ods": ("표", "application/vnd.oasis.opendocument.spreadsheet", False),
    ".pptx": ("발표 자료", "application/vnd.openxmlformats-officedocument.presentationml.presentation", False),
    ".ppt": ("발표 자료", "application/vnd.ms-powerpoint", False),
    ".odp": ("발표 자료", "application/vnd.oasis.opendocument.presentation", False),
    ".png": ("그림", "image/png", True),
    ".jpg": ("그림", "image/jpeg", True),
    ".jpeg": ("그림", "image/jpeg", True),
    ".gif": ("그림", "image/gif", True),
    ".webp": ("그림", "image/webp", True),
    ".heic": ("그림", "image/heic", False),
    ".heif": ("그림", "image/heif", False),
    ".tif": ("그림", "image/tiff", False),
    ".tiff": ("그림", "image/tiff", False),
}
ACCEPT = ",".join(ATTACH_TYPES)  # <input type=file accept=…>
MAX_FILES = 10  # 한 번에 올리는 수
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}


def clean_name(name: str) -> str:
    """브라우저가 준 파일 이름 → 저장할 이름. 받을 수 없으면 ValueError(저자에게 보일 짧은 문장)."""
    base = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (not base or base.startswith(".") or base in ("..",) or _BAD.search(base) or len(base.encode("utf-8")) > 200
            or Path(base).stem.upper() in _RESERVED):
        raise ValueError(f"쓸 수 없는 파일 이름: {name}")
    if Path(base).suffix.lower() not in ATTACH_TYPES:
        raise ValueError(f"받지 않는 형식: {name}")
    return base


def title_from_files(names: Iterable[str]) -> str | None:
    """첫 첨부의 파일 이름(확장자 제외, 제목 길이까지). 첨부가 없으면 None(2026-10-09 제목 자동 채움)."""
    for name in names:
        stem = " ".join(Path(name).stem.split())
        if stem:
            return stem[:TITLE_MAX]
    return None


def shown_title(title: str | None, names: Iterable[str]) -> str | None:
    """보일 제목: 제목이 있으면 그것, 없고 첨부가 있으면 첫 첨부의 파일 이름(확장자 제외). 파일은 바꾸지 않는다(보일 때만).
    웹 글쓰기·고치기는 저장할 때 같은 규칙으로 제목을 채운다. 대화(category_put)로 넣는 글은 제목 규칙(instructions) 그대로."""
    return title or title_from_files(names)


def kind_of(name: str) -> str:
    return ATTACH_TYPES.get(Path(name).suffix.lower(), ("파일", "", False))[0]


def media_type(name: str) -> tuple[str, bool]:
    """(미디어 타입, 브라우저에서 바로 열어도 되나)."""
    _, media, inline = ATTACH_TYPES.get(Path(name).suffix.lower(), ("", "application/octet-stream", False))
    return media, inline


def describe(name: str, size: int) -> str:
    """도구 응답·목록에 쓰는 한 조각: 이름(종류, 크기)."""
    return f"{name}({kind_of(name)}, {size_text(size)})"


__all__ = ["ACCEPT", "ATTACH_TYPES", "MAX_FILES", "clean_name", "describe", "kind_of", "mb", "media_type", "shown_title", "size_text",
           "title_from_files"]
