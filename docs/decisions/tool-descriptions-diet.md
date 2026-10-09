# 도구 설명 줄이기(점검 26) — 2026-10-09, 사용자 요청(점검 후속 B)

## Problem

Claude는 도구를 고를 때마다 23개 도구의 설명과 입력 스키마를 읽는다. 배포본(`p1-followup-a`)의 도구 목록은 9,218토큰
(설명 4,635 · 스키마 4,474 · 이름 109, `private/tmp/measure_tools.py` 추정: 비ASCII 1자 = 1토큰, ASCII 3자 = 1토큰)이었고,
후속 B의 입력 상한(15-6)·장 번호 범위(15-2)를 스키마에 실으면서 9,356토큰으로 늘었다. 목표는 −30%(6,500 안팎).
조건: 뜻이 바뀌는 줄임 금지("저자가 … 분명히 말했을 때만", 용어집 이름, 인자 뜻), 내부 이름·옛 이름 금지 유지, instructions는 손대지 않음.

## Action

- 설명: 점검 보고서 26절의 제안안(`private/tmp/audit/diet_proposal.json`)을 바탕으로, 뜻이 줄어든 곳은 되살렸다
  (category_put의 title_by 값 뜻 "저자가 말한 제목 author, Claude가 지은 제목 ai", category_edit의 "쓸 부분을 더해도 원문 확인 표시는 그대로").
  뺀 것: instructions와 겹치는 규칙 설명(제목 규칙 → 규칙 10), 같은 설명 두 번(unverified_cites), 스키마 enum이 이미 말하는 값 나열, 결과 상세(리포트·자리표시자).
  더한 것(후속 B의 바뀐 동작, 짧게): category_edit 한 번에 한 가지·쓸 부분마다 reason, category_search 낱말 여럿은 모두 맞는 글만,
  book_import 같은 파일 수정본은 멈춤, idea_add_conversation .md·.txt, files_list '이미 가져옴'.
  시험이 고정한 문장(category_put·category_trash·book_write_chapter 첫 문장들, read·write_chapter의 "null은 아직 검사 전"·"[]는 검사했고")은 그대로.
- 스키마: `server.plain_schema`가 도구 조립 뒤 'title' 주석(예: "Item Id")과 `"default": null`만 뺀다. 이름이 title인 인자(값이 스키마)·값 있는 기본값("open", 50)은 그대로.
  입력 검증은 SDK의 pydantic 모델이 따로 하므로 동작은 같다. Optional의 `anyOf[…, null]`은 남겼다(시험·클라이언트의 null 전송).
- 대안: anyOf까지 정리하면 −1,200토큰 더(약 5,200)지만 클라이언트가 null을 보낼 때의 검증을 확인해야 해서 하지 않았다.

## Result

도구 목록 9,218(배포본) → 9,356(상한 추가 뒤) → **6,359토큰(배포본 대비 −31%)**: 설명 4,635 → 3,151, 스키마 4,474(상한 추가 뒤 4,612) → 3,099.
instructions 2,437토큰 그대로. 커넥터 재연결이 필요하다(설명·스키마가 바뀜). 시험: `tests/test_author_terms.py`(내부·옛 이름), `tests/test_followup_b.py::test_plain_schema`.

도구별(설명 · 스키마 · 합계, 도구마다 따로 어림해 합이 1~20토큰 다를 수 있다):

