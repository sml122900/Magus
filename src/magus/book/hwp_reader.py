"""한글 원고 읽기(2026-10-14, docs/decisions/hwp-import.md): hwpx(OWPML, zip + XML)와 hwp 5.0(OLE 바이너리)을
docx_reader와 같은 블록 열(Manuscript)로 만든다. 장 나누기·코멘트 분류·참고문헌은 importer가 docx와 똑같이 한다.

- 제목 단계: 문단 스타일 이름(개요 N · Outline N · 제목 N · Heading N), 없으면 문단 모양의 개요 수준. '제N장'·'제N부' 글자 판정은 importer가 한다.
- 표 → markdown 표(칸 주소로 자리를 잡고, 합친 칸은 빈 칸). 그림·도형·글상자·OLE → [그림 N], 수식 → [수식].
- 각주·미주 → markdown 각주(본문에 [^N], 그 문단 뒤에 '[^N]: 내용'). 내보내기(pandoc)에서 Word 각주가 된다. 번호는 문서 전체에서 하나씩.
- 메모: hwpx의 메모 필드(fieldBegin type=MEMO … fieldEnd)를 코멘트로(작성자·날짜·걸린 글). hwp(바이너리)의 메모는 아직 가져오지 않고 리포트에 수만 적는다.
- 머리말·꼬리말·숨은 설명은 싣지 않는다(docx와 같다). 변경 추적으로 지운 글자도 싣지 않는다(hwpx).
- 암호·배포용·DRM 문서와 한글 97 이전(hwp 3.x)은 저자에게 보일 문장(ValueError)으로 멈춘다. 압축 폭탄은 zipguard 규칙(항목 수·풀린 합·압축률)으로 막는다.
- 첨부 글자 뽑기(magus.extract)와 따로 둔다: 그쪽은 글자만 흘려 읽고, 이쪽은 문단·표·메모 구조가 필요하다.
"""

from __future__ import annotations

import re
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from magus import zipguard
from magus.book.docx_reader import Block, Comment, Manuscript, markdown_table

HEADING_STYLE = re.compile(r"(?:개요|outline|heading|제목)\s*(\d{1,2})", re.I)
MAX_LEVEL = 9
LOCKED = ("암호가 걸렸거나 배포용인 한글 문서는 가져오지 못합니다. 한글에서 암호를 풀어(배포용이면 배포용으로 만들기 전 파일을) "
          "다시 저장해 올려 주세요.")
OLD_HWP = "한글 97 이전 형식(hwp 3.x)은 가져오지 못합니다. 한글에서 hwpx나 hwp로 다시 저장해 올려 주세요."


class Unreadable(Exception):
    """깨졌거나 한글 문서가 아닌 파일. importer가 저자에게 보일 문장(UNREADABLE)으로 바꾼다."""


def _local(tag: object) -> str:
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""


# ---- 개요 번호 -------------------------------------------------------------------------------------------------
# 한글은 개요 문단의 번호('제1장', '1.', '가.')를 글자로 저장하지 않고 번호 정의(형식 '제^1장', 모양 DIGIT 등)로 그린다.
# '제N장'을 글자로 찾는 importer가 장을 찾도록, 화면에 보이는 번호를 문단 앞에 붙인다(글자가 이미 그 번호로 시작하면 붙이지 않는다).

_SYLLABLES, _JAMO = "가나다라마바사아자차카타파하", "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
_PHONETIC, _IDEOGRAPH = "일이삼사오육칠팔구십", "一二三四五六七八九十"
# hwp 바이너리의 번호 모양(문단 머리 정보 속성 bit 5~8) → hwpx의 numFormat 이름
HWP_SHAPES = ("DIGIT", "CIRCLED_DIGIT", "ROMAN_CAPITAL", "ROMAN_SMALL", "LATIN_CAPITAL", "LATIN_SMALL", "CIRCLED_LATIN_CAPITAL",
              "CIRCLED_LATIN_SMALL", "HANGUL_SYLLABLE", "CIRCLED_HANGUL_SYLLABLE", "HANGUL_JAMO", "CIRCLED_HANGUL_JAMO",
              "HANGUL_PHONETIC", "IDEOGRAPH", "CIRCLED_IDEOGRAPH")


def _roman(n: int) -> str:
    out = ""
    for value, mark in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out, n = out + mark, n - value
    return out


