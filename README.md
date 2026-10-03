# Magus

책을 쓰는 사람의 세 책장과 원고를 Claude에게 MCP로 열어 주는 서버입니다.

| 책장 | 표시명 | 하는 일 |
|---|---|---|
| 영감 | **Casper · 몰약** | 생각과 대화를 보존합니다. 내가 한 말(me)과 AI가 한 말(ai)을 구분합니다. |
| 문헌 | **Melchior · 황금** | 실제로 읽고 발췌한(verified) 문헌만 인용할 수 있게 합니다. 나머지는 표시하고 집계합니다. |
| 문체 | **Balthasar · 유향** | 내가 좋아하는 문장을 이유·태그와 함께 기록하고, 문체로 찾습니다. |
| 원고 | book | 장 단위로 저장하고 버전을 남깁니다. 결정과 미해결 사항도 기록합니다. |

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
| "Magus의 book_outline을 호출해 줘" | `book_outline` | 첫 줄 `프로젝트: 닿으려는 종 (book)`<br>둘째 줄 `35장 + 서장·맺음·부록 1~3 · 8부 · 249,065자 · 미확인 문헌 297편 · 미연결 0 · 열린 미해결 86`<br>미해결 절 `코멘트 유래 미해결 86건(citation 44 · fact 40 · general 2)` |
| "제12장 인용 중 확인 안 된 것 알려줘" | `ref_check(12)` 한 번 | `unverified` 28편, `unique_unchecked: 28`, `verified: []`<br>문헌마다 문단 번호가 붙는다. 예: marchetti1994 `paragraphs: [16, 41]`, pachecocobos2019 `[28, 29]` |
| "제31장 읽고 세 문장으로 요약해 줘" | `book_read_chapter(31)` 한 번 | 제목 `대치동은 왜 아이를 줄이나`, 3,386자, 미확인 문헌 8편, 열린 미해결 1건(I78)<br>책 전체나 다른 장을 요구하지 않아야 한다. 본문에 "제13장에서 보았듯"이 있어도 13장을 읽지 않는다<br>규칙 1에 따라 `book_outline`을 먼저 부르는 것은 괜찮다 |
| "사실·수치 확인 요청만 보여 줘" | `book_issues(kind="fact")` | `미해결 40건 (status=open, kind=fact)`<br>첫 항목 `I3 · open · 1장 · import_comment · fact · 확인 필요: 폐가 부레보다…` |

"미확인 문헌 297편"은 책 전체에서 한 번씩 센 고유 문헌 수입니다. 저자 보고서 1절의 "문헌 297편"과 같은 숫자입니다.
장마다 센 수는 목차의 각 장 줄(`미확인인용 n`)에만 있습니다.
"미연결"은 한글 표기인데 참고문헌과 잇지 못한 것입니다. 미확인 수에는 넣지 않지만 숨기지 않습니다(`ref_check`의 `uncertain` 목록).
35장의 `케인스(1930)`처럼 연도 a/b가 모호한 인용은 어느 쪽에도 잇지 않고 후보 둘을 함께 보입니다(`candidates`).
확정하면 `magus alias keynes1930b "케인스(1930)"`로 넣습니다.

도구가 불리지 않거나 오류가 나면 로그 끝부분을 보세요.

### 3. 문헌 등록 시연 (`ref_add`)

**논문 PDF는 `C:\project_2026\Magus\fixtures\papers\`에 둡니다.** 이 폴더는 git에 올라가지 않습니다(`fixtures/`는 .gitignore).

1. 논문 PDF를 `fixtures\papers\`에 둡니다. 예: `kremer1993.pdf`.
2. Desktop 새 대화에서 이 문장을 그대로 씁니다(`<파일명>`, `「…」`, `…`만 바꿉니다).
   > fixtures/papers/<파일명>.pdf를 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …

   기대 결과: 해당 key가 verified로 바뀌고, 그 문헌이 나오는 장 목록이 나옵니다(아래 4번).
3. Claude가 다음과 같이 `ref_add`를 부릅니다.
   ```
   ref_add(bib={}, passages=[{text: "쓸 부분", reason: "이유"}], file_path="fixtures/papers/kremer1993.pdf")
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

쓸 부분은 논문의 문장을 그대로 붙이는 것이 좋습니다. `ref_search`가 이 발췌를 먼저 돌려주고, 글에는 이것만 인용됩니다.
PDF를 대화창에 첨부하지 말고 경로로 말하세요. 그래야 서버가 파일을 직접 읽어 전문을 저장합니다.

서버 쪽 흐름은 `tests/test_stdio.py::test_relative_file_path_from_other_cwd`가 확인합니다.
이 테스트는 다른 작업 폴더에서 서버를 하위 프로세스로 띄우고, 상대 경로로 PDF를 등록합니다.

## 처음 쓰는 순서

