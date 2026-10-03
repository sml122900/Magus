"""실원고 보정 라운드에서 확인한 모양들: 음역 추정 연결, 고유 문헌 수 집계, 대화 형식 변형."""

from __future__ import annotations

from magus.casper.conversation import split_conversation
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import check_text, link_citation_issues
from magus.melchior.translit import best_match, score
from magus.store import LocalStore


def test_transliteration_scores():
    for hangul, latin in [("케인스", "Keynes"), ("모리스", "Morris"), ("넌", "Nunn"), ("마셜", "Marshall"),
                          ("베넷", "Bennett"), ("후닝", "Huning"), ("볼프", "Wolf"), ("첸", "Qian"), ("김성은", "Kim"),
                          ("애쓰모글루", "Acemoglu"), ("크레머", "Kremer")]:
        assert score(hangul, latin) >= 0.8, (hangul, latin)
    assert score("케인스", "Kremer") < 0.5
    # 동점이면 고르지 않는다
    assert best_match("모리스", [("morris2010", "Morris"), ("marshall2010", "Marshall")]) == "morris2010"
    assert best_match("셰", [("xie2019", "Xie"), ("seo2019", "Seo")]) is None


def test_check_counts_unique_refs_and_locates_paragraphs(store: LocalStore):
    import_bibliography(
        store, "alice",
        "Keynes, J. M. (1930). Economic possibilities for our grandchildren. Nation.\n"
        "Clack, J. A. (2012). Gaining ground. Press.\n"
        "Kremer, M. (1993). Population growth and technological change. QJE.",
    )
    text = "케인스(1930)는 말했다. (Clack, 2012)\n\n다시 Clack(2012). 그리고 (Nobody, 2001).\n\n마닐라(1571)는 항구였다."
    result = check_text(store, "alice", text)
    groups = {g.key: g for g in result.groups}
    assert groups["keynes1930"].status == "unverified" and groups["keynes1930"].matched_by == "음역 추정"
    assert groups["clack2012"].count == 2 and groups["clack2012"].as_dict()["paragraphs"] == [1, 2]
    assert groups["nobody2001"].status == "unknown"
    assert groups["마닐라1571"].status == "uncertain"  # 한글 표기인데 refs와 못 이음 → 따로
    assert result.unchecked_count == 3  # 고유 문헌 수(keynes, clack, nobody). uncertain은 세지 않는다
    assert sum(g.count for g in result.groups) == 5


def test_hangul_issue_ref_key_links_by_transliteration(store: LocalStore):
    project = store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", project.id, 1, "본문", "x")
    store.add_issue("alice", project.id, "인용 확인 필요: 마셜(2015)", origin="import_comment", kind="citation", ref_key="마셜2015")
    import_bibliography(store, "alice", "Marshall, T. (2015). Prisoners of geography. Elliott & Thompson.")
    assert link_citation_issues(store, "alice") == 1
    assert store.list_issues("alice", project.id)[0].ref_id == "marshall2015"


def test_conversation_heading_and_parenthetical_markers():
    heading_style = "# 문의\n\n---\n\n## 질문 1\n\n> 몇 쪽인가?\n\n### 답변\n\n약 636쪽입니다.\n\n> **보충:** 648쪽 판도 있다.\n\n---\n\n## 질문 2\n\n> 판매가는?\n\n### 답변\n\n24,120원입니다."
    s = split_conversation(heading_style)
    assert (s.me, s.ai, s.failures) == (2, 2, [])
    assert s.utterances[0].text == "몇 쪽인가?" and "보충" in s.utterances[1].text
    variant = "**질문:** 수준이 낮지?\n\n**답변(수정된 평가):**\n\n교양 있는 질문이었습니다."
    v = split_conversation(variant)
    assert (v.me, v.ai) == (1, 1) and v.utterances[1].text == "교양 있는 질문이었습니다."


def test_same_author_year_disambiguated_by_coauthors(store: LocalStore):
    report = import_bibliography(
        store, "alice",
        "Acemoglu, D., & Zilibotti, F. (2001). Productivity differences. QJE.\n"
        "Acemoglu, D., Johnson, S., & Robinson, J. A. (2001). The colonial origins. AER.",
    )
    assert report.created == ["acemoglu2001", "acemoglu2001-2"]
    groups = {g.key: g for g in check_text(store, "alice", "(Acemoglu, Johnson & Robinson, 2001) (Acemoglu & Zilibotti, 2001) Acemoglu(2001)").groups}
    assert groups["acemoglu2001-2"].count == 1  # 공저자로 가림
    assert groups["acemoglu2001"].count == 2  # 공저자가 맞는 것 + 가릴 수 없는 것(첫 항목으로)


