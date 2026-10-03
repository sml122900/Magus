# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 14:35 KST — P0 마무리 라운드 완료(태그 `p0-report1`)

## 0. 최근 보고 (P0 마무리 라운드)

- **저자용 첫 보고서**: [docs/reports/2026-10-03-인용-점검.md](docs/reports/2026-10-03-인용-점검.md)와 같은 내용의 `.docx`(추정 약 2.3쪽).
  - "원고 전체 인용 397곳, 문헌 296편, 원문 대조 완료 0편."
  - `magus author-report`로 다시 만들 수 있다. default 사용자의 book 프로젝트만 읽는다.
- **코멘트 kind 3분할**: citation 44(refs 연결 43) · fact 39 · general 3.
  - 비인용 용어 파일 `book/non_citation_terms.txt`에 선하이정·마닐라·유조프카·푸둥·모스크바 회사를 넣었다. I46은 general이다.
  - 분류표 86건은 일지 "P0 마무리 라운드" 절에 있다.
- **ref_add 시연 경로**: 상대 경로를 프로젝트 폴더(`FILES_DIR`, 기본은 `DATA_DIR`의 부모) 기준으로 풀도록 고쳤다.
  - 저자·연도 없이 파일만 주면 PDF 첫머리의 제목으로 참고문헌을 찾는다.
  - 다른 작업 폴더에서 띄운 하위 프로세스 테스트와 실데이터 사본 리허설로 확인했다. README "첫 실행 확인" 절.
- CLAUDE.md 규칙 추가: 프로젝트 폴더 밖의 파일은 사용자가 경로를 명시해 지시했을 때만 읽는다.

## 1. 지금 바로 할 일

