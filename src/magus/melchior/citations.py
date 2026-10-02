"""인용 표기에서 첫 저자와 연도를 뽑아 ref key 후보를 만든다.

key = 첫 저자 성(소문자 영문) + 연도. 예: daeschler2006.
한글 표기(갤러, 헨릭)는 영문으로 바꾸지 않고 '갤러2022'처럼 그대로 둔다. 4단계에서 refs.aliases를 통해 영문 key로 연결한다.
지금은 2단계 코멘트 분류(ref_key 후보)에 쓰고, 4단계 ref_check에서 같은 추출기를 다시 쓴다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_LATIN = r"[A-Z][A-Za-z'’\-]+"
_HANGUL = r"[가-힣]{2,6}"
_NAME = rf"(?:{_LATIN}|{_HANGUL})"
_YEAR = r"(?:1[5-9]|20)\d{2}"
_ETAL = r"\s*(?:et\s+al\.?|외|등)"
_COAUTHOR = rf"\s*(?:,|&|and)\s*{_LATIN}"
_TAIL = rf"(?:{_ETAL}|{_COAUTHOR})*"

# (Daeschler, Shubin & Jenkins, 2006) · (Hu et al., 2023) · (헨릭, 2016)
_PARENTHETICAL = re.compile(rf"\(\s*(?P<author>{_NAME}){_TAIL}\s*,?\s*(?P<year>{_YEAR})[a-z]?\s*[,;)]")
# Clack(2012) · Hu et al.(2023) · 갤러(2022) · Shubin and Daeschler (2006)
_NARRATIVE = re.compile(rf"(?P<author>{_NAME}){_TAIL}\s*\(\s*(?P<year>{_YEAR})[a-z]?\s*[,;)]")
# 코멘트의 자유 표기: Daeschler 2006 · Clack, 2012 · Hu et al. 2023
# 라틴 이름만 받는다. '확인 2006' 같은 한글 오탐을 막기 위해서다.
_BARE = re.compile(rf"(?P<author>{_LATIN}){_TAIL}\s*,?\s+(?P<year>{_YEAR})(?![\d])")

_NOT_AUTHORS = {"In", "See", "Fig", "Figure", "Table", "Vol", "No", "Since", "From", "By", "The", "Ed", "Eds", "Ch", "Chapter"}


@dataclass(frozen=True)
class Citation:
    author: str
    year: str
    key: str
    start: int


def make_ref_key(author: str, year: str) -> str:
    """한글이 들어 있으면 한글만 남기고(공백 제거), 아니면 발음 부호를 떼고 소문자 영문만 남긴다."""
    if re.search(r"[가-힣]", author):
        return re.sub(r"[^가-힣]", "", author) + year.lower()
    ascii_name = unicodedata.normalize("NFKD", author).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z]", "", ascii_name) or "anon") + year.lower()


def find_citations(text: str, *, bare: bool = False) -> list[Citation]:
    """본문 순서대로 돌려준다. bare=True면 괄호 없는 '저자 연도' 표기도 찾는다(코멘트용)."""
    patterns = [_PARENTHETICAL, _NARRATIVE, *([_BARE] if bare else [])]
    found: dict[int, Citation] = {}
    for pattern in patterns:
        for m in pattern.finditer(text):
            author, year = m.group("author"), m.group("year")
            if author in _NOT_AUTHORS:
                continue
            found.setdefault(m.start("author"), Citation(author, year, make_ref_key(author, year), m.start("author")))
    return [found[pos] for pos in sorted(found)]
