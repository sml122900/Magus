# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 04:40 KST — **야간 자율 작업 중**(사용자 부재, 아침 보고 예정)

## 0. 아침 보고

(야간 작업이 끝나면 여기에 쓴다)

## 1. 지금 바로 할 일

- **야간 자율 작업 지시를 수행 중이다**(질문하지 않음, 단계마다 커밋과 태그, 2→7단계).
- 다음 할 일: **4단계**
  - ref_add / ref_search / ref_check와 write 게이트.
  - 추출기 한계 3건 보강.
  - citation 이슈를 refs와 연결(ref_id).
- 그 뒤 5 → 6 → 7단계. 끝나면 "0. 아침 보고"를 채운다.

## 2. 현재 단계

**3단계 완료**(태그 `step3`). 4단계를 진행 중이다.

## 3. 단계별 체크리스트

- [x] **1단계 뼈대** — 2026-10-03, 태그 `step1`
- [x] **2단계 book_import** — 2026-10-03, 태그 `step2`, **합성 fixture**
  - 산출물
    - `src/magus/book/{docx_reader,pdf_reader,importer}.py`
    - `src/magus/melchior/{bibliography,tools}.py`
    - `src/magus/store/{shelf,fileio}.py`
    - `src/magus/textindex.py`, `src/magus/synthetic.py`
    - `tests/test_{import,bibliography}.py`
  - 도구: `book_import`, `ref_import_bibliography`. CLI: `magus import`, `magus synth`.
  - 리포트: `docs/daily/2026-10-03.md` "야간 자율 작업" 절, `data/synthetic-fixtures/step2-import-report.md`, `data/users/default/projects/synth/original/import-report.md`
- [x] **3단계** book_decide / book_issue_add / book_issue_close / book_export — 2026-10-03, 태그 `step3`
  - 산출물: `src/magus/book/export.py`, `tests/test_book_tools.py`. 도구 4개가 추가돼 instructions 4번 규칙이 활성화됐다.
- [ ] **4단계** ref_add / ref_search / ref_check + 게이트, 추출기 보강, citation 이슈 ↔ refs 연결
- [ ] **5단계** idea_*
- [ ] **6단계** style_*
- [ ] **7단계** 하이브리드 검색, provider 스텁, instructions 전체 확인, README, demo 재생성

## 4. 검토 대기 결정

야간에 혼자 고른 것들이다. 형식: 선택 / 대안 / 이유.

1. **첫 장 제목 앞의 글(표지·목차·머리말)**
   - 선택: 장으로 만들지 않고 `original/unsplit.md`에 보관하고 리포트한다.
   - 대안: `ch-00 머리말`로 만든다.
   - 이유: 장 수 기준(35±2)을 흐리지 않고, 사람이 보고 결정할 수 있다.
2. **목차와 본문에 같은 장 제목이 있을 때**
   - 선택: 뒤따르는 본문이 가장 긴 것을 진짜로 본다.
   - 대안: 마지막 것을 고르거나 목차 영역을 따로 감지한다.
   - 이유: 목차 위치나 서식과 상관없이 동작한다.
3. **코멘트 이슈 본문**
   - 선택: `코멘트 + — 원문: “앵커 120자”`.
   - 대안: 코멘트만 넣는다.
   - 이유: "확인 필요"만으로는 무엇을 확인할지 알 수 없다.
4. **파싱 실패한 참고문헌 줄**
   - 선택: `raw-<해시>` key의 unverified ref로 보관한다(refs 수에 포함된다).
   - 대안: 리포트에만 남긴다.
   - 이유: 스펙의 "bib.raw로 보관"을 따르고, 아무것도 잃지 않는다.
5. **같은 목록 안 key 충돌**
   - 선택: 뒤의 것에 `-2`, `-3`을 붙인다. 연도 접미사(2012a)가 있으면 그대로 key에 넣는다.
   - 대안: 덮어쓴다.
   - 이유: 유실을 막는다.
6. **refs 재임포트**
   - 선택: 이미 있는 key는 건드리지 않는다.
   - 대안: bib을 갱신한다.
   - 이유: 책장은 사람 소유이고, verified로 올린 것을 덮어쓰지 않아야 한다.
7. **replace=True**
   - 선택: 기존 프로젝트를 `users/<id>/trash/`로 옮긴다.
   - 대안: 삭제한다.
   - 이유: 되돌릴 수 있어야 한다.
8. **book_import 입력**
   - 선택: 로컬 파일 경로.
   - 대안: 업로드나 바이트.
   - 이유: P0는 로컬 단일 사용자다. P1(HTTP)에서는 업로드로 바꿔야 한다.
