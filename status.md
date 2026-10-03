# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 15:05 KST — P0 마무리 보완 완료(태그 없음). 사용자 Desktop 테스트 결과를 기다린다.

## 0. 최근 보고 (P0 마무리 보완)

- **README 시험 문장을 정정했다**: 사용자가 준 세 문장(book_outline, 제12장 미확인 인용, 제31장 요약)에, 지난번에 내가 고른 "사실·수치 메모만 보기"를 4번으로 남겼다. 기대 결과는 실데이터에서 뽑았다.
- **outline 머리줄**
  - 미확인 문헌을 책 전체 고유 수로 바꿨다: `35장 + 서장·맺음·부록 1~3 · 8부 · 249,065자 · 미확인 문헌 296편 · 열린 미해결 86`. 보고서 1절의 296편과 같다.
  - 장별 미확인 문헌 key를 파생값으로 인덱스에 두고(SCHEMA_VERSION 7), outline은 그 합집합을 센다.
- **ref_add 리허설 마무리**: `fixtures/papers/`를 만들었다(.gitignore의 `fixtures/`에 포함). README에 PDF를 두는 곳과 Desktop에서 쓸 문장을 그대로 적었다.
- **CLAUDE.md 규칙 보강**
  - "프로젝트 폴더 밖"에 환경이 알려 준 경로도 포함한다.
  - 지시문의 참조를 못 찾으면 "불명: …"으로 적고, 내 판단으로 진행한 뒤 보고한다.
- 지난 라운드의 불명 1건("위 세 가지 테스트 프롬프트")은 사용자가 정정해 해소됐다. 이번 라운드에는 불명이 없다.

## 1. 지금 바로 할 일

- **대기: 사용자 Desktop 테스트 결과(사용자).** 결과가 올 때까지 새 기능을 만들지 않는다.
  - 사용자가 할 일: Desktop을 완전히 종료한 뒤 다시 실행한다. README "첫 실행 확인"의 시험 문장 네 개와 ref_add 시연을 해 본다. PDF는 `fixtures/papers/`에 둔다.
- 대기: 저자 보고서 답변(연도 불일치 2, 참고문헌에만 있는 4, 음역 추정 7, Acemoglu 2001)(사용자).
- 대기: 아래 "4. 검토 대기 결정" 35건(사용자).
- 결과가 오면: 문제마다 재현 테스트부터 만들고 고친다.

## 2. 현재 단계

**P0 완료 + 첫 보고서 + 마무리 보완**(`step1`~`step7`, `p0-realdata`, `p0-report1`, 이후 보완 커밋은 태그 없음). 사용자 Desktop 테스트를 기다린다.

## 3. 단계별 체크리스트

- [x] 1~7단계 — 2026-10-03, `step1`~`step7`
- [x] 실데이터 검증·보정 — 2026-10-03, `p0-realdata`
- [x] P0 마무리 — 2026-10-03, `p0-report1`
  - 코멘트 kind `fact`, 비인용 용어 파일과 `magus terms`, `magus author-report`, `docs/reports/2026-10-03-인용-점검.{md,docx}`, `src/magus/paths.py`(FILES_DIR), ref_add 제목 매칭
- [x] **P0 마무리 보완** — 2026-10-03, 태그 없음
  - `src/magus/book/outline.py`(머리줄: 장 수 표기, 책 전체 고유 미확인 문헌)
  - `src/magus/store/{schema,base,local}.py`(chapters.unverified_cite_keys, SCHEMA_VERSION 7), `src/magus/melchior/check.py`
  - README "첫 실행 확인"(시험 문장 4개, ref_add 문장), `fixtures/papers/`
  - `tests/test_outline.py::test_outline_header_counts_unique_docs_across_book`
- [ ] Desktop 실사용 피드백 반영(사용자 대기)

## 4. 검토 대기 결정

**확정됨(사용자 답변)**
- 2026-10-03 오전: #1, #15, #16, #17(고유 문헌 수로 변경), #20, #22, #25.
- 2026-10-03 오후(마무리 보완 지시): #41은 **변경**됐다. outline 머리줄을 책 전체 고유 수로 바꿨다. #42는 사용자가 정정했다. 사용자가 준 세 문장에 내가 고른 것은 4번으로 남겼다.

**대기 35건**: 2~14, 18, 19, 21, 23, 24, 26, 27~40, 43, 44
- 표는 마지막 보고 메시지와 일지 "P0 마무리 보완" 절에 있다.
- 원문 근거
  - #2~26: `git show step7:status.md`의 4절
  - #27~35: `git show p0-realdata:status.md`의 4절
  - #36~40: `git show p0-report1:status.md`의 4절
- 실원고 라운드에서 바뀐 것
  - #2: "제목 서식이 있는 것 우선"을 앞에 더했다.
  - #19: 조사 목록을 는·를 등으로 줄였다.

**이번에 새로 고른 것** (선택 / 대안 / 이유)

43. **책 전체 고유 미확인 수를 위해 장별 미확인 문헌 key를 파생값으로 인덱스에 둔다**(`chapters.unverified_cite_keys`, SCHEMA_VERSION 7)
    - 대안: outline을 부를 때마다 모든 장을 다시 검사한다.
    - 이유: outline은 모든 작업의 시작이라 싸야 한다. 장별 수를 계산할 때 key도 이미 나온다. 파생값이므로 파일에는 두지 않는다.
44. **outline 장 수를 `35장 + 서장·맺음·부록 1~3`으로 적는다**(이전: `40장`)
    - 대안: 전체 장 수만 적는다.
    - 이유: 책은 "35장 8부"로 불린다. 40장은 번호 없는 장 5개가 섞인 수라서 헷갈린다. 시험 문장 1의 기대 결과와 같은 표현이다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음). Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 실패한다. 그때는 `uv add --no-sync`와 `uv pip install`을 쓴다.