1. **원고 가져오기**: "`C:\…\원고.docx`를 book_import로 가져와 줘"
   - 리포트로 장 매핑과 코멘트 분류를 확인합니다.
2. **대화 기록 넣기**: "`C:\…\대화_전체_기록.md`를 idea_add_conversation(path)로 넣어 줘"
3. **작업 시작**: 매번 `book_outline`으로 시작하고, 필요한 장만 `book_read_chapter`로 읽습니다.
4. **문헌 검증**: 읽은 문헌은 `ref_add`로 발췌와 함께 넣습니다. 그러면 그 문헌을 인용한 곳이 verified가 됩니다.
   - 장을 고치면 `book_write_chapter`가 미확인 인용을 알려 줍니다.
5. **문체**: 좋아하는 문장은 `style_add`로 넣고, 문체 작업 전에 `style_search`로 꺼냅니다.

같은 일을 명령줄로도 할 수 있습니다(아래 "명령").

## 도구 (18개)

| 도구 | 하는 일 |
|---|---|
| `book_outline(project_id?)` | 책의 지도. 3,000토큰 이하이고 본문은 없습니다. 장별 상태·글자수·미해결·미확인 인용 집계, 직접 남긴 미해결, 최근 결정과 변경을 줍니다. |
| `book_read_chapter(number)` | 장 하나. 본문(content)과 메타를 별도 필드로 줍니다. 미확인 인용과 그 장의 미해결도 함께 줍니다. |
| `book_write_chapter(number, content, note, title?, status?)` | 장 하나를 저장합니다. 이전본은 versions/에 남고, 쓴 뒤 인용 게이트 결과를 돌려줍니다. |
| `book_issues(status, chapter_number?, origin?, kind?, limit)` | 미해결 목록(조회 전용). |
| `book_decide(text)` · `book_issue_add(text, chapter_number?, origin)` · `book_issue_close(id, note?)` | 결정과 열린 문제를 기록합니다. 번호는 다시 쓰지 않습니다. |
| `book_import(path, project_id?, title?, replace?)` | docx(또는 pdf) 원고를 장 단위로 나눕니다. 코멘트는 미해결, 참고문헌은 refs가 됩니다. |
| `book_export(path?)` | 장을 합쳐 docx로 만듭니다. |
| `ref_import_bibliography(text)` | 참고문헌 목록을 refs(unverified)로 넣습니다. |
| `ref_add(bib, passages, file_path?/full_text?, aliases?)` | 읽은 문헌을 발췌와 함께 verified로 넣습니다. 저자·연도 없이 파일만 주면 첫머리의 제목으로 참고문헌에서 찾습니다. |
| `ref_search(query, scope, k)` | verified 문헌의 발췌(먼저)와 전문에서 찾습니다. |
| `ref_check(chapter_number)` | 장의 인용을 verified / unverified / unknown으로 나눕니다. |
| `idea_add(text, kind, origin?)` | 내 생각 하나를 기록합니다(author=me). |
| `idea_add_conversation(markdown? / path?)` | 대화 기록을 me·ai 발화로 나눠 저장합니다. |
| `idea_search(query, author, k)` | 생각을 찾습니다. 기본은 내 생각만입니다. |
| `style_add(passage, reason, tags, work?)` | 문체 표본을 기록합니다. tags는 `{호흡, 시점, 열기, 장치: [], 어미, 톤}`입니다. |
| `style_search(query, k)` | 문체로 찾습니다(이유와 태그 기준). |

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

원격 모드 변수의 예시는 `.env.example`에 있습니다. 비밀은 환경변수로만 넣고 `.env`는 커밋하지 않습니다.

임베딩을 켜면 검색이 키워드(FTS)와 뜻(벡터)을 함께 씁니다.
꺼져 있거나 키가 없거나 API 호출이 실패하면 키워드 검색만으로 동작합니다.
한국어는 2글자씩 겹쳐 색인하므로 "갤러" 같은 짧은 이름도 찾습니다.

## 명령

```
magus serve                                     # MCP 서버(stdio). Claude Desktop이 실행합니다.
magus import fixtures/닿으려는_종.docx --project-id book
magus import <파일> --project-id book --replace # 다시 임포트(기존 것은 trash/로)
magus conversation fixtures/대화_전체_기록.md     # 대화 기록 → 영감 책장
magus cite-report --project-id book             # 책 전체 인용 집계(개발자용)
magus author-report --project-id book --out docs/reports/<날짜>-인용-점검.md   # 저자용 보고서(md + 같은 이름 docx)
magus terms --project-id book --add 마닐라 "모스크바 회사"   # 인용으로 보지 않을 낱말(지명·사건). 인자 없으면 목록
magus alias hayashi2016 "하야시(2016)"          # 저자가 확정한 본문 표기를 문헌에 잇는다(음역 추정·a/b 모호 확정)
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
  decisions.md issues.md 결정, 미해결
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
