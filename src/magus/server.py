"""서버 코어. 전송(stdio/HTTP)을 모른다. 전송은 magus.transports가 맡는다."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from magus.balthasar.tools import build_tools as balthasar_tools
from magus.book.tools import build_tools as book_tools
from magus.casper.tools import build_tools as casper_tools
from magus.config import Settings
from magus.instructions import build_instructions
from magus.melchior.check import refresh_cite_counts
from magus.melchior.tools import build_tools as melchior_tools
from magus.search import Embedder
from magus.store import Store

SERVER_NAME = "Magus"


def build_server(settings: Settings, store: Store, embedder: Embedder | None = None) -> MCPServer:
    def current_user() -> str:
        # user_id를 정하는 유일한 곳. P0는 환경변수 USER_ID를 쓰고, P1(HTTP)에서는 요청의 인증 주체에서 꺼낸다.
        return settings.user_id

    # 장별 미확인 인용 수는 파생값이라 인덱스를 다시 만든 뒤에는 0이다. 시작할 때 한 번 맞춘다.
    refresh_cite_counts(store, settings.user_id)
    tools = [
        *book_tools(store, current_user),
        *melchior_tools(store, current_user, embedder),
        *casper_tools(store, current_user, embedder),
        *balthasar_tools(store, current_user, embedder),
    ]
    # instructions는 실제로 등록된 도구만 언급하도록 도구 목록에서 조립한다.
    return MCPServer(name=SERVER_NAME, instructions=build_instructions(t.name for t in tools), tools=tools)
