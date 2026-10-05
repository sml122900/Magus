"""다시 올리기 — 같은 책의 새 판(#76). 합성 원고 두 판(E1 → E2)으로 확인한다.

E1에서 E2로: 1장 그대로(새 코멘트만), 2장 본문 바뀜(코멘트 하나는 남고 하나는 문장째 지워짐), 3장 그대로(Magus에서 닫은 코멘트가
원고에 남음), 4장 원고는 그대로인데 Magus에서 고쳤고 코멘트가 지워짐, 5장 빠짐, 6장 새로. 참고문헌은 같은 Hsieh 2019 두 편의
순서가 바뀐다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mcp import Client
from test_docx_features import Manuscript

from magus.book.importer import import_manuscript
from magus.book.outline import build_outline
from magus.book.reupload import reupload_manuscript
from magus.melchior.refs import add_ref
from magus.server import build_server
from magus.store import Idea, LocalStore, Passage

U, P = "alice", "b"
D1, D2 = "2026-10-02T09:00:00Z", "2026-10-04T09:00:00Z"
TALENT = "Hsieh, C.-T., Hurst, E., Jones, C. I., & Klenow, P. J. (2019). The allocation of talent and U.S. economic growth. Econometrica."
HOUSING = "Hsieh, C.-T., & Moretti, E. (2019). Housing constraints and spatial misallocation. AEJ: Macroeconomics."
CLACK = "Clack, J. A. (2012). Gaining ground: The origin and evolution of tetrapods. Indiana University Press."


def edition(path: Path, n: int) -> Path:
    m = Manuscript()
    m.doc.core_properties.title = "가상 책 — " + ("첫 부제" if n == 1 else "바뀐 부제")
    m.para("제1부 물").heading("제1장 물가")
    m.para(("물고기는 바닥을 짚었다(Clack, 2012).", "인용 확인 필요", "Claude", D1))
    if n == 1:
        m.para("같은 문단.")
    else:
        m.para(("같은 문단.", "[점검·사실] 새로 단 확인 요청", "Claude", D2))  # 본문은 같고 코멘트만 새로
    m.heading("제2장 숨")
    m.para(("숨은 비용이었다", "[점검·수치] 산소 농도", "Claude", D1), "." if n == 1 else ". 새 문장이 붙었다.")
    if n == 1:
        m.para(("둘째 문단은 곧 지워진다.", "[점검·통계] 수치 출처", "Claude", D1))
    m.heading("제3장 손").para(("손가락은 물풀을 헤쳤다.", "문단 줄이기", "편집자", D1))
    m.heading("제4장 귀환")
    m.para(("고래는 돌아갔다.", "[점검·사실] 고래 시기", "Claude", D1) if n == 1 else "고래는 돌아갔다.")
    if n == 1:
        m.heading("제5장 끝").para("끝.")
    else:
        m.heading("제6장 새 장").para("새로 쓴 장.")
    bib = [CLACK, TALENT] if n == 1 else [CLACK, HOUSING, TALENT]
    return m.bibliography(bib).save(path)


def _files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def e1(store: LocalStore, tmp_path: Path):
    """E1을 임포트하고, 저자가 Magus를 쓴 흔적을 남긴다: 결정, 직접 남긴 미해결, 생각, 확인한 문헌, 닫은 미해결, Magus에서 고친 장."""
    import_manuscript(store, U, edition(tmp_path / "e1.docx", 1), project_id=P)
    store.add_decision(U, P, "제목은 그대로 둔다")
    store.add_issue(U, P, "3장 순서 다시 보기", origin="user", chapter_number=3)
    store.add_ideas(U, [Idea(id="20261003000000000-aaaaaa", text="물가는 궁지다", kind="thought", author="me")])
    add_ref(store, U, {"key": "clack2012"}, [Passage("tetrapods came ashore", "1장 근거")])
    by_text = {i.text.split("\n")[0]: i for i in store.list_issues(U, P)}
    store.close_issue(U, P, by_text["문단 줄이기"].id, "Word에서 고치기로")
    store.write_chapter(U, P, 4, "고래는 돌아갔다. Magus에서 덧붙인 문장.", "Magus에서 고침")
    return by_text


def test_reupload_replaces_only_changed_chapters_and_keeps_history(store: LocalStore, tmp_path: Path, e1):
    root = store.root / "users" / U
    before = {k: v for k, v in _files(root).items() if k.startswith("shelf/")}
    decisions = (root / "projects" / P / "decisions.md").read_bytes()
    direct = [i for i in store.list_issues(U, P, None) if i.origin != "import_comment"]

    report = reupload_manuscript(store, U, edition(tmp_path / "e2.docx", 2), P)

    # 장: 바뀐 장만 다시 쓴다. 그대로인 장은 버전이 오르지 않고 판 번호만 적힌다
    assert (report.edition, report.previous, report.overlap) == (2, 1, 0.8)
    assert [c.display for c in report.changed] == ["제2장", "제4장"] and report.unchanged == 2
    assert [c.display for c in report.added] == ["제6장"] and [c.display for c in report.removed] == ["제5장"]
    assert report.overwritten_magus == ["제4장"]  # Magus에서 고친 본문이 원고 판으로 덮였다(이전본은 versions/)
    chapters = {c.number: c for c in store.list_chapters(U, P)}
    assert sorted(chapters) == [1, 2, 3, 4, 6]
    assert (chapters[1].version, chapters[1].edition) == (1, 2)
    assert (chapters[2].version, chapters[2].edition, chapters[2].last_note) == (2, 2, "판 E2 업로드: e2.docx")
    assert chapters[4].version == 3 and store.read_chapter(U, P, 4).content == "고래는 돌아갔다."
    assert (root / "projects" / P / "removed" / "ch-05-E1" / "ch-05.md").exists()
    assert (root / "projects" / P / "original" / "E2-e2.docx").exists()

    # 미해결: 같은 코멘트는 다시 넣지 않는다. 사라진 것은 표시만 하고 닫지 않는다
    issues = {i.text.split("\n")[0]: i for i in store.list_issues(U, P, None)}
    assert len(issues) == 7  # E1 코멘트 5 + 직접 1 + 새 코멘트 1
    assert (report.comments_total, report.issues_kept, report.issues_new) == (4, 3, 1)  # E2의 코멘트 4건: 이어진 3 + 새 1
    assert issues["인용 확인 필요"].id == e1["인용 확인 필요"].id and issues["인용 확인 필요"].stale is None
    assert issues["[점검·수치] 산소 농도"].stale is None and issues["[점검·수치] 산소 농도"].chapter_number == 2
    assert issues["문단 줄이기"].status == "closed" and report.closed_but_in_file == 1  # 닫힌 채 둔다
    assert (issues["[점검·사실] 고래 시기"].status, issues["[점검·사실] 고래 시기"].stale) == ("open", "comment_removed")
    assert (issues["[점검·통계] 수치 출처"].stale, issues["[점검·통계] 수치 출처"].stale_edition) == ("anchor_missing", 2)
    new = issues["[점검·사실] 새로 단 확인 요청"]
    assert (new.chapter_number, new.kind, new.by_ai, new.id) == (1, "fact", True, 7)
    assert dict(report.stale) == {"comment_removed": 1, "anchor_missing": 1}

    # 결정·직접 남긴 미해결·책장은 그대로(해시). 참고문헌은 새 문헌만 더한다
    assert (root / "projects" / P / "decisions.md").read_bytes() == decisions
    assert [i for i in store.list_issues(U, P, None) if i.origin != "import_comment"] == direct
    after = _files(root)
    assert {k: after[k] for k in before} == before
    assert [i.text for i in store.list_ideas(U)] == ["물가는 궁지다"]
    assert store.get_ref(U, "clack2012").status == "verified"
    # key 안정화: 순서가 바뀌어도 talent는 hsieh2019, 새 housing이 hsieh2019-2
    assert store.get_ref(U, "hsieh2019").bib["title"].startswith("The allocation of talent")
    assert store.get_ref(U, "hsieh2019-2").bib["title"].startswith("Housing constraints")
    assert report.bib.created == ["hsieh2019-2"]

    # 제목은 원고를 따른다. 판 기록은 project.json에
    project = store.get_project(U, P)
    assert (project.title, project.subtitle) == ("가상 책", "바뀐 부제") and "첫 부제" in report.titles_changed
    editions = json.loads((root / "projects" / P / "project.json").read_text(encoding="utf-8"))["editions"]
    assert [(e["number"], e["file"], e.get("changed"), e.get("removed")) for e in editions] == [(1, "e1.docx", 5, None), (2, "e2.docx", 3, 1)]
    text = report.full()
    assert "장: 본문 바뀜 2 · 그대로 2 · 새 장 1(제6장) · 빠진 장 1(제5장, removed/에 보관)" in text
    assert "해결됐을 수 있음 2(원고에서 코멘트가 지워짐 1 · 걸린 문장이 원고에 없음 1) — 닫지 않았다" in text

    # 인덱스는 파일에서 다시 만들어도 같다
    snapshot = (store.list_chapters(U, P), store.list_issues(U, P, None), store.list_editions(U, P))
    store.reindex()
    assert (store.list_chapters(U, P), store.list_issues(U, P, None), store.list_editions(U, P)) == snapshot


def test_outline_shows_edition_and_asks_for_latest_upload(store: LocalStore, tmp_path: Path, e1):
    outline = build_outline(store, U, P).splitlines()
    assert outline[3].startswith("판 E1 · 마지막 업로드 ") and outline[3].endswith("(e1.docx) · 그 뒤 Magus에서 고친 장 1")
    reupload_manuscript(store, U, edition(tmp_path / "e2.docx", 2), P)
    text = build_outline(store, U, P)
    assert "(e2.docx) · 그 뒤 Magus에서 고친 장 0" in text and "지남" not in text
    assert "- 그중 해결됐을 수 있음 2건(새 판에서 코멘트나 걸린 문장이 사라짐)" in text
    later = build_outline(store, U, P, now=datetime.now(UTC) + timedelta(days=8))
    assert "업로드 뒤 8일 지남. 그사이 저자가 Word에서 고쳤다면, 최신본을 받은함에 올려 새 판으로 올리도록" in later


def test_same_file_again_changes_nothing(store: LocalStore, tmp_path: Path, e1):
    reupload_manuscript(store, U, edition(tmp_path / "e2.docx", 2), P)
    issues = store.list_issues(U, P, None)
    again = reupload_manuscript(store, U, edition(tmp_path / "e3.docx", 2), P)
    assert (again.edition, len(again.changed), again.unchanged, again.issues_new, again.added, again.removed) == (3, 0, 5, 0, [], [])
    assert store.list_issues(U, P, None) == issues  # 표시도 그대로(언제 그렇게 됐는지 stale_edition 2 유지)


def test_different_book_needs_force(store: LocalStore, tmp_path: Path, e1):
    other = Manuscript().heading("제1장 전혀 다른").para("글.").heading("제2장 책").para("글.").bibliography().save(tmp_path / "x.docx")
    with pytest.raises(ValueError, match="장 제목이 기존 판.*0%만 겹친다"):
        reupload_manuscript(store, U, other, P)
    assert reupload_manuscript(store, U, other, P, force=True).edition == 2


def test_project_imported_before_editions_and_without_fingerprints(store: LocalStore, tmp_path: Path, e1):
    """판 기록·지문이 생기기 전 임포트(서버의 default 같은 것): 그 임포트를 E1로 적고, 미해결은 코멘트 본문으로 잇는다."""
    pdir = store.root / "users" / U / "projects" / P
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    del data["editions"]
    (pdir / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    issues_md = (pdir / "issues.md").read_text(encoding="utf-8")
    (pdir / "issues.md").write_text("\n".join(x for x in issues_md.splitlines() if not x.startswith(("- comment_fp:", "- author", "- comment_date:"))), encoding="utf-8")
    store.reindex()
    assert "판 기록 없음(다시 올리기 기능 전 임포트)" in build_outline(store, U, P)

    report = reupload_manuscript(store, U, edition(tmp_path / "e2.docx", 2), P)
    assert (report.previous, report.edition, report.issues_kept, report.issues_new) == (1, 2, 3, 1)
    assert [(e.number, e.file, e.legacy) for e in store.list_editions(U, P)] == [(1, "e1.docx", True), (2, "e2.docx", False)]
    kept = [i for i in store.list_issues(U, P, None) if i.text.startswith("인용 확인 필요")][0]
    assert (kept.author, kept.author_kind) == ("Claude", "ai") and kept.comment_fp  # 잇고 나서 지문·작성자를 채운다


@pytest.mark.anyio
async def test_book_import_new_edition_tool(settings, store: LocalStore, tmp_path: Path):
    import_manuscript(store, settings.user_id, edition(tmp_path / "e1.docx", 1), project_id=P)
    store.put_inbox(settings.user_id, "e2.docx", edition(tmp_path / "e2.docx", 2).read_bytes())
    async with Client(build_server(settings, store)) as client:
        refused = await client.call_tool("book_import", {"path": "e2.docx", "project_id": P})
        done = (await client.call_tool("book_import", {"path": "e2.docx", "project_id": P, "new_edition": True})).content[0].text
        stale = (await client.call_tool("book_issues", {"project_id": P, "possibly_resolved": True})).content[0].text
    assert refused.is_error and "new_edition=true" in refused.content[0].text
    assert done.startswith("## 새 판 E2 — 가상 책 (b)") and "### 바뀐 장" in done
    assert stale.startswith("미해결 2건 (status=open, 해결됐을 수 있음만)")
    assert "해결됐을 수 있음(원고에서 코멘트가 지워짐, E2)" in stale and "해결됐을 수 있음(걸린 문장이 원고에 없음, E2)" in stale


def test_pdf_comments_without_author_are_linked_by_text(store: LocalStore, tmp_path: Path, e1):
    """PDF로 임포트한 미해결은 작성자·날짜 없이 만든 지문이라 docx 판과 맞지 않는다. 코멘트 본문으로 잇는다(10/02 PDF → 10/05 docx)."""
    pdir = store.root / "users" / U / "projects" / P
    lines = (pdir / "issues.md").read_text(encoding="utf-8").splitlines()
    pdf_like = ["- comment_fp: 0000000000000000" if x.startswith("- comment_fp:") else x
                for x in lines if not x.startswith(("- author", "- comment_date:"))]
    (pdir / "issues.md").write_text("\n".join(pdf_like), encoding="utf-8")
    store.reindex()
    report = reupload_manuscript(store, U, edition(tmp_path / "e2.docx", 2), P)
    assert (report.issues_kept, report.issues_new, dict(report.stale)) == (3, 1, {"comment_removed": 1, "anchor_missing": 1})
