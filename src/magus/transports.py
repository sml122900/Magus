"""전송 진입점. 서버 코어(build_server)와 분리해 둔다.

- stdio: Claude Desktop이 띄우는 로컬 모드(개발용으로 유지).
- streamable-http: 원격 커넥터 모드(P1). 세션은 상태 없이(stateless) 두고 응답은 JSON 한 번으로 준다.
  요청마다 독립이라 인스턴스를 다시 띄워도 클라이언트가 세션을 잃지 않는다.
"""

from __future__ import annotations

import ipaddress

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from magus.auth import ForbiddenGate, JwtVerifier

MCP_PATH = "/mcp"


def run_stdio(server: MCPServer) -> None:
    server.run("stdio")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def http_app(server: MCPServer, host: str = "127.0.0.1", verifier: JwtVerifier | None = None) -> ASGIApp:
    """MCP 엔드포인트는 /mcp, 상태 확인은 /healthz(인증 없음, 내용 없음).
    verifier가 있으면 허용 목록 밖 사용자(유효한 토큰)에게 403을 주는 문을 앞에 둔다."""

    async def healthz(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    server.custom_route("/healthz", methods=["GET"], include_in_schema=False)(healthz)
    app = server.streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True, json_response=True, host=host)
    return ForbiddenGate(app, verifier, MCP_PATH) if verifier else app


def run_http(server: MCPServer, host: str = "127.0.0.1", port: int = 8000, verifier: JwtVerifier | None = None) -> None:
    import uvicorn

    # uvicorn 접근 로그는 끈다(도구 호출 기록은 magus.audit 한 곳). log_config=None: uvicorn 로그도 logsafe 핸들러를 거친다.
    # proxy_headers: Caddy·플랫폼 프록시 뒤에서 https 주소를 그대로 본다(PRM의 resource는 PUBLIC_URL로 고정).
    uvicorn.run(http_app(server, host, verifier), host=host, port=port, access_log=False, log_config=None, proxy_headers=True)
