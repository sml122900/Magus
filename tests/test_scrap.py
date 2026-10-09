"""스크랩(별표, 2026-10-09, #99-3).

- 저장: 글 파일·bib.json에 표시 하나("scrap": true, 끄면 키를 뺀다). 고친 시각(updated_at)은 그대로. 색인 칸(scrap)으로 거른다.
  휴지통 왕복·다시 색인·대화로 고치기(category_put item_id)·참고문헌 다시 들이기(put_ref)에도 남는다.
- 웹: 게시판 줄 오른쪽·글 보기 머리의 ☆ → ★(새로고침 없이 JSON, 스크립트가 없으면 폼으로 돌아옴), '★ 스크랩만'(?scrap=1)·개수.
- MCP: 도구 수 그대로. category_search(scrap_only), category_edit(scrap, item_id), 결과에 ★, category_list에 스크랩 수.
- 격리: 다른 사용자의 글은 스크랩·해제하지 못한다."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_node_trash import _hashes, _seed
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, LocalStore, Ref

FIRST = "20261009000000000-aaaaaa"  # 「장날 메모」의 첫 글(첨부 장터.png)
SECOND = "20261009000000001-aaaaaa"


def _item_file(data_dir: Path, book: str, item: str, user: str = "alice") -> Path:
    return data_dir / "users" / user / "shelf" / "categories" / book / "items" / f"{item}.json"


def test_store_scrap_is_one_mark_and_survives(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    notes = ids["notes"]
    path = _item_file(data_dir, notes, FIRST)
    before = json.loads(path.read_text(encoding="utf-8"))
    assert store.set_scrap("alice", f"{notes}/{FIRST}", True) is True
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after == {**before, "scrap": True}  # 표시 하나만(고친 시각도 그대로)
    assert store.get_category_item("alice", notes, FIRST).scrap
    # 대화로 고쳐도(put_category_item) 남는다
    item = store.get_category_item("alice", notes, FIRST)
    store.put_category_item("alice", CategoryItem(FIRST, notes, "대화로 고침", "me", reason=item.reason, scrap=item.scrap))
    assert json.loads(path.read_text(encoding="utf-8"))["scrap"] is True
    # 휴지통 왕복·다시 색인
    store.trash_item_with_replies("alice", notes, FIRST, "x")
    store.restore_trash("alice", "category_item", f"{notes}/{FIRST}")
    store.reindex()
    assert store.get_category_item("alice", notes, FIRST).scrap
    # 끄면 키를 뺀다
    store.set_scrap("alice", f"{notes}/{FIRST}", False)
    assert "scrap" not in json.loads(path.read_text(encoding="utf-8")) and not store.get_category_item("alice", notes, FIRST).scrap
    # 문헌 글: bib.json에 표시 하나, 참고문헌을 다시 들여도(put_ref) 그대로, 원문 확인 표시·인용 수는 그대로
    bib = data_dir / "users" / "alice" / "shelf" / "melchior" / "clack2012" / "bib.json"
    counts = [(c.number, c.unverified_cite_count) for c in store.list_chapters("alice", "book")]
    old = json.loads(bib.read_text(encoding="utf-8"))
    store.set_scrap("alice", "ref:clack2012", True)
    assert json.loads(bib.read_text(encoding="utf-8")) == {**old, "scrap": True}
    ref = store.get_ref("alice", "clack2012")
    store.put_ref("alice", Ref(key=ref.key, status=ref.status, bib=ref.bib, book=ref.book))
    assert store.get_ref("alice", "clack2012").scrap and store.get_ref("alice", "clack2012").status == "verified"
    assert [(c.number, c.unverified_cite_count) for c in store.list_chapters("alice", "book")] == counts
    with pytest.raises(ValueError):
        store.set_scrap("alice", f"{notes}/없는-글", True)


def test_web_star_toggle_filter_and_count(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    ids = _seed(store)
    notes = ids["notes"]
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        board = c.get(f"/login?next=/shelf/{notes}").text
        csrf = _csrf(board)
        assert board.count('aria-label="스크랩" title="스크랩">☆</button>') == 3 and 'aria-pressed="false"' in board
        assert f'<a class="scrap-only" href="/shelf/{notes}?scrap=1" aria-current="false">' in board
        assert '<span class="n" data-scrap-count>0</span>' in board
        # 스크립트(fetch)가 부르면 JSON
        on = c.post(f"/shelf/{notes}/{FIRST}/scrap", data={"csrf": csrf, "on": "1"}, headers={"Accept": "application/json"})
        assert on.status_code == 200 and on.json() == {"scrap": True, "count": 1}
        # 스크립트가 없으면 폼 → next로 돌아온다(바깥 주소로는 가지 않는다)
        back = c.post(f"/shelf/{notes}/{SECOND}/scrap", data={"csrf": csrf, "on": "1", "next": f"/shelf/{notes}?page=1"})
        assert str(back.url).endswith(f"/shelf/{notes}?page=1")
        away = c.post(f"/shelf/{notes}/{SECOND}/scrap", data={"csrf": csrf, "on": "1", "next": "https://evil.example/"},
                      follow_redirects=False)
        assert away.headers["location"] == f"/shelf/{notes}"
        assert c.post(f"/shelf/{notes}/{FIRST}/scrap", data={"csrf": "틀림", "on": "0"}).status_code == 403
        # 스크랩만: 개수, 찾기와 함께
        only = c.get(f"/shelf/{notes}?scrap=1").text
        assert only.count('<li><a class="post"') == 2 and '<span class="n" data-scrap-count>2</span>' in only
        assert 'aria-current="true"' in only and f'href="/shelf/{notes}"' in only  # 다시 누르면 끈다
        both = c.get(f"/shelf/{notes}", params={"q": "물안개", "scrap": "1"}).text
        assert both.count('<li><a class="post"') == 1 and "물안개" in both
        none = c.get(f"/shelf/{notes}", params={"q": "나루", "scrap": "1"}).text
        assert '<p class="msg">없음</p>' in none and '<li><a class="post"' not in none
        assert '<p class="empty">스크랩한 글이 없습니다.</p>' in c.get("/shelf/" + ids["photos"] + "?scrap=1").text
        # 글 보기 머리의 ★
        view = c.get(f"/shelf/{notes}/{FIRST}").text
        assert '<div class="post-head"><form class="star head"' in view and 'aria-pressed="true"' in view
        off = c.post(f"/shelf/{notes}/{FIRST}/scrap", data={"csrf": csrf, "on": "0"}, headers={"Accept": "application/json"})
        assert off.json() == {"scrap": False, "count": 1}
        # 문헌 글도
        refs_book = next(x for x in LocalStore(data_dir).list_categories("alice") if x.name == "읽은 논문").id
        ref = c.post(f"/shelf/{refs_book}/clack2012/scrap", data={"csrf": csrf, "on": "1"}, headers={"Accept": "application/json"})
        assert ref.json() == {"scrap": True, "count": 1}
    record = json.loads(_item_file(data_dir, notes, SECOND).read_text(encoding="utf-8"))
    assert record["scrap"] is True and "scrap" not in json.loads(_item_file(data_dir, notes, FIRST).read_text(encoding="utf-8"))


def test_other_user_cannot_scrap(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    ids = _seed(store, "alice")
    mine = _seed(store, "bob")
    refs_book = next(x for x in store.list_categories("alice") if x.name == "읽은 논문").id
    store.close()
    before = _hashes(data_dir / "users" / "alice")
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        csrf = _csrf(bob.get("/shelf").text)
        for path in (f"/shelf/{ids['notes']}/{FIRST}/scrap", f"/shelf/{refs_book}/clack2012/scrap"):
            assert bob.post(path, data={"csrf": csrf, "on": "1"}, headers={"Accept": "application/json"}).status_code == 404
        own = bob.post(f"/shelf/{mine['notes']}/{FIRST}/scrap", data={"csrf": csrf, "on": "1"}, headers={"Accept": "application/json"})
        assert own.json()["scrap"] is True
    assert _hashes(data_dir / "users" / "alice") == before


@pytest.mark.anyio
async def test_mcp_scrap_only_and_edit(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    notes = ids["notes"]
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        def text(r) -> str:
            return r.content[0].text

        assert "스크랩(★)한 글이 없다" in text(await c.call_tool("category_search", {"scrap_only": True}))
        assert "검색어가 비었다" in text(await c.call_tool("category_search", {"query": "   "}))
        done = text(await c.call_tool("category_edit", {"item_id": FIRST, "scrap": True}))
        assert "스크랩(★)했다" in done and "「장날 메모」의 글 “장터”" in done  # 제목 없는 글은 첫 첨부 이름(#99-2)
        again = text(await c.call_tool("category_edit", {"item_id": FIRST, "scrap": True}))
        assert "이미 붙어 있다" in again
        text(await c.call_tool("category_edit", {"item_id": "clack2012", "scrap": True}))
        listed = text(await c.call_tool("category_search", {"scrap_only": True}))
        assert "2건" in listed and listed.count("★스크랩") == 2 and FIRST in listed and "clack2012" in listed
        found = text(await c.call_tool("category_search", {"query": "장날", "scrap_only": True}))
        assert FIRST in found and SECOND not in found
        everyone = text(await c.call_tool("category_search", {"query": "장날"}))
        assert FIRST in everyone and SECOND in everyone and everyone.count("★스크랩") == 1
        assert "스크랩(★)한 글 2개" in text(await c.call_tool("category_list", {}))
        missing = await c.call_tool("category_edit", {"item_id": "없는-글", "scrap": True})
        assert missing.is_error
        off = text(await c.call_tool("category_edit", {"book": "장날 메모", "item_id": FIRST, "scrap": False}))
        assert "스크랩(★)을 뗐다" in off
    assert not store.get_category_item("alice", notes, FIRST).scrap and store.get_ref("alice", "clack2012").scrap
