# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 19:10 KST — P1 4단계(웹 페이지) 완료, 태그 `p1-step4`.

## 0. 최근 보고 (P1 4단계)

- **웹 페이지 4개**(`magus/web.py`, MCP와 같은 프로세스): `/login`, `/inbox`(업로드·목록·삭제), `/book`(임포트·docx 내보내기), `/checklist`(문헌 신호등 + 장별 집계), `/download/{token}`.
- **로그인**
  - 원격: WorkOS에 OAuth 인가 코드 + PKCE(S256) + `resource=PUBLIC_URL/mcp`로 로그인한다. 토큰은 MCP와 같은 검증기로 보고, 허용 목록 밖은 403이다.
  - 로컬(루프백, 인증 없음): `USER_ID`로 바로 로그인한다.
- 세션: HMAC 서명 쿠키(12시간, HttpOnly, SameSite=Lax, https면 Secure)이고, 모든 POST는 CSRF를 확인한다. 원격 모드는 `SESSION_SECRET`(32자 이상)이 없으면 시작을 거부한다.
- **book_export**(HTTP): 서명·만료(24시간) 내려받기 링크를 돌려준다. 같은 사용자로 로그인해야 받는다. 다른 사용자는 403, 위조·만료는 410이다.
- **브라우저로 한 바퀴 확인**(Claude in Chrome, 로컬 서버, 임시 폴더 demo 사용자, 합성 원고)
  - 받은함 업로드 → 원고 임포트(장 7·부 3·코멘트 13) → 인용 체크리스트(🟡 미확인 6, 장별 표)까지 갔다.
  - 그 과정에서 작은 파일이 "0.0 MB"로 보여 KB 표시로 고쳤다.
- 테스트 `tests/test_web.py`
  - 로컬 한 바퀴(+ CSRF 거부, 형식 거부, 링크 위조·로그인 필요)
  - 가짜 인증 서버로 원격 OAuth 로그인: PKCE·resource 확인, 앨리스/밥 받은함 격리, 남의 링크 403, carol 403
  - 서명 토큰 용도·만료, SESSION_SECRET 필수

## 1. 지금 바로 할 일

- **5단계: 배포·도메인·HTTPS·백업·복구 테스트·알림.** 계정이 없어도 할 수 있는 것부터 한다.
  - 호스팅 결정 문서: 조사 결과, 추천은 Vultr 서울 VPS + Docker Compose + Caddy.
  - Dockerfile·compose·Caddyfile, 백업 스크립트(restic → R2, 30일), 복구 절차, 알림(웹훅)을 만든다.
  - 복구 테스트는 로컬 restic 저장소로 먼저 해 본다.
- 대기(사용자). 실제 연결은 계정이 있어야 하고, 그 전까지 코드와 문서를 준비한다.
  - WorkOS 계정과 AuthKit 설정, 두 사람의 `user_…` id(→ `ALLOWED_USERS`)
  - 호스팅 계정과 도메인
  - 객체 스토리지 키
  - 알림 채널
- 불명
  - 완료 기준의 "refs 297": 실데이터 refs는 299건이다(파싱 실패 raw 1, acemoglu2001-2 포함). 297은 고유 미확인 문헌 수다. 판단: "refs 299, 미확인 문헌 297"로 검증한다.
  - 완료 기준의 "업로드한 docx": 실원고는 PDF만 있다(docx 없음). 판단: docx가 올 때까지 PDF로 검증한다. 대기: 원고 docx(사용자).

## 2. 현재 단계

**P1 진행 중 — 4단계 완료**(`p1-step1`~`p1-step4`). P0는 `step1`~`step7`, `p0-realdata`, `p0-report1`과 그 뒤 결정 반영 커밋까지 끝났다.

## 3. 단계별 체크리스트

