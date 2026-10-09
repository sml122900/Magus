"""후속 C(2026-10-09): 찾기에서 모든 낱말이 맞는 글이 없으면 일부 낱말만 맞는 글(표시), 이 단계에서만 한글 낱말의 앞부분(활용형).
웹(게시판·프로젝트·전체)과 대화(category_search)가 같은 규칙. 기호가 든 낱말은 글자 그대로."""

from __future__ import annotations

import re

import httpx2
import pytest
from mcp import Client
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.search import find_all_words, relaxed_words, stem_of
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

pytestmark = pytest.mark.anyio

BOOK, OTHER = "notes-a", "notes-b"
POSTS = {
    "20261009000000001-cccccc": "문장이 짧아 반복되는 리듬이 생긴다",
    "20261009000000002-cccccc": "도시가 커지면 사람이 모인다",
    "20261009000000003-cccccc": "인류가 선택했다는 이야기",
    "20261009000000004-cccccc": "리듬만 있는 글",
    "20261009000000005-cccccc": "bold로 쓴 리듬 아닌 낱말",
    "20261009000000006-cccccc": "짧고 굵게",
}


def _seed(data_dir) -> LocalStore:
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id=BOOK)
    store.create_category("alice", "다른 책", "blank", "#1f2f5c", (), "common", category_id=OTHER)
    for item_id, text in POSTS.items():
        store.put_category_item("alice", CategoryItem(item_id, BOOK, text, "me", "글", "author"))
    # 다른 책에만 '반복 리듬'이 모두 맞는 글이 있다(범위 시험)
    store.put_category_item("alice", CategoryItem("20261009000000009-cccccc", OTHER, "반복 리듬 모두", "me", "글", "author"))
    return store


def _ids(chunks) -> list[str]:
    return list(dict.fromkeys(c.owner_id.split("/")[1][:17] for c in chunks))


def test_stem_rule():
    assert [stem_of(w) for w in ("짧은", "도시는", "선택한", "리듬", "도시", "은", "AI는", "doc_1009", "민주주의")] == \
        ["짧", "도시", "선택", None, None, None, None, None, "민주주"]
    assert relaxed_words('짧은 "도시는" 리듬') == ["짧"]  # 따옴표 구절은 그대로


def test_partial_words_and_conjugations(store: LocalStore, data_dir):
    store.close()
    store = _seed(data_dir)
    lanes = ["category"]

    def found(q: str, keep=None):
        return find_all_words(store, "alice", lanes, q, 50, keep=keep)

    # '짧은 반복 리듬' ↔ '짧아… 반복… 리듬': 모든 낱말이 맞는 글이 없어 일부(끝을 뗀 꼴 포함), 맞은 낱말이 많은 것부터
    got = found("짧은 반복 리듬")
    assert _ids(got)[:2] == ["20261009000000001", "20261009000000009"]  # 3개 맞음(짧→짧아) · 2개
    assert all(c.partial > 0 for c in got) and got[0].partial == 3
    assert "20261009000000004" in _ids(got)  # 리듬만(1개)도 뒤에
    # 활용형 셋: 짧은/짧아, 도시는/도시가, 선택한/선택했다
    assert set(_ids(found("짧은"))) == {"20261009000000001", "20261009000000006"}  # 짧아·짧고
    assert _ids(found("도시는")) == ["20261009000000002"] and found("도시는")[0].partial == 1
    assert _ids(found("선택한")) == ["20261009000000003"]
    assert set(_ids(found("도시는 선택한"))) == {"20261009000000002", "20261009000000003"}
    # 모두 맞는 글이 있으면 지금처럼 그것만(일부만 맞는 글은 붙이지 않는다)
    full = found("반복 리듬")
    assert set(_ids(full)) == {"20261009000000001", "20261009000000009"} and all(c.partial == 0 for c in full)
    # 범위: 이 책에는 모두 맞는 글이 없다 → 이 책 안에서 일부만 맞는 글
    in_book = found("반복 리듬 모두", keep=lambda t, o: o.startswith(f"{BOOK}/"))
    assert _ids(in_book)[0] == "20261009000000001" and all(c.partial for c in in_book)
    assert _ids(found("반복 리듬 모두")) == ["20261009000000009"]  # 범위를 안 주면 모두 맞는 글
    # 기호가 든 낱말은 글자 그대로(일부 맞음 단계에서도 b·bold로 넓히지 않는다)
    sym = found("<b> 리듬")
    assert "20261009000000005" in _ids(sym)  # 리듬으로만 맞음
    assert all(c.partial == 1 for c in sym)
    assert found("<b>") == []
    # 앞부분으로도 없으면 결과 없음
    assert found("없는낱말") == [] and found("도시 없는낱말")[0].partial == 1
    store.close()


async def test_chat_search_marks_partial(data_dir, settings):
    store = _seed(data_dir)
    async with Client(build_server(settings, store)) as c:
        async def ask(query: str, **more) -> str:
            return (await c.call_tool("category_search", {"query": query, "k": 20, **more})).content[0].text

        text = await ask("짧은 반복 리듬", book="메모")
        assert "일부 낱말만 맞음" in text.splitlines()[0]
        order = re.findall(r"20261009\d{9}-cccccc", text)
        assert order[0].startswith("20261009000000001")  # 맞은 낱말이 많은 글 먼저
        assert "일부 낱말만 맞음" not in (await ask("반복 리듬")).splitlines()[0]
        for query, want in (("짧은", "20261009000000001"), ("도시는", "20261009000000002"), ("선택한", "20261009000000003")):
            said = await ask(query)
            assert want in said and "일부 낱말만 맞음" in said.splitlines()[0], query
        assert "결과 없음" in await ask("없는낱말")
    store.close()


def test_web_marks_partial(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    _seed(data_dir).close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        c.get("/login?next=/shelf")
        board = c.get(f"/shelf/{BOOK}", params={"q": "짧은 반복 리듬"}).text
        assert re.search(r'<p class="found">「짧은 반복 리듬」 일부 낱말만 맞음 \d+건 · ', board)
        assert "<mark>짧</mark>아" in board  # 앞부분도 표시
        assert '「반복 리듬」 1건 · ' in c.get(f"/shelf/{BOOK}", params={"q": "반복 리듬"}).text
        assert "「도시는」 일부 낱말만 맞음 1건" in c.get(f"/shelf/{BOOK}", params={"q": "도시는"}).text
        # 프로젝트·전체: 어느 책에든 모두 맞는 글이 있으면 일부만 맞는 글은 빼고 그것만
        mapped = c.get("/shelf/p/common", params={"q": "반복 리듬 모두"}).text
        assert "「반복 리듬 모두」 1건 · " in mapped and "문장이 짧아" not in mapped
        everything = c.get("/shelf", params={"q": "짧은 반복 리듬"}).text
        assert "「짧은 반복 리듬」 일부 낱말만 맞음" in everything and "문장이" in everything
        assert "「없는낱말」 맞는 글이 없습니다." in c.get("/shelf", params={"q": "없는낱말"}).text
