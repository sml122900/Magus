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
| `ref_add(bib, passages, file_path?/full_text?, aliases?)` | 읽은 문헌을 발췌와 함께 verified로 넣습니다. |
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
| `EMBEDDINGS` | `none` | `none` \| `voyage` \| `openai` |
| `VOYAGE_API_KEY` / `OPENAI_API_KEY` | — | 임베딩 제공자를 쓸 때만 필요합니다 |
| `EMBEDDINGS_MODEL` | voyage-3.5 / text-embedding-3-small | 임베딩 모델 |

임베딩을 켜면 검색이 키워드(FTS)와 뜻(벡터)을 함께 씁니다.
꺼져 있거나 키가 없거나 API 호출이 실패하면 키워드 검색만으로 동작합니다.
한국어는 2글자씩 겹쳐 색인하므로 "갤러" 같은 짧은 이름도 찾습니다.

## 명령

```
magus serve                                     # MCP 서버(stdio). Claude Desktop이 실행합니다.
magus import fixtures/닿으려는_종.docx --project-id book
magus import <파일> --project-id book --replace # 다시 임포트(기존 것은 trash/로)
magus conversation fixtures/대화_전체_기록.md     # 대화 기록 → 영감 책장
magus synth data/synthetic-fixtures             # 합성 원고·대화 기록 만들기(실파일이 없을 때)
magus seed-demo                                 # 데모 프로젝트와 책장 표본
magus reindex                                   # 원본 파일로 인덱스를 다시 만듭니다(파일을 직접 고친 뒤)
```

`magus`는 `.venv\Scripts\magus.exe`입니다. 콘솔에서 한글이 깨지면 `PYTHONIOENCODING=utf-8`을 붙이세요.

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
