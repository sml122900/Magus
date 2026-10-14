"""「내 서재」를 보통 프로젝트로(2026-10-11 묶음 4, docs/decisions/2026-10-11-batch.md).

새 사용자는 프로젝트 0개로 시작한다(「내 서재」를 자동으로 만들지 않는다). 기존 「내 서재」는 이름 그대로 보통 프로젝트다:
목록에서 최근 수정 순, 휴지통으로 옮기고 되살릴 수 있고, 프로젝트 수에 함께 센다. 프로젝트를 말하지 않으면 「내 서재」로 넣지 않는다."""

from __future__ import annotations

import re

import httpx2
import pytest
from mcp import Client

from conftest import make_book, with_library
from magus.book.outline import build_outline
from magus.category.rules import RESERVED_KEYS, name_key
from magus.config import Settings
from magus.floors import COMMON, MAX_FLOORS
from magus.server import build_server
from magus.store import LocalStore
from test_web import server_proc  # noqa: F401  (픽스처)

START = "'+ 프로젝트'로 먼저 만들어 주세요"
pytestmark = pytest.mark.anyio


def _text(result) -> str:
    return result.content[0].text


async def test_new_user_starts_with_no_projects(settings: Settings, store: LocalStore):
    assert store.list_floors("alice") == [] and store.get_map("alice", COMMON) is None
    assert START in build_outline(store, "alice")
    async with Client(build_server(settings, store)) as c:
        assert START in _text(await c.call_tool("category_list", {}))
        assert not (await c.call_tool("category_list", {})).is_error  # 오류가 아니라 안내
        made = await c.call_tool("category_create", {"name": "메모"})
        assert made.is_error and START in _text(made)
        bib = await c.call_tool("ref_import_bibliography", {"text": "Clack, J. A. (2012). Gaining ground. Press."})
        assert bib.is_error and START in _text(bib)
        assert (await c.call_tool("category_create", {"name": "메모", "project": "내 서재"})).is_error  # 없는 프로젝트
        await c.call_tool("book_import", {"title": "첫 책"})
        put = _text(await c.call_tool("category_create", {"name": "메모"}))
        assert "「첫 책」" in put  # 프로젝트가 하나면 그것
    assert [f.title for f in store.list_floors("alice")] == ["첫 책"]
    assert not (store.root / "users" / "alice" / "shelf" / "maps" / "common.json").exists()  # 쓰는 일 뒤에도 「내 서재」는 생기지 않는다


async def test_existing_library_is_an_ordinary_project(settings: Settings, store: LocalStore):
    make_book(store, "alice", "읽을 것")  # 「내 서재」의 책(옛 사용자)
    store.create_project("alice", "도시", project_id="city")
    floors = store.list_floors("alice")
    assert [(f.id, f.title) for f in floors] == [(COMMON, "내 서재"), ("city", "도시")]
    async with Client(build_server(settings, store)) as c:
        listed = _text(await c.call_tool("category_list", {}))
        assert listed.startswith("책장: 프로젝트 2개(「내 서재」(common) · 「도시」(city))") and "## 「내 서재」(common) · 올린 문서 없음" in listed
        ask = await c.call_tool("category_create", {"name": "둘째"})  # 「내 서재」도 하나로 센다: 둘이면 묻는다
        assert ask.is_error and "프로젝트가 2개라" in _text(ask)
        assert "「내 서재」" in _text(await c.call_tool("category_create", {"name": "둘째", "project": "내 서재"}))  # 이름으로 고른다
        assert (await c.call_tool("category_create", {"name": "셋째", "project": "공용"})).is_error  # 옛 별명은 받지 않는다
        outline = _text(await c.call_tool("book_outline", {"project_id": COMMON}))
        assert outline == "「내 서재」에는 올린 문서가 없습니다."
    # 휴지통으로 옮기고 되살린다(다른 프로젝트가 연결 중이 아니면)
    info = store.project_trash_info("alice", COMMON)
    assert info is not None and info.blocked is None and info.books == 2
    trash_id = store.trash_project("alice", COMMON, "시험")
    assert [f.id for f in store.list_floors("alice")] == ["city"] and store.get_map("alice", COMMON) is None
    assert store.restore_project("alice", trash_id) == COMMON
    assert [f.id for f in store.list_floors("alice")] == [COMMON, "city"]
    assert sorted(c.name for c in store.list_categories("alice", floors=[COMMON])) == ["둘째", "읽을 것"]


def test_library_counts_toward_the_project_limit(store: LocalStore):
    with_library(store, "alice")
    for n in range(MAX_FLOORS - 1):
        store.create_project("alice", f"책 {n}", project_id=f"p{n}")
    try:
        store.create_project("alice", "하나 더", project_id="over")
    except ValueError as e:
        assert f"{MAX_FLOORS}개까지" in str(e)
    else:
        raise AssertionError("「내 서재」까지 세면 가득이다")


def test_library_name_is_free_for_books():
    assert name_key("내 서재") not in RESERVED_KEYS  # 용어집 이름이 아니게 됐다(2026-10-11)


def test_web_empty_list_and_library_like_others(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        empty = c.get("/login?next=/shelf").text
        assert 'aria-label="시작 순서"' in empty and "<h2>+ 프로젝트</h2>" in empty  # 빈 목록은 시작 순서(2026-10-14)
        assert "내 서재" not in empty and 'aria-label="모든 프로젝트에서 찾기"' not in empty  # 빈 목록에는 찾기 칸도 없다
        assert c.get("/shelf/p/common").status_code == 404
        assert c.get("/shelf/new").url.path == "/shelf"  # 프로젝트 없이 책을 만들지 않는다
    setup = LocalStore(data_dir)
    make_book(setup, "alice", "읽을 것")
    setup.create_project("alice", "도시", project_id="city")
    setup.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        listed = c.get("/login?next=/shelf").text
        assert "<li class=done><b>프로젝트 만들기</b>" in listed and 'class="pcard library"' not in listed  # 문서 전이라 순서는 남는다
        assert re.findall(r'<span class="pname">([^<]+)</span>', listed)[0] == "도시"  # 최근 수정 순(「내 서재」를 끝에 두지 않는다)
        page = c.get("/shelf/p/common").text
        assert "프로젝트 휴지통으로" in page and "🗑" in page  # 휴지통으로 옮기는 단추가 있다