def number_text(n: int, fmt: str) -> str:
    """번호 하나를 모양대로(모르는 모양·범위 밖은 아라비아 숫자)."""
    fmt = (fmt or "DIGIT").upper()
    if n < 1:
        return str(n)
    if fmt == "CIRCLED_DIGIT" and n <= 20:
        return chr(0x2460 + n - 1)
    if fmt in ("ROMAN_CAPITAL", "ROMAN_SMALL") and n < 4000:
        return _roman(n) if fmt == "ROMAN_CAPITAL" else _roman(n).lower()
    if fmt in ("LATIN_CAPITAL", "LATIN_SMALL", "CIRCLED_LATIN_CAPITAL", "CIRCLED_LATIN_SMALL"):
        k = (n - 1) % 26
        return chr({"LATIN_CAPITAL": 0x41, "LATIN_SMALL": 0x61, "CIRCLED_LATIN_CAPITAL": 0x24B6, "CIRCLED_LATIN_SMALL": 0x24D0}[fmt] + k)
    if fmt == "HANGUL_SYLLABLE":
        return _SYLLABLES[(n - 1) % 14]
    if fmt == "CIRCLED_HANGUL_SYLLABLE":
        return chr(0x326E + (n - 1) % 14)
    if fmt == "HANGUL_JAMO":
        return _JAMO[(n - 1) % 14]
    if fmt == "CIRCLED_HANGUL_JAMO":
        return chr(0x3260 + (n - 1) % 14)
    if fmt == "HANGUL_PHONETIC" and n <= 10:
        return _PHONETIC[n - 1]
    if fmt in ("IDEOGRAPH", "CIRCLED_IDEOGRAPH") and n <= 10:
        return _IDEOGRAPH[n - 1]
    return str(n)


class Outline:
    """번호 정의 id → 수준별 (시작 번호, 모양, 형식 글). 개요 문단마다 그 수준을 하나 올리고 아래 수준은 처음으로 돌린다."""

    def __init__(self, numberings: dict[str, list[tuple[int, str, str]]]):
        self.numberings = numberings
        self.counts: dict[str, list[int]] = {}

    def prefix(self, numbering: str | None, level: int) -> str:
        levels = self.numberings.get(numbering or "")
        if not levels or not 0 <= level < len(levels):
            return ""
        counts = self.counts.setdefault(numbering, [0] * len(levels))
        counts[level] = counts[level] + 1 if counts[level] else max(levels[level][0], 1)
        for k in range(level + 1, len(counts)):
            counts[k] = 0

        def fill(m: re.Match[str]) -> str:
            k = int(m.group(1)) - 1
            if k >= len(levels):
                return ""
            return number_text(counts[k] or max(levels[k][0], 1), levels[k][1])

        return re.sub(r"\^(10|[1-9])", fill, levels[level][2]).strip()


_TYPED_HEAD = re.compile(r"^\s*(?:제\s*\d+\s*[장부]|서장|프롤로그|맺음|에필로그|나가며|부록|참\s*고\s*문\s*헌)")


def with_prefix(prefix: str, text: str) -> str:
    """'제1장' + '물고기의 결심' → '제1장 물고기의 결심'. 글자가 이미 그 번호로 시작하거나(손으로 적었으면) 장·부 제목을
    손으로 적었으면('제1장 …'에 기본 개요 번호 '1.'이 붙어 보이는 문서) 그대로 둔다. 장 찾기는 손으로 적은 글자를 따른다."""
    if not prefix or _squash(text).startswith(_squash(prefix)) or _TYPED_HEAD.match(text):
        return text
    return f"{prefix} {text}" if text else prefix


def _squash(text: str) -> str:
    return "".join(text.split())


def _top_paras(el: etree._Element) -> Iterator[etree._Element]:
    """el 안의 문단(hp:p) 중 다른 문단 안에 들지 않은 것(표 칸·각주·메모의 문단 목록)."""
    for child in el:
        if _local(child.tag) == "p":
            yield child
        else:
            yield from _top_paras(child)


# ---- hwpx ----------------------------------------------------------------------------------------------------

_INSIDE = {"tab": "\t", "lineBreak": "\n", "nbSpace": " ", "fwSpace": " ", "hyphen": "-"}  # hp:t 안의 글자 요소
_FIGURES = frozenset({"pic", "ole", "container", "rect", "ellipse", "arc", "polygon", "curve", "connectLine", "line",
                      "textart", "video", "chart"})
_SKIP = frozenset({"secPr", "linesegarray", "header", "footer", "hiddenComment", "parameters", "memogroup", "memo",
                   "colPr", "pageNum", "pageHiding", "pageNumCtrl"})
_XML = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def _xml(z: zipfile.ZipFile, name: str) -> etree._Element:
    return etree.fromstring(z.read(name), _XML)


