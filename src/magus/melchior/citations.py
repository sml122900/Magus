"""인용 표기에서 첫 저자와 연도를 뽑아 ref key 후보를 만든다.

key = 첫 저자 성(소문자 영문) + 연도(+ a/b 접미사). 예: daeschler2006, clack2012a.
한글 표기(갤러, 헨릭)는 영문으로 바꾸지 않고 '갤러2022'처럼 둔다. refs.aliases를 통해 영문 key로 연결한다.
한글 저자 뒤에 조사가 붙으면(갤러는(2022)) 조사를 뗀 것을 key로, 원형을 두 번째 후보로 둔다.
괄호 하나에 인용이 여럿이면(Clack, 2012; Hu et al., 2023) ';'로 나눠 모두 잡는다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_LATIN = r"[A-Z][A-Za-z'’\-]+"
_HANGUL = r"[가-힣]{2,8}"
_NAME = rf"(?:{_LATIN}|{_HANGUL})"
_YEAR = r"(?:1[5-9]|20)\d{2}[a-z]?"
_ETAL = r"\s*(?:et\s+al\.?|외|등)"
_COAUTHOR = rf"\s*(?:,|&|and)\s*{_LATIN}"
_TAIL = rf"(?:{_ETAL}|{_COAUTHOR})*"

_PAREN_GROUP = re.compile(r"\(([^()]{1,400})\)")
_PAREN_PART = re.compile(rf"^\s*(?:(?:see|cf\.)\s+|참조\s*[:：]?\s*)?(?P<author>{_NAME}){_TAIL}\s*,?\s*(?P<year>{_YEAR})(?![\d])")
# Clack(2012) · Hu et al.(2023) · 갤러(2022) · Shubin and Daeschler (2006)
_NARRATIVE = re.compile(rf"(?P<author>{_NAME}){_TAIL}\s*\(\s*(?P<year>{_YEAR})\s*[,;)]")
# 코멘트의 자유 표기: Daeschler 2006 · Clack, 2012 · Hu et al. 2023. 라틴 이름만 받는다('확인 2006' 같은 한글 오탐 방지).
_BARE = re.compile(rf"(?P<author>{_LATIN}){_TAIL}\s*,?\s+(?P<year>{_YEAR})(?![\d])")

_NOT_AUTHORS = {"In", "See", "Fig", "Figure", "Table", "Vol", "No", "Since", "From", "By", "The", "Ed", "Eds", "Ch", "Chapter"}
# 연도 앞에 자주 오지만 저자가 아닌 한국어 낱말
_NOT_KOREAN_AUTHORS = {"연도", "논문", "연구", "보고서", "기사", "당시", "이후", "이전", "현재", "출간", "발표", "초판", "개정판", "번역", "원서"}
# 한글 저자 뒤에 붙는 조사(긴 것부터)
_PARTICLES = ("에서는", "에게서", "으로는", "에서", "에게", "으로", "처럼", "보다", "까지", "부터", "조차", "은", "는", "이", "가", "의", "을", "를", "와", "과", "도", "에", "로", "만")


@dataclass(frozen=True)
class Citation:
    author: str
    year: str
    key: str  # 대표 key(조사를 뗀 것)
    start: int
    candidates: tuple[str, ...] = ()  # 찾아볼 순서: 원형 → 조사 뗀 것

    @property
    def lookup_keys(self) -> tuple[str, ...]:
        return self.candidates or (self.key,)


def make_ref_key(author: str, year: str) -> str:
    """한글이 들어 있으면 한글만 남기고(공백 제거), 아니면 발음 부호를 떼고 소문자 영문만 남긴다."""
    if re.search(r"[가-힣]", author):
        return re.sub(r"[^가-힣]", "", author) + year.lower()
    ascii_name = unicodedata.normalize("NFKD", author).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z]", "", ascii_name) or "anon") + year.lower()


def strip_particle(name: str) -> str:
    for particle in _PARTICLES:
        if name.endswith(particle) and len(name) - len(particle) >= 2:
            return name[: -len(particle)]
    return name


def _citation(author: str, year: str, start: int) -> Citation | None:
    if author in _NOT_AUTHORS:
        return None
    if re.fullmatch(_HANGUL, author):
        stem = strip_particle(author)
        if stem in _NOT_KOREAN_AUTHORS or author in _NOT_KOREAN_AUTHORS:
            return None
        original, stripped = make_ref_key(author, year), make_ref_key(stem, year)
        return Citation(stem, year, stripped, start, tuple(dict.fromkeys([original, stripped])))
    key = make_ref_key(author, year)
    return Citation(author, year, key, start, (key,))


def find_citations(text: str, *, bare: bool = False) -> list[Citation]:
    """본문 순서대로 돌려준다. bare=True면 괄호 없는 '저자 연도' 표기도 찾는다(코멘트용)."""
    found: dict[int, Citation] = {}

    def add(author: str, year: str, start: int) -> None:
        if c := _citation(author, year, start):
            found.setdefault(start, c)

    for group in _PAREN_GROUP.finditer(text):
        offset = group.start(1)
        for part in re.finditer(r"[^;]+", group.group(1)):
            if m := _PAREN_PART.match(part.group()):
                add(m.group("author"), m.group("year"), offset + part.start() + m.start("author"))
    for m in _NARRATIVE.finditer(text):
        add(m.group("author"), m.group("year"), m.start("author"))
    if bare:
        for m in _BARE.finditer(text):
            add(m.group("author"), m.group("year"), m.start("author"))
    return [found[pos] for pos in sorted(found)]