- [x] P0 1~7단계 — `step1`~`step7`, 실데이터 `p0-realdata`, 첫 보고서 `p0-report1`, 결정 44건 확정(2026-10-03)
- [x] P1 1단계 HTTP 전송 — 2026-10-03, `p1-step1`
  - `src/magus/transports.py`, `src/magus/audit.py`, `src/magus/logsafe.py`, `src/magus/cli.py`, `tests/test_http.py`, `tests/test_logsafe.py`
- [x] **P1 2단계 인증** — 2026-10-03, `p1-step2`(코드·테스트. 실제 WorkOS 연결은 대기)
  - `src/magus/auth.py`, `src/magus/server.py`(current_user·AuthSettings), `src/magus/config.py`(auth), `tests/test_auth.py`
  - `docs/decisions/auth-provider.md`, `.env.example`
- [x] **P1 3단계 받은함** — 2026-10-03, `p1-step3`
  - `src/magus/inbox.py`(safe_filename·save_upload·FileResolver·files_list), `src/magus/store/{base,local}.py`(받은함 메서드·usage_bytes), `src/magus/config.py`(한도), `src/magus/cli.py`(`magus inbox`)
  - `tests/test_inbox.py`, test_http(요청 한도 413·경로 거부), 기존 테스트의 받은함 전환
- [x] **P1 4단계 웹 페이지** — 2026-10-03, `p1-step4`
  - `src/magus/web.py`, `src/magus/signing.py`, `src/magus/store/{base,local}.py`(export_path), `src/magus/book/tools.py`(내려받기 링크), `src/magus/cli.py`(웹 등록)
  - `tests/test_web.py`, 브라우저 확인(Claude in Chrome)
- [ ] P1 5단계 배포·도메인·HTTPS·백업·복구 테스트·알림
- [ ] P1 6단계 Claude.ai 커넥터 등록, `docs/connect-claude.md`
- [ ] P1 7단계 아버지 온보딩 체크리스트

## 4. 검토 대기 결정

**P1에서 새로 고른 것** (선택 / 대안 / 이유)

45. **HTTP는 stateless + JSON 응답**(`stateless_http=True, json_response=True`)
    - 대안: 세션 유지 + SSE 스트림.
    - 이유: 지시가 "세션은 상태 없이"다. 재시작·재배포에도 클라이언트 세션이 끊기지 않고, 프록시의 스트림 시간 제한(예: Railway 5분 무데이터, Cloudflare 125초)에 걸리지 않는다. 서버→클라이언트 알림은 쓰지 않는다.
46. **로그 거르기는 핸들러 단 필터**(`logsafe.RedactingFilter`)에서 한다
    - 대안: SDK 로거 레벨을 올려 끈다.
    - 이유: 끄면 장애 원인(예외 종류·위치)까지 사라진다. 메시지만 지우고 위치는 남긴다. uvicorn 로그도 `log_config=None`으로 같은 핸들러를 거친다.
47. **인증 없는 HTTP는 루프백에만 연다**
    - 대안: 경고만 낸다.
    - 이유: 실수로 0.0.0.0에 열면 누구나 default 사용자의 원고를 읽는다.
48. **감사 로그의 오류는 "ToolError"로만 적는다**(예외 종류는 logsafe 로그에 따로 남는다)
    - 이유: SDK가 예외를 결과(isError)로 바꾼 뒤라 미들웨어에서는 둘을 가를 수 없다.
49. **인증 서비스는 WorkOS AuthKit**(`docs/decisions/auth-provider.md`)
    - 대안: Descope(차선), Auth0, Clerk, Stytch, Supabase, Scalekit, Logto.
    - 이유: CIMD 기본, aud = MCP URL, 2명 무료, 호스팅 한국어 로그인. 코드는 표준만 써서 바꾸기 쉽다.
50. **허용 목록 밖(유효한 토큰)은 403, 무효 토큰은 401**
    - 대안: 둘 다 401.
    - 이유: 401이면 Claude가 다시 로그인하라고 되풀이한다. 403이면 "허용 목록에 없다"는 이유가 보인다.
