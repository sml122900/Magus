"""인용 게이트. 본문에서 인용을 뽑아 refs와 대조한다.

결과 네 갈래: verified / unverified(refs에 있으나 미확인) / unknown(refs에 없음) /
uncertain(한글 표기인데 refs와 이어지지 않음 — 인명이면 aliases가 필요하고, 지명·사건이면 무시해도 된다).
해석 순서: key → aliases → (한글 표기만) 같은 연도 문헌과 음역 추정.

쓰기를 막지 않는다. 표시하고 집계할 뿐이고, 판단은 사용자가 한다.
- 장별 미확인 인용 수 = verified가 아닌 **고유 문헌 수**(unverified + unknown, uncertain 제외). 파생값이다.
- 각 문헌의 출현 위치(장 본문의 문단 번호)와 표기를 함께 준다.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from magus.melchior.citations import Citation, find_citations, make_ref_key, strip_particle
from magus.melchior.translit import best_match
from magus.store import Ref, Store
from magus.store.base import CiteKeys

NEEDS_SOURCE = re.compile(r"\[출처 필요[:：][^\]]*\]")
STATUS_ORDER = {"unknown": 0, "unverified": 1, "uncertain": 2, "verified": 3}


@dataclass
class CiteGroup:
    key: str
    status: str  # verified | unverified | unknown | uncertain
    title: str = ""
    matched_by: str = ""  # "" | "alias" | "음역 추정" | "연도 a/b 모호" | "음역 추정·연도 a/b 모호"
    occurrences: list[tuple[int, str]] = field(default_factory=list)  # (문단 번호, 표기)
    candidates: tuple[tuple[str, str], ...] = ()  # 연도 a/b 모호: 잇지 않고 후보만 보인다 (key, 제목)

    @property
    def count(self) -> int:
        return len(self.occurrences)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "key": self.key,
            "count": self.count,
            "cited_as": sorted({c for _, c in self.occurrences}),
            "paragraphs": sorted({p for p, _ in self.occurrences}),
        }
        if self.matched_by:
            out["matched_by"] = self.matched_by
        if self.title:
            out["title"] = self.title[:80]
        if self.candidates:
            out["candidates"] = [{"key": k, "title": t[:80]} for k, t in self.candidates]
        return out


@dataclass
class CheckResult:
    groups: list[CiteGroup]
    needs_source: int

    def of(self, status: str) -> list[CiteGroup]:
        return [g for g in self.groups if g.status == status]

    @property
    def unchecked_count(self) -> int:
        """장 목록의 '미확인인용' 숫자: verified가 아닌 고유 문헌 수(unverified + unknown). uncertain은 따로 센다."""
        return len(self.unchecked_keys)

    @property
    def unchecked_keys(self) -> list[str]:
        return [g.key for g in self.groups if g.status in ("unverified", "unknown")]

    @property
    def uncertain_keys(self) -> list[str]:
        """한글 표기인데 refs와 잇지 못한 것. 미확인 수에서는 빼지만 숨기지 않는다(outline '미연결', ref_check 목록)."""
        return [g.key for g in self.groups if g.status == "uncertain"]

    def unverified_cites(self) -> list[dict[str, object]]:
        return [{**g.as_dict(), "status": g.status} for g in self.groups if g.status != "verified"]

    def as_dict(self) -> dict[str, object]:
        return {
            "verified": [g.as_dict() for g in self.of("verified")],
            "unverified": [g.as_dict() for g in self.of("unverified")],
            "unknown": [g.as_dict() for g in self.of("unknown")],
            "uncertain": [g.as_dict() for g in self.of("uncertain")],
            "needs_source": self.needs_source,
            "unique_unchecked": self.unchecked_count,
            "unique_uncertain": len(self.uncertain_keys),
        }


def cite_floors(store: Store, user_id: str, project_id: str) -> tuple[str, ...]:
    """원고의 인용 점검이 보는 문헌의 프로젝트: 그 프로젝트의 문헌 + 지도의 연결 노드가 가리키는 노드에 꽂힌 문헌(#95).
    다른 프로젝트의 문헌은 연결하지 않으면 보지 않는다."""
    return store.cite_scope(user_id, project_id)


class Resolver:
    """인용 → ref. 한 번의 검사(또는 일괄 집계) 동안 연도별 문헌 목록을 한 번만 읽는다.
    project_id를 주면 그 원고가 보는 문헌(cite_floors)만 본다. 없으면 사람의 모든 문헌."""

    def __init__(self, store: Store, user_id: str, project_id: str | None = None):
        self.store, self.user_id = store, user_id
        self.floors = cite_floors(store, user_id, project_id) if project_id else None
        self._by_year: dict[str, list[tuple[str, str]]] | None = None

    def _years(self) -> dict[str, list[tuple[str, str]]]:
        """네 자리 연도 → (key, 영문 성). 1930a·1930b는 1930으로 묶는다."""
        if self._by_year is None:
            self._by_year = defaultdict(list)
            for ref in self.store.list_refs(self.user_id, floors=self.floors):
                year, surname = str(ref.bib.get("year", ""))[:4], str(ref.bib.get("first_author", ""))
                if year.isdigit() and surname and not re.search(r"[가-힣一-鿿]", surname):
                    self._by_year[year].append((ref.key, surname))
        return self._by_year

    def resolve(
        self,
        keys: tuple[str, ...] | list[str],
        hangul: str | None = None,
        year: str | None = None,
        coauthors: tuple[str, ...] = (),
    ) -> tuple[Ref | None, str, tuple[Ref, ...]]:
        """(ref, 어떻게 이었나, 후보). 연도 a/b가 모호하면 잇지 않고 후보만 돌려준다(ref=None, 사용자 결정 #31)."""
        for key in keys:
            if ref := self.store.resolve_ref(self.user_id, key, floors=self.floors):
                return self._disambiguate(ref, coauthors), ("" if ref.key == key else "alias"), ()
        for key in keys:  # Keynes(1930)인데 참고문헌에는 1930a·1930b만 있는 경우
            if re.search(r"\d$", key) and (variants := self._suffixed(key)):
                if len(variants) == 1:
                    return variants[0], "", ()
                return None, "연도 a/b 모호", tuple(variants)
        if hangul and year:
            candidates = self._years().get(year[:4], [])
            bases = {re.sub(r"(\d{4})[a-z]$", r"\1", k): s for k, s in candidates}
            if base := best_match(hangul, list(bases.items())):
                variants = sorted(k for k, _ in candidates if re.sub(r"(\d{4})[a-z]$", r"\1", k) == base)
                refs = tuple(r for r in (self.store.get_ref(self.user_id, k, floors=self.floors) for k in variants) if r)
                if len(refs) == 1:
                    return refs[0], "음역 추정", ()
                return None, "음역 추정·연도 a/b 모호", refs
        return None, "", ()

    def _suffixed(self, key: str) -> list[Ref]:
        """key + a, b, c … 로 있는 문헌들."""
        out = []
        for suffix in "abcdefgh":
            if not (ref := self.store.get_ref(self.user_id, key + suffix, floors=self.floors)):
                break
            out.append(ref)
        return out


    def _disambiguate(self, ref: Ref, coauthors: tuple[str, ...]) -> Ref:
        """같은 첫 저자·연도 문헌(acemoglu2001, acemoglu2001-2)이 있으면 인용의 공저자 이름으로 가린다."""
        base = re.sub(r"-\d+$", "", ref.key)
        siblings = [r for r in (self.store.get_ref(self.user_id, f"{base}-{n}", floors=self.floors) for n in range(2, 10)) if r]
        if not siblings or not coauthors:
            return ref
        candidates = [r for r in (self.store.get_ref(self.user_id, base, floors=self.floors), *siblings) if r]
        folded = [_fold(c) for c in coauthors]
        matches = [r for r in candidates if all(c in _fold(str(r.bib.get("authors", ""))) for c in folded)]
        return matches[0] if len(matches) == 1 else ref


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _paragraph_starts(text: str) -> list[int]:
    return [0, *(m.end() for m in re.finditer(r"\n\s*\n", text))]


def terms_of(store: Store, user_id: str, project_id: str) -> frozenset[str]:
    """프로젝트의 비인용 용어(book/non_citation_terms.txt)."""
    return frozenset(store.get_non_citation_terms(user_id, project_id))


def check_text(
    store: Store, user_id: str, text: str, resolver: Resolver | None = None, exclude: frozenset[str] = frozenset()
) -> CheckResult:
    resolver = resolver or Resolver(store, user_id)
    starts = _paragraph_starts(text)
    groups: dict[str, CiteGroup] = {}
    for c in find_citations(text, exclude=exclude):
        ref, how, candidates = resolver.resolve(c.lookup_keys, c.author if c.hangul else None, c.year, c.coauthors)
        if ref:
            key, status = ref.key, ref.status
        elif candidates:  # 연도 a/b 모호: 어느 것에도 잇지 않는다. 한 문헌으로 세고 상태는 unverified
            key, status = ambiguous_key(candidates), "unverified"
        else:
            key, status = c.key, ("uncertain" if c.hangul else "unknown")
        group = groups.setdefault(
            key,
            CiteGroup(
                key, status, str(ref.bib.get("title", "")) if ref else "", how,
                candidates=tuple((r.key, str(r.bib.get("title", ""))) for r in candidates),
            ),
        )
        group.occurrences.append((bisect.bisect_right(starts, c.start), _surface(c)))
    ordered = sorted(groups.values(), key=lambda g: (STATUS_ORDER[g.status], -g.count, g.key))
    return CheckResult(ordered, len(NEEDS_SOURCE.findall(text)))


def ambiguous_key(candidates: tuple[Ref, ...]) -> str:
    """keynes1930a·keynes1930b → 'keynes1930a/b'. 어느 ref key와도 겹치지 않는다."""
    keys = sorted(r.key for r in candidates)
    base = re.sub(r"[a-z]$", "", keys[0])
    return base + "/".join(k[len(base):] for k in keys)


def _surface(c: Citation) -> str:
    return f"{c.author}({c.year})"


def check_chapter(store: Store, user_id: str, project_id: str, number: int, resolver: Resolver | None = None) -> CheckResult | None:
    chapter = store.read_chapter(user_id, project_id, number)
    if chapter is None:
        return None
    resolver = resolver or Resolver(store, user_id, project_id)
    result = check_text(store, user_id, chapter.content, resolver, terms_of(store, user_id, project_id))
    store.set_cite_keys(user_id, project_id, {number: CiteKeys(result.unchecked_keys, result.uncertain_keys)})
    return result


def refresh_cite_counts(store: Store, user_id: str) -> None:
    """refs가 바뀐 뒤(책 옮기기·연결 노드 포함)나 인덱스를 다시 만든 뒤에 사용자의 모든 장 집계를 다시 계산한다."""
    for project in store.list_projects(user_id):
        resolver = Resolver(store, user_id, project.id)
        terms = terms_of(store, user_id, project.id)
        cites = {}
        for meta in store.list_chapters(user_id, project.id):
            chapter = store.read_chapter(user_id, project.id, meta.number)
            if chapter is not None:
                result = check_text(store, user_id, chapter.content, resolver, terms)
                cites[meta.number] = CiteKeys(result.unchecked_keys, result.uncertain_keys)
        store.set_cite_keys(user_id, project.id, cites)


def _issue_lookup(ref_key: str) -> tuple[list[str], str | None, str | None]:
    m = re.fullmatch(r"(?P<name>.*?)(?P<year>(?:1[5-9]|20)\d{2}[a-z]?)", ref_key)
    if not m or not re.search(r"[가-힣]", m.group("name")):
        return [ref_key], None, None
    name, year = m.group("name"), m.group("year")
    return list(dict.fromkeys([ref_key, make_ref_key(strip_particle(name), year)])), name, year


def link_citation_issues(store: Store, user_id: str) -> int:
    """citation 이슈를 refs에서 해석해 ref_id(정식 key)로 기록한다. 바뀐 이슈 수를 돌려준다.
    코멘트 문장에서 인용을 다시 뽑아 후보 전체(원형·조사 뗀 것·앞 낱말과 붙인 것·공저자)로 찾고, 문장에서 못 뽑으면
    저장된 ref_key로 찾는다(사람이 issues.md에 직접 적은 경우)."""
    from magus.book.comments import COMMENT_ANCHOR_SPLIT

    changed = 0
    for project in store.list_projects(user_id):
        resolver = Resolver(store, user_id, project.id)
        terms = terms_of(store, user_id, project.id)
        updates: dict[int, str | None] = {}
        for issue in store.list_issues(user_id, project.id, None, kind="citation"):
            comment = issue.text.partition(COMMENT_ANCHOR_SPLIT)[0]  # 이슈에 남은 앵커는 120자로 잘려 있다
            ref = None
            if cite := next(iter(find_citations(comment, bare=True, exclude=terms)), None):
                ref, _, _ = resolver.resolve(cite.lookup_keys, cite.author if cite.hangul else None, cite.year, cite.coauthors)
            elif issue.ref_key:
                keys, hangul, year = _issue_lookup(issue.ref_key)
                ref, _, _ = resolver.resolve(keys, hangul, year)
            new = ref.key if ref else None
            if new != issue.ref_id:
                updates[issue.id] = new
        store.set_issue_refs(user_id, project.id, updates)
        changed += len(updates)
    return changed


def after_refs_changed(store: Store, user_id: str) -> int:
    refresh_cite_counts(store, user_id)
    return link_citation_issues(store, user_id)


def chapters_citing(store: Store, user_id: str, key: str) -> dict[str, list[int]]:
    """이 ref를 인용하는 장들(프로젝트별). ref_add 응답에서 영향받는 장을 알려 줄 때 쓴다."""
    out: dict[str, list[int]] = defaultdict(list)
    for project in store.list_projects(user_id):
        resolver = Resolver(store, user_id, project.id)
        terms = terms_of(store, user_id, project.id)
        for meta in store.list_chapters(user_id, project.id):
            chapter = store.read_chapter(user_id, project.id, meta.number)
            if chapter and any(g.key == key for g in check_text(store, user_id, chapter.content, resolver, terms).groups):
                out[project.id].append(meta.number)
    return dict(out)
