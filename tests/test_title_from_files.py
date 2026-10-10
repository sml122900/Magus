"""제목 자동 채움(2026-10-09, #99-2).

- 웹 글쓰기·고치기: 저장할 때 제목이 비어 있고 첨부가 있으면 첫 첨부의 파일 이름(확장자 제외)을 제목으로 저장(누가 지었나 = 저자).
- 이미 저장된 제목 없는 글은 파일을 바꾸지 않고, 보일 때만(게시판 목록·글 보기·휴지통·검색 결과·MCP 결과·files_list) 같은 규칙.
- 대화(category_put)로 넣는 글은 제목 규칙(instructions) 그대로 — 자동으로 채우지 않는다."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.attachments import shown_title, title_from_files
from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

from conftest import with_library

OLD = "20261009000000000-aaaaaa"  # 제목 없이 저장된 옛 글(첨부만)


def test_rule():
    assert title_from_files(["장터  사진.JPG", "b.pdf"]) == "장터 사진"
    assert title_from_files([]) is None and shown_title("있는 제목", ["a.png"]) == "있는 제목"
    assert shown_title(None, ["보고서.final.docx"]) == "보고서.final" and shown_title(None, []) is None
    assert len(title_from_files(["가" * 120 + ".txt"]) or "") == 80


def _seed(data_dir: Path) -> str:
    store = LocalStore(data_dir)
    try:
        with_library(store, "alice")
        book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
        store.put_category_item("alice", CategoryItem(OLD, book, "", "me"))
        store.put_attachment("alice", f"{book}/{OLD}", "나루 지도.pdf", b"%PDF-1.4 x")
        return book
    finally:
        store.close()


def test_web_write_and_edit_fill_title_from_first_file(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    book = _seed(data_dir)
    old_file = data_dir / "users" / "alice" / "shelf" / "categories" / book / "items" / f"{OLD}.json"
    old_bytes = old_file.read_bytes()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        board = c.get(f"/login?next=/shelf/{book}").text
        csrf = _csrf(board)
        # 옛 글: 파일은 그대로, 보일 때만 첫 첨부 이름이 제목(흐린 본문 앞부분이 아니라 제목처럼)
        assert '<span class="pt">나루 지도</span>' in board
        view = c.get(f"/shelf/{book}/{OLD}").text
        assert "<h1>나루 지도</h1>" in view and "제목은 AI가 지음" not in view
        # 글쓰기: 제목 없이 첨부 → 첫 첨부 이름이 제목으로 저장
        made = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": " ", "content": "장날 사진들"},
                      files=[("files", ("장터 사진.jpg", b"\xff\xd8\xff x", "image/jpeg")), ("files", ("둘째.png", b"\x89PNG x", "image/png"))])
        assert "<h1>장터 사진</h1>" in made.text
        new_id = str(made.url).rsplit("/", 1)[1]
        # 제목도 첨부도 없으면 제목 없이(본문 앞부분이 보인다)
        plain = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": "", "content": "첨부 없는 글"})
        assert "<h1>첨부 없는 글</h1>" in plain.text
        plain_id = str(plain.url).rsplit("/", 1)[1]
        # 고치기: 제목을 지우고 첫 첨부를 빼면 남은 첫 첨부의 이름
        store = LocalStore(data_dir)
        first = store.list_attachments("alice", f"{book}/{new_id}")[0]
        store.close()
        edited = c.post(f"/shelf/{book}/{new_id}/edit", data={"csrf": csrf, "title": "", "content": "장날 사진들", "drop": first.id})
        assert "<h1>둘째</h1>" in edited.text
        # 고치기: 첨부가 없으면 제목은 비운 채
        c.post(f"/shelf/{book}/{plain_id}/edit", data={"csrf": csrf, "title": "", "content": "첨부 없는 글"})
    assert old_file.read_bytes() == old_bytes  # 이미 저장된 글은 보일 때만
    store = LocalStore(data_dir)
    made_item, plain_item = store.get_category_item("alice", book, new_id), store.get_category_item("alice", book, plain_id)
    assert (made_item.title, made_item.title_by) == ("둘째", "author")
    assert (plain_item.title, plain_item.title_by) == (None, None)
    store.close()
    record = json.loads((data_dir / "users" / "alice" / "shelf" / "categories" / book / "items" / f"{new_id}.json").read_text(encoding="utf-8"))
    assert record["title"] == "둘째" and record["author"] == "me"


@pytest.mark.anyio
async def test_mcp_results_show_file_title_without_writing(store: LocalStore, data_dir: Path):
    with_library(store, "alice")
    book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(OLD, book, "강가 장날 기록", "me"))
    store.put_attachment("alice", f"{book}/{OLD}", "나루 지도.docx", b"PK x")
    before = (data_dir / "users" / "alice" / "shelf" / "categories" / book / "items" / f"{OLD}.json").read_bytes()
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        found = (await c.call_tool("category_search", {"query": "장날"})).content[0].text
        assert "제목 「나루 지도」(첫 첨부의 파일 이름)" in found
        listed = (await c.call_tool("files_list", {})).content[0].text
        assert "「장날 메모」 책의 글 「나루 지도」" in listed
        # 대화로 넣는 글은 제목 규칙 그대로(자동으로 채우지 않는다)
        put = (await c.call_tool("category_put", {"book": "장날 메모", "author": "me", "content": "대화로 넣은 글", "untitled": True}))
        assert not put.is_error
    assert (data_dir / "users" / "alice" / "shelf" / "categories" / book / "items" / f"{OLD}.json").read_bytes() == before
    newest = [i for i in store.list_category_items("alice", book) if i.content == "대화로 넣은 글"]
    assert len(newest) == 1 and newest[0].title is None
