# MCP Python SDK 2.2.0 선택과 코어·전송 분리

- 날짜: 2026-10-03
- 단계: 1단계(뼈대)
- 코드: `src/magus/server.py`, `src/magus/transports.py`, `src/magus/book/tools.py`, `tests/test_server.py`, `tests/test_stdio.py`

## Problem

- 스택 요구 사항은 "MCP 공식 Python SDK, stdio와 streamable-http를 모두 지원하는 버전"이다.
- `uv add mcp`로 받은 최신 버전은 **2.2.0**이었다. 1.x에서 쓰던 `mcp.server.fastmcp.FastMCP`는 2.x에서 없어졌다(임포트하면 마이그레이션 안내와 함께 `ModuleNotFoundError`가 난다).
- 제약: P0는 stdio만 구현하되 HTTP 진입점 자리를 비워 둬야 한다. P1에서 HTTP를 열 때는 요청마다 user_id가 달라지므로, user_id를 정하는 지점이 한 곳이어야 한다.

## Action

- 설치된 SDK 코드를 직접 읽고 API를 확인한 뒤 **mcp 2.2.0**을 그대로 쓰기로 했다.
  - `from mcp.server.mcpserver import MCPServer`
  - `MCPServer(name=, instructions=)`, `@server.tool(name=, description=, structured_output=False)`
  - `server.run("stdio")`, `server.run("streamable-http", host=, port=)`로 두 전송을 모두 지원한다.
  - 동기 도구는 `anyio.to_thread.run_sync`로 워커 스레드에서 실행된다. 그래서 Store를 스레드 안전하게 만들었다(store-interface 참고).
  - stdio는 SDK가 stdin/stdout을 UTF-8로 다시 감싼다. 그래서 Windows에서도 한글이 깨지지 않는다(`mcp/server/stdio.py`).
  - 테스트에는 `mcp.Client(server)`의 in-process 연결과 `Client(StdioServerParameters(...))`의 하위 프로세스 연결을 함께 쓴다.
- 코어와 전송을 분리했다.
  - `build_server(settings, store) -> MCPServer`가 코어다. 도구를 등록하고 instructions를 넣을 뿐, 어떤 전송으로 실행될지는 모른다.
  - `transports.py`의 `run_stdio`가 P0 구현이다. `run_http`는 `NotImplementedError`로 자리만 잡아 두었다.
  - user_id를 정하는 곳은 `build_server` 안의 `current_user()` 한 군데다. P1에서는 이 함수만 인증 주체를 읽도록 바꾸면 된다.
  - 도구는 코어 모듈별로 `tools.py`의 `register(server, store, current_user)`에서 등록한다(`book/tools.py`부터 시작).
- 텍스트 도구는 `structured_output=False`로 두었다. 같은 내용이 `structuredContent`에 한 번 더 실려 응답이 두 배가 되는 것을 막는다("도구 응답은 짧게").
- 비교한 대안
  - **`mcp<2`로 고정**: 익숙한 FastMCP API를 쓸 수 있다. 하지만 시작부터 구버전에 묶이고, 나중에 2.x로 옮기는 비용이 생긴다.
  - **독립 `fastmcp` 패키지**: 공식 SDK가 아니다. 요구 사항("공식 Python SDK")에 맞지 않는다.

## Result

- `tests/test_server.py`: 서버 이름이 "Magus"이고, instructions가 6절 원문과 같으며, `book_outline` 응답에 `structured_content`가 없다. 다른 user_id로 호출하면 빈 결과가 나온다.
- `tests/test_stdio.py`: Claude Desktop과 같은 경로(`python -m magus serve`를 하위 프로세스로 띄우고 stdio로 통신)에서 한글 outline을 정상으로 받는다.
- 아직 Claude Desktop에서 실제로 연결해 보지는 않았다(사용자 확인 대기).

> 대안을 버린 이유: 1.x로 고정하면 이미 지원이 끝난 API 위에 쌓게 되고, 독립 fastmcp는 공식 SDK가 아니다. 반면 2.x는 두 전송과 in-process 테스트 클라이언트를 기본으로 제공한다.