| 도구 | 설명 | 스키마 | 합계 |
|---|---:|---:|---:|
| book_decide | 52 → 40 | 80 → 56 | 136 → 100 |
| book_issue_add | 68 → 48 | 151 → 115 | 224 → 168 |
| book_issue_close | 46 → 36 | 111 → 74 | 163 → 116 |
| book_export | 65 → 43 | 89 → 53 | 158 → 100 |
| book_import | 563 → 322 | 225 → 157 | 792 → 483 |
| book_outline | 167 → 119 | 58 → 33 | 229 → 156 |
| book_read_chapter | 275 → 169 | 84 → 62 | 365 → 237 |
| book_write_chapter | 350 → 193 | 210 → 153 | 566 → 352 |
| book_issues | 264 → 169 | 273 → 199 | 541 → 372 |
| book_document | 233 → 165 | 294 → 194 | 532 → 364 |
| ref_import_bibliography | 203 → 151 | 113 → 69 | 324 → 228 |
| ref_check | 125 → 71 | 90 → 67 | 218 → 141 |
| book_questions | 192 → 142 | 149 → 106 | 346 → 253 |
| book_answer | 207 → 123 | 127 → 88 | 338 → 215 |
| idea_add_conversation | 130 → 102 | 178 → 116 | 315 → 225 |
| category_list | 91 → 73 | 56 → 32 | 152 → 110 |
| category_create | 214 → 138 | 239 → 166 | 458 → 309 |
| category_edit | 353 → 259 | 640 → 449 | 998 → 713 |
| category_put | 469 → 325 | 798 → 581 | 1271 → 910 |
| category_search | 239 → 176 | 260 → 175 | 504 → 356 |
| category_trash | 143 → 125 | 174 → 109 | 322 → 239 |
| category_title_default | 92 → 68 | 59 → 39 | 159 → 115 |
| files_list | 102 → 101 | 23 → 12 | 129 → 117 |

## 도구별 설명 전·후 전문

### book_decide

- 전(52토큰): 책에 대한 결정을 기록한다(D번호, 다시 쓰지 않는 일련번호). 결정은 decisions.md에 쌓이고 outline에 최근 10개가 보인다.
- 후(40토큰): 책에 대한 결정을 기록한다(D번호, 다시 쓰지 않는 일련번호). 최근 10개가 outline에 보인다.

### book_issue_add

- 전(68토큰): 확인 요청(열린 문제)을 남긴다. chapter_number로 장을 지정할 수 있다. 사용자가 남기라고 한 것이면 origin=user, 에이전트가 스스로 발견한 것이면 origin=agent.
- 후(48토큰): 확인 요청(열린 문제)을 남긴다. chapter_number: 장. origin: 저자가 남기라고 했으면 user, 스스로 발견했으면 agent.

### book_issue_close

- 전(46토큰): 확인 요청을 닫는다. id는 'I3' 또는 '3'. note에 어떻게 해결했는지 쓴다. 번호는 닫아도 다시 쓰지 않는다.
- 후(36토큰): 확인 요청을 닫는다. id는 'I3' 또는 '3', note에 해결 방법. 번호는 다시 쓰지 않는다.

### book_export

- 전(65토큰): 장들을 차례대로 합쳐 docx를 만들고 파일 위치를 돌려준다. path는 파일 이름만 쓴다(프로젝트 exports/ 아래 저장). 코멘트·그림은 복원하지 않는다.
- 후(43토큰): 장들을 합쳐 docx를 만든다(path는 파일 이름만, exports/에 저장). 코멘트·그림은 복원하지 않는다.

### book_import

