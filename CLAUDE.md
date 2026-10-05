# Magus — 집필 RAG MCP 서버

- **세션을 새로 시작하면 가장 먼저 status.md를 읽는다. 그다음 이 파일의 진행상황 섹션을 본다. 작업은 status.md의 '지금 바로 할 일'부터 재개한다.**

## 진행상황

- 현재 단계: **P1(원격 MCP 서비스) 1~6단계 완료**(`p1-step1`~`p1-step6`).
  - 서버는 Vultr 서울에 배포했다(`https://magus.lifebookapplication.com`, WorkOS Staging). 백업과 서버 복구 시험을 마쳤다.
  - claude.ai 커스텀 커넥터로 웹·모바일 연결에 성공했다(CIMD).
- 원격 저장소: GitHub 비공개 `sml122900/Magus`(`origin`). **단계 태그를 찍으면 push까지 한다**(아래 "원격 저장소").
- **사용자 결정 #68(2026-10-06)**: 원고 본문의 원본은 저자의 Word(·한글) 파일이다. Magus의 원고는 최신 업로드의 사본이다(`docs/decisions/author-file-is-source.md`).
  - 다시 올리기가 핵심 기능이 됐다. 기본 부분을 구현했다(#76, `magus/book/reupload.py`, 설계·확정 범위는 `docs/decisions/reupload-design.md`).
- **7단계 준비(2026-10-06, 로컬)**: #69 표, #70 제N부 들어가며, #71 코멘트 작성자·AI 확인 요청, #72 [점검] 분류, #73 걸린 문장 전문, #74 규칙 4, #77 제목·부제, #76 다시 올리기 기본을 구현했다(status.md 0-4절).
  - 최신본을 `father-trial`에 새로 임포트해 수치를 쟀고, `reupload-trial`에서 4판 → 최신본 다시 올리기를 시험했다(기존 미해결 86 유지 + 새 43, 바뀐 장 6만 교체).
- **운영 규칙(#78)**: 같은 책을 다시 올릴 때는 수정본(`new_edition`)으로 한다. 아버지 원고를 `replace`로 다시 임포트하지 않는다. replace는 결정·직접 남긴 미해결·닫은 미해결까지 휴지통으로 보낸다.
- 다음 할 일: **7단계 아버지 온보딩**(`docs/onboarding-father.md`). 시작 전 확인은 status.md "7단계 전 확인"을 따른다. 그 전에 사용자가 claude.ai에서 book_outline을 한 번 확인한다.
  - 7단계 뒤 첫 작업: 저자 확인 질문지 `book_questions`(#84 승인, `docs/decisions/author-questions.md`).
  - 사용자 격리: 아버지 계정 추가 전에 점검했다(status.md 0-6절, `tests/test_isolation.py`).
- 다음 배포에 함께(커밋만): #90 되묻기 선택지에서 원고 빼기. 검토 대기: #91 사용자 서랍 설계안(`docs/decisions/user-drawers.md`).
- 서버(2026-10-06 03:25부터): master `p1-trash`(`74bbbf4`: 휴지통 #88·도구 설명 가드와 내부 이름 빼기 #87·문체 tags_by #89, 그 전 `p1-ui-terms` 포함). 되돌리기 기준은 `2d9777f`(이미지 `magus:rollback-2d9777f`, status.md 0-8절).
  - 다음 배포도 docs/deploy.md "업데이트" 절차(`git fetch … master && git checkout -B master FETCH_HEAD`)로 한다.
- 알려진 문제: `tests/test_http.py::test_request_size_limit`가 Windows에서 간헐적으로 실패한다(413 응답 전에 연결이 리셋됨). 서버 동작은 정상이다(status.md 7절).
- 대기 사항: 계정·키·결정·아버지 docx처럼 사용자만 할 수 있는 것(status.md에 "대기"로 적는다), 저자 보고서 답변. 상세는 status.md에만 적는다.

## 개요

책을 쓰는 사람이 머릿속 재료를 세 책장(코어)에 넣어 두고, Claude가 MCP로 꺼내 쓰게 하는 서버.
책장은 **사람 소유**(여러 책에 재사용), 원고는 **책(프로젝트) 소유**.
**원고 본문의 원본은 저자의 파일(Word·한글)이다.** Magus의 원고는 최신 업로드의 사본이다. 저자는 Word에서 고치고, 바뀌면 다시 올린다(사용자 결정 #68).

## 왜 만드나 (막아야 할 다섯 가지)

실제 사례: 한 교수가 Claude로 297쪽(35장 8부, 약 34만 자) 책을 썼다.

1. 한 대화에서 책 전체를 10번 재생성했다. 장 하나 추가할 때마다 전체를 다시 썼다. → **장 단위 저장, 책 전체를 반환하는 도구 없음**
2. 대화가 바뀌면 생각이 사라졌다(md 수동 첨부 8번, ChatGPT 답변 복붙). → **Casper(영감) 책장**
3. 인용 약 270개, 참고문헌 약 250편이 LLM 기억에서 생성됐다. Word 코멘트 86개 중 82개가 "확인 필요". → **Melchior(문헌) + 인용 게이트**
4. 문체가 저자의 목소리가 아니라 LLM 기본 문체였다. → **Balthasar(문체) 책장**
5. 원고가 두 파일로 갈라졌다. → **단일 진실 원천은 저자 파일.** Magus는 최신 업로드의 사본(ch-NN.md)을 들고, 다시 올리기로 맞춘다(#68. P0의 "디스크의 ch-NN.md가 원천"에서 바뀜)

## 이름과 명명 규칙

- 프로젝트·패키지·리포 이름: `magus`. MCP 서버 이름(클라이언트 표시): **"Magus"**.
- 모티브: 동방박사의 세 선물. 세 책장은 저자에게 선물을 바치는 세 현자다. 서로 토론하거나 투표하지 않는다. 받고 결정하는 사람은 저자다.

| 코어 | 모듈 | 표시명 | 성격 |
|---|---|---|---|
| 1번 영감 | `magus/casper/` | Casper · 몰약 | 보존하는 창고 |
| 2번 문헌 | `magus/melchior/` | Melchior · 황금 | 검증된 근거만 |
| 3번 문체 | `magus/balthasar/` | Balthasar · 유향 | 글에 배는 것 |
| 원고 | `magus/book/` | — | — |

- **MCP 도구 이름은 바꾸지 않는다**: `idea_*`, `ref_*`, `style_*`, `book_*`. 마기 이름은 코드 모듈, 로그, README, 앞으로 만들 UI에만 쓴다.
- 디스크의 shelf 하위 폴더 이름도 모듈 이름을 따른다: `shelf/casper`, `shelf/melchior`, `shelf/balthasar`.

### 저자에게 보이는 이름 (사용자 결정 #85, 2026-10-06)

**저자에게 보이는 글은 이 이름으로 쓴다**: 웹 화면, 도구 응답 문장, 서버 instructions의 사용자 대상 표현, 저자 대상 문서(onboarding-father·connect-claude·README).
코드·도구 이름(`book_*`·`idea_*` 등)·모듈 이름(Casper 등)·도구 설명·내부 설계 문서(decisions 등)·파일 형식(issues.md 등)은 바꾸지 않는다.

| 이름 | 뜻 | 기존에 섞여 쓰인 말 | 내부 |
|---|---|---|---|
| 전체 | 책 전체 현황(구성·상태). 원고 전문이 아니다 | 책 지도 | book_outline |
| 확인 요청 | 출처·사실을 확인해야 하는 곳. AI가 단 것은 "AI 확인 요청" | 미해결, 이슈 | issues |
| 생각 | 떠오른 아이디어 메모 | 영감 | Casper, idea_* |
| 문체 | 좋아서 모은 구절 | 문체 취향, 문체 책장 | Balthasar, style_* |
| 문헌 | 원문을 읽고 등록한 책·논문 | refs | Melchior, ref_* |
| 결정 | 정해 둔 방침 | | book_decide |
| 수정본 | Word에서 고친 원고를 다시 올린 것. 번호 E2, E3…는 "수정본 번호". 첫 업로드 E1은 "처음 올린 원고" | 새 판, 다시 올리기 | book_import new_edition |

- Claude에게는 서버 instructions 규칙 7~9로 전한다: 이 이름으로 답하기, "전체 보여 줘"·"수정본 올렸어" 같은 말을 도구로 옮기기, 넣을 곳을 말하지 않은 "저장해 줘"에는 먼저 묻기(아래 "서버 instructions").

## 절대 원칙

- **원고 본문의 원본은 저자 파일이다**(사용자 결정 #68).
  - 원고 상태(목차·결정·미해결·판 이력)는 대화 밖, Magus에 둔다. 이 원칙은 그대로다. 바뀐 것은 원고 본문의 원본이 저자 파일이라는 점이다.
  - Claude의 원고 수정안은 대화로 내고, 저자가 Word에 반영한다. Magus 안의 원고를 Claude가 고쳐 쓰는 것(book_write_chapter)은 기본 흐름이 아니다.
  - 서버 instructions 규칙 4도 이에 맞게 바꿨다(사용자 결정 #74). book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓴다.
- **에이전트는 책 전체를 들고 있지 않는다.** 한 작업의 컨텍스트는 목차·결정·미해결(book_outline) + 장 1개 + 검색 top-k로 이루어진다. 책 전체를 반환하는 도구는 만들지 않는다.
- **인용 게이트**: refs에 `status=verified`로 있는 출처만 인용할 수 있다. 없는 출처는 본문에 `[출처 필요: 주장 요약]`으로 남긴다. 쓰기를 막지는 않는다. 표시하고 집계만 하며, 판단은 사용자가 한다.
- **누가 말했는지 보존한다.** Casper는 사용자 발화(`author=me`)와 AI 발화(`author=ai`)를 구분해 저장하고, 검색에서는 me를 먼저 보여 준다.
- **Magus 안의 원본은 사람이 읽을 수 있는 파일(markdown/json)이다. SQLite는 인덱스일 뿐이다.** (원고 본문의 ch-NN.md는 그 자체가 저자 파일의 사본이다.) 인덱스는 언제든 파일에서 다시 만들 수 있어야 한다(`magus reindex`). 파일에 없는 정보를 SQLite에만 두지 않는다. 예외는 계산으로 얻는 값(char_count, unverified_cite_count, chunks)이다.
- **프로젝트 폴더 밖의 파일은 사용자가 경로를 명시해 지시했을 때만 읽는다.** 필요한 파일이 없으면 status.md에 "대기: 무엇을, 누가"로 기록하고 멈춘다. 다른 폴더를 뒤져 찾아오지 않는다.
  - "프로젝트 폴더 밖"에는 환경이 알려 준 경로(대화 기록 파일, 홈 폴더, Downloads)도 포함된다. 사용자가 이 세션에서 경로를 직접 적었을 때만 읽는다.
- **지시문의 참조를 찾지 못하면 밖에서 찾거나 추측하지 않는다.** status.md에 "불명: …"으로 적고, 내 판단으로 진행한 뒤 보고한다(예: "위 세 가지 테스트 프롬프트"가 메시지에 없을 때).
- **합성·테스트 데이터는 `default` 사용자에 넣지 않는다.** default는 실제 저자의 책장이다. 데모 문체 표본이 저자의 취향으로, 가짜 서지가 진짜 서지로 섞인다. 데모는 `USER_ID=demo`, 합성은 `USER_ID=synthetic`을 쓴다. CLI는 default에 `seed-demo`와 `import --synthetic`을 거부한다.
- **SaaS 준비**
  - 모든 레코드(모든 테이블의 모든 행)에 `user_id`가 있고, 모든 쿼리는 `user_id`로 필터한다.
  - P0는 단일 사용자(환경변수 `USER_ID`)다. 그래도 코드 어디에서도 단일 사용자를 가정하지 않는다. Store 메서드는 항상 `user_id`를 인자로 받는다. 서버 코어에서 user_id를 정하는 곳은 `current_user()` 한 군데뿐이다(P1에서는 인증 컨텍스트로 바꾼다).
  - 저장소는 `Store` 인터페이스(`magus/store/base.py`) 뒤에 둔다. P0 구현은 `LocalStore`(파일 + SQLite), P1 구현은 Postgres + 객체 스토리지다.
  - 전송(stdio / streamable-http)은 서버 코어(`magus/server.py: build_server`)와 분리한다(`magus/transports.py`). P0는 stdio만 구현하고 HTTP 진입점은 자리만 둔다.
- **서버는 P0에서 LLM API 키가 필요 없다.** 문체 태그 추출·요약 같은 일은 호출하는 Claude가 하고 결과를 도구 인자로 넘긴다. 외부 API는 임베딩뿐이다. `EMBEDDINGS=none`이어도 모든 도구가 FTS만으로 동작해야 한다.
- **도구 응답은 짧게.** 목록에는 상한을 두고, 긴 본문은 요청한 것만 돌려준다. book_outline은 3,000 토큰 이하다.

## 스택

- Python 3.12, uv, pytest. (uv 위치: `%APPDATA%\Python\Python313\Scripts\uv.exe`, PATH에 없음. 이 경로를 그대로 쓰기로 했다. README "uv가 PATH에 없을 때")
- MCP 공식 Python SDK **2.x** (`mcp>=2.2`, 2.2.0 기준으로 진행). 1.x와 API가 다르다.
  - `from mcp.server.mcpserver import MCPServer` (`FastMCP`는 없어졌다).
  - instructions는 생성자에서만 받는다. 그래서 `Tool.from_function(fn, name=, description=, structured_output=False)`로 도구 목록을 먼저 만들고, `MCPServer(name=, instructions=, tools=)`로 서버를 만든다.
  - JSON을 돌려주는 도구도 `structured_output=False`로 두고 텍스트 한 블록에 담는다. `structuredContent`에 같은 내용이 중복되는 것을 막기 위해서다.
  - 예상한 실패는 `mcp.server.mcpserver.exceptions.ToolError`로 올린다. 그러면 결과가 `is_error=True`가 되고 메시지가 모델에 전달된다.
  - Bash 도구의 heredoc에서는 `\\`가 `\`로 줄어든다. 백슬래시가 들어간 소스는 Edit/Write 도구로 고친다(`docs/troubleshooting/bash-heredoc-backslash.md`).
  - `server.run("stdio")` / `server.run("streamable-http", host=, port=)`.
  - 동기 도구 함수는 워커 스레드에서 실행된다 → `LocalStore`는 `check_same_thread=False` + RLock을 쓴다.
  - 테스트: `async with mcp.Client(server) as c: await c.call_tool(...)`로 in-process 연결. `c.instructions`로 instructions를 확인한다.
- SQLite + FTS5(키워드 검색). 벡터는 BLOB(float32)으로 저장하고 numpy 브루트포스 코사인으로 계산한다(P0 규모인 수만 청크까지 충분하다). 키워드와 벡터 결과는 RRF(k=60)로 합친다(`magus/search.py`). 한국어 고유명사와 학자 이름 때문에 키워드 검색은 뺄 수 없다.
  - **한국어 토큰화(확정)**: 한글·한자·가나 연속열은 2글자 bigram, 라틴 문자와 숫자는 소문자 단어로 사전 토큰화해 FTS5 unicode61에 넣는다. 질의도 같은 방식으로 쪼개 OR로 묶는다(`magus/textindex.py`). 2글자 이름("갤러")도 찾는다.
  - 임베딩은 파생값이다. 인덱스를 다시 만들면 비고, 검색할 때 `embed_missing`이 채운다. 임베딩 호출이 실패하면 FTS로 계속한다.
- docx 읽기: zip 안의 XML을 lxml로 직접 걷는다(`magus/book/docx_reader.py`). 코멘트 범위·sdt·삭제분·필드 코드를 정확히 다루기 위해서다. python-docx는 합성 fixture 생성과 export 검증에만 쓴다. docx 쓰기: `pypandoc_binary`(pandoc 3.9 내장).
- PDF 텍스트: pymupdf(`import pymupdf`). docx가 없을 때 폴백으로 원고 PDF도 받는다. **실원고가 이 경우다**(Word '메모 포함' 마크업 PDF). `magus/book/pdf_reader.py`는 레이아웃으로 구조를 되살린다.
  - 반복 머리말·쪽번호를 빼고, 오른쪽 68% 단은 말풍선 `메모 포함[Cn]`(여러 줄)으로 본다.
  - 줄 끝 공백이 없으면 이어 붙인다(한국어 줄바꿈). 들여쓰기·내어쓰기·줄 간격으로 문단을 가른다(내어쓰기 서식은 글자 크기별로 판별).
  - 글자 크기로 제목 단계를 정하고, 같은 높이 조각은 한 줄로 합친다. 앵커는 말풍선 높이의 문단이다.
  - 표는 칸 구분 없이 문단으로 들어온다.
- 임베딩: `magus/embeddings.py`. Voyage(기본 모델 voyage-3.5)와 OpenAI(text-embedding-3-small)를 표준 라이브러리 HTTP로 부른다. 모델은 `EMBEDDINGS_MODEL`로 바꾼다. 키가 없으면 경고를 남기고 FTS만 쓴다.

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `USER_ID` | `default` | P0 단일 사용자 id(영문·숫자·`_`·`-`, 64자 이하) |
| `DATA_DIR` | `./data` | 원본 파일과 index.sqlite의 루트 |
| `FILES_DIR` | `DATA_DIR`의 부모 | 도구가 받은 상대 경로(`fixtures/papers/논문.pdf`)를 푸는 기준. Desktop이 띄우는 작업 폴더는 정해져 있지 않으므로 작업 폴더 기준으로 풀지 않는다(`magus/paths.py`) |
| `EMBEDDINGS` | `none` | `none` \| `voyage` \| `openai` |
| `PUBLIC_URL` | — | 원격 모드: 바깥에서 보이는 주소. 커넥터 URL과 PRM의 resource = `PUBLIC_URL/mcp` |
| `AUTH_ISSUER` | — | 원격 모드: 인증 서버 issuer(WorkOS AuthKit). 있으면 HTTP에서 토큰 검증을 켠다 |
| `AUTH_JWKS_URL` | issuer 메타데이터의 jwks_uri | 서명 키 주소 |
| `AUTH_AUDIENCE` | `PUBLIC_URL/mcp` | 비워 둔다. `PUBLIC_URL/mcp`와 다르면 시작하지 않는다. 토큰 aud는 그 값 하나만 받는다(문자열, 또는 원소 하나인 목록. 결정 #79, `docs/decisions/shared-auth-audience.md`) |
| `ALLOWED_USERS` | — | `sub=user_id` 쉼표 목록(sub는 WorkOS 사용자 id `user_…`, 이메일 아님). 여기 없는 sub는 403. 비우면 모두 403(첫 배포에서 id를 얻는 단계). 같은 sub나 같은 이름이 두 번이면 서버가 시작하지 않는다(오류에는 항목 순서만, id는 쓰지 않음). 공개 가입은 없다 |
| `PORT` | 8000 | `magus serve --transport http`의 기본 포트 |
| `MAX_UPLOAD_MB` | 50 | 받은함 업로드 한 개 한도 |
| `MAX_USER_MB` | 1000 | 사용자별 저장 용량(사용자 폴더 전체) |
| `MAX_REQUEST_MB` | 2 | MCP 요청 본문 한도(넘으면 413) |
| `SESSION_SECRET` | (로컬: 실행마다 무작위) | 웹 세션·내려받기 링크 서명 비밀. **원격 모드에서는 필수**(32자 이상) |
| `WEB_CLIENT_ID` / `WEB_CLIENT_SECRET` | — | 웹 로그인용 OAuth 클라이언트(인증 서버에 등록, 콜백 `PUBLIC_URL/auth/callback`). 없으면 웹 로그인이 꺼진다 |
| `VOYAGE_API_KEY` / `OPENAI_API_KEY` | — | 해당 제공자를 쓸 때만 |
| `EMBEDDINGS_MODEL` | 제공자 기본값 | 임베딩 모델 이름 |

## 데이터 모델 (모든 테이블에 user_id가 있다)

- users(id), projects(id, user_id, title, subtitle?, title_en?, subtitle_en?)
  - **제목과 부제를 따로 둔다(#77).** 원고에서 읽는다: docx 파일 속성 제목을 `—`·`:`에서 나눠 제목·부제로, 표지에서 그 제목(과 부제) 바로 뒤의 라틴 문자 문단 둘을 영문 제목·부제로. 속성이 없으면 표지의 Title·Subtitle 서식 문단. 사람이 준 title·subtitle이 먼저다. 한글 부제를 표지에서 추정하지는 않는다.
- parts(user_id, project_id, number, title) — *추가(승인됨)*: 완료 기준의 "부 8개"를 위해 둔다. book_outline은 부 제목 아래에 장을 묶어 보여 준다.
- chapters(id, user_id, project_id, number, label?, title, status, part_number, path, char_count, unverified_cite_count, version, last_note, updated_at)
  - **번호 없는 장**: 서장·프롤로그 = 0, 맺음·에필로그·나가며 = 90, 부록 N = 90+N. `label`(서장·맺음·부록 N)을 앞머리와 인덱스에 두고, outline·export·read에서 "제N장" 대신 보여 준다. 부에 속하지 않는다.
    - **제N부 들어가며** = 100+N(#70). label `제N부 들어가며`, part_number N(그 부에 속한다). 장 목록·outline·export는 **읽는 순서**(`store.base.reading_order`)라 그 부의 첫 장 바로 앞에 온다.
    - outline 장 줄에는 번호 없는 장의 번호를 괄호로 적는다(`서장(0)`, `제2부 들어가며(102)`). 도구에 줄 번호다.
  - **status 값은 `draft` | `revising` | `done` 중 하나다.** 쓸 때 그 밖의 값이 오면 거부한다(Store는 ValueError, 도구는 스키마 enum으로 막는다).
- chapter_versions(id, user_id, chapter_id, version, path, note, created_at) — 보관된 **이전** 본문들
- chapters.edition: 본문이 같은 업로드 판(E1, E2…). 업로드가 쓰면 그 판 번호, book_write_chapter로 고치면 비워진다(= Magus에서 고친 본문, #76).
- editions(project.json `editions`): 업로드 한 번 = 판 하나. `{number, file, uploaded_at, sha256, changed, added, removed, unchanged, legacy?}`. 첫 임포트가 E1이다. 판 기록 전 임포트는 다시 올릴 때 legacy E1로 적는다.
- decisions(user_id, project_id, id, text, created_at) — id는 프로젝트별 일련번호 `D{n}`
- issues(user_id, project_id, id, text, status: open|closed, origin: import_comment|user|agent, chapter_number?, created_at, closed_note?, kind: citation|fact|general, ref_key?, ref_id?, author?, author_kind?: ai|person, comment_date?, anchor?, paragraph?) — id는 프로젝트별 일련번호 `I{n}`
  - **걸린 문장 전문(`anchor`, 1,000자까지)과 장 본문의 문단 번호(`paragraph`)를 둔다(#73).** 문단 번호는 ref_check의 paragraphs와 같은 번호다(빈 줄로 나눈 N번째, 소제목 포함). 본문 끝의 `— 원문: “…”`은 표시용 120자다. book_issues·book_read_chapter는 `¶N`으로 보인다. 다시 올리기에서 걸린 문장이 남았는지 이것으로 본다.
  - **원고 코멘트의 작성자를 보존한다(#71).** `author`는 Word 이름 그대로, `author_kind`는 이름으로 판정한다(`book/comments.py: author_kind`, 기본 AI 이름 목록 + 프로젝트의 `book/ai_authors.txt`). 파일(issues.md)에 적으므로 사람이 고칠 수 있다.
    - AI가 단 코멘트에서 온 미해결은 저자에게 보일 때도 **AI 확인 요청**으로 드러난다: book_issues 출처 `AI 확인 요청(Claude)`, book_read_chapter `[AI 확인 요청]`, outline `그중 AI 확인 요청 N건`, 웹 `/issues`·`/book`의 🤖, 저자 보고서 5절.
  - `kind`: 임포트할 때 코멘트로 정한다. 직접 남긴 이슈는 `general`이 기본값이다.
    - 출처 확인 코멘트: 본문에 "확인 필요", "인용 확인 필요", "원문 대조"가 들어 있거나(공백 차이와 실제 변형 허용), 독립된 낱말 "서지"가 있는 것("일어서지"는 아님).
    - **태그가 먼저다(#72)**: `[점검·인용]`·`[점검·서지]`는 출처 확인(문헌이 지목되면 citation, 아니면 fact), `[점검·통계|수치|연도|사실|사례|계산]`은 fact다. 모르는 태그와 `[사진]`은 위 표현으로 가른다.
    - `citation`: 출처 확인 코멘트이고 문헌이 지목된 것(코멘트 본문, 또는 서로 다른 인용이 하나뿐인 앵커에서 저자·연도를 찾음).
    - `fact`: 출처 확인 코멘트지만 문헌이 없는 것(사실·수치 확인 요청). 인용처럼 보인 것이 모두 비인용 용어여도 fact다("확인 필요"가 붙어 있으면 무엇이든 확인 요청이다. 사용자 결정 #36, I46 `선하이정(1835)`).
    - `general`: 확인 요청이 아닌 코멘트(작업 안내, 검토 메모 등).
  - **비인용 용어**: 프로젝트별 `book/non_citation_terms.txt`(한 줄에 하나, `#` 주석). 연도 앞에 오는 지명·사건·기관(마닐라(1571), 모스크바 회사(1555))을 인용 추출 전체(ref_check, 집계, 이슈 연결, 코멘트 분류)에서 뺀다. 여러 낱말 용어는 저자 앞 글과 이어서 본다. `--replace` 재임포트 때 새 프로젝트로 옮긴다. CLI `magus terms`로 고친다.
  - `ref_key`: citation 코멘트에서 뽑은 저자·연도 후보(`daeschler2006`, 한글이면 조사를 뗀 `갤러2022`). 코멘트 본문에 없으면 앵커 원문에서 찾고, 그래도 없으면 null이다. 추출기는 `magus/melchior/citations.py`이고, ref_check도 이것을 쓴다.
  - `ref_id`: ref_key를 refs(key 또는 aliases)에서 해석한 **정식 ref key**(예: `갤러2022` ⇒ `galor2022`). refs 행 id는 재생성되면 바뀌므로 key를 쓴다. 임포트, ref_add, ref_import_bibliography 뒤에 다시 계산한다.
- chapters.unverified_cite_count: verified가 아닌 **고유 문헌 수**(unverified + unknown, uncertain 제외). 출현 횟수가 아니다(사용자 결정 #17 변경). 파생값이라 인덱스에만 두고, 서버 시작·`magus reindex`·refs 변경·장 쓰기 때 다시 계산한다.
  - chapters.unverified_cite_keys / uncertain_cite_keys(JSON): 같은 때 함께 계산하는 그 장의 미확인 문헌 key와 미연결 한글 표기 key다. outline은 장 사이 합집합으로 책 전체 고유 수를 낸다(SCHEMA_VERSION 8에서 도입).
  - 이 캐시는 refs가 바뀌면(ref_add, ref_import_bibliography, `magus alias`, `magus terms`) 그 자리에서 사용자의 모든 장을 다시 계산한다(실원고 40장 0.3초). ref_add 직후 outline 수가 줄어드는지 테스트로 고정했다(사용자 결정 #43).
  - **한 번 준 번호는 절대 재사용하거나 다시 매기지 않는다.** 마지막 번호는 project.json의 `last_decision_id`/`last_issue_id`에 둔다.
- refs(id, user_id, key, aliases json, bib json, status: unverified|verified, has_fulltext, file_path?, created_at)
  - key는 첫 저자 성(소문자 영문) + 연도다. 예: `daeschler2006`, `galor2022`. 한글 표기(갤러, 다이아몬드 등)는 aliases에 넣는다.
- ref_passages(id, user_id, ref_id, text, reason, locator?)
- ideas(id, user_id, text, kind: thought|ai|article|conversation|tv|other, origin?, author: me|ai, parent_id?, created_at)
- style_entries(id, user_id, passage, reason, work?, tags json, created_at, tags_by?: ai|author) — tags_by는 태그를 누가 정했나(#89. Claude가 뽑음 ai / 저자가 말함 author, 기록 전 항목은 비어 있음). SCHEMA_VERSION 13
- chunks(id, user_id, owner_type, owner_id, lane: ref_picked|ref_full|idea_me|idea_ai|style, text, embedding blob?) + chunks_fts

### 디스크 구조 (원본)

```
data/users/<user_id>/shelf/casper/<id>.json                       # ideas
data/users/<user_id>/shelf/melchior/<key>/{bib.json, passages.json, full.txt}
data/users/<user_id>/shelf/balthasar/<id>.json                    # style
data/users/<user_id>/projects/<project_id>/project.json           # title, subtitle?, title_en?, subtitle_en?, created_at, parts, last_*_id
data/users/<user_id>/projects/<project_id>/book/ch-01.md … ch-35.md
data/users/<user_id>/projects/<project_id>/{decisions.md, issues.md, versions/}
data/users/<user_id>/projects/<project_id>/original/{원고 사본, unsplit.md, import-report.md, E2-<원고>, E2-unsplit.md, E2-reupload-report.md …}
data/users/<user_id>/projects/<project_id>/removed/ch-NN-E<판>/   # 새 판에 없는 장(본문 + 이전본). 지우지 않는다
data/users/<user_id>/projects/<project_id>/exports/*.docx       # book_export
data/users/<user_id>/trash/<project_id>-<시각>/                   # book_import replace=True로 밀려난 프로젝트
data/users/<user_id>/trash/shelf/{casper,balthasar}/<id>.json    # 휴지통의 생각·문체(#88). 원래 파일 + "_trash": {at, note, with?}
data/users/<user_id>/inbox/                                       # 받은함(업로드한 원고·논문·대화 기록). 도구는 파일 이름으로 가리킨다
data/index.sqlite
```

### 파일 형식

- `ch-NN.md`: 앞머리(front matter) 다음에 본문이 온다. 장 제목은 앞머리에만 두고 본문에는 넣지 않는다(export할 때 `# 제N장 제목`을 붙인다).
  - **앞머리(front matter)는 도구 경계를 넘지 않는다.** 메타는 서버가 관리한다. 읽기는 본문(content)과 메타 필드를 따로 주고, 쓰기는 본문만 받는다. 호출자가 앞머리를 붙여 보내면 벗겨 내고 응답 warnings에 경고를 넣는다(`docs/decisions/front-matter-boundary.md`).
  - 앞머리에는 **현재 상태만** 둔다. 이력은 versions/에만 남긴다.
  ```
  ---
  title: 물고기의 결심
  status: draft
  part_number: 1
  version: 3
  updated_at: 2026-10-03T02:40:00.123Z
  last_note: 2절 도입부 재작성
  ---

  본문…
  ```
- `versions/ch-NN.vK.md`: 덮어쓰기 직전의 파일을 앞머리째로 복사해 둔다. chapter_versions는 이 파일들에서 다시 만든다.
- `decisions.md` / `issues.md`: 항목마다 `## D3 · <시각>` 또는 `## I3 · open` 제목을 달고, 그 아래 `- key: value` 메타 줄과 빈 줄, 본문(여러 줄 가능)을 둔다.
- 시각은 모두 UTC ISO 8601, 밀리초 단위다(`2026-10-03T02:40:00.123Z`). 프로세스 안에서는 항상 증가하므로 문자열 정렬이 곧 시간 순서다.

### 규칙

- **현재 프로젝트**: 도구에 project_id가 없으면 그 사용자의 가장 최근에 갱신된 프로젝트를 쓴다.
  - 그래서 book_outline 응답 첫 줄에는 항상 `프로젝트: <제목> (<id>)`를 쓴다. 사용자에게 프로젝트가 2개 이상이면 그 사실과 다른 프로젝트 목록을 한 줄 덧붙인다.
- **최근 변경**은 현재 장 머리(version·last_note)와 chapter_versions를 합쳐 시각 내림차순으로 정렬한 것이다.
- 장 파일을 사람이 직접 고쳤다면 `magus reindex`로 인덱스를 갱신한다.

## MCP 도구 (이름 고정)

### 받은함 (`magus/inbox.py`) — P1
- `files_list()` → 받은함 목록(이름·크기·올린 시각·쓰임)과 사용량/한도. *(P1에서 추가된 도구. 휴지통 도구 둘(#88)까지 모두 21개)*
- 파일 인자(book_import의 path, ref_add의 file_path, idea_add_conversation의 path)는 **받은함 파일 이름**을 받는다.
  - 원격(HTTP)에서는 이름만 받는다. 경로를 주면 "받은함에 없다" 오류다(서버 파일을 읽지 못하게).
  - 로컬(stdio) 개발용으로는 받은함에 없으면 로컬 경로(절대 또는 FILES_DIR 기준)도 받는다.
  - 이 차이는 `FileResolver` 한 곳에만 있다(`build_server(local_files=)`, CLI가 stdio일 때만 True).
- 파일 이름: 폴더 구분자·`..`·숨김·제어 문자·예약 이름을 거부하고, 200바이트 이하. 형식은 .docx .pdf .md .txt만 받는다.
- 업로드(`save_upload`)는 한도를 지킨다: 한 개 `MAX_UPLOAD_MB`, 사용자 폴더 전체 `MAX_USER_MB`. 넘으면 무엇이 얼마인지 밝힌 오류를 낸다.
- ref_add가 받은함 파일을 쓰면 refs의 file_path에는 `inbox/<이름>`을 남긴다.
- 로컬 개발: `magus inbox [--add 파일…] [--remove 이름…]`. 원격에서는 웹 업로드(4단계)로만 들어온다.

### 책 (`magus/book/`)
- `book_outline(project_id?)` → **3,000 토큰 이하**. 모든 원고 작업은 이 도구로 시작한다.
  - 첫 줄은 `프로젝트: 제목 (id)`다. 부제·영문 제목이 있으면 둘째 줄에 `부제: … · 영문: … — …`을 싣는다(#77). 프로젝트가 2개 이상이면 안내 줄을 붙인다.
  - 집계 줄: `35장 + 서장·부 들어가며 2·맺음·부록 1~3 · 8부 · N자 · 미확인 문헌 N편 · 미연결 N · 열린 확인 요청 N`. 미확인 문헌은 **책 전체 고유 수**(여러 장에 나오는 문헌은 한 번)이고 저자 보고서 1절의 문헌 수와 같다. 장별 수는 각 장 줄에만 싣는다.
  - 미연결(uncertain: 한글 표기인데 refs와 못 이음)은 미확인 수에 넣지 않지만 숨기지 않는다. 머리줄에 따로 세고, ref_check에는 별도 목록(`uncertain`, `unique_uncertain`)으로 준다(사용자 결정 #29).
  - 장 목록은 부 제목 아래에 묶고, 각 줄에는 집계만 싣는다: `제N장 제목 · 상태 · N자 · 확인 요청 n · 미확인인용 n`. 장별 확인 요청 수에는 코멘트 유래까지 모두 센다.
  - 확인 요청 전문은 origin이 `user`·`agent`인 것만 싣는다(절 제목 `## 열린 확인 요청`). `import_comment`는 `코멘트 유래 확인 요청 N건(citation · fact · general 수) — book_issues(kind)로 조회` 한 줄로만 보인다.
  - 최근 결정 10개, 최근 변경 5개도 싣는다.
  - 머리에 수정본 줄을 싣는다(#76): `수정본 E2 · 마지막 업로드 10-06 14:20(원고.docx) · 그 뒤 Magus에서 고친 장 0`(첫 업로드는 `처음 올린 원고 E1`, 기록 전 임포트는 `수정본 기록 없음(…)`). 마지막 업로드 뒤 7일(`STALE_UPLOAD_DAYS`)이 지나면 "최신본을 올려 수정본으로 올리도록 저자에게 먼저 묻는다"를 붙인다. 서버는 Word 파일이 바뀌었는지 모르므로 시각만 알린다.
  - 수정본을 올린 뒤 "해결됐을 수 있음"인 확인 요청이 있으면 `그중 해결됐을 수 있음 N건` 줄을 싣는다.
  - 예산 배분 순서는 머리 → 목차 → 직접 남긴 미해결 → 결정 → 변경이다. 넘치는 것은 "외 N건"으로 접는다.
- `book_issues(status=open|closed|all, chapter_number?, origin?, kind?, limit=50, project_id?, possibly_resolved=false)` → 미해결 목록(조회 전용). 한 줄에 `I번호 · 상태 · 장 ¶문단 · 출처 · kind(→ref_key) · 내용(300자)`를 담는다. 출처는 user·agent·원고 코멘트(작성자)·AI 확인 요청(작성자). 다시 올린 뒤 표시된 것은 `해결됐을 수 있음(이유, E2)`이 붙고, possibly_resolved=true면 그것만 보인다. limit 최대 200. *(사용자 요청으로 추가된 도구)*
- `book_read_chapter(number, project_id?)` → JSON을 돌려준다. `content`(본문 markdown만), `title`, `status`, `part_number`, `version`, `last_note`, `unverified_cites`, `open_issues`(그 장의 열린 미해결). *(1단계 검토 반영으로 미리 구현)*
  - **`unverified_cites`**: 인용 게이트 결과 중 verified가 아닌 것(`{key, status: unverified|unknown, count, cited_as}`). `[]`는 검사했고 미확인 인용이 없다는 뜻이다(null은 검사 전, 4단계 이후에는 나오지 않는다). `needs_source`는 `[출처 필요: …]` 표시 수다.
- `book_write_chapter(number, content, note, title?, status?, project_id?)` → **#68 이후 기본 흐름이 아니다**(저자가 Magus에 저장하라고 할 때만). 위치는 다시 올리기 설계안 7절을 따른다. content는 본문만 받는다. 이전 본문을 versions/에 저장하고 새 본문을 기록한 **뒤** ref_check를 자동 실행한다(막지 않음). 응답에 `unverified_cites`와 `needs_source`를 담고 장별 집계를 갱신한다. 없는 번호면 새 장을 만든다. front matter가 붙어 오면 벗겨 내고 `warnings`에 경고를 넣는다. 빈 본문은 거부한다.
- `book_decide(text, project_id?)` → D번호.
- `book_issue_add(text, chapter_number?, origin=user|agent, project_id?)` → 없는 장 번호는 거부한다.
- `book_issue_close(id="I3"|"3", note?, project_id?)`
- `book_import(path, project_id?, title?, subtitle?, replace=false)` → 로컬 docx(없으면 pdf)를 새 프로젝트로 만든다(`magus/book/importer.py`).
  - 제목: "제N장"·"제N부"(공백·콜론·대시 변형 허용, 제목이 다음 줄에 와도 됨)와 번호 없는 장(서장·맺음·부록 N, 제목 서식이 있을 때만). "제N부 들어가며 …"는 부 제목이 아니라 그 부의 장(100+N)이다(#70).
  - 같은 장 번호가 여러 번 나오면(목차) 제목 서식이 있는 것, 그다음 본문이 가장 긴 것이 진짜다.
  - 첫 제목 앞의 글(표지·목차)과 부 서문은 `original/unsplit.md`에 둔다(목차 점선은 줄임). 장 안의 절·소절은 `##`·`###`이다.
  - 코멘트 표현: "확인 필요"(확인필요·확인할 필요), "인용 확인 필요", "서지"(문맥 판정), "원문 대조"(원문과·으로 대조).
  - key를 앵커에서 가져오는 것은 앵커 문단에 서로 다른 인용이 하나뿐일 때만이다.
  - 코멘트는 issues(origin=import_comment)로 넣고, 앵커 블록이 속한 장 번호를 기록한다. `classify_comment(코멘트, 앵커 원문)`으로 kind와 ref_key를 붙이고, 본문에 "— 원문: “앵커 120자”"를 덧붙인다.
  - 참고문헌 섹션은 import_bibliography로 넘긴다. 그다음 citation 이슈를 refs와 연결한다.
  - 그림·수식은 자리표시자(`[그림 N]`, `[수식]`)로 남긴다. docx 표는 칸의 글까지 markdown 표(`| 칸 |`)로 싣는다(#69, 칸이 모두 비면 `[표 N]`). export에서는 Word 표로 나간다. 원본은 **무엇보다 먼저** original/에 복사한다.
  - 재실행: 같은 project_id는 거부한다. `replace=true`면 기존 프로젝트를 trash/로 옮긴다. refs는 이미 있는 key를 건드리지 않는다.
    - **replace는 수정본 올리기가 아니다.** 결정·직접 남긴 확인 요청·닫은 확인 요청·판 이력까지 휴지통으로 간다. 같은 책의 수정본은 `new_edition=true`로 올린다(아래).
  - **수정본 = 같은 책의 새 업로드**(`book_import(path, project_id, new_edition=true, force?)`, CLI `--new-edition`, 웹 "수정본으로 올리기", `magus/book/reupload.py`, #76)
    - 같은 책은 사용자가 project_id로 고른다. 장 제목이 기존 판과 30% 미만으로 겹치면 멈춘다(맞으면 force).
    - 장 대응은 같은 번호 = 같은 장이다. 제목이 바뀌면 리포트에 적는다. 본문이 바뀐 장만 다시 쓰고(이전본은 versions/, note `수정본 E2 업로드: …`), 그대로인 장은 버전을 올리지 않고 판 번호만 적는다. 새 판에 없는 장은 removed/로 옮긴다. Magus에서 고친 장이 덮이면 리포트에 ⚠로 남긴다.
    - 원고 코멘트는 지문(`comment_fp` = 작성자 + 날짜 + 본문)으로 기존 미해결과 잇는다. 같은 코멘트는 다시 넣지 않고(번호·상태 유지, 닫힌 것은 닫힌 채), 새 코멘트만 새 미해결이 된다. 지문이 없는 옛 미해결은 코멘트 본문으로 잇는다.
    - 원고에서 코멘트가 사라진 열린 확인 요청은 `stale`로 표시만 한다: 걸린 문장이 아직 있으면 `comment_removed`, 없으면 `anchor_missing`. **자동으로 닫지 않는다.** 닫는 것은 저자다.
    - 결정·직접 남긴 미해결·책장(영감·문헌·문체)은 건드리지 않는다(해시 테스트, `tests/test_reupload.py`). 참고문헌은 새 문헌만 더한다.
    - **참고문헌 key 안정화**: 같은 기본 key(첫 저자 성 + 연도)가 목록에 둘 이상이면 기존 refs와 제목으로 짝을 짓고, 짝이 없는 것만 빈 접미사(-2, -3)를 받는다. 목록 순서가 바뀌어도 key가 문헌을 따라간다(최신본에서 hsieh2019가 다른 논문을 가리키게 되던 문제). 하나뿐이면 예전처럼 "기존 서지와 다름"만 남긴다(#6).
    - 리포트는 `original/E{n}-reupload-report.md`에 남는다.
  - 리포트: 장·부 수, 분할 못 한 구간, 목차로 판단해 버린 제목 줄, 빠진 장 번호, 코멘트→이슈(kind별, ref_key 비율, 장 밖 코멘트), 참고문헌→refs(파싱 실패 줄, key 충돌), `ch-NN.md ↔ 제목` 매핑표. 코멘트 분류 전체 표는 `original/import-report.md`에 있다. 평소에는 리포트를 낸 뒤 멈추고 사용자의 매핑 확인을 기다린다.
- `book_export(path?, project_id?)` → 부 H1·장 H2·소제목 H3로 합쳐 docx를 만든다. path는 파일 이름만 받고 `exports/`에 저장한다. 코멘트와 그림은 복원하지 않는다.

### 문헌 — Melchior (`magus/melchior/`)
- `ref_import_bibliography(text)` → 줄 단위로 저자·연도·제목을 파싱하고 key를 만든다(`magus/melchior/bibliography.py`). status는 unverified다.
  - 지원: APA, 국문 『』, 연도 후치형(근사), 연도 접미사 2012a.
  - `[국역: 이름 성, …, 연도]` 꼬리가 있으면 한글 성 + 원서·번역서 연도를 aliases에 넣는다.
  - 파싱하지 못한 줄은 key `raw-<해시>`, bib.raw로 보관한다. 같은 목록 안 key 충돌은 `-2`를 붙인다.
  - 같은 문헌(첫 저자·연도·제목, 또는 같은 원문 줄)이 목록에 두 번이면 "중복 서지"로 따로 리포트한다. 원고 오류일 수 있다(사용자 결정 #5).
  - 이미 있는 key는 건드리지 않는다. 새 목록의 제목·연도가 기존과 다르면 "기존 서지와 다름"으로 리포트만 한다(갱신하지 않음, 사용자 결정 #6).
- `ref_add(bib, passages: [{text, reason, locator?}], file_path? | full_text?, aliases?)` → status=verified로 넣는다.
  - **발췌가 하나 이상 있어야 받는다.**
  - bib은 `{key}` 또는 `{authors|author, year, title…}`이다. 같은 key나 alias가 unverified로 있으면 verified로 올리고 bib·aliases·발췌를 합친다.
  - key도 저자·연도도 없으면 bib 제목이나 전문 첫머리 5,000자에 참고문헌 제목이 그대로 있는 문헌 하나를 고른다(둘 이상이면 오류). "fixtures/papers/<파일>.pdf를 문헌으로 등록해 줘"처럼 파일만 받는 경우다.
  - 전문은 txt/md/pdf/docx 파일이나 full_text로 받는다. 상대 경로는 `FILES_DIR` 기준이다(book_import, idea_add_conversation도 같다). 발췌는 ref_picked 레인, 전문은 ref_full 레인으로 청킹한다.
- `ref_search(query, scope=picked|full|both(기본), k=8)` → 하이브리드 검색. picked 결과를 먼저 보여 주고, full 결과에는 "발췌되지 않은 부분 → ref_add로 발췌 추가"라고 표시한다.
- `ref_check(chapter_number, project_id?)` → JSON: verified / unverified / unknown(refs에 없음) / uncertain(한글 표기인데 refs와 못 이음: 인명이면 aliases 필요, 지명·사건이면 무시) 목록과 `unique_unchecked`, `needs_source`.
  - 문헌마다 `count`(출현), `cited_as`, `paragraphs`(장 본문의 문단 번호), `matched_by`(alias·음역 추정·연도 a/b 모호)를 담는다.
  - **연도 a/b가 모호하면 잇지 않는다**(사용자 결정 #31). `Keynes(1930)`·`케인스(1930)`인데 참고문헌에 1930a·1930b만 있으면, key `keynes1930a/b`·상태 unverified·`candidates`(후보 key와 제목)로 보이고 한 문헌으로 센다. 이슈의 ref_id도 비워 둔다.
  - **추정은 저장하지 않는다**(음역 추정·a/b 모호, 결정 #28·#31). 저자가 확정하면 CLI `magus alias <key> <표기>`로 aliases에 넣는다(예: `magus alias keynes1930b "케인스(1930)"` → `케인스1930`). 연도를 빼고 적으면 문헌 연도(a/b는 뗌)를 붙인다.
  - 인용 패턴: `(Daeschler, Shubin & Jenkins, 2006)`, `Clack(2012)`, `Hu et al.(2023)`, `갤러(2022)`, `(헨릭, 2016)`. 실원고에서 추가로 확인한 것은 다음과 같다.
    - 괄호 안 다중 인용, 설명 뒤 인용 `(1990년 국제달러, Maddison, 2001)`, 연도 범위 `(Toynbee, 1934–1961)`
    - 발음 부호·소문자 접두어·여러 단어 저자(Prüfer, de Vries, Ibn Khaldun), 한자 저자(田代和生)
    - 한글 공저자 `넌·첸(2011)`, 한 글자 성 `셰 등(2019)`, 띄어 쓴 일본 이름 `다시로 가즈이(1981)`
  - 해석: key → aliases → 공저자로 동명 판별 → 연도 a/b → (한글만) 같은 연도 안 음역 추정(`magus/melchior/translit.py`). 지명·사건 접미사와 일반명사는 저자로 보지 않는다.
- 책 전체 집계는 CLI `magus cite-report --project-id <id>`로 낸다(`magus/melchior/report.py`).
  - 내용: 고유 미확인 수, 많이 인용된 순위, 참고문헌에 없는 인용(+같은 저자 다른 연도 힌트), uncertain, 추정 연결, 미인용 항목.
- 저자용 보고서는 CLI `magus author-report --project-id <id> --out private/reports/<날짜>-인용-점검.md`로 만든다(`magus/melchior/author_report.py`, 같은 이름의 docx도 만든다).
  - 독자는 개발자가 아니다. key 대신 "저자(연도) 『제목』", 설명은 한두 문장, 3쪽 이내. 대상 사용자·프로젝트의 데이터만 쓴다.
  - 7개 절: 한 줄 요약 / 바로 확인할 것(연도 불일치, 참고문헌에만 있는 것) / 답해 주실 질문(음역 추정, 동명 판별) / 확인 순서 상위 20 / 사실·수치 요청(fact) / 장별 미확인 수 / 앞으로의 방식.

### 영감 — Casper (`magus/casper/`)
- `idea_add(text, kind, origin?)` → author=me로 저장한다.
- `idea_add_conversation(markdown? | path?, origin?)` → 화자 마커로 발화를 나눈다(`magus/casper/conversation.py`). 로컬 .md path도 받는다(긴 기록용).
  - 지원 마커(한 파일 안 혼용 가능): `**사용자:**`/`**Claude:**`(변형: `**사용자**:`, 나/User, ChatGPT/AI), `질문:`/`답변:`(괄호 설명 허용: `**답변(수정된 평가):**`), 제목형 `## 질문 N` / `### 답변`, `> 인용 블록` 뒤의 `**Claude 요지**`. 사용자 발화 전체가 인용 블록이면 `>`를 뗀다.
  - 사용자 발화 하나는 ideas(author=me, kind=conversation)가 되고, 바로 뒤의 AI 발화는 ideas(author=ai, parent_id=그 사용자 발화)가 된다. 대화 사이 구분 제목(`## 대화 N`, `---`)은 발화에서 떼어 낸다.
  - 리포트: me N건, ai N건, 분리 실패 구간(서문 본문, 빈 마커, 고아 AI 발화. 저장하지 않는다).
- `idea_delete(id, note)` → 생각을 휴지통으로 옮긴다(지우지 않음, #88). 그 생각에 응답한 AI 발화도 함께 옮긴다. 설명 첫 문장: 저자가 지우라고 분명히 말했을 때만, 여러 개면 목록을 보여 주고 확인받는다.
- `idea_search(query, author=me|ai|all, k=10)` → 기본값은 me다. all이면 me를 먼저 정렬한다. ai 결과에는 응답한 사용자 발화를 함께 보여 준다.

### 문체 — Balthasar (`magus/balthasar/`)
- `style_add(passage, reason, work?, tags)` → tags 스키마는 `{호흡, 시점, 열기, 장치: [], 어미, 톤}`이다. 여섯 키가 모두 필요하고(장치만 빈 목록 허용), 모르는 키는 거부한다. 태그는 호출자(Claude)가 추출해 넘기고, 서버는 검증만 한다. **임베딩 대상과 FTS 색인 대상 모두 reason + tags를 이은 문자열이지 passage가 아니다**(구절을 색인하면 문체가 아니라 주제가 검색된다. 테스트로 고정). 키워드 색인에는 work(출전)도 더한다("유홍준 그 문장", 사용자 결정 #24). 임베딩 대상에는 넣지 않는다.
  - `tags_by=ai|author`(기본 ai): 태그를 Claude가 뽑았는지 저자가 정했는지 남긴다(#89). 응답·style_search에 `(태그는 AI가 뽑음)`, 웹 `/styles`에 "AI가 뽑은 태그"로 보인다.
  - reason은 저자가 말한 이유만 쓴다. 말하지 않았으면 지어내지 않고 `(저자가 이유를 밝히지 않음)`으로 남긴다(설명에 적었다).
- `style_search(query, k=5)` → id, passage, reason, tags를 돌려준다.
- `style_delete(id, note)` → 문체를 휴지통으로 옮긴다(#88). 설명 첫 문장은 idea_delete와 같다.
- 휴지통의 생각·문체는 검색·목록·웹 화면·reindex에서 빠진다. 되살리기는 운영자 CLI `magus trash restore idea|style <id>`만 한다(생각이면 함께 옮긴 AI 발화도).

### 쓰기 도구 설명의 첫 문장(#87)

Claude는 도구를 고를 때마다 설명을 읽는다. instructions만으로는 보장되지 않아 설명 첫 문장에도 적었다.
- idea_add·style_add·ref_add: "저자가 '생각'('문체', '문헌')에 넣으라고 분명히 말했을 때만 부른다. '저장해 줘'처럼 넣을 곳이 정해지지 않았으면 부르지 말고 생각·문체·문헌 중 어디인지 먼저 묻는다."
- book_write_chapter: "저자가 'Magus 원고에 저장'하라고 분명히 말했을 때만 부른다."(규칙 4)
- idea_delete·style_delete: "저자가 그 항목을 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다."
- 도구 설명·도구 응답·instructions에는 코어 이름(Casper·Melchior·Balthasar)과 옛 이름(영감·책 지도·미해결·이슈·새 판·책장)을 쓰지 않는다. 예외는 규칙 7의 "쓰지 않는다" 문장(`instructions.AVOID`) 하나다. `tests/test_author_terms.py`가 모든 도구를 한 번씩 불러 설명·입력 스키마·응답·instructions를 검사한다.

## 서버 instructions

6절의 규칙 문장은 `src/magus/instructions.py`의 `RULES`에 **원문 그대로** 들어 있다. 사용자 승인 없이 고치지 않는다.
- 예외: **규칙 4는 사용자 결정 #74(2026-10-06)로 바꿨다.** "장 수정안은 대화에서 제안하고, 저자가 Word 원고에 반영한다. book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓰고, 그 장만 저장하며 note에 무엇을 바꿨는지 쓴다. 결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다."
- 예외: **사용자 결정 #87(2026-10-06)로 머리말에서 '책장'을 빼고("이 서버는 사용자의 생각·문헌·문체와 원고를 관리한다."), 규칙 7 끝을 "…'책 지도'·'미해결'·'이슈'·'새 판'·'영감'·'책장'·'refs' 같은 말은 쓰지 않는다. 코어 이름(Casper·Melchior·Balthasar)이나 도구 이름을 저자에게 말하지 않는다."로 바꿨다.**
- 예외: **사용자 결정 #85(2026-10-06, 용어 통일)로 머리말의 '영감'을 '생각'으로 바꾸고 규칙 7~9를 더했다.** 7 저자에게 보이는 이름(용어집), 8 저자의 말 해석("전체 보여 줘" → book_outline, "전체 읽어 줘" → 한 장씩 안내, "수정본 올렸어" → files_list의 최신 원고를 new_edition으로), 9 넣을 곳을 말하지 않은 "저장해 줘"·"기록해 줘"·"등록해 줘"·"넣어 줘"에는 쓰기 도구를 바로 부르지 않고 생각·문체·문헌 중 어디인지 먼저 묻기. 원문은 `tests/test_instructions.py`의 SPEC.
- **instructions는 등록된 도구만 언급한다.** `build_instructions(등록된 도구 이름)`은 규칙 문장에 나오는 도구(`book_|ref_|idea_|style_|files_` 이름)가 모두 등록된 규칙만 넣고, 번호는 다시 매긴다. 도구를 부르지 않는 규칙 7은 언제나 실린다. 도구가 모두 등록되면 SPEC과 똑같아진다(`tests/test_instructions.py`).
- 새 도구를 추가하면 그 도구가 필요한 규칙이 자동으로 instructions에 들어간다. 따로 손댈 것은 없다.

## 작업 순서 (단계마다 pytest 통과 + Claude Desktop 확인 방법을 보고한다)

1. 뼈대: Store 인터페이스, SQLite 스키마, 설정, stdio 서버, book_outline(가짜 데이터) → Claude Desktop 연결 확인.
2. book_import: fixtures 원고로 장 분할·코멘트·참고문헌을 임포트하고 리포트를 출력한다. 분할 결과를 사람이 보고 고칠 수 있게 ch-NN.md 파일명과 제목 매핑을 출력한다.
3. book_read/write/decide/issue/export + 버전 저장.
4. ref_*(bibliography 임포트, add, search, check) + 게이트를 write에 연결.
5. idea_*(대화 분리는 fixtures의 md 3개로 테스트).
6. style_*.
7. 하이브리드 검색 정리, instructions 적용, README.

## 완료 기준 (fixtures로 검증)

- 원고 임포트: 장 35개(±2, 분할 오차는 리포트에 남김), 부 8개, 코멘트→이슈 80개 이상, refs 200건 이상(unverified).
- book_outline 응답이 3,000 토큰 이하다.
- ref_check(1장) 결과에 daeschler2006과 clack2012가 unverified 또는 unknown으로 잡힌다.
- ref_add로 그중 하나를 verified로 만들면, ref_check를 다시 실행했을 때 verified 목록으로 옮겨 간다.
- idea_add_conversation(대화_전체_기록.md): me 96건, ai 96건이고, 모든 ai 항목에 parent_id가 있다.
- book_write_chapter 뒤 versions/에 이전본이 있고, outline의 최근 변경에 반영된다.
- EMBEDDINGS=none에서 모든 도구가 동작한다.
- 모든 쿼리가 user_id로 필터된다(다른 user_id로 호출하면 결과가 비어 있다).

## P1: 원격 MCP 서비스 (2026-10-03 킥오프)

**목표**: 사용자와 아버지가 각자의 Claude(웹·Desktop·모바일)에서 커넥터 URL 하나로 Magus를 쓴다. 설치는 없다. 데이터는 사용자별로 격리되고 매일 백업된다.

**하지 않는 것**: 자체 OAuth 서버, 결제, 다중 조직, 공개 가입(허용 목록만). stdio 모드는 없애지 않는다(로컬 개발용).

**아키텍처**
- 전송: streamable-http, **stateless + JSON 응답**(`magus/transports.py: http_app`). 엔드포인트 `/mcp`, 상태 확인 `/healthz`(인증 없음). 서버 코어(build_server)는 그대로 쓴다.
- 인증: MCP용 OAuth를 지원하는 **관리형** 인증 서비스를 쓴다. **WorkOS AuthKit**으로 정했다(`docs/decisions/auth-provider.md`, 차선 Descope). 코드는 표준(JWKS·iss·aud)만 쓴다(`magus/auth.py`).
  - Magus는 리소스 서버만 한다: Protected Resource Metadata를 내고, 액세스 토큰(JWT 서명·만료·issuer·audience)을 검증하고, `sub` → user_id를 매핑한다.
  - 허용 목록(`ALLOWED_USERS`)에 없는 sub는 거부한다. 무효 토큰은 401(+ `resource_metadata`), 유효하지만 목록 밖은 403(`ForbiddenGate`).
  - 무효 토큰의 원인(iss 불일치·aud 불일치·만료·서명·kid·형식)은 `JwtVerifier.check`가 서버 로그에 남긴다. iss·aud·kid 같은 공개 값만 쓰고 토큰 값은 남기지 않는다.
  - WorkOS는 당분간 **Staging 환경**(`dapper-palace-57-staging.authkit.app`)으로 운영한다. Production은 공개 서비스로 바꿀 때 옮긴다(결정 #49, 2026-10-05). 허용 목록 순서: 운영자 본인 `=default`(개발용 PDF 임포트본, 6단계 시험)가 먼저이고, 아버지 `=father`(docx 원본 새 임포트)는 나중이다(docs/deploy.md 2-1절, docs/onboarding-father.md).
  - **토큰 aud는 `PUBLIC_URL/mcp` 하나만 받는다**(문자열, 또는 원소 하나인 목록). 다른 값이 섞이면 401이다. `AUTH_AUDIENCE`로 넓히지 않고, 다르면 서버가 시작하지 않는다. 자매 서비스 trip_ai와 WorkOS 환경을 공유하기 때문이다(결정 #79, `docs/decisions/shared-auth-audience.md`). `ALLOWED_USERS`는 서비스별로 따로다.
  - PRM의 `resource`는 커넥터 URL(`PUBLIC_URL/mcp`)과 정확히 같아야 한다(Claude 요구). Claude 등록 방식은 CIMD("Claude의 공개 신원 사용").
- 사용자: `current_user()`가 HTTP에서는 토큰의 sub로, stdio에서는 `USER_ID`로 user_id를 정한다. 두 모드를 가르는 분기는 `current_user()` 밖으로 새지 않는다.
- 파일
  - 사용자별 받은함 `data/users/<user_id>/inbox/`. 업로드 페이지로만 들어온다.
  - 경로 인자(book_import, ref_add, idea_add_conversation)는 받은함의 파일 이름을 받는다. 새 도구 `files_list()`로 받은함을 본다.
  - book_export는 exports/에 만들고, 로그인이 필요하고 만료가 있는 다운로드 URL을 돌려준다.
- 웹(`magus/web.py`): 같은 프로세스의 Starlette 라우트로 서버에서 그린 최소 HTML이다(디자인은 P1 범위가 아니다).
  - 페이지: `/login`, `/inbox`(업로드·목록·삭제), `/book`(임포트·docx 내보내기), `/checklist`(문헌 신호등 🟢확인 🟡미확인 🔴참고문헌에 없음 ⚪미연결 + 장별), `/issues`(메뉴 "확인 요청": 목록, AI 확인 요청 🤖 표시, #71), `/download/{token}`.
  - 세 책장(읽기 전용, 넣는 것은 Claude 대화로): `/ideas`(메뉴 "생각": 날짜·내용·나/AI·출처, AI 답은 응답한 생각으로 이음), `/refs`(문헌: 신호등·서지·쓸 부분·이유·인용된 장, 인용 현황은 `/checklist`로), `/styles`(문체: 구절·출처·이유·태그, 태그로 거르기). 100개씩 쪽 나눔, 빈 책장에는 Claude에게 말할 예문 한 줄.
  - **화면 스타일**(2026-10-06): `web.py`의 `STYLE` 상수 한 곳. 토큰과 참고 문서에서 바꾼 점은 `docs/decisions/web-style.md`(참고 문서는 외부 디자인 분석 문서, `private/design/`, 리포 밖). 시스템 한글 글꼴, 본문 16px·줄간격 1.6, 굵기 400/600, 그라데이션 없음, 흰 상단 바. 화면 문구는 사용자 결정으로만 바꾼다(#85 용어집).
    - 대비 AA: ink-mute는 흰 바탕에서만, 태그 바탕은 #b9b9f9 40%, ruby는 오류 왼쪽 테두리에만(글자로는 4.29:1). 입력칸 테두리는 ink-mute(4.75:1, 사용자 결정 #86).
    - 채운 버튼은 화면마다 하나(받은함·원고의 '올리기'). 받은함은 파일을 고르면 바로 올린다(자바스크립트가 꺼지면 '올리기').
    - `/book` 원고 올리기: 책이 없으면 '새 책으로 가져오기'가 기본이고 '수정본으로 올리기'는 비활성. '바꾸기'(replace)는 접힌 영역 '드물게 쓰는 선택' 안.
    - `/book`의 장 수는 outline과 같은 표기다(`35장 + 서장·…`).
  - 로그인
    - 원격: 인증 서버에 OAuth 인가 코드 + PKCE(S256) + `resource=PUBLIC_URL/mcp`로 로그인한다. 토큰은 MCP와 같은 JwtVerifier로 검증한다.
    - 실패 화면은 둘로 나뉜다. 토큰 무효는 401("로그인 토큰을 받아들이지 못했습니다", 원인은 서버 로그)이다. 허용 목록 밖은 403("허용 목록에 없습니다")이고, **본인의 사용자 id를 화면에 보여 준다**(운영자가 목록에 넣을 값).
    - 로컬(인증 없는 HTTP, 루프백 전용): `USER_ID`로 바로 로그인한다.
  - 세션은 HMAC 서명 쿠키(HttpOnly, SameSite=Lax, https면 Secure, 12시간)다. 모든 POST는 CSRF 토큰을 확인한다(`magus/signing.py`).
  - 내려받기: book_export(원격·HTTP)는 서명·만료(24시간) 링크를 돌려준다. 링크만으로는 받을 수 없고, 같은 사용자로 로그인해 있어야 한다.
- 저장: 파일 + SQLite를 유지한다(Store 인터페이스 뒤. Postgres는 P2).
- 호스팅: **Vultr 서울 VPS($5) + Docker Compose + Caddy(자동 HTTPS)**(`docs/decisions/hosting.md`). 서버리스는 쓰지 않는다.
  - 이미지: `Dockerfile`(python:3.12-slim, uv, 비root uid 10001, /data 볼륨, healthz 헬스체크). 구성: `deploy/compose.yaml`(magus·caddy·backup·restore).
  - **서버 되돌리기 기준 커밋은 status.md에 기록된 값을 따른다**(`HEAD~1`을 쓰지 않는다). 배포할 때마다 반영 전 커밋을 status.md와 `docs/deploy.md` 반영 기록에 적는다.
- 백업: 매일 04:00 restic → Cloudflare R2(`deploy/backup.sh`). `index.sqlite`는 빼고(재생성), `forget --keep-daily 30 --keep-monthly 12 --prune`(일별 30 + 월별 12), `check --read-data-subset=1/30`. R2 버킷에 수명 주기 규칙은 걸지 않는다.
  - 복구: `docs/deploy.md` 5절. 정기 시험은 `deploy/restore-test.sh <사용자…>`(복구본 reindex 뒤 outline 비교). 로컬 훈련 결과와 기록 표도 그 문서에 있다.
- 알림: `magus/alerts.py`(텔레그램 `ALERT_TELEGRAM_*` 또는 웹훅 `ALERT_WEBHOOK_URL`). logsafe의 ERROR를 받아 백그라운드로 보낸다. 백업 누락은 healthchecks.io(`HEALTHCHECK_URL`, magus-backup)가, 서버·HTTPS 정지는 `deploy/alive.sh`(호스트 cron 5분, `HEALTHCHECK_ALIVE_URL`, magus-alive)가 알린다. 시험은 `magus alert-test`.
- **로그**: 도구 이름, user_id, 소요 시간, 결과만 남긴다(`magus/audit.py`). 본문·발췌·원고 내용은 절대 남기지 않는다.
  - SDK의 도구 실패 메시지와 예외 traceback은 `magus/logsafe.py`가 핸들러에서 거른다. 예외는 종류·위치만 남긴다.
  - ERROR는 알림 콜백으로 보낸다(10분에 한 번).
  - 테스트로 고정한다: `tests/test_http.py`, `tests/test_logsafe.py`.
- 한도: 사용자별 저장 용량, 업로드 파일 크기, 요청 크기에 상한을 둔다. 넘으면 명확한 오류를 낸다.
- 비밀: API 키·시크릿은 환경변수로만 받는다. 저장소에는 `.env.example`만 둔다.
- 안전장치: 인증이 꺼진 HTTP는 루프백(127.0.0.1)에만 열린다(`magus serve --transport http --host 0.0.0.0`은 거부).

**작업 순서**(단계마다 테스트·status.md·커밋·태그 `p1-stepN`·push)
1. HTTP 전송, 인증 없이 로컬 실행 → MCP Inspector로 도구 호출 확인.
2. 인증 서비스 연동: 토큰 검증, sub→user_id, 허용 목록. 잘못된 토큰·만료·허용 목록 밖 거부 테스트.
3. 받은함 + files_list + 경로 인자 전환. 로컬 경로를 받던 테스트를 받은함 기준으로 바꾼다.
4. 웹 페이지 4개. 업로드 → 임포트 → 체크리스트까지 브라우저로 한 바퀴 돈다.
5. 배포 + 도메인 + HTTPS + 백업 + 복구 테스트 + 알림.
6. Claude.ai 커넥터 등록 → 웹·모바일에서 book_outline, idea_add, ref_search를 실행한다. `docs/connect-claude.md`(사용자용·아버지용).
7. 아버지 온보딩 체크리스트: 커넥터 등록, docx 업로드·임포트, 첫 세션 대본(전체 → 제12장 인용 점검 → 논문 1편 등록).

**완료 기준**
- 사용자 계정으로 웹·모바일 Claude에서 모든 도구가 동작한다.
- 다른 계정의 토큰으로는 그 사용자 데이터만 보인다(격리 테스트).
- 업로드한 docx가 임포트되어 35장 + 서장·부 들어가며 2·맺음·부록 1~3, 8부, 코멘트 129(작성자 AI 129), refs 337(고유 미확인 문헌 335편)이 나온다. (#75, 2026-10-06 최신본 기준. 처음 기준 "35장·8부·코멘트 86·refs 297"은 10/02 PDF 판 수치였다)
- 백업에서 복구한 인스턴스가 같은 outline을 돌려준다.
- 로그에 원고 본문이 한 글자도 없다(테스트로 고정).
- stdio 모드 테스트가 여전히 전부 통과한다.

## 개발 명령

```
uv sync                                   # 의존성 (Desktop이 magus.exe를 실행 중이면 실패 → uv pip install)
.venv/Scripts/python -m pytest -q         # 테스트
magus serve                               # stdio 서버 (Claude Desktop이 띄움)
magus serve --transport http [--port 8000] # streamable-http(stateless) http://127.0.0.1:8000/mcp, 인증 전에는 루프백만
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http --method tools/list   # MCP Inspector(CLI)
magus import <docx|pdf> --project-id <id> [--title …] [--subtitle …] [--replace] [--synthetic]
magus import <docx|pdf> --project-id <id> --new-edition [--force]   # 같은 책의 수정본(#76)
magus conversation <md> [--origin …]      # 대화 기록 → Casper
magus synth <폴더>                        # 합성 fixture 만들기
magus seed-demo                           # 데모 프로젝트 + 책장 표본
magus reindex                             # 파일 → index.sqlite 재생성 + 파생값 재계산
magus cite-report --project-id book       # 책 전체 인용 집계(확인 순서)
magus author-report --project-id book --out private/reports/<날짜>-인용-점검.md   # 저자용 보고서(md + docx)
magus terms --project-id book [--add …] [--remove …]                         # 비인용 용어 보기·고치기
magus trash list | put idea|style <id> --note … | restore idea|style <id>   # 생각·문체 휴지통(운영자, USER_ID 사용자, #88)
magus alias <key> <표기>                                                      # 저자가 확정한 표기를 aliases에(예: keynes1930b "케인스(1930)")
magus inbox [--add 파일…] [--remove 이름…]                                    # 받은함(로컬 개발용, 원격은 웹 업로드)
magus outline [--project-id …]                                               # book_outline과 같은 출력(USER_ID). 복구 확인용
magus alert-test                                                             # 운영자 알림 채널 시험
docker compose -f deploy/compose.yaml …                                      # 운영(docs/deploy.md)
.venv/Scripts/python -m ruff check --select F,B src tests                    # 린트(pyflakes·bugbear)
```

## fixtures

`fixtures/`에는 원고 docx 1개(파일명에 "닿으려는_종")와 대화 기록 md 3개(그중 하나는 `대화_전체_기록.md`)를 둔다. 실제 원고이므로 리포에 커밋하지 않는다(.gitignore). 읽기만 한다.
- 실제 내용: 원고 `261002-닿으려는_종_전면개정_그림추가.pdf`(PDF, 297쪽, docx 없음), `대화_전체_기록.md`, `대화기록_닿으려는종.md`, `도시_유전자_민주주의_대화.md`, `사피엔스_총균쇠_대화.md`. 원본은 사용자의 Downloads에 있고, fixtures는 사본이다.
- 최신본 docx(2026-10-06 받음): `261005-인류가_선택한_진화_시대가_선택한_도시_원고.docx`. 책 제목이 바뀌었고, 코멘트 129건(작성자 모두 Claude), 표 37, 그림 10이다.
  - 로컬 `father-trial` 사용자의 `book`에 시험 임포트해 두었다(지우지 않음). 서버와 default에는 넣지 않았다.
  - 비교 결과는 `data/realdata/2026-10-06-father-trial-*.md`에 있다.
- 실데이터는 default 사용자의 `book` 프로젝트다(10/02 PDF 판). 리포트 사본은 `data/realdata/`에 있다.
- 합성 fixture는 `tests/fixtures/synthetic/`에 **커밋해 둔다**(사용자 결정 #11: 비밀이 아니고 재현성이 더 중요하다). `magus synth tests/fixtures/synthetic`로 다시 만든다(`src/magus/synthetic.py`). 실데이터(루트 `fixtures/`, gitignore)와는 계속 분리한다. 합성 PDF는 실원고 레이아웃을 흉내 낸다. 합성으로 돌린 리포트에는 "합성 fixture"라고 표시한다. 합성 데이터를 임포트할 때는 `USER_ID=synthetic`을 쓴다.

## 문서화 규약

### status.md (프로젝트 루트)

세션이 초기화돼도 이 파일 하나만 읽으면 바로 이어서 작업할 수 있어야 한다. 구성 순서는 바꾸지 않는다.

1. **지금 바로 할 일**: 다음 행동 한두 줄. 사람의 확인을 기다리는 중이면 "대기: 무엇을, 누가" 형식으로 쓴다.
2. **현재 단계**: 작업 순서(1~7단계) 중 어디인지와 상태(완료/진행/대기).
3. **단계별 체크리스트**: 1~7단계 각각 [x]/[ ], 완료일, 산출물 파일 경로.
4. **검토 대기 결정**: 사용자가 아직 확인하지 않은 것.
5. **환경 메모**: uv 경로, MCP SDK 버전, pandoc 대안, Desktop 설정 파일 경로, 실행·테스트 명령을 그대로 적는다.
6. **마지막 세션 요약**: 날짜, 한 일, 남긴 것.
7. **알려진 문제**: 미해결 버그와 우회 중인 것.

갱신 시점: 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때. 이때는 반드시 갱신한다.

### docs/ 구조

```
docs/
├── daily/YYYY-MM-DD.md      # 일지. 날짜는 로컬(KST) 기준
├── decisions/<name>.md      # 기술 결정 기록
├── troubleshooting/<name>.md# 트러블슈팅 기록
└── par-materials.md         # 이력서 소재 모음

private/reports/YYYY-MM-DD-<주제>.md # 저자에게 보내는 보고서(같은 이름의 docx 포함). 생성기로 만들고 손으로 고치지 않는다
                                    # 실원고 파생 자료라 리포에 넣지 않는다(.gitignore의 /private/, 2026-10-05 이력에서도 뺐다)
```

파일명은 kebab-case 영문으로 짓는다(예: `docs/decisions/store-interface.md`).

### 문서 형식

- **PAR**: Problem(상황·제약) / Action(선택한 것, 비교한 대안, 그렇게 고른 이유) / Result(결과, 가능하면 수치, 검증 방법).
- **일지(daily)**: 날짜 / 오늘 한 일 / 내린 결정(decisions 링크) / 막힌 것과 해결(troubleshooting 링크) / 내일 할 일 / 이력서 소재 후보.
- **기술 결정(decisions)**: PAR 구조로 쓰고, 맨 아래에 "대안을 버린 이유"를 한 줄로 적는다.
- **트러블슈팅**: 문제상황 / 시도한 것들 / 최종 해결법 / 이력서 소재 한 줄.
- **par-materials.md**: 항목마다 날짜 / P / A / R / 근거 문서 링크 / 이력서용 한 문장을 적는다. 맨 위에 "사용법" 2줄을 둔다.
- **커밋**: 컨벤셔널 커밋으로 쓰고, body 첫 줄에 "왜 이 결정을 했는지"를 한 줄로 적는다. 단계를 완료할 때마다 커밋한다.
- **브랜치·태그**
  - P0는 `master`에 바로 커밋한다. 단계를 완료하면 태그를 단다(`step1`, `step2`, …).
  - 파서 실험처럼 되돌릴 가능성이 큰 작업만 브랜치를 쓴다. 끝나면 squash merge한다.
  - **동시 세션**: 같은 리포에서 Claude Code 세션을 둘 이상 쓸 때는 각자 별도 git worktree에서 작업한다(예: `git worktree add .worktrees/<이름> <브랜치>`, `/.worktrees/`는 `.git/info/exclude`에 넣는다).
    - 메인 작업 트리에서 `git switch`·`checkout`·`reset`을 하지 않는다. 다른 세션의 작업 트리가 바뀐다(2026-10-06, 약 1분 동안 다른 세션의 트리가 바뀌었다).
    - worktree에서 테스트할 때는 메인 `.venv`의 python에 `PYTHONPATH=<worktree>/src`를 준다(편집 설치는 메인 `src`를 가리킨다).
    - master에 들일 때는 worktree에 병합 브랜치를 만들어 테스트하고, 메인 트리를 쓰는 세션에 병합을 부탁한다.
- **원격 저장소**: `origin` = https://github.com/sml122900/Magus (**Private**, 2026-10-05부터)
  - 인증은 Git Credential Manager가 한다. 토큰을 명령이나 파일에 적지 않는다.
  - **단계 태그를 찍으면 push까지 한다**: `git push origin master --tags`. 그다음 `git ls-remote --tags origin`으로 확인한다.
  - force push는 하지 않는다. 2026-10-05에 filter-repo로 이력을 정리한 뒤 처음 올린 것이 기준이다.
  - 실원고와 그 파생 자료(`data/`, `/fixtures/`, `/private/`)는 올리지 않는다. 처음 올리기 전에 확인한 방법: 이력 경로 검사(`git -c core.quotepath=false`), 실제 파일 해시 대조, 비밀 패턴·실제 비밀값 검색.

### 작업 명령어

사용자가 아래 문장을 그대로 입력하면, 위의 문서 형식에 맞춰 작성한다.

#### 일지 생성
"오늘 작업 내용으로 docs/daily/[날짜].md 만들어줘"

#### 기술 결정 문서
"[기술명] 선택 이유를 docs/decisions/[기술명].md로 PAR 구조로 만들어줘"

#### 트러블슈팅 문서
"방금 해결한 [문제]를 docs/troubleshooting/[문제명].md로 저장해줘.
문제상황 / 시도한 것들 / 최종 해결법 / 이력서 소재 한 줄 포함해서"

#### PAR 소재 추출
"오늘 작업에서 이력서에 쓸 수 있는 PAR 소재 뽑아서 par-materials.md에 기록해줘"

#### 커밋 메시지
"이 변경사항으로 컨벤셔널 커밋 메시지 써줘. 왜 이 결정을 했는지 body에 한 줄 추가해줘"

#### 세션 마무리
"오늘 작업 요약하고 CLAUDE.md 진행상황 섹션 업데이트할 내용 알려줘"

세션 마무리 명령을 받으면 요약과 CLAUDE.md 진행상황 갱신안을 보여 주고, status.md는 그 자리에서 바로 갱신한다.
