# 저자 확인 질문지(book_questions) — 설계안, 일부 구현

- 날짜: 2026-10-06
- 상태: **승인**(사용자 결정 #84, 2026-10-06). 구현은 7단계(아버지 온보딩) 뒤 첫 작업으로 한다.
- **구현(2026-10-06 밤, 야간 자율 작업 D, 태그 `questions`)**: `melchior/questions.py`(판별·답 반영), `melchior/question_tools.py`(`book_questions`·`book_answer`), 답 파일 `book/answers.md`, 오탐 두 개 수정(같은 장 두 번 찍힘 → `chapters_text`가 한 번만, Lee ↔ 이상호 → 저자가 한국 이름처럼 보이지 않으면 한국인 성명 낱말은 이름 언급으로 보지 않음).
  - 설계와 다른 점: 판별 로직을 questions.py로 **옮기지 않고**, build_cite_report·check_text·name_mentions를 그대로 불러 쓴다(저자 보고서 생성기를 건드리지 않으려고). 중복 서지는 (연도, 제목)이 같은 참고문헌으로 다시 계산하고, 제목을 못 읽은 줄(`(2013` 같은 것)은 뺀다. 연도 불일치 질문이 가리키는 문헌은 "참고문헌에만 있음"으로 또 묻지 않는다.
  - father-trial 확인: 질문 19건(연도 불일치 3, 참고문헌에만 5 = 4 + IEA 중복분 1, 한글 표기 추정 6, a/b 1, 같은 저자 두 편 2, 미연결 1, 중복 서지 1). 저자 자료 1절의 18곳 + IEA 중복분과 같다. 응답 2,102토큰(추정, 예산 3,000).
  - (2026-10-06 낮, 사용자 요청으로 끝냄) 웹 `/questions`("답해 주실 질문", 조회 전용: 종류·상태 거르기, 선택지는 코드 없이 설명만, `/book` 줄에서 링크)와 수정본 리포트 줄 "답해 주실 질문: 새로 생김 N · 저절로 닫힘 M · 답했지만 원고에 아직 그대로 K"(종류마다 5줄까지). 판별 로직을 옮기지 않고 불러 쓰는 방식은 사용자 승인.
  - 남은 것: Word 코멘트로 돌려주기(P2), 웹에서 바로 답하기.
- 배경: 채팅 Claude가 `private/reports/2026-10-06-father-materials-data.md`(father-trial, 최신본)로 아버지께 드릴 확인 자료를 만들었다.
  - 1절 "저자만 답할 수 있는 질문" 18곳: 연도 불일치 3, 참고문헌에만 있음 4, 한글 표기 추정 연결 6, 케인스 1930 a/b 1, 같은 저자·연도 두 편 2, 미연결 1, 중복 서지 1
  - 부록 A~D: 사실·수치 확인 82건, 미확인 문헌 상위 20, 장별 수, 판 사이 바뀐 점
  - 이것을 저자가 Magus를 쓰면서 직접(자기 Claude나 웹 화면으로) 받게 하는 기능을 검토한다.
- 관련: [citation-gate.md](citation-gate.md), [citation-matching-realdata.md](citation-matching-realdata.md), [reupload-design.md](reupload-design.md)(다시 올리기, 9절 돌려주기)

## Problem

### 지금 얻을 수 있는 것 (father-trial 기준, 2026-10-06 측정)

| 항목 | 얻을 수 있음 | 도구·화면 | 호출 수 |
|---|---|---|---|
| 연도 불일치 3 | 일부 | `ref_check`의 unknown(장마다). "같은 저자의 다른 연도 항목" 힌트가 없다. 참고문헌(unverified)을 보는 도구도 없다(`ref_search`는 verified만). 웹 `/checklist?status=unknown`은 🔴와 장은 보이지만 힌트가 없다 | 장을 모르면 `ref_check` 42회(알면 3회), 웹 1쪽 |
| 참고문헌에만 있음 4(+IEA 중복분 1) | 없음 | MCP·웹 모두 없다. CLI `magus cite-report`·`author-report`에만 있다 | – |
| 한글 표기 추정 연결 6 | 일부 | `ref_check`의 `matched_by: 음역 추정`(장마다). 웹 `/checklist`는 연결된 문헌을 🟡로만 보이고 "추정"이라는 표시가 없다 | 장을 모르면 42회(이번 판은 모두 제35장이라 알면 1회) |
| 케인스 1930 a/b 1 | 있음 | `ref_check`의 `keynes1930a/b`·`candidates`(제목 포함). 웹 `/checklist`의 "후보: …" | 장을 알면 1회, 웹 1쪽 |
| 같은 저자·연도 두 편 2 | 일부 | `ref_check`에는 key(`acemoglu2001-2`)만 보인다. "공저자로 골랐다"는 표시가 없다. 임포트·다시 올리기 리포트의 "key 충돌"에 올리는 그때 한 번 나온다 | 리포트 1회(그때뿐) |
| 미연결 1(셰 등 2019) | 있음 | `book_outline` 머리줄 "미연결 1"(수만), `ref_check`의 uncertain. 웹 `/checklist`의 ⚪(장 포함) | outline 1회 + 장을 알면 `ref_check` 1회, 웹 1쪽 |
| 중복 서지 1(IEA) | 일부 | 임포트·다시 올리기 리포트의 참고문헌 줄에 그때만 나온다. 저장하지 않는다(서버 `original/*-report.md`는 도구로 읽지 못한다) | 리포트 1회(그때뿐) |
| 부록 A 사실·수치 82 | 있음 | `book_issues(kind=fact, limit=200)`. 웹 `/issues?kind=fact` | 1회. 다만 응답이 약 10,600토큰(추정)이다 |
| 부록 B 미확인 상위 20 | MCP 일부, 웹 있음 | 책 전체 순위 도구가 없다. `ref_check` 42회를 Claude가 합산해야 한다. 웹 `/checklist`는 상태 → 인용 수 순으로 모두 나열한다(🔴 3건이 먼저) | MCP 42회, 웹 1쪽 |
| 부록 C 장별 미확인·확인 요청 수 | 있음 | `book_outline` 장 줄의 "미해결 n · 미확인인용 n". 웹 `/checklist` 장별 표(미해결 수는 없음) | 1회 |
| 부록 D 판 사이 바뀐 점 | 일부 | 다시 올리기 리포트(`book_import new_edition` 응답, 웹은 요약만)에 그때 한 번. outline은 판 줄만. 판 기록 전 비교(10/02 PDF ↔ 최신본)는 없다 | 올릴 때 1회 |

- 참고: 지금 응답 크기(추정, 한글 1자 = 1토큰)는 `book_outline` 2,231, `ref_check(35)` 650, `book_issues(kind=fact)` 10,628, `book_issues` 전체 18,048토큰이다.

### 지금 내부에서 어떻게 판별하는가

- **판별 엔진은 `melchior/check.py`의 `check_text`다.** 장 본문 하나의 인용마다 `CiteGroup`을 만든다.
  - `status`: verified | unverified(refs에 있으나 미확인) | unknown(refs에 없음) | uncertain(한글 표기인데 못 이음)
  - `matched_by`: "" | alias | 음역 추정 | 연도 a/b 모호 | 음역 추정·연도 a/b 모호
  - `candidates`: a/b 모호일 때 후보 key
  - `Resolver.resolve`(check.py)의 순서: key → aliases → 연도 a/b 접미사(`_suffixed`) → (한글만) 같은 연도 음역 추정(`translit.best_match`)
  - **`Resolver._disambiguate`가 같은 기본 key의 문헌(acemoglu2001, acemoglu2001-2)을 공저자 이름으로 조용히 고른다.** 골랐다는 표시(matched_by)를 남기지 않는다.
- **저장되는 것은 거의 없다.**
  - 인덱스 파생값 `chapters.unverified_cite_keys`·`uncertain_cite_keys`(`LocalStore.set_cite_keys`)만 있다. outline의 수가 여기서 나온다.
  - refs의 `status`(unverified | verified)·`aliases`(bib.json), citation 이슈의 `ref_id`(issues.md)
  - `matched_by`·`candidates`는 저장하지 않고 호출할 때마다 계산한다(결정 #28·#31: 추정은 저장하지 않는다).
- **책 전체 집계는 `melchior/report.py`의 `build_cite_report`가 그때그때 계산한다.**
  - `hint`(unknown과 같은 성의 다른 연도 key), `uncited`(참고문헌에만 있음), `inferred`(추정·모호로 이은 표기)
  - 쓰는 곳: CLI `cite-report`·`author-report`, 웹 `/checklist`. 웹은 `docs`(상태·후보)만 쓰고 uncited·hint·inferred는 쓰지 않는다.
- **`melchior/author_report.py`의 `build_author_report`만 계산하는 것**
  - `same_author`: key 접미사 `-N`이나 형제 key로 같은 저자·연도 두 편을 찾고, 장별로 어느 쪽에 이었는지 모은다.
  - `name_mentions`: 참고문헌에만 있는 문헌의 이름이 본문에 연도 없이 나오는 곳(존 그랜트, 래티모어)
  - 질문 문장(3절 "답해 주실 질문")
  - 오탐 두 개가 있다: 한 장에 같은 표기가 두 번이면 장 번호가 두 번 찍힌다("제35·35장"), 이름 대조가 Lee에 '이상호'를 섞는다(status.md 7절).
- **`melchior/bibliography.py`의 `import_bibliography`는 올릴 때만 계산한다.** 중복 서지(`duplicates`), key 충돌, 기존 서지와 다름, 파싱 실패가 `BibReport`로 나와 응답과 `original/*.md` 리포트에 들어간다. 인덱스에는 없다.
- 정리: **"참고문헌에만 있음"은 report.py에서만, "같은 저자·연도 두 편"은 author_report.py에서만, "중복 서지"는 올릴 때만 계산한다.** "한글 표기 추정 연결"은 판별 결과(`matched_by`)지만 장 단위 호출 결과로만 있다. 어느 것도 책 단위로 저장되지 않는다.

## Action — 설계(초안)

### 1. 질문의 모양

- 판별 로직을 `melchior/questions.py` 한 곳으로 모은다. `build_author_report`의 계산(same_author, inferred, ambiguous, name_mentions)과 `build_cite_report`의 hint·uncited를 여기로 옮기고, 보고서 생성기와 도구가 함께 쓴다. 이때 위의 오탐 두 개도 고친다.
- `Question(id, type, chapters, surface, refs, options, status, answer?)`
  - `id`: 판이 바뀌어도 같은 값. 종류 + key·표기로 만든다(미해결 번호와 무관). 예: `year:brook2008`, `bibonly:graunt1662`, `translit:하야시2016>hayashi2016`, `ab:keynes1930`, `pair:acemoglu2001`, `unlinked:셰2019`, `dup:iea2025=internationalenergyagency2025`
  - `surface`: 원고 표기(`Brook(2008)`, `셰 등(2019)`). 본문 문단은 싣지 않는다.
  - `refs`: 관련 참고문헌 한 줄씩(저자(연도) 『제목』)
- 종류와 선택지

| 종류 | 판별(출처) | 선택지 | 답의 반영 |
|---|---|---|---|
| year 연도 불일치 | unknown + 같은 성 다른 연도(report.hint) | ① 본문 연도를 고친다 ② 참고문헌에 그 연도 문헌을 넣는다 ③ 다른 문헌이다 | ①② 결정 기록 + "Word에서 고칠 것". 다음 판에서 조건이 사라지면 저절로 닫힌다 |
| bibonly 참고문헌에만 | report.uncited + 이름 언급 | ① 인용을 넣는다 ② 목록에서 뺀다 ③ 그대로 둔다 | ①② Word 수정 대기. ③ 답을 기록하면 다시 묻지 않는다 |
| translit 한글 표기 추정 | matched_by 음역 추정 | ① 맞다 ② 다른 문헌(같은 연도 후보 목록) ③ 참고문헌에 없다 | ①② `add_alias`(결정 #28의 확정 경로). 그러면 matched_by가 alias가 되어 질문이 사라진다 |
| ab 연도 a/b 모호 | candidates | 후보 a·b 중 하나 | `add_alias(<고른 key>, 표기)` |
| pair 같은 저자·연도 두 편 | same_author(_disambiguate 결과) | ① 맞다 ② 바꿔야 한다 | ① 답을 기록하면 다시 묻지 않는다(장 ↔ key 짝이 바뀌면 다시 묻는다). ② 결정 기록 + Word 수정 대기 |
| unlinked 미연결 | uncertain | 같은 성·연도 후보 중 하나 / 사람 이름이 아니다 / 참고문헌에 없다 | 후보면 `add_alias`, 사람 이름이 아니면 비인용 용어(`set_non_citation_terms`) |
| dup 중복 서지 | refs에서 (연도, 제목)이 같은 쌍을 다시 계산 | 어느 쪽을 지울지 | 결정 기록 + Word 수정 대기. 다음 판 참고문헌에서 하나가 빠지면 닫힌다 |

- 중복 서지는 올릴 때만 계산하던 것을 refs에서 언제든 다시 계산한다(`bibliography._identity`·제목·연도 비교). 따로 저장하지 않는다.

### 2. 형태 후보와 비용

| 형태 | 하는 일 | 비용 | 권장 |
|---|---|---|---|
| A. MCP 도구 `book_questions(project_id?, status=open, type?)` | 질문 목록과 선택지를 돌려준다(조회 전용) | 중간(questions.py로 옮기기 + id·테스트). 판별 로직은 이미 있다 | **P1, 온보딩 뒤 첫 작업** |
| A'. MCP 도구 `book_answer(question_id, choice, note?)` | 답을 반영한다: alias·비인용 용어 변경, `book_decide`로 결정 기록, 답 파일에 기록 | 중간(반영 경로가 종류마다 다르다) | **A 바로 다음.** 지금은 alias가 CLI(`magus alias`)에만 있어서, 저자가 Claude에게 답해도 운영자가 손으로 반영해야 한다 |
| B. 웹 `/questions` | 같은 목록을 화면으로. 처음엔 조회만, 나중에 답 버튼 | 조회 낮음 / 답 폼 중간 | A와 같이 조회만 먼저 |
| C. 다시 올리기 리포트에 "새로 생긴 질문 · 저절로 닫힌 질문" 절 | 올리기 전후 질문 id를 비교한다 | 낮음(A가 있으면) | A와 같이 |
| D. Word 코멘트로 돌려주기(P2) | 질문을 작성자 "Magus" 코멘트로 원고 표기 위치에 단 docx를 내보낸다 | 높음(reupload-design 9절의 run 나누기, Word 실물 확인) | P2. 질문 id를 코멘트 머리(`[Magus Q year:brook2008]`)에 넣으면 다시 올릴 때 지문으로 알아본다 |

### 3. "한 번에 한 장" 원칙과 응답 크기

- 원칙은 "에이전트는 책 전체(본문)를 들고 있지 않는다"이다. `book_questions`는 본문이 아니라 **질문 목록**을 돌려준다. 원고에서 옮기는 것은 원고 표기(`Brook(2008)`)와 장 이름뿐이다. 그래서 원칙에 어긋나지 않는다고 본다. `book_outline`·`book_issues`처럼 책 단위의 메타 목록이다.
- 응답 크기(father-trial, 추정)
  - 저자 보고서 2·3절(질문 17줄, 선택지 없음)이 약 970토큰이다.
  - 미연결·중복 서지와 질문 id·선택지를 더하면 18곳에 약 1,500~2,000토큰으로 본다.
  - outline처럼 3,000토큰 예산을 두고, 넘치면 "외 N건 — type으로 좁혀 보기"로 접는다.
- 부록 A(사실·수치 82건)는 질문이 아니라 미해결이다. `book_issues`로 둔다. 다만 82건 한 번에 약 10,600토큰이라, `book_issues`에 짧은 보기(번호·장·요청 앞 60자)를 더하는 것을 함께 검토한다(낮음, 별건).

### 4. 답을 받아 반영하는 방법

- 저자가 Claude에게 답한다("하야시는 맞아", "Brook은 2010이 맞으니 본문을 고칠게"). Claude는 `book_answer(id, choice, note)`를 부른다. 저자가 분명히 답했을 때만 부른다는 것을 도구 설명에 적는다(#74와 같은 방식).
- 서버가 하는 일
  1. 종류별 반영: alias 추가(`refs.add_alias`), 비인용 용어 추가. 그러면 그 자리에서 `after_refs_changed`로 집계를 다시 계산한다.
  2. 결정 기록: `book_decide`와 같은 경로로 D번호를 남긴다(예: "Brook(2008)은 2010의 오기. Word에서 고친다").
  3. 답 파일: 프로젝트 `book/answers.md`(사람이 읽는 파일, 원본)에 `## Q year:brook2008 · <시각>`, `- choice:`, `- decision: D12`, `- applied: alias …`를 쌓는다. 인덱스에는 두지 않거나 파생값으로만 둔다.
- 질문의 상태
  - **열림**: 조건이 있고 답이 없다.
  - **답함 · 원고 반영 대기**: Word 수정이 필요한 답(year, bibonly ①②, dup, pair ②). 다음 판에서 조건이 사라지면 저절로 닫힌다.
  - **닫힘**: 조건이 사라졌다(alias로 이어짐, 다음 판에서 고쳐짐) 또는 "그대로 둔다·맞다"로 답했다.
  - 답함인데 다음 판에도 조건이 그대로면 "답했지만 원고에 아직 그대로"로 다시 보인다.

### 5. 다시 올린 뒤의 유지와 재계산

- 질문은 저장하지 않고 **매번 지금 원고와 refs에서 계산한다.** 그래서 다시 올리면 저절로 새 판 기준이 된다.
- 판이 바뀌어도 이어지는 것은 `answers.md`의 답뿐이다. 질문 id가 key·표기로 만들어져 있어 같은 질문이면 같은 id다.
- 다시 올리기 리포트에 절을 하나 더한다: 올리기 전후 질문 id를 비교해 "새로 생긴 질문 N(예: 연도 불일치 Eloundou 2023) · 저절로 닫힌 질문 M · 답했지만 원고에 아직 그대로 K".
- alias·비인용 용어는 이미 판을 넘어 유지된다(refs는 사람 소유, 용어는 프로젝트 파일).

## 비용·시기 요약

| 항목 | 비용 | 권장 시기 |
|---|---|---|
| questions.py(판별 모으기 + 오탐 두 개 수정) + `book_questions` | 중간 | P1, 온보딩 뒤 첫 작업 |
| `book_answer` + `answers.md` | 중간 | 바로 다음 |
| 웹 `/questions`(조회) | 낮음 | questions.py와 함께 |
| 다시 올리기 리포트 "새로 생긴 질문" 절 | 낮음 | questions.py와 함께 |
| `book_issues` 짧은 보기 | 낮음 | 별건, 필요하면 |
| Word 코멘트로 돌려주기 | 높음 | P2 |

## Result (예정 — 구현할 때 확인할 것)

- father-trial에서 `book_questions`가 18곳을 돌려주고, 저자 보고서 2·3절과 같은 내용이다(오탐 두 개는 없어진다). 응답이 3,000토큰 안이다.
- `book_answer`로 translit·ab·unlinked에 답하면 질문이 닫히고 outline 수가 바뀐다. year·dup은 "원고 반영 대기"가 되고, 고친 판을 올리면 닫힌다(합성 두 판으로 테스트).
- 다시 올리기 리포트에 새로 생긴 질문과 닫힌 질문이 나온다(`reupload-trial-pdf`의 10/02 PDF → 최신본에서 Eloundou 연도·IEA 중복·Hsieh 두 편·셰 등(2019)이 새 질문).

> 대안을 버린 이유: 질문을 저장해 두면 판이 바뀔 때마다 맞추는 일이 생긴다. 지금 원고와 refs에서 매번 계산하고 답만 파일에 남기면, 다시 올리기와 결정 #28(추정은 저장하지 않고 확정만 alias로)에 그대로 맞는다.
