"""book_import: 원고(docx, 없으면 PDF)를 장 단위로 나눠 프로젝트를 만든다.

- "제N부"·"제N장" 제목(공백 변형, 콜론·대시, 제목이 다음 줄에 오는 경우)으로 나눈다.
- 같은 장 번호가 여러 번 나오면(목차) 뒤따르는 본문이 가장 긴 것을 진짜 제목으로 보고 나머지는 리포트에 남긴다.
- 첫 제목 앞(표지·목차·머리말)은 "분할 못 한 구간"으로 리포트하고 original/unsplit.md에 보관한다.
- 코멘트 → issues(origin=import_comment, 앵커가 속한 장, classify_comment로 kind·ref_key).
- 참고문헌 섹션 → import_bibliography.
- 원본 파일은 무엇보다 먼저 original/에 복사한다. 재실행할 때는 새 project_id를 쓰거나 replace=True로 기존 것을 휴지통으로 옮긴다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from magus.book.comments import classify_comment
from magus.book.docx_reader import Block, Manuscript, read_docx
from magus.book.pdf_reader import read_pdf
from magus.melchior.bibliography import BibReport, import_bibliography
from magus.store import Part, Store
from magus.store.formats import one_line

_SEP = r"[\s:：.\-–—·]"
_PART = re.compile(rf"^\s*제\s*(\d+)\s*부(?:{_SEP}+(.*?))?\s*$")
_CHAPTER = re.compile(rf"^\s*제\s*(\d+)\s*장(?:{_SEP}+(.*?))?\s*$")
_BIB = re.compile(r"^\s*(참\s*고\s*문\s*헌|참고\s*자료|references|bibliography|works cited)\s*$", re.I)
_TOC_TAIL = re.compile(r"(?:\t|\.{2,}|…+|·{2,})\s*\d+\s*$")
_SENTENCE_END = re.compile(r"[.!?。]$|다\.?$")
MAX_HEADING_LEN = 80
MAX_TITLE_LINE_LEN = 60


@dataclass
class Head:
    index: int
    kind: str  # part | chapter | bib
    number: int = 0
    title: str = ""
    title_index: int | None = None  # 제목이 다음 줄에 있었으면 그 블록
    body_chars: int = 0

    @property
    def body_start(self) -> int:
        return (self.title_index if self.title_index is not None else self.index) + 1


@dataclass
class ChapterPlan:
    number: int
    title: str
    part_number: int | None
    blocks: list[Block]


@dataclass
class Split:
    parts: list[Part]
    chapters: list[ChapterPlan]
    bib_blocks: list[Block]
    unsplit: list[Block]
    region_of_block: dict[int, int | str]  # 블록 → 장 번호 | "bib" | "unsplit"
    discarded: list[Head] = field(default_factory=list)


def _heads(blocks: list[Block]) -> list[Head]:
    heads: list[Head] = []
    for i, b in enumerate(blocks):
        if b.kind != "para":
            continue
        text = _TOC_TAIL.sub("", b.text).strip()
        if not text or len(text) > MAX_HEADING_LEN:
            continue
        if m := _PART.match(text):
            heads.append(Head(i, "part", int(m.group(1)), (m.group(2) or "").strip()))
        elif m := _CHAPTER.match(text):
            heads.append(Head(i, "chapter", int(m.group(1)), (m.group(2) or "").strip()))
        elif _BIB.match(text):
            heads.append(Head(i, "bib"))
    head_index = {h.index for h in heads}
    for h in heads:
        nxt = h.index + 1
        if h.kind != "bib" and not h.title and nxt < len(blocks) and nxt not in head_index:
            cand = blocks[nxt]
            text = cand.text.strip()
            if cand.kind == "para" and 0 < len(text) <= MAX_TITLE_LINE_LEN and not _SENTENCE_END.search(text):
                h.title, h.title_index = _TOC_TAIL.sub("", text).strip(), nxt
    for n, h in enumerate(heads):
        end = heads[n + 1].index if n + 1 < len(heads) else len(blocks)
        h.body_chars = sum(len(b.text) for b in blocks[h.body_start : end])
    return heads


def split_manuscript(blocks: list[Block]) -> Split:
    heads = _heads(blocks)
    best: dict[int, Head] = {}
    for h in (h for h in heads if h.kind == "chapter"):
        # 목차 줄은 뒤따르는 본문이 없다. 본문이 가장 긴 것(같으면 나중 것)을 진짜 장 제목으로 본다.
        if h.number not in best or h.body_chars >= best[h.number].body_chars:
            best[h.number] = h
    real_chapters = {id(h) for h in best.values()}
    real_parts: dict[int, Head] = {}
    for n, h in enumerate(heads):
        if h.kind == "part":
            nxt = heads[n + 1] if n + 1 < len(heads) else None
            if nxt is not None and id(nxt) in real_chapters:
                real_parts[h.number] = h  # 진짜 장 제목 바로 앞의 부 제목만 인정(같은 번호면 나중 것)
    bibs = [h for h in heads if h.kind == "bib" and h.body_chars > 0]
    real_bib = max(bibs, key=lambda h: (h.body_chars, h.index)) if bibs else None
    real = sorted([*best.values(), *real_parts.values(), *([real_bib] if real_bib else [])], key=lambda h: h.index)
    real_ids = {id(h) for h in real}
    discarded = [h for h in heads if id(h) not in real_ids]

    split = Split([], [], [], [], {}, discarded)
    first = real[0].index if real else len(blocks)
    split.unsplit = [b for b in blocks[:first] if b.text.strip()]
    for b in blocks[:first]:
        split.region_of_block[b.index] = "unsplit"
    part: int | None = None
    for n, h in enumerate(real):
        end = real[n + 1].index if n + 1 < len(real) else len(blocks)
        region = blocks[h.body_start : end]
        for b in blocks[h.index : end]:
            split.region_of_block[b.index] = "bib" if h.kind == "bib" else (h.number if h.kind == "chapter" else "unsplit")
        if h.kind == "part":
            part = h.number
            split.parts.append(Part(h.number, h.title))
            split.unsplit += [b for b in region if b.text.strip()]  # 부 제목과 첫 장 사이의 글(부 서문)
        elif h.kind == "chapter":
            split.chapters.append(ChapterPlan(h.number, h.title or f"제{h.number}장", part, region))
        else:
            split.bib_blocks = region
    split.chapters.sort(key=lambda c: c.number)
    return split


def blocks_to_markdown(blocks: list[Block]) -> str:
    out = []
    for b in blocks:
        text = b.text.strip()
        if not text:
            continue
        if b.kind == "table":
            out.append(text)
        elif b.heading_level is not None:
            out.append(f"## {text}")
        elif b.is_list:
            out.append(f"- {text}")
        else:
            out.append(text)
    return "\n\n".join(out)


@dataclass
class ImportReport:
    project_id: str
    title: str
    source: str
    synthetic: bool
    chapters: list[tuple[int, str, int | None, int, int]]  # 번호, 제목, 부, 글자수, 코멘트 수
    parts: list[Part]
    discarded: list[str]
    gaps: list[int]
    empty_chapters: list[int]
    unsplit_chars: int
    unsplit_preview: str
    comment_rows: list[tuple[int, int | None, str, str | None, str]]  # 이슈 번호, 장, kind, ref_key, 앞 40자
    comments_outside: Counter
    bib: BibReport
    figures: int
    tables: int
    equations: int
    notes: list[str]
    files: dict[str, str]

    def summary(self) -> str:
        kinds = Counter(row[2] for row in self.comment_rows)
        citation = kinds.get("citation", 0)
        with_key = sum(1 for row in self.comment_rows if row[2] == "citation" and row[3])
        ratio = f"{with_key}/{citation} ({with_key / citation:.0%})" if citation else "0/0"
        lines = [
            f"## 임포트 리포트 — {self.title} ({self.project_id})" + (" · 합성 fixture" if self.synthetic else ""),
            f"- 원본: {self.source}" + "".join(f" · {n}" for n in self.notes),
            f"- 장 {len(self.chapters)}개 · 부 {len(self.parts)}개 · 그림 {self.figures} · 표 {self.tables} · 수식 {self.equations}",
            f"- 분할 못 한 구간: {self.unsplit_chars:,}자 (original/unsplit.md) — {self.unsplit_preview}",
            f"- 목차 등으로 판단해 버린 제목 줄: {len(self.discarded)}개"
            + (f" — {', '.join(self.discarded[:8])}" + (" …" if len(self.discarded) > 8 else "") if self.discarded else ""),
            f"- 빠진 장 번호: {', '.join(map(str, self.gaps)) or '없음'} · 본문 없는 장: {', '.join(map(str, self.empty_chapters)) or '없음'}",
            f"- 코멘트 → 이슈 {len(self.comment_rows)}건: citation {citation} · general {kinds.get('general', 0)}"
            f" · ref_key 후보 {ratio}"
            + (f" · 장 밖 코멘트 {dict(self.comments_outside)}" if self.comments_outside else ""),
            f"- {self.bib.render().splitlines()[0]}",
            *(f"  {line}" for line in self.bib.render().splitlines()[1:]),
        ]
        return "\n".join(lines)

    def mapping_table(self) -> str:
        rows = ["| 파일 | 장 제목 | 부 | 글자수 | 코멘트 |", "|---|---|---|---:|---:|"]
        rows += [
            f"| ch-{n:02d}.md | {title} | {part if part is not None else '-'} | {chars:,} | {comments} |"
            for n, title, part, chars, comments in self.chapters
        ]
        return "\n".join(rows)

    def comment_table(self) -> str:
        rows = ["| 이슈 | 장 | kind | ref_key 후보 | 앞 40자 |", "|---|---|---|---|---|"]
        rows += [
            f"| I{iid} | {ch if ch is not None else '-'} | {kind} | {key or '-'} | {head.replace('|', '/')} |"
            for iid, ch, kind, key, head in self.comment_rows
        ]
        return "\n".join(rows)

    def full(self) -> str:
        return "\n\n".join(
            [self.summary(), "### ch-NN.md ↔ 장 제목", self.mapping_table(), "### 코멘트 분류", self.comment_table()]
        )


def read_manuscript(path: Path) -> Manuscript:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx(path)
    if suffix == ".pdf":
        return read_pdf(path)
    raise ValueError(f"지원하지 않는 형식: {path.name} (docx 또는 pdf)")


def import_manuscript(
    store: Store,
    user_id: str,
    path: Path,
    *,
    project_id: str | None = None,
    title: str | None = None,
    replace: bool = False,
    synthetic: bool = False,
) -> ImportReport:
    path = Path(path)
    manuscript = read_manuscript(path)
    split = split_manuscript(manuscript.blocks)
    if not split.chapters:
        raise ValueError("'제N장' 제목을 하나도 찾지 못했다. 원고의 장 제목 표기를 확인해 주세요.")

    if project_id and store.get_project(user_id, project_id):
        if not replace:
            raise ValueError(f"프로젝트 {project_id!r}가 이미 있다. 새 project_id를 쓰거나 replace=True로 다시 임포트한다.")
        store.archive_project(user_id, project_id)
    project = store.create_project(user_id, title or manuscript.title or path.stem, project_id=project_id)
    files = {"original": store.save_original(user_id, project.id, path.name, path.read_bytes())}

    store.set_parts(user_id, project.id, split.parts)
    empty: list[int] = []
    for ch in split.chapters:
        body = blocks_to_markdown(ch.blocks)
        if not body:
            empty.append(ch.number)
            body = "[본문 없음: 임포트 때 이 장 제목 아래에서 글을 찾지 못했다]"
        store.write_chapter(
            user_id, project.id, ch.number, body, f"임포트: {path.name}", title=ch.title, part_number=ch.part_number
        )
    unsplit_md = blocks_to_markdown(split.unsplit)
    files["unsplit"] = store.save_original(user_id, project.id, "unsplit.md", unsplit_md.encode("utf-8"))

    comment_counts: Counter = Counter()
    outside: Counter = Counter()
    rows: list[tuple[int, int | None, str, str | None, str]] = []
    for c in sorted(manuscript.comments, key=lambda c: (c.block_index is None, c.block_index or 0, int(c.id) if c.id.isdigit() else 0)):
        region = split.region_of_block.get(c.block_index) if c.block_index is not None else None
        chapter = region if isinstance(region, int) else None
        if chapter is None:
            outside[region or "위치 모름"] += 1
        else:
            comment_counts[chapter] += 1
        kind, ref_key = classify_comment(c.text, c.anchor)
        anchor = one_line(c.anchor)[:120]
        text = (c.text or "(빈 코멘트)") + (f"\n— 원문: “{anchor}”" if anchor else "")
        issue = store.add_issue(
            user_id, project.id, text, origin="import_comment", chapter_number=chapter, kind=kind, ref_key=ref_key
        )
        rows.append((issue.id, chapter, kind, ref_key, one_line(c.text)[:40]))

    bib_report = import_bibliography(store, user_id, "\n".join(b.text for b in split.bib_blocks if b.kind == "para"))
    numbers = [c.number for c in split.chapters]
    gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers)) if numbers else []
    report = ImportReport(
        project_id=project.id,
        title=project.title,
        source=f"{path.name} ({manuscript.source})",
        synthetic=synthetic,
        chapters=[
            (ch.number, ch.title, ch.part_number, len(blocks_to_markdown(ch.blocks)), comment_counts[ch.number])
            for ch in split.chapters
        ],
        parts=split.parts,
        discarded=[f"{h.index}:{'부' if h.kind == 'part' else '장' if h.kind == 'chapter' else '참고문헌'}{h.number or ''}" for h in split.discarded],
        gaps=gaps,
        empty_chapters=empty,
        unsplit_chars=len(unsplit_md),
        unsplit_preview=one_line(unsplit_md)[:40],
        comment_rows=rows,
        comments_outside=outside,
        bib=bib_report,
        figures=manuscript.figures,
        tables=manuscript.tables,
        equations=manuscript.equations,
        notes=manuscript.notes,
        files=files,
    )
    files["report"] = store.save_original(user_id, project.id, "import-report.md", report.full().encode("utf-8"))
    return report
