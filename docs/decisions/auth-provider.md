# 인증 서비스: WorkOS AuthKit (관리형 OAuth 인증 서버)

- 날짜: 2026-10-03 (P1 2단계)
- 코드: `src/magus/auth.py`(JwtVerifier, ForbiddenGate, AuthConfig), `src/magus/server.py`(current_user, AuthSettings), `tests/test_auth.py`
- 조사 기준일: 2026-10-03. 웹 조사 결과이고, 가격·기능은 각 서비스 문서 기준이다. 확인하지 못한 것은 "미확인"으로 적었다.

## Problem

- 사용자와 아버지가 각자의 Claude(웹·Desktop·모바일)에서 커넥터 URL 하나로 Magus를 쓴다. 자체 OAuth 서버는 만들지 않는다(P1 비목표). 공개 가입은 없고 허용 목록만 쓴다.
- Magus는 **리소스 서버**만 한다.
  - Protected Resource Metadata(RFC 9728)로 인증 서버를 알린다.
  - JWT 액세스 토큰을 검증한다(서명·만료·issuer·audience).
  - `sub` → user_id로 매핑한다.
- Claude.ai 커스텀 커넥터의 요구 사항(Claude 문서, 2026-10)
  - 클라이언트 등록은 세 가지다.
    - **CIMD**: "Claude의 공개 신원 사용". 권장이다. client_id는 `https://claude.ai/oauth/mcp-oauth-client-metadata`이고 콜백은 `https://claude.ai/api/mcp/auth_callback`.
    - **DCR**
    - 직접 입력한 client ID
  - CIMD는 인증 서버 메타데이터에 `client_id_metadata_document_supported: true`와 `token_endpoint_auth_methods_supported`의 `none`이 있어야 쓴다. 없으면 DCR로 내려간다.
  - PKCE S256이 필요하다.
  - 401 응답에는 `WWW-Authenticate: Bearer resource_metadata=…`가 있어야 한다.
  - **메타데이터의 `resource`는 커넥터 URL과 정확히 같아야 한다.** `authorization_servers`는 첫 항목만 쓴다.
  - 연결한 뒤에는 인증 설정을 바꿀 수 없다(지우고 다시 추가해야 한다).
  - MCP 스펙 2026-07-28은 DCR을 deprecated로, CIMD를 SHOULD로 두었다. 서버는 토큰의 audience가 자기인지 확인해야 한다(RFC 8707).
- 아버지는 비개발자다. 로그인은 Google이나 이메일 코드처럼 쉬워야 하고, 한국어 화면이면 좋다.

## Action

### 비교

