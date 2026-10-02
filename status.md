# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 03:25 KST

## 1. 지금 바로 할 일

- 대기: `fixtures/` 폴더가 아직 없다. 원고 docx 1개(파일명에 `닿으려는_종`)와 대화 기록 md 3개(그중 `대화_전체_기록.md`)를 넣어야 한다. 누가: 사용자. docx가 없고 PDF만 있으면 PDF 폴백으로 진행하고, 리포트에 "코멘트는 PDF 텍스트에서 추출"이라고 표시한다.
- 대기: Claude Desktop을 **완전히 종료**(트레이 → 종료)했다가 다시 실행한 뒤 "Magus의 book_outline을 호출해 줘"로 확인한다. 누가: 사용자. 설정 항목은 03:18에 추가했고, 03:20에도 그대로 남아 있었다.
- fixtures가 들어오면: 2단계를 시작한다.
  1. docx 구조를 조사한다(장·부 제목 표기, `word/comments.xml`과 앵커, 참고문헌 섹션).
  2. book_import를 구현한다.
  3. 임포트 리포트(장 수, 부 수, 분할 실패 구간, 코멘트→이슈 수, 참고문헌→refs 수, 파싱 실패 줄)와 `ch-NN.md ↔ 장 제목` 매핑표를 출력한다.
  4. **멈추고 사용자가 매핑을 확인할 때까지 기다린다.** 확인을 받은 뒤에 3단계로 간다.

## 2. 현재 단계

작업 순서 1~7단계 중 **1단계 완료 + 1단계 검토 반영 완료**(수정 1·2, 승인 사항, 환경 결정). **2단계는 대기 중**이다(fixtures 없음). 3단계 범위 중 book_read_chapter와 book_write_chapter는 수정 1을 위해 미리 구현했다.

## 3. 단계별 체크리스트

- [x] **1단계 뼈대** — 완료 2026-10-03, 검토 반영 2026-10-03
  - 산출물: `src/magus/{config,ids,instructions,server,transports,cli,__main__}.py`, `src/magus/store/{base,local,schema,formats}.py`, `src/magus/book/{outline,tools,demo}.py`, `tests/test_{config,store,outline,server,stdio,instructions}.py`, `README.md`, `CLAUDE.md`
  - [x] Desktop 설정에 magus 추가(백업: `claude_desktop_config.json.bak-20261003-031857`)
  - [ ] Claude Desktop 재시작 후 연결 확인 (사용자)
- [ ] **2단계** book_import (장 분할·코멘트→issues·참고문헌, 리포트, ch-NN.md↔제목 매핑) → 리포트 후 멈춤
- [ ] **3단계** book_decide / book_issue_add / book_issue_close / book_export(pypandoc_binary) — *book_read_chapter·book_write_chapter·버전 저장은 미리 완료*
- [ ] **4단계** ref_import_bibliography / ref_add / ref_search / ref_check + 인용 게이트를 write에 연결(`unverified_cites` 채우기)
- [ ] **5단계** idea_add / idea_add_conversation / idea_search (fixtures md 3개)
- [ ] **6단계** style_add / style_search
- [ ] **7단계** 하이브리드 검색(RRF) 정리, instructions 최종 확인, README 완성

## 4. 검토 대기 결정

사용자가 아직 확인하지 않은 것들이다.

1. **git 브랜치 정책**: 지금까지 `master`에 바로 커밋했다(검토 지시 "git 첫 커밋"에 따라). 단계마다 브랜치를 따서 병합할지는 정하지 않았다.
2. **book_read/write의 추가 인자와 필드**: 스펙에 없는 것들을 넣었다.
   - 인자: `project_id?`(read·write), `title?`·`status?`(write)
   - 응답 필드: `part_number`, `updated_at`, `char_count`, `open_issues`(read), `archived_version`, `warnings`(write)
3. **빈 본문 쓰기 거부**: `book_write_chapter`는 본문이 비어 있으면 오류를 낸다(장을 지우는 경로를 막으려는 것).
4. **`unverified_cites: null`**: 4단계 전에는 "검사 안 함"을 null로 표시한다(빈 목록 `[]`과 구분). outline의 "미확인 0"은 아직 검사 전이라는 뜻이다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (pip --user로 설치, PATH에 없음. **이 경로를 그대로 쓰기로 확정**)
  - Bash: `~/AppData/Roaming/Python/Python313/Scripts/uv.exe`
  - PowerShell: `& "$env:APPDATA\Python\Python313\Scripts\uv.exe"`
