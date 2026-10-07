"""문서 책·리포트를 웹에 보이는 작은 markdown 변환기(#94). 템플릿 엔진·외부 라이브러리 없이(#56).

다루는 것: 제목(#·##·###), 문단, 글머리 목록(-), 번호 목록(1.), 표(| … |), 굵게(**…**), 기울임(*…*), 가로줄(---), 인용(>).
글은 먼저 이스케이프하고 그 위에 위 표시만 태그로 바꾼다(문헌 제목의 <, & 같은 글자가 태그가 되지 않게).
"""

from __future__ import annotations

import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = _BOLD.sub(r"<b>\1</b>", out)
    return _ITALIC.sub(r"<i>\1</i>", out)


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], [r for r in cells[1:] if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
    numeric = [i for i, c in enumerate(rows[1].strip().strip("|").split("|")) if c.strip().endswith(":")] if len(rows) > 1 else []
    num = ' class="num"'
    th = "".join(f"<th{num if i in numeric else ''}>{inline(c)}</th>" for i, c in enumerate(head))
    trs = "".join("<tr>" + "".join(f"<td{num if i in numeric else ''}>{inline(c)}</td>" for i, c in enumerate(r)) + "</tr>"
                  for r in body)
    return f"<table><tr>{th}</tr>{trs}</table>"


def to_html(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if m := re.match(r"(#{1,3})\s+(.*)", stripped):
            level = len(m.group(1)) + 1  # 화면의 h1은 쪽 제목이라 문서 안은 h2부터
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
        elif re.fullmatch(r"-{3,}", stripped):
            out.append("<hr>")
            i += 1
        elif stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
        elif re.match(r"[-*]\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>")
        elif re.match(r"\d+\.\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ol>")
        elif stripped.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + "<br>".join(inline(q) for q in quote) + "</blockquote>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,3}\s|[-*]\s|\d+\.\s|\||>|-{3,}$)", lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{'<br>'.join(inline(p) for p in para)}</p>")
    return "".join(out)
