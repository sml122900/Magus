"""폼 상태·스크랩 초점(2026-10-09 구조·버그 점검 5·8·9번) 브라우저 시험: 헤드리스 Chrome으로 ☆ 초점(Space·Enter),
글자 수 표시·넘치면 막기, 바꾼 채 떠날 때 확인, 저장 뒤 뒤로 가기의 폼 모습. Chrome이나 node가 없으면 건너뛴다."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_attach_browser import CHROME, NODE
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.signing import sign
from magus.store import CategoryItem, LocalStore

SCRIPT = Path(__file__).parent / "e2e" / "forms_browser.mjs"
POST = "20261009000000000-aaaaaa"


@pytest.mark.skipif(NODE is None or CHROME is None, reason="node 또는 Chrome이 없다")
def test_star_focus_counts_leave_guard_and_back(server_proc, tmp_path):  # noqa: F811
    secret = "s" * 40
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": "http://127.0.0.1:9/never", "ALLOWED_USERS": "sub-a=alice",
        "SESSION_SECRET": secret, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(POST, book, "고칠 글", "me", "제목", "author"))
    store.close()
    cookie = sign({"uid": "alice", "sid": "a1"}, secret.encode(), "session", 3600)
    done = subprocess.run([NODE, str(SCRIPT), CHROME, base, cookie, str(tmp_path / "chrome"),
                           f"/shelf/{book}", f"/shelf/write/{book}", f"/shelf/{book}/{POST}/edit"],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "FAIL" not in done.stdout and done.stdout.count("ok  ") == 13, done.stdout
