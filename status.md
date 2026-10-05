# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-06 03:02 KST(서버 시각) — `p1-ui-terms` 서버 배포(UI·용어 #85·#86·세 책장·허용 목록 중복 거부). 되돌리기 기준 `4df2720`. 대기: 사용자가 claude.ai 커넥터를 끊고 다시 연결해 '전체 보여 줘' 확인. 그다음 아버지 첫 세션.
> 2026-10-06 01시 KST — 토큰 aud 검사 강화(결정 #79)를 `p1-auth-audience`로 서버에 반영하고, 서버의 옛 git 이력을 새 이력으로 바꿨다(0-3절).

## 0-7. 최근 보고 (2026-10-06, 서버 배포 `p1-ui-terms`, 세션 magus-25)

- 배포 전 추가: `ALLOWED_USERS`에 같은 sub·같은 이름이 두 번이면 시작하지 않는다(`2d9777f`, 오류에는 항목 순서만). 서버 `.env` 값을 로컬 파서에 바로 흘려 미리 돌렸다(값은 출력·저장하지 않음): 1줄, 통과, 허용 2명, 이름 2개.
- 태그 `p1-ui-terms` = `2d9777f`(annotated). master·태그 push(`121e55d..2d9777f`, 7커밋: 85cb2f5·61e5e77·aa9d309·cd66d2b·436e894·9fd0295·2d9777f). 보내기 전 금지 경로(data·fixtures·private·.env)·비밀·실제 id 패턴 0건.
- **서버 배포(2026-10-06 03:01~03:02, 서버 시각 KST)** — 기록 `/root/deploy-20261006-ui-terms/`(ROLLBACK.txt, head-before/after.txt, data-before/after.sha, env-before.sha, backup-before.log, up.log)
  - 반영 전 실행 커밋: `4df2720`(`p1-reupload`, master, 작업 트리 깨끗). **이것이 이번 되돌리기 기준이다.** 반영 후 `2d9777f`(`p1-ui-terms`).
  - 반영 전 백업을 손으로 실행: 성공, 스냅샷 `8ea57cec`, 파일 798개 7.711MiB, 검사 오류 없음.
  - 되돌리기 이미지: 반영 직전 이미지를 `magus:rollback-4df2720`(61dc0c7d1994)으로 남기고 옛 `magus:rollback-896633c`는 지웠다.
  - 절차: 새 bundle(로컬과 sha256 같음) → `git fetch` master·태그 → `p1-auth-audience`·`4df2720` 포함 확인 → `git checkout -B master p1-ui-terms` → `docker compose up -d --build`. Dockerfile·deploy/는 두 커밋 사이에 바뀐 것이 없다. `deploy/.env`(해시 같음)와 `data/`는 건드리지 않았다.
  - 확인: healthy·재시작 0, 로그 `허용 2명`, 바깥 `/healthz` ok, `/mcp` 401 + resource_metadata, data 원본 798개 해시 같음(index 제외), 메모리 magus 123MiB·caddy 26MiB·호스트 available 469MB, 디스크 49%.
  - 새 문구: 원격 `/login`은 HTML 없이 WorkOS로 303이라, 바깥 오류 페이지(`/download/x`)에서 상단 바 `Magus`와 입력칸 테두리 `--mute` CSS를 확인했다. 메뉴는 로그인 뒤에만 그려지므로 컨테이너 안에서 임시 로컬 서버(루프백 8799, `/tmp` 임시 폴더, 인증 끔)를 띄워 `확인 요청`·`생각` 메뉴, `수정본으로 올리기`, 생각 화면 예문을 확인하고 지웠다(남은 프로세스 없음, data 해시 그대로).
- 아버지 공간(`data/users/father`)은 아직 없다(첫 쓰기 전).
- 대기(사용자): claude.ai 설정에서 Magus 커넥터를 끊고 다시 연결한 뒤, 새 대화에서 "전체 보여 줘"로 확인(새 instructions 규칙 7~9를 받으려면 다시 연결해야 할 수 있다).

## 0-6. 최근 보고 (2026-10-06, 사용자 격리 점검 — 아버지 계정 추가 전, 세션 magus-25)

- 코드 읽기와 시험만 했다. 서버는 바꾸지 않았다. 막혀 있지 않은 곳은 찾지 못했다(고칠 것 없음).
- 사용자 공간이 정해지는 길
  - MCP: `Authorization: Bearer` → `ForbiddenGate`(auth.py: 유효하지만 목록 밖이면 403) → SDK가 `JwtVerifier.verify_token`(서명·exp·iss·aud 하나, 결정 #79) → `user_of` = `ALLOWED_USERS`의 sub → user_id(시작할 때 읽음) → `AccessToken.claims["magus_user_id"]`(서버가 넣는다. 토큰 안의 같은 이름 클레임은 쓰지 않는다)
  - → 도구는 모두 `current_user()`(server.py, 유일한 결정 지점)로 user_id를 얻는다 → Store 메서드는 user_id를 인자로 받는다
  - → 파일: `_user_dir`(local.py, `safe_id`), 프로젝트 `safe_id`, 문헌 key `safe_ref_key`(shelf.py), 받은함 `safe_filename` + `_inbox_file`(폴더 밖이면 거부), 원격은 `FileResolver`가 받은함 이름만(local_paths는 stdio만)
  - → 인덱스: 모든 쿼리에 `user_id` 조건(여러 줄 SQL의 다음 줄 포함 확인). FTS는 `chunks` JOIN 뒤 `c.user_id`, 벡터·임베딩 갱신도 user_id
  - 웹: `/login` → WorkOS(PKCE, resource) → `/auth/callback`에서 같은 `JwtVerifier.check` + `user_of` → 세션 쿠키 `{uid, sid}`(HMAC, 용도 "session", 12시간) → 요청마다 `Web.user_of`가 서명·만료와 **uid가 지금 허용 목록에 있는지** 본다 → 페이지는 모두 세션 uid로 Store를 부른다(`?project=`도 그 사용자 안에서만 찾음)
  - 내려받기: `export_link`가 `{u, p, f}`를 용도 "download"로 서명(24시간) → `/download`는 서명 + 같은 사용자 세션 둘 다 요구, 파일은 세션 사용자 공간에서만 찾는다(`export_path`)
- 항목별 결과(시험)
  - A의 MCP 호출로 B의 원고·미해결·문헌·영감·받은함: **이미 있음**(test_search::test_every_tool_is_user_scoped, test_auth::test_remote_auth_rejects_and_isolates_users) + **추가**(같은 id·key·파일 이름을 쓰는 두 사용자, reindex 뒤 포함: test_isolation::test_same_ids_in_two_users_never_mix)
  - 파일 이름 인자에 ../·절대 경로·다른 사용자 이름: **일부 있음**(test_inbox 이름 검사) + **추가**(book_import·ref_add·idea_add_conversation의 경로 7가지, 문헌 key 경로, project_id 경로, book_export 경로 → 밥의 공간 해시 그대로: test_file_arguments_cannot_reach_other_spaces)
  - A의 웹 세션으로 B의 페이지: **일부 있음**(받은함만) + **추가**(둘 다 project id `synth`일 때 /book·/issues·/checklist·/inbox, 남의 받은함 파일 임포트·삭제, 경로 이름 업로드, 남의 프로젝트 내보내기: test_web_pages_are_per_user_even_with_same_project_id)
  - 내려받기 링크를 다른 사용자가 쓰기·만들기: **이미 있음**(test_web: 밥이 앨리스 링크 403, 서명 위조·만료·용도) + **추가**(목록에서 빠진 뒤 링크도 로그인으로)
  - FTS·SQLite 결과 섞임: **추가**(FTS와 벡터 검색, 같은 문헌 key) + SQL 문 전수 확인
  - 허용 목록 밖 sub 403: **이미 있음**(MCP·웹). 목록에서 지운 뒤 기존 토큰·세션: **추가**(재시작 뒤 토큰 403, 세션·링크는 로그인으로, 남은 사용자 세션은 그대로: test_removed_user_loses_token_and_session, test_web_session_ends_when_user_is_removed)
  - 토큰 클레임으로 사용자 고르기(`magus_user_id`·`user_id` 클레임 넣기): **추가**(무시된다: test_token_claims_cannot_choose_the_user)
  - 동시 요청에서 사용자 맥락 섞임: **추가**(실제 HTTP, 두 사용자 40회 동시: test_concurrent_requests_keep_their_own_user)
  - 시험이 실제로 잡는지: FTS의 user_id 조건 빼기, 원격에서 로컬 경로 허용, 웹 세션이 허용 목록을 안 보기 — 세 변조 모두에서 해당 시험이 실패함을 확인했다(코드는 바꾸지 않음).
- 남는 위험(코드 문제 아님, 운영 절차): `ALLOWED_USERS`에 아버지 sub를 실수로 `=default`로 넣거나, 두 sub를 같은 user_id로 넣으면 공간을 함께 쓴다. 온보딩 A절의 "아버지가 다시 로그인해 `/book`이 비어 있는 것을 확인"이 이것을 잡는다. 시작할 때 같은 user_id가 두 번이면 경고하는 것은 검토 대기 후보(낮음).
- 목록에서 지우기는 `.env`를 고치고 `docker compose up -d`(재시작)해야 효과가 난다. 그 전까지는 기존 토큰·세션이 통한다.
- 테스트 230개 통과(격리 시험 7개 추가), ruff 통과. 커밋만 하고 push는 다음 태그 때.

## 0-5. 최근 보고 (2026-10-06, 서버 배포 `p1-reupload` + 아버지 자료용 데이터, 세션 magus-25)

- 결정 #80~#83 반영(`4df2720`). `docs/worktree-rule`(끝 `195af55`)은 앞 요청에서 병합해 push했다(`e396d3f`).
- 태그 `p1-reupload` = `4df2720`(annotated). master·태그를 push했다(`e396d3f..4df2720`, 금지 경로 0건).
- **서버 배포(2026-10-06 01:38~01:40, 서버 시각 KST)** — 기록 `/root/deploy-20261006-reupload/`(ROLLBACK.txt, data-before/after.sha, backup-before.log, up.log)
  - 반영 전 실행 커밋: `896633c`(`p1-auth-audience`, 브랜치 `fix/auth-audience`, 작업 트리 깨끗). **이것이 이번 되돌리기 기준이다.**
  - 반영 전 백업을 손으로 실행: 성공, 스냅샷 `a3322693`, 파일 798개 7.7MiB, 보관 정책 일별 30 + 월별 12, 검사 오류 없음.
  - 반영 전 이미지를 `magus:rollback-896633c`로 남겼다. 옛 `magus:rollback-21b4e2a`는 지웠다.
  - 절차: 새 bundle(로컬과 sha256 같음) → `git fetch` master·태그 → `p1-auth-audience` 포함 확인 → `git checkout -B master p1-reupload` → `docker compose up -d --build`. `deploy/.env`(해시 그대로)와 `data/`는 건드리지 않았다. 배포 스크립트·Dockerfile은 두 커밋 사이에 바뀐 것이 없다.
  - 확인
    - 컨테이너 healthy, 로그 `인덱스 스키마 v12 생성 → 파일에서 재생성`(01:39:52), 시작 완료 01:39:55, `허용 1명`
    - 바깥 `/healthz` `{"status":"ok"}`, `/mcp` 401 + `resource_metadata`
    - data 원본 798개(index.sqlite 제외) 해시가 반영 전과 같다. index.sqlite만 새로 만들어졌다.
    - 서버 default outline이 반영 전 수치와 같다: 249,065자, 미확인 문헌 297, 미해결 86. 판 줄 "판 기록 없음(다시 올리기 기능 전 임포트) · 임포트 10-03 15:40"이 새로 보인다.
    - 메모리(1GB 서버): magus 컨테이너 123MiB, caddy 30MiB, 호스트 used 515MB·available 440MB, 스왑 61MB. 디스크 `/` 9.7G/23G(45%).
- 아버지 자료용 데이터: `private/reports/2026-10-06-father-materials-data.md`(396줄, 리포 밖). father-trial(최신본, 비인용 용어 6개) 기준이다.
  - 이전 판 질문 8건은 모두 최신본에서도 유효하다(음역 추정 7건은 제35장 본문이 아니라 표 안에 있다).
  - 저자 보고서 생성기의 작은 오탐 두 개는 자료에서 바로잡았다: 같은 장 번호가 두 번 찍힘("제35·35장"), Lee(1969) 이름 대조에 '이상호'가 섞임(7절).
- 대기: claude.ai 새 대화에서 Magus의 book_outline을 한 번 불러 확인(사용자).

## 0-4. 최근 보고 (2026-10-06, #69~#77 구현 + 다시 올리기 기본 + 최신본 재임포트, 세션 magus-25)

- 로컬 전용. 서버와 default는 건드리지 않았다(default 파일 1,383개 해시가 세션 시작 때와 같다).
- 구현(단계마다 테스트를 넣고 커밋, 테스트 190 → 223개)
  - #74 규칙 4(`9688878`), #69 표(`e1b57b7`), #70 제N부 들어가며(`0df3d1c`), #71 작성자·AI 확인 요청(`1708217`)
  - #72 [점검·…] 분류(`1d78eb6`), #73 앵커 전문·문단 번호(`fc6bdec`), #77 제목·부제(`393f5e0`)
  - #76 다시 올리기 기본(`ef903d1`), PDF 미해결 잇기 보완(`0109ad4`), 괄호 저자 제목·리포트 장 수(`a1c9a12`)
  - 다른 세션 magus-a1의 #79(aud) 작업을 master에 병합했다(`9162a8b`). 그 세션이 `1d78eb6`까지 push했다.
- `father-trial` 최신본 재임포트(비우고 새로): 42장(35장 + 서장·부 들어가며 2·맺음·부록 1~3), 8부(부 이름 바로잡힘), 343,185자(표 37개 포함)
  - 미해결 129: citation 43 · fact 82 · general 4, 작성자 Claude(AI) 129, 장 밖 2(참고문헌), 걸린 문장 잘림 0(최대 426자 전문 저장)
  - 참고문헌 337줄 → refs 337, 인용 출현 454, 고유 미확인 335(참고문헌에 없음 3), 미연결 2, 중복 서지 1(IEA), key 충돌 2(acemoglu·hsieh)
  - outline 2,231토큰(추정). 자료: `data/realdata/2026-10-06-father-trial-{import-report-v2,cite-report-v2,verify}.md`
- 다시 올리기 시험
  - `reupload-trial`: 4판 docx(E1, 코멘트 86) → 최신본(E2). 바뀐 장 6만 교체(36장 버전 그대로), 기존 미해결 86 유지 + 새 43, 결정·직접 미해결·영감·책장 그대로, 닫은 미해결은 닫힌 채.
  - `reupload-trial-pdf`(보조): 10/02 PDF(E1) → 최신본(E2). 기존 86을 코멘트 본문으로 잇고 새 43, 새 refs 38, hsieh2019는 talent 그대로·housing이 -2.
  - 자료: `data/realdata/2026-10-06-reupload-trial*.md`

## 0-3. 최근 보고 (2026-10-06, 토큰 aud 검사 강화 + 서버 반영)

- 배경: 자매 서비스 trip_ai가 같은 WorkOS 환경(Staging)을 쓰게 된다. 사용자 본인의 sub가 두 서비스에서 같아서, aud를 느슨하게 보면 trip_ai용 토큰이 Magus를 통과한다. 지시: "질문하지 말고 진행하되, 결정은 status.md에 적는다" → 결정 #79(4절).
- 0단계 확인
  - 서버 실행 커밋: `21b4e2a`(옛 이력) + 작업 트리의 `deploy/backup.sh` 수정(#62판, 해시 `07ff437`). 새 이력에서는 `decf79c`와 트리가 같다(`docs/reports` 2개만 다름).
  - 그 뒤 master: `eff78d5`~`d77c4d5`는 문서와 backup.sh(#62)뿐이다. 이 작업 중에 다른 세션(magus-25)이 `785623a`(#69~#78 확정), `9688878`(#74), `e1b57b7`(#69), `0df3d1c`(#70)를 커밋했고 #71~ 진행 중이다. 그 작업은 서버에 배포하지 않았다.
  - 서버 `.env`: `PUBLIC_URL=https://magus.lifebookapplication.com`, `AUTH_AUDIENCE` 줄 없음(= `PUBLIC_URL/mcp`). 멈출 조건이 아니었다.
  - magus-alive: 호스트 cron 5분 `deploy/alive.sh`가 **바깥 주소** `https://magus.lifebookapplication.com/healthz`(DNS·Caddy·HTTPS·앱)를 curl한 뒤 healthchecks.io에 핑한다. `/healthz`는 있다(인증 없음, `{"status":"ok"}`). 컨테이너 헬스체크(Dockerfile)는 따로 안쪽 `127.0.0.1:8000/healthz`를 본다.
- 구멍은 실제로 있었다(옛 코드로 재현): 구멍 2(aud 목록 `[magus, trip_ai]` 통과)는 운영 설정에서도 열려 있었다. 구멍 1(`AUTH_AUDIENCE`로 넓히기)은 운영 `.env`에 값이 없어 열려 있지 않았다. 안내 문구는 `docs/deploy.md`가 아니라 `docs/connect-claude.md` 진단 표에 있었다.
- 고친 것(`fix/auth-audience`, `decf79c`에서 갈라 만듦, 태그 `p1-auth-audience` = `896633c`)
  - `78c9668`: 서버가 쓰던 backup.sh(#62)를 브랜치에 넣었다. reset 뒤에도 보관 정책이 30일로 되돌아가지 않는다.
  - `896633c`: aud는 `PUBLIC_URL/mcp` 하나(문자열, 또는 원소 하나인 목록), `AUTH_AUDIENCE`가 다르면 시작 실패(종료 2, 한국어 이유), 거부할 때 aud 모양을 로그에. 웹 로그인은 같은 `JwtVerifier` 객체를 쓴다(확인). 결정 문서 `docs/decisions/shared-auth-audience.md`.
  - 테스트 191개 중 190개 통과. 실패 1개는 알려진 간헐 실패 `test_request_size_limit`(따로 5번 중 3번 통과).
  - master 병합: 충돌 없음. 병합 뒤 `docs/connect-claude.md` 진단 표, `docs/deploy.md` 업데이트 절차·반영 기록, 이 파일, CLAUDE.md 진행상황을 고쳤다.
- 서버 반영(2026-10-06 00:53 KST): 새 이력 bundle → 옛 태그 삭제 → fetch → `reset --hard p1-auth-audience` → 브랜치 이름 `fix/auth-audience` → `up -d --build` → 확인 뒤 `reflog expire` + `gc --prune=now`.
  - 실행 커밋: `21b4e2a`(옛 이력) → `896633c`. 작업 트리 깨끗, backup.sh 해시 그대로, `.env` 해시 그대로.
  - data: 798개 파일(index.sqlite 제외) 해시가 반영 전후 같다. index.sqlite도 크기·시각 그대로다.
  - 확인: 바깥 `/healthz` ok, `curl -sI /mcp` 401 + `resource_metadata`, PRM resource = `…/mcp`, 컨테이너 재시작 0회.
    - 컨테이너 안(배포된 코드, 운영 issuer·resource에 시험용 키): trip_ai 문자열·섞인 목록 두 순서 거부, 문자열·원소 하나인 목록 통과.
    - `docker compose run -e AUTH_AUDIENCE=<trip_ai>`: 종료 2, 한국어 이유 출력.
  - 옛 이력 정리: `21b4e2a`, 보고서 객체 2개 없음, 객체 1,867 → 668. `/root/magus.bundle`도 새 bundle로 바꿨다.
  - 되돌리기: `21b4e2a`는 gc로 지웠다. 같은 상태의 새 이력 커밋은 `78c9668`이다. 이미지 `magus:rollback-21b4e2a`(반영 전 이미지)를 남겼다. 절차는 서버 `/root/deploy-20261006-auth-audience/ROLLBACK.txt`.
    - 이미지 `magus:rollback-21b4e2a`는 다음 배포(2026-10-06 `p1-reupload`) 때 지웠다.
    - 서버 디스크(2026-10-06): `/` 23G 중 8.2G 사용(38%). docker 이미지 5개 2.05GB(그중 magus 둘이 각 1.15GB), 빌드 캐시 1.15GB.
- 대기: claude.ai 새 대화에서 Magus 도구 한 번 불러 확인(사용자). 되돌리기 이미지는 확인과 관계없이 다음 배포 때 지운다.

## 0-2. 최근 보고 (2026-10-06, 작업 방식 결정 + 최신본 시험 임포트 + 다시 올리기 설계안)

- 로컬에서만 작업했다. 서버와 default는 건드리지 않았다. default 파일 1,383개는 임포트 전후 해시가 같다.
- **결정 #68 기록**: `docs/decisions/author-file-is-source.md`
  - 반영한 문서: CLAUDE.md(개요, "왜 만드나" 5, 절대 원칙, book_write_chapter·book_import 항목, 진행상황, fixtures), README "처음 쓰는 순서", store-interface.md 후속 메모
  - 코드는 바꾸지 않았다. 어긋나는 코드·문구는 검토 대기 #74·#76으로 올렸다.
- **최신본 시험 임포트**: `data/users/father-trial/projects/book/`(받은함에 원본 사본, `original/import-report.md`). 비인용 용어 5개는 onboarding 절차대로 넣었다.
  - 비교 자료: `data/realdata/2026-10-06-father-trial-{import-report,cite-report,compare,outline}.md`
  - 결과
    - 장 구성은 같다: 35장 + 서장·맺음·부록 1~3, 8부, 302,507자. outline은 2,040토큰이다.
    - 책 제목은 파일 속성(`docProps/core.xml`의 제목)에서 읽혔다: "인류가 선택한 진화, 시대가 선택한 도시 — 생존과 번영 그리고 그 이동에 관한 역사"(부제 포함). 표지나 파일 이름에서 읽은 것이 아니다.
    - 코멘트 129건이 모두 미해결이 됐다. 15건은 장 밖이다(제2부 들어가며 13, 참고문헌 2).
    - 걸린 문장은 미해결 본문에 앞 120자만 붙는다. 82건이 잘린다.
    - 작성자("Claude")는 버려진다.
    - 참조 없는 1건(코멘트 id 0)은 범위로 들어왔다: I73, 제17장.
    - **표 37개의 글(17,396자)이 본문에서 빠진다**(`[표 N]`만 남음). 부록 1 연표는 32자가 됐다.
    - **"제2부 들어가며"(17,314자)·"제4부 들어가며"(3,905자)가 부 제목으로 읽혀** 부 이름을 덮고, 본문은 unsplit.md로 간다.
    - 그림 10개는 `[그림 N]`이다. media는 10개다(요청서의 11개와 다름).
    - 참고문헌 337줄 → refs 337, 인용 출현 427회, 고유 미확인 325편(참고문헌에 없음 3), 미연결 1, 열린 미해결 129(citation 42 · fact 46 · general 41).
  - 10/02 판(default)과의 비교, 이전 원고 오류의 상태, 새 미확인 문헌은 이 세션의 보고와 compare 파일에 있다.
- **다시 올리기 설계안 초안**: `docs/decisions/reupload-design.md`(미구현). 질문 9개에 항목별 비용·시기를 적었다.

## 0-1. 최근 보고 (2026-10-05, WorkOS 설정)

- **사용자 결정**
  - WorkOS 환경: 오전에 Production으로 정했다가, 오후에 사용자 지시로 **Staging**으로 바꿨다. #49 확정: 당분간 Staging, 공개 서비스로 바꿀 때 Production.
  - 허용 목록은 지금 운영자 본인 → `default`(개발용 PDF 임포트본으로 6단계 시험)이다. 아버지는 나중에 `father`로 추가하고 docx 원본을 새로 임포트한다.
  - claude.com 콜백도 등록한다(docs에 "사용자가 추가로 등록함, 출처는 WorkOS 측 안내").
- **코드**
  - 웹 로그인 실패를 둘로 나눴다. 토큰 무효는 401("로그인 토큰을 받아들이지 못했습니다")이고, 허용 목록 밖은 403("허용 목록에 없습니다" + 본인 사용자 id)이다.
  - `JwtVerifier.check`가 실패 원인을 서버 로그에 남긴다: iss·aud 불일치(토큰 값과 기대 값), 만료(exp), 서명·kid(kid·alg), 형식. 토큰 값과 서명 조각은 남기지 않는다. 테스트로 확인했다.
  - `ALLOWED_USERS`가 비어 있어도 시작한다(경고, 모두 403). 첫 로그인으로 id를 얻는 단계에 쓴다.
- **문서**
  - docs/deploy.md: 0절(WorkOS 환경(지금은 Staging), 리디렉션 URI 3개, 리소스), 2-1절(첫 로그인 → 403 화면에서 id 얻기 → `.env` → `up -d` → 재로그인, 순서 default → father)
  - auth-provider.md 연결 절차, connect-claude.md, `deploy/.env.example`(도메인 기입, ALLOWED_USERS 비움)
  - **docs/onboarding-father.md**(7단계 초안, 비인용 용어 옮기기 포함)
- 테스트 190개 통과.

## 0. 최근 보고 (P1 5단계 준비)

- **호스팅 결정**(`docs/decisions/hosting.md`): Vultr 서울 VPS $5 + Docker Compose + Caddy(자동 HTTPS). 백업은 restic → Cloudflare R2(무료 10GB 안, 일별 30 + 월별 12, #62), 알림은 텔레그램 + healthchecks.io. 예상 월 $5 + 도메인.
- **배포 파일**
  - `Dockerfile`(비root uid 10001, healthz 헬스체크)
  - `deploy/compose.yaml`(magus·caddy·backup·restore), `deploy/Caddyfile`(접근 로그 끔: 주소에 내려받기 토큰이 있다)
  - `deploy/backup.sh`(index 제외·일별 30 + 월별 12·부분 check·healthchecks 핑), `deploy/restore-test.sh`, `deploy/.env.example`
  - 운영 절차 `docs/deploy.md`
- **로컬 검증(Docker)**
  - 이미지 빌드. 원격 모드 컨테이너: `/healthz` ok, PRM resource 맞음, 토큰 없이 401, uid 10001, healthy.
  - **복구 훈련**: 실데이터 사본 53.4MB → 운영 `backup.sh`(restic 공식 이미지, 로컬 저장소) 34초·스냅샷 50.3MiB → `restic restore` 2,396개 → 컨테이너에서 reindex → default/book **outline 66줄 같음**. 사본·저장소·이미지는 지웠다.
- **알림**: `magus/alerts.py`(텔레그램 또는 웹훅, 백그라운드 전송), logsafe의 ERROR와 연결했다. `magus alert-test`.
- 새 CLI: `magus outline`(복구 비교용), `magus alert-test`.
- 6단계 문서 초안 `docs/connect-claude.md`(사용자용·아버지용, 배포 후 실제 화면으로 고친다).
- 테스트 188개 통과(알림 3, 복구 1 추가).

## 1. 지금 바로 할 일

- **다음: 아버지 첫 로그인**(2026-10-06 02:17 허용 목록에 추가함). `/book`이 비어 있어야 한다. 그다음 온보딩 B절.
- (처리함 2026-10-06, `p1-ui-terms`) `ALLOWED_USERS`에 같은 이름이 두 번이거나 같은 sub가 두 번이면 서버가 시작하지 않는다(`auth.parse_allowed`, 오류에는 항목 순서만). 배포 전 서버 값(2명)으로 로컬에서 미리 통과를 확인했다.
- **대기(사용자)**: claude.ai 설정에서 Magus 커넥터를 끊고 다시 연결한 뒤, 새 대화에서 "전체 보여 줘"로 확인한다(`p1-ui-terms` 배포 뒤, 0-7절).
- (처리함 2026-10-06 03:02) UI·용어 배포 `p1-ui-terms`: 웹 스타일, 세 책장 화면, 용어 통일 #85, 입력칸 #86, 허용 목록 중복 거부(0-7절).
- (처리함 2026-10-06) 서버 배포 `p1-reupload`(0-5절), `docs/worktree-rule` 병합(`e396d3f`, 사용자 지시).
- **나중에 할 것**
  - 생각에 장 연결 필드(ideas에 장 번호가 없어 `/ideas`에 "연결된 장"을 못 보인다. 2026-10-06 사용자 결정으로 이번에는 하지 않음)
  - 불명(2026-10-06): 요청의 "status.md 나중 목록"이 없어서 이 목록을 새로 만들었다.
- **운영 규칙(#78)**: 같은 책을 다시 올릴 때는 수정본으로 한다(`book_import new_edition=true`, 웹 "수정본으로 올리기", CLI `--new-edition`). `replace`는 결정·직접 남긴 미해결·닫은 미해결까지 휴지통으로 보내니 쓰지 않는다.
- 로컬 시험 공간: **아버지 온보딩이 끝날 때까지 지우지 않는다(#83).** 그 뒤 지울 때는 폴더를 지우고 `magus reindex`
  - `data/users/father-trial/`(4.4MB): 최신본 새 임포트(2026-10-06 두 번째, 새 파서)
  - `data/users/reupload-trial/`(7.2MB): 4판 → 최신본 다시 올리기 시험. 시험용 결정·영감·직접 미해결이 들어 있다(`[시험]`).
  - `data/users/reupload-trial-pdf/`(18MB): 10/02 PDF → 최신본 다시 올리기 보조 시험. 시험용 항목 같음.
- 불명(2026-10-06) — 둘 다 사용자가 해석을 확인했다(2026-10-06)
  - "설계 원칙 3·6"은 채팅 Claude 쪽 번호다. 3 = 단일 진실 원천 + 원본은 파일, 6 = 누가 말했는지 보존한다.
  - "D번호"는 status.md의 `#N` 체계가 맞다(#68).
  - "media 11": docx 안 `word/media/`의 파일은 png 10개다. 그림(drawing)도 10개다.
  - "4판 docx"(2026-10-06 두 번째 요청): 세션 중간에 `fixtures/261004-닿으려는_종_전면개정4판.docx`가 생겼다(처음 확인 때는 없었음). 그 파일로 요청대로 시험했다. 이 판은 파일 속성에 제목이 없어 E1 제목이 파일 이름이 됐고, E2(최신본)에서 원고 제목으로 바뀌었다.
- **GitHub 원격 저장소(2026-10-05)**: `origin` = https://github.com/sml122900/Magus (**Private**, 로그인 없는 API 조회 404)
  - master, `p0-realdata-parser`, 태그 15개를 push했다. 로컬과 원격의 해시가 모두 같다(ls-remote 27줄, peel 포함).
  - `origin/master` 트리(133개)에 `.env`·`data/`·`fixtures/`·`private/`·`docs/reports/`가 없다. 원격 이력 전체에도 없다.
  - 운영 규칙: **단계 태그를 찍으면 `git push origin master --tags`까지 한다**(CLAUDE.md "원격 저장소"). force push는 하지 않는다.
- **보고서 이력 정리 완료(2026-10-05)**: `docs/reports`의 저자용 보고서 2개(실원고 파생)를 git filter-repo로 모든 ref의 이력에서 뺐다.
  - 백업: `C:/project_2026/Magus-before-filter.bundle`(--all, 정리 전 17 ref). 되돌리려면 이 bundle에서 다시 clone한다.
  - 보고서는 `private/reports/`(gitignore `/private/`)에 있다. 해시는 원본과 같다.
  - 확인: 이력에 경로·파일명 0건, 보고서 내용 객체 없음, 커밋 31개 그대로(지워진 커밋 없음), 테스트 190개 통과.
  - 태그 새 해시(정리 전 → 후). `step1`~`step7`, `p0-realdata`, `p0-realdata-parser` 브랜치는 그대로다.
    - `p0-report1` 41fe1bd → ffadea7
    - `p1-step1` 19d6a02 → 73733b6, `p1-step2` 7273e47 → 80fd87b, `p1-step3` c4af070 → bb3a279, `p1-step4` ca6a5cf → 20572fa
    - `p1-step5` 9b420a3 → eff78d5, `p1-step6` 2164715 → 49daa60
    - 태그 종류(annotated/lightweight)는 정리 전과 같다.
  - **서버(2026-10-06 01:40부터)**: master `4df2720`(태그 `p1-reupload`). 옛 이력은 지난 배포 때 gc로 지웠다(0-3절).
    - **서버 되돌리기 기준 커밋: `896633c`**(`p1-auth-audience`, 이번 배포 직전 실행본). 반영 전 이미지 `magus:rollback-896633c` 보관 중. 절차는 서버 `/root/deploy-20261006-reupload/ROLLBACK.txt`. `HEAD~1`을 쓰지 않는다(CLAUDE.md 호스팅).
    - 그 전 기준 `78c9668`과 이미지 `magus:rollback-21b4e2a`는 이번 배포로 대체했다(이미지 삭제).
    - 다음 배포도 같은 절차다: 새 bundle → `git fetch /root/magus.bundle master` → `git checkout -B master FETCH_HEAD` → `docker compose up -d --build`(docs/deploy.md "업데이트").
- **다음: 7단계 아버지 온보딩**(`docs/onboarding-father.md` 초안). 아래 "7단계 전 확인"을 먼저 끝낸다.
- **7단계 전 확인**
  - [x] #69~#74, #77, #76 기본 부분 구현(2026-10-06, 로컬). 최신본 재임포트·다시 올리기 시험 통과.
  - [x] `docs/onboarding-father.md`를 최신 수치와 새 흐름(Word가 원본, 새 판으로 다시 올리기)으로 고쳤다(2026-10-06). 아버지께 드릴 자료는 채팅 Claude가 다시 만든다.
  - [x] **사용자 격리 점검**(2026-10-06, 0-6절): 막혀 있지 않은 곳 없음, 시험 7개 추가.
  - [x] **서버에 master 배포**(2026-10-06 `p1-reupload`, 0-5절). 남은 것: claude.ai에서 book_outline 확인, 아버지 임포트 뒤 `/book`·`/issues` 화면 보기.
  - [x] 아버지 docx 크기: 최신본 1.4MB(한도 50MB 안).
  - [ ] 아버지 docx를 받으면 업로드 전에 크기를 확인한다(한도 `MAX_UPLOAD_MB` 50MB, #54). 넘으면 서버 `.env`에서 한도를 올리고 `up -d`.
  - [ ] 사용자가 받은함 업로드 화면(`/inbox`)을 캡처해 채팅 Claude와 검토한다(#56). 아버지가 혼자 쓸 수 있는지 본다.
  - (뺌) 하루 이상 지난 뒤 재접속(토큰 갱신)은 확인 항목에서 뺐다. 실사용 중 문제가 생기면 그때 조치한다(2026-10-05 사용자 결정).
  - (정함) WorkOS는 당분간 Staging이다(#49 확정).
- 대기(사용자 결정)
  - (처리함) `docs/reports`: 올리지 않는다. 이력에서 빼고 `private/reports/`로 옮겼다(2026-10-05 사용자 결정).
  - 테스트 메모 `20261005141301887-3e167c`를 지울지.
- (처리함, 2026-10-06 `1708217`) 웹 `/book`의 장 수를 outline 표기(`35장 + 서장·…`)와 같게 맞췄다(사용자 요청).
- **6단계 결과(2026-10-05, 완료, `p1-step6`)**
  - 모바일 Claude 앱(사용자): 웹과 같은 시험이 모두 성공했다.
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
- 업데이트 절차: 로컬 `git bundle create magus.bundle master --tags` → `/root/magus.bundle`로 올림 → 서버 `git fetch /root/magus.bundle master && git checkout -B master FETCH_HEAD` → `docker compose up -d --build`. 반영 전 커밋·data 해시를 적어 두고, 되돌릴 때는 그 커밋으로 reset --hard(docs/deploy.md "업데이트").
  - 올리기: Windows에서는 `cat magus.bundle | ssh root@<서버> 'cat > /root/magus.bundle.new'` 뒤 sha256을 대조했다(2026-10-06, 한글 경로 scp 회피).
- 계정·설정(2026-10-05, 사용자)
  - WorkOS **Staging**(`https://dapper-palace-57-staging.authkit.app`, issuer 끝 `/` 없음). 10-05 오전의 Production 결정을 사용자 지시로 바꿨다.
  - Magic Auth 켬, 비밀번호 끔, 가입 끔, DCR·CIMD 켬, 리소스 `/mcp`(Default), 웹 리디렉션 `/auth/callback`.
  - 웹 클라이언트 `client_01M45PBRZEBZV6XEGJQSPWVH4P`(기밀).
  - `deploy/.env` 점검: 빈 값·형식 문제 없음. ALLOWED_USERS는 id만 있어서 값을 보지 않고 `=default`를 붙였다.
- 불명(승인됨): "P1 5~6단계 진행 지시" 원문이 없어 status.md와 docs/deploy.md 기준으로 진행했다(사용자 승인 2026-10-05).
- 불명
  - 완료 기준의 "refs 297": 실데이터 refs는 299건이다(파싱 실패 raw 1, acemoglu2001-2 포함). 297은 고유 미확인 문헌 수다. 판단: "refs 299, 미확인 문헌 297"로 검증한다.
  - 완료 기준의 "업로드한 docx": 실원고는 PDF만 있다(docx 없음). 판단: docx가 올 때까지 PDF로 검증한다. 대기: 원고 docx(사용자).
    - 2026-10-06: docx(최신본)를 받았다. #75 승인으로 완료 기준을 최신본 수치로 바꿨다: 35장 + 서장·부 들어가며 2·맺음·부록 1~3, 8부, 코멘트 129(AI 129), refs 337(미확인 문헌 335편). CLAUDE.md 완료 기준에 반영.

## 2. 현재 단계

**P1 진행 중 — 6단계 완료, 다음은 7단계(아버지 온보딩)**(`p1-step1`~`p1-step6`). 7단계 전 확인 항목이 1절에 있다.
2026-10-06: 작업 방식 결정 #68에 따라 7단계 전 보완(#69~#77)과 다시 올리기 기본(#76)을 로컬에서 끝냈다. 남은 7단계 전 일은 서버 배포(승인 대기)다. P0는 `step1`~`step7`, `p0-realdata`, `p0-report1`과 그 뒤 결정 반영 커밋까지 끝났다.

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
- [x] **P1 5단계 배포·도메인·HTTPS·백업·복구 테스트·알림** — 2026-10-05, `p1-step5`(웹 로그인 확인 포함)
  - 배포: `deploy/alive.sh`, `deploy/compose.yaml`(TZ·restic 0.19.1), `deploy/restore-test.sh`(</dev/null), `deploy/.env.example`(R2_*), 서버 `/opt/magus`
  - 서버 복구 시험 같음(docs/deploy.md 기록 표)
  - `Dockerfile`, `.dockerignore`, `.gitattributes`, `deploy/{compose.yaml,Caddyfile,backup.sh,restore-test.sh,.env.example}`, `src/magus/alerts.py`, `src/magus/cli.py`(outline·alert-test)
  - `docs/decisions/hosting.md`, `docs/deploy.md`, `tests/test_alerts.py`, `tests/test_restore.py`
- [x] **P1 6단계 Claude.ai 커넥터 등록** — 2026-10-05, `p1-step6`
  - 웹·모바일에서 book_outline, ref_check, book_read_chapter, idea_add 성공(CIMD, 인증 실패 0)
  - `docs/connect-claude.md`(실제 화면 순서), `docs/daily/2026-10-05.md`
  - 토큰 갱신(하루 이상 지난 뒤 재접속)은 따로 확인하지 않는다. 실사용 중 문제가 생기면 조치한다(2026-10-05 사용자 결정).
- [ ] P1 7단계 아버지 온보딩 체크리스트 — **진행 중**. `docs/onboarding-father.md`(2026-10-06 최신 수치·흐름 반영)
  - [x] WorkOS(Staging)에 아버지 계정 생성(사용자, 2026-10-06). id는 WorkOS 화면에서 받았다(403 화면으로 얻는 단계는 생략).
  - [x] 서버 `ALLOWED_USERS`에 `<아버지 id>=father` 추가, `docker compose up -d`(2026-10-06 02:17 서버 시각)
    - 저장 전 확인: 새 id가 기존 id와 다름, 이름 default·father 서로 다름, 한 이름에 sub 하나. 앱 파서로 다시 읽어 허용 2명 확인
    - 백업: 서버 `/root/deploy-20261006-father/env.before`(600). `ALLOWED_USERS` 밖의 줄은 그대로
    - 확인: healthy·재시작 0, 로그 "허용 2명", `/healthz` ok, `/mcp` 401, default 파일 798개 해시 같음
    - father 공간(`data/users/father/`)은 재시작 때 생기지 않는다. 첫 쓰기(받은함 업로드·임포트·생각 기록) 때 생긴다. 읽기(outline, `/book`·`/inbox` 화면)는 폴더를 만들지 않는다.
  - [x] **UI·용어 배포 완료, 아버지 첫 세션 준비 끝**(2026-10-06 03:02, `p1-ui-terms`, 0-7절)
  - [ ] 아버지 첫 로그인 → `/book`이 비어 있는지 확인(잘못된 짝을 잡는 단계)
  - [ ] 커넥터 등록, docx 업로드·처음 가져오기, 비인용 용어 6개, 첫 세션 대본(온보딩 B·C절)
  - 7단계 준비(2026-10-06, 로컬): `9688878` #74, `e1b57b7` #69, `0df3d1c` #70, `1708217` #71, `1d78eb6` #72, `fc6bdec` #73, `393f5e0` #77, `ef903d1` #76, `0109ad4`, `a1c9a12`
  - 파일: `src/magus/book/{reupload,importer,docx_reader,comments,outline,tools,export}.py`, `src/magus/store/*`, `src/magus/melchior/{bibliography,author_report}.py`, `src/magus/{web,cli,instructions}.py`, `tests/test_docx_features.py`, `tests/test_reupload.py`

## 4. 검토 대기 결정

**P1 검토 대기**: #65~#67. 다음 보고에서 #45~#64와 같은 열(무엇을·고른 것·대안·이유·바꾸는 비용)의 표로 따로 올린다.
- #69~#78은 2026-10-06에 확정됐다(아래 "2026-10-06 확정"). 구현 기록은 6절 마지막 세션 요약에 있다.

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

**2026-10-06 확정(#69~#78)** — 69~75는 제안대로 승인, 76은 범위를 바꿔 확정, 77·78은 새 사용자 결정. 69~74는 임포트 때만 채워지는 값이라 아버지 임포트(7단계) 전에 한다.

69. **docx 표를 장 본문에 markdown 표로 싣는다**(지금은 `[표 N]`만 남는다)
    - 대안: 칸을 문단으로 풀기(PDF와 같은 모양), 지금처럼 자리표시자만 두기.
    - 이유
      - 최신본 표 37개의 글 17,396자가 본문에서 빠진다. 부록 1 연표는 표 하나라 장이 32자다.
      - 표 안 인용 10건이 집계에서 빠진다(모호한 `케인스(1930)` 포함).
      - Claude가 book_read_chapter로 표의 수치를 볼 수 없다.
    - 비용: 낮음. `docx_reader.table`을 고치고 칸 안의 `|`는 이스케이프한다. export는 pandoc이 markdown 표를 Word 표로 바꾼다.
70. **"제N부 들어가며"를 번호 없는 장으로 다룬다**
    - 지금
      - `제2부 들어가며 …`가 부 제목으로 읽힌다. 진짜 부 제목 "제2부 평지와 털", "제4부 잉여생산물"은 버려지고, 부 이름이 "들어가며 …"가 된다.
      - 본문(제2부 17,314자, 제4부 3,905자)은 unsplit.md로 가서 도구로 읽을 수 없다.
      - 코멘트 13건이 장 없이 들어간다.
      - 그 안의 인용 9편이 "본문 미인용"으로 잘못 보인다.
    - 제안: label `제N부 들어가며`, 번호 100+N(제2부 = 102), part_number N으로 둔다. 목차·export·웹에서는 그 부의 첫머리에 놓는다. 부 제목은 `제N부 <제목>` 줄에서 읽는다.
    - 대안: 부 서문으로 `project.json`에 둔다(도구로 읽을 길을 새로 만들어야 한다). 또는 90번대에 둔다(부록과 섞인다).
    - 비용: 중간(번호 규칙, 정렬, export, 웹, 테스트).
71. **코멘트 작성자를 미해결에 남기고 AI 작성을 구분한다**
    - 지금: 리더는 작성자를 읽지만 버린다. 미해결에는 origin=import_comment만 남는다. 최신본 129건의 작성자는 모두 "Claude"다.
    - 제안
      - issues.md 메타에 `author`(Word 이름 그대로)·`date`·`author_kind: me|ai`를 둔다.
      - ai 판정은 이름 목록(Claude, ChatGPT, Copilot, Gemini 등)으로 하고, 프로젝트별로 고칠 수 있게 한다.
      - outline의 코멘트 유래 줄과 book_issues에 "AI 129"처럼 보인다.
    - 이유: 절대 원칙 "누가 말했는지 보존한다". 다시 올리기의 코멘트 지문(설계안 5절)도 이 값을 쓴다.
    - 비용: 낮음~중간(SCHEMA_VERSION 9).
72. **`[점검·…]` 태그 코멘트를 분류한다**
    - 지금: 새 코멘트 43건이 `[점검·통계]`·`[점검·수치]`·`[점검·인용]` 같은 태그로 시작한다. "확인 필요"가 없어서 39건이 general이 된다(전체 general 41).
    - 제안
      - `[점검·인용]`·`[점검·서지]` → 출처 확인(문헌이 지목되면 citation, 아니면 fact)
      - `[점검·통계|수치|연도|사실|사례|계산]` → fact
      - `[사진]` → general
    - 비용: 낮음.
73. **미해결에 걸린 문장 전문을 구조화해 저장한다**
    - 지금: 본문 끝에 앞 120자만 붙인다. 129건 중 82건이 잘린다(앵커 중앙값 194자).
    - 제안: 메타 `anchor`(전문, 1,000자 상한)와 장 안 문단 번호를 둔다. 표시는 지금처럼 120자다.
    - 이유: 다시 올리기에서 "걸린 문장이 남아 있는가"를 판정하는 바탕이다(설계안 4절).
    - 비용: 낮음.
74. **서버 instructions 규칙 4를 #68에 맞게 바꾼다**(RULES는 "원문 그대로" 규칙이라 승인이 필요하다)
    - 지금: "장을 고치면 book_write_chapter로 그 장만 저장하고 note에 무엇을 바꿨는지 쓴다. 결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다."
    - 제안: "장 수정안은 대화로 제시하고 저자가 Word에 반영한다. 저자가 Magus에 저장하라고 할 때만 book_write_chapter로 그 장만 저장하고 note에 무엇을 바꿨는지 쓴다. 결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다."
    - 이유: 지금 문장대로면 아버지의 첫 세션부터 Claude가 Magus 원고를 고쳐 쓰고, Word 원고와 갈라진다.
    - 비용: 낮음(문장 하나, `tests/test_instructions.py` 기대값, book_write_chapter 설명).
75. **P1 완료 기준의 수치를 최신본으로 바꾼다**
    - 지금 기준: "업로드한 docx가 임포트되어 35장·8부·코멘트 86·refs 297". 10/02 PDF 판의 숫자다.
    - 최신본 시험 결과: 35장 + 서장·맺음·부록 1~3, 8부, 코멘트 129, refs 337(파싱 실패 1 포함), 미확인 문헌 325편.
      - #69·#70을 고치면 미확인 문헌은 약 335편이 된다(표·들어가며의 인용을 따로 세어 본 값).
    - 제안: 7단계는 최신본 수치로 검증한다. 수치는 #69·#70을 고친 뒤 다시 잰다.
76. **다시 올리기 범위(사용자 결정, 제안에서 바뀜)**(`docs/decisions/reupload-design.md` "확정 범위")
    - 이유: 아버지는 사흘에 판을 세 번 바꿨다. 첫 다시 올리기가 온보딩 직후에 온다. 그래서 기본 부분을 7단계 전으로 당긴다.
    - 7단계 전
      - 같은 책 선택(사용자가 고르고 장 제목 겹침으로 경고)
      - 장 대응은 번호·제목 일치까지
      - 바뀐 장만 교체 + 판 번호 기록
      - 기존 미해결: 걸린 문장이 그대로면 유지, 없으면 "해결됐을 수 있음"(자동으로 닫지 않음)
      - Word 코멘트 중복 방지(작성자 + 날짜 + 본문 지문)
      - 결정·영감·문헌 보존(해시 테스트), 참고문헌 key 안정화
      - outline에 판·업로드 시각 표시, 7일 경과 안내
    - 뒤로: 본문 유사도 판정, 장 이동·분할, "조금 바뀜" 기준 보정, 제안 저장, 돌려주기 docx(P2)
77. **책 제목과 부제를 따로 저장한다**(사용자 결정)
    - 이번 원고: 제목 "인류가 선택한 진화, 시대가 선택한 도시", 부제 "생존과 번영 그리고 그 이동에 관한 역사".
    - 영문 제목·부제도 따로 둘 수 있으면 둔다.
78. **운영 규칙: 다시 올리기가 생기기 전까지 replace로 다시 임포트하지 않는다**(사용자 결정, CLAUDE.md)

**2026-10-06 확정(#79, 사용자 지시 "질문하지 말고 진행하되 결정은 status.md에")**

79. **토큰 aud는 `PUBLIC_URL/mcp` 하나만 받는다. `AUTH_AUDIENCE`로 넓히지 않는다**(#51 대체, `docs/decisions/shared-auth-audience.md`)
    - 전제: trip_ai와 WorkOS 환경(Staging)을 공유한다. issuer·서명 키·sub가 같아 aud만이 서비스를 가른다.
    - aud가 문자열이면 그 값, 목록이면 원소가 그 값 하나일 때만 통과. 다른 값이 섞이거나 aud가 없으면 401.
    - `AUTH_AUDIENCE`가 비어 있으면 `PUBLIC_URL/mcp`. 값이 있는데 다르면(쉼표 목록·끝 `/` 포함) 서버가 시작하지 않고 이유를 한국어로 남긴다.
    - aud로 거부할 때 받은 aud의 모양(문자열/목록, 값)을 로그에 남긴다. 토큰·sub는 남기지 않는다(#52).
    - `ALLOWED_USERS`는 서비스별로 따로다. 같은 sub가 두 목록에 다 있을 수 있어서, 서비스 사이 토큰 재사용은 허용 목록이 아니라 aud로 막는다.
    - 401(aud 불일치)이면 WorkOS에 등록한 리소스 주소가 `PUBLIC_URL/mcp`와 글자까지 같은지 확인한다.
    - 대안: PyJWT strict_aud(원소 하나인 목록도 거부해 지금 로그인을 깨뜨릴 수 있음), 서비스별 WorkOS 환경(전제와 다름), azp로 구분(두 서비스 모두 Claude라 같음), 경고만 내고 무시(조용히 다르게 돔).
    - 서버 반영: 2026-10-06 00:53 KST, `p1-auth-audience`(0-3절).

**2026-10-06 확정(#87~#89, 사용자 결정 — p1-ui-terms 배포 뒤 시험에서)**

87. **저장 위치 되묻기와 이름 규칙을 도구 설명에도 적는다.** 배포 뒤 claude.ai에서 위치를 말하지 않은 저장 요청을 Claude가 되묻지 않고 idea_add로 저장하며 "영감 책장"이라고 했다(커넥터 재연결 전). 다시 연결한 뒤에는 되물었지만 "영감 책장(Casper)"·"문체 책장(Balthasar)"이라고 말했다.
    - idea_add·style_add·ref_add 설명 첫 문장: 저자가 '생각'('문체','문헌')에 넣으라고 분명히 말했을 때만, 아니면 먼저 묻기. book_write_chapter 첫 문장: 규칙 4.
    - 도구 설명·응답·instructions에서 코어 이름(Casper·Melchior·Balthasar)과 옛 이름(영감·책 지도·미해결·이슈·새 판·책장)을 뺐다(#85의 "코어 이름은 그대로"를 취소). 코드·모듈·내부 문서의 이름은 그대로다.
    - instructions: 머리말 "이 서버는 사용자의 생각·문헌·문체와 원고를 관리한다.", 규칙 7 끝에 "코어 이름(Casper·Melchior·Balthasar)이나 도구 이름을 저자에게 말하지 않는다." 금지 이름 목록에 '이슈'·'책장'을 더했다.
    - 시험 `tests/test_author_terms.py`: 21개 도구를 모두 한 번씩 불러 설명·입력 스키마·응답과 instructions(금지 문장 AVOID 하나는 뺌)에서 위 이름을 찾는다. 일부러 '영감'을 넣으면 실패하는 것을 확인했다.
88. **생각·문체 휴지통**: `idea_delete`·`style_delete`(지우지 않고 `trash/shelf/`로 옮김, 이유 note). 설명 첫 문장: 저자가 지우라고 분명히 말했을 때만, 여러 개면 목록을 보여 주고 확인받기. 생각을 옮기면 응답한 AI 발화도 함께. 검색·목록·웹·reindex에서 빠진다. 되살리기는 운영자 CLI `magus trash restore`만(이번 범위).
89. **문체 태그를 누가 정했나(`tags_by`: ai|author)**를 파일·인덱스에 남기고(SCHEMA_VERSION 13), 응답·style_search·웹 `/styles`("AI가 뽑은 태그"·"저자가 정한 태그")에 보인다. 기록 전 항목은 표시하지 않는다. 이유를 지어내지 않고 `(저자가 이유를 밝히지 않음)`으로 남기는 동작은 유지하고 설명에 적었다.

**2026-10-06 확정(#85·#86, 사용자 결정)**

85. **저자에게 보이는 이름을 통일한다**(CLAUDE.md "저자에게 보이는 이름")
    - 전체(book_outline, 책 지도) · 확인 요청(issues, 미해결) · 생각(Casper, 영감) · 문체(Balthasar) · 문헌(Melchior, refs) · 결정 · 수정본(new_edition, 새 판·다시 올리기. 번호 E2·E3…는 수정본 번호, 첫 업로드 E1은 "처음 올린 원고")
    - 범위: 웹 화면, 도구 응답 문장(outline·book_issues·수정본 리포트·임포트 리포트·오류), 서버 instructions(머리말 '영감' → '생각', 규칙 7~9 추가), 저자 대상 문서(onboarding-father, connect-claude, README).
    - 바꾸지 않은 것: 도구 이름·도구 설명(Claude만 읽는다. 규칙 7이 "도구의 미해결 = 확인 요청"으로 잇는다), 모듈 이름, 내부 설계 문서, 파일 형식(issues.md 제목 `# 미해결`), CLI 도움말, 장 note에 이미 적힌 `판 E2 업로드: …`(새로 쓰는 note만 `수정본 E2 업로드: …`).
    - 규칙 9: 넣을 곳을 말하지 않은 "저장해 줘"·"기록해 줘"·"등록해 줘"·"넣어 줘"에는 쓰기 도구를 바로 부르지 않고 생각·문체·문헌 중 어디인지 먼저 묻는다. 이것은 instructions 문장으로만 보장된다(서버가 막지 않는다).
86. **입력칸 테두리는 `--mute`(#64748d, 흰 바탕 4.75:1)**. 참고 문서의 입력칸 색(#a8c3de, 1.82:1)은 WCAG 1.4.11(3:1)에 못 미친다. 주 사용자 가독성이 디자인 충실도보다 먼저다(`docs/decisions/web-style.md`).
    - 참고 디자인 문서는 리포에 넣지 않는다. `private/design/`(gitignore)로 옮겼다. 문서에서는 "외부 디자인 분석 문서(private/design)"로만 부른다.

**2026-10-06 확정(#84, 사용자 승인)**

84. **저자 확인 질문지(`book_questions`) 설계안 승인. 구현은 7단계(아버지 온보딩) 뒤 첫 작업으로 한다**(`docs/decisions/author-questions.md`)
    - 조사: 1절 질문 18곳 중 MCP·웹으로 바로 얻을 수 있는 것은 케인스 a/b·미연결뿐이다. 연도 불일치·추정 연결·같은 저자 두 편·중복 서지는 일부(장마다 ref_check 또는 올릴 때 리포트에만), "참고문헌에만 있음"은 CLI 보고서에만 있다.
    - 판별은 check.py(장마다), report.py(hint·uncited), author_report.py(same_author·이름 언급), bibliography.py(중복 서지, 올릴 때만)에 흩어져 있고 책 단위로 저장되지 않는다.
    - 제안: 판별을 questions.py로 모으고 `book_questions`(조회) → `book_answer`(alias·비인용 용어·결정 기록·`book/answers.md`) 순서. 질문은 매번 계산하고 답만 파일에 남긴다. 다시 올리기 리포트에 "새로 생긴 질문" 절, 웹 `/questions` 조회. Word 코멘트로 돌려주기는 P2.
    - 시기(사용자 결정): 7단계 뒤 첫 작업. 범위는 설계안의 "비용·시기 요약"(questions.py + book_questions → book_answer + answers.md → 웹 /questions 조회·다시 올리기 리포트 절). Word 코멘트는 P2.

**2026-10-06 확정(#80~#83, 사용자 결정 — 세 번째 요청)**

80. **#71·#76 구현 세부 승인**: 원고 코멘트 작성자 구분 값은 `ai|person`(제안의 `me|ai`에서 바뀜. 편집자 같은 사람을 저자로 적지 않으려고). 원고에서 지워진 코멘트도 자동으로 닫지 않고 "해결됐을 수 있음"으로만 표시한다.
81. **`상트페테르부르크`를 비인용 용어에 넣는다.** 최신본 제27장 표의 `상트페테르부르크(1703)`(도시 건설 연도)가 미연결로 잡히던 것. `father-trial`에 넣었고(미연결 2 → 1), 아버지 프로젝트는 온보딩의 용어 명령에 넣었다(`docs/onboarding-father.md` A절).
82. **`셰 등(2019)`(제30장)이 Hsieh 2019 두 편 중 어느 것인지는 저자에게 묻는다.** 그때까지 미연결로 둔다. 답을 받으면 `magus alias hsieh2019(또는 hsieh2019-2) "셰 등(2019)"`.
83. **시험 공간 `father-trial`·`reupload-trial`·`reupload-trial-pdf`는 아버지 온보딩이 끝날 때까지 지우지 않는다.**

**P0 결정**: #1~#44 모두 확정됐다.
**P1 결정**: #45~#64 모두 확정됐다(2026-10-05). 내용은 아래 "P1 확정 결정"에 있다.
**사용자 결정 #68**(2026-10-06): 확정. 내용은 아래 "P1 확정 결정"의 68번에 있다.

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
- 2026-10-05 P1 일괄 처리(#45~#64)
  - 승인(그대로): #45 #46 #47 #48 #50 #51 #52 #53 #55 #57 #58 #59 #60 #61 #63 #64
  - 승인 + 보완: #54(아버지 docx 업로드 전 크기 확인), #56(받은함 업로드 화면을 캡처해 채팅 Claude와 검토). 둘 다 7단계 체크리스트에 넣었다.
  - 확정(구체화): #49는 WorkOS를 당분간 Staging으로 운영하고, Production은 공개 서비스로 바꿀 때 옮긴다.
  - 변경: #62 보관을 일별 30개 + 월별 12개로 바꿨다. 서버에 반영하고 확인했다.
  - #65~#67은 다음 보고로 미뤘다.
- 2026-10-06 사용자 결정: #68(원고 본문의 원본은 저자 파일). 요청서에 결정으로 적혀 와서 바로 확정으로 기록했다.
- 2026-10-06 두 번째 요청
  - #69~#75: 승인(제안대로)
  - #74 규칙 4의 취지(사용자): 수정안은 대화에서 제안하고 저자가 Word에 반영한다. book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓴다.
  - #71 보완(사용자): AI가 단 코멘트에서 온 미해결은 저자에게 보일 때도 AI의 확인 요청임이 드러나야 한다(book_issues, outline, 웹).
  - #76: 범위를 바꿔 확정. #77(제목·부제), #78(replace 금지 운영 규칙)은 새로 기록했다.
- 2026-10-06 토큰 aud 지시: #79(확정, #51 대체). 지시가 "질문하지 말고 진행, 결정은 status.md에"라 바로 확정으로 기록했다.
- 2026-10-06 세 번째 요청: #80(#71 ai|person·지워진 코멘트 자동으로 닫지 않음 승인), #81(상트페테르부르크 비인용 용어), #82(셰 등(2019)은 저자 질문, 미연결 유지), #83(시험 공간 셋은 온보딩 끝까지 보관).
- 2026-10-06: #84 승인(구현은 7단계 뒤 첫 작업).

**P1 확정 결정(#45~#64, 2026-10-05 / #68, 2026-10-06)**

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
49. **인증 서비스는 WorkOS AuthKit, 당분간 Staging 환경으로 운영한다**(`docs/decisions/auth-provider.md`)
    - 대안: Descope(차선), Auth0, Clerk, Stytch, Supabase, Scalekit, Logto.
    - 이유: CIMD 기본, aud = MCP URL, 2명 무료, 호스팅 한국어 로그인. 코드는 표준만 써서 바꾸기 쉽다.
    - 환경(2026-10-05 확정): **Staging**(`dapper-palace-57-staging.authkit.app`). Production은 공개 서비스로 바꿀 때 옮긴다. 대시보드에서 Production 생성이 거부되던 문제는 그때 확인한다.
      - 옮기면 issuer와 사용자 id가 바뀐다. ALLOWED_USERS를 다시 쓰고, 커넥터를 다시 등록하고, 웹 클라이언트를 다시 만든다.
50. **허용 목록 밖(유효한 토큰)은 403, 무효 토큰은 401**
    - 대안: 둘 다 401.
    - 이유: 401이면 Claude가 다시 로그인하라고 되풀이한다. 403이면 "허용 목록에 없다"는 이유가 보인다.
51. **audience는 검증기가 직접 본다**(`validate_token_resource=False`, 기본 aud = `PUBLIC_URL/mcp`, `AUTH_AUDIENCE`로 여럿 허용)
    - **2026-10-06 #79로 대체**: `AUTH_AUDIENCE`로 여럿 허용하지 않는다. aud는 `PUBLIC_URL/mcp` 하나만 받는다. 검증기가 직접 보는 것(`validate_token_resource=False`)은 그대로다.
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
    - 보완(2026-10-05): 아버지 docx를 받으면 업로드 전에 크기를 확인한다(7단계 체크리스트).
55. **받은함은 SQLite에 색인하지 않는다**(폴더를 그대로 읽는다)
    - 이유: 파일이 진실이고 목록이 짧다. P2(객체 스토리지)에서는 Store 구현이 목록을 준다.
56. **웹은 서버에서 그린 HTML(템플릿 엔진 없음), MCP와 같은 Starlette 앱**(`server.custom_route`)
    - 대안: Jinja2, 별도 프런트엔드(SPA).
    - 이유: 지시가 "같은 프로세스, 가벼운 것"이다. 의존성이 늘지 않고 페이지가 넷뿐이다. 값은 모두 html.escape로 이스케이프한다.
    - 보완(2026-10-05): 7단계 전에 사용자가 받은함 업로드 화면을 캡처해 채팅 Claude와 검토한다(7단계 체크리스트).
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
62. **백업은 restic → R2, index.sqlite 제외, 일별 30개 + 월별 12개, 매번 1/30 읽기 검사**
    - 대안: tar + 수명 주기 규칙(30개 전체 사본), rclone 동기화.
    - 이유: 암호화·중복 제거로 무료 10GB 안에 든다. 인덱스는 다시 만들 수 있어 실행 중인 DB의 일관성 문제가 없다. restic 저장소에는 수명 주기 규칙을 걸면 안 된다.
    - 변경(2026-10-05): 처음에는 30일만 두었다. `--keep-daily 30 --keep-monthly 12`로 바꿨다. 30일이 지나서야 발견한 손상도 되돌리기 위해서다.
      - 서버에 반영해 확인했다: `Applying Policy: keep 30 daily, 12 monthly snapshots`, 검사 오류 없음, 스냅샷 2개.
      - 칸이 다 차기 전에는 restic이 가장 오래된 스냅샷도 남긴다("oldest daily/monthly snapshot").
63. **알림은 텔레그램(서버 오류) + healthchecks.io(백업 누락)**
    - 대안: 이메일(Resend), Slack·Discord 웹훅(코드는 웹훅도 지원한다).
    - 이유: 휴대폰으로 바로 오고 무료다. 백업 누락은 "안 온 것"을 알아야 해서 데드맨 스위치가 맞다.
    - 구현 보완(2026-10-05): healthchecks.io magus-alive(5분)로 서버·HTTPS 정지도 알린다(`deploy/alive.sh`).
64. **Caddy 접근 로그는 끈다**
    - 이유: 내려받기 링크 토큰이 주소에 들어 있다. 앱의 감사 로그(도구·사용자·시간)로 충분하다.
68. **원고 본문의 원본은 저자의 Word(·한글) 파일이다. Magus의 원고는 최신 업로드의 사본이다**(`docs/decisions/author-file-is-source.md`)
    - 흐름: 저자가 Word에서 고친다 → 막히면 Claude와 대화하고, Claude는 Magus로 책 전체 맥락을 보고 조언한다 → 생각과 논문은 Magus에 쌓는다 → 원고가 바뀌면 다시 올린다.
    - 따라서
      - Claude의 수정안은 저자가 Word에 반영한다. Magus 안의 원고를 Claude가 직접 고쳐 쓰는 것은 기본 흐름이 아니다.
      - 다시 올리기가 핵심 기능이다(설계안 `docs/decisions/reupload-design.md`).
    - "원고 상태를 대화 밖에 저장한다"는 원칙은 유지한다. "원고 본문의 원본"만 저자 파일로 바꾼다.
    - 대안: Magus 원고를 원본으로 유지(저자 작업 방식과 맞지 않음), 양방향 동기화(비용이 크고 갈라짐을 키움).


## 5. 환경 메모

- **운영 확정값(2026-10-05 사용자)**: 도메인 `magus.lifebookapplication.com`, 서버 IP `158.247.225.48`, 커넥터 `https://magus.lifebookapplication.com/mcp`. WorkOS Staging(#49).
- **원격 저장소**: `origin` = https://github.com/sml122900/Magus (Private). 인증은 Git Credential Manager가 한다. 단계 태그를 찍으면 `git push origin master --tags`.
- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음). Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 실패한다. 그때는 `uv add --no-sync`와 `uv pip install`을 쓴다.
- **Python** 3.12(.venv). **MCP SDK** mcp 2.2.0.
- **의존성**: python-docx 1.2.0, pymupdf 1.28.2, pypandoc-binary 1.17(pandoc 3.9), numpy 2.5.3, lxml. ruff 0.16(개발용, `--select F,B`로 점검).
- **Node** v22.23.2(fnm). MCP Inspector는 `npx -y @modelcontextprotocol/inspector --cli …`로 쓴다.
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=12`(2026-10-06: 9 작성자, 10 앵커, 11 부제, 12 판·지문·stale). 버전이 바뀌면 처음 열 때 자동으로 다시 만들고, 서버가 시작할 때 파생값을 다시 계산한다.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`(USER_ID=default, DATA_DIR=C:\project_2026\Magus\data → FILES_DIR 기본 C:\project_2026\Magus)
  - 로그: `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`. 시작 줄에 files_root가 찍힌다.
  - 위 두 경로는 프로젝트 폴더 밖이다. 사용자가 이 세션에서 경로를 적어 지시할 때만 읽는다.
- **데이터 사용자**
  - `default`: 실원고 `book`(비인용 용어 5개), refs 299, 실대화 452발화, 문체 0
  - `demo`: 데모 프로젝트·표본
  - `synthetic`: 합성 synth
  - `father-trial`(2026-10-06): 최신본 docx 시험 임포트 `book`(받은함에 원본 사본, 비인용 용어 5개). 서버에는 없다. 시험용이라 지워도 된다(폴더 삭제 + reindex).
  - `reupload-trial`·`reupload-trial-pdf`(2026-10-06): 다시 올리기 시험 공간(4판 → 최신본, PDF → 최신본). 시험용 결정·영감 포함. 지워도 된다.
- **fixtures**
  - 실데이터(gitignore): `fixtures/261002-닿으려는_종_전면개정_그림추가.pdf`, 대화 md 4개, `fixtures/papers/`(비어 있음, 사용자가 논문 PDF를 둔다).
  - 최신본(2026-10-06 받음): `fixtures/261005-인류가_선택한_진화_시대가_선택한_도시_원고.docx`(1.4MB, 코멘트 129, 표 37, 그림 10)
  - 4판(2026-10-06 세션 중간에 생김): `fixtures/261004-닿으려는_종_전면개정4판.docx`(1.4MB, 코멘트 86, 파일 속성 제목 없음)
  - 시험 임포트 명령: `USER_ID=father-trial DATA_DIR=./data .venv/Scripts/python -m magus inbox --add fixtures/261005-….docx`, 그다음 `… -m magus import data/users/father-trial/inbox/261005-….docx --project-id book`
  - 합성(커밋): `tests/fixtures/synthetic/`(원고 docx·pdf, 대화 md 3개, 야간 작업 리포트).
- **명령**(Bash, 프로젝트 루트에서 실행. 콘솔 한글은 `PYTHONIOENCODING=utf-8`)
  ```
  .venv/Scripts/python -m pytest -q -p no:cacheprovider
  .venv/Scripts/python -m ruff check --select F,B src tests
  DATA_DIR=./data .venv/Scripts/python -m magus import fixtures/<원고>.pdf --project-id book --title "닿으려는 종" --replace > data/realdata/import-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus cite-report --project-id book > data/realdata/cite-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus author-report --project-id book --out private/reports/<날짜>-인용-점검.md
  DATA_DIR=./data .venv/Scripts/python -m magus terms --project-id book [--add …] [--remove …]
  DATA_DIR=./data .venv/Scripts/python -m magus alias <key> <표기>
  DATA_DIR=./data .venv/Scripts/python -m magus reindex
  USER_ID=<사용자> DATA_DIR=./data .venv/Scripts/python -m magus import <받은함 원고> --project-id book --new-edition   # 같은 책의 새 판
  ```
- **git**
  - master에 바로 커밋하고, 단계가 끝나면 태그를 단다. 실험은 브랜치에서 하고 squash merge한다.
  - 태그: `step1`~`step7`, `p0-realdata`, `p0-report1`, `p1-step1`~`p1-step4`. P0 뒤 커밋 두 개(마무리 보완, 결정 반영)에는 태그를 달지 않았다(지시).
  - `/fixtures/`(루트), `data/`, `/private/`(저자용 보고서 등 실원고 파생 자료)는 gitignore. `tests/fixtures/`(합성)는 커밋한다.

## 6. 마지막 세션 요약

**2026-10-06 (11)** — `p1-ui-terms` 태그·push·서버 배포(세션 magus-25)
- 허용 목록 중복 거부를 넣고(서버 값으로 미리 통과 확인), 태그·push, 지난번과 같은 절차로 배포했다. 되돌리기 기준 `4df2720`, 이미지 `magus:rollback-4df2720`. data 해시 같음.
- 남긴 것: 사용자 커넥터 재연결 확인, 아버지 첫 로그인·첫 세션. 배포 기록 커밋은 다음 태그 때 push.

**2026-10-06 (10)** — 용어 통일(#85) + UI 마무리(#86), 커밋만(세션 magus-25)
- instructions: 머리말 '영감' → '생각', 규칙 7(이름)·8(저자의 말 해석)·9(넣을 곳이 애매하면 묻기). `required_tools`가 `files_list`도 본다.
- 도구 응답: outline(`열린 확인 요청`, 장 줄 `확인 요청 n`, `## 열린 확인 요청`, `코멘트 유래 확인 요청`, `수정본 E2`/`처음 올린 원고 E1`/`수정본 기록 없음`), book_issues 머리(`확인 요청 N건`), 수정본 리포트, 임포트 리포트(`코멘트 → 확인 요청`), 오류 문장. 실데이터 outline 2,297(father-trial)·2,044(default) 토큰.
- 웹: 메뉴 확인 요청·생각, `/book` 수정본 문구, 빈 책장 예문(넣을 곳을 밝힌 말로), 입력칸 테두리 `--mute`.
- 문서: CLAUDE.md 용어집, `docs/decisions/web-style.md`(새), onboarding-father·connect-claude·README 용어. 참고 디자인 문서는 `private/design/`으로.
- 테스트 234개 통과(문구 시험은 새 문구로, 용어·애매한 저장 시험 추가). 캡처 `private/screens/2026-10-06-terms/`.
- 남긴 것: 사용자 캡처 확인 → UI 개선과 함께 한 번에 배포. push는 다음 태그 때.

**2026-10-06 (9)** — 웹 세 책장 화면(읽기 전용, 서버 배포 없음, 세션 magus-25)
- `/ideas`(영감): 최근 것부터, 날짜·내용(300자 넘으면 "더 보기"로 접음)·누가(나 / AI 알약 + "응답한 생각" 링크)·출처. 나·AI 거르기.
- `/refs`(문헌): 확인한 것부터, 신호등(🟢확인 🟡미확인)·서지·쓸 부분과 이유(발췌)·인용된 장(현재 책의 cite report). 머리줄에서 `/checklist`로 잇는다. 상태 거르기.
- `/styles`(문체): 구절·출처·이유·태그 알약, 태그를 누르면 그 태그만.
- 세 화면 모두 100개씩 쪽 나눔, 빈 책장에는 예문 한 줄, 메뉴에 영감·문헌·문체(기존 메뉴 문구는 그대로). 쓰기 폼 없음(로그아웃만).
- 영감에는 "연결된 장" 필드가 없다(ideas는 text·kind·author·origin·parent_id만). 그래서 장 링크 대신 출처(origin)를 보였다.
- 시험: `test_web::test_shelf_pages_are_read_only_lists`, 격리 `test_isolation::test_shelf_pages_show_only_own_shelf`(같은 문헌 key·project id인 두 사용자). 테스트 233개 통과, ruff 통과.
- 캡처: `private/screens/2026-10-06-shelves/`(빈 상태는 `empty/`, 채운 상태는 scratch 사본에 "캡처용 예시" 데이터를 넣어 찍음. 리포 밖).
- 남긴 것: 서버 배포는 다음 배포 때, push는 다음 태그 때.

**2026-10-06 (8)** — 웹 UI 가벼운 개선(스타일 위주, 서버 배포 없음, 세션 magus-25)
- `web.py` `STYLE` 상수에 디자인 토큰을 모았다. 상단 흰 바("Magus" + 메뉴, 지금 메뉴 표시), 카드·표·알약 버튼·입력칸 focus 링·숫자 칸 오른쪽 정렬, 768px 미만에서 표는 상자 안 가로 스크롤.
- 받은함: 파일을 고르면 바로 올린다(돌아가는 표시). `/book`: 책이 없으면 새 판 비활성, '바꾸기'는 '드물게 쓰는 선택' 안(새 문구).
- 문구는 바꾸지 않았다. 새로 넣은 문구: 상단 "Magus", 접힌 영역 "드물게 쓰는 선택". 테스트 231개 통과. 캡처 `private/screens/2026-10-06-ui/`(리포 밖).
- 남긴 것: 서버 배포는 다음 배포 때, push는 다음 태그 때.

**2026-10-06 (7)** — 아버지 계정을 서버 허용 목록에 추가(세션 magus-25)
- `.env` 백업 → 짝 확인(id 다름, 이름 서로 다름, 한 이름에 sub 하나) → 저장(600) → 앱 파서로 허용 2명 확인 → `up -d` → healthy, default 해시 같음. id는 출력·기록하지 않았다.
- 남긴 것: 아버지 첫 로그인 확인, 할 일 "같은 이름·sub 두 번이면 시작 거부"(다음 배포).

**2026-10-06 (6)** — #84 승인 기록, 사용자 격리 점검(세션 magus-25, 로컬·서버 변경 없음)
- #84는 승인. 구현은 7단계 뒤 첫 작업이다. 그 요청 사이에 #84 구현을 시작하라는 지시가 있었으나, 이어진 요청으로 시기가 바뀌어 코드는 건드리지 않았다.
- 격리 경로를 처음부터 끝까지 읽고, 빠진 시험 7개를 `tests/test_isolation.py`에 넣었다. 세 가지 변조로 시험이 실제로 잡는 것도 확인했다. 문제는 찾지 못했다.
- 남긴 것: claude.ai 확인(사용자), 다음 태그 때 push.

**2026-10-06 (5)** — "저자 확인 질문지" 기능 조사(읽기만, 구현 없음, 세션 magus-25)
- father-trial에서 지금 도구·화면으로 질문 18곳과 부록 A~D를 얼마나 얻는지 재고, 판별 위치를 정리했다. 설계안 초안 `docs/decisions/author-questions.md`, 검토 대기 #84.
- 응답 크기(추정): book_outline 2,231, ref_check(35) 650, book_issues(kind=fact) 10,628, book_issues 전체 18,048토큰. 질문지는 18곳에 1,500~2,000토큰으로 본다.

**2026-10-06 (4)** — 결정 #80~#83, 병합, 태그 `p1-reupload`·push, 서버 배포, 아버지 자료용 데이터(세션 magus-25)
- `docs/worktree-rule`을 병합하고(`e396d3f`) push했다. 그 뒤로 동시 세션 규칙(각자 worktree, 메인 트리에서 switch·checkout·reset 금지)을 따른다.
- 서버를 `896633c` → `4df2720`으로 옮겼다. 백업·data 해시·되돌리기 이미지를 갖추고 했고, data 원본 해시는 같다(0-5절).
- 아버지 자료용 데이터를 `private/reports/`에 만들었다(리포 밖).
- 남긴 것: claude.ai 확인(사용자). 7단계 완료 때 `p1-step7` 태그.

**2026-10-06 (3)** — #69~#77 구현, 다시 올리기 기본(#76), 최신본 재임포트·다시 올리기 시험(세션 magus-25, 로컬 전용)
- 단계마다 테스트를 넣고 커밋했다(0-4절 해시). 테스트 223개 통과, ruff(F·B) 통과. 간헐 실패 `test_request_size_limit`도 이번에는 5번 모두 통과했다.
- 다른 세션(magus-a1)이 잠깐 메인 트리 HEAD를 옮겼다가 되돌렸다. 그 뒤 그쪽은 별도 worktree만 썼다. 그 세션의 병합 브랜치는 master에 합쳤고(`9162a8b`), CLAUDE.md 운영 규칙 브랜치는 사용자 확인 대기로 남겼다.
- 검증하면서 두 가지를 더 고쳤다: PDF 판 미해결을 코멘트 본문으로 잇기(`0109ad4`), 저자에 괄호가 있는 참고문헌 제목(IEA 중복 찾기)·리포트 장 수(`a1c9a12`).
- 남긴 것: 서버 배포(승인 대기), `docs/worktree-rule` 병합(확인 대기). 태그는 달지 않았다(7단계 완료 때 `p1-step7`).

**2026-10-06 (2)** — 토큰 aud 검사 강화(#79), 서버 반영·이력 교체(세션 magus-a1, 다른 세션 magus-25의 #69~ 작업과 동시 진행)
- `decf79c`(서버 실행 커밋의 새 이력판)에서 `fix/auth-audience`를 갈라 고쳤다(별도 worktree `.worktrees/auth-audience`, `.git/info/exclude`로 숨김). 태그 `p1-auth-audience`.
- 서버에 그 태그만 반영했다. master는 배포하지 않았다. 서버 옛 이력은 교체하고 gc했다. data 해시 같음.
- master에 병합하고 브랜치·태그·master를 push했다. 결정 문서 `docs/decisions/shared-auth-audience.md`.
- 실수 1건: 처음에 메인 작업 트리에서 `git switch`를 해 magus-25의 작업 트리를 약 1분 decf79c로 옮겼다. 바로 master로 되돌렸고(미커밋 수정 4개 그대로), magus-25에 알렸다. 그 뒤로는 별도 worktree에서만 작업했다.
- 남긴 것: 사용자의 claude.ai 확인. 서버 `magus:rollback-21b4e2a` 이미지는 다음 배포 때 삭제(사용자 지시).

**2026-10-06** — 작업 방식 결정 #68, 최신본 시험 임포트, 다시 올리기 설계안(로컬 전용, 서버 변경 없음)
- #68을 기록했다(`docs/decisions/author-file-is-source.md`). CLAUDE.md·README·store-interface.md를 결정에 맞게 고쳤다.
- 최신본 docx를 `father-trial`에 임포트하고 10/02 판(default)과 비교했다. default 해시는 같다(1,383개 파일).
- 문제를 찾았다: 표 글 누락, "제N부 들어가며", 작성자 버림, `[점검·…]` 분류, 앵커 120자. 검토 대기 #69~#73으로 올렸다.
- instructions 규칙 4가 #68과 충돌한다(#74). 완료 기준 수치(#75), 다시 올리기 설계안 범위(#76)도 올렸다.
- 다시 올리기 설계안 초안을 썼다(`docs/decisions/reupload-design.md`, 미구현).
- 코드는 바꾸지 않았다. 테스트는 돌리지 않았다(코드 변경 없음).

**2026-10-05 (4)** — P1 6단계 완료
- 사용자가 모바일 시험도 성공했다. 토큰 갱신은 실사용 중 확인하기로 하고 7단계 전 확인 항목으로 옮겼다.
- 읽기 전용 점검을 했다. 검토 대기 결정 #45~#64 표를 만들었고, push 전 점검에서 비밀·원본이 이력에 없음을 확인했다(`docs/reports`만 결정 대기).
- 일지 `docs/daily/2026-10-05.md`를 커밋했다(`18df6e2`). status를 갱신한 커밋에 `p1-step6` 태그를 단다.

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
- 사용자 결정을 반영했다: Production(이후 Staging으로 바뀜, #49), 허용 목록 순서, claude.com 콜백.
- 웹 로그인 401/403 문구를 나누고 원인을 로그에 남기게 했다. 빈 허용 목록으로 시작할 수 있게 했다. 403 화면에 본인 id를 보인다.
- docs: deploy.md 2-1절, onboarding-father.md 초안.
- 테스트 190개 통과, ruff(F·B) 통과. 커밋했다(태그 없음).

**2026-10-03 저녁(16:30~19:50)** — P1 1~4단계 완료(`p1-step1`~`p1-step4`), 5단계 준비(로컬 복구 훈련 outline 같음).

## 7. 알려진 문제 — 실원고에서 아직 안 맞는 것

- **docx 임포트(2026-10-06)**: #69~#73·#77·#76으로 표·들어가며·작성자·분류·앵커·제목·IEA 중복·key 안정화를 고쳤다. 남은 것:
  - 책 제목은 파일 속성 제목과 표지의 Title·Subtitle 서식에서만 읽는다. 4판처럼 속성 제목이 없고 표지에 서식도 없으면 파일 이름이 제목이 된다. 임포트 때 제목·부제 칸에 적으면 그것을 쓴다.
  - (처리함 #81) `상트페테르부르크(1703)`(제27장 표)는 비인용 용어에 넣었다.
  - `셰 등(2019)`(제30장)이 미연결이다. 참고문헌에 Hsieh 2019가 두 편(hsieh2019 housing, hsieh2019-2 talent)이라 음역 추정이 하나로 정해지지 않는다. 저자에게 묻는다(#82). 답을 받으면 `magus alias`로 잇는다.
  - 다시 올리기는 같은 번호 = 같은 장이다. 장을 끼워 넣어 번호가 밀리면 내용이 다른 장을 같은 장으로 보고 교체한다(이전본은 versions/, 미해결은 걸린 문장으로 따라간다). 본문 유사도·이동·분할 판정은 뒤로 미뤘다(#76).

- **간헐 실패 테스트(Windows)**: `tests/test_http.py::test_request_size_limit`(2026-10-05 발견).
  - 5번 중 3번 실패했다(`-x`로 돌림).
  - 증상: 서버가 Content-Length만 보고 413으로 먼저 끊으면, 2MB 넘는 본문을 보내던 urllib 클라이언트가 응답 대신 `ConnectionResetError`/`ConnectionAbortedError`를 받는다.
  - 서버 동작(413으로 거절)은 맞다. 테스트가 리셋을 견디도록 고쳐야 한다(예: 리셋도 "거절됨"으로 받거나, 헤더만 보내고 응답을 먼저 읽기). 아직 고치지 않았다.
- **표(PDF 판만)**: 칸 구분 없이 한 문단으로 들어온다(27장 등). docx는 #69로 markdown 표다. 표 안의 도시 설립 연도는 비인용 용어 파일로 걸렀다(그대로 둠, docx 재임포트 때 다시 본다).
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
- **저자 보고서 생성기(`author_report.py`)의 작은 오탐**(2026-10-06 발견, 고치지 않음): 같은 표기가 한 장에 두 번 있으면 장 번호가 두 번 찍힌다("제35·35장 하야시(2016)"). 이름 대조가 Lee(1969)에 '이상호'(다른 사람, 제32장)를 섞는다. 다음 저자 보고서 전에 고친다.
- 이전부터 있던 것: 번호 충돌 가능성(멀티 프로세스), 직접 수정 뒤 reindex 필요, 토큰 추정 휴리스틱, 임베딩 API 실제 호출 미검증.
