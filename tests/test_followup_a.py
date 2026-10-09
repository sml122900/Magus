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


# ---- 13-b 연결 노드 되살리기 뒤 인용 수 ----

def _unverified(store: LocalStore) -> int:
    import re

    from magus.book.outline import build_outline

    return int(re.search(r"미확인 문헌 (\d+)편", build_outline(store, "alice", "book")).group(1))


async def test_restoring_link_node_recounts(store: LocalStore, settings: Settings):
    from pathlib import Path

    from magus.book.importer import import_manuscript
    from magus.category.moves import restore_node, trash_node_with_books

    import_manuscript(store, "alice", Path(__file__).parent / "fixtures" / "synthetic" / "닿으려는_종_합성.docx", project_id="book",
                      synthetic=True)
    async with Client(build_server(settings, store)) as c:
        await c.call_tool("category_create", {"name": "읽은 논문", "project": "내 서재"})
        r = await c.call_tool("category_put", {"book": "읽은 논문", "project": "내 서재", "author": "me", "source": {"key": "clack2012"},
                                               "checked": True, "parts": [{"text": "네발동물 대목", "reason": "근거"}]})
        assert not r.is_error, r.content[0].text
    shared = _unverified(store)
    link = next(n for n in store.get_map("alice", "book").nodes if n.link)
    trash_node_with_books(store, "alice", "book", link.id, "시험")
    assert _unverified(store) == shared + 1  # 연결 노드가 없으면 clack2012가 이 원고에서 미확인으로
    restore_node(store, "alice", f"book/{link.id}")
    assert _unverified(store) == shared  # 전에는 다음 문헌 변경·재시작까지 shared + 1이 남았다
