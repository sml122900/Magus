"""4단계: ref_add / ref_search / ref_check + 쓰기 게이트, citation 이슈 ↔ refs 연결. 완료 기준 포함."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from mcp import Client

from magus.book.importer import import_manuscript
from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore
from magus.synthetic import build_manuscript_docx

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    assert not result.is_error, result.content[0].text
    return "".join(block.text for block in result.content)


async def _json(client: Client, name: str, args: dict) -> dict:
    return json.loads(_text(await client.call_tool(name, args)))


def _keys(group: list[dict]) -> set[str]:
    return {g["key"] for g in group}


@pytest.fixture
def imported(store: LocalStore, settings: Settings, tmp_path: Path) -> LocalStore:
    import_manuscript(store, settings.user_id, build_manuscript_docx(tmp_path / "m.docx"), project_id="synth")
    return store


async def test_completion_criteria_ref_check_and_promotion(settings: Settings, imported: LocalStore):
    async with Client(build_server(settings, imported)) as client:
        before = await _json(client, "ref_check", {"chapter_number": 1})
        # 완료 기준: ref_check(1장)에 daeschler2006, clack2012가 unverified 또는 unknown
        not_verified = _keys(before["unverified"]) | _keys(before["unknown"])
        assert {"daeschler2006", "clack2012"} <= not_verified
        # 괄호 안 다중 인용(Clack, 2012; Hu et al., 2023)과 조사 붙은 저자(갤러는(2022))도 잡고 aliases로 해석한다
        clack = next(g for g in before["unverified"] if g["key"] == "clack2012")
        assert clack["count"] == 2
        assert {g["key"] for g in before["unverified"]} >= {"galor2022", "henrich2016", "hu2023"}
        assert next(g for g in before["unverified"] if g["key"] == "galor2022")["count"] == 2  # 갤러는(2022) + 갤러(2022)
        assert before["unknown"] == [] and before["verified"] == []

        added = _text(
            await client.call_tool(
                "ref_add",
                {
                    "bib": {"key": "daeschler2006"},
                    "passages": [{"text": "Tiktaalik roseae는 물고기와 네발동물 사이의 형질을 함께 지닌다.", "reason": "1장 첫 장면의 근거", "locator": "p.757"}],
                },
            )
        )
        assert added.startswith("daeschler2006: unverified → verified · 발췌 1건 추가(총 1건)")
        assert "synth: 1장" in added
        # 완료 기준: ref_add 뒤 ref_check를 다시 돌리면 verified로 옮겨 간다
        after = await _json(client, "ref_check", {"chapter_number": 1})
        assert "daeschler2006" in _keys(after["verified"]) and "daeschler2006" not in _keys(after["unverified"])


async def test_write_gate_reports_and_counts(settings: Settings, imported: LocalStore):
    async with Client(build_server(settings, imported)) as client:
        written = await _json(
            client,
            "book_write_chapter",
            {"number": 7, "content": "닿으려는 것은 종의 본성이다(Nobody, 2020). Clack(2012)도 그렇다. [출처 필요: 본성 주장]", "note": "인용 추가"},
        )
        assert {(c["key"], c["status"]) for c in written["unverified_cites"]} == {("nobody2020", "unknown"), ("clack2012", "unverified")}
        assert written["needs_source"] == 1
        outline = _text(await client.call_tool("book_outline", {}))
        assert "- 제7장 닿으려는 종 · draft" in outline and "미확인인용 2" in outline.split("- 제7장")[1].splitlines()[0]
        read = await _json(client, "book_read_chapter", {"number": 7})
        assert read["unverified_cites"] == written["unverified_cites"]
        clean = await _json(client, "book_write_chapter", {"number": 7, "content": "인용 없는 문단.", "note": "정리"})
        assert clean["unverified_cites"] == [] and clean["needs_source"] == 0  # [] = 검사했고 없음


async def test_citation_issues_link_to_refs(settings: Settings, imported: LocalStore):
    issues = {i.text.split("\n")[0]: i for i in imported.list_issues(settings.user_id, "synth", None, kind="citation")}
    assert issues["확인 필요"].ref_id == "daeschler2006"
    assert issues["원문 대조 필요"].ref_key == "갤러2022"  # 조사를 뗀 key
    assert issues["원문 대조 필요"].ref_id == "galor2022"  # aliases로 해석
    assert issues["Diamond 1997 확인 필요"].ref_id == "diamond1997"
    assert "물고기가 일어서지 못하는 장면 보강" not in issues  # "서지" 오탐 보강 → general
    async with Client(build_server(settings, imported)) as client:
        listed = _text(await client.call_tool("book_issues", {"kind": "citation", "project_id": "synth"}))
        assert "citation→갤러2022 ⇒ galor2022" in listed


async def test_ref_add_new_with_fulltext_and_search(settings: Settings, imported: LocalStore, tmp_path: Path):
    # 전문 파일은 받은함 이름으로 가리킨다(원격 모드와 같다)
    imported.put_inbox(
        settings.user_id, "zimmer.txt",
        "고래의 조상은 뭍에서 다시 물로 돌아갔다.\n\n파키케투스는 귀뼈의 모양으로 고래 계통임을 드러낸다.\n\n"
        "물가의 포유류는 수백만 년에 걸쳐 다리를 잃었다.".encode(),
    )
    async with Client(build_server(settings, imported)) as client:
        added = _text(
            await client.call_tool(
                "ref_add",
                {
                    "bib": {"authors": "Zimmer, C.", "year": "1998", "title": "At the water's edge"},
                    "passages": [{"text": "고래의 조상은 뭍에서 다시 물로 돌아갔다.", "reason": "6장 도입"}],
                    "file_path": "zimmer.txt",
                    "aliases": ["짐머1998"],
                },
            )
        )
        assert added.startswith("zimmer1998: unverified → verified") and "전문 있음" in added
        assert imported.get_ref(settings.user_id, "zimmer1998").file_path == "inbox/zimmer.txt"
        found = _text(await client.call_tool("ref_search", {"query": "고래 조상 물로", "scope": "both"}))
        lines = found.splitlines()
        assert lines[1].startswith("1. zimmer1998 (verified)") and lines[1].endswith("[발췌]")
        assert "이유: 6장 도입" in found
        assert "[전문 · 발췌되지 않은 부분]" in found and "ref_add로 이 구절을 발췌에 추가" in found
        picked_only = _text(await client.call_tool("ref_search", {"query": "파키케투스 귀뼈", "scope": "picked"}))
        assert "결과 없음" in picked_only
        full_only = _text(await client.call_tool("ref_search", {"query": "파키케투스 귀뼈", "scope": "full"}))
        assert "파키케투스" in full_only
        # 2글자 한글 이름도 찾는다(bigram)
        assert "zimmer1998" in _text(await client.call_tool("ref_search", {"query": "고래"}))


async def test_ref_add_validation(settings: Settings, imported: LocalStore):
    async with Client(build_server(settings, imported)) as client:
        assert (await client.call_tool("ref_add", {"bib": {"key": "clack2012"}, "passages": []})).is_error
        assert (await client.call_tool("ref_add", {"bib": {"title": "연도 없음"}, "passages": [{"text": "a", "reason": "b"}]})).is_error
        assert (await client.call_tool("ref_add", {"bib": {"key": "clack2012"}, "passages": [{"text": "a", "reason": " "}]})).is_error


async def test_refs_are_user_scoped(settings: Settings, imported: LocalStore):
    bob = dataclasses.replace(settings, user_id="bob")
    async with Client(build_server(bob, imported)) as client:
        assert "결과 없음" in _text(await client.call_tool("ref_search", {"query": "Clack"}))
        assert (await client.call_tool("ref_check", {"chapter_number": 1, "project_id": "synth"})).is_error
    assert imported.list_refs("bob") == []
