"""대화 검색 순위(2026-10-09, #101-1, #100-l): 문헌이 많은 책에서 서지만 맞은 결과가 칸을 채워 생각·일반 글이 밀리지 않게.

- 순위: 제목·본문·쓸 부분이 맞은 결과 > 첨부 글자(·원문)가 맞은 결과 > 서지·key·한글 표기·첨부 이름만 맞은 결과.
- 책을 말하지 않은 찾기는 책마다 4개까지 먼저, 남는 칸은 다른 책(다른 책에 결과가 없으면 그때 채움). 머리에 책별 개수.
- book을 주면 그 책만, 책별 제한 없음. 웹 찾기는 그대로."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from mcp import Client

from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, LocalStore, Passage, Ref

pytestmark = pytest.mark.anyio


def _seed(store: LocalStore) -> dict[str, str]:
    ideas = store.create_category("alice", "생각", "blank", "#1f2f5c", (), "common").id
    refs = store.create_category("alice", "문헌", "blank", "#1f4a3a", (), "common").id
    styles = store.create_category("alice", "문체", "blank", "#6e1f2f", (), "common").id
    for n in range(12):
        store.put_category_item("alice", CategoryItem(f"202610090000000{n:02d}-aaaaaa", ideas, f"도시는 모이는 곳이다 {n}", "me"))
    store.put_category_item("alice", CategoryItem("20261009000000050-bbbbbb", styles, "짧게 끊는다", "me", reason="도시 이야기의 호흡"))
    for n in range(40):  # 서지(제목)에만 '도시'가 있는 문헌 40편
        store.put_ref("alice", Ref(key=f"author{n:02d}1990", status="unverified",
                                   bib={"authors": f"Author{n:02d}", "year": 1990, "title": f"도시 연구 {n}"}, book=refs))
    store.put_ref("alice", Ref(key="daeschler2006", status="verified", bib={"authors": "Daeschler", "year": 2006, "title": "Tiktaalik"},
                               book=refs), passages=[Passage("물고기가 뭍으로 올라온 증거", "근거")])
    store.put_ref("alice", Ref(key="daeschler2009", status="unverified", bib={"authors": "Daeschler", "year": 2009, "title": "Fins"}, book=refs))
    return {"ideas": ideas, "refs": refs, "styles": styles}


async def _search(data_dir: Path, store: LocalStore, **args) -> str:
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        return (await c.call_tool("category_search", args)).content[0].text


def _books(text: str) -> list[str]:
    return re.findall(r"^## 「([^」]+)」", text, re.M)


def _count(text: str, book: str) -> int:
    part = text.split(f"## 「{book}」", 1)[1] if f"## 「{book}」" in text else ""
    return len(re.findall(r"^\d+\. ", part.split("\n## ", 1)[0], re.M))


async def test_one_book_does_not_take_every_slot(store: LocalStore, data_dir: Path):
    _seed(store)
    found = await _search(data_dir, store, query="도시")
    assert "— 8건." in found
    assert "책별 개수: " in found and "생각 12" in found and "문헌 40" in found and "문체 1" in found
    assert "— 한 책만 보려면 book=책 이름(책마다 4개까지 보였다)" in found
    assert (_count(found, "생각"), _count(found, "문체"), _count(found, "문헌")) == (4, 1, 3)  # 생각 4·문체 1, 남는 3칸은 문헌
    assert _books(found).index("문헌") == len(_books(found)) - 1  # 서지만 맞은 문헌은 맨 뒤


async def test_named_book_has_no_cap_or_counts(store: LocalStore, data_dir: Path):
    _seed(store)
    found = await _search(data_dir, store, query="도시", book="문헌")
    assert "— 8건." in found and "책별 개수" not in found and _books(found) == ["문헌"] and _count(found, "문헌") == 8
    ideas = await _search(data_dir, store, query="도시", book="생각", k=10)
    assert _count(ideas, "생각") == 10  # 책을 주면 책마다 4개 제한이 없다


async def test_only_sources_match_stays_as_before(store: LocalStore, data_dir: Path):
    _seed(store)
    found = await _search(data_dir, store, query="Daeschler")
    assert _books(found) == ["문헌"] and _count(found, "문헌") == 2  # 문헌만 맞으면 그대로(다른 책에 없으니 채운다)
    assert "책별 개수: 문헌 2" in found


async def test_grades_body_over_attachment_text_over_names(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    named = store.put_category_item("alice", CategoryItem("20261009000000060-cccccc", ids["styles"], "이름만", "me")).id
    store.put_attachment("alice", f"{ids['styles']}/{named}", "옹기장수_지도.pdf", b"%PDF-1.4 x")  # 첨부 이름에만 '옹기장수'
    texted = store.put_category_item("alice", CategoryItem("20261009000000061-dddddd", ids["styles"], "글자만", "me")).id
    att = store.put_attachment("alice", f"{ids['styles']}/{texted}", "일지.txt", "새벽에 옹기장수가 왔다".encode())
    store.attachment_text("alice", f"{ids['styles']}/{texted}", att.id)
    store.put_category_item("alice", CategoryItem("20261009000000062-eeeeee", ids["ideas"], "옹기장수의 하루", "me"))
    found = await _search(data_dir, store, query="옹기장수")
    order = re.findall(r"^\d+\. (\S+)", found, re.M)
    assert order.index("20261009000000062-eeeeee") < order.index(texted) < order.index(named)
