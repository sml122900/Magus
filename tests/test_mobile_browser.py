"""휴대폰 폭(2026-10-09 구조·버그 점검 11번) 브라우저 시험: 헤드리스 Chrome으로 390px·1280px에서 화면마다
머리는 두 줄까지(390px), 누르는 것은 44px(390px)·32px(1280px) 이상, 페이지 끝까지 내리면 '?'가 아무것도 덮지 않는다.
Chrome이나 node가 없으면 건너뛴다."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import needs_tools, with_library
from test_attach_browser import CHROME, NODE
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.contexts import Context
from magus.signing import sign
from magus.store import CategoryItem, LocalStore, Profile, Ref

SCRIPT = Path(__file__).parent / "e2e" / "mobile_measure.mjs"
PATHS = ["/shelf", "/shelf/p/common", "/shelf/p/common?view=list", "/shelf/notes", "/shelf/notes/20261009000000024-aaaaaa",
         "/shelf/edit/notes", "/shelf/write/notes", "/shelf/book/city", "/shelf/notes?page=2", "/me/documents", "/shelf/trash"]


@needs_tools("node 또는 Chrome이 없다", NODE, CHROME)
@pytest.mark.parametrize("width", [390, 1280])
def test_header_targets_and_help_button(server_proc, tmp_path, width):  # noqa: F811
    secret = "s" * 40
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": "http://127.0.0.1:9/never", "ALLOWED_USERS": "sub-a=alice",
        "SESSION_SECRET": secret, "WEB_CLIENT_ID": "web-client", "ANTHROPIC_API_KEY": "sk-test-not-used",
    })
    store = LocalStore(data_dir)
    store.create_project("alice", "도시는 어떻게 태어났나 — 아주 긴 제목의 시험 프로젝트", project_id="city")
    store.write_chapter("alice", "city", 1, "본문(Clack, 2012).", "x", title="하나")
    with_library(store, "alice")
    store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common", category_id="notes", contexts=(Context("문체", "문체 표본이다."),))
    for n in range(25):  # 두 쪽(쪽 번호)
        store.put_category_item("alice", CategoryItem(f"2026100900000{n:04d}-aaaaaa", "notes", f"글 {n} 본문", "me", f"제목 {n}", "author"))
    store.put_attachment("alice", "notes/20261009000000024-aaaaaa", "표.txt", "글자".encode())
    store.put_ref("alice", Ref(key="clack2012", status="unverified", bib={"title": "Gaining ground", "authors": "Clack, J."}, book="notes"))
    store.save_profile("alice", Profile("someone.with.a.long.mail@example.com", "아주 긴 표시 이름을 가진 사람", "", ""))
    store.close()
    cookie = sign({"uid": "alice", "sid": "a1"}, secret.encode(), "session", 3600)
    done = subprocess.run([NODE, str(SCRIPT), CHROME, base, cookie, str(tmp_path / "chrome"), str(width), *PATHS],
                          capture_output=True, text=True, encoding="utf-8", timeout=240)
    rows = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    assert len(rows) == len(PATHS), done.stdout + done.stderr
    for row in rows:
        assert row["headerLines"] <= (2 if width < 600 else 1), row
        assert row["small"] == [], row  # 누르기 작은 것
        assert row["covered"] == [], row  # '?'가 덮는 것
