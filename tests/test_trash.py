"""휴지통(#88 생각·문체 → #96 모든 책의 글)과 태그를 누가 정했는지(#89).

지우지 않고 trash/shelf/로 옮긴다. 검색·목록·웹 화면·reindex에서 빠지고, 운영자 CLI로 되살린다. 사용자마다 따로다.
글을 옮기면 그 글에 응답한 글(parent_id)도 함께 간다(옛 생각 휴지통과 같다).
"""

from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_web import server_proc  # noqa: F401 - 픽스처

from magus import cli
from magus.config import Settings
from magus.search import hybrid_search
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

pytestmark = pytest.mark.anyio

ME, AI, OTHER = "20261005141301887-3e167c", "20261005141301888-aaaaaa", "20261005141301889-bbbbbb"
STYLE = "20261005180731312-380da3"
IDEAS, STYLES = "ideas-common", "styles-common"


def _seed(store: LocalStore, user: str = "alice") -> None:
    store.create_category(user, "생각", "blank", "#1f2f5c", (), "common", category_id=IDEAS)
    store.create_category(user, "문체", "blank", "#6e1f2f", (), "common", category_id=STYLES)
    for item in (CategoryItem(ME, IDEAS, "바다는 모든 생명이 돌아가는 곳", "me"),
                 CategoryItem(AI, IDEAS, "바다 비유는 3부에 어울립니다", "ai", parent_id=ME),
                 CategoryItem(OTHER, IDEAS, "도시는 만남의 밀도", "me")):
        store.put_category_item(user, item)
    store.put_category_item(user, CategoryItem(STYLE, STYLES, "짧다. 끊긴다.", "me", tags=("호흡: 짧음",), reason="짧은 호흡",
                                               tags_by="ai"))


def _found(store: LocalStore, user: str, query: str) -> set[str]:
    return {c.owner_id.split("/")[-1] for c in hybrid_search(store, user, query, ["category"], 10)}


def test_trash_moves_files_and_restore_brings_them_back(store: LocalStore, data_dir: Path):
    _seed(store)
    moved = store.trash_item_with_replies("alice", IDEAS, ME, "시험 메모")
    assert [i.id for i in moved] == [ME, AI]  # 응답한 AI 글도 함께
    assert {i.id for i in store.list_category_items("alice", IDEAS)} == {OTHER}
    assert _found(store, "alice", "바다") == set()
    trash = data_dir / "users" / "alice" / "trash" / "shelf" / "category-items" / IDEAS
    assert sorted(p.stem for p in trash.glob("*.json")) == sorted([ME, AI])  # 지우지 않고 옮겼다
    assert not (data_dir / "users" / "alice" / "shelf" / "categories" / IDEAS / "items" / f"{ME}.json").exists()
    items = {t.id: t for t in store.list_trash("alice")}
    assert items[f"{IDEAS}/{ME}"].note == "시험 메모" and items[f"{IDEAS}/{AI}"].with_id == ME
    assert items[f"{IDEAS}/{ME}"].preview.startswith("바다는")
    store.reindex()  # 인덱스를 파일에서 다시 만들어도 휴지통의 글은 돌아오지 않는다
    assert {i.id for i in store.list_category_items("alice", IDEAS)} == {OTHER}
    assert store.restore_trash("alice", "category_item", f"{IDEAS}/{ME}") == [f"{IDEAS}/{ME}", f"{IDEAS}/{AI}"]
    assert {i.id for i in store.list_category_items("alice", IDEAS)} == {ME, AI, OTHER} and store.list_trash("alice") == []
    assert _found(store, "alice", "바다") == {ME, AI}
    with pytest.raises(ValueError):
        store.restore_trash("alice", "category_item", f"{IDEAS}/{ME}")

    entry = store.trash_category_item("alice", STYLES, STYLE, "")
    assert entry is not None and entry.tags_by == "ai" and store.list_category_items("alice", STYLES) == []
    assert _found(store, "alice", "짧은 호흡") == set()
    store.restore_trash("alice", "category_item", f"{STYLES}/{STYLE}")
    store.reindex()
    assert [s.tags_by for s in store.list_category_items("alice", STYLES)] == ["ai"]  # 누가 태그를 정했는지는 파일에 남는다
    assert store.trash_item_with_replies("alice", IDEAS, "20260101000000000-ffffff", "") == []
    assert store.trash_category_item("alice", STYLES, OTHER, "") is None
    for bad in ("../alice", "a/b"):
        with pytest.raises(ValueError):
            store.trash_category_item("alice", IDEAS, bad, "")


def test_trash_is_per_user(store: LocalStore, data_dir: Path):
    _seed(store, "alice")
    _seed(store, "bob")  # 같은 id
    assert store.trash_item_with_replies("bob", IDEAS, ME, "") and store.trash_category_item("bob", STYLES, STYLE, "")
    assert {i.id for i in store.list_category_items("alice", IDEAS)} == {ME, AI, OTHER}
    assert len(store.list_category_items("alice", STYLES)) == 1
    assert store.list_trash("alice") == [] and len(store.list_trash("bob")) == 3
    with pytest.raises(ValueError):
        store.restore_trash("alice", "category_item", f"{IDEAS}/{ME}")  # 밥의 휴지통은 앨리스가 되살리지 못한다


