"""저자 확인 질문지(#84): book_questions(조회) → book_answer(답 반영). 질문은 매번 계산하고 답만 book/answers.md에 쌓인다."""

from __future__ import annotations

import pytest
from mcp import Client

from magus.config import Settings
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import after_refs_changed
from magus.melchior.questions import build_questions, parse_answers
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio

BIB = (
    "Graunt, J. (1662). Natural and Political Observations Made upon the Bills of Mortality. London.\n"
    "Keynes, J. M. (1930a). A Treatise on Money, Vol. 2. Macmillan.\n"
    "Keynes, J. M. (1930b). Economic possibilities for our grandchildren. Nation.\n"
    "Maddison, A. (2001). The World Economy: A Millennial Perspective. OECD.\n"
    "Brook, T. (2010). The Troubled Empire: China in the Yuan and Ming Dynasties. Belknap.\n"
    "Acemoglu, D., Johnson, S., & Robinson, J. A. (2001). The colonial origins of comparative development. AER.\n"
    "Acemoglu, D., & Robinson, J. A. (2001). A theory of political transitions. AER.\n"
    "IEA. (2025). World Energy Outlook 2025. Paris.\n"
    "International Energy Agency. (2025). World Energy Outlook 2025. Paris.\n"
)
TEXT = ("매디슨(2001)에 따르면. 케인스(1930)는 말했다. Brook(2008)도. (Acemoglu, Johnson & Robinson, 2001). 가나다(2019)의 말. "
        "IEA(2025), International Energy Agency(2025).")


def _book(store: LocalStore, user: str = "alice") -> None:
    store.create_project(user, "책", project_id="book")
    store.write_chapter(user, "book", 1, TEXT, "x", title="첫 장")
    import_bibliography(store, user, BIB)
    after_refs_changed(store, user)


def _text(result) -> str:
    return "\n".join(block.text for block in result.content)


def test_questions_cover_every_type(store: LocalStore):
    _book(store)
    found = {q.id: q for q in build_questions(store, "alice", "book")}
    assert set(found) == {
        "year:brook2008", "bibonly:graunt1662", "translit:매디슨2001>maddison2001", "ab:keynes1930a/b", "pair:acemoglu2001",
        "unlinked:가나다2019", "dup:iea2025=internationalenergyagency2025", "bibonly:acemoglu2001-2",
    }  # brook2010은 연도 불일치 질문이 이미 가리키므로 '참고문헌에만 있음'으로 또 묻지 않는다
    assert found["year:brook2008"].text == "제1장 본문 Brook(2008) ↔ 참고문헌 Brook(2010) 『The Troubled Empire』. 연도가 다릅니다."
    assert "brook" not in found["year:brook2008"].text  # 저자에게 보이는 문장에는 key가 없다
    assert [c for c, _ in found["ab:keynes1930a/b"].options] == ["ref:keynes1930a", "ref:keynes1930b"]
    assert found["translit:매디슨2001>maddison2001"].surface == "매디슨(2001)"
    assert all(q.state == "open" for q in found.values())


async def test_answers_apply_and_persist(settings: Settings, store: LocalStore):
    _book(store)
    async with Client(build_server(settings, store)) as c:
        listed = _text(await c.call_tool("book_questions", {}))
        assert listed.startswith("프로젝트: 책 (book) · 저자에게 물을 것 8건(열림 8 · 원고 반영 대기 0 · 답함 0)")
        assert "[translit:매디슨2001>maddison2001] 한글 표기 추정 — 제1장 매디슨(2001) → Maddison(2001)" in listed
        assert "[ab:keynes1930a/b]" in _text(await c.call_tool("book_questions", {"type": "ab"}))
        for args, why in (({"question_id": "year:없음", "choice": "fix_text"}, "지금 원고에 없는 질문"),
                          ({"question_id": "year:brook2008", "choice": "yes"}, "선택지가 아니다")):
            result = await c.call_tool("book_answer", args)
            assert result.is_error and why in _text(result), args
        # 표기를 잇는 답은 바로 반영되고 질문이 사라진다
        said = _text(await c.call_tool("book_answer", {"question_id": "translit:매디슨2001>maddison2001", "choice": "yes", "note": "맞아"}))
        assert said.startswith("답을 기록함: [translit:매디슨2001>maddison2001] 맞다") and "「매디슨(2001)」를 그 문헌에 이음" in said
        assert "매디슨2001" in store.get_ref("alice", "maddison2001").aliases
        await c.call_tool("book_answer", {"question_id": "ab:keynes1930a/b", "choice": "ref:keynes1930b"})
        assert "케인스1930" in store.get_ref("alice", "keynes1930b").aliases
        await c.call_tool("book_answer", {"question_id": "unlinked:가나다2019", "choice": "not_person"})
        assert "가나다" in store.get_non_citation_terms("alice", "book")
        # Word에서 고칠 답은 결정으로 남고 '원고 반영 대기'가 된다. '그대로 둔다'는 답함
        waiting = _text(await c.call_tool("book_answer", {"question_id": "year:brook2008", "choice": "fix_text", "note": "2010이 맞다"}))
        assert "결정 D1로 남김" in waiting
        assert store.list_decisions("alice", "book")[0].text.startswith("[질문 year:brook2008] 제1장 본문 Brook(2008)")
        await c.call_tool("book_answer", {"question_id": "bibonly:graunt1662", "choice": "keep"})
        after = _text(await c.call_tool("book_questions", {}))
        assert "열림 4 · 원고 반영 대기 1 · 답함 1" in after and "매디슨" not in after and "graunt" not in after
        assert "[bibonly:keynes1930a]" in after  # 1930b로 이었더니 1930a가 '참고문헌에만 있음'이 됐다(새 질문)
        assert "[year:brook2008]" in _text(await c.call_tool("book_questions", {"status": "waiting"}))
    answers = parse_answers(store.get_answers("alice", "book"))
    assert [a["id"] for a in answers][:1] == ["translit:매디슨2001>maddison2001"] and answers[0]["note"] == "맞아"
    assert {a["choice"] for a in answers} == {"yes", "ref:keynes1930b", "not_person", "fix_text", "keep"}
    assert answers[3]["decision"] == "D1" and answers[0]["applied"] == "alias maddison2001 ← 매디슨2001"
    # 저자가 Word에서 고쳐 다시 올리면(여기서는 본문을 바로 바꿈) 조건이 사라져 질문도 사라진다. 답은 파일에 남는다
    store.write_chapter("alice", "book", 1, TEXT.replace("Brook(2008)", "Brook(2010)"), "수정본")
    ids = {q.id for q in build_questions(store, "alice", "book")}
    assert "year:brook2008" not in ids and "bibonly:graunt1662" in ids and len(parse_answers(store.get_answers("alice", "book"))) == 5
    store.reindex()  # 답은 파일이 원본이다
    assert {q.id: q.state for q in build_questions(store, "alice", "book")}["bibonly:graunt1662"] == "answered"


async def test_questions_are_per_user(settings: Settings, store: LocalStore):
    _book(store, "alice")
    store.create_project("bob", "밥의 책", project_id="book")
    store.write_chapter("bob", "book", 1, "그냥 글.", "x")
    bob = settings.__class__(**{**settings.__dict__, "user_id": "bob"})
    async with Client(build_server(bob, store)) as c:
        assert "저자에게 물을 것 0건" in _text(await c.call_tool("book_questions", {}))
        assert (await c.call_tool("book_answer", {"question_id": "year:brook2008", "choice": "fix_text"})).is_error
    assert store.get_answers("alice", "book") == "" and store.list_decisions("alice", "book") == []
