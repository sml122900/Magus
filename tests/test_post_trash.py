"""글 지우기 = 노드와 같은 휴지통 방식(2026-10-09 사용자 요청 3). 웹의 원문 확인 체크는 없앴다(글 고치기는 되돌렸다: test_post_edit).

글 보기의 🗑 → 화면 안 확인 창(confirm() 쓰지 않음) → 그 글·응답한 글·첨부를 휴지통으로(지우지 않는다).
프로젝트의 휴지통 화면에 노드와 글이 함께 보이고, 되살리면 그대로 돌아온다(파일 해시 왕복).
문헌 글에는 🗑이 없고, 원문 확인 표시·쓸 부분·숨긴 칸은 파일에 그대로다. 다른 사용자의 글·휴지통에는 닿지 못한다."""

from __future__ import annotations

import re

import httpx2
from test_node_trash import _hashes, _seed
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.store import CategoryItem, LocalStore, Passage

FIRST = "20261009000000000-aaaaaa"  # 「장날 메모」의 첫 글(첨부 장터.png)
REPLY = "20261009000000005-cccccc"


def _setup(data_dir, user: str = "alice") -> dict[str, str]:
    store = LocalStore(data_dir)
    try:
        ids = _seed(store, user)
        store.put_category_item(user, CategoryItem(REPLY, ids["notes"], "AI의 답", "ai", parent_id=FIRST, origin="대화"))
        return ids
    finally:
        store.close()


