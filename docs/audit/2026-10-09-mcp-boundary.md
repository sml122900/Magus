# 부록 — MCP 도구 23개 경계값 시험 표(2026-10-09 점검, 15번)

본문: `docs/audit/2026-10-09-code-audit.md` E절. 시험 데이터는 합성(`private/tmp/audit/E-data*`, 사용자 audit·audit2·audit3).

## 경계값 표

총 320건 · 도구 23개 · 내부 오류 10건 · 입력 검증 오류 34건 · ToolError 181건 · ok 95건

'다른 사용자'는 audit2의 id(프로젝트 p2·책 「비밀」·글 id·첨부 id·문헌 hidden2020·문서 id)를 audit로 부른 것. '응답 길이'가 20,000자를 넘으면 굵게 표시.

### files_list (2건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ok | 올린 파일 3개 · 사용 0.2 MB / 한도 1,000.0 MB - 논문.txt · 2 KB · 10-09 16:37 · 논문 전문(category_put file) - 대화.md · 2 KB … | 17 | 471 |
| x=1 | 모르는 인자 | ok | 올린 파일 3개 · 사용 0.2 MB / 한도 1,000.0 MB - 논문.txt · 2 KB · 10-09 16:37 · 논문 전문(category_put file) - 대화.md · 2 KB … | 14 | 471 |

