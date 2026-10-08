"""다시 올리기: 같은 책의 새 판(#76). 원고 본문의 원본은 저자 파일이고(#68) Magus는 최신 업로드의 사본이다.

7단계 전에 넣은 기본 부분(사용자 결정 #76, docs/decisions/reupload-design.md "확정 범위"):
- 같은 책: 사용자가 project_id로 고른다. 장 제목이 기존 판과 30% 미만으로 겹치면 force 없이는 멈춘다.
- 장 대응: 같은 번호 = 같은 장. 제목이 바뀌면 리포트에 적는다. 본문 유사도·이동·분할 판정은 뒤로 미뤘다.
- 본문이 바뀐 장만 다시 쓴다(이전본은 versions/). 그대로인 장은 버전을 올리지 않고 판 번호만 적는다.
  새 판에 없는 장은 removed/로 옮긴다(지우지 않는다).
- 문서 코멘트 → 미해결: 지문(작성자 + 날짜 + 본문)이 같으면 새로 만들지 않는다. 판 기록 전(PDF 등) 미해결은 코멘트 본문으로 잇는다.
  원고에서 코멘트가 지워졌거나 걸린 문장이 없으면 "해결됐을 수 있음"으로 표시만 한다. 자동으로 닫지 않는다.
- 결정·직접 남긴 미해결·책장(영감·문헌·문체)은 건드리지 않는다. 참고문헌은 새 문헌만 더한다(key는 문헌을 따라간다).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from magus.book.comments import COMMENT_ANCHOR_SPLIT
from magus.book.importer import (
    EMPTY_BODY,
    ChapterPlan,
    book_titles,
    chapter_body,
    comment_entries,
    cover_blocks,
    detect_titles,
    read_manuscript,
    split_manuscript,
    unsplit_markdown,
)
from magus.ids import utcnow
from magus.melchior.bibliography import BibReport, import_bibliography
from magus.melchior.check import after_refs_changed
from magus.melchior.questions import TYPES, build_questions
from magus.store import BookTitles, Edition, Issue, Store
from magus.store.base import STALE_REASONS, ChapterMeta

QUESTION_LINES = 5  # 리포트에 질문을 종류마다 몇 줄까지 옮기나
SAME_BOOK_MIN = 0.3  # 장 제목 겹침이 이보다 적으면 다른 책으로 보고 멈춘다
UPLOAD_NOTE = "수정본 E{n} 업로드: {name}"
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "「": '"', "」": '"'})
_ANCHOR_SHOWN = re.compile(r"— 원문: “(?P<a>.*)”\s*$", re.S)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _plain(text: str) -> str:
    """걸린 문장 대조용: 공백·따옴표 모양·markdown 기호(표의 |, 제목 #, 목록 -, 강조 *)를 지운다."""
    return re.sub(r"[\s|#*\\\-]+", "", text.translate(_QUOTES))


def _sentences(text: str) -> set[str]:
    text = re.sub(r"^#+ .*$", "", text, flags=re.M)
    return {s for s in (_squash(p) for p in re.split(r"(?<=[.!?。])\s+|\n+", text)) if len(s) >= 15}


def title_overlap(old: list[str], new: list[str]) -> float:
    """기존 장 제목 중 새 판에도 있는 비율(공백 무시)."""
    before, after = {_squash(t) for t in old}, {_squash(t) for t in new}
    return len(before & after) / len(before) if before else 1.0


def _comment_body(issue: Issue) -> str:
    return " ".join(issue.text.partition(COMMENT_ANCHOR_SPLIT)[0].split())


def _old_anchor(issue: Issue) -> str:
    """미해결의 걸린 문장. 전문(#73)이 없는 옛 미해결은 본문의 표시용 120자를 쓴다."""
    if issue.anchor:
        return issue.anchor
    m = _ANCHOR_SHOWN.search(issue.text)
    return m.group("a") if m else ""


@dataclass
class ChapterChange:
    number: int
    display: str
    old_chars: int | None
    new_chars: int | None
    kept: float | None = None  # 이전 문장 중 남은 비율
    title_from: str | None = None  # 제목이 바뀌었으면 이전 제목
    title: str = ""


@dataclass
class ReuploadReport:
    project_id: str
    title: str
    source: str
    edition: int
    previous: int
    overlap: float
    titles_changed: str = ""
    parts_changed: str = ""
    changed: list[ChapterChange] = field(default_factory=list)
    added: list[ChapterChange] = field(default_factory=list)
    removed: list[ChapterChange] = field(default_factory=list)
    unchanged: int = 0
    overwritten_magus: list[str] = field(default_factory=list)  # Magus에서 고친 뒤 이번 판으로 덮인 장
    comments_total: int = 0
    issues_kept: int = 0
    issues_new: int = 0
    issues_moved: int = 0
    stale: Counter = field(default_factory=Counter)
    closed_but_in_file: int = 0
    direct_issues: int = 0
    decisions: int = 0
    bib: BibReport = field(default_factory=BibReport)
    files: dict[str, str] = field(default_factory=dict)
    # 답해 주실 질문(#84): 올리기 전후를 비교한다. (종류, 질문 문장)
    questions_new: list[tuple[str, str]] = field(default_factory=list)
    questions_closed: list[tuple[str, str]] = field(default_factory=list)
    questions_waiting: list[tuple[str, str]] = field(default_factory=list)  # 'Word에서' 답했는데 이번 원고에도 그대로

    def summary(self) -> str:
        names = lambda rows: ", ".join(r.display for r in rows)  # noqa: E731
        renamed = [c for c in self.changed if c.title_from]
        stale = " · ".join(f"{STALE_REASONS[k]} {self.stale[k]}" for k in STALE_REASONS if self.stale[k])
        lines = [
            f"## 수정본 E{self.edition} — {self.title} ({self.project_id})",
            f"- 원본: {self.source} · 수정본 번호 E{self.previous} → E{self.edition} · 장 제목 겹침 {self.overlap:.0%}",
            *([f"- 제목 바뀜: {self.titles_changed}"] if self.titles_changed else []),
            *([f"- 부 바뀜: {self.parts_changed}"] if self.parts_changed else []),
            f"- 장: 본문 바뀜 {len(self.changed)} · 그대로 {self.unchanged} · 새 장 {len(self.added)}"
            + (f"({names(self.added)})" if self.added else "")
            + f" · 빠진 장 {len(self.removed)}"
            + (f"({names(self.removed)}, removed/에 보관)" if self.removed else ""),
            *(["  - 제목이 바뀐 장: " + ", ".join(f"{c.display} '{c.title_from}' → '{c.title}'" for c in renamed)] if renamed else []),
            *([f"- ⚠ Magus에서 고친 뒤 이번 수정본으로 덮인 장: {', '.join(self.overwritten_magus)} (이전본은 versions/에 있다)"]
              if self.overwritten_magus else []),
            f"- 문서 코멘트 {self.comments_total}건 → 이어진 확인 요청 {self.issues_kept}(장을 옮긴 것 {self.issues_moved}) · 새 확인 요청 {self.issues_new}"
            + (f" · 해결됐을 수 있음 {sum(self.stale.values())}({stale}) — 닫지 않았다" if self.stale else ""),
            *([f"  - Magus에서 닫았지만 올린 문서에 코멘트가 남아 있는 것 {self.closed_but_in_file}건(닫힌 채 둔다)"]
              if self.closed_but_in_file else []),
            f"- 그대로 둔 것: 결정 {self.decisions}건, 직접 남긴 확인 요청 {self.direct_issues}건, 생각·문헌·문체",
            f"- {self.bib.render().splitlines()[0]}",
            *(f"  {line}" for line in self.bib.render().splitlines()[1:]),
            f"- 답해 주실 질문: 새로 생김 {len(self.questions_new)} · 저절로 닫힘 {len(self.questions_closed)} · "
            f"답했지만 올린 문서에 아직 그대로 {len(self.questions_waiting)}",
            *(f"  - {label}: {kind} — {text[:100]}" for label, rows in (
                ("새로 생김", self.questions_new), ("저절로 닫힘", self.questions_closed),
                ("아직 그대로", self.questions_waiting)) for kind, text in rows[:QUESTION_LINES]),
        ]
        return "\n".join(lines)

    def change_table(self) -> str:
        rows = ["| 장 | 이전 글자 | 새 글자 | 이전 문장 남음 | 비고 |", "|---|---:|---:|---:|---|"]
        for kind, items in (("바뀜", self.changed), ("새 장", self.added), ("빠짐", self.removed)):
            for c in items:
                old = f"{c.old_chars:,}" if c.old_chars is not None else "-"
                new = f"{c.new_chars:,}" if c.new_chars is not None else "-"
                kept = f"{c.kept:.0%}" if c.kept is not None else "-"
                note = kind + (f", 제목 바뀜(이전 '{c.title_from}')" if c.title_from else "")
                rows.append(f"| {c.display} | {old} | {new} | {kept} | {note} |")
        return "\n".join(rows)

    def full(self) -> str:
        return "\n\n".join([self.summary(), "### 바뀐 장", self.change_table()])


def _legacy_edition(store: Store, user_id: str, project_id: str, chapters: list[ChapterMeta]) -> Edition:
    """판 기록이 생기기 전에 임포트한 프로젝트: 그 임포트를 E1로 적는다(파일 이름은 장 note '임포트: …'에서)."""
    project = store.get_project(user_id, project_id)
    name = next((c.last_note.removeprefix("임포트: ") for c in chapters if c.last_note.startswith("임포트: ")), "")
    return Edition(1, name or "(판 기록 전 임포트)", project.created_at if project else utcnow(), legacy=True)


def magus_edited(chapter: ChapterMeta, has_editions: bool) -> bool:
    """본문을 Magus에서 고쳤나: 판 기록이 있으면 edition이 비어 있는 장, 판 기록 전 프로젝트면 임포트 뒤 버전이 오른 장."""
    return chapter.edition is None if has_editions else chapter.version > 1


def reupload_manuscript(
    store: Store,
    user_id: str,
    path: Path,
    project_id: str,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    force: bool = False,
) -> ReuploadReport:
    path = Path(path)
    project = store.get_project(user_id, project_id)
    if project is None:
        raise ValueError(f"수정본으로 올릴 프로젝트 {project_id!r}가 없다. 처음 올리는 책이면 수정본이 아니라 임포트한다.")
    manuscript = read_manuscript(path)
    split = split_manuscript(manuscript.blocks)
    if not split.chapters:
        raise ValueError("'제N장' 제목을 하나도 찾지 못했다. 문서의 장 제목 표기를 확인해 주세요.")
    old_list = store.list_chapters(user_id, project.id)
    questions_before = {q.id: q for q in build_questions(store, user_id, project.id)}  # 올리기 전 질문(비교용)
    overlap = title_overlap([c.title for c in old_list], [c.title for c in split.chapters])
    if overlap < SAME_BOOK_MIN and not force:
        raise ValueError(
            f"장 제목이 기존 문서({project.title})와 {overlap:.0%}만 겹친다. 다른 책 같다. "
            "같은 책의 수정본이 맞으면 force=true로 다시 올리고, 다른 책이면 새 project_id로 임포트한다."
        )

    editions = store.list_editions(user_id, project.id)
    has_editions = bool(editions)
    if not editions:
        editions = [_legacy_edition(store, user_id, project.id, old_list)]
        store.add_edition(user_id, project.id, editions[0])
    n = editions[-1].number + 1
    data = path.read_bytes()
    report = ReuploadReport(project.id, project.title, f"{path.name} ({manuscript.source})", n, editions[-1].number, overlap)
    report.files["original"] = store.save_original(user_id, project.id, f"E{n}-{path.name}", data)

    # 제목: 사람이 준 것 > 원고에서 읽은 것 > 지금 것. 원고가 원본이므로 원고에서 읽혔으면 부제·영문도 그대로 따른다.
    found = detect_titles(manuscript, cover_blocks(manuscript, split))
    wanted = (
        book_titles(manuscript, split, title, subtitle, path)
        if (title or found.title)
        else BookTitles(project.title, subtitle or project.subtitle, project.title_en, project.subtitle_en)
    )
    now = BookTitles(project.title, project.subtitle, project.title_en, project.subtitle_en)
    if wanted != now:
        project = store.set_titles(user_id, project.id, wanted)
        shown = lambda t: " — ".join(x for x in (t.title, t.subtitle) if x) + (f" / {t.title_en}" if t.title_en else "")  # noqa: E731
        report.titles_changed = f"'{shown(now)}' → '{shown(wanted)}'"
        report.title = project.title

    old_parts = [(p.number, p.title) for p in store.list_parts(user_id, project.id)]
    if old_parts != [(p.number, p.title) for p in split.parts]:
        store.set_parts(user_id, project.id, split.parts)
        before, after = dict(old_parts), {p.number: p.title for p in split.parts}
        report.parts_changed = ", ".join(
            f"제{k}부 '{before.get(k, '-')}' → '{after.get(k, '-')}'" for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)
        )

    old = {c.number: c for c in old_list}
    note = UPLOAD_NOTE.format(n=n, name=path.name)
    for ch in split.chapters:
        _apply_chapter(store, user_id, project.id, ch, old.get(ch.number), n, note, has_editions, report)
    for number in [num for num in old if num not in {ch.number for ch in split.chapters}]:
        meta = old[number]
        body = store.read_chapter(user_id, project.id, number)
        store.remove_chapter(user_id, project.id, number, editions[-1].number)
        report.removed.append(ChapterChange(number, meta.display, len(body.content) if body else None, None))
    unsplit = unsplit_markdown(split).encode("utf-8")
    report.files["unsplit"] = store.save_original(user_id, project.id, "unsplit.md", unsplit)
    store.save_original(user_id, project.id, f"E{n}-unsplit.md", unsplit)

    _merge_comments(store, user_id, project.id, manuscript, split, n, report)

    report.bib = import_bibliography(store, user_id, "\n".join(b.text for b in split.bib_blocks if b.kind == "para"), project.id)
    after_refs_changed(store, user_id)
    questions_after = {q.id: q for q in build_questions(store, user_id, project.id)}
    report.questions_new = [(TYPES[q.type], q.text) for k, q in questions_after.items() if k not in questions_before]
    report.questions_closed = [(TYPES[q.type], q.text) for k, q in questions_before.items() if k not in questions_after]
    report.questions_waiting = [(TYPES[q.type], q.text) for k, q in questions_after.items()
                                if q.state == "waiting" and k in questions_before]
    report.decisions = len(store.list_decisions(user_id, project.id))
    report.direct_issues = sum(1 for i in store.list_issues(user_id, project.id, None) if i.origin != "import_comment")
    store.add_edition(
        user_id, project.id,
        Edition(n, path.name, utcnow(), hashlib.sha256(data).hexdigest(), changed=len(report.changed) + len(report.added),
                added=len(report.added), removed=len(report.removed), unchanged=report.unchanged),
    )
    report.files["report"] = store.save_original(user_id, project.id, f"E{n}-reupload-report.md", report.full().encode("utf-8"))
    return report


