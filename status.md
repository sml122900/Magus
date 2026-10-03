# Magus status

> 세션을 시작하면 이 파일부터 읽는다. 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때 반드시 갱신한다.
> 마지막 갱신: 2026-10-03 14:00 KST — 실원고 보정 라운드 완료(태그 `p0-realdata`)

## 0. 최근 보고 (실원고 보정 라운드)

- **실데이터로 완료 기준 전부 충족**: 장 35(+서장·맺음·부록 5)·부 8·코멘트 86(≥80)·refs 299(≥200), outline 1,946토큰(≤3,000), 대화_전체_기록 me 96/ai 96(모든 ai에 parent_id).
- 재료
  - `fixtures/`는 비어 있었다. 사용자 Downloads에서 실원고 **PDF**(docx 없음)와 대화 md 4개를 찾아 `fixtures/`에 사본을 두었다.
  - 사용자가 붙여 넣는다고 한 import 리포트와 Desktop 실사용 문제는 메시지에 없었다. 그래서 리포트를 직접 만들었다.
- 집계(`data/realdata/cite-report.md`, 일지 "실원고 보정 라운드" 절)
  - 고유 미확인 문헌 **296건**, 인용 출현 397회.
  - 참고문헌에 없는 인용 2건(brook2008, wiessner2014: 둘 다 연도 불일치로 보임), 한글 미해결 3건(지명), 미인용 4건.
- 문서
  - 결정: [realdata-import-calibration](docs/decisions/realdata-import-calibration.md), [citation-matching-realdata](docs/decisions/citation-matching-realdata.md)
  - 트러블슈팅: [pdf-bibliography-merge](docs/troubleshooting/pdf-bibliography-merge.md), [korean-name-particle-truncation](docs/troubleshooting/korean-name-particle-truncation.md)

## 1. 지금 바로 할 일

- **대기(사용자)**
  - 아래 "4. 검토 대기 결정"을 확인한다(이전 19건 + 이번 9건).
  - Claude Desktop을 **완전히 종료한 뒤 다시 실행**하고 실사용해 본다. 03:33 이후 재시작 기록이 없다. 로그에는 도구 호출이 0건이다.
- **사용자의 다음 작업 제안**: `data/realdata/cite-report.md`의 "가장 많이 인용된 미확인 문헌 상위 20"부터 실제로 읽고, `ref_add`(발췌 + 이유)로 verified를 만든다.
- 실사용에서 문제가 나오면: 재현 테스트부터 만들고 고친다.

## 2. 현재 단계

**P0 완료**(1~7단계 `step1`~`step7` + 실데이터 보정 `p0-realdata`). 남은 것은 사용자 검토와 실사용 피드백이다.

## 3. 단계별 체크리스트

- [x] 1~7단계 — 2026-10-03, `step1`~`step7`
- [x] **실데이터 검증·보정** — 2026-10-03, `p0-realdata`(브랜치 `p0-realdata-parser`를 squash merge)
  - 산출물
    - `src/magus/book/pdf_reader.py`(재작성)
    - `src/magus/melchior/{translit,report}.py`(신규), `citations`·`check`·`bibliography` 보정
    - `src/magus/book/{importer,comments}.py`, `src/magus/casper/conversation.py`
    - 장 label(SCHEMA_VERSION 5), CLI `magus cite-report`
    - `tests/test_{realdata_shapes,cli}.py`
  - 데이터: default 사용자의 `book` 프로젝트(실원고)와 실대화 452발화. 리포트 사본은 `data/realdata/`.
- [ ] Desktop 실사용 피드백 반영(사용자 대기)

## 4. 검토 대기 결정

**확정됨(2026-10-03 사용자 답변)**
- #1 머리말은 unsplit.md에 둔다.
- #15 verified는 발췌 1개 이상이 필요하다.
- #16 ref_id는 문헌 key다.
- #17 **변경**: 고유 문헌 수로 센다. 반영 완료.
- #20 경로 입력을 받고, 본문 입력도 유지한다.
- #22 화자 불명 구간은 리포트만 한다.
- #25 합성 데이터는 synthetic 사용자로 격리한다. CLAUDE.md에 명문화했다.