51. **audience는 검증기가 직접 본다**(`validate_token_resource=False`, 기본 aud = `PUBLIC_URL/mcp`, `AUTH_AUDIENCE`로 여럿 허용)
    - 대안: SDK의 resource 비교.
    - 이유: 서비스마다 aud를 리소스 URL·클라이언트 id 등 다르게 넣는다. 설정으로 맞춘다.
52. **로그에 sub를 남기지 않는다**(거부할 때 sha256 앞 10자만)
    - 이유: sub는 외부 계정 식별자다. 허용 목록에 넣을 id는 WorkOS 화면에서 확인한다.
53. **로컬(stdio)에서는 받은함에 없으면 로컬 경로도 받는다**(원격은 이름만)
    - 대안: 모든 모드에서 받은함 이름만 받는다.
    - 이유: P0의 Desktop 사용(README "첫 실행 확인"의 fixtures/papers 시연)을 깨지 않는다. 원격에서 경로를 받으면 서버 파일을 읽힐 수 있어 막는다. 분기는 FileResolver 한 곳에 있다.
54. **한도 기본값: 업로드 50MB, 사용자 1,000MB, 요청 2MB**
    - 근거: 실원고 PDF 6.7MB, 실사용자 폴더 53MB(재임포트 휴지통 포함), 가장 긴 장 약 2만 자(60KB).
    - 저장 용량은 사용자 폴더 전체(휴지통 포함)로 센다. 업로드할 때만 검사한다.
55. **받은함은 SQLite에 색인하지 않는다**(폴더를 그대로 읽는다)
    - 이유: 파일이 진실이고 목록이 짧다. P2(객체 스토리지)에서는 Store 구현이 목록을 준다.
56. **웹은 서버에서 그린 HTML(템플릿 엔진 없음), MCP와 같은 Starlette 앱**(`server.custom_route`)
    - 대안: Jinja2, 별도 프런트엔드(SPA).
    - 이유: 지시가 "같은 프로세스, 가벼운 것"이다. 의존성이 늘지 않고 페이지가 넷뿐이다. 값은 모두 html.escape로 이스케이프한다.
57. **웹 로그인은 별도 OAuth 클라이언트(WEB_CLIENT_ID) + PKCE + resource 지시자**
    - 대안: MCP 토큰을 웹에서 재사용(불가능), 인증 서비스의 세션 위젯.
    - 이유: 같은 aud(PUBLIC_URL/mcp) 토큰을 받으므로 MCP와 같은 검증기·허용 목록을 쓴다. 서버 쪽 세션만 둔다.
58. **세션은 서명 쿠키(서버 저장 없음), 12시간, CSRF는 세션 sid의 HMAC**
    - 이유: 단일 인스턴스·두 사용자라 서버 세션 저장소가 필요 없다. 재배포해도 SESSION_SECRET이 같으면 유지된다.
59. **내려받기는 서명 링크(24시간) + 같은 사용자 로그인 둘 다 필요**
    - 대안: 링크만으로 받기.
    - 이유: 링크가 대화 기록에 남는다. 링크만으로 원고가 새면 안 된다.
60. **로컬 HTTP의 웹은 USER_ID로 자동 로그인**(루프백 전용이라)
    - 이유: 개발 중 브라우저로 한 바퀴 돌려 보려면 인증 서버 없이도 돼야 한다.

**P0 결정**: #1~#44 모두 확정됐다.

