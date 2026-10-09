"""도움말 대화 보관(2026-10-09) 브라우저 시험: 헤드리스 Chrome으로 페이지 이동·접기·20턴·24시간·새 대화·다른 사용자·로그아웃.
실제 API는 부르지 않는다(가짜 Messages API). Chrome이나 node가 없으면 건너뛴다."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from conftest import needs_tools
from test_help import fake_api  # noqa: F401 - 픽스처
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.signing import sign

NODE = shutil.which("node")
CHROME = next((c for c in (os.environ.get("CHROME"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           shutil.which("google-chrome"), shutil.which("chromium")) if c and Path(c).exists()), None)
SCRIPT = Path(__file__).parent / "e2e" / "help_browser.mjs"


@needs_tools("node 또는 Chrome이 없다", NODE, CHROME)
def test_help_conversation_survives_pages_and_is_cleared_when_it_should(server_proc, fake_api, tmp_path):  # noqa: F811
    url, state = fake_api
    secret = "s" * 40
    base, _, log_path = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": "http://127.0.0.1:9/never", "ALLOWED_USERS": "sub-a=alice,sub-b=bob",
        "SESSION_SECRET": secret, "WEB_CLIENT_ID": "web-client", "ANTHROPIC_API_KEY": "sk-ant-fake", "ANTHROPIC_BASE_URL": url,
    })
    alice = sign({"uid": "alice", "sid": "a1"}, secret.encode(), "session", 3600)
    bob = sign({"uid": "bob", "sid": "b1"}, secret.encode(), "session", 3600)
    done = subprocess.run([NODE, str(SCRIPT), CHROME, base, alice, bob, str(tmp_path / "chrome")], capture_output=True, text=True,
                          encoding="utf-8", timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "FAIL" not in done.stdout and done.stdout.count("ok  ") >= 14
    # 서버로는 최근 3번만 갔다(21번째 질문 때도)
    assert max(len(s["body"]["messages"]) for s in state["seen"]) == 7
    assert "앨리스의 질문" not in Path(log_path).read_text(encoding="utf-8")
