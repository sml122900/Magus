"""책 전체 인용 집계 — 확인을 시작할 순서를 정하기 위한 리포트(`magus cite-report`).

- 전체·장별 고유 미확인 문헌 수(unverified + unknown)
- 가장 많이 인용된 미확인 문헌 상위 N개: key, 출현 횟수, 등장 장
- 본문에서 인용했지만 참고문헌에 없는 문헌(unknown)과, 한글 표기라 판정을 미룬 것(uncertain)
- 참고문헌에는 있지만 본문에서 한 번도 인용되지 않은 항목
- 음역 추정으로 이은 것(사람이 확인할 것)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from magus.melchior.check import Resolver, check_text, terms_of
from magus.store import Store


@dataclass
class DocStat:
    key: str
    status: str
    title: str = ""
    matched_by: str = ""
    count: int = 0
    chapters: list[str] = field(default_factory=list)
    cited_as: set[str] = field(default_factory=set)
    inferred: set[str] = field(default_factory=set)  # 음역 추정·연도 모호로 이은 표기("모리스(2010)")
    hint: str = ""  # unknown일 때: 같은 저자의 다른 연도 항목


@dataclass
class CiteReport:
    per_chapter: list[tuple[str, str, int, int, int]]  # (표시, 제목, 고유 미확인, 출현, [출처 필요])
    docs: dict[str, DocStat]
    uncited: list[tuple[str, str]]  # (key, raw)
    needs_source: int

    def of(self, *statuses: str) -> list[DocStat]:
        return [d for d in self.docs.values() if d.status in statuses]

    def render(self, top: int = 20) -> str:
        unchecked = self.of("unverified", "unknown")
        lines = [
            f"- 고유 미확인 문헌: **{len(unchecked)}건**(참고문헌에 있으나 미확인 {len(self.of('unverified'))} · "
            f"참고문헌에 없음 {len(self.of('unknown'))}) · 인용 출현 {sum(d.count for d in unchecked)}회",
            f"- verified {len(self.of('verified'))}건 · 한글 표기 미해결(uncertain) {len(self.of('uncertain'))}건 · "
            f"[출처 필요] 표시 {self.needs_source}곳 · 참고문헌 중 본문 미인용 {len(self.uncited)}건",
            "",
            "#### 장별 고유 미확인 문헌 수",
            "",
            "| 장 | 제목 | 고유 미확인 | 인용 출현 | [출처 필요] |",
            "|---|---|---:|---:|---:|",
            *(f"| {d} | {t} | {u} | {o} | {n} |" for d, t, u, o, n in self.per_chapter),
            "",
            f"#### 가장 많이 인용된 미확인 문헌 상위 {top} (확인을 시작할 순서)",
            "",
            "| 순위 | key | 상태 | 출현 | 등장 장 | 표기 | 제목 |",
            "|---:|---|---|---:|---|---|---|",
        ]
        ranked = sorted(unchecked, key=lambda d: (-d.count, -len(d.chapters), d.key))[:top]
        lines += [
            f"| {n} | {d.key} | {d.status}{' (' + d.matched_by + ')' if d.matched_by else ''} | {d.count} | "
            f"{', '.join(d.chapters)} | {', '.join(sorted(d.cited_as))[:60]} | {d.title[:50].replace('|', '/')} |"
            for n, d in enumerate(ranked, 1)
        ]
        lines += ["", "#### 본문에서 인용했지만 참고문헌에 없는 문헌 (unknown)", ""]
        lines += [
            f"- {d.key} ×{d.count} — {', '.join(d.chapters)} — {', '.join(sorted(d.cited_as))}"
            + (f" — 참고문헌의 비슷한 항목: {d.hint}" if d.hint else "")
            for d in sorted(self.of("unknown"), key=lambda d: (-d.count, d.key))
        ] or ["- 없음"]
        lines += ["", "#### 한글 표기인데 참고문헌과 잇지 못한 것 (uncertain: 인명이면 aliases 필요, 지명·사건이면 무시)", ""]
        lines += [
            f"- {d.key} ×{d.count} — {', '.join(d.chapters)} — {', '.join(sorted(d.cited_as))}"
            for d in sorted(self.of("uncertain"), key=lambda d: (-d.count, d.key))
        ] or ["- 없음"]
        lines += ["", "#### 추정으로 이은 것 (음역 추정·연도 a/b 모호 — 맞는지 확인 필요)", ""]
        lines += [
            f"- {', '.join(sorted(d.inferred))} ⇒ {d.key} — {d.title[:50]}"
            for d in sorted(self.docs.values(), key=lambda d: d.key) if d.inferred
        ] or ["- 없음"]
        lines += ["", f"#### 참고문헌에는 있지만 본문에서 인용되지 않은 항목 ({len(self.uncited)}건)", ""]
        lines += [f"- {key} — {raw[:90]}" for key, raw in self.uncited] or ["- 없음"]
        return "\n".join(lines)


def build_cite_report(store: Store, user_id: str, project_id: str) -> CiteReport:
    resolver = Resolver(store, user_id)
    terms = terms_of(store, user_id, project_id)
    docs: dict[str, DocStat] = {}
    per_chapter = []
    needs_source = 0
    for meta in store.list_chapters(user_id, project_id):
        chapter = store.read_chapter(user_id, project_id, meta.number)
        if chapter is None:
            continue
        result = check_text(store, user_id, chapter.content, resolver, terms)
        needs_source += result.needs_source
        per_chapter.append(
            (meta.display, meta.title, result.unchecked_count,
             sum(g.count for g in result.groups if g.status in ("unverified", "unknown")), result.needs_source)
        )
        for g in result.groups:
            doc = docs.setdefault(g.key, DocStat(g.key, g.status, g.title))
            doc.count += g.count
            doc.chapters.append(str(meta.number) if meta.label is None else meta.display)
            doc.cited_as.update(c for _, c in g.occurrences)
            if g.matched_by not in ("", "alias"):
                doc.inferred.update(f"{c} [{g.matched_by}]" for _, c in g.occurrences)
    refs = store.list_refs(user_id)
    for doc in docs.values():
        if doc.status == "unknown" and (name := re.sub(r"\d{4}[a-z]?(-\d+)?$", "", doc.key)):
            similar = [r.key for r in refs if re.sub(r"\d{4}[a-z]?(-\d+)?$", "", r.key) == name]
            doc.hint = ", ".join(similar[:4])
    cited = set(docs)
    uncited = [
        (ref.key, str(ref.bib.get("raw", "")))
        for ref in refs
        if ref.key not in cited and not ref.key.startswith("raw-")
    ]
    return CiteReport(per_chapter, docs, uncited, needs_source)
