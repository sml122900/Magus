"""6단계 → #96: 문체도 여느 책의 글이다(컨텍스트 「문체」). 이유·위치·태그 칸, 찾기는 category_search."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from mcp import Client

from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore
from tests.conftest import make_book

pytestmark = pytest.mark.anyio

TAGS = {"호흡": "짧고 끊김", "시점": "1인칭", "열기": "장면", "장치": ["반복", "대구"], "어미": "-다 체", "톤": "건조함"}
STYLE = "문학적 부분이 마음에 드는 구절을 모아놓은것. 내 문장 표현을 다듬을때 사용"


def _text(result) -> str:
    assert not result.is_error, result.content[0].text
    return "".join(block.text for block in result.content)


async def test_style_book_put_and_search(settings: Settings, store: LocalStore, data_dir: Path):
    book = make_book(store, settings.user_id, "문체", "문체")
    async with Client(build_server(settings, store)) as client:
        added = _text(await client.call_tool("category_put", {
            "book": "문체", "author": "me", "untitled": True, "content": "고래는 돌아갔다. 물이 고래를 불렀다. 고래는 대답했다.",
            "reason": "문장이 짧아 숨이 가쁘고, 같은 주어의 반복이 리듬을 만든다", "where": "합성 산문", "tags": ["호흡: 짧고 끊김", "장치: 반복"]}))
        assert added.splitlines()[0] == f"컨텍스트(책 「문체」): 「문체」 {STYLE}"  # 사용자가 준 문장 그대로(#96)
        await client.call_tool("category_put", {
            "book": "문체", "author": "me", "untitled": True,
            "content": "그 여름의 물가에는 아무도 없었고, 나는 오래도록 바람이 지나간 자리를 바라보았다.",
            "reason": "길게 이어지는 회상의 문장이 느린 호흡을 만든다"})
        # 낱말 여럿은 모두 맞는 글만(결정 b): '짧은'은 글에 없어('짧아'·'짧고') 빼고 찾는다
        assert "결과 없음" in _text(await client.call_tool("category_search", {"query": "짧은 반복 리듬"}))
        hit = _text(await client.call_tool("category_search", {"query": "반복 리듬"}))
        assert "## 「문체」 — 컨텍스트(책 「문체」)" in hit and "“고래는 돌아갔다." in hit and "이유: 문장이 짧아" in hit
        assert "위치: 합성 산문" in hit and "태그: 호흡: 짧고 끊김, 장치: 반복" in hit
        assert "길게 이어지는" in _text(await client.call_tool("category_search", {"query": "느린 호흡 회상"}))
        # #96: 구절(본문)도 찾는다. 무엇을 볼지는 컨텍스트가 말한다(옛 문체는 이유·태그로만 찾았다)
        assert "고래는 돌아갔다" in _text(await client.call_tool("category_search", {"query": "고래", "book": "문체"}))
        assert (await client.call_tool("category_put", {"book": "문체", "author": "me", "untitled": True})).is_error

    assert len(list((data_dir / f"users/alice/shelf/categories/{book}/items").glob("*.json"))) == 2
    before = store.list_category_items(settings.user_id, book)
    store.reindex()
    assert store.list_category_items(settings.user_id, book) == before
    bob = dataclasses.replace(settings, user_id="bob")
    async with Client(build_server(bob, store)) as client:
        assert "결과 없음" in _text(await client.call_tool("category_search", {"query": "짧은 문장"}))


async def test_all_instruction_rules_active(settings: Settings, store: LocalStore):
    from tests.test_instructions import SPEC

    async with Client(build_server(settings, store)) as client:
        assert client.instructions == SPEC  # 도구가 모두 등록되면 규칙 원문 그대로


async def test_where_is_searchable(settings: Settings, store: LocalStore):
    # "유홍준 그 문장"처럼 출전(위치)으로도 찾는다(사용자 결정 #24, #96에서도 그대로)
    make_book(store, settings.user_id, "문체", "문체")
    async with Client(build_server(settings, store)) as client:
        await client.call_tool("category_put", {"book": "문체", "author": "me", "untitled": True, "content": "아는 만큼 보인다.",
                                                "reason": "짧은 단정이 글 전체를 연다", "where": "유홍준, 나의 문화유산답사기"})
        assert "아는 만큼 보인다" in _text(await client.call_tool("category_search", {"query": "유홍준"}))
