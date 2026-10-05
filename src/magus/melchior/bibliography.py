"""참고문헌 목록 → refs(status=unverified). 줄 하나가 문헌 하나다.

지원 형식: APA식 "저자 (연도). 제목. 출처." 영문·국문 모두. 연도가 맨 끝에 오는 형식은 근사 파싱한다.
"[국역: 오데드 갤러, 『인류의 여정』, …, 2023]" 꼬리가 있으면 한글 성 + (원서 연도, 번역서 연도)를 aliases에 넣는다.
연도나 저자를 못 찾은 줄은 key "raw-<해시>"로 bib.raw만 보관하고 리포트에 남긴다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
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
_READING = re.compile(r"^(?P<name>[一-鿿㐀-䶿]{1,10})\s*\((?P<reading>[가-힣 ]{2,20})\)")
_BRACKETED_TITLE = re.compile(r"^[『《「“\"](?P<title>[^』》」”\"]+)[』》」”\"]")


@dataclass
class BibReport:
    lines: int = 0
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)  # 같은 문헌(저자·연도·제목)이 목록에 두 번: 원고 오류일 수 있다
    differs: list[str] = field(default_factory=list)  # 이미 있는 key인데 새 목록의 제목·연도가 다름(갱신하지 않음)

    def render(self) -> str:
        out = [
            f"참고문헌 {self.lines}줄 → 새 refs {len(self.created)}건(unverified), 이미 있음 {len(self.existing)}건, "
            f"파싱 실패 {len(self.failed)}줄, key 충돌 {len(self.collisions)}건, 중복 서지 {len(self.duplicates)}건, "
            f"기존 서지와 다름 {len(self.differs)}건"
        ]
        out += [f"- 파싱 실패: {line[:100]}" for line in self.failed]
        out += [f"- key 충돌: {c}" for c in self.collisions]
        out += [f"- 중복 서지(목록에 두 번): {d}" for d in self.duplicates]
        out += [f"- 기존 서지와 다름(갱신하지 않음): {d}" for d in self.differs]
        return "\n".join(out)


def _norm(text: object) -> str:
    return re.sub(r"[\W_]+", " ", str(text or "").lower()).strip()


def _identity(ref: Ref) -> tuple[str, ...]:
    """같은 문헌인지 가리는 값: 원문 줄이 같거나, 첫 저자·연도·제목이 같으면 같은 문헌이다."""
    if "first_author" not in ref.bib:
        return ("raw", _norm(ref.bib.get("raw")))
    return (_norm(ref.bib.get("first_author")), str(ref.bib.get("year", "")), _norm(ref.bib.get("title")))


def _differences(old: Ref, new: Ref) -> list[str]:
    out = []
    for name, label in (("title", "제목"), ("year", "연도")):
        before, after = old.bib.get(name), new.bib.get(name)
        if before and after and _norm(before) != _norm(after):
            out.append(f"{label} '{str(before)[:50]}' → 새 목록 '{str(after)[:50]}'")
    return out


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
    reading = None
    if m := _READING.match(text):  # 田代和生(다시로 가즈이). (1981). … — 한자 이름 뒤의 한글 읽기
        reading = m.group("reading").strip()
        text = m.group("name") + text[m.end() :]
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
        # "IEA (International Energy Agency). (2025). Energy and AI." — 저자에 괄호가 있어 APA로 못 읽은 줄은
        # 남은 글이 "(2025). 제목"으로 시작한다. 연도 괄호를 떼야 제목이 "(2025)"가 되지 않는다(key는 그대로).
        rest = re.sub(rf"^\(\s*{_YEAR}\s*\)\s*[.,]?\s*", "", rest.strip())
        title, container = _title_and_rest(rest)
        approx = True
    else:
        return None
    first = first_author(authors)
    if not first or not re.search(r"[A-Za-z가-힣一-鿿]", first):
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
    if reading:
        bib["reading"] = reading
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
    if reading := bib.get("reading"):  # 한자 이름의 한글 읽기: 성(첫 낱말)과 전체를 aliases로
        aliases += [f"{reading.split()[0]}{bib['year']}", f"{reading.replace(' ', '')}{bib['year']}"]
    return Ref(key=key, status="unverified", bib=bib, aliases=tuple(dict.fromkeys(aliases)))


def _same_document(a: Ref, b: Ref) -> bool:
    """첫 저자·연도가 같고 제목이 거의 같으면(공백·부호 무시, 80% 이상) 같은 문헌이다. 파싱 못 한 줄은 원문 줄로 본다."""
    if "first_author" not in a.bib or "first_author" not in b.bib:
        return _norm(a.bib.get("raw")) == _norm(b.bib.get("raw"))
    if (_norm(a.bib.get("first_author")), str(a.bib.get("year"))) != (_norm(b.bib.get("first_author")), str(b.bib.get("year"))):
        return False
    ta, tb = (_norm(r.bib.get("title")).replace(" ", "") for r in (a, b))
    short, long = sorted((ta, tb), key=len)
    if len(short) >= 8 and long.startswith(short):  # 부제를 붙이거나 뗀 것("Gaining ground" ↔ "Gaining ground: The origin …")
        return True
    return ta == tb or SequenceMatcher(None, ta, tb).ratio() >= 0.8


def _keyed(ref: Ref, key: str) -> Ref:
    return Ref(key=key, status=ref.status, bib=ref.bib, aliases=ref.aliases)


def _assign_keys(store: Store, user_id: str, refs: list[Ref]) -> list[tuple[Ref, Ref | None]]:
    """(key를 정한 ref, 이미 있는 같은 문헌). 다시 올려도 같은 문헌은 같은 key를 받는다(#76 key 안정화).

    같은 첫 저자·연도(같은 기본 key) 문헌이 목록에 하나뿐이고 기존 접미사 key도 없으면 예전처럼 기본 key를 쓴다
    (제목이 달라도 같은 문헌으로 보고 '기존 서지와 다름'만 남긴다, 결정 #6).
    둘 이상이면(예: Hsieh 2019 두 편) 기존 refs와 제목으로 짝을 짓는다. 짝이 없는 것만 비어 있는 다음 접미사(-2, -3)를 받는다.
    목록 순서가 바뀌어도 key가 문헌을 따라간다."""
    known = {r.key: r for r in store.list_refs(user_id)}
    groups: dict[str, list[int]] = {}
    for n, ref in enumerate(refs):
        groups.setdefault(ref.key, []).append(n)
    out: list[tuple[Ref, Ref | None] | None] = [None] * len(refs)
    for base, members in groups.items():
        variants = [base, *(k for k in (f"{base}-{n}" for n in range(2, 100)) if k in known)]
        stored = [known[k] for k in variants if k in known]
        if len(members) == 1 and len(stored) <= 1:
            out[members[0]] = (refs[members[0]], stored[0] if stored else None)
            continue
        free = iter(k for k in (base, *(f"{base}-{n}" for n in range(2, 1000))) if k not in known)
        taken: set[str] = set()
        for n in members:
            match = next((r for r in stored if r.key not in taken and _same_document(r, refs[n])), None)
            key = match.key if match else next(free)
            taken.add(key)
            out[n] = (_keyed(refs[n], key), match)
    return [o for o in out if o is not None]


def import_bibliography(store: Store, user_id: str, text: str) -> BibReport:
    report = BibReport()
    lines, refs = [], []
    for line in (raw.strip() for raw in text.splitlines()):
        if not line or _HEADING.match(line):
            continue
        report.lines += 1
        bib = parse_bib_line(line)
        if bib is None:
            report.failed.append(line)
            refs.append(Ref(key="raw-" + hashlib.sha1(line.encode()).hexdigest()[:8], status="unverified", bib={"raw": line}))
        else:
            refs.append(ref_from_bib(bib))
        lines.append(line)
    identities: dict[tuple[str, ...], str] = {}
    titled: dict[tuple[str, str], str] = {}  # (연도, 제목): 첫 저자 표기가 달라도 같은 문헌(IEA ↔ International Energy Agency)
    for line, base, (ref, existing) in zip(lines, (r.key for r in refs), _assign_keys(store, user_id, refs), strict=True):
        if (same := identities.get(_identity(ref))) is not None:
            report.duplicates.append(f"{same} = {line[:70]}")
        elif len(title := _norm(ref.bib.get("title"))) >= 8 and (same := titled.get((str(ref.bib.get("year")), title))):
            report.duplicates.append(f"{same} = {line[:70]} (제목·연도가 같고 저자 표기만 다름)")
        identities.setdefault(_identity(ref), ref.key)
        if len(title) >= 8:
            titled.setdefault((str(ref.bib.get("year")), title), ref.key)
        if ref.key != base:  # 같은 기본 key(같은 성·연도)가 겹치면 뒤의 것에 -2, -3이 붙는다
            report.collisions.append(f"{base} → {ref.key}: {line[:60]}")
        if existing is not None:
            report.existing.append(ref.key)
            if diff := _differences(existing, ref):
                report.differs.append(f"{ref.key}: {'; '.join(diff)}")
            continue
        store.put_ref(user_id, ref)
        report.created.append(ref.key)
    return report