class _HwpxWalker:
    def __init__(self, styles: dict[str, tuple[str, str]], heads: dict[str, tuple[str, str, int]], outline: Outline):
        self.styles, self.heads, self.outline = styles, heads, outline
        self.outline_ref: str | None = None  # 구역 속성(secPr)의 개요 번호 정의 id
        self.blocks: list[Block] = []
        self.open: dict[str, list[str]] = {}  # 메모 id → 걸린 글(아직 fieldEnd를 못 만남)
        self.anchors: dict[str, str] = {}
        self.comment_block: dict[str, int] = {}
        self.memos: dict[str, tuple[str, str, str]] = {}  # 메모 id → (작성자, 날짜, 내용)
        self.memo_refs: dict[str, set[str]] = {}  # 메모 id → 그 필드의 다른 값들(메모 묶음에서 내용을 찾을 때)
        self.ends: dict[str, str] = {}  # fieldEnd가 가리키는 값(beginIDRef·fieldid) → 메모 id
        self.bodies: dict[str, tuple[str, str, str]] = {}  # 메모 묶음(hp:memo)의 id → (작성자, 날짜, 내용)
        self.deleting = False
        self.cell_depth = 0
        self.pending_tables: list[etree._Element] = []
        self.pending_notes: list[str] = []
        self.figures = self.tables = self.equations = self.footnotes = 0

    def section(self, root: etree._Element) -> None:
        sec_pr = next((x for x in root.iter() if _local(x.tag) == "secPr"), None)
        if sec_pr is not None and sec_pr.get("outlineShapeIDRef"):
            self.outline_ref = sec_pr.get("outlineShapeIDRef")
        for el in root:
            if _local(el.tag) == "p":
                self.paragraph(el)
        for memo in root.iter():
            if _local(memo.tag) == "memo" and memo.get("id"):
                self.bodies[memo.get("id")] = (memo.get("author") or "", memo.get("date") or memo.get("createDateTime") or "",
                                               _paras_text(memo))

    def _level(self, p: etree._Element) -> tuple[str, int | None, bool]:
        name, eng = self.styles.get(p.get("styleIDRef") or "", ("", ""))
        style = (eng or name).lower()
        kind, _, level = self.heads.get(p.get("paraPrIDRef") or "", ("NONE", "", 0))
        for s in (name, eng):
            if m := HEADING_STYLE.search(s or ""):
                return style, min(int(m.group(1)), MAX_LEVEL), False
        if kind == "OUTLINE":
            return style, min(level + 1, MAX_LEVEL), False
        return style, None, kind in ("NUMBER", "BULLET")

    def paragraph(self, p: etree._Element) -> None:
        index = len(self.blocks)
        parts: list[str] = []
        self._visit(p, parts, index)
        for buf in self.open.values():
            buf.append("\n")
        style, level, is_list = self._level(p)
        text = "".join(parts).strip()
        kind, ref, depth = self.heads.get(p.get("paraPrIDRef") or "", ("NONE", "", 0))
        if kind == "OUTLINE":  # 개요 번호(글자로 저장되지 않는다)
            text = with_prefix(self.outline.prefix(self.outline_ref or ref, depth), text)
        self.blocks.append(Block(index, "para", text, style, level, is_list))
        tables, self.pending_tables = self.pending_tables, []
        for tbl in tables:  # 문단 안에 놓인 표는 그 문단 다음 블록(docx는 문단과 나란히 놓인다)
            self.table(tbl)
        notes, self.pending_notes = self.pending_notes, []
        for note in notes:
            self.blocks.append(Block(len(self.blocks), "para", note))

    def table(self, tbl: etree._Element) -> None:
        self.tables += 1
        index = len(self.blocks)
        grid: dict[tuple[int, int], str] = {}
        for r, tr in enumerate(x for x in tbl if _local(x.tag) == "tr"):
            for c, tc in enumerate(x for x in tr if _local(x.tag) == "tc"):
                addr = next((x for x in tc if _local(x.tag) == "cellAddr"), None)
                try:
                    at = (int(addr.get("rowAddr")), int(addr.get("colAddr"))) if addr is not None else (r, c)
                except (TypeError, ValueError):
                    at = (r, c)
                if at in grid or min(at) < 0 or max(at) > 1000:  # 주소가 겹치거나 엉뚱하면 차례대로
                    at = (r, c)
                texts = []
                self.cell_depth += 1
                for p in _top_paras(tc):
                    parts: list[str] = []
                    self._visit(p, parts, index)
                    for buf in self.open.values():
                        buf.append("\n")
                    if text := " ".join("".join(parts).split()):
                        texts.append(text)
                self.cell_depth -= 1
                grid[at] = " ".join(texts)
        rows = max((r for r, _ in grid), default=-1) + 1
        cols = max((c for _, c in grid), default=-1) + 1
        table = [[grid.get((r, c), "") for c in range(cols)] for r in range(rows)]
        text = markdown_table(table) if any(cell for row in table for cell in row) else f"[표 {self.tables}]"
        self.blocks.append(Block(index, "table", text))
        if caption := _caption(tbl):  # 표 캡션('표 1. …')은 표 다음 문단으로
            self.blocks.append(Block(len(self.blocks), "para", caption))

    def _emit(self, parts: list[str], text: str) -> None:
        parts.append(text)
        for buf in self.open.values():
            buf.append(text)

    def _text(self, t: etree._Element, parts: list[str]) -> None:
        if t.text and not self.deleting:
            self._emit(parts, t.text)
        for child in t:
            name = _local(child.tag)
            if name in ("deleteBegin", "deleteEnd"):
                self.deleting = name == "deleteBegin"
            elif name in _INSIDE and not self.deleting:
                self._emit(parts, _INSIDE[name])
            if child.tail and not self.deleting:
                self._emit(parts, child.tail)

    def _visit(self, el: etree._Element, parts: list[str], index: int) -> None:
        for child in el:
            name = _local(child.tag)
            if not name or name in _SKIP:
                continue
            if name == "t":
                self._text(child, parts)
            elif name == "tbl":
                if self.cell_depth:  # 표 칸 안의 표는 그 칸의 글로
                    for p in _top_paras(child):
                        self._visit(p, parts, index)
                        self._emit(parts, " ")
                else:
                    self.pending_tables.append(child)
            elif name in _FIGURES:
                self.figures += 1
                caption = _caption(child)
                self._emit(parts, f"[그림 {self.figures}]" + (f" {caption}" if caption else ""))
            elif name == "equation":
                self.equations += 1
                self._emit(parts, "[수식]")
            elif name == "fieldBegin":
                self._memo_begin(child, index)
            elif name == "fieldEnd":
                self._memo_end(child)
            elif name in ("footNote", "endNote"):
                self.footnotes += 1
                self._emit(parts, f"[^{self.footnotes}]")
                self.pending_notes.append(f"[^{self.footnotes}]: {_paras_text(child, ' ') or '(빈 각주)'}")
            elif name in ("deleteBegin", "deleteEnd"):
                self.deleting = name == "deleteBegin"
            elif name == "switch":  # 호환 묶음: 기본(default)만 읽는다(case와 같은 내용이 두 번 들어 있다)
                chosen = next((x for x in child if _local(x.tag) == "default"), None)
                if chosen is None:
                    chosen = next((x for x in child if _local(x.tag) == "case"), None)
                if chosen is not None:
                    self._visit(chosen, parts, index)
            else:
                self._visit(child, parts, index)

    def _memo_begin(self, field: etree._Element, index: int) -> None:
        if (field.get("type") or "").upper() != "MEMO":
            return  # 누름틀·하이퍼링크 같은 다른 필드는 글자만(필드 안 안내문·인자는 싣지 않는다)
        cid = field.get("id") or field.get("fieldid") or f"memo{len(self.memos) + 1}"
        author = date = ""
        refs = {x for x in (field.get("fieldid"), field.get("name")) if x}
        params = (x for group in field if _local(group.tag) == "parameters" for x in group.iter())
        for param in params:
            key = (param.get("name") or "").lower()
            value = (param.text or "").strip() if _local(param.tag) != "parameters" else ""
            if not value:
                continue
            refs.add(value)
            if key in ("author", "writer", "작성자") and not author:
                author = value
            elif ("date" in key or "time" in key) and not date:
                date = value
        self.memos[cid] = (author, date, _paras_text(field))
        self.memo_refs[cid] = refs
        for key in (cid, field.get("fieldid")):
            if key:
                self.ends[key] = cid
        self.open[cid] = []
        self.comment_block.setdefault(cid, index)

    def _memo_end(self, end: etree._Element) -> None:
        cid = self.ends.get(end.get("beginIDRef") or "") or self.ends.get(end.get("fieldid") or "")
        if cid in self.open:
            self.anchors[cid] = "".join(self.open.pop(cid)).strip()

    def comments(self) -> list[Comment]:
        """메모 내용이 필드 안에 없으면 메모 묶음(hp:memo)에서 id로, 그래도 없으면 차례로 찾는다."""
        named = set(self.memos).union(*self.memo_refs.values())
        spare = [k for k in self.bodies if k not in named]
        out = []
        for cid, (author, date, text) in self.memos.items():
            if not text:
                hit = next((self.bodies[k] for k in self.memo_refs[cid] | {cid} if k in self.bodies), None)
                if hit is None and spare:
                    hit = self.bodies[spare.pop(0)]
                if hit is not None:
                    author, date, text = author or hit[0], date or hit[1], hit[2]
            anchor = self.anchors.get(cid, "".join(self.open.get(cid, [])).strip())
            out.append(Comment(cid, author, text, self.comment_block.get(cid), anchor, date))
        return out