def test_year_range_and_ab_ambiguity(store: LocalStore):
    from magus.melchior.citations import find_citations

    assert [c.key for c in find_citations("(Toynbee, 1934–1961)")] == ["toynbee1934"]
    assert find_citations("한국(1965~1995) 0.16, 일본(1955~1973년)") == []  # 서술형 기간은 인용이 아니다
    import_bibliography(
        store, "alice",
        "Keynes, J. M. (1930a). A treatise on money. Macmillan.\nKeynes, J. M. (1930b). Economic possibilities. Nation.",
    )
    result = check_text(store, "alice", "(Keynes, 1930b) Keynes(1930) 케인스(1930)")
    groups = {g.key: g for g in result.groups}
    assert groups["keynes1930b"].matched_by == ""
    # 접미사 없는 인용은 어느 쪽에도 잇지 않는다(사용자 결정 #31). 후보 둘을 함께 보이고, 한 문헌으로 센다
    ambiguous = groups["keynes1930a/b"]
    assert (ambiguous.status, ambiguous.count, ambiguous.title) == ("unverified", 2, "")
    assert [k for k, _ in ambiguous.candidates] == ["keynes1930a", "keynes1930b"]
    assert "keynes1930a" not in groups and result.unchecked_count == 2
    assert ambiguous.as_dict()["candidates"][0] == {"key": "keynes1930a", "title": "A treatise on money"}
    assert {g.matched_by for g in check_text(store, "alice", "Keynes(1930)").groups} == {"연도 a/b 모호"}
    assert {g.matched_by for g in check_text(store, "alice", "케인스(1930)").groups} == {"음역 추정·연도 a/b 모호"}
    # 사용자가 확정하면(magus alias) 그 문헌으로 바로 잇는다
    from magus.melchior.refs import add_alias

    add_alias(store, "alice", "keynes1930b", "케인스(1930)")
    assert {g.key: g.matched_by for g in check_text(store, "alice", "케인스(1930)").groups} == {"keynes1930b": "alias"}


def test_cite_report(store: LocalStore):
    from magus.melchior.report import build_cite_report

    project = store.create_project("alice", "책", project_id="b")
    import_bibliography(
        store, "alice",
        "Clack, J. A. (2012). Gaining ground. Press.\nMorris, I. (2010). Why the West rules. FSG.\n"
        "Brook, T. (2010). The troubled empire. Belknap.\nGraunt, J. (1662). Observations. London.",
    )
    store.write_chapter("alice", project.id, 1, "(Clack, 2012) 모리스(2010)\n\nClack(2012) (Brook, 2008)", "x")
    store.write_chapter("alice", project.id, 2, "(Clack, 2012) 마닐라(1571)", "x", label="맺음")
    report = build_cite_report(store, "alice", project.id)
    assert report.docs["clack2012"].count == 3 and report.docs["clack2012"].chapters == ["1", "맺음"]
    assert report.docs["brook2008"].hint == "brook2010"
    assert report.docs["morris2010"].inferred == {"모리스(2010) [음역 추정]"}
    assert [k for k, _ in report.uncited] == ["brook2010", "graunt1662"]  # 본문은 Brook 2008을 인용했다
    text = report.render()
    assert "고유 미확인 문헌: **3건**" in text and "| 1 | clack2012 | unverified | 3 | 1, 맺음 |" in text
    assert "마닐라1571" in text.split("한글 표기인데")[1]


def test_three_kinds_and_non_citation_terms():
    from magus.book.comments import classify_comment
    from magus.melchior.citations import find_citations

    terms = frozenset({"선하이정", "마닐라", "모스크바 회사"})
    assert classify_comment("인용 확인 필요: Wiessner(2014)의 대화 비율.") == ("citation", "wiessner2014")
    assert classify_comment("확인 필요: 칙술루브 충돌체의 크기 추정.") == ("fact", None)
    assert classify_comment("검토 메모: 근거 연구를 인용하면 단단해집니다.") == ("general", None)
    # 비인용 용어만 걸린 확인 요청도 확인 요청이다: fact(사용자 결정 #36, 실원고 I46)
    i46 = "확인 필요: 쯔궁 선하이정(1835)의 깊이와 쓰촨 소금의 진출 경위."
    assert classify_comment(i46)[0] == "citation"  # 용어 목록이 없으면 지명이 인용처럼 잡힌다
    assert classify_comment(i46, exclude=terms) == ("fact", None)
    assert find_citations("마닐라(1571)와 모스크바 회사(1555), Clack(2012)", exclude=terms)[0].key == "clack2012"
    assert len(find_citations("마닐라(1571)와 모스크바 회사(1555), Clack(2012)", exclude=terms)) == 1


def test_terms_file_and_reimport_keeps_terms(store: LocalStore, tmp_path):
    from magus.book.importer import import_manuscript
    from magus.melchior.check import check_chapter
    from magus.synthetic import build_manuscript_pdf

    pdf = build_manuscript_pdf(tmp_path / "x.pdf")
    import_manuscript(store, "alice", pdf, project_id="b")
    store.set_non_citation_terms("alice", "b", ["넌", " 넌 ", "마셜"])
    assert store.get_non_citation_terms("alice", "b") == ["넌", "마셜"]
    assert [g.key for g in check_chapter(store, "alice", "b", 2).groups if g.key.startswith("넌") or g.key == "nunn2011"] == []
    import_manuscript(store, "alice", pdf, project_id="b", replace=True)
    assert store.get_non_citation_terms("alice", "b") == ["넌", "마셜"]  # 다시 임포트해도 유지
    issues = store.list_issues("alice", "b")
    assert issues[0].kind == "fact"  # "인용 확인 필요: 마셜(2015)" — 마셜이 비인용 용어가 되어도 확인 요청이다
