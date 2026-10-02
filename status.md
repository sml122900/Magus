# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 03:45 KST

## 1. 지금 바로 할 일

- **대기: fixtures 투입(사용자).** 03:40 기준 `fixtures/` 폴더가 없다.
  - 필요한 파일: 원고 docx 1개(파일명에 `닿으려는_종`), 대화 기록 md 3개(그중 `대화_전체_기록.md`).
  - docx가 없고 PDF만 있으면 PDF 폴백으로 진행하고, 리포트에 "코멘트는 PDF 텍스트에서 추출"이라고 표시한다.
- **대기: Claude Desktop 재시작 후 확인(사용자).**
  - 트레이에서 완전히 종료한 뒤 다시 실행하고, "Magus의 book_outline을 호출해 줘"로 확인한다.
  - 03:40 기준 설정 항목은 그대로 있다. `logs\mcp-server-magus.log`는 아직 없다. 재시작하지 않은 것으로 보인다.
- **fixtures가 들어오면 2단계를 시작한다.**
  1. docx 구조를 조사한다(장·부 제목 표기, `word/comments.xml`과 앵커, 참고문헌 섹션).
  2. book_import를 구현한다. 코멘트는 `classify_comment(코멘트, 앵커 원문)`으로 kind와 ref_key를 붙인다.
  3. 리포트를 출력한다: 장 수, 부 수, 분할 실패 구간, 코멘트→이슈 수(kind별, ref_key를 찾은 수), 참고문헌→refs 수, 파싱 실패 줄, `ch-NN.md ↔ 장 제목` 매핑표.
  4. **멈추고, 사용자가 매핑을 확인할 때까지 기다린다.**
  - 파서 실험은 브랜치(`step2-parser` 등)에서 하고, 끝나면 squash merge한다.

## 2. 현재 단계

**1단계 확정**(태그 `step1`). 검토 반영, 결정 4건, outline 구조 변경, 2단계 준비(코멘트 분류, 인용 추출기)를 모두 마쳤다. **2단계는 대기 중**이다(fixtures 없음).

## 3. 단계별 체크리스트

- [x] **1단계 뼈대** — 완료 2026-10-03, 태그 `step1`
  - 산출물
    - `src/magus/{config,ids,instructions,server,transports,cli,__main__}.py`
    - `src/magus/store/{base,local,schema,formats}.py`
    - `src/magus/book/{outline,tools,demo,comments}.py`
    - `src/magus/melchior/citations.py`
    - `tests/test_{config,store,outline,server,stdio,instructions,citations}.py`
    - `README.md`, `CLAUDE.md`
  - [x] Desktop 설정에 magus 추가(백업: `claude_desktop_config.json.bak-20261003-031857`)
  - [ ] Claude Desktop 재시작 후 연결 확인 (사용자)
- [ ] **2단계** book_import(장 분할, 코멘트→issues(kind·ref_key), 참고문헌, 리포트, 매핑표) → 리포트 후 멈춤
  - 미리 된 것: `classify_comment`, `find_citations`, issues.kind/ref_key, `book_issues`
- [ ] **3단계** book_decide / book_issue_add / book_issue_close / book_export(pypandoc_binary)
  - 미리 된 것: book_read_chapter, book_write_chapter, 버전 저장
- [ ] **4단계** ref_import_bibliography / ref_add / ref_search / ref_check + 인용 게이트를 write에 연결(`unverified_cites` 채우기, citation 이슈의 ref_key를 refs와 연결)
- [ ] **5단계** idea_add / idea_add_conversation / idea_search (fixtures md 3개)
- [ ] **6단계** style_add / style_search
- [ ] **7단계** 하이브리드 검색(RRF) 정리, instructions 최종 확인, README 완성

## 4. 검토 대기 결정

없다. 2026-10-03 사용자 답변으로 모두 확정했다.
- master에 바로 커밋하고 단계마다 태그를 단다.
- 스펙 외 인자·필드는 승인됐다.
- status는 `draft|revising|done`이다.
- 빈 본문은 거부한다.
- `unverified_cites`는 null(미검사)과 `[]`(검사했고 없음)를 구분한다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음, 이 경로로 확정)
  - Bash: `~/AppData/Roaming/Python/Python313/Scripts/uv.exe`
  - PowerShell: `& "$env:APPDATA\Python\Python313\Scripts\uv.exe"`