def test_post_trash_dialog_trash_page_and_restore(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _setup(data_dir)
    notes, shelf = ids["notes"], LocalStore(data_dir)
    refs_book = next(c.id for c in shelf.list_categories("alice") if c.name == "읽은 논문")
    shelf.close()
    root = data_dir / "users" / "alice"
    before = _hashes(root)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        post = c.get(f"/login?next=/shelf/{notes}/{FIRST}").text
        csrf = _csrf(post)
        # 글 보기: 고치기·🗑과 화면 안 확인 창(응답한 글·첨부도 함께라고 알린다)
        assert '<details class="del"><summary><span aria-hidden="true">🗑</span> 휴지통으로</summary>' in post  # 글자를 붙여 누르기 쉽게
        assert "이 글을 휴지통으로 옮길까요? 응답한 글 1개·첨부 1개도 함께 옮깁니다." in post
        assert f'<form method="post" action="/shelf/{notes}/{FIRST}/trash">' in post and 'class="del-cancel"' in post
        assert f'<a class="act" href="/shelf/{notes}/{FIRST}/edit">' in post and "confirm(" not in post
        # 문헌 글: 🗑·체크 없음
        ref = c.get(f"/shelf/{refs_book}/clack2012").text
        assert 'class="del"' not in ref and "/check" not in ref and 'type="checkbox"' not in ref
        # 없앤 주소: 원문 확인 체크, 휴지통은 POST만
        assert c.post(f"/shelf/{refs_book}/clack2012/check", data={"csrf": csrf, "set": "1"}).status_code in (404, 405)
        assert c.get(f"/shelf/{notes}/{FIRST}/trash").status_code == 405
        assert c.post(f"/shelf/{notes}/{FIRST}/trash", data={"csrf": "틀림"}).status_code == 403
        assert c.post(f"/shelf/{refs_book}/clack2012/trash", data={"csrf": csrf}).status_code == 404  # 문헌 글은 옮기지 않는다
        # 옮기기 → 그 책의 게시판으로, 휴지통 링크
        gone = c.post(f"/shelf/{notes}/{FIRST}/trash", data={"csrf": csrf})
        assert str(gone.url).endswith(f"/shelf/{notes}?done=trashed")
        assert '<p class="msg">휴지통으로 옮겼습니다. <a href="/shelf/p/book/trash">휴지통</a></p>' in gone.text
        assert "강가 장날의 소금 장수" not in gone.text and "AI의 답" not in gone.text
        assert c.get(f"/shelf/{notes}/{FIRST}").status_code == 404 and c.get(f"/shelf/{notes}/{REPLY}").status_code == 404
        # 노드도 하나 지운다 → 휴지통 화면에 노드와 글이 함께(응답 글은 따로 보이지 않는다)
        c.post("/shelf/p/book/map", data={"csrf": csrf, "action": "trash", "node": ids["other"]})
        trash = c.get("/shelf/p/book/trash").text
        assert "노드 「강」" in trash and "글 「장터」 · 책 「장날 메모」 · 응답한 글 1개·첨부 1개 함께" in trash  # 제목 없는 글은 첫 첨부 이름(#99-2)
        assert trash.count("<button>되살리기</button>") == 2 and "AI의 답" not in trash
        assert "강가 장날" not in c.get("/shelf/p/common/trash").text  # 다른 프로젝트의 휴지통에는 없다
        wrong = c.post("/shelf/p/common/trash", data={"csrf": csrf, "item": f"{notes}/{FIRST}"}, follow_redirects=False)
        assert wrong.status_code == 303 and "err=missing" in wrong.headers["location"]
        # 되살리기: 글은 그 글 보기로(응답한 글·첨부도), 노드는 지도로
        back = c.post("/shelf/p/book/trash", data={"csrf": csrf, "item": f"{notes}/{FIRST}"})
        assert str(back.url).endswith(f"/shelf/{notes}/{FIRST}?done=restored") and '<p class="msg">되살렸습니다.</p>' in back.text
        assert 'alt="장터.png"' in back.text and "AI의 답" in c.get(f"/shelf/{notes}/{REPLY}").text
        c.post("/shelf/p/book/trash", data={"csrf": csrf, "node": f"book/{ids['other']}"})
        assert '<p class="empty">휴지통이 비었습니다.</p>' in c.get("/shelf/p/book/trash").text
    after = _hashes(root)
    assert {k: v for k, v in after.items() if not k.startswith("shelf/maps/")} == \
        {k: v for k, v in before.items() if not k.startswith("shelf/maps/")}  # 글·응답 글·첨부·문헌이 바이트까지 그대로
    store = LocalStore(data_dir)
    ref = store.get_ref("alice", "clack2012")
    assert ref.status == "verified" and store.get_passages("alice", "clack2012") == [Passage("네발동물이 뭍으로", "근거")]
    assert store.get_category_item("alice", notes, FIRST).reason == "이유는 파일에"  # 숨긴 칸은 파일에 그대로
    assert store.get_map("alice", "book").node(ids["other"]) is not None
    store.close()


def test_other_user_cannot_trash_or_restore_posts(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    ids = _setup(data_dir, "alice")
    mine = _setup(data_dir, "bob")  # 같은 글 id를 밥도 쓴다(책 id는 사람마다 다르다)
    store = LocalStore(data_dir)
    only = store.put_category_item("alice", CategoryItem("20261009000000007-eeeeee", ids["notes"], "앨리스만의 글", "me")).id
    store.trash_item_with_replies("alice", ids["notes"], "20261009000000001-aaaaaa", "앨리스가 옮김")
    store.close()
    alice_before = _hashes(data_dir / "users" / "alice")
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        csrf = _csrf(bob.get("/shelf").text)
        assert bob.post(f"/shelf/{ids['notes']}/{only}/trash", data={"csrf": csrf}).status_code == 404
        trash = bob.get("/shelf/p/book/trash").text
        assert "장날 아침의 물안개" not in trash and '<p class="empty">휴지통이 비었습니다.</p>' in trash
        tried = bob.post("/shelf/p/book/trash", data={"csrf": csrf, "item": f"{ids['notes']}/20261009000000001-aaaaaa"})
        assert tried.status_code == 303 and "err=missing" in tried.headers["location"]
        for item in ("../alice/x", f"{ids['notes']}/../../alice", "x/y"):
            assert bob.post("/shelf/p/book/trash", data={"csrf": csrf, "item": item}).status_code == 303
        own = bob.post(f"/shelf/{mine['notes']}/{FIRST}/trash", data={"csrf": csrf})  # 같은 글 id의 자기 글은 자기 것만 옮긴다
        assert own.status_code == 303
    assert _hashes(data_dir / "users" / "alice") == alice_before
    store = LocalStore(data_dir)
    assert store.get_category_item("alice", ids["notes"], FIRST) is not None and store.get_category_item("bob", mine["notes"], FIRST) is None
    assert re.fullmatch(r"\d{17}-[0-9a-f]{6}", only)
    store.close()
