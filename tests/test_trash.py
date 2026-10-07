"""생각·문체 휴지통(#88)과 문체 태그를 누가 정했는지(#89).

지우지 않고 trash/shelf/로 옮긴다. 검색·목록·웹 화면·reindex에서 빠지고, 운영자 CLI로 되살린다. 사용자마다 따로다.
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
from magus.store import Idea, LocalStore, StyleEntry

pytestmark = pytest.mark.anyio

TAGS = {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": [], "어미": "-다", "톤": "건조"}
ME, AI, OTHER = "20261005141301887-3e167c", "20261005141301888-aaaaaa", "20261005141301889-bbbbbb"


def _seed(store: LocalStore, user: str = "alice") -> None:
    store.add_ideas(user, [
        Idea(ME, "바다는 모든 생명이 돌아가는 곳", "thought", "me"),
        Idea(AI, "바다 비유는 3부에 어울립니다", "conversation", "ai", None, ME),
        Idea(OTHER, "도시는 만남의 밀도", "thought", "me"),
    ])
    store.add_style(user, StyleEntry("20261005180731312-380da3", "짧다. 끊긴다.", "짧은 호흡", TAGS, tags_by="ai"))


def _found(store: LocalStore, user: str, query: str, lanes) -> set[str]:
    return {c.owner_id for c in hybrid_search(store, user, query, lanes, 10)}


def test_trash_moves_files_and_restore_brings_them_back(store: LocalStore, data_dir: Path):
    _seed(store)
    moved = store.trash_idea("alice", ME, "시험 메모")
    assert [i.id for i in moved] == [ME, AI]  # 응답한 AI 발화도 함께
    assert {i.id for i in store.list_ideas("alice")} == {OTHER}
    assert _found(store, "alice", "바다", ["idea_me", "idea_ai"]) == set()
    trash = data_dir / "users" / "alice" / "trash" / "shelf" / "casper"
    assert sorted(p.stem for p in trash.glob("*.json")) == sorted([ME, AI])  # 지우지 않고 옮겼다
    assert not (data_dir / "users" / "alice" / "shelf" / "casper" / f"{ME}.json").exists()
    items = {t.id: t for t in store.list_trash("alice")}
    assert items[ME].note == "시험 메모" and items[AI].with_id == ME and items[ME].preview.startswith("바다는")
    store.reindex()  # 인덱스를 파일에서 다시 만들어도 휴지통 항목은 돌아오지 않는다
    assert {i.id for i in store.list_ideas("alice")} == {OTHER}
    assert store.restore_trash("alice", "idea", ME) == [ME, AI]
    assert {i.id for i in store.list_ideas("alice")} == {ME, AI, OTHER} and store.list_trash("alice") == []
    assert _found(store, "alice", "바다", ["idea_me"]) == {ME}
    with pytest.raises(ValueError):
        store.restore_trash("alice", "idea", ME)

    entry = store.trash_style("alice", "20261005180731312-380da3", "")
    assert entry is not None and entry.tags_by == "ai" and store.list_styles("alice") == []
    assert _found(store, "alice", "짧은 호흡", ["style"]) == set()
    store.restore_trash("alice", "style", "20261005180731312-380da3")
    store.reindex()
    assert [s.tags_by for s in store.list_styles("alice")] == ["ai"]  # 누가 태그를 정했는지는 파일에 남는다
    assert store.trash_idea("alice", "20260101000000000-ffffff", "") == [] and store.trash_style("alice", OTHER, "") is None
    for bad in ("../alice", "a/b"):
        with pytest.raises(ValueError):
            store.trash_idea("alice", bad, "")


def test_trash_is_per_user(store: LocalStore, data_dir: Path):
    _seed(store, "alice")
    _seed(store, "bob")  # 같은 id
    assert store.trash_idea("bob", ME, "") and store.trash_style("bob", "20261005180731312-380da3", "")
    assert {i.id for i in store.list_ideas("alice")} == {ME, AI, OTHER} and len(store.list_styles("alice")) == 1
    assert store.list_trash("alice") == [] and len(store.list_trash("bob")) == 3
    with pytest.raises(ValueError):
        store.restore_trash("alice", "idea", ME)  # 밥의 휴지통은 앨리스가 되살리지 못한다


async def test_delete_tools_and_tags_by(settings: Settings, store: LocalStore):
    _seed(store, settings.user_id)
    _seed(store, "bob")
    async with Client(build_server(settings, store)) as c:
        # 생각·문체 지우기는 category_trash로 합쳤다(#94: idea_delete·style_delete 없앰)
        done = (await c.call_tool("category_trash", {"category": "생각", "item_id": ME, "note": "시험"})).content[0].text
        assert done.startswith(f"휴지통으로 옮김: 생각 {ME}") and "AI 발화 1건도 함께" in done
        assert "결과 없음" in (await c.call_tool("idea_search", {"query": "바다", "author": "all"})).content[0].text
        missing = await c.call_tool("category_trash", {"category": "생각", "item_id": ME, "note": "x"})
        assert missing.is_error and "없다" in missing.content[0].text
        added = (await c.call_tool("style_add", {"passage": "길게 이어진다", "reason": "(저자가 이유를 밝히지 않음)", "tags": TAGS})).content[0].text
        assert added.startswith("문체에 기록함 ") and added.endswith("(태그는 AI가 뽑음)")
        await c.call_tool("style_add", {"passage": "끊는다", "reason": "끊어 읽힘", "tags": TAGS, "tags_by": "author"})
        found = (await c.call_tool("style_search", {"query": "짧음"})).content[0].text
        assert "(태그는 AI가 뽑음)" in found and "(태그는 저자가 정함)" in found
        gone = (await c.call_tool("category_trash", {"category": "문체", "item_id": "20261005180731312-380da3", "note": "시험"})).content[0].text
        assert gone.startswith("휴지통으로 옮김: 문체 20261005180731312-380da3")
        descriptions = {t.name: t.description for t in (await c.list_tools()).tools}
    assert "idea_delete" not in descriptions and "style_delete" not in descriptions
    assert descriptions["category_trash"].startswith("저자가 그 항목(또는 저자가 만든 카테고리)을 지우라고 분명히 말했을 때만 부른다. "
                                                     "여러 개면 목록을 보여 주고 확인받는다.")
    for name, place in (("idea_add", "생각"), ("style_add", "문체"), ("ref_add", "문헌")):
        assert descriptions[name].startswith(f"저자가 '{place}'에 넣으라고 분명히 말했을 때만 부른다. '저장해 줘'처럼 넣을 곳이 정해지지 않았으면 부르지 말고")
        assert "생각·문체·문헌과 저자의 카테고리(category_list) 중 어디인지 먼저 묻는다(원고는 선택지에 넣지 않는다)." in descriptions[name]  # #90·#92
    assert descriptions["book_write_chapter"].startswith("저자가 'Magus 원고에 저장'하라고 분명히 말했을 때만 부른다. 넣을 곳을 되묻는 선택지에도 원고를 넣지 않는다.")
    assert {i.id for i in store.list_ideas("bob")} == {ME, AI, OTHER}  # 밥의 같은 id는 그대로
    assert len(store.list_styles("bob")) == 1


def test_operator_cli_puts_lists_and_restores(data_dir: Path, monkeypatch, capsys):
    store = LocalStore(data_dir)
    _seed(store, "default")
    store.close()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("USER_ID", "default")
    monkeypatch.setenv("EMBEDDINGS", "none")
    cli.main(["trash", "put", "idea", ME, "--note", "예전 시험 메모"])
    out = capsys.readouterr().out
    assert f"휴지통으로 옮김(default): idea {ME}, {AI}" in out and "휴지통(default) 2개" in out and "예전 시험 메모" in out
    cli.main(["trash", "restore", "idea", ME])
    assert "휴지통(default) 0개" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["trash", "put", "idea", "20260101000000000-ffffff"])


def test_web_hides_trash_and_shows_who_chose_tags(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        c.get("/login?next=/ideas")
        store = LocalStore(data_dir)
        _seed(store, "alice")
        store.add_style("alice", StyleEntry("20261005180731313-cccccc", "끊는다", "끊어 읽힘", TAGS, tags_by="author"))
        store.add_style("alice", StyleEntry("20261005180731314-dddddd", "예전 것", "기록 전", TAGS))
        store.trash_idea("alice", OTHER, "")
        store.close()
        ideas = c.get("/ideas").text
        styles = c.get("/styles").text
    assert "바다는 모든" in ideas and "도시는 만남의 밀도" not in ideas
    assert styles.count('<p class="muted">AI가 뽑은 태그</p>') == 1 and styles.count('<p class="muted">저자가 정한 태그</p>') == 1