- 전(563토큰): 올린 문서 파일(docx, 없으면 pdf)을 가운데 노드의 책으로 가져온다(새 프로젝트, 또는 project_id가 올린 문서가 없는 프로젝트면 그 가운데 노드). path에는 files_list에 보이는 이름을 준다(올린 파일 이름, 게시판 글의 첨부는 '첨부:<id>'). 저자가 올린 문서 없이 새 프로젝트를 만들자고 하면 path 없이 title만 준다(문서는 나중에 같은 project_id로 가져온다). '제N부'·'제N장' 제목으로 장을 나누고, Word 코멘트는 확인 요청(import_comment, kind=citation|fact|general)으로, 참고문헌은 원문 확인 전의 문헌 글로 넣는다. 표는 칸의 글까지 markdown 표로 싣고, 그림·수식은 [그림 N]·[수식] 자리표시자로 남기며 원본은 original/에 복사한다. 원본 파일(Word 등)에서 고친 수정본을 올릴 때는 new_edition=true와 그 책의 project_id를 준다: 본문이 바뀐 장만 바꾸고(수정본 번호 E2, E3… 기록), 같은 코멘트는 다시 넣지 않으며, 올린 문서에서 사라진 코멘트는 '해결됐을 수 있음'으로 표시만 한다. 결정·직접 남긴 확인 요청·다른 책의 글은 그대로다. 장 제목이 30% 미만으로 겹치면 다른 책으로 보고 멈춘다(맞으면 force=true). replace=true는 기존 프로젝트(결정·확인 요청 포함)를 휴지통으로 옮기고 새로 만드니 수정본에 쓰지 않는다. title·subtitle을 비우면 문서(파일 속성·표지)에서 제목·부제·영문 제목을 읽는다. 리포트(장·부 수, 분할 못 한 구간, 코멘트 분류, 참고문헌 파싱)와 장 매핑표를 돌려준다.
- 후(322토큰): 올린 문서(docx, 없으면 pdf)를 새 프로젝트(또는 올린 문서가 없는 project_id)의 가운데 노드로 가져온다. path: files_list의 이름(첨부는 '첨부:<id>'). 문서 없이 프로젝트만 만들면 path 없이 title. '제N부'·'제N장'으로 장을 나누고, Word 코멘트는 확인 요청, 참고문헌은 원문 확인 전 문헌 글로 넣는다. 수정본은 new_edition=true와 그 책의 project_id: 바뀐 장만 바꾸고(E2, E3…), 같은 코멘트는 다시 넣지 않고, 사라진 코멘트는 '해결됐을 수 있음' 표시만 한다(결정·직접 남긴 확인 요청·다른 책은 그대로). 마지막 수정본과 같은 파일이거나 장 제목이 30% 미만 겹치면 멈춘다(맞으면 force=true). replace=true는 기존 프로젝트를 통째 휴지통으로 보내니 수정본에 쓰지 않는다. title·subtitle을 비우면 문서에서 읽는다. 리포트와 장 매핑표를 돌려준다.

### book_outline

- 전(167토큰): 모든 올린 문서 작업의 첫 호출(저자가 '전체'라고 부르는 책 전체 현황). 첫 줄에 프로젝트, 장 목록(장별 상태·글자수·확인 요청 수·미확인 인용 수 집계), 직접 남긴(user·agent) 열린 확인 요청, 최근 결정 10개, 최근 변경 5개를 3,000 토큰 이하로 돌려준다. 코멘트 유래 확인 요청은 건수만 싣는다(book_issues로 조회). 본문은 담지 않는다. project_id를 생략하면 가장 최근 프로젝트.
- 후(119토큰): 모든 올린 문서 작업의 첫 호출(저자의 '전체'). 프로젝트, 장 목록(상태·글자수·확인 요청·미확인 인용 수), 직접 남긴 열린 확인 요청, 최근 결정 10·변경 5를 3,000토큰 이하로. 코멘트 유래 확인 요청은 건수만(book_issues). 본문 없음. project_id가 없으면 최근 프로젝트.

### book_read_chapter

- 전(275토큰): 장 하나를 읽는다. number는 장 번호다: 제N장은 N, 서장 0, 맺음 90, 부록 N은 90+N, 제N부 들어가며는 100+N(outline에서 번호 없는 장 옆 괄호의 숫자). JSON: content(본문 markdown만), title, status, part_number, version, last_note, unverified_cites, open_issues(이 장의 열린 확인 요청. ¶N은 코멘트가 걸린 문단 번호(content의 빈 줄로 나눈 N번째 문단). [AI 확인 요청]은 AI가 문서에 단 코멘트라 저자에게도 그렇게 알린다). 필요한 장만 읽는다. unverified_cites: 인용 게이트(ref_check) 결과 중 verified가 아닌 인용 목록({key, status: unverified|unknown, count, cited_as}). null은 아직 검사 전, []는 검사했고 미확인 인용이 없다는 뜻. needs_source는 본문의 [출처 필요: …] 표시 수.
- 후(169토큰): 장 하나를 읽는다(필요한 장만). number: 제N장 N, 서장 0, 맺음 90, 부록 N은 90+N, 제N부 들어가며 100+N(outline 괄호 숫자). JSON: content(본문만), title, status, part_number, version, last_note, needs_source, unverified_cites(원문 확인이 안 된 인용 {key, status, count, cited_as}. null은 아직 검사 전, []는 검사했고 없음), open_issues(¶N은 content의 N번째 문단. [AI 확인 요청]은 AI가 단 코멘트라 저자에게도 그렇게 알린다).

