"""코드 점검 후속 A(2026-10-09): '바로 할 수 있는 것' 항목별 시험. 항목 번호는 docs/audit/2026-10-09-code-audit.md."""

from __future__ import annotations

import pytest
from mcp import Client

from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
RANGE = "장 번호는 0~9,999입니다(0은 서장)."


# ---- 15-2 읽기 도구의 장 번호 범위 ----

async def test_read_tools_check_chapter_range(store: LocalStore, settings: Settings):
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "본문", "x", title="하나")
    async with Client(build_server(settings, store)) as c:
        for name, args in [("book_read_chapter", {"number": 2**63}), ("book_read_chapter", {"number": -1}),
                           ("book_issues", {"chapter_number": 2**63}), ("ref_check", {"chapter_number": 10_000}),
                           ("book_issue_add", {"text": "x", "chapter_number": 2**63})]:
            r = await c.call_tool(name, {**args, "project_id": "b"})
            assert r.is_error and RANGE in r.content[0].text, (name, r.content[0].text)
        ok = await c.call_tool("book_read_chapter", {"number": 1, "project_id": "b"})
        assert not ok.is_error
    assert store.read_chapter("alice", "b", 2**63) is None and store.list_issues("alice", "b", None, chapter_number=2**63) == []
