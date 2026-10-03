"""운영자 알림: ERROR 로그(내용은 logsafe가 거른 뒤)가 웹훅·텔레그램으로 간다. 설정이 없으면 꺼져 있다."""

from __future__ import annotations

import http.server
import json
import logging
import threading
import time

import pytest

from magus.alerts import sender
from magus.cli import main
from magus.logsafe import RedactingFilter


@pytest.fixture
def webhook():
    received: list[dict] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/hook", received
    httpd.shutdown()


def test_no_config_means_no_alerts():
    assert sender({}) is None


def test_error_log_goes_to_webhook_without_content(webhook):
    url, received = webhook
    send = sender({"ALERT_WEBHOOK_URL": url})
    f = RedactingFilter(send)
    try:
        raise ValueError("비밀본문가나다")
    except ValueError as e:
        record = logging.LogRecord("mcp.server.mcpserver.server", logging.ERROR, __file__, 1,
                                   "Tool %r raised an unexpected exception", ("book_outline",), (type(e), e, e.__traceback__))
    f.filter(record)
    for _ in range(50):
        if received:
            break
        time.sleep(0.05)
    assert len(received) == 1
    text = received[0]["text"]
    assert received[0]["content"] == text  # Slack(text)·Discord(content) 둘 다
    assert "book_outline" in text and "builtins.ValueError" in text and "비밀본문" not in text


def test_alert_test_command(webhook, monkeypatch, tmp_path, capsys):
    url, received = webhook
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("ALERT_WEBHOOK_URL", url)
    main(["alert-test"])
    assert "보냈습니다" in capsys.readouterr().out and "알림 시험" in received[0]["text"]
    monkeypatch.delenv("ALERT_WEBHOOK_URL")
    with pytest.raises(SystemExit):
        main(["alert-test"])