### book_write_chapter

- 전(350토큰): 저자가 'Magus의 올린 문서에 저장'하라고 분명히 말했을 때만 부른다. 넣을 곳을 되묻는 선택지에도 올린 문서를 넣지 않는다. 그 밖에는 장 수정안을 대화에서 제안하고 저자가 원본 파일에 반영한다. 장 하나를 Magus의 올린 문서에 저장한다(올린 문서의 원본은 저자의 파일이라, 다음 수정본을 올리면 저자 파일 내용으로 바뀐다). content는 본문만(front matter 없이). 이전 본문은 versions/에 보관되고 버전이 1 오른다. note에 무엇을 바꿨는지 쓴다. 없는 번호면 새 장을 만든다(title로 제목 지정). 제목·상태는 title·status 인자로만 바꾼다. status는 draft|revising|done. 빈 본문은 거부한다. unverified_cites: 인용 게이트(ref_check) 결과 중 verified가 아닌 인용 목록({key, status: unverified|unknown, count, cited_as}). null은 아직 검사 전, []는 검사했고 미확인 인용이 없다는 뜻. needs_source는 본문의 [출처 필요: …] 표시 수.
- 후(193토큰): 저자가 'Magus의 올린 문서에 저장'하라고 분명히 말했을 때만 부른다. 넣을 곳을 되묻는 선택지에도 올린 문서를 넣지 않는다. 그 밖에는 수정안을 대화로 내고 저자가 원본 파일에 반영한다. 장 하나를 저장한다(다음 수정본이 오면 저자 파일 내용으로 바뀐다). content는 본문만, note에 바꾼 것. 이전 본문은 versions/로, 버전 +1. 없는 번호면 새 장(title). 빈 본문은 거부. 응답: unverified_cites(null은 아직 검사 전, []는 검사했고 없음)·needs_source.

### book_issues

- 전(264토큰): 확인 요청 목록(조회 전용). status=open|closed|all, chapter_number, origin=import_comment|user|agent, kind=citation(문헌 지목)|fact(사실·수치 확인)|general로 거른다. 한 줄에 하나: 번호·상태·장·출처·종류(citation이면 →ref_key 후보)·내용. 출처는 user·agent·문서 코멘트(작성자)·AI 확인 요청(작성자)이다. AI 확인 요청은 AI가 문서에 단 코멘트라 저자에게 전할 때도 AI의 확인 요청이라고 밝힌다. possibly_resolved=true면 수정본을 올린 뒤 올린 문서에서 코멘트나 걸린 문장이 사라져 '해결됐을 수 있음'으로 표시된 것만 보인다(자동으로 닫지 않는다. 저자에게 확인하고 book_issue_close로 닫는다). limit 기본 50, 최대 200.
- 후(169토큰): 확인 요청 목록(조회 전용). status·chapter_number·origin·kind(citation 문헌 지목|fact 사실·수치|general)로 거른다. 한 줄: 번호·상태·장·출처·종류(→ref_key)·내용. 'AI 확인 요청'은 AI가 단 코멘트라 저자에게도 그렇게 밝힌다. possibly_resolved=true: 수정본 뒤 코멘트·걸린 문장이 사라져 '해결됐을 수 있음'인 것만(자동으로 닫지 않는다. 저자 확인 뒤 book_issue_close). limit 기본 50, 최대 200.

### book_document

