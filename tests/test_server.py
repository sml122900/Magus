from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from mcp import Client

from magus.book.demo import seed_demo
from magus.book.tools import FRONT_MATTER_WARNING
from magus.config import Settings
from magus.instructions import build_instructions, required_tools
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    assert not result.is_error, result
    return "".join(block.text for block in result.content)


async def _call(client: Client, name: str, args: dict) -> dict:
    return json.loads(_text(await client.call_tool(name, args)))


async def test_server_identity_and_tools(settings: Settings, store: LocalStore):
    async with Client(build_server(settings, store)) as client:
        assert client.server_info.name == "Magus"
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"book_outline", "book_read_chapter", "book_write_chapter", "book_issues"} <= names
        tools = {t.name: t for t in (await client.list_tools()).tools}
        for name in ("book_read_chapter", "book_write_chapter"):
            assert "null은 아직 검사 전" in tools[name].description and "[]는 검사했고" in tools[name].description
        assert tools["book_write_chapter"].input_schema["properties"]["status"]["anyOf"][0]["enum"] == [
            "draft", "revising", "done",
        ]
        # instructions는 등록된 도구로 조립되고, 등록되지 않은 도구를 언급하지 않는다.
        assert client.instructions == build_instructions(names)
        assert required_tools(client.instructions) <= names


