# Magus — 집필 RAG MCP 서버

- **세션을 새로 시작하면 가장 먼저 status.md를 읽는다. 그다음 이 파일의 진행상황 섹션을 본다. 작업은 status.md의 '지금 바로 할 일'부터 재개한다.**

## 진행상황

- 현재 단계: 1단계(뼈대) 완료. 2단계(book_import)는 아직 시작하지 않았다.
- 다음 할 일: fixtures가 들어오면 docx 구조를 조사한 뒤 book_import를 구현한다.
- 대기 사항: fixtures 투입과 Claude Desktop 연결 확인(사용자). 상세는 status.md에만 적는다.

## 개요

책을 쓰는 사람이 머릿속 재료를 세 책장(코어)에 넣어 두고, Claude가 MCP로 꺼내 쓰게 하는 서버.
책장은 **사람 소유**(여러 책에 재사용), 원고는 **책(프로젝트) 소유**.

## 왜 만드나 (막아야 할 다섯 가지)

실제 사례: 한 교수가 Claude로 297쪽(35장 8부, 약 34만 자) 책을 썼다.

1. 한 대화에서 책 전체를 10번 재생성했다. 장 하나 추가할 때마다 전체를 다시 썼다. → **장 단위 저장, 책 전체를 반환하는 도구 없음**
2. 대화가 바뀌면 생각이 사라졌다(md 수동 첨부 8번, ChatGPT 답변 복붙). → **Casper(영감) 책장**
3. 인용 약 270개, 참고문헌 약 250편이 LLM 기억에서 생성됐다. Word 코멘트 86개 중 82개가 "확인 필요". → **Melchior(문헌) + 인용 게이트**
4. 문체가 저자의 목소리가 아니라 LLM 기본 문체였다. → **Balthasar(문체) 책장**
5. 원고가 두 파일로 갈라졌다. → **단일 진실 원천(디스크의 ch-NN.md)**

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

## 절대 원칙

- **에이전트는 책 전체를 들고 있지 않는다.** 한 작업의 컨텍스트는 목차·결정·미해결(book_outline) + 장 1개 + 검색 top-k로 이루어진다. 책 전체를 반환하는 도구는 만들지 않는다.
- **인용 게이트**: refs에 `status=verified`로 있는 출처만 인용할 수 있다. 없는 출처는 본문에 `[출처 필요: 주장 요약]`으로 남긴다. 쓰기를 막지는 않는다. 표시하고 집계만 하며, 판단은 사용자가 한다.
- **누가 말했는지 보존한다.** Casper는 사용자 발화(`author=me`)와 AI 발화(`author=ai`)를 구분해 저장하고, 검색에서는 me를 먼저 보여 준다.
- **원본은 사람이 읽을 수 있는 파일(markdown/json)이다. SQLite는 인덱스일 뿐이다.** 인덱스는 언제든 파일에서 다시 만들 수 있어야 한다(`magus reindex`). 파일에 없는 정보를 SQLite에만 두지 않는다. 예외는 계산으로 얻는 값(char_count, unverified_cite_count, chunks)이다.
- **SaaS 준비**
  - 모든 레코드(모든 테이블의 모든 행)에 `user_id`가 있고, 모든 쿼리는 `user_id`로 필터한다.
  - P0는 단일 사용자(환경변수 `USER_ID`)다. 그래도 코드 어디에서도 단일 사용자를 가정하지 않는다. Store 메서드는 항상 `user_id`를 인자로 받는다. 서버 코어에서 user_id를 정하는 곳은 `current_user()` 한 군데뿐이다(P1에서는 인증 컨텍스트로 바꾼다).
  - 저장소는 `Store` 인터페이스(`magus/store/base.py`) 뒤에 둔다. P0 구현은 `LocalStore`(파일 + SQLite), P1 구현은 Postgres + 객체 스토리지다.
  - 전송(stdio / streamable-http)은 서버 코어(`magus/server.py: build_server`)와 분리한다(`magus/transports.py`). P0는 stdio만 구현하고 HTTP 진입점은 자리만 둔다.
- **서버는 P0에서 LLM API 키가 필요 없다.** 문체 태그 추출·요약 같은 일은 호출하는 Claude가 하고 결과를 도구 인자로 넘긴다. 외부 API는 임베딩뿐이다. `EMBEDDINGS=none`이어도 모든 도구가 FTS만으로 동작해야 한다.
- **도구 응답은 짧게.** 목록에는 상한을 두고, 긴 본문은 요청한 것만 돌려준다. book_outline은 3,000 토큰 이하다.

