"""6단계: style_add / style_search. tags 스키마 검증, reason + tags만 검색 대상."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from mcp import Client

from magus.balthasar.style import search_text, validate_tags
from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio

TAGS = {"호흡": "짧고 끊김", "시점": "1인칭", "열기": "장면", "장치": ["반복", "대구"], "어미": "-다 체", "톤": "건조함"}


def _text(result) -> str:
    assert not result.is_error, result.content[0].text
    return "".join(block.text for block in result.content)


def test_validate_tags():
    assert validate_tags({**TAGS, "호흡": "  짧고   끊김 "})["호흡"] == "짧고 끊김"
    assert validate_tags({**TAGS, "장치": []})["장치"] == []
    with pytest.raises(ValueError, match="없는 키: \\['톤'\\]"):
        validate_tags({k: v for k, v in TAGS.items() if k != "톤"})
    with pytest.raises(ValueError, match="모르는 키: \\['리듬'\\]"):
        validate_tags({**TAGS, "리듬": "빠름"})
    with pytest.raises(ValueError, match="장치"):
        validate_tags({**TAGS, "장치": "반복"})
    with pytest.raises(ValueError, match="시점"):
        validate_tags({**TAGS, "시점": " "})


def test_search_text_excludes_passage():
    assert search_text("장면으로 바로 들어가서 좋다", TAGS) == (
        "장면으로 바로 들어가서 좋다\n호흡: 짧고 끊김 / 시점: 1인칭 / 열기: 장면 / 장치: 반복, 대구 / 어미: -다 체 / 톤: 건조함"
    )


async def test_style_add_and_search_by_style_not_topic(settings: Settings, store: LocalStore, data_dir: Path):
    async with Client(build_server(settings, store)) as client:
        added = _text(
            await client.call_tool(
                "style_add",
                {
                    "passage": "고래는 돌아갔다. 물이 고래를 불렀다. 고래는 대답했다.",
                    "reason": "문장이 짧아 숨이 가쁘고, 같은 주어의 반복이 리듬을 만든다",
                    "tags": TAGS,
                    "work": "합성 산문",
                },
            )
        )
        assert added.startswith("기록함 ") and "장치: 반복, 대구" in added
        await client.call_tool(
            "style_add",
            {
                "passage": "그 여름의 물가에는 아무도 없었고, 나는 오래도록 바람이 지나간 자리를 바라보았다.",
                "reason": "길게 이어지는 회상의 문장이 느린 호흡을 만든다",
                "tags": {"호흡": "길고 느림", "시점": "1인칭 회상", "열기": "풍경", "장치": ["열거"], "어미": "-었다", "톤": "서정적"},
            },
        )
        hit = _text(await client.call_tool("style_search", {"query": "짧은 문장 반복 리듬"}))
        assert hit.splitlines()[1].endswith("· 합성 산문") and "구절: “고래는 돌아갔다." in hit and "태그: 호흡: 짧고 끊김" in hit
        assert "길게 이어지는" in _text(await client.call_tool("style_search", {"query": "느린 호흡 서정"}))
        # 구절에만 있는 주제어(고래·물가)로는 찾히지 않는다: 색인 대상이 reason + tags이기 때문
        assert "결과 없음" in _text(await client.call_tool("style_search", {"query": "고래"}))
        assert "결과 없음" in _text(await client.call_tool("style_search", {"query": "물가 바람"}))

        assert (await client.call_tool("style_add", {"passage": "a", "reason": "b", "tags": {**TAGS, "리듬": "x"}})).is_error
        missing = {k: v for k, v in TAGS.items() if k != "어미"}
        assert (await client.call_tool("style_add", {"passage": "a", "reason": "b", "tags": missing})).is_error
        assert (await client.call_tool("style_add", {"passage": "a", "reason": " ", "tags": TAGS})).is_error

    assert len(list((data_dir / "users/alice/shelf/balthasar").glob("*.json"))) == 2
    before = store.list_styles(settings.user_id)
    store.reindex()
    assert store.list_styles(settings.user_id) == before
    bob = dataclasses.replace(settings, user_id="bob")
    async with Client(build_server(bob, store)) as client:
        assert "결과 없음" in _text(await client.call_tool("style_search", {"query": "짧은 문장"}))


async def test_all_instruction_rules_active(settings: Settings, store: LocalStore):
    from tests.test_instructions import SPEC

    async with Client(build_server(settings, store)) as client:
        assert client.instructions == SPEC  # 도구가 모두 등록되면 6절 원문 그대로