def _caption(el: etree._Element) -> str:
    """그림·표의 캡션(hp:caption 안 문단) 글. 없으면 빈 문자열."""
    found = next((x for x in el if _local(x.tag) == "caption"), None)
    return _paras_text(found, " ") if found is not None else ""


def _paras_text(el: etree._Element, sep: str = "\n") -> str:
    """el 안 문단들의 글자(각주·메모 내용용). 문단 사이는 sep, 문단 안 공백은 그대로."""
    out = []
    for p in _top_paras(el):
        bits: list[str] = []
        for node in p.iter():
            if _local(node.tag) == "t":
                bits.append(node.text or "")
                for child in node:
                    bits.append(_INSIDE.get(_local(child.tag), ""))
                    bits.append(child.tail or "")
        if text := "".join(bits).strip():
            out.append(text if sep == "\n" else " ".join(text.split()))
    return sep.join(out)


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except ValueError:
        return default


def _hwpx_header(root: etree._Element | None) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str, int]], Outline]:
    """header.xml → (스타일 id → (이름, 영문 이름), 문단 모양 id → (머리 종류 NONE|OUTLINE|NUMBER|BULLET, 번호 정의 id, 수준),
    개요 번호(번호 정의 id → 수준별 (시작, 모양, 형식 글)))."""
    styles: dict[str, tuple[str, str]] = {}
    heads: dict[str, tuple[str, str, int]] = {}
    numberings: dict[str, list[tuple[int, str, str]]] = {}
    for el in root.iter() if root is not None else ():
        name = _local(el.tag)
        if name == "style" and el.get("id") is not None:
            styles[el.get("id")] = (el.get("name") or "", el.get("engName") or "")
        elif name == "paraPr" and el.get("id") is not None:
            head = next((x for x in el.iter() if _local(x.tag) == "heading"), None)
            if head is not None:
                heads[el.get("id")] = ((head.get("type") or "NONE").upper(), head.get("idRef") or "", _int(head.get("level")))
        elif name == "numbering" and el.get("id") is not None:
            found = sorted((_int(h.get("level"), 1), _int(h.get("start"), 1), h.get("numFormat") or "DIGIT", h.text or "")
                           for h in el if _local(h.tag) == "paraHead")
            numberings[el.get("id")] = [(start, fmt, text) for _, start, fmt, text in found]
    return styles, heads, Outline(numberings)