## 스택

- Python 3.12, uv, pytest. (uv 위치: `%APPDATA%\Python\Python313\Scripts\uv.exe`, PATH에 없음)
- MCP 공식 Python SDK **2.x** (`mcp>=2.2`). 1.x와 API가 다르다.
  - `from mcp.server.mcpserver import MCPServer` (`FastMCP`는 없어졌다). `MCPServer(name=, instructions=)`, `@server.tool(name=, description=)`.
  - `server.run("stdio")` / `server.run("streamable-http", host=, port=)`.
  - 동기 도구 함수는 워커 스레드에서 실행된다 → `LocalStore`는 `check_same_thread=False` + RLock을 쓴다.
  - 테스트: `async with mcp.Client(server) as c: await c.call_tool(...)`로 in-process 연결. `c.instructions`로 instructions를 확인한다.
- SQLite + FTS5(키워드 검색). 벡터는 BLOB으로 저장하고 브루트포스 코사인으로 계산한다(P0 규모인 수만 청크까지 충분하다). 키워드와 벡터 결과는 RRF로 합친다. 한국어 고유명사와 학자 이름 때문에 키워드 검색은 뺄 수 없다.
  - 한국어 토큰화(2글자 이름 "갤러", "헨릭"): trigram은 3글자 미만을 못 찾는다. 4단계에서 결정한다(후보: 한글 어절은 문자 bigram, 나머지는 단어 단위로 사전 토큰화한 뒤 FTS5 unicode61에 넣기).
- docx 읽기: python-docx + `word/comments.xml` 직접 파싱(코멘트와 앵커 위치). 대안은 mammoth. docx 쓰기: pandoc(md→docx), 시스템에 pandoc이 없으면 `pypandoc_binary`를 쓴다.
- PDF 텍스트: pymupdf. docx가 없을 때 폴백으로 원고 PDF도 받는다. 이때 코멘트는 `메모 포함[C` 패턴으로 추출한다.
- 임베딩: 다국어 모델(Voyage 또는 OpenAI 계열). 제공자는 환경변수로 바꾼다.

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `USER_ID` | `default` | P0 단일 사용자 id(영문·숫자·`_`·`-`, 64자 이하) |
| `DATA_DIR` | `./data` | 원본 파일과 index.sqlite의 루트 |
| `EMBEDDINGS` | `none` | `none` \| `voyage` \| `openai` |
| `VOYAGE_API_KEY` / `OPENAI_API_KEY` | — | 해당 제공자를 쓸 때만 |

## 데이터 모델 (모든 테이블에 user_id가 있다)

- users(id), projects(id, user_id, title)
- parts(user_id, project_id, number, title) — *추가*: 완료 기준의 "부 8개"를 위해 둔다.
- chapters(id, user_id, project_id, number, title, status, part, path, char_count, unverified_cite_count, version, note, updated_at)
- chapter_versions(id, user_id, chapter_id, version, path, note, created_at) — 보관된 **이전** 본문들
- decisions(user_id, project_id, id, text, created_at) — id는 프로젝트별 일련번호 `D{n}`
- issues(user_id, project_id, id, text, status: open|closed, origin: import_comment|user|agent, chapter_number?, created_at, closed_note?) — id는 프로젝트별 일련번호 `I{n}`
- refs(id, user_id, key, aliases json, bib json, status: unverified|verified, has_fulltext, file_path?, created_at)
  - key는 첫 저자 성(소문자 영문) + 연도다. 예: `daeschler2006`, `galor2022`. 한글 표기(갤러, 다이아몬드 등)는 aliases에 넣는다.
- ref_passages(id, user_id, ref_id, text, reason, locator?)
- ideas(id, user_id, text, kind: thought|ai|article|conversation|tv|other, origin?, author: me|ai, parent_id?, created_at)
- style_entries(id, user_id, passage, reason, work?, tags json, created_at)
- chunks(id, user_id, owner_type, owner_id, lane: ref_picked|ref_full|idea_me|idea_ai|style, text, embedding blob?) + chunks_fts

### 디스크 구조 (원본)

