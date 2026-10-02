"""Claude Desktop과 같은 경로: 하위 프로세스 + stdio + 한글. 단계마다 새 도구를 여기서 한 번씩 부른다."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from magus.book.demo import seed_demo
from magus.store import LocalStore
from magus.synthetic import build_manuscript_docx

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    assert not result.is_error, result.content[0].text if result.content else result
    return "".join(block.text for block in result.content)


async def test_stdio_subprocess(data_dir: Path, tmp_path: Path):
    store = LocalStore(data_dir)
    seed_demo(store, "alice")
    store.close()
    manuscript = build_manuscript_docx(tmp_path / "닿으려는_종_합성.docx")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "magus", "serve"],
        env={**os.environ, "USER_ID": "alice", "DATA_DIR": str(data_dir), "EMBEDDINGS": "none"},
    )
    async with Client(params) as client:
        assert client.server_info.name == "Magus"
        outline = _text(await client.call_tool("book_outline", {}))
        assert outline.startswith("프로젝트: 데모: 물에서 뭍으로 (demo)")
        assert "물가의 망설임" in outline

        # 2단계
        imported = _text(await client.call_tool("book_import", {"path": str(manuscript), "project_id": "synth"}))
        assert "장 7개 · 부 3개" in imported and "| ch-04.md | 닿으려는 손 | 2 |" in imported
        bib = _text(await client.call_tool("ref_import_bibliography", {"text": "Zimmer, C. (1998). At the water's edge. Free Press."}))
        assert "이미 있음 1건" in bib

        # 3단계
        assert _text(await client.call_tool("book_decide", {"text": "결정", "project_id": "synth"})).startswith("D1")
        assert _text(await client.call_tool("book_issue_add", {"text": "열린 문제", "project_id": "synth"})).startswith("I14")
        assert _text(await client.call_tool("book_issue_close", {"id": "I14", "project_id": "synth"})) == "I14 닫음"
        exported = _text(await client.call_tool("book_export", {"project_id": "synth"}))
        assert Path(exported.splitlines()[0].removeprefix("docx를 만들었다: ")).exists()

        # 4단계
        checked = _text(await client.call_tool("ref_check", {"chapter_number": 1, "project_id": "synth"}))
        assert '"daeschler2006"' in checked
        added = _text(await client.call_tool("ref_add", {"bib": {"key": "clack2012"}, "passages": [{"text": "네발동물의 기원", "reason": "1장"}]}))
        assert added.startswith("clack2012: unverified → verified")
        assert "clack2012 (verified)" in _text(await client.call_tool("ref_search", {"query": "네발동물"}))

        # 5단계
        convo = _text(await client.call_tool("idea_add_conversation", {"markdown": "**사용자:** 고래는 돌아갔다\n**Claude:** 맞습니다"}))
        assert convo.startswith("me 1건, ai 1건")
        assert _text(await client.call_tool("idea_add", {"text": "물가의 망설임", "kind": "thought"})).startswith("기록함 [me]")
        assert "[me]" in _text(await client.call_tool("idea_search", {"query": "고래"}))

