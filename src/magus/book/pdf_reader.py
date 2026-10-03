"""원고 PDF 폴백(Word가 '메모 포함' 마크업으로 내보낸 PDF). docx가 없을 때 쓴다.

Word PDF는 줄마다 따로 된 텍스트 조각이고, 문단·제목·말풍선 구분이 없다. 그래서 레이아웃으로 되살린다.
- 페이지 위아래의 반복 머리말과 쪽번호를 뺀다.
- 오른쪽 여백 단(x ≥ 쪽 너비의 68%)은 말풍선이다. "메모 포함[Cn]:"부터 다음 말풍선 전까지가 코멘트 하나다.
- 본문 줄은 문단으로 잇는다. 한국어는 단어 중간에서도 줄이 바뀌므로 줄 사이에 공백을 넣지 않는다.
  새 문단: 제목 줄, 들여쓰기 줄(왼쪽 여백 + 4~11pt, 글머리표 포함), 내어쓰기(참고문헌·글머리표 둘째 줄)가 끝나고
  여백으로 돌아온 줄, 같은 글자 크기의 보통 줄 간격보다 25% 넘게 벌어진 줄.
- 글자 크기로 제목 단계를 정한다(본문보다 1.5pt 이상 크거나, 굵고 0.5pt 이상 크면 제목).
- 코멘트 앵커는 말풍선 첫 줄 높이와 같거나 그보다 위에 있는 마지막 본문 줄이 든 문단이다(Word는 말풍선을 앵커 줄 높이에 둔다).
- 본문 단의 그림은 [그림 N]으로 남긴다. 표·수식은 구분하지 못한다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from magus.book.docx_reader import Block, Comment, Manuscript

_COMMENT_START = re.compile(r"^\s*메모\s*포함\s*\[\s*C\s*(\d+)\s*\]\s*[:：]?\s*")
_BULLET = re.compile(r"^\s*[•▪◦·\-–‣●■□○]\s")
_PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
MARGIN_COLUMN = 0.68  # 쪽 너비 대비 말풍선 단이 시작하는 위치
MIN_FIGURE_AREA = 1500  # pt². 이보다 작은 이미지(글리프 대용 등)는 그림으로 보지 않는다


@dataclass
class _Line:
    page: int
    x0: float
    y0: float
    y1: float
    text: str
    size: float
    bold: bool
    figure: bool = False


def _join(parts: list[str]) -> str:
    out = ""
    for part in parts:
        if out and re.search(r"[A-Za-z0-9,.;:)]$", out) and re.match(r"[A-Za-z(]", part):
            out += " "  # 라틴 문자끼리는 줄 끝 공백이 빠져도 띄운다. 한국어는 붙인다.
        out += part
    return re.sub(r"[ \t]+", " ", out).strip()


def _read_lines(doc: pymupdf.Document) -> tuple[list[_Line], list[_Line]]:
    body: list[_Line] = []
    margin: list[_Line] = []
    for pno, page in enumerate(doc):
        split_x = page.rect.width * MARGIN_COLUMN
        for block in page.get_text("dict")["blocks"]:
            x0, y0, x1, y1 = block["bbox"]
            if block["type"] == 1:
                if x0 < split_x and (x1 - x0) * (y1 - y0) >= MIN_FIGURE_AREA:
                    body.append(_Line(pno, x0, y0, y1, "", 0, False, figure=True))
                continue
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in line["spans"]).replace("\n", "")
                lx0, ly0, _, ly1 = line["bbox"]
                item = _Line(
                    pno, lx0, ly0, ly1, text, max(s["size"] for s in spans), all(s["flags"] & 16 for s in spans)
                )
                (margin if lx0 >= split_x else body).append(item)
    return body, margin


def _drop_running(lines: list[_Line], pages: int, height_of: dict[int, float]) -> list[_Line]:
    """여러 쪽에 되풀이되는 위·아래 띠의 글(머리말)과 쪽번호를 뺀다."""
    def band(line: _Line) -> bool:
        h = height_of[line.page]
        return line.y1 < h * 0.17 or line.y0 > h * 0.80

    repeated = Counter(line.text.strip() for line in lines if band(line))
    common = {t for t, n in repeated.items() if n >= max(3, pages * 0.2)}
    return [
        line for line in lines
        if not (band(line) and (line.text.strip() in common or _PAGE_NUMBER.match(line.text)))
    ]


def _merge_rows(lines: list[_Line]) -> list[_Line]:
    """같은 높이(세로 중심 차 3pt 미만)의 조각을 한 줄로 잇는다. 글자 하나가 이미지로 그려지면 한 줄이
    두 조각으로 갈리고, 뒤 조각의 y가 미세하게 위에 있어 순서가 뒤집힌다(실원고 참고문헌에서 확인)."""
    ordered = sorted(lines, key=lambda line: (line.page, (line.y0 + line.y1) / 2, line.x0))
    rows: list[list[_Line]] = []
    for line in ordered:
        last = rows[-1][-1] if rows else None
        if (
            last is not None
            and not line.figure
            and not last.figure
            and last.page == line.page
            and abs((last.y0 + last.y1) / 2 - (line.y0 + line.y1) / 2) < 3
        ):
            rows[-1].append(line)
        else:
            rows.append([line])
    merged = []
    for row in rows:
        row.sort(key=lambda line: line.x0)
        head = row[0]
        # 조각 사이는 띄우고(표의 칸, 끊긴 글자열), 마지막 조각의 줄 끝 공백 여부는 그대로 둔다(한국어 줄바꿈 판정용)
        text = head.text if len(row) == 1 else " ".join(r.text.strip() for r in row[:-1]) + " " + row[-1].text.lstrip()
        merged.append(
            _Line(head.page, head.x0, min(r.y0 for r in row), max(r.y1 for r in row), text,
                  max(r.size for r in row), all(r.bold for r in row), head.figure)
        )
    return merged


def read_pdf(path: Path) -> Manuscript:
    with pymupdf.open(path) as doc:
        title = (doc.metadata or {}).get("title") or None
        heights = {i: page.rect.height for i, page in enumerate(doc)}
        body, margin = _read_lines(doc)
        pages = doc.page_count
    body = _merge_rows(_drop_running(body, pages, heights))
    margin = _merge_rows(_drop_running(margin, pages, heights))

    text_lines = [line for line in body if not line.figure]
    size_chars = Counter()
    for line in text_lines:
        size_chars[round(line.size, 1)] += len(line.text)
    body_size = size_chars.most_common(1)[0][0] if size_chars else 10.0
    left = Counter(round(line.x0) for line in text_lines if abs(line.size - body_size) < 0.3).most_common(1)
    left_margin = left[0][0] if left else min((line.x0 for line in text_lines), default=0)

    def heading_level(line: _Line) -> int | None:
        if line.size >= body_size + 1.5 or (line.bold and line.size >= body_size + 0.5):
            return 1 if line.size >= body_size + 3 else (2 if line.size >= body_size + 1.5 else 3)
        return None

    # 글자 크기별 보통 줄 간격(같은 쪽, 이어지는 두 줄). 문단 사이 간격은 이보다 크다.
    gaps: dict[float, list[float]] = {}
    for prev, line in zip(text_lines, text_lines[1:], strict=False):
        if prev.page == line.page and round(prev.size, 1) == round(line.size, 1) and line.y0 > prev.y0:
            gaps.setdefault(round(line.size, 1), []).append(round(line.y0 - prev.y0, 1))
    typical = {size: Counter(values).most_common(1)[0][0] for size, values in gaps.items() if values}

    # 글자 크기별 문단 서식: 첫 줄 들여쓰기(본문)인가, 내어쓰기(참고문헌: 첫 줄은 여백, 둘째 줄부터 들여씀)인가.
    # 내어쓰기 서식에서는 여백에서 시작하는 줄이 곧 새 항목이다(한 줄짜리 항목이 많으면 줄 간격으로는 못 가른다).
    shape: dict[float, Counter] = {}
    for line in text_lines:
        offset = line.x0 - left_margin
        cls = "indent" if 4 <= offset <= 11 else ("deep" if offset > 11 else "flush")
        shape.setdefault(round(line.size, 1), Counter())[cls] += 1
    hanging = {size for size, c in shape.items() if c["deep"] >= 3 and c["indent"] <= 0.05 * sum(c.values())}

    blocks: list[Block] = []
    line_block: list[tuple[int, float, int]] = []  # (쪽, y0, 블록 번호) — 코멘트 앵커 찾기용
    figures = 0
    current: list[str] = []
    current_level: int | None = None
    current_size = 0.0
    prev: _Line | None = None

    def flush() -> None:
        nonlocal current, current_level
        if current:
            blocks.append(Block(len(blocks), "para", _join(current), heading_level=current_level))
        current, current_level = [], None

    for line in body:
        if line.figure:
            flush()
            figures += 1
            blocks.append(Block(len(blocks), "para", f"[그림 {figures}]"))
            line_block.append((line.page, line.y0, len(blocks) - 1))
            prev = None
            continue
        level = heading_level(line)
        offset = line.x0 - left_margin
        new = prev is None and not current
        if prev is not None:
            same_page = prev.page == line.page
            gap = line.y0 - prev.y0 if same_page else 0
            size_changed = abs(line.size - current_size) > 0.3
            prev_offset = prev.x0 - left_margin
            if level != current_level or (level is not None and size_changed):
                new = True
            elif level is not None:
                new = same_page and gap > typical.get(round(line.size, 1), gap) * 1.6
            else:
                new = (
                    size_changed
                    or 4 <= offset <= 11  # 첫 줄 들여쓰기·글머리표
                    or bool(_BULLET.match(line.text))
                    or (offset < 3 and prev_offset >= 11)  # 내어쓰기가 끝나고 여백으로 돌아옴
                    or (offset < 3 and round(line.size, 1) in hanging)  # 내어쓰기 서식: 여백 줄 = 새 항목
                    or (same_page and gap > typical.get(round(line.size, 1), 1e9) * 1.25)
                )
        if new:
            flush()
            current_level, current_size = level, line.size
        current.append(line.text)
        line_block.append((line.page, line.y0, len(blocks)))  # flush 전이므로 지금 쌓는 블록의 번호
        prev = line
    flush()

    comments: list[Comment] = []
    group: list[_Line] = []

    def close_comment() -> None:
        if not group or not (m := _COMMENT_START.match(group[0].text)):
            return
        text = _join([group[0].text[m.end():], *(g.text for g in group[1:])])
        top = group[0]
        anchor_index = None
        for page, y0, index in line_block:  # 같은 쪽에서 말풍선 높이 이하의 마지막 본문 줄
            if (page, y0) <= (top.page, top.y0 + 3):
                anchor_index = index
            else:
                break
        anchor_index = min(anchor_index, len(blocks) - 1) if anchor_index is not None else None
        comments.append(
            Comment(
                id=m.group(1),
                author="",
                text=text,
                block_index=anchor_index,
                anchor=blocks[anchor_index].text if anchor_index is not None else "",
            )
        )

    for line in margin:
        if _COMMENT_START.match(line.text):
            close_comment()
            group = [line]
        elif group:
            group.append(line)
    close_comment()

    notes = ["코멘트는 PDF 텍스트(말풍선 '메모 포함[Cn]')에서 추출 · 앵커는 말풍선 높이의 문단으로 근사 · 표·수식은 구분하지 못함"]
    return Manuscript(blocks, comments, title, figures=figures, source="pdf", notes=notes)
