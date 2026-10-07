"""book_import: 원고(docx, 없으면 PDF)를 장 단위로 나눠 프로젝트를 만든다.

- "제N부"·"제N장" 제목(공백 변형, 콜론·대시, 제목이 다음 줄에 오는 경우)으로 나눈다.
- 같은 장 번호가 여러 번 나오면(목차) 뒤따르는 본문이 가장 긴 것을 진짜 제목으로 보고 나머지는 리포트에 남긴다.
- 첫 제목 앞(표지·목차·머리말)은 "분할 못 한 구간"으로 리포트하고 original/unsplit.md에 보관한다.
- 코멘트 → issues(origin=import_comment, 앵커가 속한 장, classify_comment로 kind·ref_key).
- 참고문헌 섹션 → import_bibliography.
- 원본 파일은 무엇보다 먼저 original/에 복사한다. 재실행할 때는 새 project_id를 쓰거나 replace=True로 기존 것을 휴지통으로 옮긴다.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from dataclasses import replace as replace_titles
from pathlib import Path

from magus.book.comments import author_kind, classify_comment, comment_fingerprint
from magus.book.docx_reader import Block, Comment, Manuscript, read_docx
from magus.book.outline import count_by_labels
from magus.book.pdf_reader import read_pdf
from magus.melchior.bibliography import BibReport, import_bibliography
from magus.melchior.check import after_refs_changed
from magus.ids import utcnow
from magus.store import BookTitles, Edition, Part, Store
from magus.store.base import PART_INTRO_BASE, AuthorKind, IssueKind, reading_order
from magus.store.formats import one_line

_SEP = r"[\s:：.\-–—·]"
_PART = re.compile(rf"^\s*제\s*(\d+)\s*부(?:{_SEP}+(.*?))?\s*$")
# "제2부 들어가며  인간은 왜 …": 부 제목이 아니라 그 부의 첫머리 글(번호 없는 장, 번호 100+N, #70)
_PART_INTRO = re.compile(rf"^\s*제\s*(\d+)\s*부\s*들어가며(?:{_SEP}+(.*?))?\s*$")
_CHAPTER = re.compile(rf"^\s*제\s*(\d+)\s*장(?:{_SEP}+(.*?))?\s*$")
# 번호 없는 장. 제목 서식이 있는 줄일 때만 인정한다(목차 줄·본문 문장과 구별). 번호: 서장 0, 맺음 90, 부록 N은 90+N.
_SPECIAL = re.compile(rf"^\s*(?P<label>서장|프롤로그|맺음말?|에필로그|나가며|부록\s*(?P<n>\d+))(?:{_SEP}+(?P<title>.*?))?\s*$")
_BIB = re.compile(r"^\s*(참\s*고\s*문\s*헌|참고\s*자료|references|bibliography|works cited)\s*$", re.I)
_TOC_TAIL = re.compile(r"\s*(?:\t|\.{2,}|…+|·{2,})[\s.…·]*\d*\s*$")  # 목차의 점선(쪽번호는 없어도 됨)
_SENTENCE_END = re.compile(r"[.!?。]$|다\.?$")
MAX_HEADING_LEN = 80
MAX_TITLE_LINE_LEN = 60
FRONT_NUMBER = 0
BACK_NUMBER = 90  # 맺음. 부록 N은 90+N. 본문 장(1~89) 사이에 새 장을 넣을 자리를 남긴다.


def special_number(label: str, appendix: str | None) -> int:
    if appendix:
        return BACK_NUMBER + int(appendix)
    return FRONT_NUMBER if label in ("서장", "프롤로그") else BACK_NUMBER


@dataclass
class Head:
    index: int
    kind: str  # part | chapter | bib
    number: int = 0
    title: str = ""
    title_index: int | None = None  # 제목이 다음 줄에 있었으면 그 블록
    body_chars: int = 0
    styled: bool = False  # 제목 서식(docx 제목 스타일, PDF 큰 글씨)이 있는 줄인가
    label: str | None = None  # 번호 없는 장의 표시 이름(서장, 맺음, 부록 1, 제2부 들어가며)
    intro_part: int | None = None  # "제N부 들어가며"면 N

    @property
    def body_start(self) -> int:
        return (self.title_index if self.title_index is not None else self.index) + 1


@dataclass
class ChapterPlan:
    number: int
    title: str
    part_number: int | None
    blocks: list[Block]
    label: str | None = None
    level: int = 1  # 장 제목의 단계

    def markdown(self) -> str:
        return blocks_to_markdown(self.blocks, self.level)

    def paragraphs(self) -> dict[int, int]:
        """블록 → 장 본문의 문단 번호(1부터). 빈 블록은 본문에 실리지 않으므로 세지 않는다(ref_check의 paragraphs와 같다)."""
        return {b.index: n for n, b in enumerate((b for b in self.blocks if b.text.strip()), 1)}


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
        styled = b.heading_level is not None
        if m := _PART_INTRO.match(text):
            n = int(m.group(1))
            heads.append(
                Head(i, "chapter", PART_INTRO_BASE + n, (m.group(2) or "").strip(), styled=styled,
                     label=f"제{n}부 들어가며", intro_part=n)
            )
        elif m := _PART.match(text):
            heads.append(Head(i, "part", int(m.group(1)), (m.group(2) or "").strip(), styled=styled))
        elif m := _CHAPTER.match(text):
            heads.append(Head(i, "chapter", int(m.group(1)), (m.group(2) or "").strip(), styled=styled))
        elif styled and (m := _SPECIAL.match(text)):
            label = re.sub(r"\s+", " ", m.group("label"))
            number = special_number(label, m.group("n"))
            heads.append(Head(i, "chapter", number, (m.group("title") or "").strip(), styled=True, label=label))
        elif _BIB.match(text):
            heads.append(Head(i, "bib", styled=styled))
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
        # 목차 줄은 서식이 없고 뒤따르는 본문도 없다. 제목 서식이 있는 것을 먼저, 그다음 본문이 가장 긴 것
        # (같으면 나중 것)을 진짜 장 제목으로 본다. 본문 문장 "제12장 참조." 같은 짧은 줄이 이기지 않게 하려는 것이다.
        if h.number not in best or (h.styled, h.body_chars) >= (best[h.number].styled, best[h.number].body_chars):
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
            title = h.title or h.label or f"제{h.number}장"
            # 서장·맺음·부록은 어느 부에도 속하지 않는다. 부 들어가며는 그 부에 속한다.
            part_of = h.intro_part if h.intro_part is not None else (None if h.label else part)
            level = blocks[h.index].heading_level or 1
            split.chapters.append(ChapterPlan(h.number, title, part_of, region, h.label, level))
        else:
            split.bib_blocks = region
    split.chapters = reading_order(split.chapters)
    return split


def blocks_to_markdown(blocks: list[Block], chapter_level: int = 1) -> str:
    """chapter_level: 장 제목의 단계(docx Heading 2면 2, PDF 큰 글씨면 1). 장 안의 절은 그보다 한 단계 아래 = ##."""
    out = []
    for b in blocks:
        text = b.text.strip()
        if not text:
            continue
        if b.kind == "table":
            out.append(text)
        elif b.heading_level is not None:
            depth = b.heading_level - chapter_level + 1
            out.append(f"{'#' * max(2, min(depth, 4))} {text}")
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
    chapters: list[tuple[int, str | None, str, int | None, int, int]]  # 번호, 표시 이름, 제목, 부, 글자수, 코멘트 수
    parts: list[Part]
    discarded: list[str]
    gaps: list[int]
    empty_chapters: list[int]
    unsplit_chars: int
    unsplit_preview: str
    comment_rows: list[tuple[int, int | None, str, str | None, str]]  # 이슈 번호, 장, kind, ref_key, 앞 40자
    comments_linked: int
    comments_outside: Counter
    bib: BibReport
    figures: int
    tables: int
    equations: int
    notes: list[str]
    files: dict[str, str]
    comment_authors: Counter = field(default_factory=Counter)  # "Claude(AI)" → 건수(#71)
    titles: BookTitles | None = None  # 제목·부제·영문(#77)

    def summary(self) -> str:
        kinds = Counter(row[2] for row in self.comment_rows)
        citation = kinds.get("citation", 0)
        lines = [
            f"## 임포트 리포트 — {self.title} ({self.project_id})" + (" · 합성 fixture" if self.synthetic else ""),
            f"- 원본: {self.source}" + "".join(f" · {n}" for n in self.notes),
            *([titles_line(self.titles)] if self.titles and titles_line(self.titles) else []),
            f"- 장 {len(self.chapters)}개({count_by_labels([c[1] for c in self.chapters])}) · 부 {len(self.parts)}개"
            f" · 그림 {self.figures} · 표 {self.tables} · 수식 {self.equations}",
            f"- 분할 못 한 구간: {self.unsplit_chars:,}자 (original/unsplit.md) — {self.unsplit_preview}",
            f"- 목차 등으로 판단해 버린 제목 줄: {len(self.discarded)}개"
            + (f" — {', '.join(self.discarded[:8])}" + (" …" if len(self.discarded) > 8 else "") if self.discarded else ""),
            f"- 빠진 장 번호: {', '.join(map(str, self.gaps)) or '없음'} · 본문 없는 장: {', '.join(map(str, self.empty_chapters)) or '없음'}",
            f"- 코멘트 → 확인 요청 {len(self.comment_rows)}건: citation {citation}(문헌 지목, refs 연결 {self.comments_linked})"
            f" · fact {kinds.get('fact', 0)}(사실·수치 확인) · general {kinds.get('general', 0)}"
            + (f" · 장 밖 코멘트 {dict(self.comments_outside)}" if self.comments_outside else "")
            + (" · 작성자 " + ", ".join(f"{who} {n}" for who, n in self.comment_authors.most_common()) if self.comment_authors else ""),
            f"- {self.bib.render().splitlines()[0]}",
            *(f"  {line}" for line in self.bib.render().splitlines()[1:]),
        ]
        return "\n".join(lines)

    def mapping_table(self) -> str:
        rows = ["| 파일 | 장 | 제목 | 부 | 글자수 | 코멘트 |", "|---|---|---|---|---:|---:|"]
        rows += [
            f"| ch-{n:02d}.md | {label or f'제{n}장'} | {title} | {part if part is not None else '-'} | {chars:,} | {comments} |"
            for n, label, title, part, chars, comments in self.chapters
        ]
        return "\n".join(rows)

    def comment_table(self) -> str:
        rows = ["| 확인 요청 | 장 | kind | ref_key 후보 | 앞 40자 |", "|---|---|---|---|---|"]
        rows += [
            f"| I{iid} | {ch if ch is not None else '-'} | {kind} | {key or '-'} | {head.replace('|', '/')} |"
            for iid, ch, kind, key, head in self.comment_rows
        ]
        return "\n".join(rows)

    def full(self) -> str:
        return "\n\n".join(
            [self.summary(), "### ch-NN.md ↔ 장 제목", self.mapping_table(), "### 코멘트 분류", self.comment_table()]
        )