- **Python** 3.12(.venv). **MCP SDK** mcp 2.2.0.
- **의존성**: python-docx 1.2.0, pymupdf 1.28.2, pypandoc-binary 1.17(pandoc 3.9), numpy 2.5.3, lxml. ruff 0.16(개발용, `--select F,B`로 점검).
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=7`. 버전이 바뀌면 처음 열 때 자동으로 다시 만들고, 서버가 시작할 때 파생값을 다시 계산한다.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`(USER_ID=default, DATA_DIR=C:\project_2026\Magus\data → FILES_DIR 기본 C:\project_2026\Magus)
  - 로그: `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`. 시작 줄에 files_root가 찍힌다.
  - 위 두 경로는 프로젝트 폴더 밖이다. 사용자가 이 세션에서 경로를 적어 지시할 때만 읽는다.
- **데이터 사용자**
  - `default`: 실원고 `book`(비인용 용어 5개), refs 299, 실대화 452발화, 문체 0
  - `demo`: 데모 프로젝트·표본
  - `synthetic`: 합성 synth
- **fixtures**: `fixtures/261002-닿으려는_종_전면개정_그림추가.pdf`, 대화 md 4개, `fixtures/papers/`(비어 있음. 사용자가 논문 PDF를 둔다).
- **명령**(Bash, 프로젝트 루트에서 실행. 콘솔 한글은 `PYTHONIOENCODING=utf-8`)
  ```
  .venv/Scripts/python -m pytest -q -p no:cacheprovider
  .venv/Scripts/python -m ruff check --select F,B src tests
  DATA_DIR=./data .venv/Scripts/python -m magus import fixtures/<원고>.pdf --project-id book --title "닿으려는 종" --replace
  DATA_DIR=./data .venv/Scripts/python -m magus cite-report --project-id book > data/realdata/cite-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus author-report --project-id book --out docs/reports/<날짜>-인용-점검.md
  DATA_DIR=./data .venv/Scripts/python -m magus terms --project-id book [--add …] [--remove …]
  DATA_DIR=./data .venv/Scripts/python -m magus reindex
  ```
- **git**
  - master에 바로 커밋하고, 단계가 끝나면 태그를 단다. 실험은 브랜치에서 하고 squash merge한다.
  - 태그: `step1`~`step7`, `p0-realdata`, `p0-report1`. 마무리 보완 커밋에는 태그를 달지 않았다(지시).
  - `fixtures/`와 `data/`는 gitignore. `docs/reports/`는 커밋한다.

## 6. 마지막 세션 요약

**2026-10-03 오후(14:40~15:05)**
- README 시험 문장을 사용자가 준 세 개로 바꾸고, 사실·수치 메모 보기를 4번으로 남겼다. 기대 결과는 실데이터에서 뽑았다.
- outline 머리줄을 책 전체 고유 미확인 문헌 수(296)로 바꿨다. 보고서 1절과 같은지 테스트로 고정했다.
- `fixtures/papers/`를 만들고, README에 PDF 위치와 Desktop 문장을 적었다.
- CLAUDE.md 규칙을 보강했다(환경이 알려 준 경로도 밖, 불명 처리).
- 테스트 151개 통과, ruff(F·B) 통과. 커밋했다(태그 없음).
- 남긴 것: Desktop 테스트 결과 대기. 그때까지 새 기능을 만들지 않는다.

## 7. 알려진 문제 — 실원고에서 아직 안 맞는 것

- **표**: 칸 구분 없이 한 문단으로 들어온다(27장 등). 표 안의 도시 설립 연도는 비인용 용어 파일로 걸렀다(그대로 둠, docx 재임포트 때 다시 본다).
- **수식·그림**: 수식은 텍스트 그대로(`g_Y ≈ g_N + g_y`), 그림 10개는 `[그림 N]` 자리표시자다(그대로 둠).
- **코멘트 앵커**: PDF에서는 말풍선 높이의 문단 단위로 근사한다. 앵커에 인용이 하나뿐이면 그 문헌으로 잇기 때문에, 사실·수치 요청 일부(I81·I82 인구 수치)가 citation(buckley2010)으로 분류된다.
- **원고 쪽 불일치**(보고서 2·3절, 저자 답변 대기)
  - `Brook(2008)` vs 참고문헌 Brook 2010, `Wiessner(2014)` vs 참고문헌 Wiessner 1982. I12(wiessner2014)는 refs에 연결되지 않는다.
  - 참고문헌에만 있는 4건(Graunt, Lattimore, Lee, Nordhaus). 본문에는 이름만 나온다.
  - 음역 추정 7건, 케인스(1930) a/b, Acemoglu 2001 두 편.
- **참고문헌 파싱 실패 1**: `張楠(장남). (명대). 『神峰通考』`(숫자 연도 없음, raw로 보관, 그대로 둠).
- **Desktop 실사용 미검증**: 서버 쪽 경로 흐름은 테스트와 리허설로 확인했지만 Desktop에서 실제로 부른 기록은 아직 없다. 시험 문장 3(제31장 요약)은 Claude가 다른 장을 더 읽지 않는지 보는 것이라 Desktop에서만 확인할 수 있다.
- **보고서 쪽수**: Word·LibreOffice가 없어 글자폭으로 추정했다(약 2.3쪽). Word에서 열어 확인이 필요하다.
- 이전부터 있던 것: 번호 충돌 가능성(멀티 프로세스), 직접 수정 뒤 reindex 필요, 토큰 추정 휴리스틱, 임베딩 API 실제 호출 미검증.
