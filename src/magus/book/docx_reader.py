"""원고 docx 읽기. 본문을 문서 순서대로 블록(문단·표) 열로 만들고, 코멘트와 그 앵커를 함께 뽑는다.

python-docx의 고수준 API 대신 zip 안의 XML을 직접 읽는다. 코멘트 범위(commentRangeStart/End)가 문단과 표를
가로지를 수 있고, 목차·내용 컨트롤(sdt)·삭제된 변경 내용 같은 구조를 정확히 다뤄야 하기 때문이다.
그림·수식은 자리표시자([그림 N], [수식])로 남긴다. 표는 칸의 글까지 markdown 표로 싣는다(#69, 칸이 모두 비면 [표 N]).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
DC = "http://purl.org/dc/elements/1.1/"


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


_HEADING_STYLE = re.compile(r"(?:heading|제목)\s*(\d)", re.I)
_SKIP = {_w("del"), _w("delText"), _w("instrText"), _w("footnoteReference"), _w("endnoteReference"), _w("rPr"), _w("pPr")}
_FIGURE = {_w("drawing"), _w("pict"), _w("object")}
_MATH = {f"{{{M}}}oMath", f"{{{M}}}oMathPara"}


@dataclass
class Block:
    index: int
    kind: Literal["para", "table"]
    text: str
    style: str = ""
    heading_level: int | None = None
    is_list: bool = False


@dataclass
class Comment:
    id: str
    author: str
    text: str
    block_index: int | None = None
    anchor: str = ""
    date: str = ""  # Word의 w:date(작성 시각). PDF에는 없다


@dataclass
class Manuscript:
    blocks: list[Block]
    comments: list[Comment]
    title: str | None = None
    figures: int = 0
    tables: int = 0
    equations: int = 0
    source: Literal["docx", "pdf"] = "docx"
    notes: list[str] = field(default_factory=list)


class _Walker:
    def __init__(self, style_names: dict[str, str]):
        self.style_names = style_names
        self.blocks: list[Block] = []
        self.open: dict[str, list[str]] = {}
        self.anchors: dict[str, str] = {}
        self.comment_block: dict[str, int] = {}
        self.point_comments: set[str] = set()
        self.figures = self.tables = self.equations = 0

    def body(self, parent: etree._Element) -> None:
        for el in parent:
            if el.tag == _w("p"):
                self.paragraph(el)
            elif el.tag == _w("tbl"):
                self.table(el)
            elif el.tag == _w("sdt"):
                content = el.find(_w("sdtContent"))
                if content is not None:
                    self.body(content)

    def paragraph(self, p: etree._Element) -> None:
        index = len(self.blocks)
        parts: list[str] = []
        self._visit(p, parts, index)
        text = "".join(parts).strip()
        for buf in self.open.values():
            buf.append("\n")
        for cid in self.point_comments:
            self.anchors.setdefault(cid, text)
        self.point_comments.clear()
        style_id = p.find(f"{_w('pPr')}/{_w('pStyle')}")
        style = self.style_names.get(style_id.get(_w("val")), style_id.get(_w("val"))) if style_id is not None else ""
        level = None
        if m := _HEADING_STYLE.search(style or ""):
            level = int(m.group(1))
        elif (outline := p.find(f"{_w('pPr')}/{_w('outlineLvl')}")) is not None:
            level = int(outline.get(_w("val"), "9")) + 1
        is_list = p.find(f"{_w('pPr')}/{_w('numPr')}") is not None
        self.blocks.append(Block(index, "para", text, (style or "").lower(), level, is_list))

    def table(self, tbl: etree._Element) -> None:
        # 표는 markdown 표(| 칸 |)로 싣는다(#69). 칸 안의 여러 문단·안쪽 표는 공백으로 잇는다.
        # 가로로 합친 칸(gridSpan)은 빈 칸으로 채워 줄마다 칸 수를 맞춘다. 칸이 모두 비면 자리표시자만 남긴다.
        self.tables += 1
        index = len(self.blocks)
        rows: list[list[str]] = []
        for tr in tbl.findall(_w("tr")):
            row: list[str] = []
            for tc in tr.findall(_w("tc")):
                texts = []
                for p in tc.iter(_w("p")):
                    parts: list[str] = []
                    self._visit(p, parts, index)
                    for buf in self.open.values():
                        buf.append("\n")
                    if text := " ".join("".join(parts).split()):
                        texts.append(text)
                row.append(" ".join(texts))
                span = tc.find(f"{_w('tcPr')}/{_w('gridSpan')}")
                row += [""] * (int(span.get(_w("val"), "1")) - 1 if span is not None else 0)
            rows.append(row)
        text = markdown_table(rows) if any(cell for row in rows for cell in row) else f"[표 {self.tables}]"
        self.blocks.append(Block(index, "table", text))

    def _emit_text(self, parts: list[str], text: str) -> None:
        parts.append(text)
        for buf in self.open.values():
            buf.append(text)

    def _visit(self, el: etree._Element, parts: list[str], index: int) -> None:
        for child in el:
            tag = child.tag
            if not isinstance(tag, str) or tag in _SKIP:
                continue
            if tag == _w("t"):
                self._emit_text(parts, child.text or "")
            elif tag == _w("tab"):
                self._emit_text(parts, "\t")
            elif tag in (_w("br"), _w("cr")):
                self._emit_text(parts, "\n")
            elif tag in _FIGURE:
                self.figures += 1
                self._emit_text(parts, f"[그림 {self.figures}]")
            elif tag in _MATH:
                self.equations += 1
                self._emit_text(parts, "[수식]")
            elif tag == _w("commentRangeStart"):
                cid = child.get(_w("id"))
                self.open[cid] = []
                self.comment_block.setdefault(cid, index)
            elif tag == _w("commentRangeEnd"):
                cid = child.get(_w("id"))
                if cid in self.open:
                    self.anchors[cid] = "".join(self.open.pop(cid)).strip()
            elif tag == _w("commentReference"):
                cid = child.get(_w("id"))
                if cid not in self.comment_block:  # 범위 없이 한 점에만 달린 코멘트: 그 문단 전체를 앵커로
                    self.comment_block[cid] = index
                    self.point_comments.add(cid)
            else:
                self._visit(child, parts, index)


def markdown_table(rows: list[list[str]]) -> str:
    """첫 줄을 머리글로 쓰는 pipe 표. 칸 안의 '|'는 이스케이프한다. pandoc(export)이 Word 표로 되돌린다."""
    width = max(len(row) for row in rows)

    def line(cells: list[str]) -> str:
        cells = [c.replace("|", "\\|") for c in cells] + [""] * (width - len(cells))
        return "| " + " | ".join(cells) + " |"

    return "\n".join([line(rows[0]), "|" + "---|" * width, *(line(row) for row in rows[1:])])


def _style_names(xml: bytes) -> dict[str, str]:
    root = etree.fromstring(xml)
    names = {}
    for style in root.iter(_w("style")):
        name = style.find(_w("name"))
        names[style.get(_w("styleId"))] = name.get(_w("val")) if name is not None else style.get(_w("styleId"))
    return names


def _comments(xml: bytes) -> dict[str, tuple[str, str, str]]:
    """id → (작성자, 날짜, 본문)."""
    root = etree.fromstring(xml)
    out = {}
    for c in root.iter(_w("comment")):
        paras = ["".join(t.text or "" for t in p.iter(_w("t"))) for p in c.iter(_w("p"))]
        text = "\n".join(x for x in paras if x.strip()).strip()
        out[c.get(_w("id"))] = (c.get(_w("author"), ""), c.get(_w("date"), ""), text)
    return out


def read_docx(path: Path) -> Manuscript:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        document = etree.fromstring(z.read("word/document.xml"))
        styles = _style_names(z.read("word/styles.xml")) if "word/styles.xml" in names else {}
        raw_comments = _comments(z.read("word/comments.xml")) if "word/comments.xml" in names else {}
        title = None
        if "docProps/core.xml" in names:
            node = etree.fromstring(z.read("docProps/core.xml")).find(f"{{{DC}}}title")
            title = (node.text or "").strip() or None if node is not None else None

    walker = _Walker(styles)
    body = document.find(_w("body"))
    if body is not None:
        walker.body(body)
    comments = [
        Comment(
            id=cid,
            author=author,
            text=text,
            block_index=walker.comment_block.get(cid),
            anchor=walker.anchors.get(cid, "".join(walker.open.get(cid, [])).strip()),
            date=date,
        )
        for cid, (author, date, text) in raw_comments.items()
    ]
    return Manuscript(walker.blocks, comments, title, walker.figures, walker.tables, walker.equations)
