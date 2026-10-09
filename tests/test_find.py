"""찾기 보강(2026-10-09, #99-4): 사람이 떠올리는 대로 쳐도 무난히 찾는다. 웹 찾기와 category_search가 같은 함수(find_chunks).

1단계(색인, 순위 먼저): 라틴·숫자 낱말은 앞부분 일치("ra" → raw), 한글은 2글자 조각, 따옴표로 묶으면 구절.
2단계(글자 그대로 포함, 대소문자 무시): 1단계 뒤에 최근 글부터(한 글자·낱말 중간·기호). 첨부 파일 이름도 찾는다.
검색어의 ( ) " * : - 는 FTS 문법 오류를 내지 않는다. 공백만 있으면 찾지 않는다. 노란 강조는 실제로 맞은 부분에."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from magus.config import Settings
from magus.search import find_chunks
from magus.server import build_server
from magus.store import CategoryItem, LocalStore, Ref
from magus.textindex import search_match
from magus.webshelf import find, mark

LANES = ["category", "ref_bib", "ref_picked"]
CITY, SEOUL, LONDON, Y1700, MAPPED = (f"2026100900000000{n}-aaaaaa" for n in range(5))


def _seed(store: LocalStore, user: str = "alice") -> str:
    book = store.create_category(user, "도시 메모", "blank", "#1f2f5c", (), "common").id
    store.put_category_item(user, CategoryItem(CITY, book, "도시가 커지면 밀도가 오른다", "me", title="도시와 밀도"))
    store.put_category_item(user, CategoryItem(SEOUL, book, "서울은 왜 이렇게 넓어졌나", "me"))
    store.put_category_item(user, CategoryItem(LONDON, book, "17세기 런던의 인구는 늘었다", "me"))
    store.put_category_item(user, CategoryItem(Y1700, book, "1700년대 한양의 장시", "me"))
    store.put_category_item(user, CategoryItem(MAPPED, book, "", "me"))
    store.put_attachment(user, f"{book}/{MAPPED}", "답사지도_Jongno.pdf", b"%PDF-1.4 x")  # 제목·본문 없이 파일만
    store.put_ref(user, Ref(key="raw-3fb7a700", status="unverified", bib={"raw": "잘린 서지 한 줄 (Smith"}, book=book))
    return book


def _owners(store: LocalStore, q: str) -> list[str]:
    return [o.rsplit("/", 1)[-1] for o in find(store, "alice", LANES, q)]


@pytest.mark.parametrize("q", ["raw", "ra", "r", "RAW", "3fb7", "3fb7a700", "raw-3fb7a700", "raw-3fb7a700()", '"raw-3fb7a700()"', "fb7a"])
def test_raw_key_found_however_typed(store: LocalStore, q: str):
    _seed(store)
    assert "raw-3fb7a700" in _owners(store, q)


@pytest.mark.parametrize(("q", "first"), [
    ("도시", CITY), ("도시가", CITY), ("도시 밀도", CITY), ("서울은 왜", SEOUL), ("17세기", LONDON), ("1700", Y1700),
    ("런던", LONDON), ("jongno", MAPPED), ("답사", MAPPED), ("지도_Jon", MAPPED), ('"도시가 커지면"', CITY),
])
def test_korean_numbers_and_file_names(store: LocalStore, q: str, first: str):
    _seed(store)
    assert _owners(store, q)[0] == first


def test_one_letter_symbols_and_blank_never_error(store: LocalStore):
    _seed(store)
    assert set(_owners(store, "도")) >= {CITY, MAPPED}  # 한 글자(글자 그대로 포함: 답사지도)
    assert _owners(store, "   ") == [] and find_chunks(store, "alice", LANES, "", 10) == []
    for q in ("(", "*", ")", '"', ":", "-", "a*", "NEAR(", "raw OR", '"""', "^", "+도시"):
        assert isinstance(_owners(store, q), list)  # 문법 오류 없이 결과 또는 없음
    assert "raw-3fb7a700" in _owners(store, "(")  # 기호도 글자 그대로 찾는다
    assert search_match("( * :") is None and search_match('raw-3fb7a700()') == '"raw"* OR "3fb7a700"*'
    assert search_match('"raw-3fb7a700()" 도시') == '"raw 3fb7a700" OR "도시"'


def test_contained_results_come_after_ranked_and_newest_first(store: LocalStore):
    book = _seed(store)
    store.put_category_item("alice", CategoryItem("20261009000000009-bbbbbb", book, "그 도시의 골목", "me"))
    owners = _owners(store, "시의")  # 2글자 조각 '시의'는 색인에도 있다
    assert owners and owners[0] == "20261009000000009-bbbbbb"
    contained = _owners(store, "커지")  # 색인 조각(커지)으로 먼저, 같은 글은 한 번
    assert contained.count(CITY) == 1


def test_mark_shows_what_actually_matched():
    assert mark("raw-3fb7a700()", "ra") == "<mark>ra</mark>w-3fb7a700()"
    assert mark("raw-3fb7a700()", '"raw-3fb7a700()"') == "<mark>raw-3fb7a700()</mark>"
    assert mark("RAW 키", "raw") == "<mark>RAW</mark> 키"
    assert mark("도시는 넓다", "도시가") == "<mark>도시</mark>는 넓다"
    assert mark("a<b", "(") == "a&lt;b"


@pytest.mark.anyio
async def test_mcp_uses_the_same_search(store: LocalStore, data_dir: Path):
    _seed(store)
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        def text(r) -> str:
            return r.content[0].text

        assert CITY in text(await c.call_tool("category_search", {"query": "도시"}))
        assert MAPPED in text(await c.call_tool("category_search", {"query": "jongno"}))  # 첨부 파일 이름
        assert LONDON in text(await c.call_tool("category_search", {"query": "17세"}))
        for q in ("(", "*", '"', "raw-3fb7a700()"):
            assert not (await c.call_tool("category_search", {"query": q})).is_error
        assert "검색어가 비었다" in text(await c.call_tool("category_search", {"query": "  "}))
        found = text(await c.call_tool("category_search", {"query": "x", "k": 30}))
        assert "결과 없음" in found or found.count("\n") < 80  # 결과 상한은 그대로(k)


def test_index_follows_attachments(store: LocalStore):
    book = _seed(store)
    assert MAPPED in _owners(store, "jongno")
    [att] = store.list_attachments("alice", f"{book}/{MAPPED}")
    store.trash_attachment("alice", f"{book}/{MAPPED}", att.id, "x")
    assert MAPPED not in _owners(store, "jongno")  # 뺀 첨부의 이름으로는 찾지 않는다
    store.restore_trash("alice", "attachment", f"{book}/{MAPPED}/{att.id}")
    assert MAPPED in _owners(store, "jongno")
    store.reindex()  # 색인은 파일에서 다시 만든다
    assert MAPPED in _owners(store, "jongno")