def _hwpx_package(z: zipfile.ZipFile, names: set[str]) -> tuple[list[str], str | None]:
    """content.hpf(OPF)의 spine 차례 → 구역 파일들, 문서 정보의 제목. spine이 없으면 Contents/sectionN.xml 번호 차례."""
    sections: list[str] = []
    title = None
    if "Contents/content.hpf" in names:
        root = _xml(z, "Contents/content.hpf")
        hrefs = {}
        for el in root.iter():
            name = _local(el.tag)
            if name == "item" and el.get("id") and el.get("href"):
                hrefs[el.get("id")] = el.get("href")
            elif name == "title" and title is None:
                title = (el.text or "").strip() or None
        for el in root.iter():
            if _local(el.tag) == "itemref" and (href := hrefs.get(el.get("idref") or "")):
                for cand in (href, f"Contents/{href}"):
                    if cand in names and re.search(r"section\d+\.xml$", cand) and cand not in sections:
                        sections.append(cand)
                        break
    if not sections:
        found = [(int(m.group(1)), n) for n in names if (m := re.fullmatch(r"Contents/section(\d{1,6})\.xml", n))]
        sections = [n for _, n in sorted(found)]
    return sections, title


def read_hwpx(path: Path) -> Manuscript:
    with zipfile.ZipFile(path) as z:
        zipguard.check(z)  # 압축 폭탄은 풀기 전에 막는다(docx와 같다)
        names = set(z.namelist())
        if "META-INF/manifest.xml" in names and b"encrypt" in z.read("META-INF/manifest.xml").lower():
            raise ValueError(LOCKED)
        sections, title = _hwpx_package(z, names)
        if not sections:
            raise Unreadable("구역(section) 없음")
        walker = _HwpxWalker(*_hwpx_header(_xml(z, "Contents/header.xml") if "Contents/header.xml" in names else None))
        for name in sections:
            walker.section(_xml(z, name))
    return Manuscript(walker.blocks, walker.comments(), title, walker.figures, walker.tables, walker.equations, source="hwpx")


# ---- hwp 5.0 -------------------------------------------------------------------------------------------------
# 한글 문서 파일 형식 5.0 공개 문서. 레코드 머리 32비트: 태그 0~9, 수준 10~19, 크기 20~31(0xFFF면 다음 4바이트).

_SIGNATURE = b"HWP Document File"
_LOCK_FLAGS = 0x02 | 0x04 | 0x10 | 0x100 | 0x400  # FileHeader 속성: 암호 · 배포용 · DRM · 공인인증서 암호화 · 공인인증서 DRM
TAG_NUMBERING, TAG_PARA_SHAPE, TAG_STYLE = 23, 25, 42  # DocInfo
TAG_PARA_HEADER, TAG_PARA_TEXT, TAG_CTRL_HEADER, TAG_LIST_HEADER, TAG_TABLE, TAG_MEMO_LIST = 66, 67, 71, 72, 77, 93
_CHAR = {10: "\n", 24: "-", 30: " ", 31: " "}  # 한 글자짜리 제어 문자(0·13·25~29는 버린다)
_ONE = frozenset({0, 10, 13, *range(24, 32)})  # 그 밖(1~9·11·12·14~23)은 여덟 글자(16바이트)짜리 컨트롤
_EXTENDED = frozenset({1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23})  # 따로 CTRL_HEADER 레코드가 있는 컨트롤
RAW_MAX = 50_000_000  # 스트림 하나(압축된 채)의 상한


@dataclass
class _Rec:
    tag: int
    level: int
    data: bytes
    kids: list[_Rec] = field(default_factory=list)


def _u16(data: bytes, at: int) -> int:
    return int.from_bytes(data[at:at + 2], "little") if len(data) >= at + 2 else 0