**확정 기록**
- 2026-10-03 오전 답변: #1, #15, #16, #17(고유 문헌 수로 변경), #20, #22, #25.
- 2026-10-03 마무리 보완 지시: #41(변경: outline은 책 전체 고유 수), #42(사용자가 정정).
- 2026-10-03 35건 답변
  - 승인(그대로): #2 #3 #4 #7 #8 #9 #10 #12 #13 #14 #18 #19 #21 #23 #26 #27 #30 #32 #34 #35 #37 #38 #39 #40 #44
  - 보완 후 확정
    - #5: key 충돌 -2는 유지한다. 같은 문헌이 두 번이면 "중복 서지 N건"으로 따로 리포트한다.
    - #6: 기존 key는 보존한다. 새 목록의 제목·연도가 다르면 "기존 서지와 다름" 목록을 남긴다(갱신하지 않음).
    - #11: 합성 fixture는 `tests/fixtures/synthetic/`에 두고 커밋한다. 실데이터 `fixtures/`와는 분리한다.
    - #24: 문체 키워드 색인에 work도 넣는다. 임베딩 대상은 reason + tags 그대로다.
    - #28: 추정은 저장하지 않는다. 확정은 `magus alias <key> <표기>`로 한다.
    - #29: uncertain은 미확인 수에서 빼되, outline "미연결 N"과 ref_check 별도 목록으로 보인다.
    - #31: a/b가 모호하면 잇지 않는다. 후보 둘을 보이고 상태는 unverified다.
    - #33: Downloads 복사 결과는 수용한다. 규칙은 "사용자에게 요청하고 멈춤"(CLAUDE.md에 이미 있음).
    - #36: 비인용 용어만 걸린 출처 확인 코멘트도 fact다. general은 확인 요청이 아닌 코멘트에만 쓴다.
    - #43: 캐시는 유지한다. ref_add로 문헌 상태가 바뀌면 즉시 다시 계산한다.
      - 지금은 refs가 바뀔 때 모든 장을 다시 계산한다. 실원고 0.3초이고, 그 문헌이 나오는 장을 포함한다.
      - ref_add 직후 outline 수가 줄어드는지 테스트로 고정했다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음). Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 실패한다. 그때는 `uv add --no-sync`와 `uv pip install`을 쓴다.
- **Python** 3.12(.venv). **MCP SDK** mcp 2.2.0.
- **의존성**: python-docx 1.2.0, pymupdf 1.28.2, pypandoc-binary 1.17(pandoc 3.9), numpy 2.5.3, lxml. ruff 0.16(개발용, `--select F,B`로 점검).
- **Node** v22.23.2(fnm). MCP Inspector는 `npx -y @modelcontextprotocol/inspector --cli …`로 쓴다.
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=8`. 버전이 바뀌면 처음 열 때 자동으로 다시 만들고, 서버가 시작할 때 파생값을 다시 계산한다.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`(USER_ID=default, DATA_DIR=C:\project_2026\Magus\data → FILES_DIR 기본 C:\project_2026\Magus)
  - 로그: `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`. 시작 줄에 files_root가 찍힌다.
  - 위 두 경로는 프로젝트 폴더 밖이다. 사용자가 이 세션에서 경로를 적어 지시할 때만 읽는다.
- **데이터 사용자**
  - `default`: 실원고 `book`(비인용 용어 5개), refs 299, 실대화 452발화, 문체 0
  - `demo`: 데모 프로젝트·표본
  - `synthetic`: 합성 synth
- **fixtures**
  - 실데이터(gitignore): `fixtures/261002-닿으려는_종_전면개정_그림추가.pdf`, 대화 md 4개, `fixtures/papers/`(비어 있음, 사용자가 논문 PDF를 둔다).
  - 합성(커밋): `tests/fixtures/synthetic/`(원고 docx·pdf, 대화 md 3개, 야간 작업 리포트).
