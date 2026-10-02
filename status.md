# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 04:50 KST — 야간 자율 작업 종료(04:12 시작)

## 0. 아침 보고

### 1) 완료된 단계·태그·테스트
- **1~7단계를 모두 구현했다.** 태그는 `step1` … `step7`이고, 단계마다 테스트가 통과한 상태로 master에 커밋했다.
- 테스트 **114개 통과**. ruff(pyflakes·bugbear) 점검도 통과했다.
- 도구 **18개**. 모두 등록되면 instructions가 6절 원문과 글자까지 같다(테스트로 고정).

### 2) 실데이터 / 합성 데이터
- **`fixtures/`가 없어서 실데이터로는 하나도 돌리지 못했다.**
- 2·4·5단계는 전부 **합성 fixture**(`magus synth data/synthetic-fixtures`)로 검증했고, 리포트에 "합성 fixture"라고 표시했다.
- 3·6·7단계는 단위 테스트와 합성 프로젝트로 검증했다.
- 합성 데이터는 `data/users/synthetic/`에 따로 두었다. `default` 사용자에는 데모만 있다. 아침의 실원고 임포트와 섞이지 않게 하려는 것이다.

| 단계 | 데이터 | 결과 |
|---|---|---|
| 2 임포트 | 합성 docx(7장 3부, 코멘트 13, 참고문헌 30줄)와 합성 PDF | 장·부 정확, 목차 줄 11개 제거, 코멘트 13 → citation 7 / general 6, ref_key 후보 86% |
| 3 export | 합성 프로젝트 | export docx를 다시 열어 장 제목 7개와 장별 단락 수가 일치 |
| 4 refs | 합성 참고문헌과 본문 | 미확인 인용 합계 9건(1장 8, 4장 1). daeschler2006·clack2012 미확인 → ref_add 뒤 verified |
| 5 영감 | 합성 대화 3종 | 96쌍 기록 me 96 / ai 96(모든 ai에 parent_id), 질문/답변 10/10, 인용/요지 8/8 |
| 6 문체 | 단위 테스트 | 주제어로는 안 찾히고 문체 질의로 찾힘 |
| 7 검색 | 가짜 임베더(네트워크 없음) | 벡터만 잡는 질의를 RRF로 찾음, 임베딩 실패 시 FTS로 계속 |

### 3) 실원고 결과
- 실원고는 없다. 그래서 장별 미확인 인용 집계와 실원고 outline 토큰 측정은 하지 못했다.
- 합성 결과물의 위치는 다음과 같다.
  - 임포트 리포트·매핑표·코멘트 분류 표: `docs/daily/2026-10-03.md` "야간 자율 작업" 절, `data/synthetic-fixtures/step2-import-report.md`, `step4-import-report.md`(보강 후 재임포트), `data/users/synthetic/projects/synth/original/import-report.md`
  - 장별 미확인 인용 집계: `data/synthetic-fixtures/step4-refcheck-report.md`, 일지 4단계 절
  - outline 토큰(합성): synth 7장 추정 431토큰, demo 436토큰(예산 3,000). 35장 규모의 불리한 가짜 책에서는 2,893토큰이었다(테스트).

### 4) 검토 대기 결정
아래 "4. 검토 대기 결정"에 26건이 있다. 그중 먼저 봐 주면 좋은 것은 다음과 같다.
- **#1 머리말 처리**: 첫 장 제목 앞의 글을 장으로 만들지 않고 `original/unsplit.md`에 둔다.
- **#15 verified의 조건**: ref_add는 발췌가 하나 이상 있어야 받는다.
- **#16 ref_id**: 이슈의 ref_id에 정식 ref key를 쓴다(정수 id 대신).
- **#17 미확인 인용 수**: 출현 수로 센다.
- **#20 path 입력**: idea_add_conversation이 path도 받는다.
- **#22 분리 실패 구간**: 저장하지 않고 리포트만 한다.
- **#25 합성 데이터 격리**: `synthetic` 사용자로 옮겼다.

### 5) 막힌 것, 넘어간 것, 아침에 할 일(순서대로)
- 막혀서 넘어간 단계는 없다.
- 넘어간 것
  - 실데이터 검증 전부(fixtures 없음)
  - 임베딩 API 실제 호출(지시대로 하지 않음)
  - Desktop 재시작(손대지 않기로 했으므로, 지금 떠 있는 서버는 03:33의 옛 코드다)