async def test_delete_tools_and_tags_by(settings: Settings, store: LocalStore):
    _seed(store, settings.user_id)
    _seed(store, "bob")
    async with Client(build_server(settings, store)) as c:
        # 글 지우기는 category_trash 하나(#94·#96)
        done = (await c.call_tool("category_trash", {"book": "생각", "item_id": ME, "note": "시험"})).content[0].text
        assert done.startswith(f"휴지통으로 옮김: 「생각」의 글 {ME}") and "이 글에 응답한 글 1개도 함께" in done
        assert "결과 없음" in (await c.call_tool("category_search", {"query": "바다"})).content[0].text
        missing = await c.call_tool("category_trash", {"book": "생각", "item_id": ME, "note": "x"})
        assert missing.is_error and "없다" in missing.content[0].text
        await c.call_tool("category_put", {"book": "문체", "author": "me", "content": "끊는다", "reason": "끊어 읽힘",
                                           "tags": ["호흡: 끊김"], "untitled": True})
        found = (await c.call_tool("category_search", {"query": "호흡"})).content[0].text
        assert "태그: 호흡: 짧음 (AI가 뽑음)" in found and "태그: 호흡: 끊김\n" in found + "\n"
        gone = (await c.call_tool("category_trash", {"book": "문체", "item_id": STYLE, "note": "시험"})).content[0].text
        assert gone.startswith(f"휴지통으로 옮김: 「문체」의 글 {STYLE}")
        descriptions = {t.name: t.description for t in (await c.list_tools()).tools}
    for gone_tool in ("idea_delete", "style_delete", "idea_add", "style_add", "ref_add", "idea_search", "style_search", "ref_search"):
        assert gone_tool not in descriptions  # #94·#96: 합쳤다
    assert descriptions["category_trash"].startswith("저자가 그 글·책·노드를 지우라고 분명히 말했을 때만 부른다. "
                                                     "여러 개면 목록을 보여 주고 확인받는다.")
    assert descriptions["category_put"].startswith("글 넣기. 저자가 그 책에 넣으라고 분명히 말했을 때만 부른다. "
                                                   "넣을 책이 대화에서 분명하지 않으면 부르지 말고 책 이름과 컨텍스트를 보여 주며 묻는다")
    assert descriptions["book_write_chapter"].startswith("저자가 'Magus의 올린 문서에 저장'하라고 분명히 말했을 때만 부른다. 넣을 곳을 되묻는 선택지에도 올린 문서를 넣지 않는다.")
    assert {i.id for i in store.list_category_items("bob", IDEAS)} == {ME, AI, OTHER}  # 밥의 같은 id는 그대로
    assert len(store.list_category_items("bob", STYLES)) == 1


def test_operator_cli_puts_lists_and_restores(data_dir: Path, monkeypatch, capsys):
    store = LocalStore(data_dir)
    _seed(store, "default")
    store.close()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("USER_ID", "default")
    monkeypatch.setenv("EMBEDDINGS", "none")
    cli.main(["trash", "put", "category-item", f"{IDEAS}/{ME}", "--note", "예전 시험 메모"])
    out = capsys.readouterr().out
    assert f"휴지통으로 옮김(default): category-item {IDEAS}/{ME}, {IDEAS}/{AI}" in out and "휴지통(default) 2개" in out
    assert "예전 시험 메모" in out
    cli.main(["trash", "restore", "category-item", f"{IDEAS}/{ME}"])
    assert "휴지통(default) 0개" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["trash", "put", "category-item", f"{IDEAS}/20260101000000000-ffffff"])


def test_web_hides_trash_and_shows_who_chose_tags(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/ideas")
        store = LocalStore(data_dir)
        _seed(store, "alice")
        store.put_category_item("alice", CategoryItem("20261005180731313-cccccc", STYLES, "끊는다", "me", tags=("호흡: 끊김",),
                                                      reason="끊어 읽힘", tags_by="author"))
        store.put_category_item("alice", CategoryItem("20261005180731314-dddddd", STYLES, "예전 것", "me", tags=("톤: 건조",),
                                                      reason="기록 전"))
        store.trash_item_with_replies("alice", IDEAS, OTHER, "")
        store.close()
        ideas = c.get("/ideas").text  # 예전 주소 → 이전으로 생긴 책
        styles = c.get("/styles").text
    assert "바다는 모든" in ideas and "도시는 만남의 밀도" not in ideas
    # 누가 태그를 정했나는 파일에 그대로 있고(#89), 게시판에는 제목·본문·첨부만 보인다(#97)
    assert "AI가 뽑은 태그" not in styles and "저자가 정한 태그" not in styles and "끊는다" in styles
    store = LocalStore(data_dir)
    assert store.get_category_item("alice", STYLES, "20261005180731313-cccccc").tags_by == "author"
    store.close()
