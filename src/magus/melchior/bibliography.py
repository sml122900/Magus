"""참고문헌 목록 → refs(status=unverified). 줄 하나가 문헌 하나다.

지원 형식: APA식 "저자 (연도). 제목. 출처." 영문·국문 모두. 연도가 맨 끝에 오는 형식은 근사 파싱한다.
"[국역: 오데드 갤러, 『인류의 여정』, …, 2023]" 꼬리가 있으면 한글 성 + (원서 연도, 번역서 연도)를 aliases에 넣는다.
연도나 저자를 못 찾은 줄은 key "raw-<해시>"로 bib.raw만 보관하고 리포트에 남긴다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from magus.melchior.citations import make_ref_key
from magus.store import Ref, Store

_HEADING = re.compile(r"^\s*(참\s*고\s*문\s*헌|참고\s*자료|references|bibliography|works cited)\s*$", re.I)
_NUMBERING = re.compile(r"^\s*(?:\[\d+\]|\d+[.)]|[-•·*])\s+")
_TRANSLATION = re.compile(r"\[\s*국역\s*[:：]\s*(?P<body>[^\]]+)\]")
_YEAR = r"(?:1[5-9]|20)\d{2}[a-z]?"
_APA = re.compile(rf"^(?P<authors>[^()]+?)\s*[,.]?\s*\(\s*(?P<year>{_YEAR})(?:\s*[,/][^)]*)?\s*\)\s*[.,]?\s*(?P<rest>.*)$")
_ANY_YEAR = re.compile(rf"(?<!\d)(?P<year>{_YEAR})(?![\d])")
_AUTHOR_SPLIT = re.compile(r"\s*(?:,|&|·|、|\band\b|\s외\b|\s등\b)\s*")
_BRACKETED_TITLE = re.compile(r"^[『《「“\"](?P<title>[^』》」”\"]+)[』》」”\"]")


@dataclass
class BibReport:
    lines: int = 0
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)

    def render(self) -> str:
        out = [
            f"참고문헌 {self.lines}줄 → 새 refs {len(self.created)}건(unverified), 이미 있음 {len(self.existing)}건, "
            f"파싱 실패 {len(self.failed)}줄, key 충돌 {len(self.collisions)}건"
        ]
        out += [f"- 파싱 실패: {line[:100]}" for line in self.failed]
        out += [f"- key 충돌: {c}" for c in self.collisions]
        return "\n".join(out)


def first_author(authors: str) -> str:
    first = _AUTHOR_SPLIT.split(authors.strip(), maxsplit=1)[0].strip(" .")
    return first


def _title_and_rest(rest: str) -> tuple[str, str]:
    rest = rest.strip()
    if m := _BRACKETED_TITLE.match(rest):
        return m.group("title").strip(), rest[m.end() :].strip(" .,")
    title, sep, tail = rest.partition(". ")
    return title.strip(" ."), tail.strip()


def parse_bib_line(line: str) -> dict[str, Any] | None:
    """한 줄을 bib dict로. 저자나 연도를 못 찾으면 None."""
    raw = line.strip()
    text = _NUMBERING.sub("", raw)
    translation = None
    if m := _TRANSLATION.search(text):
        translation = m.group("body").strip()
        text = (text[: m.start()] + text[m.end() :]).strip()
    if m := _APA.match(text):
        authors, year, rest = m.group("authors").strip(" ,."), m.group("year"), m.group("rest")
        title, container = _title_and_rest(rest)
        approx = False
    elif (y := _ANY_YEAR.search(text)) and "." in text[: y.start()]:
        # "Clack, J. A. Gaining ground. Indiana University Press, 2012." 같은 연도 후치형
        authors_part, _, rest = text.partition(". ")
        if re.fullmatch(r"[A-Z]\.?", authors_part.split(",")[-1].strip()):  # 이니셜에서 잘렸으면 한 번 더
            more, _, rest = rest.partition(". ")
            authors_part = f"{authors_part}. {more}"
        authors, year = authors_part.strip(" ,."), y.group("year")
        title, container = _title_and_rest(rest)
        approx = True
    else:
        return None
    first = first_author(authors)
    if not first or not re.search(r"[A-Za-z가-힣]", first):
        return None
    bib: dict[str, Any] = {
        "authors": authors,
        "first_author": first,
        "year": year,
        "title": title,
        "container": container,
        "raw": raw,
    }
    if approx:
        bib["parse"] = "approx"
    if translation:
        bib["translation"] = translation
    return bib


def ref_from_bib(bib: dict[str, Any]) -> Ref:
    key = make_ref_key(bib["first_author"], bib["year"])
    aliases: list[str] = []
    if tr := bib.get("translation"):
        korean_author = tr.split(",")[0].strip()
        surname = korean_author.split()[-1] if korean_author.split() else ""
        if re.fullmatch(r"[가-힣]{1,8}", surname):
            years = [bib["year"], *(y.group("year") for y in _ANY_YEAR.finditer(tr))]
            aliases = [f"{surname}{y}" for y in dict.fromkeys(years)]
    return Ref(key=key, status="unverified", bib=bib, aliases=tuple(aliases))


def import_bibliography(store: Store, user_id: str, text: str) -> BibReport:
    report = BibReport()
    seen: set[str] = set()
    for line in (raw.strip() for raw in text.splitlines()):
        if not line or _HEADING.match(line):
            continue
        report.lines += 1
        bib = parse_bib_line(line)
        if bib is None:
            report.failed.append(line)
            ref = Ref(key="raw-" + hashlib.sha1(line.encode()).hexdigest()[:8], status="unverified", bib={"raw": line})
        else:
            ref = ref_from_bib(bib)
        if ref.key in seen:  # 같은 목록 안에서 key가 겹치면(예: 같은 성·연도) 뒤의 것에 -2, -3을 붙인다
            n = 2
            while f"{ref.key}-{n}" in seen:
                n += 1
            report.collisions.append(f"{ref.key} → {ref.key}-{n}: {line[:60]}")
            ref = Ref(key=f"{ref.key}-{n}", status=ref.status, bib=ref.bib, aliases=ref.aliases)
        seen.add(ref.key)
        if store.get_ref(user_id, ref.key):
            report.existing.append(ref.key)
            continue
        store.put_ref(user_id, ref)
        report.created.append(ref.key)
    return report
