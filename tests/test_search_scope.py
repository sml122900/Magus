"""대화 검색 범위(2026-10-09, #100-1): category_search가 문헌 글의 서지·key·한글 표기·첨부 이름도 찾는다(웹 찾기와 같게).
결과에는 원문 확인 상태(원문 확인 전이면 '미확인')와 쓸 부분이 보인다. 인용 규칙(instructions 2)은 그대로 — 찾기는 넓게, 인용은 좁게."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore, Passage, Ref

pytestmark = pytest.mark.anyio


def _seed(store: LocalStore) -> str:
    book = store.create_category("alice", "읽은 논문", "blank", "#1f2f5c", (), "common").id
    store.put_ref("alice", Ref(key="galor2022", status="verified", bib={"authors": "Galor, O.", "year": 2022, "title": "The journey of humanity"},
                               aliases=("갤러2022",), book=book), passages=[Passage("인류의 여정은 성장의 역사다", "핵심 주장", "12쪽")])
    store.put_ref("alice", Ref(key="smith1776", status="unverified", bib={"authors": "Smith, A.", "year": 1776, "title": "The wealth of nations"},
                               book=book))
    store.put_attachment("alice", "ref:smith1776", "wealth_scan_ch1.pdf", b"%PDF-1.4 x")
    return book


async def _search(data_dir: Path, store: LocalStore, query: str) -> str:
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        return (await c.call_tool("category_search", {"query": query})).content[0].text


@pytest.mark.parametrize(("query", "key"), [("Galor", "galor2022"), ("2022", "galor2022"), ("galor2022", "galor2022"),
                                            ("갤러", "galor2022"), ("journey", "galor2022"), ("Smith", "smith1776"),
                                            ("1776", "smith1776"), ("wealth_scan", "smith1776"), ("smi", "smith1776")])
async def test_sources_found_by_bibliography_key_and_file_name(store: LocalStore, data_dir: Path, query: str, key: str):
    _seed(store)
    found = await _search(data_dir, store, query)
    assert f"{key} · 문헌 글" in found


async def test_result_shows_check_state_and_picked_parts(store: LocalStore, data_dir: Path):
    _seed(store)
    smith = await _search(data_dir, store, "Smith")
    assert "smith1776 · 문헌 글 · 미확인(원문 확인 전 — 인용하지 않는다)" in smith and "쓸 부분 없음" in smith
    assert "첨부 1개: wealth_scan_ch1.pdf" in smith
    galor = await _search(data_dir, store, "Galor")
    assert "galor2022 · 문헌 글 · 원문 확인 · " in galor and "쓸 부분 “인류의 여정은 성장의 역사다” · 12쪽" in galor
    assert galor.count("galor2022 · 문헌 글") == 1  # 서지와 쓸 부분이 함께 맞아도 한 번
    assert "인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다" in galor