- 전(233토큰): 저자가 올린 문서에서 읽기용 문서를 만들어 책장에 넣으라고 분명히 말했을 때만 부른다. kind=출처 확인 문서: 질문·본문 불일치·사실 확인 요청·우선 확인 문헌·장별 미확인 수·바뀐 점을 서버가 데이터로 만든다(Claude는 그 수치·목록을 쓰거나 preface에 옮기지 않는다). preface: 저자가 원하면 짧은 머리말(AI가 쓴 것으로 표시). project_id: 기준 문서(없으면 최근). node: 그 프로젝트 지도의 노드(없으면 가운데). 제목은 글과 같은 규칙. document_id를 주면 그 문서를 지금 올린 문서로 다시 만든다(이전 것은 이력으로 남는다).
- 후(165토큰): 저자가 올린 문서에서 읽기용 문서를 만들어 책장에 넣으라고 분명히 말했을 때만 부른다. kind=출처 확인 문서: 내용(질문·불일치·사실 확인·우선 문헌·장별 미확인 수·바뀐 점)은 서버가 만든다. Claude는 그 수치를 옮기지 않고, 저자가 원하면 preface(머리말, AI 표시)만. node가 없으면 가운데. 제목은 글과 같은 규칙. document_id면 지금 문서로 다시 만든다(이전 것은 이력).

### ref_import_bibliography

- 전(203토큰): 참고문헌 목록 텍스트(한 줄에 한 문헌)를 원문 확인 전의 문헌 글로 넣는다(book을 주면 그 책, 없으면 그 프로젝트의 문헌이 든 책). key는 첫 저자 성(소문자 영문)+연도(예: daeschler2006)이고, '[국역: …]'이 있으면 한글 성+연도를 aliases에 넣는다. 이미 있는 key는 건드리지 않는다(다른 프로젝트에만 있던 문헌이면 「내 서재」로 옮기고 두 지도에 연결 노드를 붙인다). 파싱 실패 줄은 raw로 보관하고 리포트한다. project: 넣을 프로젝트(instructions의 프로젝트 규칙). 
- 후(151토큰): 참고문헌 텍스트(한 줄에 한 문헌)를 원문 확인 전 문헌 글로 넣는다(book, 없으면 그 프로젝트의 문헌 책). key는 첫 저자 성(영문 소문자)+연도, '[국역: …]'은 한글 성+연도를 aliases에. 있는 key는 그대로(다른 프로젝트에만 있으면 「내 서재」로 옮기고 연결 노드를 붙인다). 파싱 실패 줄은 raw로 보관·리포트. project: instructions의 프로젝트 규칙.

### ref_check

- 전(125토큰): 장 본문의 인용을 문헌 글과 대조한다. JSON: verified(원문 확인) / unverified(원문 확인 전) / unknown(문헌 글에 없음) 세 목록과 needs_source([출처 필요: …] 표시 수). 그 프로젝트와 연결 노드의 문헌만 본다. 인용 표기: (Daeschler, Shubin & Jenkins, 2006), Clack(2012), Hu et al.(2023), 갤러(2022), (헨릭, 2016).
- 후(71토큰): 장 본문의 인용을 문헌 글과 대조한다. JSON: verified(원문 확인)/unverified(원문 확인 전)/unknown(문헌 글에 없음)과 needs_source. 범위는 그 프로젝트와 연결 노드의 문헌.

### book_questions

- 전(192토큰): 저자만 답할 수 있는 인용 질문 목록(조회 전용): 연도 불일치(year), 참고문헌에만 있음(bibonly), 한글 표기 추정(translit), 연도 a/b 모호(ab), 같은 저자·연도 두 편(pair), 미연결 표기(unlinked), 중복 서지(dup). 질문은 매번 지금 올린 문서와 문헌에서 계산한다(수정본을 올리면 저절로 새 문서 기준). 본문은 싣지 않고 본문 표기와 장만 싣는다. status=open(기본, 아직 답 없음)|waiting(답했고 Word 수정 대기)|all. 질문마다 [id]와 선택지 코드가 있다.
- 후(142토큰): 저자만 답할 수 있는 인용 질문 목록(조회 전용): year 연도 불일치·bibonly 참고문헌에만·translit 한글 표기 추정·ab 연도 a/b·pair 같은 저자·연도 두 편·unlinked 미연결·dup 중복 서지. 매번 지금 문서·문헌에서 계산한다. 본문 대신 표기와 장만. status=open(기본)|waiting(답함, Word 수정 대기)|all. 질문마다 [id]와 선택지 코드.

### book_answer

