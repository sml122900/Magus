"""전송 진입점. 서버 코어(build_server)와 분리해 둔다."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer


def run_stdio(server: MCPServer) -> None:
    server.run("stdio")


def run_http(server: MCPServer, host: str = "127.0.0.1", port: int = 8000) -> None:
    """P1 자리. streamable-http는 요청마다 user_id를 정하는 인증과 함께 연다.
    그때 server.run("streamable-http", host=host, port=port)를 쓰고,
    build_server의 current_user()가 인증 주체에서 user_id를 꺼내도록 바꾼다."""
    raise NotImplementedError("HTTP 전송은 P1에서 인증과 함께 연다. P0는 stdio만 지원한다.")
