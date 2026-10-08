# Magus

책을 쓰는 사람의 세 책장과 원고를 Claude에게 MCP로 열어 주는 서버입니다.

| 책장 | 표시명 | 하는 일 |
|---|---|---|
| 생각 | **Casper · 몰약** | 생각과 대화를 보존합니다. 내가 한 말(me)과 AI가 한 말(ai)을 구분합니다. |
| 문헌 | **Melchior · 황금** | 실제로 읽고 발췌한(verified) 문헌만 인용할 수 있게 합니다. 나머지는 표시하고 집계합니다. |
| 문체 | **Balthasar · 유향** | 내가 좋아하는 문장을 이유·태그와 함께 기록하고, 문체로 찾습니다. |
| 원고 | book | 장 단위로 저장하고 버전을 남깁니다. 결정과 확인 요청도 기록합니다. |

저자에게 보이는 이름(사용자 결정 #85)은 **전체**(책 전체 현황, `book_outline`) · **확인 요청**(issues) · **생각** · **문체** · **문헌** · **결정** · **수정본**(Word에서 고쳐 다시 올린 원고, 번호 E2·E3…)입니다. 웹 화면, 도구 응답, Claude의 답이 이 이름을 씁니다. 도구 이름(`book_*`·`idea_*` 등)과 코드 모듈 이름은 그대로입니다.

세 현자는 토론하지 않습니다. 선물을 바칠 뿐이고, 받고 결정하는 것은 저자입니다.

이 서버가 막으려는 것은 다음과 같습니다.

- 장 하나를 고칠 때마다 책 전체를 다시 생성하는 것
- 대화가 바뀌면 생각이 사라지는 것
- 읽지 않은 문헌을 인용하는 것
- LLM 기본 문체
- 원고가 여러 파일로 갈라지는 것

## 설치

```
uv sync
.venv/Scripts/python -m pytest -q        # macOS/Linux는 .venv/bin/python
```

### uv가 PATH에 없을 때

`pip install --user uv`로 설치하면 uv.exe가 PATH에 없는 user Scripts 폴더에 놓입니다. 이때는 전체 경로로 실행하세요.

```powershell
# PowerShell
& "$env:APPDATA\Python\Python313\Scripts\uv.exe" sync
```

```bash
# Git Bash
~/AppData/Roaming/Python/Python313/Scripts/uv.exe sync
```

uv는 설치에만 씁니다. 서버는 `.venv\Scripts\magus.exe`를 직접 실행하므로, Claude Desktop 설정에는 uv가 필요 없습니다.

## Claude Desktop 연결

Claude Desktop에서 **설정 → 개발자 → 구성 편집**을 누르면 `claude_desktop_config.json`이 열립니다.
Microsoft Store판은 `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Claude\` 아래에 있습니다.
`mcpServers`에 다음을 추가하세요.

```json
{
  "mcpServers": {
    "magus": {
      "command": "C:\\project_2026\\Magus\\.venv\\Scripts\\magus.exe",
      "args": ["serve"],
      "env": {
        "USER_ID": "default",
        "DATA_DIR": "C:\\project_2026\\Magus\\data",
        "EMBEDDINGS": "none"
      }
    }
  }
}
```

저장한 뒤 Claude Desktop을 **완전히 종료**하고(트레이 아이콘 → 종료) 다시 실행하세요.
서버 로그는 `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`에 남습니다.
새 대화에서 "Magus의 book_outline을 호출해 줘"라고 해 보세요.

## 첫 실행 확인

### 1. Desktop 다시 시작

1. Claude Desktop을 **완전히 종료**합니다. 창을 닫는 것으로는 부족합니다(트레이의 Claude 아이콘 → 종료).
   작업 관리자에 `magus.exe`가 남아 있으면 서버가 옛 코드로 계속 돕니다.
2. Claude Desktop을 다시 실행하고 **새 대화**를 엽니다.
3. 입력창의 도구 메뉴에서 magus가 켜져 있는지 봅니다(도구 18개).
4. 로그는 `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`에 있습니다.
   Microsoft Store판은 `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Claude\logs\`에 있습니다.
   서버가 시작될 때 다음 줄이 찍힙니다.
   ```
   magus INFO user_id=default data_dir=C:\project_2026\Magus\data files_root=C:\project_2026\Magus embeddings=none
   ```

### 2. 시험 문장 네 개

넷 다 읽기만 하고 원고는 바꾸지 않습니다. 기대 결과는 2026-10-03 실원고 임포트 기준입니다.

| 말하기 | 불리는 도구 | 기대 결과 |
|---|---|---|
| "Magus의 book_outline을 호출해 줘" | `book_outline` | 첫 줄 `프로젝트: 닿으려는 종 (book)`<br>둘째 줄 `35장 + 서장·맺음·부록 1~3 · 8부 · 249,065자 · 미확인 문헌 297편 · 미연결 0 · 열린 확인 요청 86`<br>확인 요청 절 `코멘트 유래 확인 요청 86건(citation 44 · fact 40 · general 2)` |
| "제12장 인용 중 확인 안 된 것 알려줘" | `ref_check(12)` 한 번 | `unverified` 28편, `unique_unchecked: 28`, `verified: []`<br>문헌마다 문단 번호가 붙는다. 예: marchetti1994 `paragraphs: [16, 41]`, pachecocobos2019 `[28, 29]` |
| "제31장 읽고 세 문장으로 요약해 줘" | `book_read_chapter(31)` 한 번 | 제목 `대치동은 왜 아이를 줄이나`, 3,386자, 미확인 문헌 8편, 열린 확인 요청 1건(I78)<br>책 전체나 다른 장을 요구하지 않아야 한다. 본문에 "제13장에서 보았듯"이 있어도 13장을 읽지 않는다<br>규칙 1에 따라 `book_outline`을 먼저 부르는 것은 괜찮다 |
| "사실·수치 확인 요청만 보여 줘" | `book_issues(kind="fact")` | `확인 요청 40건 (status=open, kind=fact)`<br>첫 항목 `I3 · open · 1장 · import_comment · fact · 확인 필요: 폐가 부레보다…` |

"미확인 문헌 297편"은 책 전체에서 한 번씩 센 고유 문헌 수입니다. 저자 보고서 1절의 "문헌 297편"과 같은 숫자입니다.
장마다 센 수는 목차의 각 장 줄(`미확인인용 n`)에만 있습니다.
"미연결"은 한글 표기인데 참고문헌과 잇지 못한 것입니다. 미확인 수에는 넣지 않지만 숨기지 않습니다(`ref_check`의 `uncertain` 목록).
35장의 `케인스(1930)`처럼 연도 a/b가 모호한 인용은 어느 쪽에도 잇지 않고 후보 둘을 함께 보입니다(`candidates`).
확정하면 `magus alias keynes1930b "케인스(1930)"`로 넣습니다.

도구가 불리지 않거나 오류가 나면 로그 끝부분을 보세요.

### 3. 문헌 등록 시연 (`category_put`, 원문 확인 글)

**논문 PDF는 `C:\project_2026\Magus\fixtures\papers\`에 둡니다.** 이 폴더는 git에 올라가지 않습니다(`fixtures/`는 .gitignore).

1. 논문 PDF를 `fixtures\papers\`에 둡니다. 예: `kremer1993.pdf`.
2. Desktop 새 대화에서 이 문장을 그대로 씁니다(`<파일명>`, `「…」`, `…`만 바꿉니다).
   > fixtures/papers/<파일명>.pdf를 「참고문헌」 책에 원문 확인으로 넣어 줘. 쓸 부분은 「…」, 이유는 …

   기대 결과: 해당 key가 verified로 바뀌고, 그 문헌이 나오는 장 목록이 나옵니다(아래 4번).
3. Claude가 다음과 같이 `category_put`을 부릅니다(#96: 문헌 글 = 서지가 있는 글, 원문 확인 = checked).
   ```
   category_put(book="참고문헌", author="me", source={}, checked=true, parts=[{text: "쓸 부분", reason: "이유"}], file="fixtures/papers/kremer1993.pdf")
   ```
   - **경로**: 상대 경로는 Desktop이 서버를 띄운 작업 폴더가 아니라 **프로젝트 폴더** 기준으로 풉니다.
     프로젝트 폴더는 `DATA_DIR`의 부모이고, `FILES_DIR`로 바꿀 수 있습니다. 절대 경로도 됩니다.
     `book_import`와 `idea_add_conversation(path)`도 같은 규칙을 씁니다.
   - **서지**: 저자·연도를 말하지 않아도 됩니다. PDF 첫머리(5,000자)에 참고문헌의 제목이 그대로 있으면 그 문헌을 찾습니다.
     찾지 못하면 "저자와 연도가 필요하다"는 오류가 납니다. 그때 저자와 연도를 말해 주면 됩니다.
4. 기대 결과:
   ```
   kremer1993: unverified → verified · 발췌 1건 추가(총 1건) · 전문 있음 · aliases 없음
   citation 이슈 연결 변경 0건 · 이 문헌을 인용하는 장: book: 30장, 32장, 35장
   ```
   "35장의 인용을 점검해 줘"를 다시 하면 kremer1993(본문 표기 `크레머(1993)`)이 `verified`로 옮겨 가 있습니다.
   이 출력은 실데이터 사본에 제목만 적힌 PDF로 미리 돌려 본 결과입니다(사본은 지웠습니다).
5. 파일이 없으면 다음 오류가 납니다.
   ```
   파일이 없다: C:\project_2026\Magus\fixtures\papers\… (상대 경로는 C:\project_2026\Magus 기준으로 푼다)
   ```

쓸 부분은 논문의 문장을 그대로 붙이는 것이 좋습니다. `category_search`가 이 쓸 부분을 먼저 돌려주고, 글에는 이것만 인용됩니다.
PDF를 대화창에 첨부하지 말고 경로로 말하세요. 그래야 서버가 파일을 직접 읽어 전문을 저장합니다.

서버 쪽 흐름은 `tests/test_stdio.py::test_relative_file_path_from_other_cwd`가 확인합니다.
이 테스트는 다른 작업 폴더에서 서버를 하위 프로세스로 띄우고, 상대 경로로 PDF를 등록합니다.

## 처음 쓰는 순서

1. **원고 가져오기**: "`C:\…\원고.docx`를 book_import로 가져와 줘"
   - 리포트로 장 매핑과 코멘트 분류를 확인합니다.
2. **대화 기록 넣기**: "`C:\…\대화_전체_기록.md`를 「생각」 책에 넣어 줘"(idea_add_conversation(book, path))
3. **작업 시작**: 매번 `book_outline`으로 시작하고, 필요한 장만 `book_read_chapter`로 읽습니다.
4. **문헌 검증**: 읽은 문헌은 `category_put(source, checked=true, parts)`로 쓸 부분과 함께 넣습니다(원문 확인 글). 그러면 그 문헌을 인용한 곳이 verified가 됩니다.
   - 장을 고치면 `book_write_chapter`가 미확인 인용을 알려 줍니다.
   - 원고 본문의 원본은 저자의 Word 파일입니다(결정 #68, `docs/decisions/author-file-is-source.md`). 수정안은 대화에서 받아 Word에 반영하고, `book_write_chapter`는 Magus 안에 저장하라고 할 때만 씁니다.
   - 원고가 바뀌면 수정본으로 올립니다(`book_import new_edition=true`, 웹 "수정본으로 올리기", `docs/decisions/reupload-design.md`). `replace`는 결정과 확인 요청까지 휴지통으로 보내니 수정본에 쓰지 않습니다.
5. **책과 컨텍스트**(#96): 좋아하는 문장·생각·메모는 모두 책의 글이고(`category_put`·`category_search`), AI가 그 책을 읽는 법은 저자가 붙인 컨텍스트(예: 「문체」)가 정합니다.

같은 일을 명령줄로도 할 수 있습니다(아래 "명령").

## 도구 (23개, #96)

| 도구 | 하는 일 |
|---|---|
| `book_outline(project_id?)` | 책 전체 현황(저자에게는 "전체"). 3,000토큰 이하이고 본문은 없습니다. 장별 상태·글자수·확인 요청·미확인 인용 집계, 지도 두 줄, 직접 남긴 확인 요청, 최근 결정과 변경을 줍니다. |
| `book_read_chapter(number)` | 장 하나. 본문(content)과 메타, 그 원고의 컨텍스트를 별도 필드로 줍니다. 미확인 인용과 그 장의 확인 요청도 함께 줍니다. |
| `book_write_chapter(number, content, note, title?, status?)` | 장 하나를 저장합니다(저자가 Magus 원고에 저장하라고 했을 때만). 이전본은 versions/에 남고, 쓴 뒤 인용 게이트 결과를 돌려줍니다. |
| `book_issues(…)` · `book_decide(text)` · `book_issue_add(…)` · `book_issue_close(id, note?)` | 확인 요청 목록(조회 전용)과 결정·열린 문제 기록. 번호는 다시 쓰지 않습니다. |
| `book_questions(…)` · `book_answer(question_id, choice, note?)` | 저자만 답할 수 있는 인용 질문과 그 답(#84). |
| `files_list()` | 올린 파일 목록과 사용량. 파일 인자에는 여기 나온 이름만 줍니다. |
| `book_import(path, project_id?, title?, subtitle?, replace?, new_edition?, force?)` | 올린 docx(또는 pdf) 원고를 장 단위로 나눕니다. 코멘트는 확인 요청, 참고문헌은 문헌 글(원문 확인 전)이 됩니다. 같은 책은 `new_edition=true`로 수정본. |
| `book_export(path?)` · `book_document(…)` | 장을 합친 docx, 원고에서 만든 문서(출처 확인 문서, 내용은 서버가). |
| `ref_import_bibliography(text, project?, book?)` · `ref_check(chapter_number)` | 참고문헌 목록을 문헌 글로 넣기, 장의 인용을 verified / unverified / unknown으로 나누기. |
| `idea_add_conversation(book, markdown? / path?)` | 대화 기록을 me·ai 발화로 나눠 그 책의 글로 넣습니다. |
| `category_list()` | 프로젝트마다 지도·노드·책(글 수·컨텍스트 이름), 자주 쓰는 컨텍스트, 제목 기본값. |
| `category_create(name, template, color?, project?, node?, context?)` · `category_edit(book?/node?, …, context?)` | 책·노드 만들기와 이름·색·컨텍스트·위치·선 바꾸기. |
| `category_put(book, author, content?, title?, …, reason?, where?, parts?, source?, checked?, file?)` | 글 넣기(고치기). 서지(source)가 있으면 문헌 글, checked면 원문 확인. |
| `category_search(query, book?, project?, author?, full?)` · `category_trash(note, book?, item_id?, node?)` · `category_title_default(mode)` | 글 찾기(책마다 컨텍스트), 휴지통(지우지 않음), 제목 기본값. |

서버 instructions(Claude에게 주는 규칙)는 등록된 도구에 맞춰 자동으로 조립됩니다.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `USER_ID` | `default` | 사용자 id |
| `DATA_DIR` | `./data` | 원본 파일과 인덱스(index.sqlite)를 두는 위치 |
| `FILES_DIR` | `DATA_DIR`의 부모 | 도구에 준 상대 경로(`fixtures/papers/논문.pdf`)를 푸는 기준 |
| `EMBEDDINGS` | `none` | `none` \| `voyage` \| `openai` |
| `VOYAGE_API_KEY` / `OPENAI_API_KEY` | — | 임베딩 제공자를 쓸 때만 필요합니다 |
| `EMBEDDINGS_MODEL` | voyage-3.5 / text-embedding-3-small | 임베딩 모델 |
| `PUBLIC_URL` | — | 원격 모드: 바깥에서 보이는 주소. 커넥터 URL과 PRM의 resource = `PUBLIC_URL/mcp` |
| `AUTH_ISSUER` | — | 원격 모드: 인증 서버 issuer(WorkOS AuthKit). 있으면 HTTP에서 토큰 검증을 켠다 |
| `AUTH_JWKS_URL` | issuer 메타데이터의 jwks_uri | 서명 키 주소 |
| `AUTH_AUDIENCE` | `PUBLIC_URL/mcp` | 받아들일 토큰 aud(쉼표로 여럿) |
| `ALLOWED_USERS` | — | `sub=user_id` 쉼표 목록. 여기 없는 sub는 403. 공개 가입은 없다 |
| `PORT` | 8000 | `magus serve --transport http`의 기본 포트 |
| `MAX_UPLOAD_MB` | 50 | 받은함 업로드 한 개 한도 |
| `MAX_USER_MB` | 1000 | 사용자별 저장 용량(사용자 폴더 전체) |
| `MAX_REQUEST_MB` | 2 | MCP 요청 본문 한도(넘으면 413) |
| `SESSION_SECRET` | (로컬: 실행마다 무작위) | 웹 세션·내려받기 링크 서명 비밀. **원격 모드에서는 필수**(32자 이상) |
| `WEB_CLIENT_ID` / `WEB_CLIENT_SECRET` | — | 웹 로그인용 OAuth 클라이언트(인증 서버에 등록, 콜백 `PUBLIC_URL/auth/callback`). 없으면 웹 로그인이 꺼진다 |

원격 모드 변수의 예시는 `.env.example`에 있습니다. 비밀은 환경변수로만 넣고 `.env`는 커밋하지 않습니다.

임베딩을 켜면 검색이 키워드(FTS)와 뜻(벡터)을 함께 씁니다.
꺼져 있거나 키가 없거나 API 호출이 실패하면 키워드 검색만으로 동작합니다.
한국어는 2글자씩 겹쳐 색인하므로 "갤러" 같은 짧은 이름도 찾습니다.

## 명령

```
magus serve                                     # MCP 서버(stdio). Claude Desktop이 실행합니다.
magus import fixtures/닿으려는_종.docx --project-id book
magus import <파일> --project-id book --replace # 다시 임포트(기존 것은 trash/로)
magus conversation fixtures/대화_전체_기록.md     # 대화 기록 → 생각
magus cite-report --project-id book             # 책 전체 인용 집계(개발자용)
magus author-report --project-id book --out private/reports/<날짜>-인용-점검.md   # 저자용 보고서(md + 같은 이름 docx)
magus trash list                                # 생각·문체 휴지통 보기(put·restore idea|style <id>)
magus terms --project-id book --add 마닐라 "모스크바 회사"   # 인용으로 보지 않을 낱말(지명·사건). 인자 없으면 목록
magus alias hayashi2016 "하야시(2016)"          # 저자가 확정한 본문 표기를 문헌에 잇는다(음역 추정·a/b 모호 확정)
magus inbox --add <파일>                         # 받은함에 넣기(로컬 개발용). --remove <이름>, 인자 없으면 목록
magus synth tests/fixtures/synthetic            # 합성 원고·대화 기록 다시 만들기(커밋돼 있음, 실데이터와 분리)
magus seed-demo                                 # 데모 프로젝트와 책장 표본
magus reindex                                   # 원본 파일로 인덱스를 다시 만듭니다(파일을 직접 고친 뒤)
```

`magus`는 `.venv\Scripts\magus.exe`입니다. 콘솔에서 한글이 깨지면 `PYTHONIOENCODING=utf-8`을 붙이세요.

### 원격(HTTP) 모드 — P1 진행 중

```
magus serve --transport http --port 8000        # http://127.0.0.1:8000/mcp (streamable-http, stateless, JSON 응답)
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http --method tools/list
```

- `AUTH_ISSUER`가 없으면 인증이 없습니다. 그래서 루프백(127.0.0.1)에만 열리고, `--host 0.0.0.0`은 거부됩니다.
- `AUTH_ISSUER`·`PUBLIC_URL`·`ALLOWED_USERS`를 넣으면 토큰을 검증합니다(WorkOS AuthKit, `docs/decisions/auth-provider.md`).
  - 토큰이 없거나 무효하면 401이고, 허용 목록 밖이면 403입니다.
  - 인증 서버 위치는 `/.well-known/oauth-protected-resource/mcp`로 알립니다.
- `/healthz`는 상태 확인용입니다(인증 없음, 내용 없음).
- 파일은 받은함(`data/users/<id>/inbox/`)에 두고 도구에는 **이름만** 줍니다(`files_list()`로 확인).
  - 원격에서는 로컬 경로를 받지 않습니다. 로컬(stdio, Desktop)에서는 받은함에 없으면 로컬 경로도 받습니다.
- 한도: 업로드 한 개 `MAX_UPLOAD_MB`, 사용자별 `MAX_USER_MB`, 요청 본문 `MAX_REQUEST_MB`(넘으면 413).
- 운영(배포·백업·복구·알림)은 [docs/deploy.md](docs/deploy.md)에 있습니다. 구성은 Docker Compose(magus + Caddy + restic)입니다.
- 웹 페이지(같은 주소): `/login`, `/inbox`(받은함 업로드·삭제), `/book`(임포트·docx 내보내기), `/checklist`(인용 신호등).
  - 로컬에서는 `http://127.0.0.1:8000/login`이 `USER_ID`로 바로 로그인합니다.
  - 원격에서는 WorkOS로 로그인합니다(`WEB_CLIENT_ID`, `SESSION_SECRET`).
  - book_export는 원격에서 24시간짜리 내려받기 링크를 줍니다. 받으려면 같은 계정으로 로그인해 있어야 합니다.
- 서버 로그에는 도구 이름·user_id·소요 시간·결과만 남습니다. 원고 본문·발췌·생각은 남지 않습니다. 오류 메시지와 예외도 종류와 위치만 남깁니다.

### fixtures로 확인하기

```
magus import fixtures/<닿으려는_종…>.docx --project-id book > report.md
magus conversation fixtures/대화_전체_기록.md
```

임포트 리포트에서 다음을 확인하세요.

- 장·부 수
- 분할 못 한 구간, 목차로 판단해 버린 줄
- 코멘트 분류(kind, ref_key)
- 참고문헌 파싱 실패 줄

전체 표는 `data/users/<id>/projects/book/original/import-report.md`에 있습니다.

## 데이터

원본은 모두 `DATA_DIR` 아래에 사람이 읽을 수 있는 파일로 저장됩니다. `index.sqlite`는 이 파일들로 언제든 다시 만들 수 있습니다.

```
users/<user_id>/projects/<project_id>/
  book/ch-01.md …        장 본문(맨 위에 앞머리 메타, 그 아래 markdown)
  versions/              이전 버전
  decisions.md issues.md 결정, 확인 요청
  original/              원본 원고 사본, unsplit.md, import-report.md
  exports/               book_export 결과
users/<user_id>/shelf/
  casper/<id>.json       생각·대화 발화
  melchior/<key>/        bib.json, passages.json, full.txt
  balthasar/<id>.json    문체 표본
users/<user_id>/trash/   다시 임포트할 때 밀려난 프로젝트
```

## 문제 해결

- **`uv sync`가 "다른 프로세스가 파일을 사용 중" 오류로 실패한다**: Claude Desktop이 `magus.exe`를 실행 중이기 때문입니다. Desktop을 종료하거나 `uv pip install <패키지>`를 쓰세요.
- **새 도구가 Desktop에 보이지 않는다**: Desktop을 완전히 종료한 뒤 다시 실행하세요. 서버는 시작할 때의 코드로 계속 돕니다.
- **장 파일을 직접 고쳤는데 outline에 반영되지 않는다**: `magus reindex`를 실행하세요.