- **대기(사용자)**
  - 보고서를 아버님께 전달하고 답을 받는다. 연도 불일치 2건, 참고문헌에만 있는 4건, 음역 추정 7건, Acemoglu 2001 두 편.
  - Claude Desktop을 **완전히 종료한 뒤 다시 실행**하고, README "첫 실행 확인"의 시험 문장 세 개를 해 본다.
  - `fixtures/papers/`에 실제 논문 PDF 하나를 두고 ref_add 시연을 해 본다. 지금 그 폴더는 없다.
  - "위 세 가지 테스트 프롬프트"의 원문이 따로 있었다면 알려 준다. 지시문과 이전 대화에서 찾지 못해 세 개를 골랐다(#42).
  - 아래 "4. 검토 대기 결정"을 확인한다(이전 28건 + 이번 7건).
- 답이 오면 할 일
  - 음역 추정이 맞으면 해당 ref에 aliases를 넣는다(추정 표시가 사라진다).
  - 비인용 용어가 더 나오면 `magus terms --add`로 넣는다.

## 2. 현재 단계

**P0 완료 + 첫 보고서**(1~7단계 `step1`~`step7`, 실데이터 보정 `p0-realdata`, 마무리 `p0-report1`). 남은 것은 사용자 검토와 Desktop 실사용 피드백이다.

## 3. 단계별 체크리스트

- [x] 1~7단계 — 2026-10-03, `step1`~`step7`
- [x] 실데이터 검증·보정 — 2026-10-03, `p0-realdata`
- [x] **P0 마무리** — 2026-10-03, `p0-report1`
  - 산출물
    - 코멘트 kind `fact`(SCHEMA_VERSION 6), 비인용 용어 파일과 `magus terms`
    - `src/magus/melchior/author_report.py`, `magus author-report`, `docs/reports/2026-10-03-인용-점검.{md,docx}`
    - `src/magus/paths.py`(FILES_DIR), ref_add 제목 매칭
    - outline 표기: "(장별 합)", kind별 수, 특수 장 label
    - `tests/test_author_report.py`, test_stdio·test_outline·test_config·test_realdata_shapes 추가분
- [ ] Desktop 실사용 피드백 반영(사용자 대기)

## 4. 검토 대기 결정

**확정됨(2026-10-03 사용자 답변)**: #1, #15, #16, #17(고유 문헌 수로 변경), #20, #22, #25.

**대기(이전 28건, 그대로 둠)**
- 1차 19건: 2·3·4·5·6·7·8·9·10·11·12·13·14·18·19·21·23·24·26. 내용은 `git show step7:status.md`의 4절에 있다.
- 실원고 라운드 9건: 27~35. 내용은 `git show p0-realdata:status.md`의 4절에 있다.
  - 27 서장·맺음·부록은 번호 없는 장(0, 90, 90+N)
  - 28 음역 추정은 검사할 때만
  - 29 uncertain은 미확인 수에서 뺀다
  - 30 앵커 key는 인용이 하나뿐일 때만
  - 31 a/b 모호는 첫 항목 + 표시
  - 32 코멘트 표현 확장
  - 33 fixtures 사본
  - 34 버그 refs 예외 처리
  - 35 데모 데이터를 demo 사용자로

**이번 라운드에서 새로 고른 것** (선택 / 대안 / 이유)

36. **출처 확인 코멘트에서 인용처럼 보인 것이 모두 비인용 용어면 general**
    - 대안: fact로 둔다.
    - 이유: I46을 general로 하라는 지시를 규칙으로 옮겼다. 문헌이 아예 없으면 fact다.
37. **비인용 용어 파일은 프로젝트별**(`projects/<id>/book/non_citation_terms.txt`)이고, `--replace` 재임포트 때 새 프로젝트로 옮긴다.
    - 대안: 사용자(책장)별.
    - 이유: 지명·사건은 책마다 다르다. 재임포트로 사람이 정한 목록이 사라지면 안 된다.
38. **상대 경로는 FILES_DIR 기준**(기본 `DATA_DIR`의 부모 = 프로젝트 폴더). ref_add·book_import·idea_add_conversation에 적용한다.
    - 대안: 작업 폴더 기준(이전 동작), 또는 DATA_DIR 기준.
    - 이유: Desktop이 띄우는 작업 폴더는 정해져 있지 않다. 사용자가 말하는 경로(`fixtures/papers/…`)는 프로젝트 폴더 기준이다.
39. **ref_add에 key도 저자·연도도 없으면 제목으로 찾는다**: bib 제목이나 전문 첫머리 5,000자에 참고문헌 제목(정규화, 12자 이상)이 그대로 있는 문헌이 하나일 때만.
    - 대안: 오류를 내고 저자·연도를 요구한다.
    - 이유: 299편이 이미 unverified로 있다. 저자가 서지를 다시 말할 필요가 없다. 둘 이상이면 고르지 않는다.
40. **저자 보고서는 생성기로 만든다**(손으로 쓰지 않음)
    - 형식: 3쪽 안에 들도록 본문 10pt로 하고, 사실·수치 요청은 장별 한 줄에 이어 붙였다.
    - "본문에 이름만 나옴"은 확실한 자리만 본다: 이니셜이 맞는 이름 뒤, 괄호 속, 공저자와 가운뎃점.
    - 연도 불일치 2건은 "연도 오기 또는 참고문헌 누락"으로 적고 판단은 저자에게 맡겼다.
41. **outline 머리줄을 "미확인 인용(장별 합)"으로 바꿨다**
    - 대안: 책 전체 고유 수(296)를 계산해 싣는다.
    - 이유: 장별 값은 저장된 파생값이라 싸다. 책 전체 고유 수는 cite-report와 보고서가 맡는다. 표기만 바꿔 혼동을 막았다.
42. **README 시험 문장 세 개는 내가 골랐다**: 책 지도, 35장 인용 점검, 사실·수치 요청.
    - 이유: 지시문에 "위 세 가지 테스트 프롬프트"가 있었지만 메시지와 이전 대화 어디에도 없었다.

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음). Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 실패한다. 그때는 `uv add --no-sync`와 `uv pip install`을 쓴다.
- **Python** 3.12(.venv). **MCP SDK** mcp 2.2.0.
- **의존성**: python-docx 1.2.0, pymupdf 1.28.2, pypandoc-binary 1.17(pandoc 3.9), numpy 2.5.3, lxml. ruff 0.16(개발용, `--select F,B`로 점검).
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=6`.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`(USER_ID=default, DATA_DIR=C:\project_2026\Magus\data → FILES_DIR 기본 C:\project_2026\Magus)
  - 로그: `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`. 시작 줄에 files_root가 찍힌다.