def _apply_chapter(
    store: Store, user_id: str, project_id: str, ch: ChapterPlan, old: ChapterMeta | None, n: int, note: str,
    has_editions: bool, report: ReuploadReport,
) -> None:
    body = chapter_body(ch)
    display = ch.label or f"제{ch.number}장"
    if old is None:
        store.write_chapter(user_id, project_id, ch.number, body, note, title=ch.title, part_number=ch.part_number,
                            label=ch.label, edition=n)
        report.added.append(ChapterChange(ch.number, display, None, len(body)))
        return
    current = store.read_chapter(user_id, project_id, ch.number)
    old_body = current.content if current else ""
    if old_body == body and (old.title, old.part_number, old.label) == (ch.title, ch.part_number, ch.label):
        store.set_chapter_edition(user_id, project_id, ch.number, n)
        report.unchanged += 1
        return
    if magus_edited(old, has_editions) and old_body != body:
        report.overwritten_magus.append(display)
    store.write_chapter(user_id, project_id, ch.number, body, note, title=ch.title, part_number=ch.part_number,
                        label=ch.label, edition=n)
    before = _sentences(old_body)
    kept = len(before & _sentences(body)) / len(before) if before and body != EMPTY_BODY else None
    report.changed.append(
        ChapterChange(ch.number, display, len(old_body), len(body), kept, old.title if old.title != ch.title else None, ch.title)
    )


