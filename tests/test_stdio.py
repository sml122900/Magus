"""Claude Desktop과 같은 경로: 하위 프로세스 + stdio + 한글."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from magus.book.demo import seed_demo
from magus.store import LocalStore

pytestmark = pytest.mark.anyio


async def test_stdio_subprocess(data_dir: Path):
    store = LocalStore(data_dir)
    seed_demo(store, "alice")
    store.close()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "magus", "serve"],
        env={**os.environ, "USER_ID": "alice", "DATA_DIR": str(data_dir), "EMBEDDINGS": "none"},
    )
    async with Client(params) as client:
        assert client.server_info.name == "Magus"
        result = await client.call_tool("book_outline", {})
        text = "".join(block.text for block in result.content)
        assert text.startswith("# 데모: 물에서 뭍으로")
        assert "물가의 망설임" in text
