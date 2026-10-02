# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 03:10 KST

## 1. 지금 바로 할 일

- 대기: `fixtures/`에 원고 docx 1개(파일명에 `닿으려는_종`)와 대화 기록 md 3개(그중 `대화_전체_기록.md`)를 넣는다. 누가: 사용자.
- 대기: Claude Desktop에 magus를 연결하고 "Magus의 book_outline을 호출해 줘"로 데모 outline이 나오는지 확인한다. 누가: 사용자. 방법은 README "Claude Desktop 연결" 참고. 03:01 기준 Desktop 설정에 `mcpServers`가 아직 없다.
- fixtures가 들어오면: 2단계를 시작한다. 먼저 docx 구조를 조사한다(장·부 제목 표기, `word/comments.xml`과 앵커, 참고문헌 섹션).

## 2. 현재 단계

작업 순서 1~7단계 중 **1단계 완료**(코드·테스트·문서·커밋). Desktop 연결 확인은 사용자 대기. **2단계는 대기 중**이다(fixtures 필요).

## 3. 단계별 체크리스트

- [x] **1단계 뼈대** (Store 인터페이스, SQLite 스키마, 설정, stdio 서버, book_outline) — 완료 2026-10-03
  - 산출물: `src/magus/{config,ids,instructions,server,transports,cli,__main__}.py`, `src/magus/store/{base,local,schema,formats}.py`, `src/magus/book/{outline,tools,demo}.py`, `tests/test_{config,store,outline,server,stdio}.py`, `README.md`, `CLAUDE.md`
  - [ ] Claude Desktop 연결 확인 (사용자)
- [ ] **2단계** book_import (장 분할·코멘트→issues·참고문헌, 리포트, ch-NN.md↔제목 매핑)
- [ ] **3단계** book_read_chapter / book_write_chapter / book_decide / book_issue_add / book_issue_close / book_export + 버전 저장
- [ ] **4단계** ref_import_bibliography / ref_add / ref_search / ref_check + 인용 게이트를 write에 연결
- [ ] **5단계** idea_add / idea_add_conversation / idea_search (fixtures md 3개)
- [ ] **6단계** style_add / style_search
- [ ] **7단계** 하이브리드 검색(RRF) 정리, instructions 적용 확인, README 완성

## 4. 검토 대기 결정

사용자가 아직 확인하지 않은 것들이다.

1. **`parts` 테이블 추가**: 데이터 모델에는 없다. 완료 기준의 "부 8개"를 저장하려고 넣었다. 부 제목은 `project.json`의 `parts`, 장이 어느 부에 속하는지는 front matter의 `part`에 둔다.
2. **결정·미해결 id**: 프로젝트별 일련번호 `D{n}`/`I{n}`이다. `book_issue_close`는 "I3"이나 3으로 받을 예정이다.
3. **현재 프로젝트 규칙**: project_id를 생략하면 그 사용자의 가장 최근에 갱신된 프로젝트를 쓴다.
4. **instructions 조기 적용**: 1단계부터 6절 원문을 넣었다. 아직 없는 도구(ref_search 등)를 언급한다.
5. **.gitignore**: `fixtures/`(실제 원고)와 `data/`를 리포에서 뺐다.
6. **Desktop 설정**: Claude가 `claude_desktop_config.json`에 magus 항목을 직접 넣을지, 사용자가 넣을지.
7. **uv 영구 설치**: user Scripts 폴더를 PATH에 넣을지, 공식 설치 스크립트로 다시 설치할지(지금은 전체 경로로 실행 중).
8. **git 브랜치 정책**: 첫 커밋 두 개는 `master`에 했다(빈 저장소라 분기할 기준점이 없었다). 앞으로 단계마다 브랜치(`step-2-import` 등)를 따서 병합할지, master에 바로 커밋할지.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (pip --user로 설치, PATH에 없음)
  - Bash: `~/AppData/Roaming/Python/Python313/Scripts/uv.exe`
  - PowerShell: `& "$env:APPDATA\Python\Python313\Scripts\uv.exe"`
- **Python**: 프로젝트는 3.12(`.python-version`), 시스템 기본은 3.13. venv는 `.venv\`.
- **MCP SDK**: `mcp` 2.2.0. `from mcp.server.mcpserver import MCPServer`(FastMCP는 없어짐). 테스트는 `mcp.Client(server)`(in-process)와 `Client(StdioServerParameters)`(하위 프로세스)로 한다.
- **SQLite** 3.49.1(FTS5, trigram 사용 가능).
- **pandoc**: 없음. 3단계에서 `pypandoc_binary`(pandoc 내장 휠)를 쓸 예정이다.
- **Claude Desktop 설정 파일**(MSIX 설치라서 `%APPDATA%\Claude`가 아님): `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`
  - 로그: 같은 폴더의 `logs\mcp-server-magus.log`
  - 넣을 항목: `"magus": {"command": "C:\\project_2026\\Magus\\.venv\\Scripts\\magus.exe", "args": ["serve"], "env": {"USER_ID": "default", "DATA_DIR": "C:\\project_2026\\Magus\\data", "EMBEDDINGS": "none"}}`
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
- **git**: 브랜치 `master`, 작성자 sml122900. 원격 저장소 없음.

## 6. 마지막 세션 요약

**2026-10-03**
- 한 일
  - 킥오프와 CLAUDE.md 작성, 환경 준비(uv, mcp 2.2.0).
  - 1단계 뼈대: Store, 스키마, 설정, stdio 서버, book_outline. 테스트 24개 통과.
  - 실제 `data/`에 데모 프로젝트(`demo`)를 만들었다.
  - 검토 반영: 문서화 체계(status.md, docs/)를 만들고, "도구는 본문만" 원칙을 코드로 강제했다.
  - 커밋 2개: feat(1단계), docs(문서화).
- 남긴 것
  - fixtures 대기.
  - Desktop 확인 대기.
  - 검토 대기 결정 8건.
  - outline 미해결 표시 한계(아래 알려진 문제).

## 7. 알려진 문제

- **outline의 미해결 표시 한계**: 35장 규모에 장 제목이 길면 목차가 예산 대부분을 쓴다. 그래서 미해결 86건 중 7건만 실리고 "외 79건"으로 접힌다(추정 2,846/3,000토큰). 2단계에서 실제 원고로 다시 확인한다. 대안: 목차에서 status 생략, 미해결을 장별 건수로만 표시.
- **아직 없는 도구를 가리키는 안내**: outline의 "장별 미해결은 book_read_chapter 메타에 있음"과 instructions가 언급하는 도구는 각 단계 전까지 존재하지 않는다.
- **번호 충돌 가능성**: 결정·미해결 번호는 프로세스 안의 락으로만 보호된다. CLI와 서버가 동시에 쓰면 번호가 충돌할 수 있다(P0에서는 허용).
- **직접 수정 감지 없음**: 장 파일을 사람이 직접 고치면 자동으로 감지하지 못한다. `magus reindex`를 실행해야 인덱스에 반영된다.
- **토큰 추정은 휴리스틱**: 한글 1자를 1토큰, ASCII 3자를 1토큰으로 센다. 실제 토크나이저가 아니고, 보수적으로 잡은 값이다.
- **FTS 한국어 토큰화 미정**: trigram은 2글자 이름("갤러")을 찾지 못한다. 4단계에서 정한다(후보: 한글 bigram으로 사전 토큰화).
