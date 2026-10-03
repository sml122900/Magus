# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 17:05 KST — P1 1단계(HTTP 전송) 완료, 태그 `p1-step1`.

## 0. 최근 보고 (P1 1단계)

- **P1 킥오프**(원격 MCP 서비스). 스펙은 CLAUDE.md "P1" 절에 있다.
  - P0의 "Desktop 테스트 결과 대기"는 사용자의 P1 지시로 넘어갔다. 그 결과는 아직 받지 못했다.
- **1단계 완료**: streamable-http(stateless + JSON 응답), `/mcp` · `/healthz`.
  - 하위 프로세스 서버에서 18개 도구를 모두 HTTP로 불렀다(`tests/test_http.py`).
  - MCP Inspector(CLI, npx)로 tools/list 18개와 tools/call 3건(book_outline, ref_check, style_search)을 확인했다(임시 폴더의 demo 사용자).
- 로그 원칙을 코드와 테스트로 고정했다
  - `magus/audit.py`: 도구 호출마다 이름·user_id·ms·결과만 남긴다.
  - `magus/logsafe.py`: SDK의 도구 실패 메시지와 예외 traceback에서 내용을 지운다. 예외는 종류·위치만 남기고, ERROR는 알림 콜백으로 보낸다(10분에 한 번).
  - 테스트는 본문·발췌·생각·구절 표식이 서버 로그에 한 글자도 없는지 본다.
- 인증이 꺼진 HTTP는 루프백에만 열린다(`--host 0.0.0.0` 거부).
- 조사 두 건을 백그라운드로 돌렸다.
  - 호스팅·백업·알림: 끝났다. 5단계 결정 문서에 쓴다.
  - 인증 서비스: 진행 중이다. 2단계 결정 문서(`docs/decisions/auth-provider.md`)에 쓴다.

## 1. 지금 바로 할 일

- **2단계: 인증 서비스 연동.** 조사 결과로 `docs/decisions/auth-provider.md`(PAR, 비교표)를 쓰고 하나를 고른다.
  - 토큰 검증(JWKS 서명·exp·iss·aud), sub→user_id, `ALLOWED_USERS`를 넣는다.
  - 잘못된 토큰·만료·허용 목록 밖 거부를 테스트한다. 테스트는 로컬 RSA 키와 가짜 JWKS로 한다(외부 호출 없음).
- 대기(사용자): 인증 서비스 계정, 호스팅 계정, 도메인, 객체 스토리지 키, 알림 채널. 실제 연결은 사용자 계정이 있어야 한다. 그 전까지 코드와 문서를 준비한다.
- 불명
  - 완료 기준의 "refs 297": 실데이터 refs는 299건이다(파싱 실패 raw 1, acemoglu2001-2 포함). 297은 고유 미확인 문헌 수다. 판단: "refs 299, 미확인 문헌 297"로 검증한다.
  - 완료 기준의 "업로드한 docx": 실원고는 PDF만 있다(docx 없음). 판단: docx가 올 때까지 PDF로 검증한다. 대기: 원고 docx(사용자).

## 2. 현재 단계

**P1 진행 중 — 1단계 완료**(`p1-step1`). P0는 `step1`~`step7`, `p0-realdata`, `p0-report1`과 그 뒤 결정 반영 커밋까지 끝났다.

## 3. 단계별 체크리스트

- [x] P0 1~7단계 — `step1`~`step7`, 실데이터 `p0-realdata`, 첫 보고서 `p0-report1`, 결정 44건 확정(2026-10-03)
- [x] **P1 1단계 HTTP 전송** — 2026-10-03, `p1-step1`
  - `src/magus/transports.py`(http_app·run_http), `src/magus/audit.py`, `src/magus/logsafe.py`, `src/magus/cli.py`(`--host`·`--port`, 루프백 가드)
  - `tests/test_http.py`, `tests/test_logsafe.py`
- [ ] P1 2단계 인증(토큰 검증·sub→user_id·허용 목록)
- [ ] P1 3단계 받은함 + files_list + 경로 인자 전환
- [ ] P1 4단계 웹 페이지 4개
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
  - 태그: `step1`~`step7`, `p0-realdata`, `p0-report1`, `p1-step1`. P0 뒤 커밋 두 개(마무리 보완, 결정 반영)에는 태그를 달지 않았다(지시).
  - `/fixtures/`(루트)와 `data/`는 gitignore. `tests/fixtures/`와 `docs/reports/`는 커밋한다.

## 6. 마지막 세션 요약

**2026-10-03 저녁(16:30~17:05)** — P1 킥오프, 1단계
- CLAUDE.md에 P1 절(목표·비목표·아키텍처·순서·완료 기준)을 넣었다.
- streamable-http 전송, 도구 호출 감사 로그, 로그 거르기, 루프백 가드를 만들었다.
- HTTP로 18개 도구를 확인했다(pytest + MCP Inspector CLI).
- 테스트 161개 통과, ruff(F·B) 통과. `p1-step1` 태그.
- 남긴 것: 인증 서비스 조사 결과 대기(백그라운드). 호스팅 조사 결과는 받았다.

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