def _records(raw: bytes) -> list[_Rec]:
    """레코드 열을 수준으로 나무를 만든다(레코드의 자식은 바로 뒤에 오는 수준이 더 깊은 레코드들)."""
    flat: list[_Rec] = []
    pos, n = 0, len(raw)
    while pos + 4 <= n:
        head = int.from_bytes(raw[pos:pos + 4], "little")
        tag, level, size = head & 0x3FF, (head >> 10) & 0x3FF, head >> 20
        pos += 4
        if size == 0xFFF:
            if pos + 4 > n:
                break
            size, pos = int.from_bytes(raw[pos:pos + 4], "little"), pos + 4
        if pos + size > n:
            break  # 잘린 레코드(뒤 군더더기)
        flat.append(_Rec(tag, level, raw[pos:pos + size]))
        pos += size
    root = _Rec(-1, -1, b"")
    stack = [root]
    for rec in flat:
        while len(stack) > 1 and stack[-1].level >= rec.level:
            stack.pop()
        stack[-1].kids.append(rec)
        stack.append(rec)
    return root.kids


def _stream(ole, entry: list[str], compressed: bool, budget: list[int]) -> bytes:  # noqa: ANN001
    """스트림 하나를 읽고, 압축이면 푼다(raw deflate). zipguard와 같은 규칙: 1MB를 넘으면 압축률 100:1, 파일 전체 200MB."""
    size = ole.get_size(entry)
    if size > RAW_MAX:
        raise zipguard.UnsafeDocument(f"{zipguard.REFUSED} 파일이 너무 큽니다.")
    raw = ole.openstream(entry).read()
    if not compressed:
        return raw
    d = zlib.decompressobj(-15)
    limit = max(zipguard.RATIO_FROM, zipguard.MAX_RATIO * size)
    out = bytearray()
    data = raw
    while data and not d.eof:
        out += d.decompress(data, 1_000_000)
        if len(out) > limit or len(out) > budget[0]:
            raise zipguard.UnsafeDocument(f"{zipguard.REFUSED} 압축을 풀면 너무 큽니다.")
        data = d.unconsumed_tail
    budget[0] -= len(out)
    return bytes(out)


def _numbering(data: bytes) -> list[tuple[int, str, str]]:
    """NUMBERING 레코드: 수준 7개마다 문단 머리 정보(속성 4 · 너비 보정 2 · 본문과의 거리 2 · 글자 모양 4) + 형식 글(WORD 길이 + WCHAR들),
    그 뒤 시작 번호(UINT16)와 수준별 시작 번호(UINT32 7개, 5.0.2.5부터). 번호 모양은 속성 bit 5~8."""
    levels: list[tuple[int, str]] = []
    pos = 0
    for _ in range(7):
        if pos + 14 > len(data):
            break
        prop, n = int.from_bytes(data[pos:pos + 4], "little"), _u16(data, pos + 12)
        text = data[pos + 14:pos + 14 + 2 * n].decode("utf-16-le", "replace")
        shape = (prop >> 5) & 0xF
        levels.append((shape, text))
        pos += 14 + 2 * n
    start = _u16(data, pos) or 1
    starts = [int.from_bytes(data[pos + 2 + 4 * k:pos + 6 + 4 * k], "little") for k in range(len(levels))
              ] if len(data) >= pos + 2 + 4 * len(levels) else []
    return [((starts[k] if k < len(starts) and starts[k] else start if k == 0 else 1),
             HWP_SHAPES[shape] if shape < len(HWP_SHAPES) else "DIGIT", text) for k, (shape, text) in enumerate(levels)]


def _style_names(data: bytes) -> tuple[str, str]:
    """STYLE 레코드: 이름(WORD 길이 + WCHAR들), 영문 이름(같은 꼴), 그 뒤 속성들."""
    n = _u16(data, 0)
    name = data[2:2 + 2 * n].decode("utf-16-le", "replace")
    at = 2 + 2 * n
    m = _u16(data, at)
    return name, data[at + 2:at + 2 + 2 * m].decode("utf-16-le", "replace")