- **Python**: 프로젝트는 3.12(`.python-version`), 시스템 기본은 3.13. venv는 `.venv\`.
- **MCP SDK**: `mcp` 2.2.0(**확정**). `from mcp.server.mcpserver import MCPServer`. 도구는 `Tool.from_function`으로 먼저 만들고 `MCPServer(name=, instructions=, tools=)`로 넘긴다. 실패는 `ToolError`로 올린다.
- **pandoc**: 없음 → `pypandoc_binary`로 **확정**(3단계에서 의존성 추가).
- **SQLite** 3.49.1(FTS5, trigram 사용 가능). 인덱스 `SCHEMA_VERSION=2`.
- **Claude Desktop**
  - MSIX 설치 `Claude_2.16120.0.0`. 설정 파일은 `%APPDATA%\Claude`가 아니라 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`에 있다.
  - 로그: 같은 폴더의 `logs\mcp-server-magus.log`
  - 백업: 같은 폴더의 `claude_desktop_config.json.bak-20261003-031857`
  - 추가한 항목: `"magus": {"command": "C:\\project_2026\\Magus\\.venv\\Scripts\\magus.exe", "args": ["serve"], "env": {"USER_ID": "default", "DATA_DIR": "C:\\project_2026\\Magus\\data", "EMBEDDINGS": "none"}}`
- **명령**(Bash, 프로젝트 루트에서 실행)
  ```
  UV=~/AppData/Roaming/Python/Python313/Scripts/uv.exe
  $UV sync
  $UV run pytest -q
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/magus.exe seed-demo
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/magus.exe reindex
  .venv/Scripts/magus.exe serve          # Desktop이 실행하는 것과 같다(stdio)
  ```
  - 콘솔에서 한글을 읽으려면 `PYTHONIOENCODING=utf-8`을 붙인다.
  - Bash 도구의 heredoc은 `\\`를 `\`로 줄인다. 백슬래시가 들어간 소스는 Edit/Write 도구로 고친다.
- **git**: 브랜치 `master`, 작성자 sml122900, 원격 저장소 없음. `fixtures/`와 `data/`는 .gitignore에 있다. core.autocrlf 경고(LF→CRLF)는 무시해도 된다.

## 6. 마지막 세션 요약

**2026-10-03**
- 한 일
  - 킥오프와 1단계 뼈대. 문서화 체계(status.md, docs/)를 만들었다.
  - 1단계 검토를 반영했다.
    - 승인 사항: part_number, 번호 재사용 금지, outline 첫 줄 표시.
    - 수정 1: book_read_chapter·book_write_chapter와 front matter 경계.
    - 수정 2: instructions를 등록된 도구 목록에서 조립.
  - README에 uv를 PATH 없이 쓰는 방법을 적었다.
  - Desktop 설정에 magus를 추가했다(백업 후). 설정에 적은 명령을 직접 실행해 도구 3개가 응답하는 것을 확인했다.
  - 테스트 35개 통과. 커밋했다.
- 남긴 것
  - fixtures가 없어서 2단계는 시작하지 못했다.
  - Desktop 재시작 후 확인을 기다린다.
  - 검토 대기 결정 4건.

## 7. 알려진 문제

- **outline의 미해결 표시 한계**: 35장 규모에 장 제목이 길면 목차가 예산 대부분을 쓴다. 그래서 미해결 86건 중 7건만 실리고 "외 79건"으로 접힌다(첫 줄 형식을 바꾼 뒤 다시 재도 추정 2,845/3,000토큰, 그대로 7건). 2단계에서 실제 원고로 다시 확인한다. 대안: 목차에서 status 생략, 미해결을 장별 건수로만 표시. 장별 미해결은 이제 book_read_chapter의 `open_issues`에서 볼 수 있다.
- **Desktop이 설정 파일을 다시 쓸 수 있음**: Desktop은 실행 중에 같은 파일에 preferences를 쓴다. 재시작한 뒤 `mcpServers.magus`가 사라졌는지 확인한다. 사라졌으면 백업과 status의 항목으로 복구한다.
- **번호 충돌 가능성**: 결정·미해결 번호는 프로세스 안의 락으로만 보호된다. CLI와 서버가 동시에 쓰면 번호가 충돌할 수 있다(P0에서는 허용). 재사용은 막았다.
- **직접 수정 감지 없음**: 장 파일을 사람이 직접 고치면 자동으로 감지하지 못한다. `magus reindex`를 실행해야 인덱스에 반영된다. book_read_chapter의 메타는 인덱스에서, 본문은 파일에서 읽는다.
- **토큰 추정은 휴리스틱**: 한글 1자를 1토큰, ASCII 3자를 1토큰으로 센다. 실제 토크나이저가 아니고, 보수적으로 잡은 값이다.
- **FTS 한국어 토큰화 미정**: trigram은 2글자 이름("갤러")을 찾지 못한다. 4단계에서 정한다(후보: 한글 bigram으로 사전 토큰화).
