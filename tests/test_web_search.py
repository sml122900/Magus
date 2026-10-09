"""웹 찾기(2026-10-09 구조·버그 점검 4번): 기호가 든 검색어는 글자 그대로, 낱말이 여럿이면 모두 맞는 글만(AND),
구절은 발췌에 구절 전체를 표시, 파일 이름으로만 맞은 글은 '📎 파일 이름', 결과 문구는 세 곳(게시판·지도·전체)이 같다.
대화(category_search)도 같은 규칙(2026-10-09 결정 b, 전에는 웹만)."""

from __future__ import annotations

import re

import httpx2
import pytest
from mcp import Client
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.search import find_all_words, find_chunks
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

pytestmark = pytest.mark.anyio

BOOK = "notes-common"
POSTS = {
    "20261009000000001-aaaaaa": "볼드 <b>태그</b> 예시",
    "20261009000000002-aaaaaa": "bold로 시작하는 b 낱말",
    "20261009000000003-aaaaaa": "doc_1009 파일 이야기",
    "20261009000000004-aaaaaa": "doc 그리고 1009 따로",
    "20261009000000005-aaaaaa": "도시 성장 이야기",
    "20261009000000006-aaaaaa": "도시, 성장의 조건",
    "20261009000000007-aaaaaa": "도시만 있음",
    "20261009000000008-aaaaaa": "성장만 있음",
    "20261009000000009-aaaaaa": "사진 한 장",
}


def _seed(data_dir) -> LocalStore:
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id=BOOK)
    for item_id, text in POSTS.items():  # 제목이 있어야 파일 이름이 제목 자리에 보이지 않는다(제목 자동 채움)
        store.put_category_item("alice", CategoryItem(item_id, BOOK, text, "me", "글", "author"))
    store.put_attachment("alice", f"{BOOK}/20261009000000009-aaaaaa", "현장사진.png", b"\x89PNG\r\n\x1a\n0000")
    return store


def _owners(chunks) -> set[str]:
    return {c.owner_id.split("/")[1][:17] for c in chunks}


def test_find_all_words(store: LocalStore, data_dir):
    store.close()
    store = _seed(data_dir)
    lanes = ["category"]
    assert _owners(find_all_words(store, "alice", lanes, "<b>", 50)) == {"20261009000000001"}  # b·bold로 넓히지 않는다
    assert _owners(find_all_words(store, "alice", lanes, "doc_1009", 50)) == {"20261009000000003"}  # doc·1009 따로인 글은 아니다
    assert _owners(find_all_words(store, "alice", lanes, "도시 성장", 50)) == {"20261009000000005", "20261009000000006"}  # AND
    assert _owners(find_all_words(store, "alice", lanes, '"도시 성장"', 50)) == {"20261009000000005", "20261009000000006"}
    assert _owners(find_all_words(store, "alice", lanes, "도시 없는낱말", 50)) == set()
    assert len(_owners(find_all_words(store, "alice", lanes, "도시", 50))) == 3  # 낱말 하나는 지금까지와 같다
    # find_chunks(순위·1단계 찾기)는 그대로: 낱말 중 하나만 맞아도
    assert "20261009000000007" in _owners(find_chunks(store, "alice", lanes, "도시 성장", 50))
    store.close()


async def test_chat_search_same_rules(data_dir, settings):
    """대화(category_search)도 웹과 같은 사례(결정 b): 낱말 여럿은 AND, 기호가 든 낱말은 글자 그대로, 낱말 하나는 그대로."""
    store = _seed(data_dir)
    async with Client(build_server(settings, store)) as c:
        async def found(query: str) -> set[str]:
            text = (await c.call_tool("category_search", {"query": query, "k": 20})).content[0].text
            return {item[:17] for item in re.findall(r"20261009\d{9}-aaaaaa", text)}

        assert await found("<b>") == {"20261009000000001"}
        assert await found("doc_1009") == {"20261009000000003"}
        assert await found("도시 성장") == {"20261009000000005", "20261009000000006"}
        assert await found('"도시 성장"') == {"20261009000000005", "20261009000000006"}
        assert await found("도시 없는낱말") == set()
        assert len(await found("도시")) == 3
        assert await found("현장사진") == {"20261009000000009"}
    store.close()


def test_web_search_lines(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    _seed(data_dir).close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        c.get("/login?next=/shelf")
        board = c.get(f"/shelf/{BOOK}", params={"q": "도시 성장"}).text
        assert f'<p class="found">「도시 성장」 2건 · <a href="/shelf/{BOOK}">지우기</a></p>' in board
        phrase = c.get(f"/shelf/{BOOK}", params={"q": '"도시 성장"'}).text
        assert "<mark>도시, 성장</mark>" in phrase  # 구절 전체(문장부호가 끼어도)
        none = c.get(f"/shelf/{BOOK}", params={"q": "없는낱말"}).text
        assert '<p class="found">「없는낱말」 맞는 글이 없습니다. · ' in none and '<p class="msg">없음</p>' not in none
        symbol = c.get(f"/shelf/{BOOK}", params={"q": "<b>"}).text
        assert "「&lt;b&gt;」 1건" in symbol and "bold로" not in symbol
        named = c.get(f"/shelf/{BOOK}", params={"q": "현장사진"}).text
        assert re.search(r'<small class="hit"><span aria-hidden="true">📎</span> <mark>현장사진</mark>\.png</small>', named)
        mapped = c.get("/shelf/p/common", params={"q": "도시 성장"}).text
        assert '<p class="found">「도시 성장」 2건 · <a href="/shelf/p/common">지우기</a></p>' in mapped
        assert "「없는낱말」 맞는 글이 없습니다." in c.get("/shelf/p/common", params={"q": "없는낱말"}).text
        everything = c.get("/shelf", params={"q": "도시 성장"}).text
        assert '<p class="found">「도시 성장」 2건 · <a href="/shelf">지우기</a></p>' in everything
        assert "「없는낱말」 맞는 글이 없습니다." in c.get("/shelf", params={"q": "없는낱말"}).text
