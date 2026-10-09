"""작은 화면 고침(2026-10-09 구조·버그 점검 6·7·9·12번): 장 상태 한국어, 휴지통 목록, 스크랩 초점, 작은 것."""

from __future__ import annotations

import httpx2
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.store import LocalStore


def test_chapter_status_names(server_proc):  # noqa: F811
    """장 상태는 한국어(초안·고치는 중·완성). 모두 초안이면 상태 칸을 숨긴다."""
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    for pid in ("a", "b"):
        store.create_project("alice", f"책 {pid}", project_id=pid)
        store.write_chapter("alice", pid, 1, "첫 장 본문", "x", title="하나")
        store.write_chapter("alice", pid, 2, "둘째 장 본문", "x", title="둘")
    store.write_chapter("alice", "b", 1, "첫 장 본문 고침", "x", status="revising")
    store.write_chapter("alice", "b", 2, "둘째 장 본문 고침", "x", status="done")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        c.get("/login?next=/shelf")
        mixed = c.get("/shelf/book/b").text
        assert "<th>상태</th>" in mixed and "<td>고치는 중</td>" in mixed and "<td>완성</td>" in mixed
        assert "revising" not in mixed.split("<main>")[1] and ">done<" not in mixed
        drafts = c.get("/shelf/book/a").text
        assert "<th>상태</th>" not in drafts and "draft" not in drafts.split("<main>")[1]


def test_trash_list_counts_links_and_earlier_posts(server_proc):  # noqa: F811
    """휴지통 목록: 머리에 N개, 연결 노드는 「원본 이름」, 노드 아래 안에 있던 것 한 줄, 먼저 버린 글은 따로(노드를 되살린 뒤 되살린다)."""
    import re  # noqa: PLC0415

    from test_web import _csrf  # noqa: PLC0415

    from magus.category.moves import add_link, trash_node_with_books  # noqa: PLC0415
    from magus.store import CategoryItem  # noqa: PLC0415

    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    store.create_project("alice", "도시의 책", project_id="city")
    store.create_project("alice", "강의 책", project_id="river")
    node = store.add_node("alice", "city", "현장")
    store.create_category("alice", "답사", "blank", "#1f2f5c", (), "city", node.id, category_id="walk")
    store.put_category_item("alice", CategoryItem("20261009000000001-aaaaaa", "walk", "먼저 버린 글", "me"))
    store.put_category_item("alice", CategoryItem("20261009000000002-aaaaaa", "walk", "남은 글", "me"))
    store.trash_category_item("alice", "walk", "20261009000000001-aaaaaa", "먼저")
    trash_node_with_books(store, "alice", "city", node.id, "노드째")
    link = add_link(store, "alice", "city", "river", "center")
    trash_node_with_books(store, "alice", "city", link.id, "연결 노드")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        page = c.get("/login?next=/shelf/p/city/trash").text
        csrf = _csrf(page)
        assert '<p class="trash-count">3개</p>' in page
        assert "<b>노드 「현장」</b>" in page and '<small class="trash-sub">책 1권·글 1개·먼저 버린 글 1개</small>' in page
        assert "<b>연결 노드 「강의 책」</b>" in page
        row = re.search(r"<li>[^<]*<time[^>]*>[^<]*</time> <b>글 「먼저 버린 글」 · 책 「답사」</b>(.*?)</li>", page).group(1)
        assert "<button>" not in row and "노드 「현장」과 함께 휴지통에 있는 책의 글입니다." in row
        node_ref = re.search(r'name="node" value="(city/[^"]+)"', page.split("노드 「현장」")[0].rsplit("<li>", 1)[1] + page.split("노드 「현장」")[1]).group(1)
        c.post("/shelf/p/city/trash", data={"csrf": csrf, "node": node_ref})
        after = c.get("/shelf/p/city/trash").text
        assert '<p class="trash-count">2개</p>' in after and 'name="item" value="walk/20261009000000001-aaaaaa"' in after
        back = c.post("/shelf/p/city/trash", data={"csrf": csrf, "item": "walk/20261009000000001-aaaaaa"})
        assert "먼저 버린 글" in back.text and back.url.path == "/shelf/walk/20261009000000001-aaaaaa"
