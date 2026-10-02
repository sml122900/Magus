from __future__ import annotations

import dataclasses

import pytest
from mcp import Client

from magus.book.demo import seed_demo
from magus.config import Settings
from magus.instructions import INSTRUCTIONS
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    assert not result.is_error, result
    return "".join(block.text for block in result.content)


async def test_server_identity_and_tools(settings: Settings, store: LocalStore):
    async with Client(build_server(settings, store)) as client:
        assert client.server_info.name == "Magus"
        assert client.instructions == INSTRUCTIONS
        names = {t.name for t in (await client.list_tools()).tools}
        assert "book_outline" in names


async def test_book_outline_tool(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    async with Client(build_server(settings, store)) as client:
        result = await client.call_tool("book_outline", {})
        assert result.structured_content is None  # 텍스트만 돌려준다(중복 없이)
        text = _text(result)
        assert text.startswith("# 데모: 물에서 뭍으로")
        assert _text(await client.call_tool("book_outline", {"project_id": "demo"})) == text


async def test_other_user_gets_empty_result(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    bob = dataclasses.replace(settings, user_id="bob")
    async with Client(build_server(bob, store)) as client:
        assert "프로젝트가 없습니다" in _text(await client.call_tool("book_outline", {}))
        assert "없습니다" in _text(await client.call_tool("book_outline", {"project_id": "demo"}))
