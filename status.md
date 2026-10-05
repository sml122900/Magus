# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-05 KST — P1 5단계 배포(서버·HTTPS·SSH 키 전용·알림·alive·데이터 이전·백업·서버 복구 시험 같음). 웹 로그인 확인 대기. 태그 없음.

## 0-1. 최근 보고 (2026-10-05, WorkOS 설정)

- **사용자 결정**
  - WorkOS는 Production 환경을 쓴다.
  - 허용 목록은 지금 운영자 본인 → `default`(개발용 PDF 임포트본으로 6단계 시험)이다. 아버지는 나중에 `father`로 추가하고 docx 원본을 새로 임포트한다.
  - claude.com 콜백도 등록한다(docs에 "사용자가 추가로 등록함, 출처는 WorkOS 측 안내").
- **코드**
  - 웹 로그인 실패를 둘로 나눴다. 토큰 무효는 401("로그인 토큰을 받아들이지 못했습니다")이고, 허용 목록 밖은 403("허용 목록에 없습니다" + 본인 사용자 id)이다.
  - `JwtVerifier.check`가 실패 원인을 서버 로그에 남긴다: iss·aud 불일치(토큰 값과 기대 값), 만료(exp), 서명·kid(kid·alg), 형식. 토큰 값과 서명 조각은 남기지 않는다. 테스트로 확인했다.
  - `ALLOWED_USERS`가 비어 있어도 시작한다(경고, 모두 403). 첫 로그인으로 id를 얻는 단계에 쓴다.
- **문서**
  - docs/deploy.md: 0절(Production, 리디렉션 URI 3개, 리소스), 2-1절(첫 로그인 → 403 화면에서 id 얻기 → `.env` → `up -d` → 재로그인, 순서 default → father)
  - auth-provider.md 연결 절차, connect-claude.md, `deploy/.env.example`(도메인 기입, ALLOWED_USERS 비움)
  - **docs/onboarding-father.md**(7단계 초안, 비인용 용어 옮기기 포함)
- 테스트 190개 통과.

## 0. 최근 보고 (P1 5단계 준비)

- **호스팅 결정**(`docs/decisions/hosting.md`): Vultr 서울 VPS $5 + Docker Compose + Caddy(자동 HTTPS). 백업은 restic → Cloudflare R2(무료 10GB 안, 30일), 알림은 텔레그램 + healthchecks.io. 예상 월 $5 + 도메인.
- **배포 파일**
  - `Dockerfile`(비root uid 10001, healthz 헬스체크)
  - `deploy/compose.yaml`(magus·caddy·backup·restore), `deploy/Caddyfile`(접근 로그 끔: 주소에 내려받기 토큰이 있다)
  - `deploy/backup.sh`(index 제외·30일·부분 check·healthchecks 핑), `deploy/restore-test.sh`, `deploy/.env.example`
  - 운영 절차 `docs/deploy.md`
- **로컬 검증(Docker)**
  - 이미지 빌드. 원격 모드 컨테이너: `/healthz` ok, PRM resource 맞음, 토큰 없이 401, uid 10001, healthy.
  - **복구 훈련**: 실데이터 사본 53.4MB → 운영 `backup.sh`(restic 공식 이미지, 로컬 저장소) 34초·스냅샷 50.3MiB → `restic restore` 2,396개 → 컨테이너에서 reindex → default/book **outline 66줄 같음**. 사본·저장소·이미지는 지웠다.
- **알림**: `magus/alerts.py`(텔레그램 또는 웹훅, 백그라운드 전송), logsafe의 ERROR와 연결했다. `magus alert-test`.
- 새 CLI: `magus outline`(복구 비교용), `magus alert-test`.
- 6단계 문서 초안 `docs/connect-claude.md`(사용자용·아버지용, 배포 후 실제 화면으로 고친다).
- 테스트 188개 통과(알림 3, 복구 1 추가).

## 1. 지금 바로 할 일