| 서비스 | MCP / DCR / CIMD | JWT + JWKS, aud | 무료 → 첫 유료 | Claude.ai 사례 | 가입 제한 | 비고 |
|---|---|---|---|---|---|---|
| **WorkOS AuthKit** | MCP 가이드 있음. CIMD 기본, DCR 유지, RFC 8414 | JWT, `/oauth2/jwks`, `aud` = 등록한 리소스 URL | 100만 MAU 무료. 커스텀 도메인 월 $99(필요 없음) | WorkOS 자체 MCP 서버를 Claude 커스텀 커넥터로 씀(2026-08). 실패 보고 #271·#620(닫힘, 수정 내역 없음) | 가입 토글 + 초대(Google 신규 가입도 막는지는 미확인) | 호스팅 로그인(Google·이메일 코드·패스키), 90개 언어(한국어) |
| Auth0 | MCP용 GA(2026-05), DCR. CIMD는 수동 등록 | JWT RS256(API 등록 필요, 리소스 파라미터 호환 설정 필요) | 25k MAU 무료, Essentials 월 $35부터 | 제3자 가이드(2026-04, 08 갱신) | Google 신규 가입은 막지 못하고 Action으로 로그인 때 거부 | 설정 단계가 가장 많고, audience 끝 슬래시 오류가 있다 |
| Stytch | DCR, CIMD 토글 | JWT RS256, `aud` = 프로젝트/클라이언트 id(URL 아님) | 10k MAU 무료 | 미확인 | 미확인 | **동의 화면을 직접 호스팅해야 한다** |
| Descope | DCR·CIMD(2026-01 GA), 호스팅 동의 화면 | JWT, `aud`에 MCP URL 포함, Python `descope-mcp` | 7.5k MAU·월 2,000 MCP 동의 무료, Pro 월 $249(연간) | 문서에 Claude가 클라이언트로 나옴(독립 보고는 미확인) | 로그인 전용 흐름으로 신규 거부 가능 | 차선 |
| Clerk | DCR·CIMD(2026-08) | 새 앱은 JWT(옛 앱 opaque), `aud` 미확인 | 50k 무료, Pro 월 $25 | 운영 인스턴스는 동작, **개발 인스턴스 실패**(#1104, 2026-10-03 열림) | 초대 전용 무료, 허용 목록 유료 | 운영에는 커스텀 도메인 필요 |
| Scalekit | DCR·CIMD | JWT, `aud` = 등록 URL | MCP Auth는 Growth 월 $99, 무료 여부 미확인 | Claude Desktop 문제 해결 문서 있음 | 미확인 | 기존 로그인 위에 얹는 용도 |
| Supabase Auth | OAuth 2.1 서버 + DCR, **CIMD 없음** | JWT(비대칭 키 필요), 기본 `aud`는 MCP URL 아님(미확인) | 50k MAU 무료, **1주 쉬면 프로젝트 정지** | 커스텀 커넥터 안내 있음 | 미확인 | **동의 화면을 직접 만들어야 한다** |
| Logto Cloud | CIMD 있음, **DCR 없음** | 미확인 | 무료 등급에 서드파티 앱·API 리소스 없음 | 미확인 | 미확인 | Pro 필요(미확인) |

자체 호스팅(Keycloak, Cloudflare OAuth 라이브러리)은 "자체 OAuth 서버 없음" 원칙 때문에 뺐다.

### 선택: WorkOS AuthKit

1. Magus에 필요한 것이 기본으로 있다: CIMD(Claude 권장 방식), DCR 대체, RFC 8414 메타데이터, `aud` = MCP URL. 그래서 PyJWT + JWKS로 바로 검증된다.
2. 두 명이면 $0이다. 커스텀 도메인은 필요 없다(issuer는 `https://<이름>.authkit.app`).
3. 로그인 화면을 WorkOS가 호스팅한다(Stytch·Supabase는 직접 만든다). Google·이메일 코드·패스키를 쓸 수 있고 한국어로 나온다.
4. 가입을 끄고 초대만 남길 수 있다. 그래도 Magus는 허용 목록에 없는 `sub`를 따로 거부한다(이중 방어).
5. Claude 커넥터로 쓰이는 실제 사례(WorkOS 자체 MCP 서버)가 있다.

### Magus 쪽 구현(서비스에 묶이지 않음)

- `JwtVerifier`: JWKS(`AUTH_JWKS_URL`, 없으면 issuer 메타데이터에서 `jwks_uri` 탐색)로 서명을 검증한다. exp(여유 30초), iss, aud(기본 `PUBLIC_URL/mcp`)도 본다. 비대칭 알고리즘만 받는다(none·HS* 거부).
- `sub` → user_id는 `ALLOWED_USERS="sub=user_id,…"`로만 정한다.
  - 토큰이 무효하면 401이다. SDK가 `WWW-Authenticate … resource_metadata`를 붙인다.
  - 토큰은 유효한데 목록에 없으면 **403**이다(`ForbiddenGate`). 401이면 Claude가 로그인을 되풀이하기 때문이다.
- `current_user()`
  - 로컬(stdio)은 `USER_ID`를 쓴다. 원격은 검증된 토큰의 클레임(`magus_user_id`)을 쓴다.
  - 두 모드의 분기는 이 함수 안에만 있다. 동기 도구는 워커 스레드에서 돌지만 contextvar가 이어진다(격리 테스트로 확인).
- PRM: `/.well-known/oauth-protected-resource/mcp`. `resource` = `PUBLIC_URL/mcp`, `authorization_servers` = [`AUTH_ISSUER`].
- 로그에는 sub를 그대로 남기지 않는다(거부할 때는 sha256 앞 10자만).

## Result

- `tests/test_auth.py`(외부 인증 서버 없이 로컬 RSA 키 + 로컬 HTTP JWKS)
  - 받는 토큰: 유효하고 허용된 토큰만 받는다.
  - 거부하는 토큰: 만료, 다른 issuer, 다른 aud, 다른 서명 키, 모르는 kid, 허용 목록 밖, HS256 위조, JWT 아님.
  - 하위 프로세스 HTTP 서버
    - PRM의 resource가 커넥터 URL과 같다.
    - 토큰이 없거나 무효하면 401이고 `resource_metadata`가 붙는다. 허용 목록 밖은 403이다.
    - 앨리스가 임포트한 원고와 생각이 밥에게는 보이지 않는다. 감사 로그에는 user=alice·user=bob이 갈려 남는다.
- **실제 WorkOS 연결은 아직이다.** 사용자 계정이 필요하다(아래 "연결 절차"). 대기 상태다.

### 연결 절차(사용자, 5·6단계에서 실행)

1. WorkOS 계정을 만들고 AuthKit을 켠다. MCP 가이드(https://workos.com/docs/authkit/mcp)를 따른다.
   - CIMD와 DCR이 켜져 있는지 확인한다.
   - 리소스(audience)로 `https://<도메인>/mcp`를 등록한다.
2. 가입을 끄고(초대만) 두 사람을 초대한다. 로그인 방법은 Google과 이메일 코드를 켠다.
3. 서버 환경변수를 넣는다. `AUTH_ISSUER=https://<이름>.authkit.app`, `PUBLIC_URL=https://<도메인>`.
   - `AUTH_JWKS_URL`은 비워 둔다. 메타데이터에서 찾고, 안 되면 `https://<이름>.authkit.app/oauth2/jwks`.
4. 두 사람이 한 번씩 로그인하면 WorkOS 사용자 목록에 `user_…` id가 생긴다. `ALLOWED_USERS=user_…=default,user_…=father`로 넣는다.
5. Claude.ai → 커넥터 추가 → URL `https://<도메인>/mcp`. 등록 방식은 "Claude의 공개 신원 사용"(CIMD)이다.
   - **웹·Desktop·모바일에서 로그인과 토큰 갱신을 모두 확인한다**(알려진 위험).

## 위험과 대안

- WorkOS + claude.ai 로그인 실패 보고가 있다(#271·#620). 외부 인증 서버에서 토큰 갱신이 안 되는 문제(#228)도 열려 있다. 6단계에서 갱신까지 확인한다.
- 실패하면 **Descope**로 바꾼다(차선, CIMD·DCR·호스팅 동의 화면, `aud`에 MCP URL). 그다음은 Auth0다.
- Magus 쪽 코드는 표준(JWKS·iss·aud)만 쓰므로 환경변수만 바꾸면 된다.

**대안을 버린 이유**: Auth0는 신규 Google 가입을 막지 못하고 설정이 가장 많다. Stytch·Supabase는 동의 화면을 직접 만들어야 하고, Supabase는 1주 쉬면 정지된다. Clerk은 개발 인스턴스에서 Claude와 실패가 보고됐다. Logto는 무료로 MCP 리소스를 쓸 수 없다. Scalekit은 무료 여부가 불확실하다.

## 출처

- Claude: https://claude.com/docs/connectors/building/authentication · https://claude.com/docs/connectors/custom/add-unlisted · https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp · https://claude.ai/oauth/mcp-oauth-client-metadata
- MCP 스펙: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- WorkOS: https://workos.com/docs/authkit/mcp · https://workos.com/pricing · https://workos.com/docs/authkit/invite-only-signup · https://workos.com/docs/authkit/connect/token-claims · https://workos.com/blog/build-stateless-mcp-server-2026-07-28-authkit
- Auth0: https://auth0.com/pricing · https://auth0.com/blog/auth0-auth-for-mcp-servers-generally-available/ · https://auth0.com/docs/get-started/auth0-overview/create-applications/register-applications-with-cimd
- Stytch: https://stytch.com/docs/connected-apps/guides/mcp-auth-overview · https://stytch.com/pricing
- Descope: https://docs.descope.com/mcp · https://www.descope.com/pricing · https://www.descope.com/blog/post/cimd-support
- Clerk: https://clerk.com/changelog/2026-08-06-client-id-metadata-documents · https://clerk.com/pricing
- Scalekit: https://docs.scalekit.com/authenticate/mcp/quickstart/ · https://www.scalekit.com/pricing/auth-for-saas
- Supabase: https://supabase.com/docs/guides/auth/oauth-server · https://supabase.com/pricing · https://github.com/supabase/auth/issues/2850
- Logto: https://docs.logto.io/integrate-logto/third-party-applications/dynamic-apps · https://logto.io/pricing
- 실패 보고: https://github.com/anthropics/claude-ai-mcp/issues/271 · /620 · /1104 · /228