```
data/users/<user_id>/shelf/casper/<id>.json                       # ideas
data/users/<user_id>/shelf/melchior/<key>/{bib.json, passages.json, full.txt}
data/users/<user_id>/shelf/balthasar/<id>.json                    # style
data/users/<user_id>/projects/<project_id>/project.json           # title, created_at, parts
data/users/<user_id>/projects/<project_id>/book/ch-01.md … ch-35.md
data/users/<user_id>/projects/<project_id>/{decisions.md, issues.md, versions/, original/}
data/index.sqlite
```

### 파일 형식

- `ch-NN.md`: 앞머리(front matter) 다음에 본문이 온다. 장 제목은 앞머리에만 두고 본문에는 넣지 않는다(export할 때 `# 제N장 제목`을 붙인다).
  - **메타는 서버가 관리하고, 도구는 본문만 주고받는다.** 호출자가 앞머리를 붙여 보내도 서버가 버린다(`docs/decisions/front-matter-boundary.md`).
  ```
  ---
  title: 물고기의 결심
  status: draft
  part: 1
  version: 3
  updated_at: 2026-10-03T02:40:00.123Z
  note: 2절 도입부 재작성
  ---

  본문…
  ```
- `versions/ch-NN.vK.md`: 덮어쓰기 직전의 파일을 앞머리째로 복사해 둔다. chapter_versions는 이 파일들에서 다시 만든다.
- `decisions.md` / `issues.md`: 항목마다 `## D3 · <시각>` 또는 `## I3 · open` 제목을 달고, 그 아래 `- key: value` 메타 줄과 빈 줄, 본문(여러 줄 가능)을 둔다.
- 시각은 모두 UTC ISO 8601, 밀리초 단위다(`2026-10-03T02:40:00.123Z`). 프로세스 안에서는 항상 증가하므로 문자열 정렬이 곧 시간 순서다.

### 규칙

- **현재 프로젝트**: 도구에 project_id가 없으면 그 사용자의 가장 최근에 갱신된 프로젝트를 쓴다.
- **최근 변경**은 현재 장 머리(version·note)와 chapter_versions를 합쳐 시각 내림차순으로 정렬한 것이다.
- 장 파일을 사람이 직접 고쳤다면 `magus reindex`로 인덱스를 갱신한다.

## MCP 도구 (이름 고정)

### 책 (`magus/book/`)
- `book_outline(project_id?)` → 제목, 장 목록(번호·제목·상태·글자수·미확인 인용 수), 최근 결정 10개, 열린 미해결, 최근 변경 5개를 돌려준다. **3,000 토큰 이하**로 자른다. 미해결은 예산 안에서 최대한 싣고, 넘치는 건수는 "외 N건"으로 표시한다(장별 미해결은 book_read_chapter 메타에서 볼 수 있다). 모든 원고 작업은 이 도구로 시작한다.
- `book_read_chapter(number)` → markdown 본문과 메타(버전, 미확인 인용 목록, 그 장의 열린 미해결).
- `book_write_chapter(number, content, note)` → 이전 본문을 versions/에 저장하고 새 본문을 기록한 뒤 ref_check를 자동 실행한다. 응답에 미확인 인용 목록을 담는다. 없는 번호면 새 장을 만든다.
- `book_decide(text)` / `book_issue_add(text, chapter_number?)` / `book_issue_close(id, note?)`
- `book_import(path)` → "제N장"(공백 변형 허용)과 "제N부" 제목으로 원고를 나눈다.
  - 코멘트는 issues(origin=import_comment)로 넣고, 앵커가 속한 장 번호를 기록한다.
  - 참고문헌 섹션은 ref_import_bibliography로 넘긴다.
  - 그림·표·수식은 자리표시자(`[그림 N]`, `[표 N]`, `[수식]`)로 남기고, 원본 docx는 original/에 복사한다.
  - 리포트: 장 수, 분할 못 한 구간, 코멘트→이슈 수, 참고문헌→refs 수, 파싱 실패 줄, `ch-NN.md ↔ 제목` 매핑.
- `book_export(path?)` → md를 합쳐 docx를 만들고 경로를 돌려준다. P0에서는 코멘트와 그림을 복원하지 않는다.