- **아침에 사용자가 할 일**
  1. `fixtures/`에 원고 docx(파일명에 "닿으려는_종")와 대화 md 3개를 넣는다.
  2. Claude Desktop을 **완전히 종료한 뒤 다시 실행**한다. 그래야 새 서버(18개 도구)가 뜬다.
     - 그 전에 프로젝트 폴더에서 `uv sync`를 한 번 돌리면 의존성이 정리된다. Desktop이 꺼져 있어야 성공한다.
  3. 원고 임포트(또는 Desktop에서 book_import):
     `PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus import fixtures/<원고>.docx --project-id book > data/book-import-report.md`
     - 리포트에서 확인할 것: 장 35±2, 부 8, 코멘트 80건 이상, refs 200건 이상, 분할 못 한 구간, 목차로 버린 줄, 매핑표, 코멘트 분류 표.
  4. 대화 기록: `… -m magus conversation fixtures/대화_전체_기록.md`
     - me 96 / ai 96이 나와야 한다. 나머지 두 md도 같은 명령으로 넣는다.
  5. 결과가 어긋나면(장 분할, 코멘트 분류, 참고문헌 파싱, 대화 마커) 알려 준다. 실원고를 보고 보정하고, 같은 project_id로 다시 할 때는 `--replace`를 쓴다(기존 것은 trash/로 간다).
  6. 아래 검토 대기 결정 26건을 확인한다.
  7. (선택) 임베딩: Desktop 설정 env에 `EMBEDDINGS=voyage`와 `VOYAGE_API_KEY`를 넣는다.

### 6) Desktop 연결 판정
- `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log` 기준으로 **연결 성공**.
- 2026-10-03 03:33:49에 `Server started and connected successfully`가 찍혔고, initialize·tools/list·prompts/list·resources/list가 모두 응답했다.
- 도구 호출(tools/call) 기록은 아직 없다.
- 그 서버는 03:33 시점의 옛 코드(1단계 검토 반영 무렵)로 떠 있다. 재시작해야 18개 도구가 보인다.

## 1. 지금 바로 할 일

- **대기: fixtures 투입과 Desktop 재시작(사용자).** 위 "아침에 사용자가 할 일" 1~2.
- fixtures가 들어오면 실원고로 2단계(임포트)부터 돌린다. 리포트·매핑표·코멘트 분류를 사용자와 함께 확인하고, 그다음 4·5단계(ref_check 전 장 집계, 대화 96/96)를 돌린다.

## 2. 현재 단계

**1~7단계 구현 완료**(태그 `step7`). 실데이터 검증은 대기 중이다(fixtures 없음).

## 3. 단계별 체크리스트

- [x] **1단계 뼈대** — 2026-10-03, `step1`
- [x] **2단계 book_import** — 2026-10-03, `step2`, 합성 fixture
  - 산출물: `src/magus/book/{docx_reader,pdf_reader,importer}.py`, `src/magus/melchior/bibliography.py`, `src/magus/synthetic.py`, `tests/test_{import,bibliography}.py`
- [x] **3단계** decide / issue_add / issue_close / export — 2026-10-03, `step3`
  - 산출물: `src/magus/book/export.py`, `tests/test_book_tools.py`
- [x] **4단계** ref_add / ref_search / ref_check + 게이트, 추출기 보강, 이슈 ↔ refs — 2026-10-03, `step4`, 합성 fixture
  - 산출물: `src/magus/melchior/{citations,check,refs,tools}.py`, `src/magus/search.py`, `tests/test_{refs,citations}.py`
- [x] **5단계** idea_* — 2026-10-03, `step5`, 합성 fixture
  - 산출물: `src/magus/casper/{conversation,tools}.py`, `tests/test_casper.py`
- [x] **6단계** style_* — 2026-10-03, `step6`
  - 산출물: `src/magus/balthasar/{style,tools}.py`, `tests/test_balthasar.py`
- [x] **7단계** 하이브리드 검색, provider 스텁, instructions, README, demo — 2026-10-03, `step7`
  - 산출물: `src/magus/{embeddings,search,textindex}.py`, `tests/test_search.py`, `README.md`
- [ ] **실데이터 검증**: 완료 기준 중 원고 임포트 수치와 대화 96/96(실파일)

## 4. 검토 대기 결정

야간에 혼자 고른 것들이다. 형식: 선택 / 대안 / 이유.

**2단계 — 임포트**

1. **첫 장 제목 앞의 글(표지·목차·머리말)**
   - 선택: 장으로 만들지 않고 `original/unsplit.md`에 보관하고 리포트한다.
   - 대안: `ch-00 머리말`로 만든다.
   - 이유: 장 수 기준을 흐리지 않고, 사람이 보고 결정할 수 있다.
2. **목차와 본문에 같은 장 제목이 있을 때**
   - 선택: 뒤따르는 본문이 가장 긴 것을 진짜로 본다.
   - 대안: 마지막 것을 고른다.
   - 이유: 목차 위치·서식과 상관없이 동작한다.
