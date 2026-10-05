"""최신본 docx 시험 임포트(2026-10-06)에서 나온 보완: 표(#69). 작은 합성 docx로 확인한다."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from magus.book.importer import import_manuscript
from magus.melchior.check import check_chapter
from magus.store import LocalStore

BIB = [
    "Clack, J. A. (2012). Gaining ground: The origin and evolution of tetrapods. Indiana University Press.",
    "Daeschler, E. B., Shubin, N. H., & Jenkins, F. A. (2006). A Devonian tetrapod-like fish. Nature, 440, 757–763.",
]


class Manuscript:
    """시험용 원고. pieces는 문자열 또는 (문자열, 코멘트 본문[, 작성자[, 날짜]])."""

    def __init__(self) -> None:
        self.doc = Document()

    def heading(self, text: str, level: int = 1) -> Manuscript:
        self.doc.add_paragraph(text, style=f"Heading {level}")
        return self

    def para(self, *pieces) -> Manuscript:
        p = self.doc.add_paragraph()
        for piece in pieces:
            if isinstance(piece, tuple):
                self.comment(p.add_run(piece[0]), *piece[1:])
            else:
                p.add_run(piece)
        return self

    def comment(self, runs, text: str, author: str = "편집자", date: str = "2026-10-02T09:00:00Z") -> None:
        c = self.doc.add_comment(runs, text=text, author=author, initials=author[:2])
        c._comment_elm.set(qn("w:date"), date)  # python-docx는 지금 시각을 넣는다. 판 사이 지문 시험을 위해 고정한다

    def table(self, rows: list[list[str]]):
        table = self.doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                table.cell(r, c).text = text
        return table

    def bibliography(self, lines: list[str] = BIB) -> Manuscript:
        self.heading("참고문헌")
        for line in lines:
            self.doc.add_paragraph(line)
        return self

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(path))
        return path


def test_tables_are_markdown_with_citations_and_comments(store: LocalStore, tmp_path: Path):
    m = Manuscript().heading("제1장 물가")
    m.para("물고기는 바닥을 짚었다.")
    table = m.table([["지표", "값", "출처"], ["산소", "낮음", "Clack(2012)"], ["합친 칸", "", "a|b"]])
    table.cell(2, 0).merge(table.cell(2, 1))  # gridSpan=2
    m.comment(table.cell(1, 1).paragraphs[0].runs, "수치 확인 필요")
    m.para("다음 문단(Daeschler, Shubin & Jenkins, 2006).")
    import_manuscript(store, "alice", m.bibliography().save(tmp_path / "t.docx"), project_id="b")

    body = store.read_chapter("alice", "b", 1).content
    assert "| 지표 | 값 | 출처 |\n|---|---|---|\n| 산소 | 낮음 | Clack(2012) |\n| 합친 칸 |  | a\\|b |" in body
    assert "[표 1]" not in body
    # 표 안의 인용도 인용 게이트가 센다(최신본: 표 37개, 17,396자가 빠져 있었다)
    assert {g.key for g in check_chapter(store, "alice", "b", 1).groups} == {"clack2012", "daeschler2006"}
    [issue] = store.list_issues("alice", "b")
    assert issue.chapter_number == 1 and "— 원문: “낮음”" in issue.text


def test_empty_table_keeps_placeholder(store: LocalStore, tmp_path: Path):
    m = Manuscript().heading("제1장 물가")
    m.para("본문.")
    m.table([["", ""], ["", ""]])
    import_manuscript(store, "alice", m.bibliography().save(tmp_path / "e.docx"), project_id="b")
    assert "[표 1]" in store.read_chapter("alice", "b", 1).content
