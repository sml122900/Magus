"""인용 표기에서 첫 저자와 연도를 뽑아 ref key 후보를 만든다.

key = 첫 저자 성(소문자 영문) + 연도(+ a/b 접미사). 예: daeschler2006, clack2012a, devries1984.
- 라틴 이름: 발음 부호(Prüfer, Giráldez), 소문자 접두어(de Vries, von Glahn, della Paolera), 여러 단어(Ibn Khaldun) 허용.
- 한자 이름(田代和生)은 한자 그대로 key로 쓴다. 참고문헌의 한글 읽기는 aliases로 잇는다.
- 한글 표기(갤러, 케인스)는 영문으로 바꾸지 않는다. refs.aliases나 음역 추정(check.py)으로 영문 key에 잇는다.
  조사가 붙으면(갤러는(2022)) 조사를 뗀 것을 key로, 원형을 첫 후보로 둔다.
  한 글자 성은 '등'·'외'·'·'이 뒤따를 때만 받는다(셰 등(2019), 넌·첸(2011)).
- 괄호 하나에 인용이 여럿이면(Clack, 2012; Hu et al., 2023) ';'로 나눠 모두 잡고, 설명 뒤에 붙은 인용
  (1990년 국제달러, Maddison, 2001)도 잡는다.
- 연도 앞에 오는 지명·사건·통계(모스크바 회사(1555), 합계출산율(2023))는 저자로 보지 않는다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace

_UPPER = "A-ZÀ-ÖØ-ÞĀĂĄĆĈĊČĎĐĒĔĖĘĚĜĞĠĢĤĦĨĪĬĮİĲĴĶĹĻĽĿŁŃŅŇŊŌŎŐŒŔŖŘŚŜŞŠŢŤŦŨŪŬŮŰŲŴŶŸŹŻŽ"
_WORD = r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž'’\-]"
_PARTICLE = r"(?:de|van|von|der|den|della|del|di|da|du|le|la|ter|ten|bin|ibn|al|el|dos|das)"
_LATIN_WORD = rf"[{_UPPER}]{_WORD}+"
# 성: (소문자 접두어)* + 대문자로 시작하는 낱말 1~3개. 예: Clack, de Vries, van der Linden, Ibn Khaldun
_LATIN = rf"(?:{_PARTICLE}\s+){{0,2}}{_LATIN_WORD}(?:\s+{_LATIN_WORD}){{0,2}}"
_HAN = r"[一-鿿㐀-䶿]{2,8}"
_HANGUL = r"[가-힣]{2,8}|[가-힣](?=\s*(?:[·・]|등|외))"
_YEAR = r"(?:1[5-9]|20)\d{2}[a-z]?"
_ETAL = r"\s*(?:et\s+al\.?|외|등)"
# 공저자 꼬리는 첫 저자의 문자 체계를 따른다. 한글 낱말 뒤에 라틴 공저자가 붙는 것을 허용하면
# "대사량 배수, Hu et al.(2023)"이 '배수2023'이 된다(실원고 코멘트에서 확인).
_LATIN_TAIL = rf"(?:{_ETAL}|\s*(?:,|&|and)\s*(?:{_PARTICLE}\s+){{0,2}}{_LATIN_WORD})*"  # , Shubin · & van Zanden
_HANGUL_TAIL = rf"(?:{_ETAL}|\s*[·・]\s*[가-힣]{{1,8}}|(?:와|과)\s+[가-힣]{{2,8}})*"  # 넌·첸 · 애쓰모글루와 로빈슨
_AUTHOR = rf"(?P<who>(?P<latin>{_LATIN}){_LATIN_TAIL}|(?P<han>{_HAN}){_ETAL}?|(?P<hangul>{_HANGUL}){_HANGUL_TAIL})"

_PAREN_GROUP = re.compile(r"\(([^()]{1,400})\)")
# 괄호 조각 끝의 '이름…, 연도'. 앞에 설명이 있으면 쉼표·콜론 뒤에서 시작한다.
# (Toynbee, 1934–1961): key는 시작 연도. 괄호 인용에서만 받는다. 서술형 "한국(1965~1995)"은 기간이지 인용이 아니다.
_RANGE = r"(?:\s*[–\-]\s*\d{2,4})?"
_PAREN_PART = re.compile(
    rf"(?:^\s*|[,:]\s*)(?:(?:see|cf\.)\s+|참조\s*[:：]?\s*)?{_AUTHOR}\s*,?\s*(?P<year>{_YEAR}){_RANGE}\s*$"
)
# Clack(2012) · Hu et al.(2023) · 갤러(2022) · Shubin and Daeschler (2006) · 넌·첸(2011)
_NARRATIVE = re.compile(rf"(?<![\w가-힣]){_AUTHOR}\s*\(\s*(?P<year>{_YEAR})\s*[,;)]")
# 코멘트의 자유 표기: Daeschler 2006 · Clack, 2012 · Hu et al. 2023. 라틴 이름만('확인 2006' 같은 한글 오탐 방지).
_BARE = re.compile(rf"(?<![\w])(?P<who>(?P<latin>{_LATIN}){_LATIN_TAIL})\s*,?\s+(?P<year>{_YEAR})(?![\d])")

_NOT_AUTHORS = {"In", "See", "Fig", "Figure", "Table", "Vol", "No", "Since", "From", "By", "The", "Ed", "Eds", "Ch", "Chapter", "AD", "BC", "CE", "BCE"}
# 연도 앞에 자주 오지만 저자가 아닌 한국어 낱말
_NOT_KOREAN_AUTHORS = {
    "연도", "논문", "연구", "보고서", "기사", "당시", "이후", "이전", "현재", "출간", "발표", "초판", "개정판", "번역", "원서",
    "합계출산율", "출산율", "인구", "통계", "자료", "기준", "추정", "조사", "건설", "설립", "창립", "개항", "함락", "건국",
    "종합서", "저서", "단행본", "개론서", "번역본", "원본", "자료집", "보고", "판본",  # 실원고: "영문 종합서(2015)"
}
# 이렇게 끝나는 한글 낱말은 지명·기관·사건이다(모스크바 회사, 곡물법 반대 동맹, 안트베르펜 함락)
_NON_PERSON_SUFFIXES = (
    "회사", "동맹", "함락", "조약", "전쟁", "혁명", "운동", "공황", "시장", "협회", "학회", "정부", "제국", "왕국", "왕조",
    "항구", "출산율", "통계", "법", "령", "판", "년", "세기", "시대", "선언", "회의", "박람회", "철도", "은행", "대학",
)
# 한글 저자 뒤에 붙는 조사(긴 것부터). 은·이·가·의·도·로·만처럼 실제 이름 끝에 흔한 글자(김성은, 카를로,
# 호프만)는 넣지 않는다. 실원고 보정에서 '김성은 → 김성'으로 잘리는 것을 확인했다.
_PARTICLES = ("에서는", "에게서", "으로는", "에서", "에게", "으로", "처럼", "보다", "까지", "부터", "조차", "는", "를")


@dataclass(frozen=True)
class Citation:
    author: str
    year: str
    key: str  # 대표 key(조사를 뗀 것)
    start: int
    candidates: tuple[str, ...] = ()  # 찾아볼 순서: 원형 → 조사 뗀 것
    coauthors: tuple[str, ...] = ()  # 같은 첫 저자·연도 문헌이 여럿일 때 가르는 데 쓴다

    @property
    def lookup_keys(self) -> tuple[str, ...]:
        return self.candidates or (self.key,)

    @property
    def hangul(self) -> bool:
        return bool(re.search(r"[가-힣]", self.author))


def make_ref_key(author: str, year: str) -> str:
    """key 규칙: 괄호 속 읽기는 버리고, 한자가 있으면 한자, 한글이 있으면 한글, 아니면 발음 부호를 뗀 소문자 영문."""
    main = re.sub(r"\([^)]*\)", "", author).strip() or author
    if re.search(r"[一-鿿㐀-䶿]", main):
        return re.sub(r"[^一-鿿㐀-䶿]", "", main) + year.lower()
    if re.search(r"[가-힣]", main):
        return re.sub(r"[^가-힣]", "", main) + year.lower()
    ascii_name = unicodedata.normalize("NFKD", main).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z]", "", ascii_name) or "anon") + year.lower()


def strip_particle(name: str) -> str:
    for particle in _PARTICLES:
        if name.endswith(particle) and len(name) - len(particle) >= 2:
            return name[: -len(particle)]
    return name


def _citation(author: str, year: str, start: int) -> Citation | None:
    author = author.strip()
    if author in _NOT_AUTHORS:
        return None
    if re.fullmatch(r"[가-힣]{1,8}", author):
        stem = strip_particle(author)
        if stem in _NOT_KOREAN_AUTHORS or author in _NOT_KOREAN_AUTHORS or stem.endswith(_NON_PERSON_SUFFIXES):
            return None
        original, stripped = make_ref_key(author, year), make_ref_key(stem, year)
        return Citation(stem, year, stripped, start, tuple(dict.fromkeys([original, stripped])))
    key = make_ref_key(author, year)
    return Citation(author, year, key, start, (key,))


def is_excluded(text: str, start: int, author: str, exclude: frozenset[str] | set[str]) -> bool:
    """프로젝트의 비인용 용어(지명·사건)인가. '모스크바 회사'처럼 여러 낱말이면 저자 앞 글과 이어서 본다."""
    if not exclude:
        return False
    context = re.sub(r"\s+", " ", text[max(0, start - 30) : start] + author).strip()
    return author in exclude or any(context.endswith(term) for term in exclude)


def find_citations(text: str, *, bare: bool = False, exclude: frozenset[str] | set[str] = frozenset()) -> list[Citation]:
    """본문 순서대로 돌려준다. bare=True면 괄호 없는 '저자 연도' 표기도 찾는다(코멘트용).
    exclude: 프로젝트의 비인용 용어(book/non_citation_terms.txt). 여기 걸리는 것은 인용으로 보지 않는다."""
    found: dict[int, Citation] = {}

    def add(m: re.Match[str], offset: int = 0) -> None:
        group = next(g for g in ("latin", "han", "hangul") if g in m.re.groupindex and m.group(g))
        start = offset + m.start(group)
        if is_excluded(text, start, m.group(group), exclude):
            return
        if c := _citation(m.group(group), m.group("year"), start):
            tail = m.group("who")[len(m.group(group)) :]
            names = re.findall(rf"{_LATIN_WORD}|[가-힣]{{1,8}}", tail)
            coauthors = tuple(n for n in names if n not in ("et", "al", "외", "등", "와", "과", "and"))
            candidates = c.candidates
            if group == "hangul" and (prev := re.search(r"([가-힣]{2,6})\s$", text[max(0, start - 8) : start])):
                # 띄어 쓴 일본·중국 이름(다시로 가즈이(1981))은 앞 낱말과 붙인 것도 후보로 둔다(aliases와 맞추기)
                candidates = (*candidates, make_ref_key(prev.group(1) + c.author, c.year))
            found.setdefault(start, replace(c, coauthors=coauthors, candidates=candidates))

    for group in _PAREN_GROUP.finditer(text):
        offset = group.start(1)
        for part in re.finditer(r"[^;]+", group.group(1)):
            if m := _PAREN_PART.search(part.group()):
                add(m, offset + part.start())
    for m in _NARRATIVE.finditer(text):
        add(m)
    if bare:
        for m in _BARE.finditer(text):
            add(m)
    return [found[pos] for pos in sorted(found)]