**대기(이전 19건)**: 2·3·4·5·6·7·8·9·10·11·12·13·14·18·19·21·23·24·26. 내용은 `git show step7:status.md`의 4절에 있다. 요약하면 다음과 같다.
- #2 목차 중복: 본문이 가장 긴 것을 고른다. **이번에 "제목 서식이 있는 것 우선"을 앞에 더했다.**
- #3 이슈 본문에 원문 120자를 붙인다.
- #4 파싱 실패 줄은 raw ref로 보관한다.
- #5 key 충돌에는 -2를 붙인다.
- #6 refs 재임포트 때 기존 key를 보존한다.
- #7 replace는 휴지통으로 옮긴다.
- #8 로컬 경로 입력.
- #9 소제목은 ##.
- #10 한글 bigram FTS.
- #11 합성 fixture 위치.
- #12 export는 파일 이름만 받는다.
- #13 issue origin 인자.
- #14 export 제목 단계.
- #18 ref_search 기본값은 both.
- #19 조사 처리: **이번에 목록을 줄였다(는·를 등만)**.
- #21 연속된 AI 발화는 합치지 않는다.
- #23 tags 여섯 키 필수.
- #24 FTS도 reason+tags만.
- #26 임베딩 키가 없으면 FTS로 동작한다.

**이번 라운드에서 새로 고른 것** (선택 / 대안 / 이유)

27. **서장·맺음·부록은 번호 없는 장으로 둔다**
    - 선택: 번호는 서장 0, 맺음 90, 부록 N은 90+N이고, label을 표시한다.
    - 대안: unsplit에 두거나 36~39번을 매긴다.
    - 이유: 서장에도 코멘트와 인용이 있어 게이트 안에 있어야 한다. 그대로 두면 맺음·부록이 제35장에 붙는다. 1~89는 새 장을 넣을 자리로 남긴다.
28. **음역 추정은 검사할 때만 한다**
    - 선택: aliases에 저장하지 않는다. 같은 연도 안에서만 비교하고, 문턱은 0.75, 동점이면 고르지 않는다.
    - 대안: 자동으로 aliases에 저장한다.
    - 이유: 추정이 원본(파일)을 오염시키면 안 된다. 사람이 리포트의 "추정 연결" 목록을 확인한다.
29. **uncertain(한글 표기 미해결)은 미확인 수에서 뺀다**
    - 대안: unknown으로 센다.
    - 이유: 실원고에서는 3건 모두 지명(표 안 도시 설립 연도)이었다. 목록으로는 보여 준다.
30. **코멘트 key를 앵커에서 가져오는 것은 앵커 문단에 서로 다른 인용이 하나뿐일 때만**
    - 대안: 첫 인용을 쓴다.
    - 이유: PDF 앵커는 문단 전체라 인용이 여럿이면 어느 것인지 모른다.
31. **연도 a/b가 모호하면 첫 항목으로 잇고 "연도 a/b 모호"로 표시한다**(Keynes(1930) → 1930a)
    - 대안: unknown으로 둔다.
32. **코멘트 표현을 넓혔다**: "확인할 필요", "원문과/으로 대조"(정해 둔 표현의 실제 변형).
33. **fixtures 사본**: 사용자 Downloads의 원본을 `fixtures/`에 복사했다(원본은 건드리지 않음).
34. **책장 refs 예외 처리**: 첫 임포트에서 버그로 잘못 합쳐진 refs 190건(모두 unverified, 몇 분 전 생성)은 "재임포트 때 기존 key 보존" 원칙의 예외로 보았다. 책장째 `trash/shelf-melchior-buggy-merge-*`로 옮기고 다시 임포트했다.
35. **default에 있던 데모 데이터(프로젝트 + 생각 4·문체 2)를 `demo` 사용자로 옮겼다**(원본은 default/trash에 있음).

## 5. 환경 메모

