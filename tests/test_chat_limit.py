"""대화는 읽기 중심, 넣기는 사이트에서(2026-10-11 묶음 1, docs/decisions/2026-10-11-batch.md).

MCP로 들어온 본문(category_put의 content·idea_add_conversation의 markdown·book_write_chapter의 content)이 3,000자를 넘으면
사이트에서 올리라는 안내로 거절한다. 사이트에 올린 파일(path)·짧은 메모·쓸 부분·결정은 그대로다. 웹 글쓰기는 이 한도와 상관없다."""

from __future__ import annotations

import pytest
from mcp import Client

from magus.config import Settings
from magus.instructions import RULES, build_instructions
from magus.limits import CHAT_BODY_MAX
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
SITE = "파일은 Magus 사이트의 책 게시판에서 글쓰기로 올려 주세요."


def _text(result) -> str:
    return result.content[0].text


async def test_long_bodies_from_chat_are_refused_with_the_site_guide(settings: Settings, store: LocalStore):
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "짧은 본문", "x", title="첫 장")
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "b")
    long = "가" * (CHAT_BODY_MAX + 1)
    async with Client(build_server(settings, store)) as c:
        put = await c.call_tool("category_put", {"book": "메모", "author": "me", "content": long, "untitled": True})
        assert put.is_error and _text(put).endswith(f"긴 글(3,000자 넘음, 지금 3,001자)은 대화로 넣지 않습니다. {SITE}")
        convo = await c.call_tool("idea_add_conversation", {"book": "메모", "markdown": "**사용자:** " + long})
        assert convo.is_error and SITE in _text(convo)
        chapter = await c.call_tool("book_write_chapter", {"number": 1, "content": long, "note": "x", "project_id": "b"})
        assert chapter.is_error and "원본 파일(Word)에서 고친 뒤 사이트에서 수정본으로 올려 주세요" in _text(chapter)
        assert store.list_category_items("alice") == [] and store.read_chapter("alice", "b", 1).content == "짧은 본문"  # 아무것도 쓰지 않았다
        # 3,000자(앞뒤 공백 빼고)까지는 그대로 받는다
        ok = await c.call_tool("category_put", {"book": "메모", "author": "me", "content": "  " + "가" * CHAT_BODY_MAX + "\n", "untitled": True})
        assert not ok.is_error, _text(ok)
        # 짧은 메모·결정·쓸 부분은 지금처럼
        assert not (await c.call_tool("book_decide", {"text": "이렇게 하기로", "project_id": "b"})).is_error
        source = await c.call_tool("category_put", {"book": "메모", "author": "me", "source": {"authors": "Clack, J.", "year": "2012",
                                                                                           "title": "Gaining ground"},
                                                    "checked": True, "parts": [{"text": "네발동물", "reason": "근거"}]})
        assert not source.is_error, _text(source)


async def test_conversation_file_on_the_site_is_not_limited(settings: Settings, store: LocalStore):
    """사이트에 올린 파일(path)은 대화로 넘긴 본문이 아니라서 3,000자 한도와 상관없다."""
    store.create_project("alice", "책", project_id="b")
    store.create_category("alice", "대화", "blank", "#1f2f5c", (), "b")
    turns = "".join(f"**사용자:** 질문 {n} {'가' * 200}\n\n**Claude:** 답 {n} {'나' * 200}\n\n" for n in range(10))
    assert len(turns) > CHAT_BODY_MAX
    store.put_inbox("alice", "대화기록.md", turns.encode("utf-8"))
    async with Client(build_server(settings, store)) as c:
        added = await c.call_tool("idea_add_conversation", {"book": "대화", "path": "대화기록.md"})
        assert not added.is_error and "me 10건, ai 10건" in _text(added)


async def test_rules_tell_claude_to_stop_before_calling(settings: Settings, store: LocalStore):
    async with Client(build_server(settings, store)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
    text = build_instructions(names)
    assert SITE.removesuffix(".") in text and "2,000자를 넘을 것 같으면 부르기 전에 멈추고" in text
    assert "book_import로 가져오는 것은 그대로 한다" in RULES[6] and "확인 요청 답과 닫기·스크랩은 대화로 그대로 한다" in RULES[7]
