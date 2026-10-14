"""로그에 원고 내용이 남지 않는다: SDK의 도구 실패 메시지와 예외 traceback까지 거른다. ERROR는 알림으로 간다."""

from __future__ import annotations

import io
import logging

import pytest
from mcp import Client

from magus.config import Settings
from magus.logsafe import RedactingFilter
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
SECRET = "비밀본문가나다"


@pytest.fixture
def captured():
    out, alerts = io.StringIO(), []
    handler = logging.StreamHandler(out)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    handler.addFilter(RedactingFilter(alerts.append))
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.INFO)
    yield out, alerts
    root.removeHandler(handler)
    root.setLevel(old)


async def test_tool_failure_and_exception_messages_are_redacted(settings: Settings, store: LocalStore, captured, monkeypatch):
    out, alerts = captured
    async with Client(build_server(settings, store)) as client:
        # 예상한 실패(ToolError): SDK가 메시지를 찍는다 → 메시지를 지운다
        failed = await client.call_tool("book_write_chapter", {"number": 1, "content": SECRET, "note": "x"})
        assert failed.is_error
        # 예상 못 한 예외: traceback에 예외 메시지가 들어간다 → 종류와 위치만 남긴다
        monkeypatch.setattr(store, "get_project", lambda *_: (_ for _ in ()).throw(RuntimeError(SECRET)))
        crashed = await client.call_tool("book_outline", {})
        assert crashed.is_error
    log = out.getvalue()
    assert SECRET not in log
    assert "Tool 'book_write_chapter' failed: '(내용 생략)'" in log
    assert "builtins.RuntimeError at " in log and "outline.py" in log
    assert "tool=book_outline user=alice" in log and "status=error" in log
    assert len(alerts) == 1 and "RuntimeError" in alerts[0] and SECRET not in alerts[0]


def test_alerts_are_rate_limited():
    alerts: list[str] = []
    f = RedactingFilter(alerts.append)
    for _ in range(3):
        f.filter(logging.LogRecord("magus", logging.ERROR, __file__, 1, "디스크 가득", None, None))
    assert len(alerts) == 1


def test_peer_reset_in_asyncio_is_a_warning_not_an_alert():
    """상대가 먼저 연결을 끊은 것(Windows Proactor의 'Exception in callback …_call_connection_lost')은 서버 잘못이 아니다(2026-10-14)."""
    alerts: list[str] = []
    f = RedactingFilter(alerts.append)
    for exc in (ConnectionResetError(10054, "원격 호스트가 끊음"), ConnectionAbortedError(), BrokenPipeError()):
        record = logging.LogRecord("asyncio", logging.ERROR, __file__, 1, "Exception in callback %s", ("_call_connection_lost(None)",),
                                   (type(exc), exc, None))
        f.filter(record)
        assert record.levelno == logging.WARNING and record.levelname == "WARNING" and "원격 호스트" not in record.getMessage()
    assert alerts == []
    other = logging.LogRecord("asyncio", logging.ERROR, __file__, 1, "Exception in callback", None, (ValueError, ValueError("x"), None))
    f.filter(other)  # 다른 예외는 그대로 ERROR(알림도 간다)
    assert other.levelno == logging.ERROR and len(alerts) == 1