9. **장 안의 소제목(Heading 스타일)**
   - 선택: `## 소제목`으로 바꾼다.
   - 대안: 평문으로 둔다.
   - 이유: 구조를 보존한다.
10. **FTS 한국어 토큰화**(4단계 결정을 당김)
    - 선택: 한글은 2글자 bigram, 라틴 문자는 소문자 단어로 사전 토큰화한 뒤 FTS5 unicode61에 넣는다.
    - 대안: trigram.
    - 이유: 2글자 이름("갤러")을 찾을 수 있어야 한다.
12. **book_export의 path**
    - 선택: 파일 이름만 받는다(디렉터리는 버림). 저장 위치는 `projects/<id>/exports/`.
    - 대안: 임의 절대 경로.
    - 이유: SaaS 전환 때 서버 파일 시스템을 노출하지 않으려는 것이다.
13. **book_issue_add의 origin 인자**
    - 선택: user|agent, 기본값 user.
    - 대안: 항상 agent.
    - 이유: Claude가 사용자 요청으로 남긴 것과 스스로 발견한 것을 outline에서 구분한다.
14. **export 제목 단계**
    - 선택: 부는 Heading 1, 장은 Heading 2, 장 안 소제목은 Heading 3. 부가 없으면 장이 Heading 1이다. 문서 제목은 pandoc 메타데이터로 넣는다.
11. **합성 fixture 위치**
    - 선택: `data/synthetic-fixtures/`(gitignore). 생성기는 `src/magus/synthetic.py`.
    - 대안: `fixtures/`에 둔다.
    - 이유: `fixtures/`는 실파일 전용이고 읽기만 하기로 했다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음)
  - **주의**: Claude Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 진입점을 다시 쓰다가 실패한다(os error 32).
  - 그때는 `uv add --no-sync <pkg>`와 `uv pip install <pkg>`를 쓰고, 테스트는 `.venv/Scripts/python -m pytest`로 돌린다.
- **Python**: 프로젝트는 3.12. venv는 `.venv\`.
- **MCP SDK**: `mcp` 2.2.0. `Tool.from_function`으로 도구를 만들고 `MCPServer(name=, instructions=, tools=)`로 넘긴다.
- **추가 의존성**(야간): python-docx 1.2.0, pymupdf 1.28.2(`import pymupdf`), pypandoc-binary 1.17(pandoc 3.9 내장), numpy 2.5.3, lxml.
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=3`.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` (백업 `.bak-20261003-031857`)
  - **로그는 `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`**(설정 폴더 아래 logs가 아님)
  - 03:33에 Desktop이 magus를 띄웠고 initialize와 tools/list가 성공했다.
- **명령**(Bash, 프로젝트 루트에서 실행)
  ```
  .venv/Scripts/python -m pytest -q -p no:cacheprovider
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus synth data/synthetic-fixtures
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus import <docx|pdf> --project-id <id> [--replace] [--synthetic]
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus reindex
  ```
- **git**: master에 바로 커밋하고, 단계가 끝나면 태그(`stepN`)를 단다. `fixtures/`와 `data/`는 gitignore.

## 6. 마지막 세션 요약

**2026-10-03 야간**
- 2단계 완료(합성 fixture). 3단계 완료(export 왕복 테스트: 장 제목과 장별 단락 수 일치).
- 결과: 7장·3부, 목차 줄 11개 제거, 코멘트 13건(citation 8 / general 5, ref_key 75%), refs 30건(실패 3, 충돌 1).
- 테스트 81개 통과.

## 7. 알려진 문제

- **코멘트 분류 "서지" 오탐**: "일어서지"(합성 I6)도 citation으로 분류된다. 4단계에서 보강한다.
- **조사가 붙은 한글 저자 key**: `갤러는(2022)` → `갤러는2022`(합성 I4). 4단계에서 보강한다.
- **괄호 안 다중 인용**: `(Clack, 2012; Hu et al., 2023)`은 괄호·서술형 패턴에서 첫 인용만 잡힌다. 4단계에서 보강한다.
- **PDF 폴백의 한계**: 앵커는 바로 앞 블록으로 근사한다. 그림·표·수식은 구분하지 못한다.
- **Desktop 서버는 03:33에 띄운 옛 코드다**: 새 도구를 보려면 Desktop을 다시 시작해야 한다.
- 번호 충돌 가능성, 직접 수정 감지 없음, 토큰 추정 휴리스틱: 이전과 같다.