- **Python**: 프로젝트는 3.12(`.python-version`), 시스템 기본은 3.13. venv는 `.venv\`.
- **MCP SDK**: `mcp` 2.2.0(확정). `from mcp.server.mcpserver import MCPServer`. 도구는 `Tool.from_function`으로 먼저 만들고 `MCPServer(name=, instructions=, tools=)`로 넘긴다. 실패는 `ToolError`로 올린다. 인자를 `Literal`로 쓰면 스키마 enum이 되고, 다른 값은 SDK가 거부한다.
- **pandoc**: 없음 → `pypandoc_binary`로 확정(3단계에서 의존성 추가).
- **SQLite** 3.49.1(FTS5, trigram 사용 가능). 인덱스 `SCHEMA_VERSION=3`.
- **Claude Desktop**
  - MSIX 설치 `Claude_2.16120.0.0`. 설정 파일은 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`에 있다.
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
- **git**
  - 브랜치 `master`에 바로 커밋한다. 단계를 완료하면 태그(`step1`, …)를 단다. 실험만 브랜치를 쓰고 squash merge한다.
  - 작성자 sml122900. 원격 저장소 없음.
  - `fixtures/`와 `data/`는 .gitignore에 있다. LF→CRLF 경고는 무시해도 된다.

## 6. 마지막 세션 요약

**2026-10-03**
- 한 일
  - 킥오프 → 1단계 뼈대 → 문서화 체계 → 1단계 검토 반영 → 검토 대기 결정 답변 반영과 보완. 1단계를 확정하고 태그 `step1`을 달았다.
  - 이번 반영분
    - status 값 제한, `unverified_cites`의 뜻을 도구 설명에 명시.
    - outline 집계화와 `book_issues` 도구(직접 남긴 미해결 16건이 3,000토큰 안에 모두 실림).
    - 이슈 kind·ref_key, 코멘트 분류기, 인용 추출기.
  - 테스트 54개 통과.
- 남긴 것
  - fixtures 대기(2단계를 시작하지 못함).
  - Desktop 재시작 후 확인 대기.

## 7. 알려진 문제

- **outline의 결정·변경 일부 생략**: 일부러 불리하게 잡은 규모(장 제목 28자 × 35장, 직접 남긴 미해결 16건)에서는 결정 10건 중 7건, 변경 5건 중 2건만 실리고 나머지는 "외 N건"으로 접힌다(추정 2,893토큰). 가장 최근 것은 항상 실린다. 실제 원고로 2단계에서 다시 잰다.
- **코멘트 분류 마커 "서지"의 오탐 가능성**: "일어서지"처럼 다른 낱말 안에 든 "서지"도 citation으로 분류된다. 실제 코멘트로 2단계에서 보정한다. 공백 무시 매칭도 같이 점검한다.
- **인용 추출기의 한계**
  - `(Clack, 2012; Hu et al., 2023)`처럼 한 괄호에 여러 인용이 있으면, 괄호·서술형 패턴은 첫 인용만 잡는다. bare 모드에서는 둘째도 잡힌다.
  - 한글 저자 뒤에 조사가 붙으면(`갤러는(2022)`) 조사까지 key에 들어간다.
  - 4단계 ref_check 전에 `;` 분할과 조사 처리를 보강한다.
- **Desktop이 설정 파일을 다시 쓸 수 있음**: 재시작한 뒤 `mcpServers.magus`가 남아 있는지 확인한다. 사라졌으면 백업과 위 항목으로 복구한다.
- **번호 충돌 가능성**: 결정·미해결 번호는 프로세스 안의 락으로만 보호된다. CLI와 서버가 동시에 쓰면 번호가 충돌할 수 있다(P0에서는 허용). 재사용은 막았다.
- **직접 수정 감지 없음**: 장 파일을 사람이 직접 고치면 `magus reindex`를 실행해야 인덱스에 반영된다.
- **토큰 추정은 휴리스틱**: 한글 1자를 1토큰, ASCII 3자를 1토큰으로 센다. `·` 같은 비ASCII 기호도 1토큰으로 센다. 보수적으로 잡은 값이다.
- **FTS 한국어 토큰화 미정**: trigram은 2글자 이름("갤러")을 찾지 못한다. 4단계에서 정한다(후보: 한글 bigram으로 사전 토큰화).