### 문헌 — Melchior (`magus/melchior/`)
- `ref_import_bibliography(text)` → 줄 단위로 저자·연도·제목을 파싱하고 key를 만든다. status는 unverified다. 파싱하지 못한 줄은 bib.raw로 보관하고 리포트에 남긴다.
- `ref_add(bib, passages: [{text, reason, locator?}], file_path? | full_text?)` → status=verified로 넣는다. 발췌는 ref_picked 레인, 전문은 ref_full 레인으로 청킹한다. 같은 key가 unverified로 있으면 그 항목을 verified로 올린다.
- `ref_search(query, scope=picked|full|both, k=8)` → picked 결과를 먼저 보여 준다. full 결과에는 "발췌되지 않은 부분"이라고 표시한다(발췌 추가 제안용).
- `ref_check(chapter_number)` → 본문에서 인용 패턴을 뽑아 key로 정규화한다(영문 성, 한글 표기는 aliases로). 결과는 verified / unverified / unknown(refs에 아예 없음) 세 목록이다. 인용 패턴 예: `(Daeschler, Shubin & Jenkins, 2006)`, `Clack(2012)`, `Hu et al.(2023)`, `갤러(2022)`, `(헨릭, 2016)`.

### 영감 — Casper (`magus/casper/`)
- `idea_add(text, kind, origin?)` → author=me로 저장한다.
- `idea_add_conversation(markdown)` → 화자 마커로 발화를 나눈다.
  - 지원 마커: `**사용자:**`/`**Claude:**`, `질문:`/`답변:`, `> 인용 블록` 뒤의 `**Claude 요지**`.
  - 사용자 발화 하나는 ideas(author=me, kind=conversation)가 되고, 바로 뒤의 AI 발화는 ideas(author=ai, parent_id=그 사용자 발화)가 된다.
  - 리포트: me N건, ai N건, 분리 실패 구간.
- `idea_search(query, author=me|ai|all, k=10)` → 기본값은 me다. all이면 me를 먼저 정렬한다.

### 문체 — Balthasar (`magus/balthasar/`)
- `style_add(passage, reason, work?, tags)` → tags 스키마는 `{호흡, 시점, 열기, 장치: [], 어미, 톤}`이다. 태그는 호출자(Claude)가 추출해 넘기고, 서버는 검증만 한다. **임베딩 대상은 reason + tags를 이은 문자열이지 passage가 아니다**(구절을 임베딩하면 문체가 아니라 주제가 검색된다).
- `style_search(query, k=5)` → passage, reason, tags를 돌려준다.

## 서버 instructions

6절 문구는 `src/magus/instructions.py`에 **그대로** 들어 있다. 고치지 않는다.

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

## 개발 명령

```
uv sync                      # 의존성
uv run pytest                # 테스트
uv run magus serve           # stdio 서버 (Claude Desktop이 띄움)
uv run magus seed-demo       # 가짜 데모 프로젝트 생성
uv run magus reindex         # 파일 → index.sqlite 재생성
```

## fixtures

`fixtures/`에는 원고 docx 1개(파일명에 "닿으려는_종")와 대화 기록 md 3개(그중 하나는 `대화_전체_기록.md`)가 있다. 실제 원고이므로 리포에 커밋하지 않는다(.gitignore).

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
```

파일명은 kebab-case 영문으로 짓는다(예: `docs/decisions/store-interface.md`).

### 문서 형식

- **PAR**: Problem(상황·제약) / Action(선택한 것, 비교한 대안, 그렇게 고른 이유) / Result(결과, 가능하면 수치, 검증 방법).
- **일지(daily)**: 날짜 / 오늘 한 일 / 내린 결정(decisions 링크) / 막힌 것과 해결(troubleshooting 링크) / 내일 할 일 / 이력서 소재 후보.
- **기술 결정(decisions)**: PAR 구조로 쓰고, 맨 아래에 "대안을 버린 이유"를 한 줄로 적는다.
- **트러블슈팅**: 문제상황 / 시도한 것들 / 최종 해결법 / 이력서 소재 한 줄.
- **par-materials.md**: 항목마다 날짜 / P / A / R / 근거 문서 링크 / 이력서용 한 문장을 적는다. 맨 위에 "사용법" 2줄을 둔다.
- **커밋**: 컨벤셔널 커밋으로 쓰고, body 첫 줄에 "왜 이 결정을 했는지"를 한 줄로 적는다. 단계를 완료할 때마다 커밋한다.

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
