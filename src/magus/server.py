"""서버 코어. 전송(stdio/HTTP)을 모른다. 전송은 magus.transports가 맡는다."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from magus.book import tools as book_tools
from magus.config import Settings
from magus.instructions import INSTRUCTIONS
from magus.store import Store

SERVER_NAME = "Magus"


def build_server(settings: Settings, store: Store) -> MCPServer:
    server = MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS)

    def current_user() -> str:
        # user_id를 정하는 유일한 곳. P0는 환경변수 USER_ID를 쓰고, P1(HTTP)에서는 요청의 인증 주체에서 꺼낸다.
        return settings.user_id

    book_tools.register(server, store, current_user)
    return server