- 전(207토큰): 저자가 그 질문에 분명히 답했을 때만 부른다. Claude가 짐작해서 답하지 않는다. question_id는 book_questions의 [ ] 안 id, choice는 그 질문의 선택지 코드다(ref:<key>는 다른 문헌을 고를 때 그 문헌의 key). 본문 표기를 문헌에 잇는 답과 '사람 이름이 아니다'는 바로 반영되고 수가 다시 계산된다. 'Word에서'라고 적힌 답은 결정으로 남는다(저자가 Word에서 고친 뒤 수정본을 올리면 질문이 사라진다). note에는 저자의 말을 짧게 적는다. 답은 올린 문서와 함께 남아 다시 묻지 않는다.
- 후(123토큰): 저자가 그 질문에 분명히 답했을 때만 부른다(짐작해서 답하지 않는다). question_id: book_questions의 [id], choice: 선택지 코드(ref:<key>는 다른 문헌). 표기 잇기·'사람 이름 아님'은 바로 반영되고, 'Word에서' 답은 결정으로 남는다(수정본이 오면 질문이 사라진다). note: 저자의 말을 짧게.

### idea_add_conversation

- 전(130토큰): 대화 기록 markdown을 발화 단위로 나눠 책(book)에 글로 넣는다. markdown 본문 또는 올린 .md 파일 이름(path) 중 하나. 마커: **사용자:**/**Claude:**, 질문:/답변:, '> 인용' 뒤의 **Claude 요지**. 사용자 발화 → author=me, 바로 뒤 AI 발화 → author=ai(응답한 발화를 parent_id로). 리포트: me N건, ai N건, 분리 실패 구간.
- 후(102토큰): 대화 기록 markdown(본문, 또는 올린 .md·.txt 이름 path)을 발화로 나눠 책(book)에 글로 넣는다. 마커: **사용자:**/**Claude:**, 질문:/답변:, '> 인용' 뒤 **Claude 요지**. 사용자 → me, 바로 뒤 AI → ai(parent_id). 리포트: me·ai 건수, 분리 실패 구간.

### category_list

- 전(91토큰): 프로젝트마다 지도(노드·선·연결 노드)와 노드에 꽂힌 책(글 수, [ ]는 컨텍스트 이름), 자주 쓰는 컨텍스트, 제목 기본값. '지도·책장 보여 줘', 넣을 곳을 묻기 전에 부른다. project를 주면 그 프로젝트만.
- 후(73토큰): 프로젝트마다 지도(노드·선·연결 노드), 노드의 책(글 수, [ ]는 컨텍스트), 자주 쓰는 컨텍스트, 제목 기본값. '지도·책장 보여 줘'와 넣을 곳을 묻기 전에 부른다.

### category_create

- 전(214토큰): 저자가 새 책이나 노드를 만들자고 분명히 말했을 때만 부른다(이름을 확인받은 뒤). template: 빈 책·인물·사례·수치·용어(책. 템플릿마다 칸 몇 개) · 노드 · 연결 노드(다른 프로젝트의 노드를 잇는다. name에 '프로젝트 · 노드'). node: 책을 꽂을 노드(없으면 이름이 같은 새 노드). context: 붙일 컨텍스트(자주 쓰는 컨텍스트 이름이나 저자가 말한 글, 순서대로). color: 색 이름(빨강·파랑·겨자 등) 또는 #RRGGBB. 책 이름은 12자까지. project: 넣을 프로젝트(instructions의 프로젝트 규칙). 
- 후(138토큰): 저자가 새 책이나 노드를 만들자고 분명히 말했을 때만 부른다(이름을 확인받은 뒤). template: 빈 책·인물·사례·수치·용어(칸이 다름)·노드·연결 노드(name에 '프로젝트 · 노드'). node: 꽂을 노드(없으면 같은 이름의 새 노드). context: 자주 쓰는 컨텍스트 이름이나 글. color: 색 이름 또는 #RRGGBB. 책 이름 12자까지.

### category_edit