class _HwpWalker:
    def __init__(self, styles: list[tuple[str, str]], shapes: list[int], outline: Outline):
        self.styles, self.shapes, self.outline = styles, shapes, outline
        self.outline_ref = "1"  # 구역 정의(secd)의 개요 번호 id(1부터). 없으면 첫 번호 정의
        self.blocks: list[Block] = []
        self.pending_tables: list[_Rec] = []
        self.pending_notes: list[str] = []
        self.figures = self.tables = self.equations = self.footnotes = self.memos = 0

    def section(self, recs: list[_Rec]) -> None:
        for rec in recs:
            if rec.tag == TAG_PARA_HEADER:
                self.paragraph(rec)
        self.memos += sum(1 for _ in _walk(recs) if _.tag == TAG_MEMO_LIST)

    def _level(self, header: bytes) -> tuple[str, int | None, bool]:
        shape_id, style_id = _u16(header, 8), header[10] if len(header) > 10 else 0
        name, eng = self.styles[style_id] if style_id < len(self.styles) else ("", "")
        style = (eng or name).lower()
        for s in (name, eng):
            if m := HEADING_STYLE.search(s):
                return style, min(int(m.group(1)), MAX_LEVEL), False
        prop = self.shapes[shape_id] if shape_id < len(self.shapes) else 0
        kind, level = (prop >> 23) & 0x3, (prop >> 25) & 0x7  # 문단 머리: 0 없음 · 1 개요 · 2 번호 · 3 글머리표
        if kind == 1:
            return style, min(level + 1, MAX_LEVEL), False
        return style, None, kind in (2, 3)

    def paragraph(self, rec: _Rec) -> None:
        index = len(self.blocks)
        parts: list[str] = []
        self._text(rec, parts, in_cell=False)
        style, level, is_list = self._level(rec.data)
        text = "".join(parts).strip()
        shape_id = _u16(rec.data, 8)
        prop = self.shapes[shape_id] if shape_id < len(self.shapes) else 0
        if (prop >> 23) & 0x3 == 1:  # 개요 문단: 화면에 보이는 번호(글자로 저장되지 않는다)를 앞에
            text = with_prefix(self.outline.prefix(self.outline_ref, (prop >> 25) & 0x7), text)
        self.blocks.append(Block(index, "para", text, style, level, is_list))
        tables, self.pending_tables = self.pending_tables, []
        for ctrl in tables:
            self.table(ctrl)
        notes, self.pending_notes = self.pending_notes, []
        for note in notes:
            self.blocks.append(Block(len(self.blocks), "para", note))

    def _text(self, para: _Rec, parts: list[str], *, in_cell: bool) -> None:
        """PARA_TEXT(UTF-16LE) → 글자. 확장 컨트롤(표·그림·수식·각주)은 문단의 CTRL_HEADER와 차례로 맞춘다(컨트롤 id로)."""
        data = next((k.data for k in para.kids if k.tag == TAG_PARA_TEXT), b"")
        ctrls = [k for k in para.kids if k.tag == TAG_CTRL_HEADER]
        taken = 0
        pos, start, end = 0, 0, len(data) & ~1
        while pos < end:
            code = data[pos] if data[pos + 1] == 0 else 0xFFFF
            if code >= 32:
                pos += 2
                continue
            if start < pos:
                parts.append(data[start:pos].decode("utf-16-le", "replace"))
            if code in _ONE:
                parts.append(_CHAR.get(code, ""))
                pos += 2
            else:
                ctrl_id = data[pos + 2:pos + 6][::-1].decode("latin-1")
                if code == 9:
                    parts.append("\t")
                elif code in _EXTENDED:
                    ctrl = None
                    for j in range(taken, len(ctrls)):
                        if ctrls[j].data[:4][::-1].decode("latin-1") == ctrl_id:
                            ctrl, taken = ctrls[j], j + 1
                            break
                    self._control(ctrl_id, ctrl, parts, in_cell)
                pos += 16
            start = pos
        if start < end:
            parts.append(data[start:end].decode("utf-16-le", "replace"))

    def _control(self, ctrl_id: str, ctrl: _Rec | None, parts: list[str], in_cell: bool) -> None:
        if ctrl_id == "secd" and ctrl is not None:  # 구역 정의: id 4 · 속성 4 · 단 간격 2 · 줄맞춤 2+2 · 탭 4 · 번호 문단 모양 id 2
            if ref := _u16(ctrl.data, 18):
                self.outline_ref = str(ref)
        elif ctrl_id == "gso ":  # 그리기 개체(그림·도형·글상자)
            self.figures += 1
            parts.append(f"[그림 {self.figures}]")
        elif ctrl_id == "eqed":
            self.equations += 1
            parts.append("[수식]")
        elif ctrl_id == "tbl " and ctrl is not None:
            if in_cell:  # 표 칸 안의 표는 그 칸의 글로
                for _, paras in _cells(ctrl):
                    for p in paras:
                        self._text(p, parts, in_cell=True)
                        parts.append(" ")
            else:
                self.pending_tables.append(ctrl)
        elif ctrl_id in ("fn  ", "en  ") and ctrl is not None:
            self.footnotes += 1
            texts = []
            for _, paras in _cells(ctrl):
                for p in paras:
                    bits: list[str] = []
                    self._text(p, bits, in_cell=True)
                    if text := " ".join("".join(bits).split()):
                        texts.append(text)
            parts.append(f"[^{self.footnotes}]")
            self.pending_notes.append(f"[^{self.footnotes}]: {' '.join(texts) or '(빈 각주)'}")
        # 머리말·꼬리말(head·foot)·숨은 설명(tcmt)·쪽 번호·책갈피·필드는 싣지 않는다

    def table(self, ctrl: _Rec) -> None:
        self.tables += 1
        index = len(self.blocks)
        info = next((k.data for k in ctrl.kids if k.tag == TAG_TABLE), b"")
        rows_n, cols_n = _u16(info, 4), _u16(info, 6)
        cells = _cells(ctrl)
        places = _cell_places([head for head, _ in cells], rows_n, cols_n)
        grid: dict[tuple[int, int], str] = {}
        for at, (_, paras) in zip(places, cells, strict=True):
            texts = []
            for p in paras:
                bits: list[str] = []
                self._text(p, bits, in_cell=True)
                if text := " ".join("".join(bits).split()):
                    texts.append(text)
            grid[at] = " ".join(texts)
        rows = max((r for r, _ in grid), default=-1) + 1
        cols = max((c for _, c in grid), default=-1) + 1
        table = [[grid.get((r, c), "") for c in range(cols)] for r in range(rows)]
        text = markdown_table(table) if any(cell for row in table for cell in row) else f"[표 {self.tables}]"
        self.blocks.append(Block(index, "table", text))


