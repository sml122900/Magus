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