- 전(353토큰): 저자가 책·노드의 이름·색·컨텍스트·위치나 선, 문헌 글의 원문 확인 표시·쓸 부분, 또는 글의 스크랩을 바꾸라고 분명히 말했을 때만 부른다. book(책 이름) 또는 node(노드 이름). context: 새 컨텍스트 목록(자주 쓰는 컨텍스트 이름이나 글, []이면 뗀다). move_to: 책을 옮길 노드('프로젝트 · 노드'나 프로젝트). undo_move=true: 마지막 옮기기 되돌리기. node와 함께 link=이을 노드, unlink=끊을 노드. 같은 이름이 여러 프로젝트에 있으면 project. checked=true|false와 item_id(문헌 글 key): 원문 확인 표시를 붙이거나 뗀다(저자가 그렇게 말했을 때만. 쓸 부분·서지는 그대로). scrap=true|false와 item_id(글 id 또는 문헌 글 key): 글을 스크랩(★)하거나 뗀다(저자가 '스크랩해 줘'라고 했을 때만). parts([{text, reason, where}])와 item_id(문헌 글 key): 저자가 고른 대목을 그 문헌 글의 쓸 부분으로 더한다(원문 확인 표시는 그대로).
- 후(259토큰): 저자가 책·노드(이름·색·컨텍스트·위치·선)나 글(원문 확인 표시·쓸 부분·스크랩)을 바꾸라고 분명히 말했을 때만 부른다. 한 번에 한 가지만. 대상은 book 또는 node(같은 이름이 여러 프로젝트에 있으면 project). context: 새 목록([]이면 뗌). move_to: '프로젝트 · 노드'나 프로젝트, undo_move: 마지막 옮기기 되돌리기. node와 link/unlink: 선 잇기·끊기. item_id(문헌 글 key)와 checked: 원문 확인 표시 붙이기·떼기, parts([{text, reason, where}], 쓸 부분마다 reason): 저자가 고른 대목을 쓸 부분으로 더함(원문 확인 표시는 그대로). item_id(글 id·key)와 scrap: 스크랩(★) 켜기·끄기('스크랩해 줘'일 때만).

### category_put

- 전(469토큰): 글 넣기. 저자가 그 책에 넣으라고 분명히 말했을 때만 부른다. 넣을 책이 대화에서 분명하지 않으면 부르지 말고 책 이름과 컨텍스트를 보여 주며 묻는다(category_list). item_id를 주면 그 글을 고친다. 응답 머리의 컨텍스트를 따른다. author: 저자의 말이면 me, Claude가 쓴 글(요약·설명)이면 ai. reason(이유)·where(위치: 출전·쪽)·tags·fields(그 책의 칸)·chapters(장 번호)는 저자가 말한 것만 넣고 지어내지 않는다. 문헌이면 source에 서지({authors, year, title…} 또는 {key}). checked=true는 저자가 원문을 읽고 확인한 것이고 parts([{text, reason, where}], 원문에서 고른 대목) 하나 이상이 필요하다. 인용 점검은 checked 글만 확인으로 본다. file: 원문 파일(올린 파일 이름), aliases: 한글 표기(예: 갤러2022). 제목: 제목을 넣을 때는 title_by를 반드시 함께 준다(저자가 말한 제목이면 author, Claude가 지었으면 ai). 저자가 제목을 말하지 않았으면 저장하기 전에 직접 지을지·지어 드릴지·비워 둘지 묻는다(저자의 제목 기본값이 정해져 있으면 묻지 않고 따른다. category_list에 보인다). 비워 두기로 했으면 untitled=true. 저자가 '앞으로는 …'이라고 정하면 category_title_default로 기본값을 저장한다. 
- 후(325토큰): 글 넣기. 저자가 그 책에 넣으라고 분명히 말했을 때만 부른다. 넣을 책이 대화에서 분명하지 않으면 부르지 말고 책 이름과 컨텍스트를 보여 주며 묻는다(category_list). item_id면 그 글을 고친다. 응답 머리의 컨텍스트를 따른다. author: 저자의 말 me, Claude가 쓴 글 ai. reason·where(출전·쪽)·tags·fields·chapters는 저자가 말한 것만. 문헌이면 source(서지 {authors, year, title…} 또는 {key}). checked=true(저자가 원문을 읽고 확인)는 parts(원문에서 고른 대목) 하나 이상 필요, 인용 점검은 checked만 확인으로 본다. file: 원문 파일(올린 파일 이름), aliases: 한글 표기(갤러2022). 제목을 넣으면 title_by도 반드시(저자가 말한 제목 author, Claude가 지은 제목 ai). 제목을 말하지 않았으면 instructions의 제목 규칙(기본값이 없으면 먼저 묻고, 비우기로 했으면 untitled=true).

