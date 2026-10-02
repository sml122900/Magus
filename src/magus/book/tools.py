"""원고(book_*) MCP 도구. 도구는 얇게 두고, 일은 Store와 이 패키지의 함수가 한다."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from magus.book.outline import build_outline
from magus.store import Store


def register(server: MCPServer, store: Store, current_user: Callable[[], str]) -> None:
    @server.tool(
        name="book_outline",
        description=(
            "모든 원고 작업의 첫 호출. 책 제목, 장 목록(번호·제목·상태·글자수·미확인 인용 수), "
            "최근 결정 10개, 열린 미해결, 최근 변경 5개를 3,000 토큰 이하로 돌려준다. "
            "본문은 담지 않는다. project_id를 생략하면 가장 최근 프로젝트."
        ),
        structured_output=False,
    )
    def book_outline(project_id: str | None = None) -> str:
        return build_outline(store, current_user(), project_id)