- **6단계 진행 중 — 웹 완료, 대기: 모바일 시험과 다음 날 재접속(토큰 갱신) 확인, 사용자.** `p1-step6` 태그는 이 둘 뒤에 단다(사용자 지시).
  - 웹 결과(2026-10-05 23:05~23:13, 사용자): 넷 다 성공했다.
    - book_outline: 35장 + 서장·맺음·부록 1~3, 8부, 249,065자, 미확인 297, 미연결 0, 미해결 86(citation 44 · fact 40 · general 2).
    - 제12장 ref_check: 28편, 문단 번호 포함.
    - 제31장 요약: I78과 미확인 8편도 함께 언급.
    - idea_add: `20261005141301887-3e167c`.
  - 커넥터 화면은 "지금 로그인", "Claude의 게시된 ID 사용"(CIMD)을 감지했다. 로컬 magus 커넥터는 꺼 두었다.
  - 서버 로그(감사 로그는 인자를 남기지 않는다): book_outline 23:05:43 → ref_check 23:06:15 → book_read_chapter 23:10:24(31장 요약 동안 **1회**) → idea_add 23:13:01. auth 실패 없음.
    - 장 번호는 로그에 없다. 대화창의 도구 호출 입력에서 확인한다.
  - 등록 흐름: 23:01:21 `POST /mcp` 401 → PRM 200 → (WorkOS) → 23:01:57 `POST /mcp` 200(Bearer, `Claude-User`).
    - CIMD·DCR은 서버에서 보이지 않는다. 화면 선택이 CIMD였고, WorkOS 대시보드에 동적 등록 클라이언트가 새로 생기지 않았으면 CIMD로 확정한다.
  - 임시 Caddy 접근 로그는 되돌렸다(HEAD와 같음, caddy 재생성으로 쌓인 로그 삭제, 2026-10-05 23:2x).
    - 그사이 인증서 공개 뒤의 스캐너 접근(`GET /`, `/login`)이 보였다. 정상적인 인터넷 소음이다.
  - `docs/connect-claude.md`를 실제 화면 순서로 갱신했다(감지된 인증·CIMD, 요청 헤더 비움, 도구 메뉴에서 켜기, 로컬·원격 동시 사용 금지).
- **미해결: 영감 항목 삭제.** idea_delete 도구도, 웹 기능도 없다.
  - 지금은 운영자가 서버에서 `shelf/casper/<id>.json`을 지우고 reindex한다(connect-claude.md "영감 항목 지우기").
  - 테스트 메모 `20261005141301887-3e167c`는 서버 default 책장에 남아 있다. 사용자가 지우라고 하면 지운다.
- 확인됨(2026-10-05, 사용자)
  - 웹 로그인 성공: `/book`에 "닿으려는 종"(book, 40장)이 보이고 상단이 default다. PKCE 충돌 없음.
  - 텔레그램 "알림 시험"을 받았다. healthchecks magus-alive가 up이다(22:50·22:55 핑).
  - `p1-step5` 태그(`9b420a3`).