- OS: Windows 11. 셸은 PowerShell과 Git Bash.
- **uv** 0.12.22: `C:\Users\이성민\AppData\Roaming\Python\Python313\Scripts\uv.exe` (PATH에 없음). Desktop이 `magus.exe`를 실행 중이면 `uv sync`나 `uv add`가 실패한다. 그때는 `uv add --no-sync`와 `uv pip install`을 쓴다.
- **Python** 3.12(.venv). **MCP SDK** mcp 2.2.0.
- **의존성**: python-docx 1.2.0, pymupdf 1.28.2, pypandoc-binary 1.17(pandoc 3.9), numpy 2.5.3, lxml. ruff 0.16(개발용).
- **SQLite** 3.49.1. 인덱스 `SCHEMA_VERSION=5`.
- **Claude Desktop**
  - 설정: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`(USER_ID=default)
  - 로그: `%LOCALAPPDATA%\Claude\Logs\mcp-server-magus.log`
- **데이터 사용자**
  - `default`: 실원고 `book`, refs 299, 실대화 452발화, 문체 0
  - `demo`: 데모 프로젝트·표본
  - `synthetic`: 합성 synth
- **fixtures**: `fixtures/261002-닿으려는_종_전면개정_그림추가.pdf`, `대화_전체_기록.md`, `대화기록_닿으려는종.md`, `도시_유전자_민주주의_대화.md`, `사피엔스_총균쇠_대화.md`(원본은 `~/Downloads/0_아빠 대화내용과 pdf_261003/`, `~/Downloads/대화_전체_기록.md`)
- **명령**(Bash, 프로젝트 루트에서 실행. 콘솔 한글은 `PYTHONIOENCODING=utf-8`)
  ```
  .venv/Scripts/python -m pytest -q -p no:cacheprovider
  DATA_DIR=./data .venv/Scripts/python -m magus import fixtures/<원고>.pdf --project-id book --title "닿으려는 종" --replace
  DATA_DIR=./data .venv/Scripts/python -m magus cite-report --project-id book > data/realdata/cite-report.md
  DATA_DIR=./data .venv/Scripts/python -m magus conversation fixtures/<대화>.md
  DATA_DIR=./data .venv/Scripts/python -m magus reindex
  DATA_DIR=./data USER_ID=demo .venv/Scripts/python -m magus seed-demo     # default에는 거부됨
  ```
- **git**
  - master에 바로 커밋하고, 단계가 끝나면 태그를 단다. 실험은 브랜치에서 하고 squash merge한다.
  - 태그: `step1`~`step7`, `p0-realdata`.
  - `fixtures/`와 `data/`는 gitignore.

## 6. 마지막 세션 요약

**2026-10-03 오후(13:18~14:00)**
- 검토 결정 7건을 반영했다(#17은 고유 문헌 수로 변경).
- 실원고 PDF와 실대화 4종으로 2·4·5단계를 다시 돌리고 파서를 보정했다.
  - PDF 레이아웃 복원, 특수 장, 참고문헌 병합 버그, 인용 형식 16종, 음역 추정, 실명 훼손, 코멘트·대화 표현 변형.
- 책 전체 인용 집계 CLI(`cite-report`)를 만들었다.
- default 사용자를 정리했다(데모를 demo 사용자로 이동, CLI 가드).
- 테스트 140개 통과, ruff 통과. 브랜치를 squash merge하고 `p0-realdata` 태그를 달았다.

## 7. 알려진 문제 — 실원고에서 아직 안 맞는 것

- **표**: 칸 구분 없이 한 문단으로 들어온다(27장 등). 그 안의 도시 설립 연도(마닐라(1571)·유조프카(1869)·푸둥(1990))가 uncertain으로 잡힌다.
- **수식**: 텍스트 그대로다(`g_Y ≈ g_N + g_y`). 그림 10개는 `[그림 N]` 자리표시자이고, 캡션은 별도 문단이다.
- **코멘트 앵커**: PDF에서는 말풍선 높이의 문단 단위로 근사한다. 코멘트가 가리키는 정확한 구절은 알 수 없다.
- **코멘트의 문헌 key**
  - citation 코멘트 84건 중 39건은 key가 없다. 대부분 특정 문헌이 아니라 사실·수치를 확인하라는 요청이다("칙술루브 충돌체의 크기 추정").
  - 지명 오탐 1건: I46 `선하이정(1835)`(소금 우물).
- **원고 쪽 불일치**(저자가 확인할 것)
  - `Brook(2008)` vs 참고문헌 Brook 2010
  - `Wiessner(2014)` vs 참고문헌 Wiessner 1982
  - 참고문헌에만 있고 본문에 연도 없이 이름만 나오는 4건(Graunt, Lattimore, Lee, Nordhaus)
- **모호한 연결**
  - 음역 추정 7건(하야시·후닝·김성은·크레머·모리스·넌·케인스)은 사람이 확인해야 한다.
  - `케인스(1930)`은 1930a/b 중 어느 것인지 모른다.
  - 공저자 없이 `Acemoglu(2001)`로 쓰면 두 편 중 어느 것인지 모른다.
- **참고문헌 파싱 실패 1**: `張楠(장남). (명대). 『神峰通考』`(숫자 연도 없음, raw로 보관).
- **Desktop 실사용 미검증**: 사용자가 실사용 문제 목록을 주지 않았고, 로그상 도구 호출이 0이다. Desktop 재시작이 필요하다.
- 이전부터 있던 것: 번호 충돌 가능성(멀티 프로세스), 직접 수정 뒤 reindex 필요, 토큰 추정 휴리스틱, 임베딩 API 실제 호출 미검증.
