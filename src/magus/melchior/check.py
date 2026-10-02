"""인용 게이트. 본문에서 인용을 뽑아 refs와 대조한다: verified / unverified / unknown(refs에 아예 없음).

쓰기를 막지 않는다. 표시하고 집계할 뿐이고, 판단은 사용자가 한다.
- book_write_chapter가 쓴 뒤에 자동으로 돌고, 장별 미확인 인용 수(unverified + unknown 출현 수)를 인덱스에 기록한다.
- refs가 바뀌면(ref_add, ref_import_bibliography, book_import) 사용자의 모든 장 집계와 citation 이슈 연결을 다시 계산한다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from magus.melchior.citations import find_citations, make_ref_key, strip_particle
from magus.store import Ref, Store

NEEDS_SOURCE = re.compile(r"\[출처 필요[:：][^\]]*\]")


@dataclass
class CiteGroup:
    key: str
    status: str  # verified | unverified | unknown
    cited_as: list[str] = field(default_factory=list)
    title: str = ""

    @property
    def count(self) -> int:
        return len(self.cited_as)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"key": self.key, "count": self.count, "cited_as": sorted(set(self.cited_as))}
        if self.title:
            out["title"] = self.title[:80]
        return out


@dataclass
class CheckResult:
    groups: list[CiteGroup]
    needs_source: int

    def of(self, status: str) -> list[CiteGroup]:
        return [g for g in self.groups if g.status == status]

    @property
    def unchecked_count(self) -> int:
        """장 목록의 '미확인인용' 숫자: verified가 아닌 인용의 출현 수."""
        return sum(g.count for g in self.groups if g.status != "verified")

    def unverified_cites(self) -> list[dict[str, object]]:
        return [{**g.as_dict(), "status": g.status} for g in self.groups if g.status != "verified"]

    def as_dict(self) -> dict[str, object]:
        return {
            "verified": [g.as_dict() for g in self.of("verified")],
            "unverified": [g.as_dict() for g in self.of("unverified")],
            "unknown": [g.as_dict() for g in self.of("unknown")],
            "needs_source": self.needs_source,
        }


def resolve_keys(store: Store, user_id: str, keys: tuple[str, ...] | list[str]) -> Ref | None:
    for key in keys:
        if ref := store.resolve_ref(user_id, key):
            return ref
    return None


def check_text(store: Store, user_id: str, text: str) -> CheckResult:
    groups: dict[str, CiteGroup] = {}
    for c in find_citations(text):
        ref = resolve_keys(store, user_id, c.lookup_keys)
        key = ref.key if ref else c.key
        group = groups.setdefault(
            key,
            CiteGroup(key, ref.status if ref else "unknown", title=str(ref.bib.get("title", "")) if ref else ""),
        )
        group.cited_as.append(f"{c.author}({c.year})")
    order = {"unknown": 0, "unverified": 1, "verified": 2}
    return CheckResult(sorted(groups.values(), key=lambda g: (order[g.status], g.key)), len(NEEDS_SOURCE.findall(text)))


def check_chapter(store: Store, user_id: str, project_id: str, number: int) -> CheckResult | None:
    chapter = store.read_chapter(user_id, project_id, number)
    if chapter is None:
        return None
    result = check_text(store, user_id, chapter.content)
    store.set_cite_counts(user_id, project_id, {number: result.unchecked_count})
    return result


def refresh_cite_counts(store: Store, user_id: str) -> None:
    """refs가 바뀐 뒤나 인덱스를 다시 만든 뒤에 사용자의 모든 장 집계를 다시 계산한다."""
    for project in store.list_projects(user_id):
        counts = {}
        for meta in store.list_chapters(user_id, project.id):
            chapter = store.read_chapter(user_id, project.id, meta.number)
            if chapter is not None:
                counts[meta.number] = check_text(store, user_id, chapter.content).unchecked_count
        store.set_cite_counts(user_id, project.id, counts)


def _issue_lookup_keys(ref_key: str) -> list[str]:
    m = re.fullmatch(r"(?P<name>.*?)(?P<year>(?:1[5-9]|20)\d{2}[a-z]?)", ref_key)
    if not m or not re.search(r"[가-힣]", m.group("name")):
        return [ref_key]
    return list(dict.fromkeys([ref_key, make_ref_key(strip_particle(m.group("name")), m.group("year"))]))


def link_citation_issues(store: Store, user_id: str) -> int:
    """citation 이슈의 ref_key를 refs에서 해석해 ref_id(정식 key)로 기록한다. 바뀐 이슈 수를 돌려준다."""
    changed = 0
    for project in store.list_projects(user_id):
        updates: dict[int, str | None] = {}
        for issue in store.list_issues(user_id, project.id, None, kind="citation"):
            ref = resolve_keys(store, user_id, _issue_lookup_keys(issue.ref_key)) if issue.ref_key else None
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
        for meta in store.list_chapters(user_id, project.id):
            chapter = store.read_chapter(user_id, project.id, meta.number)
            if chapter and any(g.key == key for g in check_text(store, user_id, chapter.content).groups):
                out[project.id].append(meta.number)
    return dict(out)