- **데이터 사용자**
  - `default`: 실원고 `book`(비인용 용어 5개), refs 299, 실대화 452발화, 문체 0
  - `demo`: 데모 프로젝트·표본
  - `synthetic`: 합성 synth
- **fixtures**: `fixtures/261002-닿으려는_종_전면개정_그림추가.pdf`, 대화 md 4개. `fixtures/papers/`는 아직 없다(사용자 대기).
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
  - 태그: `step1`~`step7`, `p0-realdata`, `p0-report1`.
  - `fixtures/`와 `data/`는 gitignore. `docs/reports/`는 커밋한다.

## 6. 마지막 세션 요약

**2026-10-03 오후(13:48~14:35)**
- CLAUDE.md에 "프로젝트 폴더 밖 파일" 규칙을 넣었다.
- 코멘트 kind를 citation·fact·general로 나눴다. 비인용 용어 파일을 도입해 실원고를 다시 임포트하고 분류표를 갱신했다.
- 저자용 인용 점검 보고서(md + docx)를 생성기로 만들었다.
- ref_add 시연 경로(FILES_DIR, 제목 매칭)를 고치고 README "첫 실행 확인" 절을 썼다.
- outline 표기를 다듬었다(장별 합, kind별 수, 특수 장 label).
- 테스트 150개 통과, ruff(F·B) 통과. 커밋하고 `p0-report1` 태그를 달았다.

## 7. 알려진 문제 — 실원고에서 아직 안 맞는 것

- **표**: 칸 구분 없이 한 문단으로 들어온다(27장 등). 표 안의 도시 설립 연도는 비인용 용어 파일로 걸렀다(그대로 둠, docx 재임포트 때 다시 본다).
- **수식·그림**: 수식은 텍스트 그대로(`g_Y ≈ g_N + g_y`), 그림 10개는 `[그림 N]` 자리표시자다(그대로 둠).
- **코멘트 앵커**: PDF에서는 말풍선 높이의 문단 단위로 근사한다. 앵커에 인용이 하나뿐이면 그 문헌으로 잇기 때문에, 사실·수치 요청 일부(I81·I82 인구 수치)가 citation(buckley2010)으로 분류된다.
- **원고 쪽 불일치**(보고서 2·3절, 저자 답변 대기)
  - `Brook(2008)` vs 참고문헌 Brook 2010, `Wiessner(2014)` vs 참고문헌 Wiessner 1982. I12(wiessner2014)는 refs에 연결되지 않는다.
  - 참고문헌에만 있는 4건(Graunt, Lattimore, Lee, Nordhaus). 본문에는 이름만 나온다.
  - 음역 추정 7건, 케인스(1930) a/b, Acemoglu 2001 두 편.
- **참고문헌 파싱 실패 1**: `張楠(장남). (명대). 『神峰通考』`(숫자 연도 없음, raw로 보관, 그대로 둠).
- **Desktop 실사용 미검증**: 서버 쪽 경로 흐름은 테스트와 리허설로 확인했지만 Desktop에서 실제로 부른 기록은 아직 없다.
- **보고서 쪽수**: Word·LibreOffice가 없어 글자폭으로 추정했다(약 2.3쪽). Word에서 열어 확인이 필요하다.
- 이전부터 있던 것: 번호 충돌 가능성(멀티 프로세스), 직접 수정 뒤 reindex 필요, 토큰 추정 휴리스틱, 임베딩 API 실제 호출 미검증.
