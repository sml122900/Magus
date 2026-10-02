# 인용 게이트: 막지 않고 표시·집계, verified는 발췌가 있어야, 이슈는 ref key로 연결

- 날짜: 2026-10-03 (야간 자율 작업)
- 단계: 4단계
- 코드: `src/magus/melchior/{citations,check,refs,tools}.py`, `src/magus/book/comments.py`, `src/magus/search.py`, `tests/test_refs.py`, `tests/test_citations.py`

## Problem

- 실제 사례에서는 인용 약 270개와 참고문헌 약 250편이 LLM의 기억에서 만들어졌다. 저자는 그 문헌들을 읽지 않았다. Word 코멘트 86개 중 82개가 "확인 필요"였다.
- 원칙: refs에 `verified`로 있는 출처만 인용한다. 없으면 `[출처 필요: …]`로 남긴다. **막지 않고 표시하고 집계한다. 판단은 사용자가 한다.**
- 한국어 원고의 인용 표기는 다양하다: `(Daeschler, Shubin & Jenkins, 2006)`, `Clack(2012)`, `Hu et al.(2023)`, `갤러(2022)`, `(헨릭, 2016)`, 괄호 안 다중 인용, 조사가 붙은 한글 저자(`갤러는(2022)`).
- 2단계에서 드러난 한계가 셋이었다: 코멘트 분류의 "서지" 오탐("일어서지"), 괄호 안 다중 인용 누락, 조사가 key에 섞이는 문제.

## Action

- **추출기 보강**
  - 괄호 묶음 `(…)`을 먼저 찾고 `;`로 나눠 하나씩 파싱한다. 그래서 다중 인용을 모두 잡는다.
  - 한글 저자는 조사(은·는·의·으로 …)를 뗀 것을 대표 key로 쓰고, **원형을 첫 후보로 남긴다**. 이름 자체가 조사처럼 끝나는 경우(카를로)를 위해서다. 해석은 원형 → 조사 뗀 것 순서로 시도한다.
  - 연도 접미사(2012a)를 key에 포함한다. "논문(2006)", "당시(1998)" 같은 비저자 낱말은 제외한다.
  - "서지"는 앞에 한글이 없고, 뒤가 한글이 아니거나 정보·사항·확인 같은 낱말일 때만 인정한다.
- **해석**: 후보 key를 refs.key에서 찾고, 없으면 aliases에서 찾는다. 국역 꼬리에서 만든 `갤러2022`, `헨릭2016`이 영문 key로 이어진다. 둘 다 없으면 unknown이다.
- **게이트**
  - `book_write_chapter`는 쓰기를 마친 **뒤에** ref_check를 돌린다. 응답에 `unverified_cites`(unverified·unknown의 key·횟수·표기)와 `needs_source`(`[출처 필요]` 수)를 담는다.
  - `book_read_chapter`도 같은 결과를 준다. `[]`는 "검사했고 없음"이다.
  - 장별 `unverified_cite_count`(verified가 아닌 인용의 **출현 수**)는 인덱스에만 두는 파생값이다. 서버 시작, `magus reindex`, refs 변경 때 다시 계산한다.
- **verified의 조건**
  - `ref_add`는 발췌(`passages`, text와 reason)가 하나 이상 있어야 받는다. 목록에 있거나 기억난다는 이유로는 verified가 되지 않는다.
  - 같은 key(또는 alias)가 unverified로 있으면 verified로 올리고, bib·aliases·발췌를 합친다(중복 발췌는 버림).
  - 전문(`file_path` txt/md/pdf/docx 또는 `full_text`)은 ref_full 레인으로 청킹한다.
- **citation 이슈 ↔ refs**
  - 이슈의 `ref_key`(코멘트에서 뽑은 후보)를 해석해 `ref_id`에 **정식 ref key**를 기록한다.
  - refs 행 id는 인덱스를 다시 만들면 바뀌므로, 파일(issues.md)에 남는 안정적인 식별자로 key를 쓴다.
  - 연결은 임포트, ref_add, ref_import_bibliography 뒤에 다시 계산한다. `book_issues`에서 `citation→갤러2022 ⇒ galor2022`, `⇒ refs 없음`처럼 보인다.
- **ref_search**
  - 하이브리드 검색(FTS 한글 bigram + 벡터 RRF, 벡터는 7단계)으로 찾는다.
  - 발췌 레인을 먼저 보여 주고, 전문 결과에는 "발췌되지 않은 부분 → ref_add로 발췌에 추가"라고 표시한다.
- 비교한 대안
  - **쓰기 차단**: 원칙("막지 않는다")에 어긋나고, 초고 단계의 흐름을 끊는다.
  - **bib만으로 verified 허용**: 실제 사례의 실패(읽지 않은 문헌 인용)를 되풀이한다.
  - **refs.id로 이슈 연결**: 인덱스를 다시 만들면 id가 바뀐다.
  - **미확인 수를 파일에 저장**: refs가 바뀔 때마다 모든 장 파일을 다시 써야 하고, 파생값이 원본에 섞인다.

## Result

- 완료 기준을 테스트로 고정했다(`test_completion_criteria_ref_check_and_promotion`). 1장 ref_check에서 daeschler2006과 clack2012가 unverified로 잡히고, ref_add 뒤 다시 돌리면 daeschler2006이 verified로 옮겨 간다.
- 합성 원고의 7개 장 전체 ref_check 결과(`data/synthetic-fixtures/step4-refcheck-report.md`)
  - 1장: 인용 8건이 모두 unverified다(갤러는(2022)·갤러(2022) → galor2022 ×2, 다중 인용의 clack2012 ×2, hu2023 ×2).
  - 4장: `다이아몬드(1997)`가 aliases를 통해 diamond1997로 해석됐다.
  - 3장: `[출처 필요]` 1건.
  - 합계 미확인 9건.
- 코멘트 분류 재실행
  - "일어서지" 코멘트(I6)가 general이 됐다.
  - I4의 ref_key가 `갤러는2022`에서 `갤러2022`로 바뀌었다.
  - citation 7건 중 ref_key 후보 6건(86%)이고, 그중 refs와 연결된 것은 6건이다.
- 테스트 95개.

> 대안을 버린 이유: 차단은 원칙에 어긋나고, bib만으로 verified를 허용하면 실제 사례의 실패를 되풀이한다. 그래서 "표시하고 집계, verified는 발췌가 있어야"로 정했다.