- 다음(6단계 뒤): 웹 페이지의 "장 40" 표기를 outline 표기(`35장 + 서장·맺음·부록 1~3`)와 같게 맞춘다(사용자 요청, 급하지 않음).
- **5단계 배포 결과(2026-10-05)**
  - 서버: Docker 29.1.3, Compose 2.40.3, ufw 22·80·443, 시간대 Asia/Seoul, unattended-upgrades 켬, 스왑은 Vultr 기본 2.3G.
  - SSH: 비밀번호 로그인 끔(`/etc/ssh/sshd_config.d/00-magus.conf`, 50-cloud-init보다 먼저 읽힘). 기존 세션을 열어 둔 채 새 세션 키 접속을 확인한 뒤 닫았다.
  - 서버는 이제 `publickey`만 제시한다. root는 prohibit-password.
  - 코드: git bundle → `/opt/magus`(현재 `21b4e2a`). `.env`는 600 root, `data/`는 uid 10001.
  - 확인(바깥에서)
    - `/healthz` ok, Let's Encrypt 인증서 발급, HTTP는 308로 HTTPS.
    - PRM resource = `/mcp`, 토큰 없이 401(+resource_metadata), `/login`은 WorkOS(S256·resource).
    - 로그 "허용 1명", 컨테이너 uid 10001.
  - 알림: 봇 토큰·chat id 유효(텔레그램 API getMe·getChat, 값 출력 없음), alert-test 보냄. alive.sh 핑 성공, cron 5분.
  - 데이터: 로컬 default의 projects·shelf(797개, 8.1MB, trash 제외)를 서버로 옮기고 reindex했다. outline이 로컬과 바이트 단위로 같다(66줄).
    - 처음에는 시각만 달랐다(컨테이너 UTC). compose에 `TZ: Asia/Seoul`을 넣어 고쳤다(`0c8e089`).
  - 백업: 첫 백업 24초, 스냅샷 `28e5e451` 7.7MiB, 오류 없음. cron 매일 04:00 KST(시간대 변경 뒤 cron 재시작). restic 0.19.1 고정(`21b4e2a`).
  - 복구 시험(서버, R2): `restore-test.sh default` 28초, outline 같음. deploy.md 기록 표에 적었다.
  - 운영 스크립트의 `docker compose exec·run`에 `</dev/null`을 붙였다(표준입력을 먹어 뒤 명령이 사라지는 것을 겪음).
- 접속 메모
  - 서버 접속은 Windows OpenSSH(`/c/Windows/System32/OpenSSH/ssh.exe`, Git Bash에서도 됨)와 사용자의 ssh-agent(id_ed25519, 사용자가 등록)를 쓴다.
  - Git Bash 기본 ssh는 한글 사용자 폴더 이름 때문에 키를 찾지 못한다.
  - 서버 호스트 키: ED25519 `SHA256:WchFUFNtRDD2D0JaTPPajWdFYWLfBxTmg+EgoumWuJo`.
  - 임시 배포 키는 만들었다가 쓰지 않고 지웠다(서버에 등록된 적 없음).
- 업데이트 절차: 로컬 `git bundle create magus.bundle master --tags` → scp `/root/magus.bundle` → 서버 `git pull /root/magus.bundle master` → `docker compose up -d --build`.
- 계정·설정(2026-10-05, 사용자)
  - WorkOS **Staging**(`https://dapper-palace-57-staging.authkit.app`, issuer 끝 `/` 없음). 10-05 오전의 Production 결정을 사용자 지시로 바꿨다.
  - Magic Auth 켬, 비밀번호 끔, 가입 끔, DCR·CIMD 켬, 리소스 `/mcp`(Default), 웹 리디렉션 `/auth/callback`.
  - 웹 클라이언트 `client_01M45PBRZEBZV6XEGJQSPWVH4P`(기밀).
  - `deploy/.env` 점검: 빈 값·형식 문제 없음. ALLOWED_USERS는 id만 있어서 값을 보지 않고 `=default`를 붙였다.
- 불명(승인됨): "P1 5~6단계 진행 지시" 원문이 없어 status.md와 docs/deploy.md 기준으로 진행했다(사용자 승인 2026-10-05).
- 불명
  - 완료 기준의 "refs 297": 실데이터 refs는 299건이다(파싱 실패 raw 1, acemoglu2001-2 포함). 297은 고유 미확인 문헌 수다. 판단: "refs 299, 미확인 문헌 297"로 검증한다.
  - 완료 기준의 "업로드한 docx": 실원고는 PDF만 있다(docx 없음). 판단: docx가 올 때까지 PDF로 검증한다. 대기: 원고 docx(사용자).

## 2. 현재 단계