### category_search

- 전(239토큰): 책의 글에서 찾는다(문헌 글은 서지·key·첨부 이름과 쓸 부분, full=true면 원문 전체도. 원문 확인 전 문헌은 '미확인'으로 보이고 인용하지 않는다). book을 주면 그 책만, project를 주면 그 프로젝트와 연결 노드. author=me|ai|all(기본, 저자의 말을 먼저). k=8. scrap_only=true면 저자가 스크랩(★)한 글만(query 없이 부르면 스크랩 전체, 최근 것부터). 결과는 책마다 컨텍스트와 함께. 첨부(docx·pdf·txt·md)에서 뽑은 글자도 찾는다(맞은 곳 앞뒤와 쪽). attachment='첨부:<id>'와 page=N이면 그 첨부의 글자를 3,000자씩 한 쪽 읽는다(한 번에 전체를 읽지 않는다).
- 후(176토큰): 책의 글에서 찾는다(문헌 글은 서지·key·첨부 이름·쓸 부분, full=true면 원문까지. 원문 확인 전 문헌은 '미확인'이고 인용하지 않는다). 낱말 여럿은 모두 맞는 글만. book: 그 책만, project: 그 프로젝트와 연결 노드. author 기본 all(저자의 말 먼저). scrap_only=true: 스크랩(★)만(query 없으면 전체, 최근순). 첨부(docx·pdf·txt·md) 글자도 찾는다. attachment='첨부:<id>'와 page=N: 그 첨부를 3,000자씩 한 쪽 읽는다.

### category_trash

- 전(143토큰): 저자가 그 글·책·노드를 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다. item_id면 그 글(응답한 글도 함께), 없으면 책 통째(글 수를 말하고 확인받은 뒤), node만 주면 그 노드(책이 있으면 먼저 옮긴다). 문헌 글과 문헌이 든 책은 옮기지 않는다. 휴지통으로 옮길 뿐 지우지 않는다. note: 이유.
- 후(125토큰): 저자가 그 글·책·노드를 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다. item_id: 그 글(응답한 글도), 없으면 책 통째(글 수를 말하고 확인 뒤), node만: 그 노드(책은 먼저 옮긴다). 문헌 글·문헌이 든 책은 옮기지 않는다. 휴지통으로 옮길 뿐. note: 이유.

### category_title_default

- 전(92토큰): 저자가 앞으로 제목을 어떻게 할지 정해 말했을 때만 부른다: '매번 물어봐' → ask, '앞으로는 제목 지어 줘' → ai, '앞으로는 비워 둬' → none. 글을 넣을 때 이 기본값을 따른다(대화가 바뀌어도 서버에 남는다).
- 후(68토큰): 저자가 앞으로의 제목 방식을 정해 말했을 때만 부른다: '매번 물어봐' ask, '앞으로는 지어 줘' ai, '앞으로는 비워 둬' none. 대화가 바뀌어도 서버에 남는다.

### files_list

- 전(102토큰): 저자가 웹에서 올린 파일과 게시판 글에 첨부한 문서(docx·pdf·md·txt) 목록: 이름, 크기, 올린 시각, 쓰임·어느 글. book_import·category_put(file)·idea_add_conversation의 파일 인자에는 여기 나온 **이름만** 준다(게시판 첨부는 '첨부:<id>').
- 후(101토큰): 웹에서 올린 파일과 게시판 글의 첨부 문서(docx·pdf·md·txt) 목록(이름·크기·시각·어느 글, 가져온 문서는 '이미 가져옴'). 파일 인자(book_import·category_put file·idea_add_conversation)에는 여기 나온 이름만 준다(첨부는 '첨부:<id>').

대안을 버린 이유: 스키마의 anyOf null 정리는 토큰을 더 줄이지만 클라이언트가 null을 보내는 경우의 검증 확인이 필요해 이번에는 하지 않았다.