3. **코멘트 이슈 본문**
   - 선택: `코멘트 + — 원문: “앵커 120자”`.
   - 대안: 코멘트만 넣는다.
   - 이유: "확인 필요"만으로는 무엇을 확인할지 알 수 없다.
4. **파싱 실패한 참고문헌 줄**
   - 선택: `raw-<해시>` key의 unverified ref로 보관한다(refs 수에 포함).
   - 대안: 리포트에만 남긴다.
   - 이유: 아무것도 잃지 않는다.
5. **같은 목록 안 key 충돌**
   - 선택: 뒤의 것에 `-2`를 붙인다. 연도 접미사(2012a)가 있으면 key에 넣는다.
   - 대안: 덮어쓴다.
6. **refs 재임포트**
   - 선택: 이미 있는 key는 건드리지 않는다.
   - 대안: 갱신한다.
   - 이유: 사람 소유 책장이고, verified를 덮어쓰지 않아야 한다.
7. **replace=True**
   - 선택: 기존 프로젝트를 `trash/`로 옮긴다.
   - 대안: 삭제한다.
8. **book_import 입력**
   - 선택: 로컬 파일 경로.
   - 대안: 업로드.
   - 이유: P0는 로컬이다. P1(HTTP)에서는 업로드로 바꿔야 한다.
9. **장 안의 소제목(Heading 스타일)**
   - 선택: `## 소제목`으로 바꾼다.
10. **FTS 한국어 토큰화**
    - 선택: 한글 bigram 사전 토큰화.
    - 대안: trigram, 형태소 분석기.
    - 이유: 2글자 이름을 찾고, 미등록 학자 이름을 쪼개지 않는다.
11. **합성 fixture 위치**
    - 선택: `data/synthetic-fixtures/`(gitignore). 생성기는 `src/magus/synthetic.py`.
    - 대안: `fixtures/`에 둔다.
    - 이유: `fixtures/`는 실파일 전용이고 읽기만 한다.

**3단계 — export·이슈**

12. **book_export의 path**
    - 선택: 파일 이름만 받는다. 저장 위치는 `exports/`.
    - 대안: 임의 절대 경로.
    - 이유: SaaS 전환 때 서버 파일 시스템을 노출하지 않는다.
13. **book_issue_add의 origin 인자**
    - 선택: user|agent, 기본값 user.
    - 이유: outline에서 에이전트가 남긴 것을 구분한다.
14. **export 제목 단계**
    - 선택: 부 H1, 장 H2, 소제목 H3. 부가 없으면 장이 H1이다.

**4단계 — 문헌**

15. **ref_add는 발췌가 하나 이상 있어야 받는다**
    - 대안: bib만으로 verified를 허용한다.
    - 이유: "읽은 것만 verified".
16. **이슈의 ref_id에 정식 ref key를 쓴다**
    - 대안: refs.id 정수.
    - 이유: 인덱스 행 id는 재생성되면 바뀐다.
17. **장별 미확인 인용 수 = verified가 아닌 인용의 출현 수**(`[출처 필요]`는 따로 셈)
    - 대안: 서로 다른 문헌 수.
18. **ref_search의 scope 기본값 = both**
    - 이유: 발췌를 먼저 보여 주고 전문을 뒤에 붙인다.
19. **한글 저자 조사**
    - 선택: 조사를 뗀 key를 대표로 쓰고, 원형을 첫 후보로 둔다.
    - 이유: "갤러는"을 해석하면서 "카를로"를 망가뜨리지 않는다.

**5단계 — 영감**

20. **idea_add_conversation이 path도 받는다**
    - 대안: markdown만 받는다.
    - 이유: 실제 기록이 길다.
21. **연속된 AI 발화**
    - 선택: 합치지 않고 둘 다 같은 사용자 발화를 부모로 삼는다(리포트에 참고로 남김).
22. **분리 실패 구간**(서문 본문, 빈 마커, 고아 AI 발화)
    - 선택: 저장하지 않고 리포트만 한다.
    - 대안: author=me로 저장한다.
    - 이유: 누가 말했는지 모르는 글을 사용자의 주장으로 저장하지 않는다.

**6·7단계 — 문체·검색**

23. **tags 검증**
    - 선택: 여섯 키를 모두 필수로 한다(장치만 빈 목록 허용). 모르는 키는 거부한다.
24. **FTS 색인도 reason + tags만**
    - 스펙은 임베딩 대상만 정했다. FTS도 같은 기준으로 맞췄다.
    - 이유: 구절의 주제어가 섞이면 문체가 아니라 주제가 검색된다.

**운영**