async def test_book_outline_tool(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    async with Client(build_server(settings, store)) as client:
        result = await client.call_tool("book_outline", {})
        assert result.structured_content is None  # 텍스트만 돌려준다(중복 없이)
        text = _text(result)
        assert text.startswith("프로젝트: 데모: 물에서 뭍으로 (demo)")
        assert _text(await client.call_tool("book_outline", {"project_id": "demo"})) == text


async def test_read_returns_body_and_meta_separately(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    async with Client(build_server(settings, store)) as client:
        ch = await _call(client, "book_read_chapter", {"number": 2})
        assert ch["content"] == "아가미덮개가 사라지고 목이 생겼다. Clack(2012)은 이 변화를 길게 다룬다.\n\n목은 머리를 돌리는 자유였다."
        assert "---" not in ch["content"] and "version:" not in ch["content"]
        assert (ch["title"], ch["status"], ch["part_number"], ch["version"]) == ("목이 생긴 날", "draft", 1, 2)
        assert ch["last_note"] == "2장 끝에 한 문장 추가"
        # 4단계부터 인용 게이트가 돈다: 데모 책장에는 refs가 없으므로 Clack(2012)은 unknown
        assert ch["unverified_cites"] == [
            {"key": "clack2012", "count": 1, "cited_as": ["Clack(2012)"], "paragraphs": [1], "status": "unknown"}
        ]
        assert ch["label"] == "제2장"
        assert ch["needs_source"] == 0
        assert (await _call(client, "book_read_chapter", {"number": 1}))["open_issues"] == ["I1 Daeschler 2006 원문 확인 필요"]
        missing = await client.call_tool("book_read_chapter", {"number": 99})
        assert missing.is_error and "있는 장: 1, 2, 3, 4, 5" in missing.content[0].text


async def test_read_then_write_same_body_only_bumps_version(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    async with Client(build_server(settings, store)) as client:
        before = await _call(client, "book_read_chapter", {"number": 2})
        written = await _call(
            client, "book_write_chapter", {"number": 2, "content": before["content"], "note": "그대로 저장"}
        )
        assert written["warnings"] == [] and written["version"] == 3 and written["archived_version"] == 2
        after = await _call(client, "book_read_chapter", {"number": 2})
        assert after["content"] == before["content"]
        assert after["version"] == before["version"] + 1
        for key in ("title", "status", "part_number", "char_count"):
            assert after[key] == before[key]
        assert after["last_note"] == "그대로 저장"


async def test_write_with_front_matter_keeps_server_meta(settings: Settings, store: LocalStore, data_dir: Path):
    seed_demo(store, settings.user_id)
    injected = "---\ntitle: 바꿔치기\nstatus: done\nversion: 99\npart_number: 7\n---\n\n새 본문"
    async with Client(build_server(settings, store)) as client:
        written = await _call(client, "book_write_chapter", {"number": 3, "content": injected, "note": "메타 주입"})
        assert written["warnings"] == [FRONT_MATTER_WARNING]
        after = await _call(client, "book_read_chapter", {"number": 3})
        assert after["content"] == "새 본문"
        assert (after["title"], after["status"], after["part_number"], after["version"]) == ("숨의 경제학", "draft", 1, 2)
    raw = (data_dir / "users/alice/projects/demo/book/ch-03.md").read_text(encoding="utf-8")
    assert raw.count("---") == 2 and "바꿔치기" not in raw


async def test_write_creates_new_chapter_with_title(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    async with Client(build_server(settings, store)) as client:
        written = await _call(
            client, "book_write_chapter", {"number": 6, "content": "새 장 본문", "note": "신규", "title": "다시 물로"}
        )
        assert (written["title"], written["version"], written["archived_version"]) == ("다시 물로", 1, None)
        assert "- 제6장 다시 물로 · draft" in _text(await client.call_tool("book_outline", {}))
        empty = await client.call_tool("book_write_chapter", {"number": 6, "content": "---\ntitle: x\n---\n", "note": "빈"})
        assert empty.is_error


async def test_write_rejects_unknown_status(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    async with Client(build_server(settings, store)) as client:
        bad = await client.call_tool("book_write_chapter", {"number": 1, "content": "본문", "note": "x", "status": "final"})
        assert bad.is_error
        ok = await _call(client, "book_write_chapter", {"number": 1, "content": "본문", "note": "x", "status": "revising"})
        assert ok["status"] == "revising"


async def test_book_issues_lists_and_filters(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    store.add_issue(settings.user_id, "demo", "에이전트가 남긴 것", origin="agent", chapter_number=3)
    async with Client(build_server(settings, store)) as client:
        def issues(args: dict) -> str:  # 첫 줄은 그 원고의 컨텍스트(#96), 그 아래가 목록
            return client.call_tool("book_issues", args)

        first = _text(await issues({}))
        assert first.splitlines()[0].startswith("컨텍스트")
        everything = first.split("\n", 1)[1]
        assert everything.splitlines()[0] == "확인 요청 4건 (status=open)"
        assert "- I1 · open · 1장 · 문서 코멘트 · citation→daeschler2006 ⇒ refs 없음 · Daeschler 2006 원문 확인 필요" in everything
        comments = _text(await issues({"origin": "import_comment"})).split("\n", 1)[1]
        assert comments.splitlines()[0] == "확인 요청 1건 (status=open, origin=import_comment)"
        ch3 = _text(await issues({"chapter_number": 3, "kind": "general"})).split("\n", 1)[1]
        assert [line.split(" · ")[0] for line in ch3.splitlines()[1:]] == ["- I2", "- I4"]
        limited = _text(await issues({"limit": 2})).split("\n", 1)[1]
        assert "앞 2건만 표시" in limited and len(limited.splitlines()) == 3
        assert _text(await issues({"status": "closed"})).split("\n", 1)[1] == "확인 요청 0건 (status=closed)"
        assert (await client.call_tool("book_issues", {"origin": "robot"})).is_error


async def test_other_user_gets_empty_result(settings: Settings, store: LocalStore):
    seed_demo(store, settings.user_id)
    bob = dataclasses.replace(settings, user_id="bob")
    async with Client(build_server(bob, store)) as client:
        assert "프로젝트가 없습니다" in _text(await client.call_tool("book_outline", {}))
        assert "없습니다" in _text(await client.call_tool("book_outline", {"project_id": "demo"}))
        assert (await client.call_tool("book_read_chapter", {"number": 1})).is_error
        assert (await client.call_tool("book_read_chapter", {"number": 1, "project_id": "demo"})).is_error
        assert (await client.call_tool("book_write_chapter", {"number": 1, "content": "x", "note": "y", "project_id": "demo"})).is_error
        assert (await client.call_tool("book_issues", {"project_id": "demo"})).is_error


async def test_ref_add_updates_outline_count_immediately(settings: Settings, store: LocalStore):
    # 장별 미확인 key는 파생값 캐시다. 원문 확인 글로 넣어 verified가 되면 곧바로 다시 계산돼야 한다(사용자 결정 #43, #96).
    from magus.melchior.bibliography import import_bibliography
    from magus.melchior.check import refresh_cite_counts

    p = store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", p.id, 1, "Clack(2012)와 (Hu et al., 2023)", "x")
    store.write_chapter("alice", p.id, 2, "Clack(2012) 다시.", "x")
    import_bibliography(store, "alice", "Clack, J. A. (2012). Gaining ground. Press.\nHu, W. (2023). Bottleneck. Science.")
    refresh_cite_counts(store, "alice")
    async with Client(build_server(settings, store)) as client:
        assert "미확인 문헌 2편" in _text(await client.call_tool("book_outline", {}))
        await client.call_tool("category_put", {"book": "참고문헌", "author": "me", "source": {"key": "clack2012"}, "checked": True,
                                                "parts": [{"text": "네발동물", "reason": "1장"}]})
        outline = _text(await client.call_tool("book_outline", {}))
    assert "미확인 문헌 1편" in outline
    toc = [line for line in outline.splitlines() if line.startswith("- 제")]
    assert toc[0].endswith("미확인인용 1") and toc[1].endswith("미확인인용 0")  # hu2023만 남음 / 2장은 0