**P1 진행 중 — 5단계 배포 완료, 웹 로그인 확인 대기**(`p1-step1`~`p1-step4`, `p1-step5`는 로그인 뒤). P0는 `step1`~`step7`, `p0-realdata`, `p0-report1`과 그 뒤 결정 반영 커밋까지 끝났다.

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
- [ ] P1 5단계 배포·도메인·HTTPS·백업·복구 테스트·알림 — **배포 완료 2026-10-05**, 웹 로그인 확인 뒤 `p1-step5`
  - 배포: `deploy/alive.sh`, `deploy/compose.yaml`(TZ·restic 0.19.1), `deploy/restore-test.sh`(</dev/null), `deploy/.env.example`(R2_*), 서버 `/opt/magus`
  - 서버 복구 시험 같음(docs/deploy.md 기록 표)
  - `Dockerfile`, `.dockerignore`, `.gitattributes`, `deploy/{compose.yaml,Caddyfile,backup.sh,restore-test.sh,.env.example}`, `src/magus/alerts.py`, `src/magus/cli.py`(outline·alert-test)
  - `docs/decisions/hosting.md`, `docs/deploy.md`, `tests/test_alerts.py`, `tests/test_restore.py`
- [ ] P1 6단계 Claude.ai 커넥터 등록, `docs/connect-claude.md`(초안만 있음)
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
61. **호스팅은 Vultr 서울 VPS + Docker Compose + Caddy**(`docs/decisions/hosting.md`)
    - 대안: Fly.io(도쿄, 볼륨이 머신 하나에 묶임), Railway(싱가포르, 요청 시간 제한), Lightsail(차선), Oracle 무료(회수 위험).
    - 이유: 서울이라 지연이 가장 작고, 디스크 제약·프록시 시간 제한이 없고, $5다.
62. **백업은 restic → R2, index.sqlite 제외, 30일, 매번 1/30 읽기 검사**
    - 대안: tar + 수명 주기 규칙(30개 전체 사본), rclone 동기화.
    - 이유: 암호화·중복 제거로 무료 10GB 안에 든다. 인덱스는 다시 만들 수 있어 실행 중인 DB의 일관성 문제가 없다. restic 저장소에는 수명 주기 규칙을 걸면 안 된다.
63. **알림은 텔레그램(서버 오류) + healthchecks.io(백업 누락)**
    - 대안: 이메일(Resend), Slack·Discord 웹훅(코드는 웹훅도 지원한다).
    - 이유: 휴대폰으로 바로 오고 무료다. 백업 누락은 "안 온 것"을 알아야 해서 데드맨 스위치가 맞다.
65. **허용 목록이 비어 있으면 시작은 하고 모두 거부한다**(이전: 시작 거부)
    - 대안: 임시 가짜 항목을 넣게 한다.
    - 이유: 첫 배포에서 로그인해 봐야 id가 보인다. 빈 목록은 닫힌 쪽(모두 403)이라 안전하다. 시작할 때 경고를 남긴다.
66. **웹 403 화면에 본인의 사용자 id(sub)를 보여 준다**
    - 대안: 숨기고 운영자가 WorkOS Users에서 찾는다.
    - 이유
      - 서명이 확인된 토큰의 sub라 **그 사람 자신의 id**다. 남의 정보가 아니다.
      - sub는 비밀번호·토큰 같은 자격 증명이 아니라 식별자다. 알아도 그것만으로 할 수 있는 일이 없다. 목록에 넣는 결정은 여전히 운영자가 한다.
      - 서버 로그에는 계속 해시만 남긴다. 화면은 본인만 본다.
      - 남는 위험: 허용되지 않은 사람이 운영자에게 "넣어 달라"고 부탁할 근거가 생긴다. 운영자가 거절하면 되는 수준이다.
      - MCP 쪽 403(JSON)에는 넣지 않았다. Claude가 그 본문을 사용자에게 보여 주는지 알 수 없다.
67. **401 원인 로그에 iss·aud·kid·exp 값을 함께 적는다**(토큰 값·서명은 빼고)
    - 이유: 설정 불일치는 실제 값을 봐야 고칠 수 있다(예: aud에 리소스 URL 대신 client id가 오는 경우). 이 값들은 비밀이 아니다.