- **명령**(Bash, 프로젝트 루트에서 실행. 콘솔 한글은 `PYTHONIOENCODING=utf-8`)
  ```
  .venv/Scripts/python -m pytest -q -p no:cacheprovider
  .venv/Scripts/python -m ruff check --select F,B src tests
  DATA_DIR=./data .venv/Scripts/python -m magus import fixtures/<원고>.pdf --project-id book --title "닿으려는 종" --replace > data/realdata/import-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus cite-report --project-id book > data/realdata/cite-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus author-report --project-id book --out docs/reports/<날짜>-인용-점검.md
  DATA_DIR=./data .venv/Scripts/python -m magus terms --project-id book [--add …] [--remove …]
  DATA_DIR=./data .venv/Scripts/python -m magus alias <key> <표기>
  DATA_DIR=./data .venv/Scripts/python -m magus reindex
  ```
- **git**
  - master에 바로 커밋하고, 단계가 끝나면 태그를 단다. 실험은 브랜치에서 하고 squash merge한다.
  - 태그: `step1`~`step7`, `p0-realdata`, `p0-report1`, `p1-step1`~`p1-step4`. P0 뒤 커밋 두 개(마무리 보완, 결정 반영)에는 태그를 달지 않았다(지시).
  - `/fixtures/`(루트)와 `data/`는 gitignore. `tests/fixtures/`와 `docs/reports/`는 커밋한다.

## 6. 마지막 세션 요약

**2026-10-03 저녁(16:30~19:10)** — P1 킥오프, 1~4단계
- 1단계 HTTP 전송(`p1-step1`), 2단계 인증(`p1-step2`), 3단계 받은함(`p1-step3`), 4단계 웹(`p1-step4`).
- 브라우저(Claude in Chrome)로 업로드 → 임포트 → 체크리스트를 확인했다.
- 테스트 184개 통과, ruff(F·B) 통과.
- 남긴 것: 5단계(배포)부터. 계정·도메인이 필요한 일은 대기.

## 7. 알려진 문제 — 실원고에서 아직 안 맞는 것

- **표**: 칸 구분 없이 한 문단으로 들어온다(27장 등). 표 안의 도시 설립 연도는 비인용 용어 파일로 걸렀다(그대로 둠, docx 재임포트 때 다시 본다).
- **수식·그림**: 수식은 텍스트 그대로(`g_Y ≈ g_N + g_y`), 그림 10개는 `[그림 N]` 자리표시자다(그대로 둠).
- **코멘트 앵커**: PDF에서는 말풍선 높이의 문단 단위로 근사한다. 앵커에 인용이 하나뿐이면 그 문헌으로 잇기 때문에, 사실·수치 요청 일부(I81·I82 인구 수치)가 citation(buckley2010)으로 분류된다(#30 승인).
- **원고 쪽 불일치**(보고서 2·3절, 저자 답변 대기)
  - `Brook(2008)` vs 참고문헌 Brook 2010, `Wiessner(2014)` vs 참고문헌 Wiessner 1982. I12(wiessner2014)는 refs에 연결되지 않는다.
  - 참고문헌에만 있는 4건(Graunt, Lattimore, Lee, Nordhaus). 본문에는 이름만 나온다.
  - 음역 추정 6건(하야시·후닝·김성은·크레머·모리스·넌). 케인스(1930)는 a/b 후보 둘이고 잇지 않았다. Acemoglu 2001 두 편.
- **참고문헌 파싱 실패 1**: `張楠(장남). (명대). 『神峰通考』`(숫자 연도 없음, raw로 보관, 그대로 둠).
- **Desktop 실사용 미검증**: 서버 쪽 경로 흐름은 테스트와 리허설로 확인했지만 Desktop에서 실제로 부른 기록은 아직 없다. 시험 문장 3(제31장 요약)은 Claude가 다른 장을 더 읽지 않는지 보는 것이라 Desktop에서만 확인할 수 있다.
- **보고서 쪽수**: Word·LibreOffice가 없어 글자폭으로 추정했다(약 2.3쪽). Word에서 열어 확인이 필요하다.
- 이전부터 있던 것: 번호 충돌 가능성(멀티 프로세스), 직접 수정 뒤 reindex 필요, 토큰 추정 휴리스틱, 임베딩 API 실제 호출 미검증.