25. **합성 데이터 격리**
    - 선택: `data/users/default` 전체를 `data/users/synthetic`으로 옮기고, `default`에는 데모만 새로 만들었다.
    - 대안: default에 그대로 둔다.
    - 이유: 아침 실원고 임포트 때 합성 refs(가짜 서지)가 "이미 있음"으로 진짜 서지를 막는다.
    - 합성 데이터를 Desktop에서 보려면 설정 env의 `USER_ID`를 `synthetic`으로 바꾼다.
26. **임베딩 키가 없을 때**
    - 선택: 경고 후 FTS로 동작한다.
    - 대안: 서버 시작 실패.
    - 이유: Desktop에서 서버가 아예 안 뜨는 것보다 낫다. API 호출 실패도 FTS로 계속한다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음)
  - **Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 실패한다**(os error 32). 그때는 `uv add --no-sync`와 `uv pip install`을 쓴다. 테스트는 `.venv/Scripts/python -m pytest -q -p no:cacheprovider`.
- **Python**: 3.12(.venv).
- **MCP SDK**: mcp 2.2.0.
- **의존성**: python-docx 1.2.0, pymupdf 1.28.2(`import pymupdf`), pypandoc-binary 1.17(pandoc 3.9), numpy 2.5.3, lxml. ruff 0.16(개발용, uv pip로만 설치, pyproject에는 없음).
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=4`.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` (백업 `.bak-20261003-031857`)
  - 로그: `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`
- **데이터**
  - `data/users/default`: 데모 프로젝트 + 책장 표본(생각 4, 문체 2).
  - `data/users/synthetic`: 합성 프로젝트 synth, 데모, refs 30, 대화 228건 등.
  - `data/synthetic-fixtures/`: 합성 원본과 리포트.
- **명령**(Bash, 프로젝트 루트에서 실행)
  ```
  .venv/Scripts/python -m pytest -q -p no:cacheprovider
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus import <docx|pdf> --project-id <id> [--replace] [--synthetic]
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus conversation <md>
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus synth data/synthetic-fixtures
  PYTHONIOENCODING=utf-8 DATA_DIR=./data .venv/Scripts/python -m magus reindex
  PYTHONIOENCODING=utf-8 DATA_DIR=./data USER_ID=synthetic .venv/Scripts/python -m magus …   # 합성 사용자
  ```
- **git**: master에 바로 커밋하고, 단계가 끝나면 태그(`step1`~`step7`)를 단다. `fixtures/`와 `data/`는 gitignore.

## 6. 마지막 세션 요약

**2026-10-03 야간(04:12~04:50, 사용자 부재)**
- 2~7단계를 모두 구현하고 커밋·태그했다.
- 실데이터가 없어서 합성 fixture 생성기를 만들어 2·4·5단계를 검증했다.
- 완료 기준 중 코드로 확인할 수 있는 것은 모두 테스트로 고정했다: ref_check 이동, 대화 96/96(합성), write → versions → outline, EMBEDDINGS=none으로 전 도구 호출, 다른 user_id 빈 결과, outline 3,000토큰 이하.
- 남긴 것: 실원고 검증, Desktop 재시작, 검토 대기 결정 26건.

## 7. 알려진 문제

- **실원고 미검증**: 장 제목 표기, 코멘트 앵커, 참고문헌 형식, 대화 마커가 합성과 다를 수 있다. 특히 다음을 실파일로 보정해야 한다.
  - 각주형 인용(¹, [1])은 지원하지 않는다.
  - 한글 저자는 2~8자만 받는다.
  - 연도가 맨 끝에 오는 참고문헌은 근사 파싱이다.
- **PDF 폴백의 한계**: 앵커는 바로 앞 블록으로 근사한다. 그림·표·수식은 구분하지 못한다.
- **Desktop 서버는 03:33의 옛 코드다**: 재시작해야 새 도구가 보인다.
- **장별 미확인 인용 수·임베딩은 파생값이다**: 인덱스를 다시 만든 직후에는 비거나 0이다. 서버 시작, `magus reindex`, 검색이 다시 채운다.
- **파일을 직접 지우거나 고친 뒤에는 `magus reindex`가 필요하다**: 그 전에는 인덱스가 옛 상태를 보여 준다(데모를 다시 만들 때 실제로 겪음).
- **번호 충돌 가능성**: 결정·미해결 번호는 프로세스 안의 락으로만 보호된다. CLI와 서버가 동시에 쓰면 충돌할 수 있다(P0에서는 허용).
- **토큰 추정은 휴리스틱**: 한글 1자를 1토큰으로 센다(보수적).
- **임베딩 API 실제 호출은 검증하지 않았다**: 요청 모양만 테스트했다.