64. **Caddy 접근 로그는 끈다**
    - 이유: 내려받기 링크 토큰이 주소에 들어 있다. 앱의 감사 로그(도구·사용자·시간)로 충분하다.

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

- **운영 확정값(2026-10-05 사용자)**: 도메인 `magus.lifebookapplication.com`, 서버 IP `158.247.225.48`, 커넥터 `https://magus.lifebookapplication.com/mcp`. WorkOS 대시보드 설정 진행 중(사용자).
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

**2026-10-05 (3)** — P1 5단계 배포
- env 점검(값 출력 없음)과 자가 점검(테스트 190·ruff·DNS·WorkOS 메타·compose 해석)을 했다.
- SSH: ssh-agent 문제는 사용자가 직접 풀었다.
- 서버 준비(Docker·ufw·시간대)를 하고, 비밀번호 로그인을 껐다(기존 세션 유지 절차).
- 번들로 배포했고, HTTPS·PRM·401·/login을 확인했다.
- 알림을 시험하고, alive cron을 걸었다.
- default 데이터를 옮겼다(outline 같음, TZ 수정). 첫 백업, 백업 cron, restic 고정, 서버 복구 시험(같음)까지 했다.
- 커밋 `6d2c5d2`, `0c8e089`, `21b4e2a`. 웹 로그인 확인 대기에서 멈춤.

**2026-10-05 (2)** — 배포용 env 파일
- `deploy/.env`를 만들었다. 비밀이 아닌 값을 채우고, SESSION_SECRET(64자 hex)은 로컬에서 만들어 바로 썼다(출력하지 않음).
- 비밀값 10개는 빈 값으로 두었다. 각 줄 위에 값의 출처를 주석으로 달았다.
- 확인한 것
  - git: `.gitignore:18`(`.env`)에 걸린다. 추적·이력 없음, `git add --dry-run`에도 잡히지 않는다.
  - Docker: `.dockerignore`가 `deploy`·`.env`를 빼므로 이미지에 들어가지 않는다.
- compose 보간을 가짜 값으로 시험했다. 같은 파일의 앞 키를 `${…}`로 참조할 수 있다. 따옴표 없는 `$`는 값이 잘리고(`a$b`→`a`), 작은따옴표로 감싸면 그대로 남는다. 파일 머리에 주의를 적었다.
- 사용자 대기에서 멈춤.

**2026-10-05** — WorkOS 대시보드 설정 지원
- 대시보드에 넣을 값을 코드·docs 근거로 표로 정리했다. 근거가 없는 것은 "모름·추정"으로 표시했다.
- 사용자 결정을 반영했다: Production, 허용 목록 순서, claude.com 콜백.
- 웹 로그인 401/403 문구를 나누고 원인을 로그에 남기게 했다. 빈 허용 목록으로 시작할 수 있게 했다. 403 화면에 본인 id를 보인다.
- docs: deploy.md 2-1절, onboarding-father.md 초안.
- 테스트 190개 통과, ruff(F·B) 통과. 커밋했다(태그 없음).

**2026-10-03 저녁(16:30~19:50)** — P1 1~4단계 완료(`p1-step1`~`p1-step4`), 5단계 준비(로컬 복구 훈련 outline 같음).

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
- **원격 미검증(계정 대기)**: 실제 WorkOS 로그인(웹·Claude 커넥터·토큰 갱신), Caddy 인증서 발급, R2 백업, 서버 위 복구 시험, 텔레그램 수신.
- **웹 업로드 크기**: Starlette는 multipart 파일을 디스크로 받으므로, 큰 요청은 `Content-Length`로만 미리 거른다(파일 한도 × 20 + 1MB). 청크 전송(길이 없음)은 다 받은 뒤 파일별 한도로 거른다.
- 이전부터 있던 것: 번호 충돌 가능성(멀티 프로세스), 직접 수정 뒤 reindex 필요, 토큰 추정 휴리스틱, 임베딩 API 실제 호출 미검증.
