"""저자용 인용 점검 보고서: key 대신 '저자(연도) 『제목』', 이름만 나온 곳은 확실한 자리만, 7개 절."""

from __future__ import annotations

from pathlib import Path

from magus.melchior.author_report import build_author_report, chapters_text, cite_label, name_mentions, short_title, write_docx
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import after_refs_changed
from magus.store import LocalStore

BIB = (
    "Graunt, J. (1662). Natural and Political Observations Made upon the Bills of Mortality. London.\n"
    "Lee, R. B. (1969). Eating Christmas in the Kalahari. Natural History.\n"
    "Nordhaus, W. D., & Tobin, J. (1972). Is growth obsolete? In Economic Growth (pp. 1–80). NBER.\n"
    "Keynes, J. M. (1930a). A Treatise on Money, Vol. 2. Macmillan.\n"
    "Keynes, J. M. (1930b). Economic possibilities for our grandchildren. Nation.\n"
    "Maddison, A. (2001). The World Economy: A Millennial Perspective. OECD.\n"
    "Brook, T. (2010). The Troubled Empire: China in the Yuan and Ming Dynasties. Belknap.\n"
)


def test_labels_and_chapters():
    assert chapters_text(["15", "32"]) == "제15·32장"
    assert chapters_text(["15", "부록 2"]) == "제15장, 부록 2"
    assert chapters_text(["제35장"]) == "제35장"
    assert chapters_text(["35", "35", "부록 2", "부록 2"]) == "제35장, 부록 2"  # 같은 장이 두 번 찍히던 오탐
    assert short_title("Is growth obsolete? In Economic Growth (pp") == "Is growth obsolete?"
    assert short_title("A Treatise on Money, Vol") == "A Treatise on Money"
    assert short_title("The World Economy: A Millennial Perspective") == "The World Economy"


def test_name_mentions_only_certain_spots(store: LocalStore):
    import_bibliography(store, "alice", BIB)
    graunt, lee, nordhaus = (store.get_ref("alice", k) for k in ("graunt1662", "lee1969", "nordhaus1972"))
    texts = [
        ("서장", "1662년 런던. 존 그랜트라는 상인이 있었다. 그런데 그랜트는 답을 찾았다."),
        ("제7장", "집은 사람이 고른다. 그런데 새들은 다르다."),  # '고른다' ≈ Graunt지만 이름 자리가 아니다
        ("제10장", "인류학자 리처드 리는 !쿵족과 지냈다."),
        ("제2장", "레슬리 아이엘로와 휠러는 말했다. 훨씬 이른 시기였다."),  # Lee 음역 오탐 자리
        ("제19장", "노리치·콜체스터로 이주했다."),  # Nordhaus 비슷하지만 공저자(토빈)가 없다
        ("제35장", "케인스(1930), 노드하우스·토빈의 여가"),
        ("제32장", "국내 연구(이상호, 박지민)도 있다."),  # 한국인 성명은 성씨 표기만 맞아도 1점이라 Lee로 잡히던 오탐
    ]
    assert name_mentions(texts, graunt) == (["존 그랜트"], ["서장"])
    assert name_mentions(texts, lee) == (["리처드 리"], ["제10장"])
    assert name_mentions(texts, nordhaus) == (["노드하우스·토빈"], ["제35장"])
    assert cite_label(nordhaus) == "Nordhaus 외(1972) 『Is growth obsolete?』"
    assert cite_label(nordhaus, all_authors=True).startswith("Nordhaus·Tobin(1972)")


def test_report_sections_without_keys(store: LocalStore, tmp_path: Path):
    project = store.create_project("alice", "닿으려는 종", project_id="book")
    store.write_chapter("alice", project.id, 1, "Maddison(2001)에 따르면. 케인스(1930)는 말했다. Brook(2008)도.", "x")
    store.write_chapter("alice", project.id, 2, "(Maddison, 2001) 다시. 존 그랜트가 장부를 보았다.", "x")
    store.add_issue("alice", project.id, "확인 필요: 칙술루브 충돌체의 크기 추정과 대멸종 연대.", chapter_number=1,
                    origin="import_comment", kind="fact")
    import_bibliography(store, "alice", BIB)
    after_refs_changed(store, "alice")
    text = build_author_report(store, "alice", "book", "2026-10-03")
    for n in range(1, 8):
        assert f"## {n}. " in text
    assert "원고 전체 인용 **4곳**, 문헌 **3편**, 원문 대조 완료 **0편**" in text
    assert "제1장 본문 Brook(2008) ↔ 참고문헌 Brook(2010) 『The Troubled Empire』" in text
    assert "Graunt(1662) 『Natural and Political Observations Made upon the Bills…』 — 본문에는 이름만 나옵니다: '존 그랜트'(제2장)" in text
    assert "제1장 케인스(1930): Keynes(1930a) 『A Treatise on Money』, Keynes(1930b)" in text
    assert "1. Maddison(2001) 『The World Economy』 — 2곳(제1·2장)" in text
    assert "- **제1장**: 칙술루브 충돌체의 크기 추정과 대멸종 연대. (I1)" in text
    assert "maddison2001" not in text and "graunt1662" not in text  # 저자는 key를 보지 않는다
    assert write_docx(text, tmp_path / "r.docx").stat().st_size > 5000