def _walk(recs: list[_Rec]) -> Iterator[_Rec]:
    for rec in recs:
        yield rec
        yield from _walk(rec.kids)


def _cells(ctrl: _Rec) -> list[tuple[bytes, list[_Rec]]]:
    """컨트롤(표·각주) 안의 문단 목록들: LIST_HEADER 하나 + 그 뒤의 문단들(같은 수준). 문단이 LIST_HEADER의 자식이어도 받는다."""
    out: list[tuple[bytes, list[_Rec]]] = []
    for k in ctrl.kids:
        if k.tag == TAG_LIST_HEADER:
            out.append((k.data, [p for p in k.kids if p.tag == TAG_PARA_HEADER]))
        elif k.tag == TAG_PARA_HEADER:
            if not out:
                out.append((b"", []))
            out[-1][1].append(k)
    return out


def _cell_places(heads: list[bytes], rows_n: int, cols_n: int) -> list[tuple[int, int]]:
    """칸마다 (행, 열). 셀 속성의 주소(열·행 UINT16)는 문단 리스트 머리 뒤에 온다. 머리를 8바이트로 읽는 구현(pyhwp)과
    6바이트로 적은 공개 문서가 달라, 모든 칸이 표 크기 안에서 겹치지 않는 쪽을 쓴다. 둘 다 아니면 차례대로 채운다."""
    for at in (8, 6):
        places = [(_u16(h, at + 2), _u16(h, at)) for h in heads]
        if (all(len(h) >= at + 4 for h in heads) and len(set(places)) == len(places)
                and all(r < max(rows_n, 1) and c < max(cols_n, 1) for r, c in places)):
            return places
    width = max(cols_n, 1)
    return [(n // width, n % width) for n in range(len(heads))]


def read_hwp(path: Path) -> Manuscript:
    import olefile  # noqa: PLC0415

    with path.open("rb") as f:
        if f.read(len(_SIGNATURE)) == _SIGNATURE:  # 한글 97 이전(HWP 3.x)은 OLE 파일이 아니다
            raise ValueError(OLD_HWP)
    if not olefile.isOleFile(str(path)):
        raise Unreadable("OLE 아님")
    budget = [zipguard.MAX_UNZIPPED]
    try:
        ole = olefile.OleFileIO(str(path))
    except OSError as e:
        raise Unreadable("OLE 열기 실패") from e
    with ole:
        header = ole.openstream("FileHeader").read(256) if ole.exists("FileHeader") else b""
        if not header.startswith(_SIGNATURE) or len(header) < 40:
            raise Unreadable("hwp 머리 없음")
        flags = int.from_bytes(header[36:40], "little")
        if flags & _LOCK_FLAGS or ole.exists("ViewText"):  # 배포용 문서는 본문이 ViewText에 암호화되어 있다
            raise ValueError(LOCKED)
        compressed = bool(flags & 0x01)
        styles: list[tuple[str, str]] = []
        shapes: list[int] = []
        numberings: dict[str, list[tuple[int, str, str]]] = {}
        if ole.exists("DocInfo"):
            for rec in _walk(_records(_stream(ole, ["DocInfo"], compressed, budget))):
                if rec.tag == TAG_STYLE:
                    styles.append(_style_names(rec.data))
                elif rec.tag == TAG_PARA_SHAPE:
                    shapes.append(int.from_bytes(rec.data[:4], "little") if len(rec.data) >= 4 else 0)
                elif rec.tag == TAG_NUMBERING:
                    numberings[str(len(numberings) + 1)] = _numbering(rec.data)
        sections = sorted((int(m.group(1)), e) for e in ole.listdir()
                          if len(e) == 2 and e[0] == "BodyText" and (m := re.fullmatch(r"Section(\d{1,6})", e[1])))
        if not sections:
            raise Unreadable("본문 구역 없음")
        walker = _HwpWalker(styles, shapes, Outline(numberings))
        for _, entry in sections:
            walker.section(_records(_stream(ole, entry, compressed, budget)))
        title = None
        if ole.exists("\x05HwpSummaryInformation"):
            try:
                found = ole.getproperties("\x05HwpSummaryInformation").get(2)  # PIDSI_TITLE. 바이트 제목은 쓰지 않는다(파일 이름이 대신)
                title = (" ".join(found.split()) or None) if isinstance(found, str) else None
            except Exception:  # noqa: BLE001 - 문서 정보는 없어도 된다
                title = None
    notes = [f"hwp 메모 {walker.memos}개는 확인 요청으로 가져오지 않음(hwpx로 저장해 올리면 가져온다)"] if walker.memos else []
    return Manuscript(walker.blocks, [], title, walker.figures, walker.tables, walker.equations, source="hwp", notes=notes)


def read_hangul(path: Path) -> Manuscript:
    """확장자로 hwpx·hwp를 고른다."""
    return read_hwpx(path) if path.suffix.lower() == ".hwpx" else read_hwp(path)
