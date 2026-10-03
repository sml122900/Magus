"""로그 설정. 본문·발췌·원고 내용은 절대 로그에 남기지 않는다(P1 원칙).

우리 코드(magus.audit)는 처음부터 내용을 찍지 않는다. 그래도 남는 길이 둘 있어 핸들러에서 막는다.
- SDK가 도구 실패 메시지를 찍는다(`Tool 'x' failed: '<메시지>'`). 메시지에 파일 이름·본문 조각이 들어갈 수 있다 → 메시지를 지운다.
- 예상 못 한 예외의 traceback. 예외 메시지(`ValueError('…본문…')`)가 들어간다 → 예외 종류와 위치(파일:줄 함수)만 남긴다.

ERROR 이상 기록은 알림 콜백으로도 보낸다(종류와 위치만, 같은 내용은 10분에 한 번).
"""

from __future__ import annotations

import logging
import re
import sys
import time
import traceback
from collections.abc import Callable

FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
# 인자에 사용자 데이터가 들어가는 SDK 메시지: 첫 인자(도구·리소스 이름)만 남긴다
_PEER_TEXT = {"Tool %r failed: %r", "Resource %r failed: %r"}
ALERT_INTERVAL = 600.0


def _short(path: str) -> str:
    """site-packages 아래는 패키지 경로만, 그 밖은 파일 경로 그대로(사용자 데이터 경로는 traceback 프레임에 오지 않는다)."""
    return re.split(r"[\\/]site-packages[\\/]", path)[-1]


def _frames(exc: BaseException) -> str:
    """'mcp…UnexpectedToolError ← builtins.RuntimeError at src/magus/book/outline.py:45 build_outline ← …'.
    SDK가 감싼 예외는 원인(__cause__)까지 따라가 실제 예외의 위치를 보인다. 메시지는 넣지 않는다."""
    chain = [exc]
    while chain[-1].__cause__ is not None and len(chain) < 5:
        chain.append(chain[-1].__cause__)
    root = chain[-1]
    tb = traceback.extract_tb(root.__traceback__)[-6:]
    where = " ← ".join(f"{_short(f.filename)}:{f.lineno} {f.name}" for f in reversed(tb))
    kinds = " ← ".join(f"{type(e).__module__}.{type(e).__qualname__}" for e in chain)
    return f"{kinds} at {where or '?'}"


class RedactingFilter(logging.Filter):
    def __init__(self, alert: Callable[[str], None] | None = None):
        super().__init__()
        self.alert = alert
        self._sent: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg in _PEER_TEXT and isinstance(record.args, tuple) and record.args:
            record.args = (record.args[0], "(내용 생략)")
        if record.exc_info and record.exc_info[1] is not None:
            # 메시지 없이 예외 종류와 위치만. 원래 traceback은 버린다.
            record.msg = f"{record.getMessage()} | {_frames(record.exc_info[1])}"
            record.args, record.exc_info, record.exc_text = None, None, None
        if record.levelno >= logging.ERROR and self.alert:
            self._notify(record)
        return True

    def _notify(self, record: logging.LogRecord) -> None:
        key = f"{record.name}|{record.msg}"
        now = time.monotonic()
        if now - self._sent.get(key, -ALERT_INTERVAL) < ALERT_INTERVAL:
            return
        self._sent[key] = now
        try:
            self.alert(f"[Magus] {record.levelname} {record.name}: {record.getMessage()}"[:900])
        except Exception:  # 알림 실패가 서버를 멈추면 안 된다
            pass


def setup_logging(alert: Callable[[str], None] | None = None, level: int = logging.INFO) -> logging.Handler:
    """stderr 하나로 모은다(stdio 전송에서 stdout은 MCP 프로토콜 전용이다). uvicorn도 log_config=None으로 여기에 합친다."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(RedactingFilter(alert))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)
    return handler