### book_outline (10건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ok | 프로젝트: 닿으려는 종 (합성) (synth) 7장 · 3부 · 736자 · 미확인 문헌 6편 · 미연결 0 · 열린 확인 요청 13 처음 올린 문서 E1 · 마지막 업로드 10-09 16:37(… | 10 | 961 |
| project_id="" |  | ok | 프로젝트: 닿으려는 종 (합성) (synth) 7장 · 3부 · 736자 · 미확인 문헌 6편 · 미연결 0 · 열린 확인 요청 13 처음 올린 문서 E1 · 마지막 업로드 10-09 16:37(… | 4 | 961 |
| project_id="p2" | 다른 사용자 프로젝트 | ok | 프로젝트 'p2'가 없습니다. | 0 | 16 |
| project_id="../audit2/projects/p2" |  | ok | 프로젝트 '../audit2/projects/p2'가 없습니다. | 0 | 35 |
| project_id="common" | 내 서재 id | ok | 프로젝트 'common'가 없습니다. | 0 | 20 |
| project_id=<200k자> |  | ok | 프로젝트 '가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 2 | **200,014** |
| project_id=123 | 잘못된 형 | 입력 검증 오류 | 1 validation error for book_outlineArguments project_id Input should be a valid string [type=string_type, inp… | 0 | 256 |
| (없음) | 쓰기 경계값 뒤 outline | ok | 프로젝트: 닿으려는 종 (합성) (synth) 8장 · 3부 · 200,459자 · 미확인 문헌 5편 · 미연결 0 · 열린 확인 요청 12 처음 올린 문서 E1 · 마지막 업로드 10-09 16… | 16 | 1,144 |
| (없음) | 쓰기 경계값 뒤 outline(장 제목 2… | ok | 프로젝트: 닿으려는 종 (합성) (synth) 8장 · 3부 · 200,459자 · 미확인 문헌 5편 · 미연결 0 · 열린 확인 요청 12 처음 올린 문서 E1 · 마지막 업로드 10-09 16… | 48 | 1,248 |
| (없음) | 프로젝트 늘린 뒤 | ok | 프로젝트: 둘째 (second) 부제: 가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 55 | **200,384** |

### book_read_chapter (14건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| number=1 |  | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 9 | 1,876 |
| number=0 |  | ToolError | 0장이 없습니다. 있는 장: 1, 2, 3, 4, 5, 6, 7 | 0 | 75 |
| number=-1 |  | ToolError | -1장이 없습니다. 있는 장: 1, 2, 3, 4, 5, 6, 7 | 0 | 76 |
| number=101 |  | ToolError | 101장이 없습니다. 있는 장: 1, 2, 3, 4, 5, 6, 7 | 0 | 77 |
| number=1000000 |  | ToolError | 1000000장이 없습니다. 있는 장: 1, 2, 3, 4, 5, 6, 7 | 0 | 81 |
| number=10000000000000000000 |  | **내부 오류** | INTERNAL OverflowError: Python int too large to convert to SQLite INTEGER @ local.py:307 read_chapter | 0 | 38 |
| number=9223372036854775808 |  | **내부 오류** | INTERNAL OverflowError: Python int too large to convert to SQLite INTEGER @ local.py:307 read_chapter | 0 | 38 |
| number=1.5 |  | 입력 검증 오류 | 1 validation error for book_read_chapterArguments number Input should be a valid integer, got a number with a… | 0 | 308 |
| number="3" |  | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 3 | 532 |
| number="삼" |  | 입력 검증 오류 | 1 validation error for book_read_chapterArguments number Input should be a valid integer, unable to parse str… | 0 | 301 |
| number=null |  | 입력 검증 오류 | 1 validation error for book_read_chapterArguments number Input should be a valid integer [type=int_type, inpu… | 0 | 263 |
| number=true |  | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 10 | 1,876 |
| number=1, project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 56 |
| number=1, project_id="../x" |  | ToolError | 프로젝트 '../x'가 없습니다. | 0 | 58 |

### book_issues (12건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 2 | 1,524 |
| status="bad" |  | 입력 검증 오류 | 1 validation error for book_issuesArguments status Input should be 'open', 'closed' or 'all' [type=literal_er… | 0 | 267 |
| limit=0 |  | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 2 | 273 |
| limit=-5 |  | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 2 | 273 |
| limit=10000000000000000000 |  | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 3 | 1,524 |
| limit="x" |  | 입력 검증 오류 | 1 validation error for book_issuesArguments limit Input should be a valid integer, unable to parse string as … | 0 | 288 |
| chapter_number=-1 |  | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 3 | 153 |
| chapter_number=10000000000000000000 |  | **내부 오류** | INTERNAL OverflowError: Python int too large to convert to SQLite INTEGER @ local.py:630 list_issues | 0 | 32 |
| origin="bad" |  | 입력 검증 오류 | 1 validation error for book_issuesArguments origin Input should be 'import_comment', 'user' or 'agent' [type=… | 0 | 277 |
| kind="bad" |  | 입력 검증 오류 | 1 validation error for book_issuesArguments kind Input should be 'citation', 'fact' or 'general' [type=litera… | 0 | 271 |
| possibly_resolved="yes" | 문자열 → bool | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 2 | 153 |
| project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 50 |

### book_questions (5건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ok | 프로젝트: 닿으려는 종 (합성) (synth) · 저자에게 물을 것 23건(열림 23 · 원본 반영 대기 0 · 답함 0) 보기: status=open. 저자가 답하면 book_answer(que… | 33 | 4,324 |
| status="bad" |  | 입력 검증 오류 | 1 validation error for book_questionsArguments status Input should be 'open', 'waiting' or 'all' [type=litera… | 0 | 274 |
| type="bad" |  | 입력 검증 오류 | 1 validation error for book_questionsArguments type Input should be 'year', 'bibonly', 'translit', 'ab', 'pai… | 0 | 310 |
| status="all", type="translit" |  | ok | 프로젝트: 닿으려는 종 (합성) (synth) · 저자에게 물을 것 23건(열림 23 · 원본 반영 대기 0 · 답함 0) 보기: status=all · type=translit(한글 표기 추정)… | 31 | 180 |
| project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 53 |

### book_answer (8건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| question_id="", choice="" |  | ToolError | 지금 올린 문서에 없는 질문이다: . 이미 해결됐거나 id가 다르다. book_questions로 확인한다. | 37 | 94 |
| question_id="없는:id", choice="keep" |  | ToolError | 지금 올린 문서에 없는 질문이다: 없는:id. 이미 해결됐거나 id가 다르다. book_questions로 확인한다. | 35 | 99 |
| question_id=<200k자>, choice="keep" |  | ToolError | 지금 올린 문서에 없는 질문이다: 가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 36 | **200,094** |
| question_id="bibonly:ahlberg2019", choice="bad" |  | ToolError | 선택지가 아니다: 'bad'. 이 질문의 선택지: cite, drop, keep | 37 | 78 |
| question_id="bibonly:ahlberg2019", choice="ref:../../x" |  | ToolError | 선택지가 아니다: 'ref:../../x'. 이 질문의 선택지: cite, drop, keep | 38 | 86 |
| question_id="bibonly:ahlberg2019", choice="keep", note=<200k자> | note 20만 자 | ok | 답을 기록함: [bibonly:ahlberg2019] 그대로 둠. 남은 열린 질문 22건. | 79 | 50 |
| question_id="bibonly:benton2015", choice="keep", project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 50 |
| question_id="bibonly:benton2015" | choice 빠짐 | 입력 검증 오류 | 1 validation error for book_answerArguments choice Field required [type=missing, input_value={'question_id': … | 0 | 261 |

### ref_check (6건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| chapter_number=1 |  | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 10 | 1,089 |
| chapter_number=0 |  | ToolError | 0장이 없습니다. | 1 | 41 |
| chapter_number=-1 |  | ToolError | -1장이 없습니다. | 0 | 42 |
| chapter_number=10000000000000000000 |  | **내부 오류** | INTERNAL OverflowError: Python int too large to convert to SQLite INTEGER @ local.py:307 read_chapter | 0 | 30 |
| chapter_number="x" |  | 입력 검증 오류 | 1 validation error for ref_checkArguments chapter_number Input should be a valid integer, unable to parse str… | 0 | 293 |
| chapter_number=1, project_id="p2" | 다른 사용자 | ToolError | 프로젝트가 없습니다. | 0 | 43 |

### book_decide (5건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| text="" |  | ToolError | 결정 내용이 비어 있다 | 0 | 46 |
| text=" " |  | ToolError | 결정 내용이 비어 있다 | 0 | 46 |
| text=<200k자> | 20만 자 | ok | D1 기록함 (synth): 가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 9 | 136 |
| text=123 |  | 입력 검증 오류 | 1 validation error for book_decideArguments text Input should be a valid string [type=string_type, input_valu… | 0 | 248 |
| text="x", project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 50 |

### book_issue_add (7건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| text="" |  | ToolError | 확인 요청 내용이 비어 있다 | 1 | 52 |
| text=<200k자> | 20만 자 | ok | I14 열림 (synth · user): 가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 23 | 143 |
| text="x", chapter_number=0 |  | ToolError | 0장이 없습니다. | 1 | 46 |
| text="x", chapter_number=-1 |  | ToolError | -1장이 없습니다. | 0 | 47 |
| text="x", chapter_number=10000000000000000000 |  | **내부 오류** | INTERNAL OverflowError: Python int too large to convert to SQLite INTEGER @ local.py:307 read_chapter | 0 | 35 |
| text="x", origin="import_comment" |  | 입력 검증 오류 | 1 validation error for book_issue_addArguments origin Input should be 'user' or 'agent' [type=literal_error, … | 0 | 276 |
| text="x", project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 53 |

### book_issue_close (10건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| id="" |  | ToolError | 확인 요청 번호 형식이 아닙니다: '' (예: I3 또는 3) | 1 | 73 |
| id="I" |  | ToolError | 확인 요청 번호 형식이 아닙니다: 'I' (예: I3 또는 3) | 0 | 74 |
| id="I0" |  | ToolError | I0이 없습니다. book_issues로 번호를 확인하세요. | 10 | 72 |
| id="I-1" |  | ToolError | 확인 요청 번호 형식이 아닙니다: 'I-1' (예: I3 또는 3) | 0 | 76 |
| id="I999999999999999999999999999999" |  | ToolError | I999999999999999999999999999999이 없습니다. book_issues로 번호를 확인하세요. | 4 | 101 |
| id="I²" |  | **내부 오류** | INTERNAL ValueError: invalid literal for int() with base 10: '²' @ tools.py:211 book_issue_close | 1 | 37 |
| id="１" |  | ok | I1 닫음 | 14 | 5 |
| id="I1 " |  | ok | I1 닫음 | 15 | 5 |
| id="I2", note=<200k자> | note 20만 자 | ok | I2 닫음: 가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 32 | **200,007** |
| id="I3", project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 55 |

### book_write_chapter (10건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| number=1, content="", note="x" |  | ToolError | 본문이 비어 있습니다. 장을 지우려는 것이라면 book_issue_add로 남겨 주세요. | 0 | 90 |
| number=1, content="---\ntitle: x\n---\n", note="x" | 앞머리만 | ToolError | 본문이 비어 있습니다. 장을 지우려는 것이라면 book_issue_add로 남겨 주세요. | 0 | 90 |
| number=2, content=<200k자>, note="big" | 본문 20만 자 | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 31 | 326 |
| number=3, content="본문", note="" | note 빈 문자열 | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 18 | 320 |
| number=-1, content="음수 장", note="x", title="음수" |  | ToolError | 장 번호는 0 이상 | 0 | 51 |
| number=10000000000000000000, content="큰 장", note="x" |  | **내부 오류** | INTERNAL OverflowError: Python int too large to convert to SQLite INTEGER @ local.py:727 _index_chapter | 9 | 39 |
| number=999, content="999장", note="x" |  | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 13 | 324 |
| number=4, content="x", note="x", status="bad" |  | 입력 검증 오류 | 1 validation error for book_write_chapterArguments status Input should be 'draft', 'revising' or 'done' [type… | 0 | 285 |
| number=4, content="x", note="x", title=<200k자> | 제목 20만 자 | ok | {"context": "컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서… | 62 | **200,314** |
| number=1, content="x", note="x", project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 57 |

### book_export (10건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\synth-2026… | 493 | 188 |
| path="" |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\synth-2026… | 412 | 188 |
| path="../evil.docx" |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\evil.docx … | 455 | 172 |
| path="C:\\Windows\\evil.docx" |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\evil.docx … | 423 | 172 |
| path="a/b.docx" |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\b.docx (코멘… | 394 | 169 |
| path="con.docx" |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\con.docx (… | 400 | 171 |
| path="x" |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\x.docx (코멘… | 388 | 169 |
| path="없는.pdf" |  | ok | docx를 만들었다: C:\project_2026\Magus\private\tmp\audit\E-data\data\users\audit\projects\synth\exports\없는.pdf.doc… | 403 | 174 |
| path=<200k자> |  | **내부 오류** | INTERNAL FileNotFoundError: [Errno 2] No such file or directory: 'C:\\project_2026\\Magus\\private\\tmp\\audi… | 430 | 32 |
| project_id="p2" | 다른 사용자 | ToolError | 프로젝트 'p2'가 없습니다. | 0 | 50 |

### book_import (28건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ToolError | 올린 문서 없이 프로젝트를 만들려면 제목(title)을 준다. 문서를 가져오려면 path에 올린 파일 이름을 준다. | 0 | 98 |
| path="", title="" |  | ToolError | 올린 문서 없이 프로젝트를 만들려면 제목(title)을 준다. 문서를 가져오려면 path에 올린 파일 이름을 준다. | 0 | 98 |
| path="없는.docx" |  | ToolError | 올린 파일에 '없는.docx'이 없다. files_list로 이름을 확인하거나, 저자에게 웹 책장에서 먼저 올려 달라고 한다. | 0 | 104 |
| path="../../audit2/inbox/합성.docx" | 상대 경로 | ToolError | 올린 파일에 '../../audit2/inbox/합성.docx'이 없다. files_list로 이름을 확인하거나, 저자에게 웹 책장에서 먼저 올려 달라고 한다. | 0 | 123 |
| path="C:\\project_2026\\Magus\\private\\tmp\\audit\\E-data\\data\\users\\audit2\\inbox\\합… | 다른 사용자 절대 경로 | ToolError | 올린 파일에 'C:\\project_2026\\Magus\\private\\tmp\\audit\\E-data\\data\\users\\audit2\\inbox\\합성.docx'이 없다. files… | 0 | 186 |
| path="첨부:20261009073748232-93d364" | 다른 사용자 첨부 | ToolError | 게시판 첨부에 '첨부:20261009073748232-93d364'이 없다. files_list로 이름을 확인한다. | 3 | 98 |
| path="첨부:" |  | ToolError | 게시판 첨부에 '첨부:'이 없다. files_list로 이름을 확인한다. | 4 | 74 |
| path="첨부:../../x" |  | ToolError | 게시판 첨부에 '첨부:../../x'이 없다. files_list로 이름을 확인한다. | 3 | 81 |
| path="대화.md", project_id="mdimp" | md 파일 | ToolError | 지원하지 않는 형식: 대화.md (docx 또는 pdf) | 0 | 65 |
| path="논문.txt", project_id="txtimp" | txt 파일 | ToolError | 지원하지 않는 형식: 논문.txt (docx 또는 pdf) | 0 | 66 |
| path="첨부:20261009073747327-fb3abe", project_id="mdatt" | md 첨부 | ToolError | 지원하지 않는 형식: 첨부대화.md (docx 또는 pdf) | 4 | 67 |
| path="합성.docx", project_id="synth" | 이미 있는 id | ToolError | 프로젝트 'synth'가 이미 있다. 같은 책을 Word에서 고쳐 다시 올리는 것이면 수정본으로 올린다(book_import new_edition=true, 웹 '수정본으로 올리기'). 다른 책이… | 14 | 205 |
| path="합성.docx", project_id="../evil" |  | ToolError | project_id='../evil': 영문·숫자·_·-만, 64자 이하, 영문/숫자로 시작 | 14 | 85 |
| path="합성.docx", project_id="common" |  | ToolError | 'common'은 「내 서재」의 id라 작업물 id로 쓸 수 없다 | 12 | 70 |
| path="합성.docx", project_id="한글" |  | ToolError | project_id='한글': 영문·숫자·_·-만, 64자 이하, 영문/숫자로 시작 | 16 | 80 |
| path="합성.docx", new_edition=true | project_id 없음 | ToolError | 수정본으로 올릴 책의 project_id를 주세요(book_outline 첫 줄의 괄호 안). | 0 | 86 |
| path="합성.docx", new_edition=true, project_id="p2" | 다른 사용자 | ToolError | 수정본으로 올릴 프로젝트 'p2'가 없다. 처음 올리는 책이면 수정본이 아니라 임포트한다. | 0 | 84 |
| path="논문.txt", new_edition=true, project_id="synth" | txt 수정본 | ToolError | 지원하지 않는 형식: 논문.txt (docx 또는 pdf) | 0 | 66 |
| path="대화.md", new_edition=true, project_id="synth" | md 수정본 | ToolError | 지원하지 않는 형식: 대화.md (docx 또는 pdf) | 0 | 65 |
| title="x", project_id="../evil" |  | ToolError | project_id='../evil': 영문·숫자·_·-만, 64자 이하, 영문/숫자로 시작 | 0 | 85 |
| title="x", project_id="common" |  | ToolError | 'common'은 「내 서재」의 id라 작업물 id로 쓸 수 없다 | 0 | 70 |
| title=" " |  | ToolError | 올린 문서 없이 프로젝트를 만들려면 제목(title)을 준다. 문서를 가져오려면 path에 올린 파일 이름을 준다. | 0 | 98 |
| title="x", new_edition=true |  | ToolError | 수정본·바꾸기에는 문서 파일(path)이 필요하다. | 0 | 62 |
| path=5 |  | 입력 검증 오류 | 1 validation error for book_importArguments path Input should be a valid string [type=string_type, input_valu… | 0 | 246 |
| path="합성.docx", replace=true, project_id="nope" | 없는 프로젝트 replace | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 1,840 | 1,658 |
| path="합성.docx", new_edition=true, replace=true, project_id="synth" | 둘 다 | ok | 컨텍스트(책 「닿으려는 종 (합성)」): 「원고」 내가 쓰고 있는 책의 원고다. 원본은 내 Word 파일이고, 여기 있는 것은 마지막으로 올린 사본이다. 고칠 곳은 대화에서 제안해 주면 내가 Wo… | 194,059 | **401,215** |
| title=<200k자>, project_id="bigtitle" | 제목 20만 자 | ok | 올린 문서가 없는 프로젝트를 만듦: 「가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 19 | 263 |
| title="둘째", project_id="second", subtitle=<200k자> | 부제 20만 자 | ok | 올린 문서가 없는 프로젝트를 만듦: 「둘째」(second). 지도에 가운데 노드가 있다. 문서는 저자가 가운데 노드의 '책 추가 → 문서 올리기'로 올리거나, book_import(path=올린 … | 27 | 141 |

### book_document (12건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) | 제목 기본값 묻기 | ToolError | 제목을 정하지 않아 저장하지 않았다. 저자의 제목 기본값은 '매번 묻기'다. 저자에게 제목을 직접 지을지, 지어 드릴지, 비워 둘지 묻고 답을 들은 뒤 다시 부른다(직접 → title과 title… | 3 | 262 |
| kind="bad" |  | 입력 검증 오류 | 1 validation error for book_documentArguments kind Input should be '출처 확인 문서' [type=literal_error, input_valu… | 0 | 254 |
| project_id="p2", untitled=true | 다른 사용자 | ToolError | 프로젝트 'p2'가 없다. | 0 | 50 |
| node="없는", untitled=true |  | ToolError | 『닿으려는 종 (합성)』 지도에 '없는' 노드가 없다. 문서는 그 올린 문서의 프로젝트 지도에 둔다. | 2 | 92 |
| node="../x", untitled=true |  | ToolError | 『닿으려는 종 (합성)』 지도에 '../x' 노드가 없다. 문서는 그 올린 문서의 프로젝트 지도에 둔다. | 2 | 94 |
| preface=<200k자>, untitled=true |  | ToolError | 머리말은 2000자까지다. 수치·목록은 넣지 않는다(서버가 만든다). | 0 | 74 |
| document_id="20261009073748422-8bc05f" | 다른 사용자 문서 | ToolError | 문서 20261009073748422-8bc05f가 없다. | 0 | 68 |
| document_id="../x" |  | ToolError | 문서 ../x가 없다. | 0 | 48 |
| title="문서", untitled=false | title_by 없음 | ToolError | 제목을 넣을 때는 title_by를 함께 준다: 저자가 말한 제목이면 author, Claude가 지었으면 ai. 기본값은 없다(저자가 지은 제목이 AI 것으로, 또는 그 반대로 기록되지 않게).… | 1 | 155 |
| title=<200k자>, title_by="author" | 제목 20만 자 | ok | 컨텍스트(책 「가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가」): 「출처 확인 문서」 올린 문서의… | 3,326 | 489 |
| untitled=true, project_id="common" |  | ToolError | 프로젝트 'common'가 없다. | 0 | 54 |
| untitled=true, node="메모" | 다른 노드 | ok | 컨텍스트(책 「닿으려는 종 (합성) 출처 확인 문서」): 「출처 확인 문서」 올린 문서의 인용과 사실 확인 상태를 서버가 정리한 읽기용 문서다. 만든 때의 사진이라 새 수정본이 오면 옛 판 기준이… | 309 | 370 |

### ref_import_bibliography (8건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| text="" |  | ok | 참고문헌 0줄 → 새 문헌 글 0건(원문 확인 전), 이미 있음 0건, 파싱 실패 0줄, key 충돌 0건, 중복 서지 0건, 기존 서지와 다름 0건 확인 요청과의 연결 변경 0건. 모두 원문 확… | 31 | 180 |
| text="\n\n\n" |  | ok | 참고문헌 0줄 → 새 문헌 글 0건(원문 확인 전), 이미 있음 0건, 파싱 실패 0줄, key 충돌 0건, 중복 서지 0건, 기존 서지와 다름 0건 확인 요청과의 연결 변경 0건. 모두 원문 확… | 30 | 180 |
| text=<200k자> | 한 줄 20만 자 | ok | 컨텍스트(책 「참고문헌」): 「논문」 원문을 읽고 모은 논문과 책이다. '원문 확인' 표시가 있는 글만 인용 근거로 쓴다. 표시가 없는 글은 아직 원문을 확인하지 않은 목록(원고의 참고문헌에서 읽… | 166 | 446 |
| text="Kim, A. (2020). Title.", project="p2" | 다른 사용자 | ToolError | 'p2' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 1 | 98 |
| text="Kim, A. (2020). Title.", book="없는" |  | ToolError | '없는' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 문서] · 「닿으려는 종 … | 14 | 173 |
| text="Kim, A. (2020). Title.", book="닿으려는 종 (합성)" |  | ToolError | 「닿으려는 종 (합성)」에는 올린 문서가 들어 있어 글을 넣지 않는다(고칠 곳은 대화로 제안하고, 저자가 원본 파일에서 고친다). 글을 넣을 책을 저자에게 묻는다. | 3 | 137 |
| text="Kim, A. (2020). Title.", book="비밀" | 다른 사용자 책 | ToolError | '비밀' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 문서] · 「닿으려는 종 … | 15 | 173 |
| text=<61k자>, book="참고문헌" | 61k자 1,500줄 | ok | 컨텍스트(책 「참고문헌」): 「논문」 원문을 읽고 모은 논문과 책이다. '원문 확인' 표시가 있는 글만 인용 근거로 쓴다. 표시가 없는 글은 아직 원문을 확인하지 않은 목록(원고의 참고문헌에서 읽… | 18,339 | **108,905** |

### idea_add_conversation (19건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | 입력 검증 오류 | 1 validation error for idea_add_conversationArguments book Field required [type=missing, input_value={}, inpu… | 0 | 244 |
| book="메모" |  | ToolError | markdown(대화 기록 본문)과 path(올린 .md 파일 이름) 중 하나만 준다 | 0 | 91 |
| book="메모", markdown="x", path="대화.md" |  | ToolError | markdown(대화 기록 본문)과 path(올린 .md 파일 이름) 중 하나만 준다 | 0 | 91 |
| book="메모", markdown="" |  | ToolError | markdown(대화 기록 본문)과 path(올린 .md 파일 이름) 중 하나만 준다 | 0 | 91 |
| book="메모", markdown="마커 없음" |  | ToolError | 발화를 하나도 나누지 못했다. 지원 마커: **사용자:**/**Claude:**, 질문:/답변:, > 인용 뒤 **Claude 요지** me 0건, ai 0건, 분리 실패 구간 1개 - 1행: 마… | 7 | 157 |
| book="메모", markdown=<200k자> | 마커 없는 20만 자 | ToolError | 발화를 하나도 나누지 못했다. 지원 마커: **사용자:**/**Claude:**, 질문:/답변:, > 인용 뒤 **Claude 요지** me 0건, ai 0건, 분리 실패 구간 1개 - 1행: 가… | 6 | 192 |
| book="메모", markdown=<73k자> | 73k자 2,000쌍 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 me 2000건, ai 2000건, 분리 실패 구간 0개 넣음: 「메모」(「닿으려는 종 (합성)」)에 발화 4000개 (origin=-). A… | 25,232 | 149 |
| book="메모", path="합성.docx" | docx 파일 | **내부 오류** | INTERNAL UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd7 in position 10: invalid continuation byte @… | 10 | 42 |
| book="메모", path="첨부:20261009073747306-75eed1" | docx 첨부 | **내부 오류** | INTERNAL UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd7 in position 10: invalid continuation byte @… | 120 | 42 |
| book="메모", path="첨부:20261009073747327-fb3abe" | md 첨부 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 me 10건, ai 10건, 분리 실패 구간 0개 넣음: 「메모」(「닿으려는 종 (합성)」)에 발화 20개 (origin=첨부대화). AI 발… | 265 | 146 |
| book="메모", path="논문.txt" | txt | ToolError | 발화를 하나도 나누지 못했다. 지원 마커: **사용자:**/**Claude:**, 질문:/답변:, > 인용 뒤 **Claude 요지** me 0건, ai 0건, 분리 실패 구간 1개 - 1행: C… | 10 | 192 |
| book="메모", path="../x.md" |  | ToolError | 올린 파일에 '../x.md'이 없다. files_list로 이름을 확인하거나, 저자에게 웹 책장에서 먼저 올려 달라고 한다. | 10 | 114 |
| book="메모", path="첨부:20261009073748251-21d1bb" | 다른 사용자 첨부 | ToolError | 게시판 첨부에 '첨부:20261009073748251-21d1bb'이 없다. files_list로 이름을 확인한다. | 123 | 108 |
| book="닿으려는 종 (합성)", markdown="**사용자:** a\n**Claude:** b" |  | ToolError | 「닿으려는 종 (합성)」에는 올린 문서가 들어 있어 글을 넣지 않는다(고칠 곳은 대화로 제안하고, 저자가 원본 파일에서 고친다). 글을 넣을 책을 저자에게 묻는다. | 12 | 135 |
| book="", markdown="**사용자:** a\n**Claude:** b" |  | ToolError | '' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 문서] · 「닿으려는 종 (합… | 22 | 169 |
| book="비밀", markdown="**사용자:** a\n**Claude:** b" | 다른 사용자 책 | ToolError | '비밀' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 문서] · 「닿으려는 종 … | 23 | 171 |
| book="20261009073748150-6b43e5", markdown="**사용자:** a\n**Claude:** b" | 다른 사용자 책 id | ToolError | '20261009073748150-6b43e5' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…… | 22 | 193 |
| book="메모", markdown="**사용자:** a\n**Claude:** b", origin=<200k자> | origin 20만 자 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 me 1건, ai 1건, 분리 실패 구간 0개 넣음: 「메모」(「닿으려는 종 (합성)」)에 발화 2개 (origin=가가가가가가가가가가가가가가… | 58 | **200,139** |
| book="메모", markdown="**사용자:** a\n**Claude:** b", project="없는" | 없는 프로젝트 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 me 1건, ai 1건, 분리 실패 구간 0개 넣음: 「메모」(「닿으려는 종 (합성)」)에 발화 2개 (origin=-). AI 발화에는 응답… | 36 | 140 |

### category_list (7건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ok | 책장: 프로젝트 2개(내 서재 · 「닿으려는 종 (합성)」(synth)) · 제목 기본값: 매번 묻기 자주 쓰는 컨텍스트(context에 이름으로 붙인다): 「문체」 문학적 부분이 마음에 드는 구… | 119 | 668 |
| project="" |  | ok | 책장: 프로젝트 2개(내 서재 · 「닿으려는 종 (합성)」(synth)) · 제목 기본값: 매번 묻기 자주 쓰는 컨텍스트(context에 이름으로 붙인다): 「문체」 문학적 부분이 마음에 드는 구… | 105 | 668 |
| project="없는" |  | ToolError | '없는' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 17 | 88 |
| project="p2" | 다른 사용자 | ToolError | 'p2' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 15 | 88 |
| project=<200k자> |  | ToolError | '가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 16 | **200,086** |
| project=1 |  | 입력 검증 오류 | 1 validation error for category_listArguments project Input should be a valid string [type=string_type, input… | 0 | 253 |
| (없음) | 프로젝트 늘린 뒤 | ok | 책장: 프로젝트 5개(내 서재 · 「닿으려는 종 (합성)」(synth) · 「닿으려는 종 (합성)」(nope) · 「가가가가가가가가가가가가가가가가가가가가가가가…」(bigtitle) · 「둘째」(s… | 147 | 1,166 |

### category_title_default (3건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| mode="bad" |  | 입력 검증 오류 | 1 validation error for category_title_defaultArguments mode Input should be 'ask', 'ai' or 'none' [type=liter… | 0 | 283 |
| mode="" |  | 입력 검증 오류 | 1 validation error for category_title_defaultArguments mode Input should be 'ask', 'ai' or 'none' [type=liter… | 0 | 280 |
| (없음) |  | 입력 검증 오류 | 1 validation error for category_title_defaultArguments mode Field required [type=missing, input_value={}, inp… | 0 | 246 |

### category_create (22건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| name="" |  | ToolError | 책 이름이 비어 있습니다 | 9 | 51 |
| name=<200k자> |  | ToolError | 책 이름은 12자까지입니다(책등에 들어가는 길이). 지금 200000자 | 10 | 77 |
| name="../x" |  | ToolError | 책 이름에 쓸 수 없는 글자가 있습니다: . / (글자·숫자·띄어쓰기·가운뎃점·하이픈·괄호만) | 7 | 90 |
| name="가가가가가가가가가가가가가" |  | ToolError | 책 이름은 12자까지입니다(책등에 들어가는 길이). 지금 13자 | 8 | 73 |
| name="123" |  | ToolError | 숫자만으로는 책 이름을 지을 수 없습니다 | 8 | 60 |
| name="카테고리" |  | ToolError | '카테고리'는 Magus가 쓰는 말이라 책 이름으로는 쓸 수 없어요. 다른 이름을 붙여 주세요. (쓸 수 없는 이름: 전체, 확인 요청, AI 확인 요청, 결정, 수정본, 책장, 컨텍스트, 휴지통… | 8 | 190 |
| name="메모" |  | ToolError | '메모' 책이 이미 있습니다. 다른 이름을 지어 주세요 | 10 | 68 |
| name="새책", template="bad" |  | 입력 검증 오류 | 1 validation error for category_createArguments template Input should be '빈 책', '인물', '사례', '수치', '용어', '노드' … | 0 | 298 |
| name="새책", color="bad" |  | ToolError | 색 'bad'을 알 수 없다. 기본 색 이름(빨강·주황·노랑·초록·파랑·남색·보라·분홍·갈색·회색·검정·미색·자주·짙은 초록·청록·겨자·하늘·먹색) 또는 #RRGGBB(예: #b22222)로 준다 | 9 | 147 |
| name="새책", color=<200k자> |  | ToolError | 색 '가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 11 | **200,144** |
| name="새책", node="없는" |  | ToolError | 「닿으려는 종 (합성)」 지도에 '없는' 노드가 없다. 노드: 가운데 · 참고문헌 · 메모 | 17 | 88 |
| name="새책", context=["없는 이름"] | 컨텍스트=자유 글? | ok | 컨텍스트(책 「새책」): 없는 이름 책을 만듦: 「새책」 · 빈 책 · 색 갈색(#7a4e2d) · 「닿으려는 종 (합성)」 · 노드 「새책」에 꽂혔다. | 37 | 85 |
| name="새책2", context=["가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가…<200k자> |  | ToolError | 컨텍스트는 하나에 500자까지다(지금 200000자). | 10 | 68 |
| name="새책3", context=["a", "b", "c", "d", "e"] |  | ToolError | 컨텍스트는 노드·책마다 4개까지 붙인다. | 8 | 60 |
| name="새책4", project="p2" | 다른 사용자 | ToolError | 'p2' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 9 | 90 |
| name="", template="노드" |  | ToolError | 노드 이름은 1~20자다. | 11 | 52 |
| name=<200k자>, template="노드" |  | ToolError | 노드 이름은 1~20자다. | 11 | 52 |
| name="", template="연결 노드" |  | ToolError | 「닿으려는 종 (합성)」 지도에 '' 노드가 없다. 노드: 가운데 · 참고문헌 · 메모 · 새책 | 17 | 91 |
| name="p2 · 비밀", template="연결 노드" | 다른 사용자 노드 | ToolError | 'p2' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 15 | 90 |
| name="없는 · 노드", template="연결 노드" |  | ToolError | '없는' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 16 | 90 |
| name="synth · 메모", template="연결 노드" | 같은 프로젝트 | ToolError | 같은 프로젝트의 노드는 연결 노드로 만들지 않는다(선으로 잇는다). | 16 | 75 |
| name="새책5", context="문체" | context 문자열 | 입력 검증 오류 | 1 validation error for category_createArguments context Input should be a valid list [type=list_type, input_v… | 1 | 254 |

### category_put (40건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| book="", author="me", content="x", untitled=true |  | ToolError | '' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 문서… | 25 | 174 |
| book="없는", author="me", content="x", untitled=true |  | ToolError | '없는' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 27 | 176 |
| book="닿으려는 종 (합성)", author="me", content="x", untitled=true |  | ToolError | 「닿으려는 종 (합성)」에는 올린 문서가 들어 있어 글을 넣지 않는다(고칠 곳은 대화로 제안하고, 저자가 원본 파일에서 고친다). 글을 넣을 책을 저자에게 묻는다. | 11 | 126 |
| book="메모", author="bad", content="x", untitled=true |  | 입력 검증 오류 | 1 validation error for category_putArguments author Input should be 'me' or 'ai' [type=literal_error, input_v… | 0 | 256 |
| book="메모", content="x", untitled=true | author 빠짐 | 입력 검증 오류 | 1 validation error for category_putArguments author Field required [type=missing, input_value={'book': '메모', … | 0 | 274 |
| book="메모", author="me", content="", untitled=true |  | ToolError | 내용·제목·칸·쓸 부분 중 하나는 있어야 한다. | 13 | 61 |
| book="메모", author="me", content=<200k자>, untitled=true |  | ToolError | 내용은 20000자까지다. | 15 | 49 |
| book="메모", author="me", content="제목 없음" | 기본값 묻기 | ToolError | 제목을 정하지 않아 저장하지 않았다. 저자의 제목 기본값은 '매번 묻기'다. 저자에게 제목을 직접 지을지, 지어 드릴지, 비워 둘지 묻고 답을 들은 뒤 다시 부른다(직접 → title과 title… | 14 | 261 |
| book="메모", author="me", content="x", title="제목" | title_by 없음 | ToolError | 제목을 넣을 때는 title_by를 함께 준다: 저자가 말한 제목이면 author, Claude가 지었으면 ai. 기본값은 없다(저자가 지은 제목이 AI 것으로, 또는 그 반대로 기록되지 않게).… | 14 | 154 |
| book="메모", author="me", content="x", title=<200k자>, title_by="author" | 제목 20만 자 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 넣음: 「메모」 20261009073842034-a64098 · 제목 「가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 29 | 167 |
| book="메모", author="me", content="x", untitled=true, fields={"없는칸": "x"} |  | ToolError | 「메모」에는 '없는칸' 칸이 없다. 칸: 없음. 이유·위치는 reason·where로 준다. | 15 | 86 |
| book="메모", author="me", content="x", untitled=true, fields={"x": 123} |  | 입력 검증 오류 | 1 validation error for category_putArguments fields.x Input should be a valid string [type=string_type, input… | 0 | 254 |
| book="메모", author="me", content="x", untitled=true, tags=["t", "t", "t", "t", "t", "t", "… |  | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 넣음: 「메모」 20261009073842079-c78e9c · 제목 없음 · 누가: 저자의 말(me) | 19 | 87 |
| book="메모", author="me", content="x", untitled=true, tags=["가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… |  | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 넣음: 「메모」 20261009073842099-4b449c · 제목 없음 · 누가: 저자의 말(me) | 19 | 87 |
| book="메모", author="me", content="x", untitled=true, reason=<200k자>, where=<200k자> | 이유·위치 20만 자 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 넣음: 「메모」 20261009073842120-800f2c · 제목 없음 · 누가: 저자의 말(me) | 22 | 87 |
| book="메모", author="me", content="x", untitled=true, chapters=[-1] |  | ToolError | 『닿으려는 종 (합성)』에 없는 장 번호: [-1]. book_outline의 장 번호를 쓴다. | 20 | 88 |
| book="메모", author="me", content="x", untitled=true, chapters=[10000000000000000000] |  | ToolError | 『닿으려는 종 (합성)』에 없는 장 번호: [10000000000000000000]. book_outline의 장 번호를 쓴다. | 24 | 106 |
| book="메모", author="me", content="x", untitled=true, chapters=[1] |  | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 넣음: 「메모」 20261009073842195-5839d3 · 제목 없음 · 누가: 저자의 말(me) · 연결된 장 1 | 27 | 97 |
| book="메모", author="me", content="x", untitled=true, chapters=[1], project="p2" | 다른 사용자 프로젝트 | ToolError | 'p2' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 18 | 87 |
| book="메모", author="me", content="x", untitled=true, item_id="없는" |  | ToolError | 「메모」에 글 없는가 없다. category_search 결과의 id를 준다. | 15 | 78 |
| book="메모", author="me", content="x", untitled=true, item_id="20261009073748169-19d725" | 다른 사용자 글 id | ToolError | 「메모」에 글 20261009073748169-19d725가 없다. category_search 결과의 id를 준다. | 14 | 100 |
| book="메모", author="me", content="x", untitled=true, item_id="../x" |  | ToolError | 「메모」에 글 ../x가 없다. category_search 결과의 id를 준다. | 12 | 80 |
| book="메모", author="me", content="x", untitled=true, project="없는" | 없는 프로젝트 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 넣음: 「메모」 20261009073842279-5f5dfa · 제목 없음 · 누가: 저자의 말(me) | 21 | 87 |
| book="메모", author="me", content="x", untitled=true, project="내 서재" | 다른 프로젝트 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 넣음: 「메모」 20261009073842299-b32456 · 제목 없음 · 누가: 저자의 말(me) | 19 | 87 |
| book="메모", author="me", source="문자열" |  | 입력 검증 오류 | 1 validation error for category_putArguments source Input should be a valid dictionary [type=dict_type, input… | 0 | 254 |
| book="메모", author="me", source={}, checked=true |  | ToolError | 원문 확인에는 쓸 부분(parts)이 하나 이상 있어야 한다. 직접 읽고 고른 대목(text)과 이유(reason)를 준다. | 14 | 104 |
| book="메모", author="me", source={"key": "../evil"} |  | ToolError | ref key='../evil': 소문자 영문·숫자·한글·한자·_·-, 80자 이하 | 14 | 81 |
| book="메모", author="me", source={"key": "CON"} |  | ToolError | ref key='CON': 소문자 영문·숫자·한글·한자·_·-, 80자 이하 | 15 | 77 |
| book="메모", author="me", source={"authors": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa… | 저자 20만 자 | ToolError | ref key='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa… | 30 | **200,078** |
| book="메모", author="me", source={"authors": "Kim", "year": "abc"} |  | ToolError | bib에 key가 없으면 저자(authors 또는 author)와 네 자리 연도(year)가 필요하다. 전문 첫머리에서 참고문헌 제목도 찾지 못했다 | 32 | 117 |
| book="메모", author="me", source={"authors": "Kim", "year": 2021}, checked=true | parts 없음 | ToolError | 원문 확인에는 쓸 부분(parts)이 하나 이상 있어야 한다. 직접 읽고 고른 대목(text)과 이유(reason)를 준다. | 13 | 104 |
| book="메모", author="me", source={"authors": "Kim", "year": 2021}, checked=true, parts=[{"t… | 빈 쓸 부분 | ToolError | 원문 확인에는 쓸 부분(parts)이 하나 이상 있어야 한다. 직접 읽고 고른 대목(text)과 이유(reason)를 준다. | 14 | 104 |
| book="메모", author="me", source={"authors": "Kim", "year": 2021}, checked=true, parts=[{"t… | 쓸 부분 20만 자 | ToolError | 원문 확인에는 쓸 부분마다 이유(reason: 왜 골랐는지)가 필요하다 | 14 | 74 |
| book="메모", author="me", source={"authors": "Lee", "year": 2021}, file="없는.pdf" |  | ToolError | 올린 파일에 '없는.pdf'이 없다. files_list로 이름을 확인하거나, 저자에게 웹 책장에서 먼저 올려 달라고 한다. | 15 | 104 |
| book="메모", author="me", source={"authors": "Lee", "year": 2021}, file="../../x.pdf" |  | ToolError | 올린 파일에 '../../x.pdf'이 없다. files_list로 이름을 확인하거나, 저자에게 웹 책장에서 먼저 올려 달라고 한다. | 13 | 109 |
| book="메모", author="me", source={"authors": "Lee", "year": 2021}, file="첨부:202610090737482… | 다른 사용자 첨부 | ToolError | 게시판 첨부에 '첨부:20261009073748232-93d364'이 없다. files_list로 이름을 확인한다. | 128 | 99 |
| book="메모", author="me", source={"authors": "Lee", "year": 2021}, file="C:\\project_2026\\… | 다른 사용자 절대 경로 | ToolError | 올린 파일에 'C:\\project_2026\\Magus\\private\\tmp\\audit\\E-data\\data\\users\\audit2\\inbox\\합성.docx'이 없다. files… | 15 | 187 |
| book="메모", author="me", source={"authors": "Park", "year": 2021}, aliases=["가가가가가가가가가가가가가… | aliases 20만 자 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 park2021: 새 문헌 글 → 원문 확인 전 · 쓸 부분 0개 더함(모두 0개) · 원문 파일 없음 · 한글 표기 ['가가가가가가가가가가가… | 193 | **200,228** |
| book="메모", author="ai", source={"authors": "Choi", "year": 2021, "title": "AI가 넣은 문헌"}, t… | 문헌 글에 제목·태그·장 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 choi2021: 새 문헌 글 → 원문 확인 전 · 쓸 부분 0개 더함(모두 0개) · 원문 파일 없음 · 한글 표기 없음 · 책 「메모」(「… | 111 | 226 |
| book="메모", author="me", parts="x", untitled=true |  | 입력 검증 오류 | 1 validation error for category_putArguments parts Input should be a valid list [type=list_type, input_value=… | 0 | 245 |

### category_search (33건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| query="" |  | ok | category_search: 검색어가 비었다(찾을 말을 준다. 스크랩한 글만 보려면 scrap_only=true). | 0 | 65 |
| query=<200k자> |  | ok | category_search '가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가… | 103 | **401,089** |
| query="\"" |  | ok | category_search '"' (모든 책): 결과 없음. | 5 | 34 |
| query="a AND" |  | ok | category_search 'a AND' (모든 책) — 8건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 참고문헌 300 이상 — 한… | 49 | 1,590 |
| query="NEAR(" |  | ok | category_search 'NEAR(' (모든 책): 결과 없음. | 11 | 38 |
| query="*" |  | ok | category_search '*' (모든 책): 결과 없음. | 12 | 34 |
| query="-x" |  | ok | category_search '-x' (모든 책) — 7건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 7 — 한 책만 보려면 bo… | 22 | 936 |
| query="col:x" |  | ok | category_search 'col:x' (모든 책) — 7건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 7 — 한 책만 보려면… | 21 | 939 |
| query="'" |  | ok | category_search "'" (모든 책) — 2건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 참고문헌 2 — 한 책만 보려면 b… | 15 | 502 |
| query="\\" |  | ok | category_search '\\' (모든 책): 결과 없음. | 10 | 35 |
| query="사지동물" |  | ok | category_search '사지동물' (모든 책) — 3건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 3 — 한 책만 보려면 … | 21 | 567 |
| query="사지동물", k=0 |  | ok | category_search '사지동물' (모든 책) — 1건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 3 — 한 책만 보려면 … | 16 | 267 |
| query="사지동물", k=-1 |  | ok | category_search '사지동물' (모든 책) — 1건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 3 — 한 책만 보려면 … | 16 | 267 |
| query="사지동물", k=10000000000000000000 |  | ok | category_search '사지동물' (모든 책) — 3건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 3 — 한 책만 보려면 … | 19 | 567 |
| query="사지동물", k="x" |  | 입력 검증 오류 | 1 validation error for category_searchArguments k Input should be a valid integer, unable to parse string as … | 0 | 292 |
| query="사지동물", book="없는" |  | ToolError | '없는' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 31 | 179 |
| query="사지동물", book="닿으려는 종 (합성)" |  | ToolError | 「닿으려는 종 (합성)」에는 올린 문서가 들어 있다. 장은 book_read_chapter, 확인 요청은 book_issues로 본다. | 16 | 113 |
| query="비밀", book="비밀" | 다른 사용자 책 | ToolError | '비밀' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 32 | 179 |
| query="hidden" | 다른 사용자 문헌 key | ok | category_search 'hidden' (모든 책): 결과 없음. | 13 | 39 |
| query="사지동물", project="없는" |  | ToolError | '없는' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 9 | 90 |
| query="사지동물", project="p2" | 다른 사용자 | ToolError | 'p2' 프로젝트를 찾지 못했다. 프로젝트: 내 서재 · 「닿으려는 종 (합성)」(synth) | 9 | 90 |
| query="x", author="bad" |  | 입력 검증 오류 | 1 validation error for category_searchArguments author Input should be 'me', 'ai' or 'all' [type=literal_erro… | 0 | 269 |
| attachment="20261009073747306-75eed1", page=1 |  | ok | 첨부 「첨부원고.docx」(첨부:20261009073747306-75eed1) · 「메모」 책의 글 「audit의 비밀 생각 사지동물 물가」 · 쪽 1/2 · 글자 3,926자 이 글자는 찾고 읽… | 28 | 3,250 |
| attachment="20261009073747306-75eed1", page=0 |  | ok | 첨부 「첨부원고.docx」(첨부:20261009073747306-75eed1) · 「메모」 책의 글 「audit의 비밀 생각 사지동물 물가」 · 쪽 1/2 · 글자 3,926자 이 글자는 찾고 읽… | 4 | 3,250 |
| attachment="20261009073747306-75eed1", page=-1 |  | ok | 첨부 「첨부원고.docx」(첨부:20261009073747306-75eed1) · 「메모」 책의 글 「audit의 비밀 생각 사지동물 물가」 · 쪽 1/2 · 글자 3,926자 이 글자는 찾고 읽… | 5 | 3,250 |
| attachment="20261009073747306-75eed1", page=10000000000000000000 |  | ok | 첨부 「첨부원고.docx」(첨부:20261009073747306-75eed1) · 「메모」 책의 글 「audit의 비밀 생각 사지동물 물가」 · 쪽 2/2 · 글자 3,926자 이 글자는 찾고 읽… | 5 | 1,140 |
| attachment="20261009073747306-75eed1", page="x" |  | 입력 검증 오류 | 1 validation error for category_searchArguments page Input should be a valid integer, unable to parse string … | 0 | 295 |
| attachment="첨부:20261009073748232-93d364" | 다른 사용자 첨부 | ToolError | 첨부 '첨부:20261009073748232-93d364'이 없다. category_search 결과나 files_list의 '첨부:<id>'를 준다. | 119 | 122 |
| attachment="../x" |  | ToolError | 첨부 '../x'이 없다. category_search 결과나 files_list의 '첨부:<id>'를 준다. | 0 | 99 |
| attachment="첨부:" |  | ToolError | 첨부 '첨부:'이 없다. category_search 결과나 files_list의 '첨부:<id>'를 준다. | 0 | 98 |
| attachment="", query="x" |  | ok | category_search 'x' (모든 책) — 8건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 8 · 참고문헌 2 — 한 책… | 26 | 1,031 |
| scrap_only=true |  | ok | category_search (모든 책 · 스크랩만): 결과 없음. 스크랩(★)한 글이 없다. | 155 | 52 |
| query="Park" | aliases 20만 자 뒤 찾기 | ok | category_search 'Park' (모든 책) — 1건. author=me 글이 저자의 말이다. 인용은 '원문 확인' 문헌 글의 쓸 부분만 쓴다. 책별 개수: 메모 1 — 한 책만 보려면 … | 76 | **200,268** |

### category_edit (35건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| (없음) |  | ToolError | book(책) 또는 node(노드)를 준다. | 0 | 60 |
| book="" |  | ToolError | book(책) 또는 node(노드)를 준다. | 0 | 60 |
| book="없는", color="빨강" |  | ToolError | '없는' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 29 | 177 |
| book="메모" |  | ToolError | 바꿀 것(new_name·color·context·move_to) 또는 undo_move를 준다. | 0 | 90 |
| book="메모", new_name="" |  | ToolError | 바꿀 것(new_name·color·context·move_to) 또는 undo_move를 준다. | 0 | 90 |
| book="메모", new_name=<200k자> |  | ToolError | 책 이름은 12자까지입니다(책등에 들어가는 길이). 지금 200000자 | 15 | 75 |
| book="메모", color="bad" |  | ToolError | 색 'bad'을 알 수 없다. 기본 색 이름(빨강·주황·노랑·초록·파랑·남색·보라·분홍·갈색·회색·검정·미색·자주·짙은 초록·청록·겨자·하늘·먹색) 또는 #RRGGBB(예: #b22222)로 준다 | 12 | 145 |
| book="메모", context=["없는 이름"] | 자유 글 컨텍스트 | ok | 컨텍스트(책 「메모」): 없는 이름 책 「메모」을 고침: 컨텍스트를 바꿈. | 27 | 41 |
| book="메모", context=[] | 컨텍스트 떼기 | ok | 컨텍스트: 없음(일반 메모로 다룬다) — 책 「메모」 책 「메모」을 고침: 컨텍스트를 뗌. | 30 | 50 |
| book="메모", move_to="없는" |  | ToolError | 「닿으려는 종 (합성)」 지도에 '없는' 노드가 없다. 노드: 가운데 · 참고문헌 · 메모 · 새책 | 34 | 91 |
| book="메모", move_to="p2" | 다른 사용자 프로젝트 | ToolError | 「닿으려는 종 (합성)」 지도에 'p2' 노드가 없다. 노드: 가운데 · 참고문헌 · 메모 · 새책 | 36 | 91 |
| book="메모", undo_move=true | 옮긴 적 없음 | ToolError | 되돌릴 옮기기가 없다. | 15 | 48 |
| book="비밀", color="빨강" | 다른 사용자 책 | ToolError | '비밀' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 31 | 177 |
| book="닿으려는 종 (합성)", new_name="x" |  | ToolError | 올린 문서가 든 책의 이름은 프로젝트 제목이다(바꾸지 않는다). | 17 | 71 |
| node="없는", color="빨강" |  | ToolError | 「닿으려는 종 (합성)」 지도에 '없는' 노드가 없다. 노드: 가운데 · 참고문헌 · 메모 · 새책 | 25 | 91 |
| node="가운데", new_name="새 가운데" | 가운데 이름 | ToolError | 가운데 노드 이름은 프로젝트 제목이라 바꾸지 않는다. | 13 | 65 |
| node="메모" | 바꿀 것 없음 | ToolError | 노드에서 바꿀 것(new_name·color·context·link·unlink)을 준다. | 11 | 86 |
| node="메모", link="메모" | 자기 자신 | ToolError | 같은 노드끼리는 잇지 않는다. | 13 | 52 |
| node="메모", link="없는" |  | ToolError | 「닿으려는 종 (합성)」 지도에 '없는' 노드가 없다. 노드: 가운데 · 참고문헌 · 메모 · 새책 | 20 | 91 |
| node="메모", new_name=<200k자> |  | ToolError | 노드 이름은 1~20자다. | 14 | 50 |
| node="메모", new_name="" | 빈 이름 | ToolError | 노드에서 바꿀 것(new_name·color·context·link·unlink)을 준다. | 11 | 86 |
| checked=true, item_id="" |  | ToolError | checked에는 item_id(문헌 글의 key, 예: clack2012)를 함께 준다. | 0 | 86 |
| checked=true, item_id="없는" |  | ToolError | 문헌 글 '없는'이 없다. category_search로 key를 확인한다. | 1 | 78 |
| checked=true, item_id="hidden2020" | 다른 사용자 문헌 | ToolError | 문헌 글 'hidden2020'이 없다. category_search로 key를 확인한다. | 0 | 86 |
| checked=true, item_id="ahlberg2019" | 쓸 부분 없는 문헌 | ToolError | Ahlberg(2019) 『Follow the footprints and mind the gaps』에는 쓸 부분이 없다. 원문 확인 글로 넣으려면 저자가 고른 대목을 parts에 담아 catego… | 0 | 179 |
| checked=true, item_id="secret2020", book="참고문헌" | 다른 책 이름 | ToolError | 그 문헌 글은 「참고문헌」 책에 있지 않다. | 19 | 60 |
| scrap=true, item_id="20261009073748169-19d725" | 다른 사용자 글 | ToolError | 글 '20261009073748169-19d725'이 없다. category_search 결과의 id(문헌 글은 key)를 준다. | 5 | 108 |
| scrap=true, item_id="../x" |  | ToolError | 글 '../x'이 없다. category_search 결과의 id(문헌 글은 key)를 준다. | 5 | 88 |
| scrap=true, item_id="20261009073747239-3ff0d8", book="없는" |  | ToolError | '없는' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 30 | 177 |
| parts=[], item_id="secret2020" | 빈 parts 목록 | ToolError | book(책) 또는 node(노드)를 준다. | 0 | 60 |
| parts=[{"text": ""}], item_id="secret2020" | 빈 대목 | ok | secret2020(2020) 『Secret book of audit』: 쓸 부분 0개 더함(모두 1개, 같은 대목은 한 번). 원문 확인 표시는 그대로다. | 0 | 87 |
| parts=[{"text": "가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가…<200k자>, item_id="secr… | 대목 20만 자 | ok | secret2020(2020) 『Secret book of audit』: 쓸 부분 1개 더함(모두 2개, 같은 대목은 한 번). 원문 확인 표시는 그대로다. | 105 | 87 |
| parts=[{"text": "x"}], item_id="20261009073747239-3ff0d8" | 일반 글 id | ToolError | 문헌 글 '20261009073747239-3ff0d8'이 없다. category_search로 key를 확인한다. 문헌 글이 아니면 category_put으로 넣는다. | 0 | 130 |
| parts=[{"text": "x"}], item_id="hidden2020" | 다른 사용자 문헌 | ToolError | 문헌 글 'hidden2020'이 없다. category_search로 key를 확인한다. 문헌 글이 아니면 category_put으로 넣는다. | 0 | 116 |
| parts="x", item_id="secret2020" |  | 입력 검증 오류 | 1 validation error for category_editArguments parts Input should be a valid list [type=list_type, input_value… | 0 | 247 |

### category_trash (14건)

| 입력 | 비고 | 결과 | 요지 | ms | 응답 길이 |
|---|---|---|---|---|---|
| note="" |  | ToolError | book(책·글) 또는 node(노드)를 준다. | 0 | 63 |
| (없음) |  | 입력 검증 오류 | 1 validation error for category_trashArguments note Field required [type=missing, input_value={}, input_type=… | 0 | 230 |
| note="x", book="없는" |  | ToolError | '없는' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 38 | 178 |
| note="x", book="닿으려는 종 (합성)" |  | ToolError | 「닿으려는 종 (합성)」에는 올린 문서가 들어 있다. 이 책은 저자가 웹 책장의 책 설정에서 휴지통으로 옮긴다. | 16 | 99 |
| note="x", book="메모", item_id="없는" |  | ToolError | item id='없는': 영문·숫자·_·-만, 64자 이하, 영문/숫자로 시작 | 14 | 80 |
| note="x", book="메모", item_id="../x" |  | ToolError | item id='../x': 영문·숫자·_·-만, 64자 이하, 영문/숫자로 시작 | 13 | 82 |
| note="x", book="메모", item_id="secret2020" | 문헌 글 | ToolError | 문헌 글(서지·원문 확인)은 휴지통으로 옮기지 않는다(인용 점검이 보는 기록이다). | 16 | 83 |
| note="x", book="메모", item_id="20261009073748169-19d725" | 다른 사용자 글 | ToolError | 「메모」에 글 20261009073748169-19d725가 없다. category_search 결과의 id를 준다. | 16 | 102 |
| note="x", book="비밀" | 다른 사용자 책 | ToolError | '비밀' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「참고문헌」[논문] · 「메모」 · 「새책」[없는 이름] · 「닿으려는 종 (합성)」[원고] · 「가가가가가가가가가가가가가…」[출처 확인 … | 32 | 178 |
| note="x", node="가운데" |  | ToolError | 가운데 노드는 휴지통으로 옮기지 않는다. | 24 | 59 |
| note="x", node="없는" |  | ToolError | 「닿으려는 종 (합성)」 지도에 '없는' 노드가 없다. 노드: 가운데 · 참고문헌 · 메모 · 새책 | 16 | 92 |
| note="x", node="메모" | 책이 꽂힌 노드 | ToolError | 책이 꽂힌 노드는 휴지통으로 옮기지 않는다. 책을 먼저 다른 노드로 옮긴다. | 24 | 79 |
| note="x", book="참고문헌" | 문헌이 든 책 통째 | ToolError | 「참고문헌」에는 문헌·참고문헌 항목이 1531편 있어 휴지통으로 옮기지 않는다 | 19 | 80 |
| note=<200k자>, book="메모", item_id="20261009073747248-aa0318" | note 20만 자 | ok | 휴지통으로 옮김: 「메모」의 글 20261009073747248-aa0318 “AI 정리”. 지운 것이 아니라 옮긴 것이라 운영자가 되살릴 수 있다. | 34 | 83 |
