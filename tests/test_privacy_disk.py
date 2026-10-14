"""2026-10-14 사용자 지시: 개인정보 처리방침 화면(/privacy, 기능 플래그로 꺼 둠)과 디스크 85% 알림(deploy/alive.sh), 사용자별 한도 500MB(compose)."""

from __future__ import annotations

import http.server
import os
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path

import httpx2
import pytest
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.webstart import PRIVACY_CUT, PRIVACY_FILE

ROOT = Path(__file__).resolve().parents[1]
SH = shutil.which("sh")


def test_privacy_page_is_off_unless_flagged(server_proc):  # noqa: F811
    base, _, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=60) as c:
        off, unknown = c.get("/privacy"), c.get("/no-such-page")
        assert off.status_code == 404 and unknown.status_code == 404
        assert off.text.replace("/privacy", "") == unknown.text.replace("/no-such-page", "")  # 없는 주소와 똑같이 보인다


def test_privacy_page_when_on_shows_draft_without_check_table(server_proc):  # noqa: F811
    base, _, _ = server_proc({"PRIVACY_PAGE": "on"})
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=60) as c:
        page = c.get("/privacy")  # 로그인 없이
        assert page.status_code == 200 and "<h1>개인정보 처리방침(초안)</h1>" in page.text
        assert "WorkOS" in page.text and "Anthropic" in page.text and "최대 약 1년" in page.text
        assert "대조 기록" not in page.text and "test_logsafe" not in page.text  # 대조 표는 공개하지 않는다


def test_privacy_draft_has_check_table_after_cut():
    text = PRIVACY_FILE.read_text(encoding="utf-8")
    shown, check = text.split(PRIVACY_CUT, 1)
    assert "| 초안 문장 | 근거(코드·설정) | 결과 |" in check and "**다름(지시문)**" in check
    assert "PRIVACY_PAGE" not in shown  # 공개되는 부분에는 운영 설정 이름이 없다


def test_user_limit_is_500mb_in_compose():
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert 'MAX_USER_MB: "500"' in compose


class _Catch(http.server.BaseHTTPRequestHandler):
    got: list[str] = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("content-length") or 0)).decode()
        _Catch.got.append(self.path + "?" + body)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):  # 조용히
        pass


@pytest.fixture
def telegram():
    _Catch.got = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Catch)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", _Catch.got
    srv.shutdown()


@pytest.mark.skipif(SH is None, reason="sh가 없다")
def test_alive_sends_disk_alert_once_then_waits(tmp_path, telegram):
    api, got = telegram
    work = tmp_path / "deploy"
    work.mkdir()
    shutil.copy(ROOT / "deploy" / "alive.sh", work / "alive.sh")
    (work / ".env").write_text("ALERT_TELEGRAM_BOT_TOKEN=fake-token\nALERT_TELEGRAM_CHAT_ID=42\n", encoding="utf-8")  # 시험용 가짜 값
    state = tmp_path / "disk-state"

    def run(**extra: str) -> None:
        env = {**os.environ, "ALERT_TELEGRAM_API": api, "DISK_ALERT_STATE": str(state).replace("\\", "/"), **extra}
        done = subprocess.run([SH, str(work / "alive.sh").replace("\\", "/")], env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr

    run(DISK_ALERT_PERCENT="0")  # 사용률이 0%를 넘으니 알림
    assert len(got) == 1 and got[0].startswith("/botfake-token/sendMessage?")
    text = urllib.parse.parse_qs(got[0].split("?", 1)[1])["text"][0]
    assert text.startswith("[Magus] 디스크 사용률 ") and "알림 기준 0%" in text and state.exists()
    run(DISK_ALERT_PERCENT="0")  # 6시간 안에는 다시 보내지 않는다
    assert len(got) == 1
    run(DISK_ALERT_PERCENT="100")  # 기준 아래로 내려오면 상태를 지운다(다음에 넘을 때 바로 알림)
    assert len(got) == 1 and not state.exists()
    run(DISK_ALERT_TEST="1")  # 시험 알림(상태 파일은 건드리지 않는다)
    assert len(got) == 2 and "디스크 알림 시험" in urllib.parse.parse_qs(got[1].split("?", 1)[1])["text"][0] and not state.exists()
