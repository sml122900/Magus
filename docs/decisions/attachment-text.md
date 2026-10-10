# 첨부 글자 뽑기·대화 검색 범위·예약어 '스크랩'(2026-10-09, 사용자 요청 #100)

## Problem
- 게시판 글에 붙인 문서(docx·pdf 등)를 Claude가 찾지도 읽지도 못했다. 대화에서는 이름·종류·크기만 보였다.
- 대화의 category_search는 문헌 글을 쓸 부분·원문으로만 찾아, 웹에서 찾히는 문헌(저자·연도·key·첨부 이름)이 대화에서는 안 찾혔다(#99-h).
- 「스크랩」이라는 책이 생기면 "스크랩 보여 줘"(category_search scrap_only)와 헷갈린다(#99-m).
- 제약: 새 도구 없음(23개), 서버 메모리 1GB, 원본은 읽기만, 옛 코드가 읽어도 깨지지 않게, 로그에 파일 이름·내용 없음.

## Action
- **뽑기**(`magus.extract`): docx는 zip 안 word/document.xml을 lxml iterparse로 문단마다 읽고 버린다. pdf는 pymupdf로 한 쪽씩. txt·md는 1MB씩(UTF-8, 아니면 cp949).
  새 라이브러리를 넣지 않았다(pymupdf·lxml은 원고 읽기에 이미 쓴다). 30만 자 상한(truncated), 글자가 안 나오면 empty, 깨진 파일 failed.
  시간은 쪽·문단·덩어리마다 살펴 20초를 넘으면 later(처음 열 때 다시). 웹 저장 한 번에 20초 합계.
- **저장**: 첨부 폴더 안 `.text/<이름>.txt` + `.text/status.json`. 썸네일(.thumb/)과 같은 방식이라 첨부 목록은 그대로(파일만 센다)이고
  첨부 폴더째 휴지통을 오간다. 배포 때 `magus extract --all-users`로 이미 올라간 첨부를 한 번에.
- **찾기**: 색인 v23 — 레인 attach_text, chunks.part(첨부 id). 웹·대화 같은 `find_chunks`, 첨부 글자는 제목·본문·파일 이름 다음. 임베딩하지 않는다.
  웹은 "📎 이름 · …앞뒤 100자…", 대화는 맞은 첨부·쪽 번호·앞뒤 100자와 읽는 법.
- **읽기**: 대화는 category_search(attachment='첨부:<id>', page=N)로 3,000자씩. 웹은 글 보기의 '글자 보기'(뽑은 글자 그대로).
  쓸 부분으로 저장은 category_edit(parts, item_id=문헌 key) — instructions 규칙 2 새 문장이 가리키는 도구라 인자를 더했다(passages.json만 고침).
- **대화 검색 범위**: category_search에 ref_bib 레인(서지·key·한글 표기·첨부 이름). 원문 확인 전 문헌은 '미확인(원문 확인 전 — 인용하지 않는다)'.
- **'스크랩' 예약**: RESERVED_SHOWN에 더함. 이름 검사는 새 책·이름 바꾸기 때만이라 이미 있는 「스크랩」 책은 그대로.
- 비교한 대안
  - 읽기 전용 새 도구(attachment_read): 도구·설명이 늘고 커넥터가 길어진다. 찾기 도구에 attachment·page 두 인자.
  - files_list에 읽기 붙이기: files_list는 올린 파일 목록이 일이다. 찾기 결과에서 바로 이어 읽는 쪽이 흐름이 짧다.
  - 별도 프로세스로 시간 제한: 프로세스마다 pymupdf를 다시 올려 메모리가 든다. 쪽마다 살피는 방식으로 충분하다(한 쪽이 아주 오래 걸리는 PDF만 예외).
  - pypdf 추가: 이미 있는 pymupdf가 쪽 단위로 가볍게 읽는다. 의존성을 늘리지 않았다.

## Result
- 시험 410 → 419 통과(뽑기 종류·스캔·30만 자·시간·찾기·쪽 읽기·격리·휴지통 왕복·명령·로그), 대화 검색 범위 10, 예약어 2.
- 시험본(default·father-trial 사본): 수치 전후 같음(299·297·0·86 / 337·335·1·129·E1). default 글 하나에 시험 첨부 5개 →
  `magus extract`: 대상 4 · 뽑음 3 · 글자 없음 1 · 형식 아님 1. 원본 해시 그대로, 새 파일은 .text/뿐. 옛 코드(p1-edit-scrap)로 읽어도 첨부 목록·수치 그대로.
- 도구 23개, 목록 8,787 → 9,207토큰, instructions 2,305 → 2,385토큰(커넥터 재연결).

대안을 버린 이유: 새 도구와 새 의존성·별도 프로세스는 늘리는 것만 많고, 찾기 도구의 두 인자와 쪽마다 살피는 시간 제한으로 충분하다.

## 형식 늘림(2026-10-11, 상태 VERSION 2)

- **P**: 첨부로 받는 형식(hwp·hwpx·pptx·xlsx·odt·rtf·csv) 중 글자를 뽑는 것은 docx·pdf·txt·md뿐이었다. 아버지 원고처럼 한글(hwp)로 쓴 문서는 찾지도 읽지도 못했다.
- **A**: hwp·hwpx·pptx·xlsx·odt·rtf·csv·html·htm을 뽑는다. 새 의존성은 olefile(BSD) 하나. pyhwp 등 GPL·AGPL 계열은 쓰지 않았다.
  - hwp: olefile로 `BodyText/Section{N}`(번호 순)을 열어 레코드(머리 32비트, 크기 0xFFF면 다음 4바이트)를 흘려 읽고 `HWPTAG_PARA_TEXT`(67)만 UTF-16LE로 읽는다.
    한 글자짜리 제어 문자(0·10·13·24~31)는 2바이트, 나머지 컨트롤(1~9·11·12·14~23)은 16바이트를 건너뛴다(탭은 탭). 압축 구역은 raw deflate를 1MB씩 풀고
    zipguard와 같은 규칙(1MB를 넘으면 압축률 100:1, 파일 전체 200MB)에서 멈춘다. OLE 스트림 하나는 50MB까지.
    FileHeader 속성의 암호·배포용·DRM 비트나 ViewText가 있으면 status=failed + reason=hwp_locked, 한글 97 이전(HWP 3.x)은 reason=hwp_old → 화면·대화에 '읽을 수 없는 hwp'.
  - hwpx(Contents/section*.xml 번호 순, hp:t)·pptx(presentation.xml의 슬라이드 차례, '## 슬라이드 N', a:t)·xlsx(workbook.xml의 시트 차례, '## 시트 이름', 행마다 한 줄·칸은 탭,
    공유 문자열·인라인·숫자는 적힌 그대로, 시트마다 2,000행)·odt(content.xml의 text:p·text:h, 변경 추적의 지운 글자·메모는 뺌): docx처럼 zipguard를 먼저 거치고,
    lxml target 파서에 64KB씩 흘려 넣는다(트리를 만들지 않는다. DTD가 든 XML은 받지 않는다).
  - rtf(\ansicpg의 코드 페이지로 \'hh, \uN과 \ucN, 글꼴·색·스타일·정보·그림·머리말 묶음과 {\*…}는 건너뜀), csv(txt와 같다), html(stdlib html.parser, script·style 버림,
    블록은 줄바꿈·표 칸은 탭, <meta charset>을 따르고 없으면 UTF-8 → cp949). html·htm은 이번에 첨부로 받기 시작했다(내려받기만: application/octet-stream).
  - 옛 Office 바이너리(doc·ppt·xls)는 뽑지 않고 글 보기 파일 목록·대화의 첨부 줄·첨부 읽기에 '글자를 뽑지 않는 형식'으로 보인다.
  - 이미 올라간 첨부: 상태가 없거나 그 형식을 뽑기 전 VERSION의 상태면 `magus warm-cache`(와 `magus extract`)·처음 열 때 뽑는다. 출력은 개수·시간뿐.
- **R**: 시험 `tests/test_extract_formats.py` 12개(형식마다·hwp 압축/비압축·암호/배포용/옛 형식·압축 폭탄·zip 폭탄·DTD·30만 자·xlsx 행 상한·doc 등 표시·warm-cache·대화 찾기·쪽 읽기·웹).
  hwp 시험 파일은 olefile이 쓰지 못해 시험 안의 작은 CFB 작성기로 만든다(미니 스트림 없이). 실제 한글 프로그램이 저장한 hwp·hwpx로는 아직 확인하지 않았다.

대안을 버린 이유: pyhwp는 AGPL이고, python-pptx·openpyxl·striprtf·bs4는 필요한 일(글자만)에 비해 무겁다. 표준 라이브러리 + lxml + olefile로 충분하다.
