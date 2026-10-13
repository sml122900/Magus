"""도구 호출 기록. 남기는 것은 도구 이름, user_id, 소요 시간, 결과(ok/error)뿐이다.

본문·발췌·원고 내용은 절대 로그에 남기지 않는다. 그래서 인자(params.arguments)와 결과 본문, 오류 메시지는 찍지 않는다
(오류 메시지에도 파일 이름이나 본문 조각이 들어갈 수 있다). 오류는 예외 종류만 적는다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from magus import activity

log = logging.getLogger("magus.audit")


class ToolCallLog:
    """MCPServer middleware. tools/call만 기록한다(initialize·tools/list 같은 프로토콜 요청은 뺀다)."""

    def __init__(self, current_user: Callable[[], str]):
        self.current_user = current_user

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        tool = str((ctx.params or {}).get("name", "?"))
        try:
            user = self.current_user()
        except Exception:  # 인증 실패 등. 사용자를 알 수 없으면 '-'
            user = "-"
        started = time.perf_counter()
        status, kind = "ok", ""
        via = activity.VIA.set(activity.CHAT)  # 활동 기록의 경로(2026-10-14): 도구가 지우고 되살리면 '대화'
        try:
            result = await call_next(ctx)
            failed = result.get("isError") if isinstance(result, dict) else getattr(result, "is_error", False)
            if failed:  # 도구 오류(예상한 실패든 예외든 SDK가 결과로 바꾼다). 예외는 logsafe가 따로 알린다
                status, kind = "error", "ToolError"
            return result
        except Exception as e:
            status, kind = "error", type(e).__name__
            raise
        finally:
            activity.VIA.reset(via)
            ms = (time.perf_counter() - started) * 1000
            log.info("tool=%s user=%s ms=%.0f status=%s%s", tool, user, ms, status, f" error={kind}" if kind else "")