def titles_line(t: BookTitles) -> str:
    """'- 부제: … · 영문: … — …'. 부제도 영문도 없으면 빈 문자열."""
    english = " — ".join(x for x in (t.title_en, t.subtitle_en) if x)
    parts = [f"부제: {t.subtitle}" if t.subtitle else "", f"영문: {english}" if english else ""]
    return "- " + " · ".join(x for x in parts if x) if any(parts) else ""


_TITLE_SPLIT = re.compile(r"\s+[—–]\s+|\s*:\s+")  # 파일 속성 제목 "제목 — 부제", "제목: 부제"


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _is_latin(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum(ch.isascii() for ch in letters) / len(letters) > 0.8


def detect_titles(manuscript: Manuscript, cover: list[Block]) -> BookTitles:
    """책 제목과 부제를 따로 읽는다(#77). cover는 첫 제목 앞의 블록(표지·목차).

    - 제목·부제: docx 파일 속성 제목을 '—'·':'에서 나눈다. 속성이 없으면 표지의 Title·Subtitle 서식 문단.
    - 영문 제목·부제: 표지에서 제목(과 부제) 바로 뒤에 오는 라틴 문자 문단 둘까지.
    한글 부제를 표지에서 추정하지는 않는다(바로 뒤 줄이 저자·날짜일 수 있다)."""
    title = subtitle = None
    if manuscript.title:
        head, *tail = _TITLE_SPLIT.split(manuscript.title.strip(), maxsplit=1)
        title, subtitle = head.strip() or None, (tail[0].strip() or None) if tail else None
    paras = [b for b in cover if b.kind == "para" and b.text.strip()]
    styled = {b.style: " ".join(b.text.split()) for b in reversed(paras) if b.style in ("title", "subtitle")}
    if not title and "title" in styled:
        title, subtitle = styled["title"], subtitle or styled.get("subtitle")
    latin: list[str] = []
    if title:
        at = next((n for n, b in enumerate(paras) if _squash(b.text) == _squash(title)), None)
        if at is not None:
            i = at + 1
            if subtitle and i < len(paras) and _squash(paras[i].text) == _squash(subtitle):
                i += 1
            while i < len(paras) and len(latin) < 2 and _is_latin(paras[i].text):
                latin.append(" ".join(paras[i].text.split()))
                i += 1
    return BookTitles(title, subtitle, *(latin + [None, None])[:2])


def cover_blocks(manuscript: Manuscript, split: Split) -> list[Block]:
    """첫 제목 앞의 블록(표지·목차)."""
    cover = []
    for b in manuscript.blocks:
        if split.region_of_block.get(b.index) != "unsplit":
            break
        cover.append(b)
    return cover


def book_titles(manuscript: Manuscript, split: Split, title: str | None, subtitle: str | None, path: Path) -> BookTitles:
    """사람이 준 제목·부제가 먼저, 없으면 원고에서 읽은 것, 그것도 없으면 파일 이름."""
    found = detect_titles(manuscript, cover_blocks(manuscript, split))
    return BookTitles(
        (title or "").strip() or found.title or path.stem,
        (subtitle or "").strip() or found.subtitle,
        found.title_en,
        found.subtitle_en,
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
    subtitle: str | None = None,
    replace: bool = False,
    synthetic: bool = False,
) -> ImportReport:
    path = Path(path)
    manuscript = read_manuscript(path)
    split = split_manuscript(manuscript.blocks)
    if not split.chapters:
        raise ValueError("'제N장' 제목을 하나도 찾지 못했다. 원고의 장 제목 표기를 확인해 주세요.")

    terms: list[str] = []
    ai_names: list[str] = []
    existing = store.get_project(user_id, project_id) if project_id else None
    # 원고 없이 제목만 만든 빈 층(#93)이면 그 층에 원고를 채운다(층의 카테고리·자리는 그대로, 제목은 저자가 지은 것)
    empty = (existing is not None and not replace and not store.list_chapters(user_id, existing.id)
             and not store.list_editions(user_id, existing.id))
    if existing is not None and not empty:
        if not replace:
            raise ValueError(
                f"프로젝트 {project_id!r}가 이미 있다. 같은 책을 Word에서 고쳐 다시 올리는 것이면 수정본으로 올린다"
                "(book_import new_edition=true, 웹 '수정본으로 올리기'). 다른 책이면 새 project_id를 쓴다. "
                "replace=True는 결정·확인 요청까지 휴지통으로 보내고 새로 만든다."
            )
        terms = store.get_non_citation_terms(user_id, existing.id)  # 사람이 정한 비인용 용어는 다시 임포트해도 유지
        ai_names = store.get_ai_authors(user_id, existing.id)  # AI 작성자 이름 목록도 같다
        store.archive_project(user_id, existing.id)
    titles = book_titles(manuscript, split, title, subtitle, path)
    if empty and existing is not None:
        project = store.set_titles(user_id, existing.id, replace_titles(titles, title=title or existing.title))
    else:
        project = store.create_project(user_id, titles.title or path.stem, project_id=project_id, titles=titles)
    files = {"original": store.save_original(user_id, project.id, path.name, path.read_bytes())}
    if terms:
        store.set_non_citation_terms(user_id, project.id, terms)
    if ai_names:
        store.set_ai_authors(user_id, project.id, ai_names)
    exclude = frozenset(terms)

    store.set_parts(user_id, project.id, split.parts)
    empty: list[int] = []
    for ch in split.chapters:
        body = chapter_body(ch)
        if body == EMPTY_BODY:
            empty.append(ch.number)
        store.write_chapter(
            user_id,
            project.id,
            ch.number,
            body,
            f"임포트: {path.name}",
            title=ch.title,
            part_number=ch.part_number,
            label=ch.label,
            edition=1,
        )
    unsplit_md = unsplit_markdown(split)
    files["unsplit"] = store.save_original(user_id, project.id, "unsplit.md", unsplit_md.encode("utf-8"))

    comment_counts: Counter = Counter()
    outside: Counter = Counter()
    authors: Counter = Counter()
    rows: list[tuple[int, int | None, str, str | None, str]] = []
    for e in comment_entries(manuscript, split, exclude, ai_names):
        c = e.comment
        if e.chapter is None:
            outside[e.region or "위치 모름"] += 1
        else:
            comment_counts[e.chapter] += 1
        issue = store.add_issue(
            user_id, project.id, e.issue_text, origin="import_comment", chapter_number=e.chapter, kind=e.kind,
            ref_key=e.ref_key, author=c.author, author_kind=e.author_kind, comment_date=c.date,
            anchor=c.anchor, paragraph=e.paragraph, comment_fp=e.fp,
        )
        rows.append((issue.id, e.chapter, e.kind, e.ref_key, one_line(c.text)[:40]))
        if c.author:
            authors[c.author + ("(AI)" if issue.by_ai else "")] += 1

    bib_report = import_bibliography(store, user_id, "\n".join(b.text for b in split.bib_blocks if b.kind == "para"), project.id)
    after_refs_changed(store, user_id)  # 장별 미확인 인용 수, citation 이슈 → refs 연결(ref_id)
    linked = sum(1 for i in store.list_issues(user_id, project.id, None, kind="citation") if i.ref_id)
    numbers = [c.number for c in split.chapters if not c.label]  # 서장(0)·맺음(90)·부록(9N)·부 들어가며(100+N)는 빼고 본다
    gaps = sorted(set(range(1, max(numbers) + 1)) - set(numbers)) if numbers else []
    report = ImportReport(
        project_id=project.id,
        title=project.title,
        source=f"{path.name} ({manuscript.source})",
        synthetic=synthetic,
        chapters=[
            (ch.number, ch.label, ch.title, ch.part_number, len(ch.markdown()), comment_counts[ch.number])
            for ch in split.chapters
        ],
        parts=split.parts,
        discarded=[f"{h.index}:{'부' if h.kind == 'part' else '장' if h.kind == 'chapter' else '참고문헌'}{h.number or ''}" for h in split.discarded],
        gaps=gaps,
        empty_chapters=empty,
        unsplit_chars=len(unsplit_md),
        unsplit_preview=one_line(unsplit_md)[:40],
        comment_rows=rows,
        comments_linked=linked,
        comments_outside=outside,
        comment_authors=authors,
        titles=titles,
        bib=bib_report,
        figures=manuscript.figures,
        tables=manuscript.tables,
        equations=manuscript.equations,
        notes=manuscript.notes,
        files=files,
    )
    files["report"] = store.save_original(user_id, project.id, "import-report.md", report.full().encode("utf-8"))
    data = path.read_bytes()
    store.add_edition(  # 첫 임포트가 판 E1이다(#76). 다시 올리면 E2, E3…
        user_id, project.id,
        Edition(1, path.name, utcnow(), hashlib.sha256(data).hexdigest(), changed=len(split.chapters), added=len(split.chapters)),
    )
    return report


EMPTY_BODY = "[본문 없음: 임포트 때 이 장 제목 아래에서 글을 찾지 못했다]"


def chapter_body(ch: ChapterPlan) -> str:
    return ch.markdown() or EMPTY_BODY


def unsplit_markdown(split: Split) -> str:
    """장 밖의 글(표지·목차·부 서문). 목차의 점선은 줄여서 보관한다."""
    return re.sub(r"\s*[.…·]{4,}\s*", " … ", blocks_to_markdown(split.unsplit))


@dataclass
class CommentEntry:
    """원고 코멘트 하나를 미해결로 만들 준비: 위치(장·문단), 분류, 작성자 판정, 지문."""

    comment: Comment
    region: int | str | None  # 장 번호 | "unsplit" | "bib" | None(위치 모름)
    kind: IssueKind
    ref_key: str | None
    paragraph: int | None
    author_kind: AuthorKind | None
    fp: str

    @property
    def chapter(self) -> int | None:
        return self.region if isinstance(self.region, int) else None

    @property
    def issue_text(self) -> str:
        anchor = one_line(self.comment.anchor)[:120]
        return (self.comment.text or "(빈 코멘트)") + (f"\n— 원문: “{anchor}”" if anchor else "")


def comment_entries(
    manuscript: Manuscript, split: Split, exclude: frozenset[str], ai_names: list[str]
) -> list[CommentEntry]:
    """문서 순서대로. 같은 지문(작성자·날짜·본문이 같은 코멘트)이 또 나오면 '-2', '-3'을 붙여 가른다."""
    paragraphs = {ch.number: ch.paragraphs() for ch in split.chapters}
    seen: Counter = Counter()
    out = []
    for c in sorted(manuscript.comments, key=lambda c: (c.block_index is None, c.block_index or 0, int(c.id) if c.id.isdigit() else 0)):
        region = split.region_of_block.get(c.block_index) if c.block_index is not None else None
        chapter = region if isinstance(region, int) else None
        kind, ref_key = classify_comment(c.text, c.anchor, exclude)
        fp = comment_fingerprint(c.author, c.date, c.text)
        seen[fp] += 1
        out.append(
            CommentEntry(
                c, region, kind, ref_key,
                paragraphs.get(chapter, {}).get(c.block_index) if chapter is not None else None,
                author_kind(c.author, ai_names),
                fp if seen[fp] == 1 else f"{fp}-{seen[fp]}",
            )
        )
    return out
