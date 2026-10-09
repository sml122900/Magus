# Magus — 집필 RAG MCP 서버

- **세션을 새로 시작하면 가장 먼저 status.md를 읽는다. 그다음 이 파일의 진행상황 섹션을 본다. 작업은 status.md의 '지금 바로 할 일'부터 재개한다.**
- **사용자에게 하는 보고·요약·질문은 한국어로 쓴다**(2026-10-07 사용자 지시. 영어로 보고한 일이 있었다). 코드·명령·파일 경로·식별자는 그대로 둔다.

## 진행상황

- 현재 단계: **P1(원격 MCP 서비스) 1~6단계 완료**(`p1-step1`~`p1-step6`).
  - 서버는 Vultr 서울에 배포했다(`https://magus.lifebookapplication.com`, WorkOS Staging). 백업과 서버 복구 시험을 마쳤다.
  - claude.ai 커스텀 커넥터로 웹·모바일 연결에 성공했다(CIMD).
- 원격 저장소: GitHub 비공개 `sml122900/Magus`(`origin`). **단계 태그를 찍으면 push까지 한다**(아래 "원격 저장소").
- **사용자 결정 #68(2026-10-06)**: 원고 본문의 원본은 저자의 Word(·한글) 파일이다. Magus의 원고는 최신 업로드의 사본이다(`docs/decisions/author-file-is-source.md`).
  - 다시 올리기가 핵심 기능이 됐다. 기본 부분을 구현했다(#76, `magus/book/reupload.py`, 설계·확정 범위는 `docs/decisions/reupload-design.md`).
- **7단계 준비(2026-10-06, 로컬)**: #69 표, #70 제N부 들어가며, #71 코멘트 작성자·AI 확인 요청, #72 [점검] 분류, #73 걸린 문장 전문, #74 규칙 4, #77 제목·부제, #76 다시 올리기 기본을 구현했다(status.md 0-4절).
  - 최신본을 `father-trial`에 새로 임포트해 수치를 쟀고, `reupload-trial`에서 4판 → 최신본 다시 올리기를 시험했다(기존 미해결 86 유지 + 새 43, 바뀐 장 6만 교체).
- **운영 규칙(#78)**: 같은 책을 다시 올릴 때는 수정본(`new_edition`)으로 한다. 아버지 원고를 `replace`로 다시 임포트하지 않는다. replace는 결정·직접 남긴 미해결·닫은 미해결까지 휴지통으로 보낸다.
- 다음 할 일: **7단계 아버지 온보딩**(`docs/onboarding-father.md`). 시작 전 확인은 status.md "7단계 전 확인"을 따른다. 그 전에 사용자가 claude.ai에서 book_outline을 한 번 확인한다.
  - 저자 확인 질문지(#84)는 2026-10-06에 앞당겨 끝냈다: 도구 `book_questions`·`book_answer`, 웹 `/questions`, 수정본 리포트 절(서버 배포 전).
  - 사용자 격리: 아버지 계정 추가 전에 점검했다(status.md 0-6절, `tests/test_isolation.py`).
- 다음 배포에 함께(커밋만): #90 되묻기 선택지에서 원고 빼기.
- **야간 자율 작업(2026-10-06 밤, #92, 서버 배포 없음)**: 책장 화면(`/shelf`, 양장본 책장 + 게시판형 목록 + 검색, 태그 `shelf-web`), 저자의 카테고리·책 색·항목 제목(도구 21 → 28, 인덱스 v15, 태그 `shelf-categories`). #92는 사용자 확인(e만 바꿈). 아침 보완과 함께 2026-10-06 14:51 `p1-shelf`로 서버에 배포했다(status.md 0-10절).
- **층·3D 책장(2026-10-07, 사용자 결정 #93 승인, 로컬만, 태그 `floors-local`)**: 작업물마다 책장의 한 층, 맨 위 공용 층. 카테고리(기본 포함)는 층에 꽂히고 옮긴다(#92-a 대체, `docs/decisions/floors.md`).
  인용 점검은 그 작업물 층 + 공용 문헌. 두 작업물이 쓰게 되어 공용으로 옮긴 문헌은 리포트 한 줄과 문헌 항목의 기록(시각·이유)으로 알린다(#93-a 더함). 이전은 `magus floors plan|apply|revert`.
  **2026-10-08 #94·#95·#96과 묶어 배포했다(`p1-contexts`, 서버 이전 한 번, `docs/deploy.md` 2-2절)**. 3D 책장 화면은 #95로 걷어 냈다.
- **모든 동작을 책장에서(2026-10-07 밤, 사용자 결정 #94, 확인 대기, 로컬만, 태그 `shelf-books-local`)**: 책 종류 원고 책·모음 책·문서 책, 층의 '책 추가', 원고 책 화면(탭 넷),
  출처 확인 문서(book_document, 내용은 서버가, Claude는 머리말만), 메뉴는 책장 하나·받은함은 내 정보의 '올린 파일'. 도구 30 → 29(10,904토큰), 인덱스 v19(`docs/decisions/bookshelf-all.md`, status.md 0-15절).
- **층 → 프로젝트·마인드맵(2026-10-08, 사용자 결정 #95, 확인 대기, 로컬만)**: 프로젝트(옛 층) → 지도(노드·선) → 노드 → 책장(정면 2D) → 책 → 게시판.
  옛 공용 층은 프로젝트 「내 서재」(내부 id `common`), 공유는 연결 노드로. 지도 `shelf/maps/<프로젝트>.json`. 인용 점검은 자기 문헌 + 연결 노드가 가리키는 문헌.
  도구 29개 그대로(floor → project(+ node), 노드 일은 category_*에 합침, 10,900토큰), instructions 규칙 7·8·12·13. 웹은 프로젝트 목록 + 프로젝트 화면(지도 + 패널).
  3D 책장 걷어 냄. 이전 `magus maps plan|apply|revert`(`docs/decisions/project-map.md`, 문구 전문 `project-map-texts.md`, status.md 0-18절). 2026-10-08 묶음 배포(`p1-contexts`).
- **종류를 없애고 '컨텍스트'로(2026-10-08, 사용자 요청 #96, 확인 대기, 로컬만)**: 책에는 글이 쌓이거나 올린 문서가 들어 있다. 종류 이름(원고 책·모음 책·문서 책, 생각·문체·문헌)은
  저자에게 보이지 않고, AI가 읽는 법은 노드·책의 **컨텍스트**(저자가 적은 글, 사본)다. 자주 쓰는 컨텍스트(`shelf/contexts.json`, 처음 제공 「문체」·「원고」·「논문」·「생각 메모」).
  생각·문체는 책의 글(항목 파일)로, 문헌은 제자리 + 그 문헌이 든 책. 도구 29 → 23(글 넣기 category_put·찾기 category_search, 8,416토큰), instructions 머리말·규칙 2·3·5~9·11·12.
  응답 머리에 컨텍스트 전문. 이전은 `magus maps apply`에 합침(`docs/decisions/contexts.md`, 문구 전후 `contexts-texts.md`, status.md 0-19절). 2026-10-08 21:47 묶음 배포(`p1-contexts`).
  **사용자 답(2026-10-08 저녁)**: d·s는 바꿔서, 나머지 승인. d = 노드 → 책 순서로 컨텍스트를 이어 읽는다(합쳐 1,000자). s = 일반 기능의 '원고' → '올린 문서'
  (instructions 머리말·1·4·6·7·8·12, 화면·도구 응답·설명). 도구 목록 8,450토큰, instructions 2,259토큰. #93~#96 묶음은 사용자 확인 뒤 배포했다(status.md 0-20절).
- **서버(2026-10-09 19:32부터): master `p1-high-fix`(`deba2af`, 코드 점검 높음 5건: 그림 폭탄·docx 압축 폭탄(`magus/zipguard.py`)·색인 다시 만들기가 깨진 파일에 멈추지 않음·장 번호 0~9,999·대화로 글 고치기 = 웹과 같은 patch, 운영: 로그 회전 10MB × 5·배포 전 백업 태그 `BACKUP_TAG`, 데이터 이전 없음·인덱스 v23, book_write_chapter 입력 스키마만 바뀜(재연결 필수 아님), status.md 0-29절, `docs/deploy.md` 2-9절). 되돌리기 기준 `409242d`(이미지 `magus:rollback-409242d`). 되돌리기 이미지는 `rollback-409242d`·`rollback-58ce884`만 남겼다(그 전 판은 태그에서 다시 빌드).**
- 그 전 서버(2026-10-09 18:35부터): master `p1-fix-ui`(`409242d`, 구조·버그 점검 고치기 1~12: 인용 계산 캐시·오류 화면·프로젝트 휴지통·웹 찾기 AND·입력 길이·장 상태·휴지통 목록·폼 상태·스크랩 초점·도움말·휴대폰 폭·작은 것, 데이터 이전 없음·인덱스 v23, 도구 설명·instructions 그대로, status.md 0-28절, `docs/deploy.md` 2-8절). 되돌리기 기준 `58ce884`(이미지 `magus:rollback-58ce884`).
- 그 전 서버(2026-10-09 오후부터): master `p1-search-rank`(`58ce884`, #101 대화 검색 순위·원문 확인 묻기, 데이터 이전 없음·인덱스 v23, status.md 0-27절, `docs/deploy.md` 2-7절). 되돌리기 기준 `458ffb9`(이미지 `magus:rollback-458ffb9`).**
- 그 전 서버(2026-10-09 14:57부터): master `p1-attach-text`(`458ffb9`, #100 첨부 글자·대화 검색 범위·예약어, 데이터 이전 없음·인덱스 v23, 기존 첨부 글자 2개 뽑음, status.md 0-26절, `docs/deploy.md` 2-6절). 되돌리기 기준 `d692855`(이미지 `magus:rollback-d692855`, 이미지만 되돌리면 된다).**
- 그 전 서버(2026-10-09 13:50부터): master `p1-edit-scrap`(`d692855`, #99 웹 수정 묶음, 인덱스 v22, status.md 0-25절, `docs/deploy.md` 2-5절). 되돌리기 기준 `0e0c89e`(이미지 `magus:rollback-0e0c89e`).
- 그 전 서버(2026-10-09 03:13부터): master `p1-board`(`0e0c89e`, #98 + 배포 전 수정, 데이터 이전 없음, status.md 0-24절, `docs/deploy.md` 2-4절). 되돌리기 기준 `ed15ffb`(이미지 `magus:rollback-ed15ffb`).
- 그 전 서버(2026-10-09 00:33부터): master `p1-razor`(`ed15ffb`, #97, 데이터 이전 없음, status.md 0-22절). 되돌리기 기준 `efc19ac`(이미지 `magus:rollback-efc19ac`).
- 그 전 서버(2026-10-08 21:47부터): master `p1-contexts`(`efc19ac`: #93 층 + #94 책 종류 + #95 프로젝트·지도 + #96 컨텍스트 묶음, 데이터 이전 `magus maps apply --all-users`, status.md 0-20절).
  되돌리기 기준은 `ec6c40b`(`p1-profile-email`, 이미지 `magus:rollback-ec6c40b`, 그 앞 `magus:rollback-e08bb79`). **되돌릴 때는 먼저 새 코드로 `magus maps revert --all-users`**(서버 `/root/deploy-20261008-contexts/ROLLBACK.txt`).
  (그 전 서버 2026-10-06 18:28~: `p1-profile-email`. `74bbbf4`까지 갈 때는 코드로 빌드하고 생각 파일의 제목 키를 먼저 정리한다, status.md 0-10절.)
  - 다음 배포도 docs/deploy.md "업데이트" 절차(`git fetch … master && git checkout -B master FETCH_HEAD`)로 한다.
- **오캄의 면도날 + 도움말 + 노드 삭제(#97, 2026-10-09 00:33 서버 배포 `p1-razor`)**: 화면 글자는 최소로(제목·단추·입력칸 이름·날짜·개수), 설명은 `docs/help/`(01~05)와
  오른쪽 아래 '?' 도움말 챗봇(`magus/helpbot.py`, 서버에서만 Haiku 4.5, 하루 30회)이 맡는다. 게시판 = 제목·본문·첨부(`magus/attachments.py`·`store/attachments.py`),
  문헌 글에 '원문 확인' 체크 하나(원문 확인 넣기 폼 없앰). 데이터 형식 그대로(이전 없음). instructions 규칙 12 = 바로 book_document(커넥터 재연결 필요).
  도움말은 이어지는 질문(브라우저가 최근 3번을 함께, 3,000자, 저장 없음). 노드 삭제(웹만): 🗑 → 화면 안 확인 창 → 책·글·첨부·선째 휴지통,
  지도의 '휴지통'(`/shelf/p/<프로젝트>/trash`)에서 되살리기(가운데·다른 프로젝트가 연결 중·문헌 책은 막음, 영구 삭제 없음, MCP 도구 그대로).
  태그 `razor-c`·`razor-ab`·`razor-d`·`node-trash`·`p1-razor`, 결정 문서 `docs/decisions/razor-help.md`, 배포 `docs/deploy.md` 2-3절, status.md 0-21·0-22절.
- **웹 수정 3건(2026-10-09, 사용자 요청 #98, 2026-10-09 03:13 서버 배포 `p1-board`)**: 도움말 대화를 브라우저(localStorage, 사용자별 열쇠)에 보관,
  책 = 별도 페이지의 게시판(`magus/webboard.py`: 위치 표시·20개씩·글쓰기·글 보기, 지도 옆 iframe 없앰), 문서·수정본은 게시판 첨부 → files_list `첨부:<id>` → book_import,
  웹의 글 고치기·원문 확인 체크 없앰, 글 🗑 → 프로젝트 휴지통에서 되살리기. instructions 규칙 7 수정본 문장 바꿈(커넥터 재연결). 태그 `board-1-help`·`board-2-pages`·`board-3-trash`
  (status.md 0-23절, `docs/decisions/board-pages.md`, 4절 #98 표는 c·e 수정 뒤 승인).
  배포 전 수정(0-24절, 태그 `board-4-fixes`): 사진 썸네일(`magus/thumbs.py`, Pillow, 긴 변 400px JPEG·EXIF 회전, 첨부 id 폴더 안 `.thumb/thumb.jpg`, 원본은 읽기만,
  `/shelf/<책>/<글>/thumbs/<첨부>` 못 만들면 원본, `magus thumbs [--all-users]`)과 글 보기 사진 격자·크게 보기, 원문 확인 표시 떼기·붙이기 `category_edit(item_id, checked)`
  (새 도구 없음, 붙일 때 쓸 부분 하나 이상, status_by.via=chat), 규칙 7 끝 "어느 파일인지 분명하지 않으면(후보가 여럿이거나 없으면) 파일 이름을 보여 주고 묻는다.",
  휴대폰 화면(지도 맞춤·목록에서 노드 아래 책장·'?' 여백), '🗑 휴지통으로'·'⚙ 책 설정'·'📎 N', 컨텍스트 줄은 책 설정 안에만. 도구 23개·8,639토큰.
- **웹 수정 묶음(2026-10-09, 사용자 요청 #99, 2026-10-09 13:50 서버 배포 `p1-edit-scrap`)**: 글 고치기 되돌림(바꾼 칸만 파일에서 고침 `Store.patch_category_item`·문헌 글은 `set_ref_memo`,
  기존 첨부 ✕ → 휴지통 종류 `attachment`, 프로젝트 휴지통에서 그 글로 되살림. 원칙: 웹에서 없애는 것은 모두 휴지통), 제목 자동 채움(웹 쓰기·고치기에서 제목이 비고 첨부가 있으면
  첫 첨부 이름, 저장된 글은 보일 때만 `attachments.shown_title`), 스크랩(글 파일·bib.json `"scrap": true`, 웹 ☆·'★ 스크랩만' `?scrap=1`,
  `category_search(scrap_only)`·`category_edit(scrap, item_id)`), 찾기 보강(`search.find_chunks` 웹·대화 공통: 앞부분 일치·따옴표 구절·낱말 하나면 가까운 낱말부터 →
  글자 포함(최근 것부터), 첨부 이름 색인), 첨부 고르기(스크립트가 담은 목록·✕·담는 순간 거절), 책 색(색 선택기 먼저·'기본 색 ▾'), 책등(upright·2~4자 tcy·5자 이상 눕힘),
  정해진 이름 안내(`RESERVED_SHOWN` 목록), 도움말. 인덱스 v22. 도구 23개·8,787토큰, instructions 규칙 6·7(2,305토큰, 커넥터 재연결).
  태그 `webfix-1-edit`~`webfix-9-help`·`webfix-4b-rank`, 결정 문서 `docs/decisions/web-edit-scrap.md`, 배포 `docs/deploy.md` 2-5절, status.md 0-25절·4절 #99 표.
- **대화 검색 범위 + 예약어 '스크랩' + 첨부 글자 뽑기(2026-10-09, 사용자 요청 #100, 2026-10-09 14:57 서버 배포 `p1-attach-text`)**: category_search가 문헌 글의 서지·key·한글 표기·첨부 이름(ref_bib)도 찾음(미확인 표시),
  '스크랩' 정해진 이름, 첨부(docx·pdf·txt·md) 글자를 첨부 폴더 안 `.text/`에 뽑아(`magus/extract.py`, 30만 자·20초·글자 없음·나중에, `magus extract --all-users`)
  색인 v23(레인 attach_text, chunks.part)으로 찾고, 대화는 `category_search(attachment='첨부:<id>', page=N)`로 3,000자씩, 웹은 '글자 보기'로 읽음.
  쓸 부분 저장은 `category_edit(item_id=문헌 key, parts)`. instructions 규칙 2 끝 문장(2,385토큰), 도구 23개·9,207토큰(커넥터 재연결).
  태그 `att-1-search-scope`·`att-2-reserved`·`att-3-extract`, 결정 문서 `docs/decisions/attachment-text.md`, 배포 `docs/deploy.md` 2-6절, status.md 0-26절·4절 #100 표.
- **대화 검색 순위 보정 + 쓸 부분 저장 뒤 원문 확인 묻기(2026-10-09, 사용자 요청 #101, 서버 배포 `p1-search-rank`)**: category_search 결과 등급
  (제목·본문·쓸 부분 > 첨부 글자·원문 > 서지·key·한글 표기·첨부 이름만), 책을 말하지 않은 찾기는 책마다 4개까지(`PER_BOOK`)·남는 칸은 다른 책, 머리에 '책별 개수'.
  book 지정은 제한 없음, 웹 찾기 그대로. instructions 규칙 2 끝에 원문 확인 묻기(2,437토큰, 커넥터 재연결). 태그 `rank-1-search`·`rank-2-ask-check`, status.md 0-27절, `docs/deploy.md` 2-7절.
- (고침 2026-10-06 밤) `tests/test_http.py::test_request_size_limit`의 Windows 간헐 실패: 머리만 보내고 응답을 먼저 읽게 고쳤다(status.md 7절).
- 대기 사항: 계정·키·결정·아버지 docx처럼 사용자만 할 수 있는 것(status.md에 "대기"로 적는다), 저자 보고서 답변. 상세는 status.md에만 적는다.

## 개요

책을 쓰는 사람이 머릿속 재료를 세 책장(코어)에 넣어 두고, Claude가 MCP로 꺼내 쓰게 하는 서버.
책장은 **사람 소유**(여러 책에 재사용), 원고는 **책(프로젝트) 소유**.
**원고 본문의 원본은 저자의 파일(Word·한글)이다.** Magus의 원고는 최신 업로드의 사본이다. 저자는 Word에서 고치고, 바뀌면 다시 올린다(사용자 결정 #68).

## 왜 만드나 (막아야 할 다섯 가지)

실제 사례: 한 교수가 Claude로 297쪽(35장 8부, 약 34만 자) 책을 썼다.

1. 한 대화에서 책 전체를 10번 재생성했다. 장 하나 추가할 때마다 전체를 다시 썼다. → **장 단위 저장, 책 전체를 반환하는 도구 없음**
2. 대화가 바뀌면 생각이 사라졌다(md 수동 첨부 8번, ChatGPT 답변 복붙). → **Casper(영감) 책장**
3. 인용 약 270개, 참고문헌 약 250편이 LLM 기억에서 생성됐다. Word 코멘트 86개 중 82개가 "확인 필요". → **Melchior(문헌) + 인용 게이트**
4. 문체가 저자의 목소리가 아니라 LLM 기본 문체였다. → **Balthasar(문체) 책장**
5. 원고가 두 파일로 갈라졌다. → **단일 진실 원천은 저자 파일.** Magus는 최신 업로드의 사본(ch-NN.md)을 들고, 다시 올리기로 맞춘다(#68. P0의 "디스크의 ch-NN.md가 원천"에서 바뀜)

## 이름과 명명 규칙

- 프로젝트·패키지·리포 이름: `magus`. MCP 서버 이름(클라이언트 표시): **"Magus"**.
- 모티브: 동방박사의 세 선물. 세 책장은 저자에게 선물을 바치는 세 현자다. 서로 토론하거나 투표하지 않는다. 받고 결정하는 사람은 저자다.

| 코어 | 모듈 | 표시명 | 성격 |
|---|---|---|---|
| 1번 영감 | `magus/casper/` | Casper · 몰약 | 보존하는 창고 |
| 2번 문헌 | `magus/melchior/` | Melchior · 황금 | 검증된 근거만 |
| 3번 문체 | `magus/balthasar/` | Balthasar · 유향 | 글에 배는 것 |
| 원고 | `magus/book/` | — | — |

- **MCP 도구 이름은 바꾸지 않는다**: `idea_*`, `ref_*`, `style_*`, `book_*`, `category_*`(#92). 마기 이름은 코드 모듈, 로그, README, 앞으로 만들 UI에만 쓴다.
- 디스크의 shelf 하위 폴더 이름도 모듈 이름을 따른다: `shelf/casper`, `shelf/melchior`, `shelf/balthasar`.

### 저자에게 보이는 이름 (사용자 결정 #85, 2026-10-06)

**저자에게 보이는 글은 이 이름으로 쓴다**: 웹 화면, 도구 응답 문장, 서버 instructions의 사용자 대상 표현, 저자 대상 문서(onboarding-father·connect-claude·README).
코드·도구 이름(`book_*`·`idea_*` 등)·모듈 이름(Casper 등)·도구 설명·내부 설계 문서(decisions 등)·파일 형식(issues.md 등)은 바꾸지 않는다.

| 이름 | 뜻 | 기존에 섞여 쓰인 말 | 내부 |
|---|---|---|---|
| 전체 | 책 전체 현황(구성·상태). 원고 전문이 아니다 | 책 지도 | book_outline |
| 확인 요청 | 출처·사실을 확인해야 하는 곳. AI가 단 것은 "AI 확인 요청" | 미해결, 이슈 | issues |
| 생각 · 문체 · 문헌 | #96부터 종류가 아니라 **저자가 붙인 책 이름이나 컨텍스트 이름**이다(이전으로 생긴 책 「생각」·「문체」·「문헌」, 컨텍스트 「생각 메모」·「문체」·「논문」) | 영감, refs | Casper·Balthasar·Melchior(코드) |
| 결정 | 정해 둔 방침 | | book_decide |
| 수정본 | 원본 파일(Word 등)에서 고친 문서를 다시 올린 것. 번호 E2, E3…는 "수정본 번호". 첫 업로드 E1은 "처음 올린 문서"(#96 답 s) | 새 판, 다시 올리기 | book_import new_edition |
| 프로젝트 | 작업물 하나(원고와 그 자료). 원고 없는 프로젝트도 있다. 웹 첫 화면은 프로젝트 목록(#95) | 층(#93), 작업물 | projects + floor id, `project` 인자, `/shelf/p/<id>` |
| 「내 서재」 | 여러 프로젝트가 함께 쓰는 자료를 두는 프로젝트. 원고는 없다(#95, 이름 검토 대기) | 공용 층(#93) | floor `common`, `magus.maps.LIBRARY_NAME` |
| 지도 | 프로젝트의 마인드맵. 노드와 선(방향 없음)(#95) | | `shelf/maps/<id>.json`, get_map, category_list |
| 노드 | 지도의 한 점. 열면 책장이 보인다. 가운데 노드는 원고 자리(이름 = 프로젝트 제목)(#95) | | node 인자, MapNode |
| 연결 노드 | 다른 프로젝트의 노드를 가리키는 노드. 보거나 넣으면 원본에 들어간다. 원본이 없어지면 '원본 없음'(#95) | 공용(#93) | MapNode.link |
| 책장 | 노드를 열면 보이는, 책이 꽂힌 칸(정면 2D)(#92·#94·#95) | 세 책장(옛 메뉴), 층(#93) | webshelf.py, webmap.py, webbooks.py |
| 책 | 노드에 꽂힌 묶음. 안에 글이 쌓이거나, 올린 문서가 들어 있다. **종류로 나눠 부르지 않고 책 이름으로 부른다**(#96). 책등 위 띠에 컨텍스트 이름 | 원고 책·모음 책·문서 책(#94), 카테고리 | categories(글 책), `ms.<프로젝트>`, `doc.<id>`, 도구의 `book` |
| 글 | 책에 쌓인 것 하나(제목·내용·누가·이유·위치·칸·태그). 서지가 있으면 문헌 글, 원문을 읽고 확인했으면 '원문 확인'(쓸 부분 하나 이상)(#96) | 항목, 생각·문장·문헌 | category_items, refs(문헌 글) |
| 컨텍스트 | 노드·책에 저자가 적어 둔, AI가 그 글을 읽는 방법(이름 20자·내용 500자, 한 곳에 4개). 책은 꽂힌 노드의 것 → 책의 것 순서로 이어 읽고(응답 머리 합쳐 1,000자), 둘 다 없으면 일반 메모(#96, 답 d) | | `contexts`, `magus/contexts.py` |
| 자주 쓰는 컨텍스트 | 저자가 이름을 붙여 모아 둔 컨텍스트(20개). 노드·책을 만들거나 고칠 때 단추로 붙인다(붙인 것은 사본). 내 정보 아래 `/me/contexts`(#96) | | `shelf/contexts.json` |
| 올린 문서 | 가운데 노드에 올린 Word·PDF 파일(장 목록·확인 요청·인용 상태·수정본 이력). 원본은 저자의 파일. 프로젝트 하나에 하나, 옮기지 않음. 처음 컨텍스트 「원고」. 일반 기능을 가리킬 때 '원고' 대신 이 이름(#96 답 s) | 원고 책(#94), 올린 원고(#96 첫 판) | projects, `/shelf/book/<id>` |
| 올린 문서에서 만든 문서 | 올린 문서에서 만든 읽기용 문서. 만든 때의 사진(새 수정본이 오면 "옛 판 기준"). 첫 종류는 출처 확인 문서(컨텍스트 「출처 확인 문서」) | 문서 책(#94), 원고에서 만든 문서(#96 첫 판), 저자 보고서 | book_document, documents |
| 게시판 | 책을 열면 보이는 날짜·제목 목록(글 뒤에 문헌 글, 제목이 없으면 내용 앞부분을 흐리게)(#92·#95·#96) | 목록 | `/shelf/<책>` |
| 올린 파일 | Claude에게 파일 이름으로 건넬 파일(내 정보 아래 `/me/files`). 원고·논문은 책장에서 올리면 바로 쓰인다 | 받은함 | inbox/, files_list |

- Claude에게는 서버 instructions 규칙 5~8로 전한다(#96 번호): 컨텍스트를 따르기, 이 이름으로 답하기, "전체 보여 줘"·"수정본 올렸어" 같은 말을 도구로 옮기기, 넣을 곳을 말하지 않은 "저장해 줘"에는 먼저 묻기(아래 "서버 instructions").

## 절대 원칙

- **원고 본문의 원본은 저자 파일이다**(사용자 결정 #68).
  - 원고 상태(목차·결정·미해결·판 이력)는 대화 밖, Magus에 둔다. 이 원칙은 그대로다. 바뀐 것은 원고 본문의 원본이 저자 파일이라는 점이다.
  - Claude의 원고 수정안은 대화로 내고, 저자가 Word에 반영한다. Magus 안의 원고를 Claude가 고쳐 쓰는 것(book_write_chapter)은 기본 흐름이 아니다.
  - 서버 instructions 규칙 4도 이에 맞게 바꿨다(사용자 결정 #74). book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓴다.
- **에이전트는 책 전체를 들고 있지 않는다.** 한 작업의 컨텍스트는 목차·결정·미해결(book_outline) + 장 1개 + 검색 top-k로 이루어진다. 책 전체를 반환하는 도구는 만들지 않는다.
- **인용 게이트**: refs에 `status=verified`로 있는 출처만 인용할 수 있다. 원고는 **그 프로젝트의 문헌 + 지도의 연결 노드가 가리키는 노드에 꽂힌 문헌**과 대조한다(#95, `store.cite_scope`, `melchior.check.cite_floors`). 없는 출처는 본문에 `[출처 필요: 주장 요약]`으로 남긴다. 쓰기를 막지는 않는다. 표시하고 집계만 하며, 판단은 사용자가 한다.
  저자에게는 '원문 확인' 글로 보인다. **인용 점검은 원문 확인 표시와 참고문헌 항목만 보고, 컨텍스트 글을 읽어 판단하지 않는다**(#96).
- **누가 말했는지 보존한다.** 글은 저자(`author=me`)와 AI(`author=ai`)를 구분해 저장하고(AI 답은 응답한 글 parent_id), 찾기에서는 me를 먼저 보여 준다.
- **Magus 안의 원본은 사람이 읽을 수 있는 파일(markdown/json)이다. SQLite는 인덱스일 뿐이다.** (원고 본문의 ch-NN.md는 그 자체가 저자 파일의 사본이다.) 인덱스는 언제든 파일에서 다시 만들 수 있어야 한다(`magus reindex`). 파일에 없는 정보를 SQLite에만 두지 않는다. 예외는 계산으로 얻는 값(char_count, unverified_cite_count, chunks)이다.
- **프로젝트 폴더 밖의 파일·폴더는 만들지도 지우지도 않는다. 경로가 프로젝트 밖으로 풀리면 그 자리에서 멈추고 보고한다. 프로젝트 안이라도 내가 이 세션에서 만들지 않은 폴더를 통째로 지우지 않는다.**(2026-10-06 사용자 지시. 그 전날 밤 캡처 스크립트가 경로를 `C:\c\…`로 잘못 풀어 파일을 만들었고, 정리하며 `C:\c`를 통째로 지웠다.) 임시 파일은 프로젝트 안 `private/tmp/`(gitignore)에 둔다.
- **프로젝트 폴더 밖의 파일은 사용자가 경로를 명시해 지시했을 때만 읽는다.** 필요한 파일이 없으면 status.md에 "대기: 무엇을, 누가"로 기록하고 멈춘다. 다른 폴더를 뒤져 찾아오지 않는다.
  - "프로젝트 폴더 밖"에는 환경이 알려 준 경로(대화 기록 파일, 홈 폴더, Downloads)도 포함된다. 사용자가 이 세션에서 경로를 직접 적었을 때만 읽는다.
- **.env는 변수 이름 개수만 확인한다. 값을 읽는 명령(cat·값 grep·python으로 열기·길이·해시 비교 포함)은 하위 에이전트도 금지.**(2026-10-09 사용자 지시. 감사 중 SESSION_SECRET 값이 도구 출력에 찍혔다.) 보호 장치는 `.claude/settings.json`(Read 금지 규칙 + PreToolUse 훅 `.claude/hooks/env_guard.py`).
- **지시문의 참조를 찾지 못하면 밖에서 찾거나 추측하지 않는다.** status.md에 "불명: …"으로 적고, 내 판단으로 진행한 뒤 보고한다(예: "위 세 가지 테스트 프롬프트"가 메시지에 없을 때).
- **합성·테스트 데이터는 `default` 사용자에 넣지 않는다.** default는 실제 저자의 책장이다. 데모 문체 표본이 저자의 취향으로, 가짜 서지가 진짜 서지로 섞인다. 데모는 `USER_ID=demo`, 합성은 `USER_ID=synthetic`을 쓴다. CLI는 default에 `seed-demo`와 `import --synthetic`을 거부한다.
- **SaaS 준비**
  - 모든 레코드(모든 테이블의 모든 행)에 `user_id`가 있고, 모든 쿼리는 `user_id`로 필터한다.
  - P0는 단일 사용자(환경변수 `USER_ID`)다. 그래도 코드 어디에서도 단일 사용자를 가정하지 않는다. Store 메서드는 항상 `user_id`를 인자로 받는다. 서버 코어에서 user_id를 정하는 곳은 `current_user()` 한 군데뿐이다(P1에서는 인증 컨텍스트로 바꾼다).
  - 저장소는 `Store` 인터페이스(`magus/store/base.py`) 뒤에 둔다. P0 구현은 `LocalStore`(파일 + SQLite), P1 구현은 Postgres + 객체 스토리지다.
  - 전송(stdio / streamable-http)은 서버 코어(`magus/server.py: build_server`)와 분리한다(`magus/transports.py`). P0는 stdio만 구현하고 HTTP 진입점은 자리만 둔다.
- **서버는 P0에서 LLM API 키가 필요 없다.** 문체 태그 추출·요약 같은 일은 호출하는 Claude가 하고 결과를 도구 인자로 넘긴다. 외부 API는 임베딩뿐이다. `EMBEDDINGS=none`이어도 모든 도구가 FTS만으로 동작해야 한다.
- **도구 응답은 짧게.** 목록에는 상한을 두고, 긴 본문은 요청한 것만 돌려준다. book_outline은 3,000 토큰 이하다.

## 스택

- Python 3.12, uv, pytest. (uv 위치: `%APPDATA%\Python\Python313\Scripts\uv.exe`, PATH에 없음. 이 경로를 그대로 쓰기로 했다. README "uv가 PATH에 없을 때")
- MCP 공식 Python SDK **2.x** (`mcp>=2.2`, 2.2.0 기준으로 진행). 1.x와 API가 다르다.
  - `from mcp.server.mcpserver import MCPServer` (`FastMCP`는 없어졌다).
  - instructions는 생성자에서만 받는다. 그래서 `Tool.from_function(fn, name=, description=, structured_output=False)`로 도구 목록을 먼저 만들고, `MCPServer(name=, instructions=, tools=)`로 서버를 만든다.
  - JSON을 돌려주는 도구도 `structured_output=False`로 두고 텍스트 한 블록에 담는다. `structuredContent`에 같은 내용이 중복되는 것을 막기 위해서다.
  - 예상한 실패는 `mcp.server.mcpserver.exceptions.ToolError`로 올린다. 그러면 결과가 `is_error=True`가 되고 메시지가 모델에 전달된다.
  - Bash 도구의 heredoc에서는 `\\`가 `\`로 줄어든다. 백슬래시가 들어간 소스는 Edit/Write 도구로 고친다(`docs/troubleshooting/bash-heredoc-backslash.md`).
  - `server.run("stdio")` / `server.run("streamable-http", host=, port=)`.
  - 동기 도구 함수는 워커 스레드에서 실행된다 → `LocalStore`는 `check_same_thread=False` + RLock을 쓴다.
  - 테스트: `async with mcp.Client(server) as c: await c.call_tool(...)`로 in-process 연결. `c.instructions`로 instructions를 확인한다.
- SQLite + FTS5(키워드 검색). 벡터는 BLOB(float32)으로 저장하고 numpy 브루트포스 코사인으로 계산한다(P0 규모인 수만 청크까지 충분하다). 키워드와 벡터 결과는 RRF(k=60)로 합친다(`magus/search.py`). 한국어 고유명사와 학자 이름 때문에 키워드 검색은 뺄 수 없다.
  - **한국어 토큰화(확정)**: 한글·한자·가나 연속열은 2글자 bigram, 라틴 문자와 숫자는 소문자 단어로 사전 토큰화해 FTS5 unicode61에 넣는다. 질의도 같은 방식으로 쪼개 OR로 묶는다(`magus/textindex.py`). 2글자 이름("갤러")도 찾는다.
  - 임베딩은 파생값이다. 인덱스를 다시 만들면 비고, 검색할 때 `embed_missing`이 채운다. 임베딩 호출이 실패하면 FTS로 계속한다.
- docx 읽기: zip 안의 XML을 lxml로 직접 걷는다(`magus/book/docx_reader.py`). 코멘트 범위·sdt·삭제분·필드 코드를 정확히 다루기 위해서다. python-docx는 합성 fixture 생성과 export 검증에만 쓴다. docx 쓰기: `pypandoc_binary`(pandoc 3.9 내장).
- PDF 텍스트: pymupdf(`import pymupdf`). docx가 없을 때 폴백으로 원고 PDF도 받는다. **실원고가 이 경우다**(Word '메모 포함' 마크업 PDF). `magus/book/pdf_reader.py`는 레이아웃으로 구조를 되살린다.
  - 반복 머리말·쪽번호를 빼고, 오른쪽 68% 단은 말풍선 `메모 포함[Cn]`(여러 줄)으로 본다.
  - 줄 끝 공백이 없으면 이어 붙인다(한국어 줄바꿈). 들여쓰기·내어쓰기·줄 간격으로 문단을 가른다(내어쓰기 서식은 글자 크기별로 판별).
  - 글자 크기로 제목 단계를 정하고, 같은 높이 조각은 한 줄로 합친다. 앵커는 말풍선 높이의 문단이다.
  - 표는 칸 구분 없이 문단으로 들어온다.
- 임베딩: `magus/embeddings.py`. Voyage(기본 모델 voyage-3.5)와 OpenAI(text-embedding-3-small)를 표준 라이브러리 HTTP로 부른다. 모델은 `EMBEDDINGS_MODEL`로 바꾼다. 키가 없으면 경고를 남기고 FTS만 쓴다.

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `USER_ID` | `default` | P0 단일 사용자 id(영문·숫자·`_`·`-`, 64자 이하) |
| `DATA_DIR` | `./data` | 원본 파일과 index.sqlite의 루트 |
| `FILES_DIR` | `DATA_DIR`의 부모 | 도구가 받은 상대 경로(`fixtures/papers/논문.pdf`)를 푸는 기준. Desktop이 띄우는 작업 폴더는 정해져 있지 않으므로 작업 폴더 기준으로 풀지 않는다(`magus/paths.py`) |
| `EMBEDDINGS` | `none` | `none` \| `voyage` \| `openai` |
| `PUBLIC_URL` | — | 원격 모드: 바깥에서 보이는 주소. 커넥터 URL과 PRM의 resource = `PUBLIC_URL/mcp` |
| `AUTH_ISSUER` | — | 원격 모드: 인증 서버 issuer(WorkOS AuthKit). 있으면 HTTP에서 토큰 검증을 켠다 |
| `AUTH_JWKS_URL` | issuer 메타데이터의 jwks_uri | 서명 키 주소 |
| `AUTH_AUDIENCE` | `PUBLIC_URL/mcp` | 비워 둔다. `PUBLIC_URL/mcp`와 다르면 시작하지 않는다. 토큰 aud는 그 값 하나만 받는다(문자열, 또는 원소 하나인 목록. 결정 #79, `docs/decisions/shared-auth-audience.md`) |
| `ALLOWED_USERS` | — | `sub=user_id` 쉼표 목록(sub는 WorkOS 사용자 id `user_…`, 이메일 아님). 여기 없는 sub는 403. 비우면 모두 403(첫 배포에서 id를 얻는 단계). 같은 sub나 같은 이름이 두 번이면 서버가 시작하지 않는다(오류에는 항목 순서만, id는 쓰지 않음). 공개 가입은 없다 |
| `PORT` | 8000 | `magus serve --transport http`의 기본 포트 |
| `MAX_UPLOAD_MB` | 50 | 업로드 한 개 한도(책장의 원고·수정본, 올린 파일, 문헌 등록) |
| `MAX_USER_MB` | 1000 | 사용자별 저장 용량(사용자 폴더 전체) |
| `MAX_REQUEST_MB` | 2 | MCP 요청 본문 한도(넘으면 413) |
| `MAX_ATTACH_MB` | 20 | 글의 첨부 한 개 한도(#97). 한 번에 10개, 사용자 전체는 `MAX_USER_MB`에 함께 |
| `ANTHROPIC_API_KEY` | — | 웹 도움말(#97). 서버에서만 쓰고 브라우저로 내려보내지 않는다. 없으면 도움말만 "지금은 도움말을 쓸 수 없어요." |
| `HELP_DAILY_LIMIT` / `HELP_MODEL` / `HELP_MAX_TOKENS` / `HELP_DIR` | 30 / `claude-haiku-4-5-20251001` / 600 / 저장소 `docs/help` | 도움말 사용자별 하루 질문 수·모델·답 길이·문서 폴더 |
| `SESSION_SECRET` | (로컬: 실행마다 무작위) | 웹 세션·내려받기 링크 서명 비밀. **원격 모드에서는 필수**(32자 이상) |
| `WEB_CLIENT_ID` / `WEB_CLIENT_SECRET` | — | 웹 로그인용 OAuth 클라이언트(인증 서버에 등록, 콜백 `PUBLIC_URL/auth/callback`). 없으면 웹 로그인이 꺼진다 |
| `VOYAGE_API_KEY` / `OPENAI_API_KEY` | — | 해당 제공자를 쓸 때만 |
| `EMBEDDINGS_MODEL` | 제공자 기본값 | 임베딩 모델 이름 |

## 데이터 모델 (모든 테이블에 user_id가 있다)

- users(id), projects(id, user_id, title, subtitle?, title_en?, subtitle_en?)
  - **제목과 부제를 따로 둔다(#77).** 원고에서 읽는다: docx 파일 속성 제목을 `—`·`:`에서 나눠 제목·부제로, 표지에서 그 제목(과 부제) 바로 뒤의 라틴 문자 문단 둘을 영문 제목·부제로. 속성이 없으면 표지의 Title·Subtitle 서식 문단. 사람이 준 title·subtitle이 먼저다. 한글 부제를 표지에서 추정하지는 않는다.
- parts(user_id, project_id, number, title) — *추가(승인됨)*: 완료 기준의 "부 8개"를 위해 둔다. book_outline은 부 제목 아래에 장을 묶어 보여 준다.
- chapters(id, user_id, project_id, number, label?, title, status, part_number, path, char_count, unverified_cite_count, version, last_note, updated_at)
  - **번호 없는 장**: 서장·프롤로그 = 0, 맺음·에필로그·나가며 = 90, 부록 N = 90+N. `label`(서장·맺음·부록 N)을 앞머리와 인덱스에 두고, outline·export·read에서 "제N장" 대신 보여 준다. 부에 속하지 않는다.
    - **제N부 들어가며** = 100+N(#70). label `제N부 들어가며`, part_number N(그 부에 속한다). 장 목록·outline·export는 **읽는 순서**(`store.base.reading_order`)라 그 부의 첫 장 바로 앞에 온다.
    - outline 장 줄에는 번호 없는 장의 번호를 괄호로 적는다(`서장(0)`, `제2부 들어가며(102)`). 도구에 줄 번호다.
  - **status 값은 `draft` | `revising` | `done` 중 하나다.** 쓸 때 그 밖의 값이 오면 거부한다(Store는 ValueError, 도구는 스키마 enum으로 막는다).
- chapter_versions(id, user_id, chapter_id, version, path, note, created_at) — 보관된 **이전** 본문들
- chapters.edition: 본문이 같은 업로드 판(E1, E2…). 업로드가 쓰면 그 판 번호, book_write_chapter로 고치면 비워진다(= Magus에서 고친 본문, #76).
- editions(project.json `editions`): 업로드 한 번 = 판 하나. `{number, file, uploaded_at, sha256, changed, added, removed, unchanged, legacy?}`. 첫 임포트가 E1이다. 판 기록 전 임포트는 다시 올릴 때 legacy E1로 적는다.
- decisions(user_id, project_id, id, text, created_at) — id는 프로젝트별 일련번호 `D{n}`
- issues(user_id, project_id, id, text, status: open|closed, origin: import_comment|user|agent, chapter_number?, created_at, closed_note?, kind: citation|fact|general, ref_key?, ref_id?, author?, author_kind?: ai|person, comment_date?, anchor?, paragraph?) — id는 프로젝트별 일련번호 `I{n}`
  - **걸린 문장 전문(`anchor`, 1,000자까지)과 장 본문의 문단 번호(`paragraph`)를 둔다(#73).** 문단 번호는 ref_check의 paragraphs와 같은 번호다(빈 줄로 나눈 N번째, 소제목 포함). 본문 끝의 `— 원문: “…”`은 표시용 120자다. book_issues·book_read_chapter는 `¶N`으로 보인다. 다시 올리기에서 걸린 문장이 남았는지 이것으로 본다.
  - **원고 코멘트의 작성자를 보존한다(#71).** `author`는 Word 이름 그대로, `author_kind`는 이름으로 판정한다(`book/comments.py: author_kind`, 기본 AI 이름 목록 + 프로젝트의 `book/ai_authors.txt`). 파일(issues.md)에 적으므로 사람이 고칠 수 있다.
    - AI가 단 코멘트에서 온 미해결은 저자에게 보일 때도 **AI 확인 요청**으로 드러난다: book_issues 출처 `AI 확인 요청(Claude)`, book_read_chapter `[AI 확인 요청]`, outline `그중 AI 확인 요청 N건`, 웹 원고 책 확인 요청 탭의 🤖, 저자 보고서 5절.
  - `kind`: 임포트할 때 코멘트로 정한다. 직접 남긴 이슈는 `general`이 기본값이다.
    - 출처 확인 코멘트: 본문에 "확인 필요", "인용 확인 필요", "원문 대조"가 들어 있거나(공백 차이와 실제 변형 허용), 독립된 낱말 "서지"가 있는 것("일어서지"는 아님).
    - **태그가 먼저다(#72)**: `[점검·인용]`·`[점검·서지]`는 출처 확인(문헌이 지목되면 citation, 아니면 fact), `[점검·통계|수치|연도|사실|사례|계산]`은 fact다. 모르는 태그와 `[사진]`은 위 표현으로 가른다.
    - `citation`: 출처 확인 코멘트이고 문헌이 지목된 것(코멘트 본문, 또는 서로 다른 인용이 하나뿐인 앵커에서 저자·연도를 찾음).
    - `fact`: 출처 확인 코멘트지만 문헌이 없는 것(사실·수치 확인 요청). 인용처럼 보인 것이 모두 비인용 용어여도 fact다("확인 필요"가 붙어 있으면 무엇이든 확인 요청이다. 사용자 결정 #36, I46 `선하이정(1835)`).
    - `general`: 확인 요청이 아닌 코멘트(작업 안내, 검토 메모 등).
  - **비인용 용어**: 프로젝트별 `book/non_citation_terms.txt`(한 줄에 하나, `#` 주석). 연도 앞에 오는 지명·사건·기관(마닐라(1571), 모스크바 회사(1555))을 인용 추출 전체(ref_check, 집계, 이슈 연결, 코멘트 분류)에서 뺀다. 여러 낱말 용어는 저자 앞 글과 이어서 본다. `--replace` 재임포트 때 새 프로젝트로 옮긴다. CLI `magus terms`로 고친다.
  - `ref_key`: citation 코멘트에서 뽑은 저자·연도 후보(`daeschler2006`, 한글이면 조사를 뗀 `갤러2022`). 코멘트 본문에 없으면 앵커 원문에서 찾고, 그래도 없으면 null이다. 추출기는 `magus/melchior/citations.py`이고, ref_check도 이것을 쓴다.
  - `ref_id`: ref_key를 refs(key 또는 aliases)에서 해석한 **정식 ref key**(예: `갤러2022` ⇒ `galor2022`). refs 행 id는 재생성되면 바뀌므로 key를 쓴다. 임포트, ref_add, ref_import_bibliography 뒤에 다시 계산한다.
- chapters.unverified_cite_count: verified가 아닌 **고유 문헌 수**(unverified + unknown, uncertain 제외). 출현 횟수가 아니다(사용자 결정 #17 변경). 파생값이라 인덱스에만 두고, 서버 시작·`magus reindex`·refs 변경·장 쓰기 때 다시 계산한다.
  - chapters.unverified_cite_keys / uncertain_cite_keys(JSON): 같은 때 함께 계산하는 그 장의 미확인 문헌 key와 미연결 한글 표기 key다. outline은 장 사이 합집합으로 책 전체 고유 수를 낸다(SCHEMA_VERSION 8에서 도입).
  - 이 캐시는 refs가 바뀌면(ref_add, ref_import_bibliography, `magus alias`, `magus terms`) 그 자리에서 사용자의 모든 장을 다시 계산한다(실원고 40장 0.3초). ref_add 직후 outline 수가 줄어드는지 테스트로 고정했다(사용자 결정 #43).
  - **한 번 준 번호는 절대 재사용하거나 다시 매기지 않는다.** 마지막 번호는 project.json의 `last_decision_id`/`last_issue_id`에 둔다.
- refs(id, user_id, key, aliases json, bib json, status: unverified|verified, has_fulltext, file_path?, created_at, book?) — book(bib.json `"book"`)은 그 문헌 글이 든 책(카테고리 id, #96)
  - key는 첫 저자 성(소문자 영문) + 연도다. 예: `daeschler2006`, `galor2022`. 한글 표기(갤러, 다이아몬드 등)는 aliases에 넣는다.
- ref_passages(id, user_id, ref_id, text, reason, locator?)
- (#96 전, 이전 전용) ideas(id, user_id, text, kind: thought|ai|article|conversation|tv|other, origin?, author: me|ai, parent_id?, created_at, title?, title_by?: ai|author, edited_at?, edited_by?: author|ai) — 색인 테이블은 v20에서 뺐다. 파일(`shelf/casper`)은 이전 때 책의 글이 된다. 제목은 선택(#92). 제목도 검색한다. edited_*는 처음 쓴 뒤 고친 사람·시각(웹에서 저자가 고치면 author. 처음 쓴 사람 author는 그대로). 값이 없으면 파일에 키를 쓰지 않는다(옛 코드로 되돌려도 읽힘). SCHEMA_VERSION 16
- (#96 전, 이전 전용) style_entries(id, user_id, passage, reason, work?, tags json, created_at, tags_by?: ai|author) — 이전 때 글(passage → 내용, work → 위치, tags → "키: 값")이 된다. tags_by는 태그를 누가 정했나(#89. Claude가 뽑음 ai / 저자가 말함 author, 기록 전 항목은 비어 있음). SCHEMA_VERSION 13
- categories(id, user_id, name, name_key, template, color, fields json, schema_version, created_at, updated_at, contexts json) — 글이 쌓이는 책(#92 카테고리 → #96 책). (user_id, floor, name_key) 유일, 60권까지.
  이전으로 생긴 책은 id `ideas-<프로젝트>`·`styles-<프로젝트>`·`refs-<프로젝트>`와 `"legacy": 옛 종류`(revert용).
- category_items(id, user_id, category_id, title?, title_by?, content, fields json, author: me|ai, tags json, chapters json, schema_version, created_at, updated_at, edited_at?, edited_by?,
  reason?, location?(파일 "where"), passages json(쓸 부분), parent_id?, origin?, kind?, tags_by?, scrap) — 글(#96). 덧붙은 칸이 있으면 schema_version 2
  - **scrap(#99)**: 스크랩(별표). 파일에는 켰을 때만 `"scrap": true`(형식 버전 그대로, 끄면 키를 뺀다, updated_at 그대로). 문헌 글은 bib.json의 같은 키(refs.scrap).
    put_category_item은 이 코드가 모르는 칸을 파일에서 지우지 않고, 웹 고치기·스크랩은 `patch_category_item`으로 바꾼 칸만 쓴다. SCHEMA_VERSION 22(첨부 이름 색인)
- **컨텍스트(#96)**: 붙인 곳의 파일에 사본 `"contexts": [{name, text}]`(category.json·project.json·document.json·지도 노드). 자주 쓰는 컨텍스트 `shelf/contexts.json`
  = {schema_version 1, contexts: [{id, name, text, created_at, updated_at}]}. 파일이 없으면 처음 제공하는 넷(`contexts.DEFAULTS`, 읽기만으로는 쓰지 않음). 색인 v20.
- 책장 설정(shelf/settings.json, 인덱스 없음): 기본 카테고리 책 색, 내 색(12개까지), 제목 기본값 ask|ai|none
- **프로젝트·지도(#95, 옛 층 #93)**: 「내 서재」(id `common`, 옛 공용 층) + 작업물(프로젝트)마다 하나. ideas·style_entries·refs·categories·documents의 `floor`
  (파일의 "floor"가 원본) = 그 항목이 속한 프로젝트 id(키 이름은 층 이전 그대로). `shelf/floors.json` = {order, builtins(프로젝트마다 기본 카테고리), changed_at, last_move, last_undone}.
  기본 카테고리(생각·문체·문헌)는 한 프로젝트에 종류마다 하나. floors.json이 없으면 이전 규칙과 같은 배치로 읽는다(`store/floors.py: legacy_layout`). 프로젝트 20개까지, id `common`은 못 쓴다.
  - 지도 `shelf/maps/<프로젝트>.json` = {schema_version 1, updated_at, nodes: [{id, name?, x, y, color?, books: [ms|ideas|styles|refs|<카테고리 id>|doc.<id>] 또는 link: {project, node}}], edges: [[a, b]]}.
    가운데 노드 id `center`(이름은 프로젝트 제목, 원고 책은 여기만). 노드 40·노드마다 책 12. 연결 노드는 책을 갖지 않는다(연결의 연결은 원본으로, 같은 원본은 한 번).
  - **지도 파일이 없으면 지금 배치에서 계산한다**(가운데에 원고·문서 책, 기본 카테고리·카테고리는 이름이 같은 노드 하나씩, 「내 서재」의 문헌(과 자기 문체가 없으면 문체)으로 가는 연결 노드).
    있어도 읽을 때 맞춘다(없어진 책은 빼고, 노드에 없는 책은 이름이 같은 노드나 빈자리의 새 노드). 책이 생기거나 옮겨 오면 놓을 노드와 함께 그 자리에서 파일에 적고,
    지도를 바꾸는 쓰기 전에는 모든 지도를 먼저 파일로 적는다(`store/maps.py: ensure_maps`). 옮기며 생긴 노드는 되돌릴 때 비면 치운다(FloorMove.made_node).
  - 인용 점검 범위 `cite_scope` = 자기 + 연결 노드가 가리키는 노드에 그 프로젝트의 문헌 책이 꽂힌 프로젝트. 문헌은 사람마다 한 권(key 하나): 이 원고가 못 보는 다른 프로젝트에만 있는
    문헌을 쓰게 되면 「내 서재」로 옮기고 두 지도에 연결 노드를 붙인다(`project_args.share_ref`). refs.moved(bib.json "moved" = {at, from, to, reason})에 옮긴 기록.
  - 휴지통의 노드 `trash/shelf/nodes/<프로젝트>/<노드>.json`(이어진 선 포함). 되살리기 `magus trash restore node <프로젝트>/<노드>`.
- **문서 책(#94)**: documents(id, user_id, floor, title, doc_type, project_id, color, edition, versions json, created_at, updated_at). 원본은 `shelf/documents/<id>/document.json`
  ({id, title, title_by, doc_type: source_check, project_id, floor, color, versions: [{number, at, edition, method, preface_by, stats}], schema_version 1}) + `v1.md, v2.md…`(만든 때의 본문).
  「내 서재」에는 두지 않는다(원고가 있는 프로젝트에만). 기준 원고의 마지막 수정본 > 문서의 edition이면 "옛 판 기준". 휴지통은 `trash/shelf/documents/<id>/`. 책장 검색 레인 `document`(웹 전용).
  projects.color(project.json `color`, 원고 책 색). 인덱스 v19.
- chunks(id, user_id, owner_type, owner_id, lane: ref_picked|ref_full|style_passage|ref_bib|category, text, embedding blob?) + chunks_fts(#96: 글은 모두 category 레인, idea_*·style 레인은 쓰지 않음)
  - style_passage(문체 구절·출전)·ref_bib(문헌 서지)는 **웹 책장 검색 전용**이다. 도구 검색(style_search·ref_search)은 보지 않고 임베딩도 하지 않는다(#92). category는 owner_id `<카테고리 id>/<항목 id>`. SCHEMA_VERSION 15

### 디스크 구조 (원본)

```
data/users/<user_id>/shelf/casper/<id>.json                       # (#96 전) 생각. 이전 때 책의 글로 옮긴다
data/users/<user_id>/shelf/melchior/<key>/{bib.json, passages.json, full.txt}
data/users/<user_id>/shelf/balthasar/<id>.json                    # (#96 전) 문체. 이전 때 책의 글로 옮긴다
data/users/<user_id>/shelf/contexts.json                          # 자주 쓰는 컨텍스트(#96). 없으면 처음 제공하는 넷
data/users/<user_id>/projects/<project_id>/project.json           # title, subtitle?, title_en?, subtitle_en?, created_at, parts, last_*_id
data/users/<user_id>/projects/<project_id>/book/ch-01.md … ch-35.md
data/users/<user_id>/projects/<project_id>/{decisions.md, issues.md, versions/}
data/users/<user_id>/projects/<project_id>/book/answers.md         # 저자 확인 질문지의 답(#84). 질문은 저장하지 않는다
data/users/<user_id>/projects/<project_id>/original/{원고 사본, unsplit.md, import-report.md, E2-<원고>, E2-unsplit.md, E2-reupload-report.md …}
data/users/<user_id>/projects/<project_id>/removed/ch-NN-E<판>/   # 새 판에 없는 장(본문 + 이전본). 지우지 않는다
data/users/<user_id>/projects/<project_id>/exports/*.docx       # book_export
data/users/<user_id>/trash/<project_id>-<시각>/                   # book_import replace=True로 밀려난 프로젝트
data/users/<user_id>/trash/shelf/{casper,balthasar}/<id>.json    # (#96 전) 휴지통의 생각·문체(#88). 이전 때 trash/shelf/category-items/<책>/로
data/users/<user_id>/shelf/categories/<id>/{category.json, items/<글 id>.json}   # 글이 쌓이는 책(#92 → #96). category.json에 contexts
data/users/<user_id>/shelf/categories/<id>/files/<글 id>/<첨부 id>/<파일 이름>   # 글의 첨부(#97). 문헌 글은 shelf/melchior/<key>/files/<첨부 id>/<이름>
data/users/<user_id>/trash/shelf/attachments/<책 id>/<글 id>/<첨부 id>/       # 뺀 첨부(#97, 지우지 않음). 글 휴지통은 category-items/<책>/files/<글>/
data/users/<user_id>/shelf/settings.json                          # 책 색·내 색·제목 기본값(#92)
data/users/<user_id>/shelf/floors.json                            # 프로젝트 순서·프로젝트마다 기본 카테고리·마지막 옮기기(#93·#95)
data/users/<user_id>/shelf/maps/<프로젝트 id>.json                 # 지도: 노드(위치·색·책·연결)와 선(#95). 「내 서재」는 common.json
data/users/<user_id>/trash/shelf/nodes/<프로젝트>/<노드>.json        # 휴지통의 노드(#95)
data/users/<user_id>/shelf/documents/<id>/{document.json, v1.md, v2.md …}   # 문서 책(#94). 만든 때의 사진, 다시 만들면 새 vN
data/users/<user_id>/profile.json                                # 메일(웹 로그인 때 userinfo)·표시 이름(내 정보에서). 로그에 남기지 않는다
data/users/<user_id>/trash/shelf/categories/<id>/                 # 휴지통의 카테고리 통째. 항목 하나는 trash/shelf/category-items/<카테고리 id>/
data/users/<user_id>/inbox/                                       # 올린 파일(옛 받은함: Claude에게 이름으로 건넬 파일·문헌 등록한 논문). 책장에서 올린 원고는 여기 두지 않고 original/에만
data/index.sqlite
```

### 파일 형식

- `ch-NN.md`: 앞머리(front matter) 다음에 본문이 온다. 장 제목은 앞머리에만 두고 본문에는 넣지 않는다(export할 때 `# 제N장 제목`을 붙인다).
  - **앞머리(front matter)는 도구 경계를 넘지 않는다.** 메타는 서버가 관리한다. 읽기는 본문(content)과 메타 필드를 따로 주고, 쓰기는 본문만 받는다. 호출자가 앞머리를 붙여 보내면 벗겨 내고 응답 warnings에 경고를 넣는다(`docs/decisions/front-matter-boundary.md`).
  - 앞머리에는 **현재 상태만** 둔다. 이력은 versions/에만 남긴다.
  ```
  ---
  title: 물고기의 결심
  status: draft
  part_number: 1
  version: 3
  updated_at: 2026-10-03T02:40:00.123Z
  last_note: 2절 도입부 재작성
  ---

  본문…
  ```
- `versions/ch-NN.vK.md`: 덮어쓰기 직전의 파일을 앞머리째로 복사해 둔다. chapter_versions는 이 파일들에서 다시 만든다.
- `decisions.md` / `issues.md`: 항목마다 `## D3 · <시각>` 또는 `## I3 · open` 제목을 달고, 그 아래 `- key: value` 메타 줄과 빈 줄, 본문(여러 줄 가능)을 둔다.
- 시각은 모두 UTC ISO 8601, 밀리초 단위다(`2026-10-03T02:40:00.123Z`). 프로세스 안에서는 항상 증가하므로 문자열 정렬이 곧 시간 순서다.

### 규칙

- **현재 프로젝트**: 도구에 project_id가 없으면 그 사용자의 가장 최근에 갱신된 프로젝트를 쓴다.
  - 그래서 book_outline 응답 첫 줄에는 항상 `프로젝트: <제목> (<id>)`를 쓴다. 사용자에게 프로젝트가 2개 이상이면 그 사실과 다른 프로젝트 목록을 한 줄 덧붙인다.
- **최근 변경**은 현재 장 머리(version·last_note)와 chapter_versions를 합쳐 시각 내림차순으로 정렬한 것이다.
- 장 파일을 사람이 직접 고쳤다면 `magus reindex`로 인덱스를 갱신한다.

## MCP 도구 (이름 고정)

### 받은함 (`magus/inbox.py`) — P1
- `files_list()` → 올린 파일(옛 받은함) 목록(이름·크기·올린 시각·쓰임)과 사용량/한도, 그리고 게시판 글에 첨부한 문서(docx·pdf·md·txt, 새것부터 20개)를
  `첨부:<첨부 id> · 이름 · 크기 · 시각 · 「책」 책의 글 「제목」`으로(#98). 파일 인자에 `첨부:<id>`를 주면 FileResolver가 그 첨부를 읽는다(`inbox.attached_file`, `Store.file_attachments`). *(P1에서 추가된 도구. 휴지통 도구 둘(#88), 카테고리 도구 일곱(#92), 저자 확인 질문지 둘(#84)까지 30개였고, #94에서 idea_delete·style_delete를 category_trash에 합치고 book_document를 더해 29개, #96에서 idea_add·style_add·ref_add를 category_put에, idea_search·style_search·ref_search를 category_search에 합쳐 **23개**(8,416토큰))*
  - 도구 문장에서는 '받은함' 대신 '올린 파일'이라고 쓴다(#94). 코드·폴더 이름(inbox)은 그대로.
- 파일 인자(book_import의 path, category_put의 file, idea_add_conversation의 path)는 **받은함 파일 이름**을 받는다.
  - 원격(HTTP)에서는 이름만 받는다. 경로를 주면 "받은함에 없다" 오류다(서버 파일을 읽지 못하게).
  - 로컬(stdio) 개발용으로는 받은함에 없으면 로컬 경로(절대 또는 FILES_DIR 기준)도 받는다.
  - 이 차이는 `FileResolver` 한 곳에만 있다(`build_server(local_files=)`, CLI가 stdio일 때만 True).
- 파일 이름: 폴더 구분자·`..`·숨김·제어 문자·예약 이름을 거부하고, 200바이트 이하. 형식은 .docx .pdf .md .txt만 받는다.
- 업로드(`save_upload`)는 한도를 지킨다: 한 개 `MAX_UPLOAD_MB`, 사용자 폴더 전체 `MAX_USER_MB`. 넘으면 무엇이 얼마인지 밝힌 오류를 낸다.
- category_put(file)이 받은함 파일을 쓰면 refs의 file_path에는 `inbox/<이름>`을 남긴다.
- 로컬 개발: `magus inbox [--add 파일…] [--remove 이름…]`. 원격에서는 웹 업로드(4단계)로만 들어온다.

### 책 (`magus/book/`)
- `book_outline(project_id?)` → **3,000 토큰 이하**. 모든 원고 작업은 이 도구로 시작한다.
  - 첫 줄은 `프로젝트: 제목 (id)`다. 부제·영문 제목이 있으면 둘째 줄에 `부제: … · 영문: … — …`을 싣는다(#77). 프로젝트가 2개 이상이면 안내 줄을 붙인다.
  - 집계 줄: `35장 + 서장·부 들어가며 2·맺음·부록 1~3 · 8부 · N자 · 미확인 문헌 N편 · 미연결 N · 열린 확인 요청 N`. 미확인 문헌은 **책 전체 고유 수**(여러 장에 나오는 문헌은 한 번)이고 저자 보고서 1절의 문헌 수와 같다. 장별 수는 각 장 줄에만 싣는다.
  - 미연결(uncertain: 한글 표기인데 refs와 못 이음)은 미확인 수에 넣지 않지만 숨기지 않는다. 머리줄에 따로 세고, ref_check에는 별도 목록(`uncertain`, `unique_uncertain`)으로 준다(사용자 결정 #29).
  - 장 목록은 부 제목 아래에 묶고, 각 줄에는 집계만 싣는다: `제N장 제목 · 상태 · N자 · 확인 요청 n · 미확인인용 n`. 장별 확인 요청 수에는 코멘트 유래까지 모두 센다.
  - 확인 요청 전문은 origin이 `user`·`agent`인 것만 싣는다(절 제목 `## 열린 확인 요청`). `import_comment`는 `코멘트 유래 확인 요청 N건(citation · fact · general 수) — book_issues(kind)로 조회` 한 줄로만 보인다.
  - 최근 결정 10개, 최근 변경 5개도 싣는다.
  - 머리에 수정본 줄을 싣는다(#76): `수정본 E2 · 마지막 업로드 10-06 14:20(원고.docx) · 그 뒤 Magus에서 고친 장 0`(첫 업로드는 `처음 올린 문서 E1`, 기록 전 임포트는 `수정본 기록 없음(…)`). 마지막 업로드 뒤 7일(`STALE_UPLOAD_DAYS`)이 지나면 "최신본을 올려 수정본으로 올리도록 저자에게 먼저 묻는다"를 붙인다. 서버는 Word 파일이 바뀌었는지 모르므로 시각만 알린다.
  - 수정본을 올린 뒤 "해결됐을 수 있음"인 확인 요청이 있으면 `그중 해결됐을 수 있음 N건` 줄을 싣는다.
  - 예산 배분 순서는 머리 → 목차 → 직접 남긴 미해결 → 결정 → 변경이다. 넘치는 것은 "외 N건"으로 접는다.
- `book_issues(status=open|closed|all, chapter_number?, origin?, kind?, limit=50, project_id?, possibly_resolved=false)` → 미해결 목록(조회 전용). 한 줄에 `I번호 · 상태 · 장 ¶문단 · 출처 · kind(→ref_key) · 내용(300자)`를 담는다. 출처는 user·agent·원고 코멘트(작성자)·AI 확인 요청(작성자). 다시 올린 뒤 표시된 것은 `해결됐을 수 있음(이유, E2)`이 붙고, possibly_resolved=true면 그것만 보인다. limit 최대 200. *(사용자 요청으로 추가된 도구)*
- `book_read_chapter(number, project_id?)` → JSON을 돌려준다. `content`(본문 markdown만), `title`, `status`, `part_number`, `version`, `last_note`, `unverified_cites`, `open_issues`(그 장의 열린 미해결). *(1단계 검토 반영으로 미리 구현)*
  - **`unverified_cites`**: 인용 게이트 결과 중 verified가 아닌 것(`{key, status: unverified|unknown, count, cited_as}`). `[]`는 검사했고 미확인 인용이 없다는 뜻이다(null은 검사 전, 4단계 이후에는 나오지 않는다). `needs_source`는 `[출처 필요: …]` 표시 수다.
- `book_write_chapter(number, content, note, title?, status?, project_id?)` → **#68 이후 기본 흐름이 아니다**(저자가 Magus에 저장하라고 할 때만). 위치는 다시 올리기 설계안 7절을 따른다. content는 본문만 받는다. 이전 본문을 versions/에 저장하고 새 본문을 기록한 **뒤** ref_check를 자동 실행한다(막지 않음). 응답에 `unverified_cites`와 `needs_source`를 담고 장별 집계를 갱신한다. 없는 번호면 새 장을 만든다. front matter가 붙어 오면 벗겨 내고 `warnings`에 경고를 넣는다. 빈 본문은 거부한다.
- `book_decide(text, project_id?)` → D번호.
- `book_issue_add(text, chapter_number?, origin=user|agent, project_id?)` → 없는 장 번호는 거부한다.
- `book_issue_close(id="I3"|"3", note?, project_id?)`
- `book_import(path, project_id?, title?, subtitle?, replace=false)` → 로컬 docx(없으면 pdf)를 새 프로젝트로 만든다(`magus/book/importer.py`).
  - 제목: "제N장"·"제N부"(공백·콜론·대시 변형 허용, 제목이 다음 줄에 와도 됨)와 번호 없는 장(서장·맺음·부록 N, 제목 서식이 있을 때만). "제N부 들어가며 …"는 부 제목이 아니라 그 부의 장(100+N)이다(#70).
  - 같은 장 번호가 여러 번 나오면(목차) 제목 서식이 있는 것, 그다음 본문이 가장 긴 것이 진짜다.
  - 첫 제목 앞의 글(표지·목차)과 부 서문은 `original/unsplit.md`에 둔다(목차 점선은 줄임). 장 안의 절·소절은 `##`·`###`이다.
  - 코멘트 표현: "확인 필요"(확인필요·확인할 필요), "인용 확인 필요", "서지"(문맥 판정), "원문 대조"(원문과·으로 대조).
  - key를 앵커에서 가져오는 것은 앵커 문단에 서로 다른 인용이 하나뿐일 때만이다.
  - 코멘트는 issues(origin=import_comment)로 넣고, 앵커 블록이 속한 장 번호를 기록한다. `classify_comment(코멘트, 앵커 원문)`으로 kind와 ref_key를 붙이고, 본문에 "— 원문: “앵커 120자”"를 덧붙인다.
  - 참고문헌 섹션은 import_bibliography로 넘긴다. 그다음 citation 이슈를 refs와 연결한다.
  - 그림·수식은 자리표시자(`[그림 N]`, `[수식]`)로 남긴다. docx 표는 칸의 글까지 markdown 표(`| 칸 |`)로 싣는다(#69, 칸이 모두 비면 `[표 N]`). export에서는 Word 표로 나간다. 원본은 **무엇보다 먼저** original/에 복사한다.
  - 재실행: 같은 project_id는 거부한다. `replace=true`면 기존 프로젝트를 trash/로 옮긴다. refs는 이미 있는 key를 건드리지 않는다.
    - **replace는 수정본 올리기가 아니다.** 결정·직접 남긴 확인 요청·닫은 확인 요청·판 이력까지 휴지통으로 간다. 같은 책의 수정본은 `new_edition=true`로 올린다(아래).
  - **수정본 = 같은 책의 새 업로드**(`book_import(path, project_id, new_edition=true, force?)`, CLI `--new-edition`, 웹 "수정본으로 올리기", `magus/book/reupload.py`, #76)
    - 같은 책은 사용자가 project_id로 고른다. 장 제목이 기존 판과 30% 미만으로 겹치면 멈춘다(맞으면 force).
    - 장 대응은 같은 번호 = 같은 장이다. 제목이 바뀌면 리포트에 적는다. 본문이 바뀐 장만 다시 쓰고(이전본은 versions/, note `수정본 E2 업로드: …`), 그대로인 장은 버전을 올리지 않고 판 번호만 적는다. 새 판에 없는 장은 removed/로 옮긴다. Magus에서 고친 장이 덮이면 리포트에 ⚠로 남긴다.
    - 원고 코멘트는 지문(`comment_fp` = 작성자 + 날짜 + 본문)으로 기존 미해결과 잇는다. 같은 코멘트는 다시 넣지 않고(번호·상태 유지, 닫힌 것은 닫힌 채), 새 코멘트만 새 미해결이 된다. 지문이 없는 옛 미해결은 코멘트 본문으로 잇는다.
    - 원고에서 코멘트가 사라진 열린 확인 요청은 `stale`로 표시만 한다: 걸린 문장이 아직 있으면 `comment_removed`, 없으면 `anchor_missing`. **자동으로 닫지 않는다.** 닫는 것은 저자다.
    - 결정·직접 남긴 미해결·책장(영감·문헌·문체)은 건드리지 않는다(해시 테스트, `tests/test_reupload.py`). 참고문헌은 새 문헌만 더한다.
    - **참고문헌 key 안정화**: 같은 기본 key(첫 저자 성 + 연도)가 목록에 둘 이상이면 기존 refs와 제목으로 짝을 짓고, 짝이 없는 것만 빈 접미사(-2, -3)를 받는다. 목록 순서가 바뀌어도 key가 문헌을 따라간다(최신본에서 hsieh2019가 다른 논문을 가리키게 되던 문제). 하나뿐이면 예전처럼 "기존 서지와 다름"만 남긴다(#6).
    - 리포트는 `original/E{n}-reupload-report.md`에 남는다.
  - 리포트: 장·부 수, 분할 못 한 구간, 목차로 판단해 버린 제목 줄, 빠진 장 번호, 코멘트→이슈(kind별, ref_key 비율, 장 밖 코멘트), 참고문헌→refs(파싱 실패 줄, key 충돌), `ch-NN.md ↔ 제목` 매핑표. 코멘트 분류 전체 표는 `original/import-report.md`에 있다. 평소에는 리포트를 낸 뒤 멈추고 사용자의 매핑 확인을 기다린다.
- `book_export(path?, project_id?)` → 부 H1·장 H2·소제목 H3로 합쳐 docx를 만든다. path는 파일 이름만 받고 `exports/`에 저장한다. 코멘트와 그림은 복원하지 않는다.
- `book_document(kind=출처 확인 문서, project_id?, node?, title?, title_by?, untitled?, preface?, document_id?)` → 원고에서 문서 책을 만든다(#94, `book/document_tools.py`, `book/documents.py`).
  - 출처 확인 문서: 한눈에 / 1 답해 주실 질문(연도 불일치·참고문헌에만은 2절에) / 2 원고 불일치 / 3 사실·수치 확인 요청 / 4 원문 확인 우선 문헌 / 5 장별 미확인 문헌 수 / 6 이전 수정본 대비 바뀐 점.
    내용은 서버가 데이터로 만든다(저자 보고서 생성기 `melchior/author_report.py`의 절 함수를 함께 쓴다). Claude는 preface(2,000자)만, "Claude(AI)가 쓴 머리말입니다."로 표시.
  - 놓는 곳은 그 원고 프로젝트의 노드(node, 없으면 가운데 노드). 제목 규칙은 idea_add와 같다(비면 "<원고 제목> 출처 확인 문서"). document_id를 주면 지금 원고로 다시 만든다(이전 것은 이력).
  - 응답은 한 줄(제목·프로젝트·노드·기준 수정본·질문·열린 확인 요청·미확인 문헌 수) + "저자에게 책장에서 볼 수 있다고 알린다(수치는 대화에 옮겨 쓰지 않는다)".

### 문헌 — Melchior (`magus/melchior/`)
- `ref_import_bibliography(text, project?, book?)` → (#96) 넣을 책은 book, 없으면 그 프로젝트에서 문헌 글이 가장 많은 책, 없으면 「참고문헌」 책을 만들고 「논문」 컨텍스트. 줄 단위로 저자·연도·제목을 파싱하고 key를 만든다(`magus/melchior/bibliography.py`). status는 unverified다.
  - 지원: APA, 국문 『』, 연도 후치형(근사), 연도 접미사 2012a.
  - `[국역: 이름 성, …, 연도]` 꼬리가 있으면 한글 성 + 원서·번역서 연도를 aliases에 넣는다.
  - 파싱하지 못한 줄은 key `raw-<해시>`, bib.raw로 보관한다. 같은 목록 안 key 충돌은 `-2`를 붙인다.
  - 같은 문헌(첫 저자·연도·제목, 또는 같은 원문 줄)이 목록에 두 번이면 "중복 서지"로 따로 리포트한다. 원고 오류일 수 있다(사용자 결정 #5).
  - 이미 있는 key는 건드리지 않는다. 새 목록의 제목·연도가 기존과 다르면 "기존 서지와 다름"으로 리포트만 한다(갱신하지 않음, 사용자 결정 #6).
- (#96에서 뺌) `ref_add` → `category_put(book, author, source=서지, checked=true, parts=[{text, reason, where}], file?, aliases?)`(`melchior/refs.py: add_ref`). 아래 규칙은 그대로다. status=verified로 넣는다.
  - **발췌가 하나 이상 있어야 받는다.**
  - bib은 `{key}` 또는 `{authors|author, year, title…}`이다. 같은 key나 alias가 unverified로 있으면 verified로 올리고 bib·aliases·발췌를 합친다.
  - key도 저자·연도도 없으면 bib 제목이나 전문 첫머리 5,000자에 참고문헌 제목이 그대로 있는 문헌 하나를 고른다(둘 이상이면 오류). "fixtures/papers/<파일>.pdf를 문헌으로 등록해 줘"처럼 파일만 받는 경우다.
  - 전문은 txt/md/pdf/docx 파일이나 full_text로 받는다. 상대 경로는 `FILES_DIR` 기준이다(book_import, idea_add_conversation도 같다). 발췌는 ref_picked 레인, 전문은 ref_full 레인으로 청킹한다.
- (#96에서 뺌) `ref_search` → `category_search(query, book?, full=true)`. 쓸 부분(ref_picked)을 먼저, 전문(ref_full)은 full=true일 때만.
- `ref_check(chapter_number, project_id?)` → JSON: verified / unverified / unknown(refs에 없음) / uncertain(한글 표기인데 refs와 못 이음: 인명이면 aliases 필요, 지명·사건이면 무시) 목록과 `unique_unchecked`, `needs_source`.
  - 문헌마다 `count`(출현), `cited_as`, `paragraphs`(장 본문의 문단 번호), `matched_by`(alias·음역 추정·연도 a/b 모호)를 담는다.
  - **연도 a/b가 모호하면 잇지 않는다**(사용자 결정 #31). `Keynes(1930)`·`케인스(1930)`인데 참고문헌에 1930a·1930b만 있으면, key `keynes1930a/b`·상태 unverified·`candidates`(후보 key와 제목)로 보이고 한 문헌으로 센다. 이슈의 ref_id도 비워 둔다.
  - **추정은 저장하지 않는다**(음역 추정·a/b 모호, 결정 #28·#31). 저자가 확정하면 CLI `magus alias <key> <표기>`로 aliases에 넣는다(예: `magus alias keynes1930b "케인스(1930)"` → `케인스1930`). 연도를 빼고 적으면 문헌 연도(a/b는 뗌)를 붙인다.
  - 인용 패턴: `(Daeschler, Shubin & Jenkins, 2006)`, `Clack(2012)`, `Hu et al.(2023)`, `갤러(2022)`, `(헨릭, 2016)`. 실원고에서 추가로 확인한 것은 다음과 같다.
    - 괄호 안 다중 인용, 설명 뒤 인용 `(1990년 국제달러, Maddison, 2001)`, 연도 범위 `(Toynbee, 1934–1961)`
    - 발음 부호·소문자 접두어·여러 단어 저자(Prüfer, de Vries, Ibn Khaldun), 한자 저자(田代和生)
    - 한글 공저자 `넌·첸(2011)`, 한 글자 성 `셰 등(2019)`, 띄어 쓴 일본 이름 `다시로 가즈이(1981)`
  - 해석: key → aliases → 공저자로 동명 판별 → 연도 a/b → (한글만) 같은 연도 안 음역 추정(`magus/melchior/translit.py`). 지명·사건 접미사와 일반명사는 저자로 보지 않는다.
- **저자 확인 질문지(#84)**: `book_questions(status=open|waiting|all, type?, project_id?)` → 저자만 답할 수 있는 인용 질문(연도 불일치 year·참고문헌에만 bibonly·한글 표기 추정 translit·연도 a/b ab·같은 저자·연도 두 편 pair·미연결 unlinked·중복 서지 dup). 질문은 매번 지금 원고·문헌에서 계산하고(저장하지 않음), 3,000토큰 예산. `book_answer(question_id, choice, note?, project_id?)` → 표기를 잇는 답은 alias, "사람 이름이 아님"은 비인용 용어로 바로 반영하고 수를 다시 계산한다. "Word에서" 답은 결정(D번호)으로 남겨 "원고 반영 대기"가 된다. 답은 프로젝트의 `book/answers.md`(사람이 읽는 파일)에 쌓인다(`magus/melchior/questions.py`, `question_tools.py`). 웹 `/questions`("답해 주실 질문", 조회 전용, 코드 대신 설명, `/book`에서 링크)와 수정본 리포트의 "답해 주실 질문: 새로 생김 · 저절로 닫힘 · 답했지만 원고에 아직 그대로" 줄이 있다.
- 책 전체 집계는 CLI `magus cite-report --project-id <id>`로 낸다(`magus/melchior/report.py`).
  - 내용: 고유 미확인 수, 많이 인용된 순위, 참고문헌에 없는 인용(+같은 저자 다른 연도 힌트), uncertain, 추정 연결, 미인용 항목.
- 저자용 보고서는 CLI `magus author-report --project-id <id> --out private/reports/<날짜>-인용-점검.md`로 만든다(`magus/melchior/author_report.py`, 같은 이름의 docx도 만든다).
  - 독자는 개발자가 아니다. key 대신 "저자(연도) 『제목』", 설명은 한두 문장, 3쪽 이내. 대상 사용자·프로젝트의 데이터만 쓴다.
  - 7개 절: 한 줄 요약 / 바로 확인할 것(연도 불일치, 참고문헌에만 있는 것) / 답해 주실 질문(음역 추정, 동명 판별) / 확인 순서 상위 20 / 사실·수치 요청(fact) / 장별 미확인 수 / 앞으로의 방식.

### 영감 — Casper (`magus/casper/`)
- (#96에서 뺌) `idea_add` → `category_put(book, author, content, title?, title_by?, untitled?)`. 제목 규칙은 그대로: **제목을 주면 title_by가 반드시 있어야 한다**(기본값 없음, #92-e: 저자가 지은 제목이 AI 것으로 기록되지 않게). 제목을 주지 않고 untitled도 아니면 저자의 제목 기본값을 따른다(#92: 매번 묻기면 저장하지 않고 먼저 묻게 하는 오류, AI가 짓기면 지어서 다시 부르게 하는 오류, 비워 두기면 제목 없이 저장).
- `idea_add_conversation(book, markdown? | path?, origin?, project?)` → (#96) 그 책의 글로 넣는다(AI 발화는 parent_id·kind=conversation). 화자 마커로 발화를 나눈다(`magus/casper/conversation.py`). 로컬 .md path도 받는다(긴 기록용).
  - 지원 마커(한 파일 안 혼용 가능): `**사용자:**`/`**Claude:**`(변형: `**사용자**:`, 나/User, ChatGPT/AI), `질문:`/`답변:`(괄호 설명 허용: `**답변(수정된 평가):**`), 제목형 `## 질문 N` / `### 답변`, `> 인용 블록` 뒤의 `**Claude 요지**`. 사용자 발화 전체가 인용 블록이면 `>`를 뗀다.
  - 사용자 발화 하나는 ideas(author=me, kind=conversation)가 되고, 바로 뒤의 AI 발화는 ideas(author=ai, parent_id=그 사용자 발화)가 된다. 대화 사이 구분 제목(`## 대화 N`, `---`)은 발화에서 떼어 낸다.
  - 리포트: me N건, ai N건, 분리 실패 구간(서문 본문, 빈 마커, 고아 AI 발화. 저장하지 않는다).
- (#94에서 뺌) `idea_delete` → `category_trash(category=생각, item_id, note)`. 그 생각에 응답한 AI 발화도 함께 휴지통으로 옮긴다.
- (#96에서 뺌) `idea_search` → `category_search(query, author=me|ai|all)`. all이면 me를 먼저, ai 글에는 응답한 글을 함께 보인다.

### 프로젝트 인자(#95, 옛 층 인자 #93, `magus/project_args.py`)
- 넣는 도구(category_put·idea_add_conversation·ref_import_bibliography·category_create)에 `project`(「내 서재」·프로젝트 id·제목, 앞부분이 하나만 맞아도).
  말하지 않았으면 프로젝트가 하나면 그것, 없으면 「내 서재」, 둘 이상이면 넣지 않고 묻게 하는 오류(프로젝트 목록).
  (#96) 넣을 책은 `book`(이름)으로 고른다: 이름이 같은 책이 여럿이면 그 프로젝트의 것 → 지도의 연결 노드가 가리키는 것 → 그래도 여럿이거나 없으면 책 이름과 컨텍스트 이름을 담은 오류(`category/books.py: find_book`).
- 찾는 도구(category_search·category_list)는 project가 없으면 모두, 있으면 그 프로젝트 + 연결 노드가 가리키는 같은 책. 같은 종류가 여러 프로젝트에 있으면 결과마다 프로젝트.
- 문헌 글(category_put source): 새 문헌만 프로젝트가 필요하다. 이미 있는 문헌은 제자리, project를 줬고 그 원고가 못 보는 곳에 있으면 「내 서재」로 옮기고 두 지도에 연결 노드. ref_import_bibliography·book_import의 참고문헌도 같다.
- 지도 일(도구 수를 늘리지 않음): `category_create(template=노드|연결 노드, node)`(연결 노드는 name에 원본 '프로젝트 · 노드'), `category_edit(node, new_name, color, link, unlink)`,
  책 옮기기 `category_edit(book, move_to=노드|'프로젝트 · 노드'|프로젝트)`·`undo_move`, `category_trash(node)`(가운데·책이 꽂힌 노드는 막음). 지도 보기는 `category_list`.
- book_import에 path 없이 title이면 원고 없는 프로젝트(원고는 나중에 같은 project_id로). book_outline 머리에 지도 두 줄(`지도(노드 N · 선 N): …`, `선: …`).
- 도구 목록 9,566 → 10,957(#93) → 10,904(#94) → 10,900(#95) → 8,416토큰(#96, 23개). 한도는 10,904.

### 책·글 (`magus/category/`, #92 카테고리 → #96 책·글·컨텍스트)
- **#96부터 기본 카테고리는 없다.** 모든 책이 같다(이름·색·컨텍스트·위치를 바꾸고, 문헌 글이 든 책만 휴지통 막음). 아래 #92 줄의 '기본 셋'·'생각·문체·문헌' 규칙은 #96 전 기록이다.
  - `category_list()` → 프로젝트마다 지도·노드·책(글 수, `[ ]`는 컨텍스트 이름), 자주 쓰는 컨텍스트 이름, 제목 기본값.
  - `category_create(name, template=빈 책|인물|사례|수치|용어|노드|연결 노드, color?, project?, node?, context?: [자주 쓰는 컨텍스트 이름 | 글])`.
  - `category_edit(book?|node?, new_name?, color?, context?([]이면 뗌), project?, move_to?, undo_move?, link?, unlink?)`.
  - `category_put(book, author, content?, title?, title_by?, untitled?, reason?, where?, parts?: [{text, reason, where}], source?(서지), checked?, file?, aliases?, fields?, tags?, chapters?, item_id?, project?)`
    = 글 넣기. source가 있으면 문헌 글(`melchior/refs.py: add_ref`, checked면 원문 확인 + 쓸 부분 하나 이상), 없으면 책의 글. 올린 문서가 든 책에는 넣지 않는다.
  - `category_search(query?, book?, project?, author=all|me|ai, full?, k=8, scrap_only?)` → 책으로 묶고 책마다 컨텍스트 머리. 글에 첨부가 있으면 `첨부 N개: 이름(종류, 크기)`만(#97, 내용은 읽지 않음).
    #99: 웹 찾기와 같은 `search.find_chunks`(앞부분 일치·구절 → 글자 포함), 첨부 파일 이름도 찾음(문헌 글은 여전히 쓸 부분·원문만), 결과에 ★스크랩,
    제목 없는 글은 `제목 「첫 첨부 이름」(첫 첨부의 파일 이름)`. scrap_only=true에 query가 없으면 스크랩 전체(최근 것부터). `category_edit(scrap, item_id)`로 스크랩 켜고 끄기. `category_trash(note, book?, item_id?, project?, node?)`(AI 답 글도 함께).
  - 응답 첫 줄은 그 책의 컨텍스트(`contexts.View.header`). 자주 쓰는 컨텍스트를 만들고 고치는 것은 웹(`/me/contexts`)만.
- (#92 기록) 기본 카테고리는 생각·문체·문헌이다(이름·삭제 불가, 책 색만 바꿈, 넣는 것은 각자의 도구). 그 옆에 저자가 만든 카테고리가 책장에 꽂힌다. 설계·고른 것: `docs/decisions/user-drawers.md`.
- `category_list()` → 기본 셋과 저자의 카테고리(이름·템플릿·칸·항목 수·책 색), 제목 기본값.
- `category_create(name, template=빈 카테고리|인물|사례|수치|용어, color?)` → 이름 규칙(12자, 예약어·중복 금지, 30개까지), 색은 기본 색 이름(18개) 또는 #RRGGBB.
- `category_edit(category, new_name?, color?)` → 기본 셋은 색만.
- `category_put(category, author: me|ai, content?, title?, title_by?, untitled?, fields?, tags?, chapters?, item_id?, project_id?)` → 넣기(item_id면 준 것만 고치기). 칸은 그 카테고리의 칸 이름만, 장은 지금 책에 있는 번호만. 제목 규칙은 idea_add와 같다.
  - **내용·제목·칸 중 하나만 있어도 저장한다**(모두 비었을 때만 거부, 빈 카테고리는 제목이나 내용). 목록에서 제목·내용이 없으면 채워진 칸(예: 장소: 엘알토)이 앞부분으로 보인다(2026-10-06 비밀 대화 시험).
  - **category=생각이면 거부하지 않고 생각에 저장한다**(idea_add와 같은 제목 기본값·title_by 규칙, 누가는 author를 따른다, 장·태그는 넣지 않음). 문체·문헌이면 저장하지 않고 "문체는 이 도구로 넣지 않는다. style_add 도구를 찾아 쓴다(…)"처럼 도구 이름을 담은 오류를 돌려준다. 도구를 그때그때 찾아 불러오는 클라이언트에서 Claude가 idea_add 대신 category_put을 부르고 "생각 도구가 연결돼 있지 않다"고 답한 일 때문이다. category_list 응답과 category_put 설명 앞부분에도 같은 한 줄이 있다.
- `category_search(query, category?, k=8, project?)`, `category_trash(note, category?, item_id?, project?, node?)`(항목 또는 저자 카테고리 통째. 생각·문체 항목도 여기서(#94), 문헌 항목과 기본 셋 통째는 못 옮김), `category_title_default(mode: ask|ai|none)`.
- 쓰기 도구 설명 첫 문장은 "저자가 …라고 분명히 말했을 때만 부른다"다. 되묻는 선택지는 생각·문체·문헌과 저자의 카테고리(원고 없음).

### 문체 — Balthasar (`magus/balthasar/`) — #96에서 도구를 뺐다(`balthasar/tools.py` 지움, `style.py`는 이전용)
- (#96 전 기록) `style_add(passage, reason, work?, tags)` → tags 스키마는 `{호흡, 시점, 열기, 장치: [], 어미, 톤}`이다. 여섯 키가 모두 필요하고(장치만 빈 목록 허용), 모르는 키는 거부한다. 태그는 호출자(Claude)가 추출해 넘기고, 서버는 검증만 한다. **임베딩 대상과 FTS 색인 대상 모두 reason + tags를 이은 문자열이지 passage가 아니다**(구절을 색인하면 문체가 아니라 주제가 검색된다. 테스트로 고정). 키워드 색인에는 work(출전)도 더한다("유홍준 그 문장", 사용자 결정 #24). 임베딩 대상에는 넣지 않는다.
  - `tags_by=ai|author`(기본 ai): 태그를 Claude가 뽑았는지 저자가 정했는지 남긴다(#89). 응답·style_search에 `(태그는 AI가 뽑음)`, 웹 `/styles`에 "AI가 뽑은 태그"로 보인다.
  - reason은 저자가 말한 이유만 쓴다. 말하지 않았으면 지어내지 않고 `(저자가 이유를 밝히지 않음)`으로 남긴다(설명에 적었다).
- (#96에서 뺌) `style_search` → `category_search`. 여섯 키 태그 강제도 없앴다(태그는 자유 목록, 무엇을 채울지는 컨텍스트가 말한다).
- (#94에서 뺌) `style_delete` → `category_trash(category=문체, item_id, note)`.
- 휴지통의 생각·문체는 검색·목록·웹 화면·reindex에서 빠진다. 되살리기는 운영자 CLI만 한다. #96부터 글은 `magus trash restore category-item <책 id>/<글 id>`(함께 옮긴 AI 답 글도), 노드는 `node <프로젝트>/<노드>`. 카테고리는 `magus trash restore category <id> [--name 새 이름]`, 항목은 `category-item <카테고리 id>/<항목 id>`(#92).

### 쓰기 도구 설명의 첫 문장(#87)

Claude는 도구를 고를 때마다 설명을 읽는다. instructions만으로는 보장되지 않아 설명 첫 문장에도 적었다.
- (#96) category_put: "글 넣기. 저자가 그 책에 넣으라고 분명히 말했을 때만 부른다. 넣을 책이 대화에서 분명하지 않으면 부르지 말고 책 이름과 컨텍스트 이름을 보여 주며 묻는다." 아래 둘은 #96 전 기록.
- (#96 전) idea_add·style_add·ref_add: "저자가 '생각'('문체', '문헌')에 넣으라고 분명히 말했을 때만 부른다. '저장해 줘'처럼 넣을 곳이 정해지지 않았으면 부르지 말고 생각·문체·문헌과 저자의 카테고리(category_list) 중 어디인지 먼저 묻는다(원고는 선택지에 넣지 않는다)."(#90·#92)
- category_put: "저자가 그 카테고리에 넣으라고 분명히 말했을 때만 부른다." + 위와 같은 되묻기. category_create·category_edit·category_trash·category_title_default도 "분명히 말했을 때만"으로 시작한다(#92).
- book_write_chapter: "저자가 'Magus 원고에 저장'하라고 분명히 말했을 때만 부른다."(규칙 4)
- category_trash(#94에서 idea_delete·style_delete를 합침): "저자가 그 항목(또는 저자가 만든 카테고리)을 지우라고 분명히 말했을 때만 부른다. 여러 개면 목록을 보여 주고 확인받는다."
- book_document: "저자가 원고에서 문서를 만들어 책장에 넣으라고 분명히 말했을 때만 부른다."
- 도구 설명·도구 응답·instructions에는 코어 이름(Casper·Melchior·Balthasar)과 옛 이름(영감·책 지도·미해결·이슈·새 판), #96부터 책 종류 이름(원고 책·모음 책·문서 책·카테고리)을 쓰지 않는다. '책장'은 #92로 용어집 이름이 됐다. 예외는 용어집 규칙(#96부터 6)의 "쓰지 않는다" 문장(`instructions.AVOID`) 하나다. `tests/test_author_terms.py`가 모든 도구를 한 번씩 불러 설명·입력 스키마·응답·instructions를 검사한다.

## 서버 instructions

6절의 규칙 문장은 `src/magus/instructions.py`의 `RULES`에 **원문 그대로** 들어 있다. 사용자 승인 없이 고치지 않는다.
- 예외: **규칙 4는 사용자 결정 #74(2026-10-06)로 바꿨다.** "장 수정안은 대화에서 제안하고, 저자가 Word 원고에 반영한다. book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓰고, 그 장만 저장하며 note에 무엇을 바꿨는지 쓴다. 결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다."
- 예외: **사용자 결정 #87(2026-10-06)로 머리말에서 '책장'을 빼고("이 서버는 사용자의 생각·문헌·문체와 원고를 관리한다."), 규칙 7 끝을 "…'책 지도'·'미해결'·'이슈'·'새 판'·'영감'·'책장'·'refs' 같은 말은 쓰지 않는다. 코어 이름(Casper·Melchior·Balthasar)이나 도구 이름을 저자에게 말하지 않는다."로 바꿨다.**
- 예외: **사용자 결정 #85(2026-10-06, 용어 통일)로 머리말의 '영감'을 '생각'으로 바꾸고 규칙 7~9를 더했다.** 7 저자에게 보이는 이름(용어집), 8 저자의 말 해석("전체 보여 줘" → book_outline, "전체 읽어 줘" → 한 장씩 안내, "수정본 올렸어" → files_list의 최신 원고를 new_edition으로), 9 넣을 곳을 말하지 않은 "저장해 줘"·"기록해 줘"·"등록해 줘"·"넣어 줘"에는 쓰기 도구를 바로 부르지 않고 생각·문체·문헌 중 어디인지 먼저 묻기. 원문은 `tests/test_instructions.py`의 SPEC.
- 예외: **2026-10-06 비밀 대화 시험(사용자 요청)으로 규칙 11을 더했다**: "어떤 도구가 이 대화에 없어 보이면 '연결돼 있지 않다'고 답하기 전에 도구 이름으로 찾아본다." 도구를 부르지 않는 규칙이라 규칙 7처럼 언제나 실린다.
- 예외: **사용자 결정 #92(2026-10-06 밤, 책장·카테고리)로 머리말에 '카테고리'를 넣고("이 서버는 사용자의 생각·문헌·문체·카테고리와 원고를 관리한다."), 규칙 7에 책장·카테고리를 더하고 쓰지 않는 이름에서 '책장'을 빼고, 규칙 9의 선택지에 저자의 카테고리를 더하고(category_list, 많으면 목록), 규칙 10(제목: 직접·지어 드림·비워 둠 중에서 묻고 '앞으로는'이면 category_title_default)을 더했다.**
- 예외: **사용자 결정 #93(2026-10-07, 층, 승인됨)로 규칙 7에 '층'을 더하고 규칙 12(층을 말하지 않았을 때 넣을 층·찾을 층)를 더했다.** 도구 이름을 부르지 않아 언제나 실린다.
- 예외: **사용자 결정 #94(2026-10-07 밤, 책 종류, 확인 대기)로 규칙 7의 책장·카테고리 설명을 책장·층·책(원고 책·모음 책·문서 책)으로 바꾸고 쓰지 않는 말에 '받은함'·'인용 체크리스트'를 더했다.**
  규칙 8의 '수정본 올렸어'는 먼저 book_outline의 수정본 줄을 본다(책장에서 올렸으면 이미 처리됨). 규칙 13(새): '…로 만들어 책장에 넣어 줘' → 점검 도구로 확인 뒤 book_document, 수치는 옮기지 않고 머리말만.
  전후 전문은 `docs/decisions/bookshelf-tool-texts.md`.
- 예외: **사용자 결정 #95(2026-10-08, 프로젝트·마인드맵, 확인 대기)로 규칙 7의 책장·층·책을 프로젝트·지도·노드·연결 노드·책장·책·게시판으로 바꾸고 쓰지 않는 말에 '층'·'공용'을 더했다.**
  규칙 8 끝에 "'지도 보여 줘'·'책장 보여 줘'는 category_list다", 규칙 12를 프로젝트 고르기(그 프로젝트의 책 → 연결 노드가 가리키는 책 → 묻기)로, 규칙 13의 '책장(이 층)'을 '책장(이 노드)'로.
  전후 전문은 `docs/decisions/project-map-texts.md` 2절.
- 예외: **사용자 요청 #96(2026-10-08, 종류를 없애고 컨텍스트로, 확인 대기)로 머리말을 "이 서버는 저자의 프로젝트(지도·노드·책·글)와 원고를 관리한다."로 바꾸고**,
  규칙 2(인용은 원문 확인 글의 쓸 부분만, category_search), 3(글의 author), 5(새, 사용자 문장 그대로: "글을 읽거나 넣을 때 그 노드·책의 컨텍스트를 따른다. 컨텍스트가 없으면 일반 메모로 다룬다. 컨텍스트는 저자가 적은 읽는 방법이다."),
  6(용어집: 책·글·컨텍스트·자주 쓰는 컨텍스트, 종류로 부르지 않음, 쓰지 않는 말에 원고 책·모음 책·문서 책·카테고리), 7·9·11·12(종류 이름 뺌), 8(넣을 곳: 대화에서 분명하면 그 책, 아니면 책 이름·컨텍스트 이름을 보여 주며 묻기)를 바꾸고,
  옛 5·6(style_search·style_add 태그)을 뺐다. 규칙은 12개. 전후 전문은 `docs/decisions/contexts-texts.md` 3절.
- 예외: **2026-10-08 밤 사용자 요청(#97 C)**: 마지막 규칙(12, 문서 만들기)을 "저자가 '…로 만들어 이 노드에 넣어 줘'처럼 올린 문서에서 읽기용 문서를 만들어 달라고 하면 바로 book_document를 부른다."로.
  점검 도구(book_questions·ref_check·book_issues)를 먼저 부르지 않는다(book_document가 서버에서 데이터를 만든다). 나머지 문장 그대로. 2,225토큰.
- 예외: **#96 답(2026-10-08 저녁, 승인)**: 머리말 "…와 올린 문서를 관리한다.", 규칙 1 "올린 문서 작업은 항상 book_outline로 시작하고, … 올린 문서 전체를 요구하지 않는다.",
  규칙 4 "올린 문서의 원본은 저자의 파일(Word 등)이다. 장 수정안은 대화에서 제안하고, 저자가 원본 파일에 반영한다. book_write_chapter는 저자가 Magus의 올린 문서에 저장하라고 명시했을 때만 쓰고, …",
  규칙 6에 '올린 문서'(새)와 '컨텍스트 … 책은 꽂힌 노드의 것을 먼저, 책의 것을 이어 읽는다', 쓰지 않는 말에 '올린 원고'. 규칙 7·8·12의 '원고' → '올린 문서'. 규칙 5는 그대로.
  전후 전문은 `docs/decisions/contexts-texts.md` 0절.
- 예외: **#98(2026-10-09, 사용자 지시 "규칙 7이 맞는지 확인하고 바꾸면 보고")로 규칙 7의 수정본 문장을 바꿨다**: "'수정본 올렸어'·'수정본 올려 줘'는 저자가 고친 문서(.docx·.pdf)를
  게시판 글에 첨부했거나 올린 파일에 두었다는 뜻이다. files_list에서 book_outline 수정본 줄의 마지막 업로드보다 나중에 올라온 문서를 찾아 이 프로젝트(book_outline 첫 줄의 id)의
  수정본으로 올린다(book_import, path는 files_list에 보이는 이름, new_edition=true)." 웹의 수정본 올리기 폼을 없앴기 때문이다(status.md 0-23절).
- 예외: **#101(2026-10-09, 사용자 요청)로 규칙 2 끝에 "쓸 부분을 저장한 뒤에는 원문 확인 표시도 할지 한 번 묻고, 저자가 그렇다고 하면 category_edit(checked=true)로 표시한다."를 더했다**(2,385 → 2,437토큰).
- 예외: **#100(2026-10-09, 사용자 요청 첨부 글자)로 규칙 2 끝에 "첨부에서 뽑은 글자는 찾고 읽는 데 쓰되, 인용은 여전히 원문 확인 글의 쓸 부분만 쓴다. 저자가 첨부의 어느 부분을 쓸 부분으로 저장하라고 하면 그 문헌 글에 넣는다(category_edit)."를 더했다**(2,305 → 2,385토큰).
- 예외: **#99(2026-10-09, 사용자 요청 스크랩)로 규칙 6 용어에 「스크랩(저자가 별표로 표시해 둔 글. 중요 표시)」, 규칙 7 끝에 "'스크랩 보여 줘'는 category_search(scrap_only=true)다."를 더했다**(2,261 → 2,305토큰).
- **instructions는 등록된 도구만 언급한다.** `build_instructions(등록된 도구 이름)`은 규칙 문장에 나오는 도구(`book_|ref_|idea_|style_|files_|category_` 이름)가 모두 등록된 규칙만 넣고, 번호는 다시 매긴다. 도구를 부르지 않는 규칙(#96 번호 5·6·10·11)은 언제나 실린다. 도구가 모두 등록되면 SPEC과 똑같아진다(`tests/test_instructions.py`).
- 새 도구를 추가하면 그 도구가 필요한 규칙이 자동으로 instructions에 들어간다. 따로 손댈 것은 없다.

## 작업 순서 (단계마다 pytest 통과 + Claude Desktop 확인 방법을 보고한다)

1. 뼈대: Store 인터페이스, SQLite 스키마, 설정, stdio 서버, book_outline(가짜 데이터) → Claude Desktop 연결 확인.
2. book_import: fixtures 원고로 장 분할·코멘트·참고문헌을 임포트하고 리포트를 출력한다. 분할 결과를 사람이 보고 고칠 수 있게 ch-NN.md 파일명과 제목 매핑을 출력한다.
3. book_read/write/decide/issue/export + 버전 저장.
4. ref_*(bibliography 임포트, add, search, check) + 게이트를 write에 연결.
5. idea_*(대화 분리는 fixtures의 md 3개로 테스트).
6. style_*.
7. 하이브리드 검색 정리, instructions 적용, README.

## 완료 기준 (fixtures로 검증)

- 원고 임포트: 장 35개(±2, 분할 오차는 리포트에 남김), 부 8개, 코멘트→이슈 80개 이상, refs 200건 이상(unverified).
- book_outline 응답이 3,000 토큰 이하다.
- ref_check(1장) 결과에 daeschler2006과 clack2012가 unverified 또는 unknown으로 잡힌다.
- ref_add로 그중 하나를 verified로 만들면, ref_check를 다시 실행했을 때 verified 목록으로 옮겨 간다.
- idea_add_conversation(대화_전체_기록.md): me 96건, ai 96건이고, 모든 ai 항목에 parent_id가 있다.
- book_write_chapter 뒤 versions/에 이전본이 있고, outline의 최근 변경에 반영된다.
- EMBEDDINGS=none에서 모든 도구가 동작한다.
- 모든 쿼리가 user_id로 필터된다(다른 user_id로 호출하면 결과가 비어 있다).

## P1: 원격 MCP 서비스 (2026-10-03 킥오프)

**목표**: 사용자와 아버지가 각자의 Claude(웹·Desktop·모바일)에서 커넥터 URL 하나로 Magus를 쓴다. 설치는 없다. 데이터는 사용자별로 격리되고 매일 백업된다.

**하지 않는 것**: 자체 OAuth 서버, 결제, 다중 조직, 공개 가입(허용 목록만). stdio 모드는 없애지 않는다(로컬 개발용).

**아키텍처**
- 전송: streamable-http, **stateless + JSON 응답**(`magus/transports.py: http_app`). 엔드포인트 `/mcp`, 상태 확인 `/healthz`(인증 없음). 서버 코어(build_server)는 그대로 쓴다.
- 인증: MCP용 OAuth를 지원하는 **관리형** 인증 서비스를 쓴다. **WorkOS AuthKit**으로 정했다(`docs/decisions/auth-provider.md`, 차선 Descope). 코드는 표준(JWKS·iss·aud)만 쓴다(`magus/auth.py`).
  - Magus는 리소스 서버만 한다: Protected Resource Metadata를 내고, 액세스 토큰(JWT 서명·만료·issuer·audience)을 검증하고, `sub` → user_id를 매핑한다.
  - 허용 목록(`ALLOWED_USERS`)에 없는 sub는 거부한다. 무효 토큰은 401(+ `resource_metadata`), 유효하지만 목록 밖은 403(`ForbiddenGate`).
  - 무효 토큰의 원인(iss 불일치·aud 불일치·만료·서명·kid·형식)은 `JwtVerifier.check`가 서버 로그에 남긴다. iss·aud·kid 같은 공개 값만 쓰고 토큰 값은 남기지 않는다.
  - WorkOS는 당분간 **Staging 환경**(`dapper-palace-57-staging.authkit.app`)으로 운영한다. Production은 공개 서비스로 바꿀 때 옮긴다(결정 #49, 2026-10-05). 허용 목록 순서: 운영자 본인 `=default`(개발용 PDF 임포트본, 6단계 시험)가 먼저이고, 아버지 `=father`(docx 원본 새 임포트)는 나중이다(docs/deploy.md 2-1절, docs/onboarding-father.md).
  - **토큰 aud는 `PUBLIC_URL/mcp` 하나만 받는다**(문자열, 또는 원소 하나인 목록). 다른 값이 섞이면 401이다. `AUTH_AUDIENCE`로 넓히지 않고, 다르면 서버가 시작하지 않는다. 자매 서비스 trip_ai와 WorkOS 환경을 공유하기 때문이다(결정 #79, `docs/decisions/shared-auth-audience.md`). `ALLOWED_USERS`는 서비스별로 따로다.
  - PRM의 `resource`는 커넥터 URL(`PUBLIC_URL/mcp`)과 정확히 같아야 한다(Claude 요구). Claude 등록 방식은 CIMD("Claude의 공개 신원 사용").
- 사용자: `current_user()`가 HTTP에서는 토큰의 sub로, stdio에서는 `USER_ID`로 user_id를 정한다. 두 모드를 가르는 분기는 `current_user()` 밖으로 새지 않는다.
- 파일
  - 사용자별 올린 파일(옛 받은함) `data/users/<user_id>/inbox/`. 내 정보의 '올린 파일'과 문헌 등록(논문 파일)으로 들어온다. 책장에서 올린 원고는 거치지 않는다(#94).
  - 경로 인자(book_import, ref_add, idea_add_conversation)는 받은함의 파일 이름을 받는다. 새 도구 `files_list()`로 받은함을 본다.
  - book_export는 exports/에 만들고, 로그인이 필요하고 만료가 있는 다운로드 URL을 돌려준다.
- 웹(`magus/web.py`): 같은 프로세스의 Starlette 라우트로 서버에서 그린 최소 HTML이다(디자인은 P1 범위가 아니다).
  - **메뉴는 '프로젝트' 하나(#94·#95).** 페이지: `/login`, `/shelf…`(아래), `/me`(내 정보)·`/me/files`(올린 파일: 업로드·목록·삭제), `/download/{token}`.
    옛 `/book`·`/issues`·`/checklist`·`/questions`는 가장 최근 원고 책의 탭으로(원고가 없으면 `/shelf`), `/inbox`는 `/me/files`로 넘긴다. `POST /book/export`(docx)는 그대로.
  - **프로젝트·지도(#95, `magus/webmap.py`·`webmap_assets.py`)**: 첫 화면 `/shelf` = 프로젝트 목록(이름·최근 수정·노드 수, 「내 서재」는 끝, '+ 프로젝트' = 원고 올리기 또는 제목만 `POST /shelf/projects`).
    프로젝트 화면 `/shelf/p/<프로젝트>?node=&book=&at=&view=map|list`(pushState): 지도(노드 = 링크, 선 = 노드 아래 SVG) + 패널(1200px 이상 오른쪽, 좁으면 아래, 768px 미만은 목록 먼저).
    노드를 누르면 패널에 그 노드의 정면 책장(`GET …/panel?node=` 조각), 책을 누르면 같은 패널 아래 게시판 자리(iframe)에 그 책 화면. 지도 바꾸기 `POST …/map`(action = move_node·add_node·
    add_link·rename·color·connect·disconnect·trash, 스크립트는 JSON, 폼은 되돌아가기). 책 옮기기 `POST /shelf/move`(to = 프로젝트[:노드])·`/shelf/undo`. 내려받기 `…/export.zip`·`/shelf/export.zip`.
    스크립트: 노드 끌기(놓으면 위치 저장, keepalive), 빈 곳 두 번 누르기·'+ 노드'(떠 있는 상자), 노드 오른쪽 ＋ 끌기·'선 잇기' 모드, 선 눌러 끊기, 휠·핀치·끌기·'가운데로'·＋/－,
    패널의 책을 노드로 끌어 옮기기(링크 끌기 dragstart는 막음). 스크립트 없이·키보드: 노드 링크(Tab·Enter), 목록 보기, 노드 설정 폼, 책 설정 '위치'.
    옛 주소 `/shelf?floor=`·`?at=`·`/shelf/floor/…`는 그 프로젝트 화면으로. 패널 안 요청은 머리 없이(`webshelf.EMBED`), 패널 안에서 프로젝트 화면이 열리면 바깥을 그 주소로.
    값은 web-style.md "지도". 3D 책장(`webfloors.py`)은 #95로 지웠다.
  - **책 종류(#94, `magus/webbooks.py`)**: 노드 책장의 점선 '책 추가' → `/shelf/add?project=&node=`(원고 올리기 `POST /shelf/manuscript`(진행 막대, XHR) · 모음 책 만들기 `/shelf/new` · 문서 책 안내).
    원고 책 `/shelf/book/<작업물>?tab=chapters|issues|cites|editions`(인용 상태 안에 `view=questions`, 수정본 이력 안에 `POST …/edition`과 리포트 `report=N`).
    문서 책 `/shelf/doc/<id>`(`?v=N` 이력, `POST …/redo` 다시 만들기, `…/docx`, 인쇄 CSS로 PDF). 책 설정 `/shelf/edit/ms.<id>`·`doc.<id>`(이름·색·위치), 휴지통 `/shelf/trash/ms.…`·`doc.…`.
    원고 책은 옮기지 않는다(가운데 노드 자체). 원고 책 휴지통은 원고만 옮기고 같은 id의 원고 없는 프로젝트를 남긴다. (#97에서 문헌 등록 폼 `POST /shelf/refs/register`를 없앴다.)
  - **게시판 페이지(#98, 2026-10-09, `magus/webboard.py`)**: 책을 누르면 별도 페이지 `/shelf/<책>`(위치 표시 프로젝트 › 프로젝트 이름 › 노드 › 책, 한 줄 = 제목·📎/그림 미리보기·날짜,
    최신 글 위 20개씩, 오른쪽 위 '글쓰기'), 글쓰기 `/shelf/write/<책>`(끌어다 놓기·고르기·`capture` 사진 찍기), 글 보기 `/shelf/<책>/<글>`(본문·사진·파일 목록·🗑 화면 안 확인 창 →
    `POST …/trash`). 지도 옆 패널의 게시판 자리(iframe)·EMBED·주소창 넘기기는 없앴고 옛 `?at=`·`/shelf/add`는 그 페이지로 넘긴다. 책장에는 책 목록과 '새 책' 하나,
    웹의 수정본 올리기·글 고치기·원문 확인 체크는 없다. 프로젝트 휴지통에 노드와 글(되살리기). 도움말 대화는 브라우저 localStorage(사용자별 열쇠, 20턴·24시간·새 대화·로그아웃).
    아래 #94~#96 설명 중 '책 추가'·'수정본 이력 안 POST …/edition'·'게시판(iframe)'은 #98 전 기록이다.
  - **컨텍스트(#96, `magus/webcontexts.py`)**: '+ 노드'·노드 설정·새 책·책 설정(올린 문서·만든 문서 포함)에 컨텍스트 칸(자주 쓰는 컨텍스트 단추: 누르면 붙고 다시 누르면 떨어짐,
    붙인 사본은 그 자리에서 고침, 줄마다 '자주 쓰는 컨텍스트로 등록'·'떼기', 직접 적기). 노드 패널·게시판(노드 「…」 → 이 책)·올린 문서·만든 문서 머리에 컨텍스트 이름(누르면 전문).
    책등 위 띠 = 컨텍스트 이름(첫 이름 + 외 N). 내 정보 → 자주 쓰는 컨텍스트 `/me/contexts`(고치기·지우기·새로 더하기). 책 추가 = 새 책 / 문서 올리기 / 올린 문서에서 만든 문서.
    '원고 책' → '올린 문서'(#96 답 s), '문서 책' → '올린 문서에서 만든 문서', '항목' → '글', 일반 기능의 '원고' → '올린 문서'(본문·원본 파일). 게시판은 하나(글 뒤에 문헌 글, 거르기 나·AI).
  - **#97(오캄의 면도날)**: 화면에는 제목·단추·입력칸 이름·날짜·개수만(설명은 `docs/help`와 '?' 도움말 `POST /help/ask`). 새 글·고치기 = 제목·본문·첨부(`/shelf/<책>/<글>/files/<id>`, 본인 것만),
    문헌 글에 '원문 확인' 체크(`POST /shelf/<책>/<key>/check`). 원문 확인 거르기·넣기 폼은 없다(쓸 부분은 대화로). 화면마다 `<body data-screen>`(도움말에 보낼 정해 둔 화면 이름).
    옛 주소 `/shelf/ideas…`·`ideas.<프로젝트>`는 이전으로 생긴 책으로 넘긴다. 값은 web-style.md "컨텍스트".
  - (#95로 걷어 냄) 한 화면 3D 책장(`/shelf?floor=&book=&at=`)·층 확대·3D 장(#93, 2026-10-07~08). 기록은 web-style.md "책장 3D", status.md 0-16·0-17절.
  - **책장**(`magus/webshelf.py`, #92·#95): 노드를 열면 보이는 양장본 책장(정면 2D, 한 줄 여섯 권, 책등 세로쓰기·위 띠·아래 항목 수·두께는 항목 수 단계, 점선 "책 추가"). 책을 누르면 게시판형 목록 `/shelf/{ideas|styles|refs|카테고리 id}`(한 줄 = 제목·작성 시각·보조 정보, 누르면 펼침, 100개씩, 기존 거르기 유지), 항목 고유 주소 `/shelf/<…>/<항목 id>`(펼친 채 열림). 검색 `?q=`(두 글자 이상 FTS, 한 글자는 그대로 포함, `<mark>`), `/shelf?q=`는 카테고리별로 묶는다. 예전 `/ideas`·`/refs`·`/styles`는 넘긴다.
    - 문헌 책등 아래는 "확인 n · 전체 m" 두 줄(낭독기 "문헌, 확인 n편, 전체 m편"), 두께는 전체 수 기준. 문헌 목록 머리줄도 "문헌 확인 n편 · 전체 m편(미확인 k편)". 원고 참고문헌에서 들여온 미확인 항목까지 세어 '원문을 읽고 등록한 책'으로 오해하지 않게.
    - 생각과 저자의 카테고리 항목은 펼친 곳의 "고치기 · 휴지통으로"로 웹에서 고치고 옮긴다(`/shelf/<…>/<항목 id>/edit`·`/trash`, 자기 책장만, CSRF, 휴지통은 확인 화면 한 번). AI가 쓴 항목을 고치면 "저자가 고침(시각)"이 남는다.
    - 만들기 `/shelf/new`, 이름·색 `/shelf/edit/<…>`(기본 셋은 색만, 색 격자 18 + 내 색 12 + 색 선택기·#RRGGBB·R·G·B), 휴지통 `/shelf/trash/<id>`(확인 화면), 바로 적기 `POST /shelf/write/<ideas|카테고리 id>`(누가 = 저자). 문체·문헌은 대화로 넣는다. 책장 전용 색은 web-style.md "책장 전용".
  - **화면 스타일**(2026-10-06): `web.py`의 `STYLE` 상수 한 곳. 토큰과 참고 문서에서 바꾼 점은 `docs/decisions/web-style.md`(참고 문서는 외부 디자인 분석 문서, `private/design/`, 리포 밖). 시스템 한글 글꼴, 본문 16px·줄간격 1.6, 굵기 400/600, 그라데이션 없음, 흰 상단 바. 화면 문구는 사용자 결정으로만 바꾼다(#85 용어집).
    - 대비 AA: ink-mute는 흰 바탕에서만, 태그 바탕은 #b9b9f9 40%, ruby는 오류 왼쪽 테두리에만(글자로는 4.29:1). 입력칸 테두리는 ink-mute(4.75:1, 사용자 결정 #86).
    - 채운 버튼은 화면마다 하나(책 추가의 원고 '올리기', 수정본 이력의 '수정본 올리기', 올린 파일의 '올리기'). 원고는 파일을 골라 '올리기'(진행 막대).
    - (#94 전) `/book` 원고 올리기의 '새 책으로 가져오기'·'바꾸기'는 없어졌다. 새 원고는 '+ 프로젝트'나 원고 없는 프로젝트 가운데 노드의 '책 추가', 같은 책은 수정본 이력, 바꾸기는 원고 책 휴지통 뒤 다시 올리기.
    - 원고 책 머리의 장 수는 outline과 같은 표기다(`35장 + 서장·…`).
  - 로그인
    - 원격: 인증 서버에 OAuth 인가 코드 + PKCE(S256) + `resource=PUBLIC_URL/mcp`로 로그인한다. 토큰은 MCP와 같은 JwtVerifier로 검증한다.
    - 실패 화면은 둘로 나뉜다. 토큰 무효는 401("로그인 토큰을 받아들이지 못했습니다", 원인은 서버 로그)이다. 허용 목록 밖은 403("허용 목록에 없습니다")이고, **본인의 사용자 id를 화면에 보여 준다**(운영자가 목록에 넣을 값).
    - 로컬(인증 없는 HTTP, 루프백 전용): `USER_ID`로 바로 로그인한다.
  - **상단 바 이름**: 표시 이름, 없으면 가입 메일, 없으면 내부 이름(user id). 메일은 웹 로그인 콜백에서 ① 인증 서버 userinfo(WorkOS `POST /oauth2/userinfo`, Bearer 액세스 토큰, scope `openid profile email`. **주소는 OIDC 디스커버리 `/.well-known/openid-configuration`에서 찾는다** — WorkOS의 `oauth-authorization-server` 메타데이터에는 userinfo_endpoint가 없어 처음 배포에서 메일을 못 받았다) ② 실패하면 로그인 응답의 `id_token`(서명·iss·aud=웹 클라이언트 id·exp 검증, WorkOS 문서: email claim)으로 받는다. 어느 쪽이든 sub가 검증한 액세스 토큰의 sub와 같을 때만 `profile.json`에 적는다. 로그는 `email=yes via=userinfo|id_token` 또는 `email=no (이유 코드)`만. 이름을 누르면 `/me`(내 정보: 표시 이름 바꾸기, 40자, CSRF, 비우면 메일로. 메일은 보이기만). 메일·표시 이름은 로그에 남기지 않는다(받았는지 yes/no만, #52).
  - 세션은 HMAC 서명 쿠키(HttpOnly, SameSite=Lax, https면 Secure, 12시간)다. 모든 POST는 CSRF 토큰을 확인한다(`magus/signing.py`).
  - 내려받기: book_export(원격·HTTP)는 서명·만료(24시간) 링크를 돌려준다. 링크만으로는 받을 수 없고, 같은 사용자로 로그인해 있어야 한다.
- 저장: 파일 + SQLite를 유지한다(Store 인터페이스 뒤. Postgres는 P2).
- 호스팅: **Vultr 서울 VPS($5) + Docker Compose + Caddy(자동 HTTPS)**(`docs/decisions/hosting.md`). 서버리스는 쓰지 않는다.
  - 이미지: `Dockerfile`(python:3.12-slim, uv, 비root uid 10001, /data 볼륨, healthz 헬스체크). 구성: `deploy/compose.yaml`(magus·caddy·backup·restore).
  - **서버 되돌리기 기준 커밋은 status.md에 기록된 값을 따른다**(`HEAD~1`을 쓰지 않는다). 배포할 때마다 반영 전 커밋을 status.md와 `docs/deploy.md` 반영 기록에 적는다.
- 백업: 매일 04:00 restic → Cloudflare R2(`deploy/backup.sh`). `index.sqlite`는 빼고(재생성), `forget --keep-daily 30 --keep-monthly 12 --prune`(일별 30 + 월별 12), `check --read-data-subset=1/30`. R2 버킷에 수명 주기 규칙은 걸지 않는다.
  - 복구: `docs/deploy.md` 5절. 정기 시험은 `deploy/restore-test.sh <사용자…>`(복구본 reindex 뒤 outline 비교). 로컬 훈련 결과와 기록 표도 그 문서에 있다.
- 알림: `magus/alerts.py`(텔레그램 `ALERT_TELEGRAM_*` 또는 웹훅 `ALERT_WEBHOOK_URL`). logsafe의 ERROR를 받아 백그라운드로 보낸다. 백업 누락은 healthchecks.io(`HEALTHCHECK_URL`, magus-backup)가, 서버·HTTPS 정지는 `deploy/alive.sh`(호스트 cron 5분, `HEALTHCHECK_ALIVE_URL`, magus-alive)가 알린다. 시험은 `magus alert-test`.
- **로그**: 도구 이름, user_id, 소요 시간, 결과만 남긴다(`magus/audit.py`). 본문·발췌·원고 내용은 절대 남기지 않는다.
  - SDK의 도구 실패 메시지와 예외 traceback은 `magus/logsafe.py`가 핸들러에서 거른다. 예외는 종류·위치만 남긴다.
  - ERROR는 알림 콜백으로 보낸다(10분에 한 번).
  - 테스트로 고정한다: `tests/test_http.py`, `tests/test_logsafe.py`.
- 한도: 사용자별 저장 용량, 업로드 파일 크기, 요청 크기에 상한을 둔다. 넘으면 명확한 오류를 낸다.
- 비밀: API 키·시크릿은 환경변수로만 받는다. 저장소에는 `.env.example`만 둔다.
- 안전장치: 인증이 꺼진 HTTP는 루프백(127.0.0.1)에만 열린다(`magus serve --transport http --host 0.0.0.0`은 거부).

**작업 순서**(단계마다 테스트·status.md·커밋·태그 `p1-stepN`·push)
1. HTTP 전송, 인증 없이 로컬 실행 → MCP Inspector로 도구 호출 확인.
2. 인증 서비스 연동: 토큰 검증, sub→user_id, 허용 목록. 잘못된 토큰·만료·허용 목록 밖 거부 테스트.
3. 받은함 + files_list + 경로 인자 전환. 로컬 경로를 받던 테스트를 받은함 기준으로 바꾼다.
4. 웹 페이지 4개. 업로드 → 임포트 → 체크리스트까지 브라우저로 한 바퀴 돈다.
5. 배포 + 도메인 + HTTPS + 백업 + 복구 테스트 + 알림.
6. Claude.ai 커넥터 등록 → 웹·모바일에서 book_outline, idea_add, ref_search를 실행한다. `docs/connect-claude.md`(사용자용·아버지용).
7. 아버지 온보딩 체크리스트: 커넥터 등록, docx 업로드·임포트, 첫 세션 대본(전체 → 제12장 인용 점검 → 논문 1편 등록).

**완료 기준**
- 사용자 계정으로 웹·모바일 Claude에서 모든 도구가 동작한다.
- 다른 계정의 토큰으로는 그 사용자 데이터만 보인다(격리 테스트).
- 업로드한 docx가 임포트되어 35장 + 서장·부 들어가며 2·맺음·부록 1~3, 8부, 코멘트 129(작성자 AI 129), refs 337(고유 미확인 문헌 335편)이 나온다. (#75, 2026-10-06 최신본 기준. 처음 기준 "35장·8부·코멘트 86·refs 297"은 10/02 PDF 판 수치였다)
- 백업에서 복구한 인스턴스가 같은 outline을 돌려준다.
- 로그에 원고 본문이 한 글자도 없다(테스트로 고정).
- stdio 모드 테스트가 여전히 전부 통과한다.

## 개발 명령

```
uv sync                                   # 의존성 (Desktop이 magus.exe를 실행 중이면 실패 → uv pip install)
.venv/Scripts/python -m pytest -q         # 테스트
magus serve                               # stdio 서버 (Claude Desktop이 띄움)
magus serve --transport http [--port 8000] # streamable-http(stateless) http://127.0.0.1:8000/mcp, 인증 전에는 루프백만
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http --method tools/list   # MCP Inspector(CLI)
magus import <docx|pdf> --project-id <id> [--title …] [--subtitle …] [--replace] [--synthetic]
magus import <docx|pdf> --project-id <id> --new-edition [--force]   # 같은 책의 수정본(#76)
magus conversation <md> --book <책> [--origin …]   # 대화 기록 → 그 책의 글(#96)
magus synth <폴더>                        # 합성 fixture 만들기
magus seed-demo                           # 데모 프로젝트 + 책장 표본
magus reindex                             # 파일 → index.sqlite 재생성 + 파생값 재계산
magus cite-report --project-id book       # 책 전체 인용 집계(확인 순서)
magus author-report --project-id book --out private/reports/<날짜>-인용-점검.md   # 저자용 보고서(md + docx)
magus terms --project-id book [--add …] [--remove …]                         # 비인용 용어 보기·고치기
magus trash list | put category|category-item|node <id> --note … | restore category|category-item|node <id> [--name …]   # 휴지통(운영자, USER_ID 사용자, #88·#92·#96)
magus alias <key> <표기>                                                      # 저자가 확정한 표기를 aliases에(예: keynes1930b "케인스(1930)")
magus maps plan|apply|revert [--user …|--all-users] [--backup 폴더]            # 프로젝트·지도 + 책·컨텍스트 이전(#95·#96, 층 이전 포함, 옛 이름 floors): 미리보기 / 백업 뒤 실행·전후 비교 / 옛 코드용 되돌리기. 새 serve는 옛 형식 사용자가 있으면 시작하지 않는다
magus inbox [--add 파일…] [--remove 이름…]                                    # 받은함(로컬 개발용, 원격은 웹 업로드)
magus outline [--project-id …]                                               # book_outline과 같은 출력(USER_ID). 복구 확인용
magus alert-test                                                             # 운영자 알림 채널 시험
docker compose -f deploy/compose.yaml …                                      # 운영(docs/deploy.md)
.venv/Scripts/python -m ruff check --select F,B src tests                    # 린트(pyflakes·bugbear)
```

## fixtures

`fixtures/`에는 원고 docx 1개(파일명에 "닿으려는_종")와 대화 기록 md 3개(그중 하나는 `대화_전체_기록.md`)를 둔다. 실제 원고이므로 리포에 커밋하지 않는다(.gitignore). 읽기만 한다.
- 실제 내용: 원고 `261002-닿으려는_종_전면개정_그림추가.pdf`(PDF, 297쪽, docx 없음), `대화_전체_기록.md`, `대화기록_닿으려는종.md`, `도시_유전자_민주주의_대화.md`, `사피엔스_총균쇠_대화.md`. 원본은 사용자의 Downloads에 있고, fixtures는 사본이다.
- 최신본 docx(2026-10-06 받음): `261005-인류가_선택한_진화_시대가_선택한_도시_원고.docx`. 책 제목이 바뀌었고, 코멘트 129건(작성자 모두 Claude), 표 37, 그림 10이다.
  - 로컬 `father-trial` 사용자의 `book`에 시험 임포트해 두었다(지우지 않음). 서버와 default에는 넣지 않았다.
  - 비교 결과는 `data/realdata/2026-10-06-father-trial-*.md`에 있다.
- 실데이터는 default 사용자의 `book` 프로젝트다(10/02 PDF 판). 리포트 사본은 `data/realdata/`에 있다.
- 합성 fixture는 `tests/fixtures/synthetic/`에 **커밋해 둔다**(사용자 결정 #11: 비밀이 아니고 재현성이 더 중요하다). `magus synth tests/fixtures/synthetic`로 다시 만든다(`src/magus/synthetic.py`). 실데이터(루트 `fixtures/`, gitignore)와는 계속 분리한다. 합성 PDF는 실원고 레이아웃을 흉내 낸다. 합성으로 돌린 리포트에는 "합성 fixture"라고 표시한다. 합성 데이터를 임포트할 때는 `USER_ID=synthetic`을 쓴다.

## 문서화 규약

### status.md (프로젝트 루트)

세션이 초기화돼도 이 파일 하나만 읽으면 바로 이어서 작업할 수 있어야 한다. 구성 순서는 바꾸지 않는다.

1. **지금 바로 할 일**: 다음 행동 한두 줄. 사람의 확인을 기다리는 중이면 "대기: 무엇을, 누가" 형식으로 쓴다.
2. **현재 단계**: 작업 순서(1~7단계) 중 어디인지와 상태(완료/진행/대기).
3. **단계별 체크리스트**: 1~7단계 각각 [x]/[ ], 완료일, 산출물 파일 경로.
4. **검토 대기 결정**: 사용자가 아직 확인하지 않은 것.
5. **환경 메모**: uv 경로, MCP SDK 버전, pandoc 대안, Desktop 설정 파일 경로, 실행·테스트 명령을 그대로 적는다.
6. **마지막 세션 요약**: 날짜, 한 일, 남긴 것.
7. **알려진 문제**: 미해결 버그와 우회 중인 것.

갱신 시점: 단계를 완료했을 때, 사용자 확인을 기다리며 멈출 때, 세션을 끝낼 때. 이때는 반드시 갱신한다.

### docs/ 구조

```
docs/
├── daily/YYYY-MM-DD.md      # 일지. 날짜는 로컬(KST) 기준
├── decisions/<name>.md      # 기술 결정 기록
├── troubleshooting/<name>.md# 트러블슈팅 기록
└── par-materials.md         # 이력서 소재 모음

private/reports/YYYY-MM-DD-<주제>.md # 저자에게 보내는 보고서(같은 이름의 docx 포함). 생성기로 만들고 손으로 고치지 않는다
                                    # 실원고 파생 자료라 리포에 넣지 않는다(.gitignore의 /private/, 2026-10-05 이력에서도 뺐다)
```

파일명은 kebab-case 영문으로 짓는다(예: `docs/decisions/store-interface.md`).

### 문서 형식

- **PAR**: Problem(상황·제약) / Action(선택한 것, 비교한 대안, 그렇게 고른 이유) / Result(결과, 가능하면 수치, 검증 방법).
- **일지(daily)**: 날짜 / 오늘 한 일 / 내린 결정(decisions 링크) / 막힌 것과 해결(troubleshooting 링크) / 내일 할 일 / 이력서 소재 후보.
- **기술 결정(decisions)**: PAR 구조로 쓰고, 맨 아래에 "대안을 버린 이유"를 한 줄로 적는다.
- **트러블슈팅**: 문제상황 / 시도한 것들 / 최종 해결법 / 이력서 소재 한 줄.
- **par-materials.md**: 항목마다 날짜 / P / A / R / 근거 문서 링크 / 이력서용 한 문장을 적는다. 맨 위에 "사용법" 2줄을 둔다.
- **커밋**: 컨벤셔널 커밋으로 쓰고, body 첫 줄에 "왜 이 결정을 했는지"를 한 줄로 적는다. 단계를 완료할 때마다 커밋한다.
- **브랜치·태그**
  - P0는 `master`에 바로 커밋한다. 단계를 완료하면 태그를 단다(`step1`, `step2`, …).
  - 파서 실험처럼 되돌릴 가능성이 큰 작업만 브랜치를 쓴다. 끝나면 squash merge한다.
  - **동시 세션**: 같은 리포에서 Claude Code 세션을 둘 이상 쓸 때는 각자 별도 git worktree에서 작업한다(예: `git worktree add .worktrees/<이름> <브랜치>`, `/.worktrees/`는 `.git/info/exclude`에 넣는다).
    - 메인 작업 트리에서 `git switch`·`checkout`·`reset`을 하지 않는다. 다른 세션의 작업 트리가 바뀐다(2026-10-06, 약 1분 동안 다른 세션의 트리가 바뀌었다).
    - worktree에서 테스트할 때는 메인 `.venv`의 python에 `PYTHONPATH=<worktree>/src`를 준다(편집 설치는 메인 `src`를 가리킨다).
    - master에 들일 때는 worktree에 병합 브랜치를 만들어 테스트하고, 메인 트리를 쓰는 세션에 병합을 부탁한다.
- **원격 저장소**: `origin` = https://github.com/sml122900/Magus (**Private**, 2026-10-05부터)
  - 인증은 Git Credential Manager가 한다. 토큰을 명령이나 파일에 적지 않는다.
  - **단계 태그를 찍으면 push까지 한다**: `git push origin master --tags`. 그다음 `git ls-remote --tags origin`으로 확인한다.
  - force push는 하지 않는다. 2026-10-05에 filter-repo로 이력을 정리한 뒤 처음 올린 것이 기준이다.
  - 실원고와 그 파생 자료(`data/`, `/fixtures/`, `/private/`)는 올리지 않는다. 처음 올리기 전에 확인한 방법: 이력 경로 검사(`git -c core.quotepath=false`), 실제 파일 해시 대조, 비밀 패턴·실제 비밀값 검색.

### 작업 명령어

사용자가 아래 문장을 그대로 입력하면, 위의 문서 형식에 맞춰 작성한다.

#### 일지 생성
"오늘 작업 내용으로 docs/daily/[날짜].md 만들어줘"

#### 기술 결정 문서
"[기술명] 선택 이유를 docs/decisions/[기술명].md로 PAR 구조로 만들어줘"

#### 트러블슈팅 문서
"방금 해결한 [문제]를 docs/troubleshooting/[문제명].md로 저장해줘.
문제상황 / 시도한 것들 / 최종 해결법 / 이력서 소재 한 줄 포함해서"

#### PAR 소재 추출
"오늘 작업에서 이력서에 쓸 수 있는 PAR 소재 뽑아서 par-materials.md에 기록해줘"

#### 커밋 메시지
"이 변경사항으로 컨벤셔널 커밋 메시지 써줘. 왜 이 결정을 했는지 body에 한 줄 추가해줘"

#### 세션 마무리
"오늘 작업 요약하고 CLAUDE.md 진행상황 섹션 업데이트할 내용 알려줘"

세션 마무리 명령을 받으면 요약과 CLAUDE.md 진행상황 갱신안을 보여 주고, status.md는 그 자리에서 바로 갱신한다.
