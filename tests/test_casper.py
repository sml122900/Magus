"""5단계 → #96: 대화 기록(idea_add_conversation)을 책의 글로. 세 형식과 완료 기준(me 96 / ai 96). 찾기는 category_search."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from mcp import Client

from magus.casper.conversation import split_conversation
from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore
from magus.synthetic import conversation_full_record, conversation_qa, conversation_quote_summary
from tests.conftest import make_book

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    assert not result.is_error, result.content[0].text
    return "".join(block.text for block in result.content)


def test_format_a_full_record_96_pairs():
    split = split_conversation(conversation_full_record())
    assert (split.me, split.ai) == (96, 96)
    assert split.failures == [(1, "아래는 여러 대화를 이어 붙인 합성 기록이다.")]  # 서문은 분리 실패로 리포트
    for n, u in enumerate(split.utterances):
        if u.speaker == "ai":
            assert split.utterances[u.parent].speaker == "me" and u.parent == n - 1
    assert "## 대화" not in split.utterances[23].text  # 대화 사이 구분 제목은 앞 발화에 붙지 않는다
    assert split.utterances[1].text.endswith("환경의 압력으로 볼 수도 있습니다.")  # 여러 문단 답변


def test_format_b_and_c():
    b = split_conversation(conversation_qa())
    assert (b.me, b.ai, b.failures) == (10, 10, [])
    c = split_conversation(conversation_quote_summary())
    assert (c.me, c.ai, c.failures) == (8, 8, [])
    assert c.utterances[0].text.startswith("물고기가 뭍으로 올라온 건") and ">" not in c.utterances[0].text
    assert c.utterances[1].text.startswith("사용자는 물가을(를)")


def test_failures_are_reported():
    split = split_conversation("**Claude:** 고아 답변\n\n**사용자:**\n\n**사용자:** 진짜 질문\n**Claude:** 답")
    assert (split.me, split.ai) == (1, 1)
    assert [line for line, _ in split.failures] == [1, 3]
    assert "앞선 사용자 발화가 없는 AI 발화" in split.failures[0][1]


async def test_completion_criterion_and_search(settings: Settings, store: LocalStore, tmp_path: Path):
    book = make_book(store, settings.user_id, "생각", "생각 메모")
    store.put_inbox(settings.user_id, "대화_전체_기록.md", conversation_full_record().encode())  # 올린 파일 이름으로
    async with Client(build_server(settings, store)) as client:
        report = _text(await client.call_tool("idea_add_conversation", {"path": "대화_전체_기록.md", "book": "생각"}))
        assert report.startswith("컨텍스트(책 「생각」): 「생각 메모」 떠오른 생각을 적어 둔 메모다.")  # 컨텍스트를 머리에(#96)
        assert "me 96건, ai 96건, 분리 실패 구간 1개" in report
        items = store.list_category_items(settings.user_id, book)
        me = {i.id for i in items if i.author == "me"}
        ai = [i for i in items if i.author == "ai"]
        assert len(me) == 96 and len(ai) == 96 and all(i.parent_id in me for i in ai)
        assert all(i.kind == "conversation" and i.origin == "대화_전체_기록" for i in items)

        put = _text(await client.call_tool("category_put", {"book": "생각", "author": "me", "content": "고래는 돌아간 자의 상징이다",
                                                              "where": "산책", "untitled": True}))
        assert "넣음: 「생각」" in put
        mine = _text(await client.call_tool("category_search", {"query": "고래", "author": "me"}))
        assert "[ai]" not in mine and "[me]" in mine and "## 「생각」 — 컨텍스트(책 「생각」)" in mine
        both = _text(await client.call_tool("category_search", {"query": "고래", "k": 20}))  # 낱말 여럿은 AND(결정 b)라 하나로
        authors = [line.split("]")[0].split("[")[1] for line in both.splitlines() if line[:1].isdigit() and "[" in line]
        assert "me" in authors and "ai" in authors and authors == sorted(authors, key=lambda a: a != "me")  # 저자의 말 먼저
        ai_only = _text(await client.call_tool("category_search", {"query": "고래", "author": "ai"}))
        assert "[me]" not in ai_only and "↳ 이 글이 응답한 저자의 말" in ai_only


async def test_conversation_markdown_argument_and_errors(settings: Settings, store: LocalStore):
    make_book(store, settings.user_id, "질의")
    async with Client(build_server(settings, store)) as client:
        text = _text(await client.call_tool("idea_add_conversation", {"markdown": conversation_qa(3), "origin": "질의", "book": "질의"}))
        assert text.startswith("컨텍스트: 없음(일반 메모로 다룬다)") and "me 3건, ai 3건" in text
        assert (await client.call_tool("idea_add_conversation", {"book": "질의"})).is_error
        assert (await client.call_tool("idea_add_conversation", {"markdown": "마커 없는 글", "book": "질의"})).is_error
        missing = await client.call_tool("idea_add_conversation", {"markdown": conversation_qa(1), "book": "없는 책"})
        assert missing.is_error and "책: 「질의」" in missing.content[0].text  # 없는 책이면 책 이름을 보여 주며 묻게 한다


async def test_ideas_user_scoped_and_reindexed(settings: Settings, store: LocalStore, data_dir: Path):
    book = make_book(store, settings.user_id, "생각", "생각 메모")
    async with Client(build_server(settings, store)) as client:
        await client.call_tool("idea_add_conversation", {"markdown": conversation_quote_summary(2), "book": "생각"})
    files = list((data_dir / f"users/alice/shelf/categories/{book}/items").glob("*.json"))
    assert len(files) == 4
    before = store.list_category_items(settings.user_id, book)
    store.reindex()
    assert store.list_category_items(settings.user_id, book) == before
    bob = dataclasses.replace(settings, user_id="bob")
    async with Client(build_server(bob, store)) as client:
        assert "결과 없음" in _text(await client.call_tool("category_search", {"query": "물고기"}))
