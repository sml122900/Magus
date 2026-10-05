# 토큰 aud는 이 서버 하나만 받는다(결정 #79, #51 대체)

2026-10-06. 브랜치 `fix/auth-audience`, 태그 `p1-auth-audience`.

## Problem

- 자매 서비스 trip_ai가 Magus와 **같은 WorkOS 환경(Staging, `dapper-palace-57-staging.authkit.app`)**을 쓰게 된다. 이 결정은 그 공유를 전제로 한다.
  - 같은 환경이라 issuer와 서명 키(JWKS)가 같다. 사용자 본인의 WorkOS user id(`sub`)도 두 서비스에서 같다.
  - 그래서 iss·서명·sub·허용 목록으로는 "Magus용 토큰인가"를 가를 수 없다. 가르는 값은 aud(리소스 주소)뿐이다.
- trip_ai 점검에서, Magus에서 복사한 인증 코드에 구멍 두 개가 나왔다.
  - **구멍 1**: `AUTH_AUDIENCE`에 값을 더하면 받는 aud가 넓어졌다(결정 #51 "`AUTH_AUDIENCE`로 여럿 허용"). `docs/connect-claude.md` 진단 표에도 aud 불일치가 나면 "`AUTH_AUDIENCE`에 실제 aud를 더한다"는 안내가 있었다. 운영자가 그 안내대로 trip_ai 주소를 더하면, trip_ai용 토큰이 Magus를 통과한다.
  - **구멍 2**: 토큰의 aud가 목록이면 하나만 겹쳐도 통과했다. PyJWT의 `audience` 검사는 "목록 안에 기대 값이 하나라도 있으면 통과"다. `[magus/mcp, trip-ai/mcp]`처럼 두 서비스를 함께 가리키는 토큰을 받는다.
- 옛 코드(`decf79c`)로 재현했다(로컬, 2026-10-06).
  - 기본 설정(AUTH_AUDIENCE 없음)에서 aud `[magus/mcp, trip-ai/mcp]` 토큰: **받음**(구멍 2). 운영 서버도 이 설정이었다.
  - `AUTH_AUDIENCE=magus/mcp,trip-ai/mcp`로 시작하고 trip_ai 문자열 aud 토큰: **받음**(구멍 1). 운영 서버 `.env`에는 `AUTH_AUDIENCE` 줄이 없어 이 구멍은 열려 있지 않았다.
  - 기본 설정에서 trip_ai 문자열 aud 토큰: 거부(이것은 원래 막혀 있었다).
- 제약: trip_ai 배포 전에 Magus부터 막는다. 운영 중인 서버(`decf79c`)에서 갈라 작업하고, master의 다른 진행 중 작업(#69~#78)은 배포하지 않는다.

## Action

**고른 것**
- 토큰 aud는 정확히 `PUBLIC_URL + "/mcp"` 하나여야 한다(`magus/auth.py: only_audience`).
  - 문자열이면 그 값과 같아야 한다.
  - 목록이면 원소가 그 값 하나뿐일 때만 받는다. 다른 값이 섞이거나, 같은 값이 두 번이어도 거부한다.
  - aud가 없으면 거부한다(`require`에 aud 추가).
  - 구현: PyJWT의 aud 검사를 먼저 통과시키고, 그 뒤에 정확히 하나인지 따로 본다. 실패하면 같은 `InvalidAudienceError`로 올려서 401 흐름과 로그 형식을 그대로 쓴다.
- `AUTH_AUDIENCE`는 받는 aud를 바꾸거나 넓히는 설정이 아니다.
  - 비어 있으면 `PUBLIC_URL/mcp`다.
  - 값이 있는데 `PUBLIC_URL/mcp`와 한 글자라도 다르면(끝 `/`, 쉼표 목록 포함) **서버가 시작하지 않는다**. 이유는 stderr(운영에서는 `docker compose logs magus`)에 한국어로 남는다: `설정 오류로 시작하지 않습니다: AUTH_AUDIENCE='…'가 PUBLIC_URL/mcp(…)와 달라 시작하지 않습니다. …`
  - 조용히 무시하지 않고 멈추는 이유: 운영자는 넓히려는 뜻으로 값을 넣었다. 무시하면 의도와 다른 상태로 돈다는 사실을 모른다.
- aud 때문에 거부할 때 받은 aud의 **모양**을 로그에 남긴다: `aud 불일치 (토큰 aud=목록 2개 ["…/mcp", "…/mcp"], 기대=…/mcp)`, `aud 불일치 (토큰 aud=문자열 "…", 기대=…)`.
  - aud는 비밀이 아니다. 토큰 자체와 sub는 지금처럼 남기지 않는다(#52).
  - 값은 검증 전 입력이라 JSON 문자열로 적는다. 줄바꿈 같은 제어 문자로 로그 줄을 꾸며 넣지 못한다. 값은 120자, 목록은 앞 5개까지만 적는다.
- 웹 로그인(#57)도 같은 검증기를 쓴다. `magus serve`가 `JwtVerifier`를 하나 만들어 MCP(SDK 토큰 검증), `ForbiddenGate`, 웹 콜백(`Web.callback` → `verifier.check`)에 같은 객체를 넘긴다. 따로 맞출 코드는 없었다. 테스트로 고정했다(웹 로그인에서도 trip_ai·섞인 목록 aud는 401).
- 문서: `docs/deploy.md` 2-1절의 401 안내, `docs/connect-claude.md` 진단 표("`AUTH_AUDIENCE`에 실제 aud를 더한다" 삭제), `.env.example`, `CLAUDE.md` 설정 표, `auth-provider.md`.
  - 401(aud 불일치)이면 **WorkOS에 등록한 리소스 주소가 `PUBLIC_URL/mcp`와 글자까지 같은지** 확인하라고 적었다.

**서비스별로 따로인 것**
- `ALLOWED_USERS`는 서비스마다 따로다. Magus의 목록과 trip_ai의 목록은 서로 영향을 주지 않는다. 같은 sub가 두 목록에 다 있을 수 있다.
- 바로 그래서 허용 목록만으로는 서비스 사이 토큰 재사용을 막지 못한다(사용자 본인은 두 목록에 다 있다). 막는 것은 aud 검사다.
- 리소스(aud)는 서비스마다 다르게 WorkOS에 등록한다: Magus `https://magus.lifebookapplication.com/mcp`, trip_ai `https://trip-ai.lifebookapplication.com/mcp`.

**비교한 대안**
- PyJWT `strict_aud=True`: aud가 목록이면 원소가 하나여도 거부한다. WorkOS가 aud를 목록으로 줄 수도 있어(원소 하나), 지금 되는 로그인을 깨뜨릴 위험이 있다.
- 서비스마다 WorkOS 환경을 따로 둔다: 가장 깔끔하게 갈린다. 하지만 trip_ai와 환경을 공유하는 것이 전제이고, Magus만으로 정할 일이 아니다. 공유하더라도 aud 검사는 어차피 필요하다.
- `azp`(클라이언트 id)로 가른다: 두 서비스 모두 Claude(CIMD)가 클라이언트라 같은 값이 온다. 가를 수 없다.
- `AUTH_AUDIENCE`에 다른 값이 오면 경고만 내고 무시한다: 운영자가 모르는 채로 돈다. 시작을 막는 쪽이 드러난다.

## Result

- 테스트: 191개 중 190개 통과. 실패 1개는 알려진 간헐 실패 `tests/test_http.py::test_request_size_limit`다(Windows 연결 리셋, status.md 7절). 따로 5번 돌려 3번 통과했다.
  - 새로 고정한 것(`tests/test_auth.py`, `tests/test_web.py`)
    - 검증기: trip_ai 문자열 aud, `[magus, trip_ai]`, `[trip_ai, magus]`, `[magus, magus]`, aud 없음은 거부. 문자열, 원소 하나인 목록은 받음.
    - **실제 HTTP 서버**(하위 프로세스): trip_ai aud와 섞인 목록은 401(+`resource_metadata`), 정상 aud 둘(문자열·원소 하나인 목록)은 200. 서버 로그에 aud의 모양이 남는다.
    - 웹 로그인: trip_ai aud, 섞인 목록은 401 화면, 원인은 로그에만.
    - 설정: `AUTH_AUDIENCE`가 쉼표 목록, 다른 값, 끝 `/`만 다른 값, trip_ai면 ValueError. 앞뒤 공백만 있는 같은 값은 받는다.
    - 시작: `magus serve --transport http`가 다른 `AUTH_AUDIENCE`로는 종료 코드 2로 끝나고 stderr에 한국어 이유가 남는다(듣기 시작 전에 멈춤).
    - 로그 주입: aud에 줄바꿈이 있어도 로그 한 줄로 남는다.
- 서버 반영 결과는 status.md(결정 #79)와 `docs/deploy.md` 기록에 있다.

**대안을 버린 이유**: strict_aud는 원소 하나인 목록까지 거부해 지금 되는 로그인을 깨뜨릴 수 있고, 환경 분리는 전제(trip_ai와 공유)와 다르며, azp는 두 서비스가 같은 값(Claude)이라 가를 수 없고, 경고만 내고 무시하는 방식은 운영자 의도와 다르게 조용히 돈다.
