"""웹 경로의 요청 본문 크기 한도(2026-10-09 점검 5-a). 서버 메모리가 1GB라 받는 도중에 끊는다.

- Content-Length 머리가 한도를 넘으면 본문을 읽기 전에, 머리가 없는 청크 전송이면 받은 양이 한도를 넘는 순간 413.
  끊는 것은 라우트가 본문을 읽을 때(receive) HTTPException(413)을 올리는 방식이라, 웹 오류 화면(413)이 그대로 그린다.
- 한도는 주소마다(Web.body_limit): 글의 첨부(글쓰기·고치기) 첨부 한 개 한도 × 10 + 2MB,
  올린 파일 한 개 한도 × 4 + 1MB, 그 밖의 웹 폼 MAX_REQUEST_MB(2MB). /mcp는 SDK의 한도(같은 MAX_REQUEST_MB)를 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from magus.inbox import mb

TOO_LARGE = "보낸 내용이 너무 큽니다(한 번에 {limit}까지)."


class BodyLimitGate:
    """limit_for(method, path) → 이 요청 본문의 최대 바이트(None이면 이 문은 보지 않는다)."""

    def __init__(self, app: ASGIApp, limit_for: Callable[[str, str], int | None]):
        self.app, self.limit_for = app, limit_for

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope.get("method", "GET"), scope.get("path", ""))
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        try:
            declared_size = int(declared) if declared else None
        except ValueError:
            declared_size = None
        seen = 0

        async def limited() -> Message:
            nonlocal seen
            if declared_size is not None and declared_size > limit:
                raise HTTPException(413, TOO_LARGE.format(limit=mb(limit)))
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise HTTPException(413, TOO_LARGE.format(limit=mb(limit)))
            return message

        await self.app(scope, limited, send)
