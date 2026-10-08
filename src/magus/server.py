"""서버 코어. 전송(stdio/HTTP)을 모른다. 전송은 magus.transports가 맡는다."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from magus.audit import ToolCallLog
from magus.auth import USER_ID_CLAIM, JwtVerifier
from magus.book.document_tools import build_tools as document_tools
from magus.book.tools import build_tools as book_tools
from magus.casper.tools import build_tools as casper_tools
from magus.category.tools import build_tools as category_tools
from magus.config import Settings
from magus.inbox import FileResolver
from magus.inbox import build_tools as inbox_tools
from magus.instructions import build_instructions
from magus.melchior.check import refresh_cite_counts
from magus.melchior.question_tools import build_tools as question_tools
from magus.melchior.tools import build_tools as melchior_tools
from magus.search import Embedder
from magus.store import Store

SERVER_NAME = "Magus"


def build_server(
    settings: Settings,
    store: Store,
    embedder: Embedder | None = None,
    verifier: JwtVerifier | None = None,
    local_files: bool = False,
    export_link: Callable[[str, str], str] | None = None,
) -> MCPServer:
    """settings.auth가 있으면 원격(HTTP) 모드: 리소스 서버로서 토큰을 검증하고 sub로 user_id를 정한다.
    local_files: 파일 인자로 로컬 경로도 받는다(stdio 개발용만). 기본은 받은함 이름만."""
    auth = settings.auth
    if auth is not None and verifier is None:
        verifier = JwtVerifier(auth)

    def current_user() -> str:
        # user_id를 정하는 유일한 곳. 로컬(stdio)은 환경변수 USER_ID, 원격(HTTP)은 검증된 토큰의 sub → 허용 목록.
        # 두 모드를 가르는 분기는 이 함수 밖으로 나가지 않는다.
        if auth is None:
            return settings.user_id
        token = get_access_token()
        if token is None or not token.claims or USER_ID_CLAIM not in token.claims:
            raise PermissionError("인증된 사용자가 없다")
        return str(token.claims[USER_ID_CLAIM])

    # 장별 미확인 인용 수는 파생값이라 인덱스를 다시 만든 뒤에는 0이다. 시작할 때 한 번 맞춘다.
    for user_id in sorted(set(auth.allowed.values())) if auth else [settings.user_id]:
        refresh_cite_counts(store, user_id)
    files = FileResolver(store, settings.files_root, local_paths=local_files)
    tools = [
        *book_tools(store, current_user, files, export_link),
        *document_tools(store, current_user),
        *melchior_tools(store, current_user, embedder, files),
        *question_tools(store, current_user),
        *casper_tools(store, current_user, embedder, files),
        *category_tools(store, current_user, embedder, files),
        *inbox_tools(store, current_user, settings.max_user_bytes),
    ]
    # instructions는 실제로 등록된 도구만 언급하도록 도구 목록에서 조립한다.
    return MCPServer(
        name=SERVER_NAME,
        instructions=build_instructions(t.name for t in tools),
        tools=tools,
        middleware=[ToolCallLog(current_user)],  # 도구 이름·user_id·소요 시간·결과만 기록(본문 없음)
        # 원격 모드: Protected Resource Metadata(/.well-known/oauth-protected-resource/mcp)로 인증 서버를 알리고,
        # 토큰이 없거나 무효하면 401 + WWW-Authenticate. audience는 JwtVerifier가 직접 검사한다.
        auth=AuthSettings(issuer_url=auth.issuer, resource_server_url=auth.resource, validate_token_resource=False)
        if auth
        else None,
        token_verifier=verifier if auth else None,
    )
