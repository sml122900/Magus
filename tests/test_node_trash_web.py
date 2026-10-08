"""노드 삭제 웹 화면(#97 2): 노드를 고르면 🗑, 화면 안의 작은 확인 창(confirm() 아님), 휴지통 화면에서 되살리기. 다른 사용자는 못 한다."""

from __future__ import annotations

import re

import httpx2
from test_node_trash import _hashes, _seed
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.store import LocalStore


def test_delete_dialog_trash_page_and_restore(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    ids = _seed(store)
    store.create_project("alice", "강과 사람", project_id="river")
    link = store.add_link_node("alice", "river", "common", ids["case"])
    store.close()
    root = data_dir / "users" / "alice"
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get(f"/login?next=/shelf/p/book?node={ids['walk']}").text
        csrf = _csrf(page)
        assert '<summary aria-label="노드 휴지통으로" title="노드 휴지통으로">🗑</summary>' in page and "confirm(" not in page
        assert "노드 「답사」와 책 3권·글 4개를 휴지통으로 옮길까요?" in page and '<button class="primary">옮기기</button>' in page
        assert '<a class="btn" href="/shelf/p/book/trash">휴지통</a>' in page
        assert "🗑" not in c.get("/shelf/p/book", params={"node": "center"}).text.split('id="pp-node"')[1].split("</aside>")[0]
        refs = c.get("/shelf/p/book", params={"node": ids["refs"]}).text
        assert "문헌 글이 든 책 「읽은 논문」이 있어 지울 수 없습니다." in refs
        linked = c.get("/shelf/p/common", params={"node": ids["case"]}).text.split('id="pp-node"')[1]
        assert "「강과 사람」에서 연결하고 있어 지울 수 없습니다." in linked and "옮기기</button>" not in linked.split("</details>")[0]
        link_page = c.get("/shelf/p/river", params={"node": link.id}).text
        assert "연결 노드 「사례」를 휴지통으로 옮길까요? 원본 노드와 그 책·글은 그대로 남습니다." in link_page
        assert "장날" in c.get("/shelf", params={"q": "장날"}).text
        before = _hashes(root)
        gone = c.post("/shelf/p/book/map", data={"csrf": csrf, "action": "trash", "node": ids["walk"]})
        assert "노드를 휴지통으로 옮겼습니다." in gone.text and f'data-node="{ids["walk"]}"' not in gone.text
        assert "<p>「장날」 없음</p>" in c.get("/shelf", params={"q": "장날"}).text  # 검색에서 빠진다
        assert c.get(f"/shelf/{ids['notes']}").status_code == 404
        trash = c.get("/shelf/p/book/trash").text
        assert "노드 「답사」 · 책 3권" in trash and re.search(r'<time datetime="[^"]+">\d{4}-\d\d-\d\d \d\d:\d\d</time>', trash)
        assert c.post("/shelf/p/book/trash", data={"csrf": "틀림", "node": f"book/{ids['walk']}"}).status_code == 403
        back = c.post("/shelf/p/book/trash", data={"csrf": csrf, "node": f"book/{ids['walk']}"})
        assert "되살렸습니다." in back.text and f"node={ids['walk']}" in str(back.url) and "노드 「답사」와 책 3권" in back.text
        assert '<p class="empty">휴지통이 비었습니다.</p>' in c.get("/shelf/p/book/trash").text
        assert _hashes(root) == before  # 삭제 → 되살리기 왕복 뒤 파일이 같다
        # 연결 노드를 지우면 연결 노드만, 원본은 그대로
        c.post("/shelf/p/river/map", data={"csrf": csrf, "action": "trash", "node": link.id})
        assert "사례" in c.get("/shelf/p/common", params={"node": ids["case"]}).text
        assert "연결 노드" in c.get("/shelf/p/river/trash").text
        # 막힌 노드는 서버에서도 막는다
        blocked = c.post("/shelf/p/book/map", data={"csrf": csrf, "action": "trash", "node": ids["refs"]})
        assert "문헌 글이 든 책 「읽은 논문」이 있어 지울 수 없습니다." in blocked.text
        assert c.post("/shelf/p/book/map", data={"csrf": csrf, "action": "trash", "node": "center"}).status_code == 200
        assert LocalStore(data_dir).get_map("alice", "book").node("center") is not None


def test_other_user_cannot_delete_or_restore(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    ids = _seed(store, "alice")
    _seed(store, "bob")
    store.trash_node_with_books("alice", "book", ids["walk"], "앨리스가 옮김")
    store.restore_trash("alice", "node", f"book/{ids['walk']}")
    other = store.add_node("alice", "book", "치울 노드")
    store.trash_node_with_books("alice", "book", other.id, "앨리스 휴지통")
    store.close()
    before = _hashes(data_dir / "users" / "alice")
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        csrf = _csrf(bob.get("/shelf").text)
        tried = bob.post("/shelf/p/book/map", data={"csrf": csrf, "action": "trash", "node": ids["walk"]})
        assert tried.status_code == 303 and "maperr=" in tried.headers["location"]  # 밥의 지도에는 그 노드가 없다
        assert "치울 노드" not in bob.get("/shelf/p/book/trash").text
        restored = bob.post("/shelf/p/book/trash", data={"csrf": csrf, "node": f"book/{other.id}"})
        assert restored.status_code == 303 and "err=" in restored.headers["location"]
        assert bob.post("/shelf/p/book/trash", data={"csrf": csrf, "node": "../alice/x"}).status_code == 303
    assert _hashes(data_dir / "users" / "alice") == before