def _merge_comments(store: Store, user_id: str, project_id: str, manuscript, split, n: int, report: ReuploadReport) -> None:
    """원고 코멘트를 기존 미해결과 잇는다. 같은 코멘트는 다시 넣지 않고, 사라진 코멘트는 표시만 한다(닫지 않는다)."""
    terms = frozenset(store.get_non_citation_terms(user_id, project_id))
    entries = comment_entries(manuscript, split, terms, store.get_ai_authors(user_id, project_id))
    report.comments_total = len(entries)
    from_comments = [i for i in store.list_issues(user_id, project_id, None) if i.origin == "import_comment"]
    by_fp = {i.comment_fp: i for i in from_comments if i.comment_fp}
    by_text: dict[str, list[Issue]] = {}
    for i in from_comments:
        # 지문이 없거나(판 기록 전) 작성자 없이 만든 지문(PDF 말풍선)이면 docx 판의 지문과 맞을 수 없다: 코멘트 본문으로 잇는다
        if not i.comment_fp or not i.author:
            by_text.setdefault(_squash(_comment_body(i)), []).append(i)
    matched: set[int] = set()
    updates: list[Issue] = []
    for e in entries:
        c = e.comment
        issue = by_fp.get(e.fp)
        if issue is None or issue.id in matched:
            pool = [i for i in by_text.get(_squash(" ".join(c.text.split())), []) if i.id not in matched]
            issue = pool[0] if pool else None
        if issue is None:
            store.add_issue(
                user_id, project_id, e.issue_text, origin="import_comment", chapter_number=e.chapter, kind=e.kind,
                ref_key=e.ref_key, author=c.author, author_kind=e.author_kind, comment_date=c.date, anchor=c.anchor,
                paragraph=e.paragraph, comment_fp=e.fp,
            )
            report.issues_new += 1
            continue
        matched.add(issue.id)
        report.issues_kept += 1
        report.issues_moved += issue.chapter_number != e.chapter
        report.closed_but_in_file += issue.status == "closed"
        anchored = bool(c.anchor.strip())
        new = replace(
            issue,
            text=e.issue_text,
            chapter_number=e.chapter,
            anchor=c.anchor or issue.anchor,
            paragraph=e.paragraph,
            comment_fp=e.fp,
            author=issue.author or c.author or None,
            author_kind=issue.author_kind or e.author_kind,
            comment_date=issue.comment_date or c.date or None,
            stale=None if anchored else "anchor_missing",
            stale_edition=None if anchored else n,
        )
        if not anchored and issue.status == "open":
            report.stale["anchor_missing"] += 1
        if new != issue:
            updates.append(new)

    # 원고에서 코멘트가 사라진 열린 미해결: 걸린 문장이 아직 있으면 '코멘트가 지워짐', 없으면 '걸린 문장 없음'
    bodies = {ch.number: _plain(chapter_body(ch)) for ch in split.chapters}
    for issue in from_comments:
        if issue.id in matched or issue.status != "open":
            continue
        anchor = _plain(_old_anchor(issue))
        where = None
        if len(anchor) >= 4:
            order = [issue.chapter_number, *bodies] if issue.chapter_number in bodies else list(bodies)
            where = next((num for num in order if anchor in bodies[num]), None)
        stale = "comment_removed" if where is not None else "anchor_missing"
        report.stale[stale] += 1
        new = replace(issue, stale=stale, stale_edition=issue.stale_edition if issue.stale == stale else n,
                      chapter_number=where if where is not None else issue.chapter_number)
        if new != issue:
            updates.append(new)
    store.update_issues(user_id, project_id, updates)
