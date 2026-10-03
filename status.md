# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 16:00 KST — 검토 대기 결정 35건 확정·보완 반영(태그 없음). 사용자 Desktop 테스트 결과를 기다린다.

## 0. 최근 보고 (검토 결정 35건 반영)

- **35건을 모두 확정했다.** 승인 25건은 그대로 두었다. 보완 10건(#5 #6 #11 #24 #28 #29 #31 #33 #36 #43)은 고친 뒤 확정했다.
- 실데이터에 미친 영향(재임포트 후)
  - 코멘트: citation 44 · fact **40** · general **2**. I46 `선하이정(1835)`이 fact로 바뀌었다(#36).
  - 미확인 문헌: **297편**(이전 296). 35장 `케인스(1930)`을 이제 1930a에 잇지 않고, 후보 둘을 보이는 문헌 1편으로 따로 센다(#31).
  - 참고문헌: 중복 서지 0건, 기존 서지와 다름 0건(#5·#6).
  - outline 머리줄: `… · 미확인 문헌 297편 · 미연결 0 · 열린 미해결 86`(#29).
- 저자 보고서(`docs/reports/2026-10-03-인용-점검.{md,docx}`)를 생성기로 다시 만들었다. outline과 1절 수를 맞추려는 것이다.
  - 바뀐 곳은 세 줄이다: 1절 296→297편, 5절 39→40건, 16장에 I46 추가.
  - 이전 판은 `git show p0-report1:docs/reports/2026-10-03-인용-점검.md`에 있다.

## 1. 지금 바로 할 일

- **대기: 사용자 Desktop 테스트 결과(사용자).** 결과가 올 때까지 새 기능을 만들지 않는다.
  - 사용자가 할 일: Desktop을 완전히 종료한 뒤 다시 실행한다. README "첫 실행 확인"의 시험 문장 네 개와 ref_add 시연을 해 본다. PDF는 `fixtures/papers/`에 둔다.
- 대기: 저자 보고서 답변(사용자). 답이 오면 음역 추정·a/b는 `magus alias <key> <표기>`로 넣는다.
- 결과가 오면: 문제마다 재현 테스트부터 만들고 고친다.

## 2. 현재 단계

**P0 완료 + 첫 보고서 + 마무리 보완 + 검토 결정 반영**(`step1`~`step7`, `p0-realdata`, `p0-report1`, 이후 커밋은 태그 없음). 사용자 Desktop 테스트를 기다린다.

## 3. 단계별 체크리스트

- [x] 1~7단계 — 2026-10-03, `step1`~`step7`
- [x] 실데이터 검증·보정 — 2026-10-03, `p0-realdata`
- [x] P0 마무리 — 2026-10-03, `p0-report1`
- [x] P0 마무리 보완 — 2026-10-03(outline 고유 수, README 시험 문장, fixtures/papers/)
- [x] **검토 결정 35건 반영** — 2026-10-03, 태그 없음
  - `src/magus/melchior/bibliography.py`(중복 서지, 기존 서지와 다름)
  - `src/magus/book/comments.py`(#36 fact)
  - `src/magus/melchior/check.py`(a/b 후보, uncertain key), `src/magus/store/*`(uncertain_cite_keys, SCHEMA_VERSION 8, 문체 fts_extra)
  - `src/magus/melchior/refs.py`(add_alias), `src/magus/cli.py`(`magus alias`), `src/magus/book/outline.py`(미연결)
  - `src/magus/melchior/{report,author_report}.py`(후보 표시)
  - `tests/fixtures/synthetic/`(합성 fixture 커밋, .gitignore를 `/fixtures/`로)
  - 테스트: test_bibliography·test_balthasar·test_cli·test_outline·test_server·test_import·test_realdata_shapes 추가분
- [ ] Desktop 실사용 피드백 반영(사용자 대기)

## 4. 검토 대기 결정

**없음.** #1~#44 모두 확정됐다.

**확정 기록**
- 2026-10-03 오전 답변: #1, #15, #16, #17(고유 문헌 수로 변경), #20, #22, #25.
- 2026-10-03 마무리 보완 지시: #41(변경: outline은 책 전체 고유 수), #42(사용자가 정정).
- 2026-10-03 35건 답변
  - 승인(그대로): #2 #3 #4 #7 #8 #9 #10 #12 #13 #14 #18 #19 #21 #23 #26 #27 #30 #32 #34 #35 #37 #38 #39 #40 #44
  - 보완 후 확정
    - #5: key 충돌 -2는 유지한다. 같은 문헌이 두 번이면 "중복 서지 N건"으로 따로 리포트한다.
    - #6: 기존 key는 보존한다. 새 목록의 제목·연도가 다르면 "기존 서지와 다름" 목록을 남긴다(갱신하지 않음).
    - #11: 합성 fixture는 `tests/fixtures/synthetic/`에 두고 커밋한다. 실데이터 `fixtures/`와는 분리한다.
    - #24: 문체 키워드 색인에 work도 넣는다. 임베딩 대상은 reason + tags 그대로다.
    - #28: 추정은 저장하지 않는다. 확정은 `magus alias <key> <표기>`로 한다.
    - #29: uncertain은 미확인 수에서 빼되, outline "미연결 N"과 ref_check 별도 목록으로 보인다.
    - #31: a/b가 모호하면 잇지 않는다. 후보 둘을 보이고 상태는 unverified다.
    - #33: Downloads 복사 결과는 수용한다. 규칙은 "사용자에게 요청하고 멈춤"(CLAUDE.md에 이미 있음).
    - #36: 비인용 용어만 걸린 출처 확인 코멘트도 fact다. general은 확인 요청이 아닌 코멘트에만 쓴다.
    - #43: 캐시는 유지한다. ref_add로 문헌 상태가 바뀌면 즉시 다시 계산한다.
      - 지금은 refs가 바뀔 때 모든 장을 다시 계산한다. 실원고 0.3초이고, 그 문헌이 나오는 장을 포함한다.
      - ref_add 직후 outline 수가 줄어드는지 테스트로 고정했다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음). Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 실패한다. 그때는 `uv add --no-sync`와 `uv pip install`을 쓴다.
- **Python** 3.12(.venv). **MCP SDK** mcp 2.2.0.
- **의존성**: python-docx 1.2.0, pymupdf 1.28.2, pypandoc-binary 1.17(pandoc 3.9), numpy 2.5.3, lxml. ruff 0.16(개발용, `--select F,B`로 점검).
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=8`. 버전이 바뀌면 처음 열 때 자동으로 다시 만들고, 서버가 시작할 때 파생값을 다시 계산한다.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`(USER_ID=default, DATA_DIR=C:\project_2026\Magus\data → FILES_DIR 기본 C:\project_2026\Magus)
  - 로그: `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`. 시작 줄에 files_root가 찍힌다.
  - 위 두 경로는 프로젝트 폴더 밖이다. 사용자가 이 세션에서 경로를 적어 지시할 때만 읽는다.
- **데이터 사용자**
  - `default`: 실원고 `book`(비인용 용어 5개), refs 299, 실대화 452발화, 문체 0
  - `demo`: 데모 프로젝트·표본
  - `synthetic`: 합성 synth
- **fixtures**
  - 실데이터(gitignore): `fixtures/261002-닿으려는_종_전면개정_그림추가.pdf`, 대화 md 4개, `fixtures/papers/`(비어 있음, 사용자가 논문 PDF를 둔다).
  - 합성(커밋): `tests/fixtures/synthetic/`(원고 docx·pdf, 대화 md 3개, 야간 작업 리포트).
- **명령**(Bash, 프로젝트 루트에서 실행. 콘솔 한글은 `PYTHONIOENCODING=utf-8`)
  ```
  .venv/Scripts/python -m pytest -q -p no:cacheprovider
  .venv/Scripts/python -m ruff check --select F,B src tests
  DATA_DIR=./data .venv/Scripts/python -m magus import fixtures/<원고>.pdf --project-id book --title "닿으려는 종" --replace > data/realdata/import-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus cite-report --project-id book > data/realdata/cite-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus author-report --project-id book --out docs/reports/<날짜>-인용-점검.md
  DATA_DIR=./data .venv/Scripts/python -m magus terms --project-id book [--add …] [--remove …]
  DATA_DIR=./data .venv/Scripts/python -m magus alias <key> <표기>
  DATA_DIR=./data .venv/Scripts/python -m magus reindex
  ```
- **git**
  - master에 바로 커밋하고, 단계가 끝나면 태그를 단다. 실험은 브랜치에서 하고 squash merge한다.
  - 태그: `step1`~`step7`, `p0-realdata`, `p0-report1`. 그 뒤 커밋 두 개(마무리 보완, 결정 반영)에는 태그를 달지 않았다(지시).
  - `/fixtures/`(루트)와 `data/`는 gitignore. `tests/fixtures/`와 `docs/reports/`는 커밋한다.

## 6. 마지막 세션 요약

**2026-10-03 오후(15:15~16:00)**
- 검토 결정 35건 답변을 반영했다. 승인은 25건이고, 보완 10건은 고친 뒤 확정했다.
- 참고문헌 리포트에 중복 서지와 기존 서지와 다른 점을 넣었다. a/b 모호는 잇지 않고 후보로 보인다. 미연결을 표시하고, `magus alias`와 문체 work 색인을 넣었다. 비인용 용어만 걸린 확인 요청은 fact로 바꿨고, 합성 fixture를 커밋했다.
- 실원고를 다시 임포트하고 cite-report와 저자 보고서를 다시 만들었다(297편, fact 40).
- 테스트 157개 통과, ruff(F·B) 통과. 커밋했다(태그 없음).
- 남긴 것: Desktop 테스트 결과 대기. 그때까지 새 기능을 만들지 않는다.

## 7. 알려진 문제 — 실원고에서 아직 안 맞는 것

- **표**: 칸 구분 없이 한 문단으로 들어온다(27장 등). 표 안의 도시 설립 연도는 비인용 용어 파일로 걸렀다(그대로 둠, docx 재임포트 때 다시 본다).
- **수식·그림**: 수식은 텍스트 그대로(`g_Y ≈ g_N + g_y`), 그림 10개는 `[그림 N]` 자리표시자다(그대로 둠).
- **코멘트 앵커**: PDF에서는 말풍선 높이의 문단 단위로 근사한다. 앵커에 인용이 하나뿐이면 그 문헌으로 잇기 때문에, 사실·수치 요청 일부(I81·I82 인구 수치)가 citation(buckley2010)으로 분류된다(#30 승인).
- **원고 쪽 불일치**(보고서 2·3절, 저자 답변 대기)
  - `Brook(2008)` vs 참고문헌 Brook 2010, `Wiessner(2014)` vs 참고문헌 Wiessner 1982. I12(wiessner2014)는 refs에 연결되지 않는다.
  - 참고문헌에만 있는 4건(Graunt, Lattimore, Lee, Nordhaus). 본문에는 이름만 나온다.
  - 음역 추정 6건(하야시·후닝·김성은·크레머·모리스·넌). 케인스(1930)는 a/b 후보 둘이고 잇지 않았다. Acemoglu 2001 두 편.
- **참고문헌 파싱 실패 1**: `張楠(장남). (명대). 『神峰通考』`(숫자 연도 없음, raw로 보관, 그대로 둠).
- **Desktop 실사용 미검증**: 서버 쪽 경로 흐름은 테스트와 리허설로 확인했지만 Desktop에서 실제로 부른 기록은 아직 없다. 시험 문장 3(제31장 요약)은 Claude가 다른 장을 더 읽지 않는지 보는 것이라 Desktop에서만 확인할 수 있다.
- **보고서 쪽수**: Word·LibreOffice가 없어 글자폭으로 추정했다(약 2.3쪽). Word에서 열어 확인이 필요하다.
- 이전부터 있던 것: 번호 충돌 가능성(멀티 프로세스), 직접 수정 뒤 reindex 필요, 토큰 추정 휴리스틱, 임베딩 API 실제 호출 미검증.
