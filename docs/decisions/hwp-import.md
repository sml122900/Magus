# 한글(hwpx·hwp) 원고를 올린 문서로 가져오기 (2026-10-14, 야간 작업 · 아침 승인 묶음 · 서버 배포 전)

## Problem

- 올린 문서(book_import)는 Word(docx)와 PDF만 받았다. 한국 저자 상당수는 한글로 쓴다. 게시판 첨부의 글자 뽑기(`magus/extract.py`)는
  2026-10-11부터 hwp·hwpx 글자를 뽑지만, 글자를 흘려 30만 자까지 모으는 일이라 문단 단위·제목 단계·표·메모 같은 구조가 없어 장 나누기에 쓸 수 없다.
- 제약
  - 장 나누기·코멘트 분류·참고문헌·수정본(`importer.py`·`reupload.py`)은 docx와 똑같이 써야 한다. 그래서 docx_reader와 같은 중간 꼴(`Manuscript`: 블록·코멘트)을 만든다.
  - 새 의존성 없이 한다(olefile·lxml은 이미 있다). 압축 폭탄·암호·배포용·한글 97 이전 문서를 막는다.
  - **개요 번호**: 한글은 '제1장'·'1.'·'가.' 같은 개요 번호를 글자로 저장하지 않고 번호 정의(형식 `제^1장`, 모양 DIGIT 등)로 그린다.
    글자로 '제N장'을 찾는 importer가 장을 하나도 못 찾을 수 있다(그러면 가져오기가 통째로 실패한다).
  - 서버 배포는 하지 않는다(아침 승인 묶음). 도구 설명·스키마는 바꿔도 되지만 최소로, instructions 규칙 문장은 바꾸지 않는다.

## Action

1. **새 모듈 `magus/book/hwp_reader.py`**(`read_hwpx`·`read_hwp`·`read_hangul`). 결과는 docx_reader의 `Manuscript` 그대로(`source`에 hwpx·hwp를 더함).
   - **hwpx(OWPML, zip + XML)**: zipguard 검사 → `META-INF/manifest.xml`에 암호화 표시면 멈춤 → `Contents/content.hpf`의 spine 차례로 구역
     (없으면 `Contents/sectionN.xml` 번호 차례), 문서 정보의 제목 → `Contents/header.xml`에서 스타일 이름(영문 이름)·문단 모양의 머리(heading type·idRef·level)·번호 정의
     → 구역마다 문단(`hp:p`). XML은 엔티티를 풀지 않고 네트워크를 쓰지 않는 파서로 읽는다.
     - 제목 단계: 스타일 이름 `개요 N`·`Outline N`·`제목 N`·`Heading N` → N, 아니면 문단 모양 머리가 OUTLINE이면 수준 + 1. NUMBER·BULLET은 목록(`- `).
     - 표(`hp:tbl`): 문단 안에 놓이므로 그 문단 다음 블록. 칸은 `cellAddr`로 자리를 잡아 markdown 표(합친 칸은 빈 칸, 칸이 모두 비면 `[표 N]`). 표 안 표는 그 칸의 글로. 캡션은 표 다음 문단.
     - 그림·도형·글상자·OLE·차트 → `[그림 N]`(캡션이 있으면 뒤에). 수식 → `[수식]`. 머리말·꼬리말·숨은 설명·누름틀 안내문·변경 추적으로 지운 글자는 싣지 않는다. 호환 묶음(`hp:switch`)은 default만.
     - **각주·미주 → markdown 각주**: 본문에 `[^N]`, 그 문단(과 표) 뒤에 `[^N]: 내용` 블록. 번호는 문서 전체에서 하나씩이라 내보내기(pandoc)에서 장을 합쳐도 겹치지 않고 Word 각주가 된다.
       importer의 제목 줄 판정은 `[^N]`을 떼고 본다.
     - **메모 → 코멘트**: `fieldBegin type="MEMO"` … `fieldEnd`(beginIDRef·fieldid로 짝). 작성자는 인자 `Author`(·writer·작성자), 날짜는 이름에 date·time이 든 인자,
       내용은 필드 안 `subList`의 문단, 없으면 메모 묶음(`hp:memo`)에서 id로(그래도 없으면 차례로). 걸린 글은 두 필드 사이 글(docx의 commentRange와 같다). 그 뒤는 docx와 똑같이 확인 요청(작성자·AI 판정·지문)이 된다.
   - **hwp 5.0(OLE 복합 파일)**: 한글 97 이전(서명 `HWP Document File` 머리) → 멈춤. FileHeader 속성의 암호·배포용·DRM·공인인증서 비트나 `ViewText` → 멈춤.
     `DocInfo`(STYLE·PARA_SHAPE·NUMBERING)와 `BodyText/SectionN`을 읽어(압축이면 raw deflate) 레코드를 수준으로 나무로 만든다.
     - 문단 = PARA_HEADER(문단 모양 id 8바이트째·스타일 id 10바이트째) + PARA_TEXT(UTF-16LE. 제어 문자: 한 글자짜리는 2바이트, 나머지는 16바이트) + CTRL_HEADER들.
       확장 컨트롤은 글자 안의 컨트롤 id로 CTRL_HEADER와 차례를 맞춘다: `tbl `(TABLE의 행·열 수 + 칸마다 LIST_HEADER의 셀 주소), `gso `(그림·도형), `eqed`(수식),
       `fn  `·`en  `(각주·미주), `secd`(구역 정의: 개요 번호 정의 id). 머리말·꼬리말·숨은 설명·책갈피·필드는 싣지 않는다.
     - 셀 주소 앞 '문단 리스트 머리'를 공개 문서는 6바이트, pyhwp는 8바이트로 읽는다. 둘 다 해 보고 모든 칸이 표 크기 안에서 겹치지 않는 쪽을 쓴다(아니면 차례대로).
     - 메모: 꼴을 확인할 길이 없어 **가져오지 않는다**. 메모 목록(MEMO_LIST) 레코드 수만 리포트 머리에 "hwp 메모 N개는 확인 요청으로 가져오지 않음(hwpx로 저장해 올리면 가져온다)".
     - 폭탄: 스트림 하나 50MB, 압축을 풀 때 1MB를 넘으면 압축률 100:1, 파일 전체 200MB(zipguard와 같은 규칙, extract의 `_inflate`와 같은 수치).
   - **개요 번호를 글자로**(hwpx·hwp 공통 `Outline`): 개요 문단마다 그 수준 카운터를 하나 올리고 아래 수준을 처음으로 돌린 뒤, 형식 글의 `^N`을 N수준 번호(그 수준의 모양: 숫자·①·Ⅰ·i·A·a·가·㉮·ㄱ·일·一)로 채워
     문단 앞에 붙인다(`물고기의 결심` + `제^1장` → `제1장 물고기의 결심`). 글자가 이미 그 번호로 시작하거나 '제N장·제N부·서장·맺음·부록·참고문헌'을 손으로 적은 문단에는 붙이지 않는다
     (기본 개요 번호 `^1.`이 손으로 적은 '제1장 …' 앞에 붙어 장 찾기를 가리지 않게).
2. **연결**: `importer.read_manuscript`(.hwpx·.hwp, 깨진 파일은 같은 UNREADABLE 문장), 수정본(`reupload`, 같은 함수를 쓴다), 문서 업데이트(`docupdate.DOC_TYPES`·원본 판정 `inbox.MANUSCRIPT_TYPES`),
   올린 파일·게시판 첨부를 도구 인자로(`inbox.INBOX_TYPES` → files_list에 보이고 `첨부:<id>`로 가져옴), 문헌 전문(`melchior.refs.read_fulltext`), 내려받기 원본 폴백(`original_bytes`), CLI 도움말, 도움말 문서.
3. **비교한 대안**
   - extract.py의 `_hwp`·`_Hwpx`를 고쳐 함께 쓰기: 그쪽은 글자를 흘려 상한까지 모으는 일(구조 없음)이고, 오늘 밤 다른 작업이 그 파일을 고치고 있다. 작은 조각(레코드 머리·deflate)은 베꼈다.
   - pyhwp(hwp5) 같은 라이브러리: AGPL·큰 의존성·hwpx 미지원. LibreOffice·한컴 변환기로 docx로 바꾸기: 서버에 무거운 프로그램, 메모·개요 번호 변환이 불확실.
   - 제목 단계를 글자 크기로(PDF처럼): 한글 문서는 스타일·개요 수준이 있어 그쪽이 정확하다.
   - 각주를 버리기(docx_reader와 같게): 인용을 각주에 다는 원고가 많아, 버리면 인용 점검(ref_check)이 못 본다. markdown 각주는 내보내기에서 각주로 돌아온다.

## Result

- 시험 `tests/test_hwp_import.py` 15개(모두 코드로 만든 hwpx·hwp, 밖의 파일 없음): hwpx 블록(제목 단계·표·목록·각주·그림·수식·지운 글자·switch·머리말 뺌·메모 두 꼴),
  hwpx 가져오기(장 3·부 2·확인 요청 2(citation·ref_key·작성자·AI 판정·¶)·문헌 2·제목/부제/영문 제목·원본 사본·판 E1), 개요 번호(hwpx·hwp), 수정본 E2(문서 업데이트)·E3,
  hwpx 암호·깨짐·폭탄, hwp 압축/비압축 × 셀 머리 8/6바이트, hwp 가져오기·문헌 전문, hwp 암호·배포용·ViewText·3.x·깨짐·폭탄, 대화 book_import(hwpx)·files_list.
- 도구 목록 6,506 → 6,468토큰(replace 뺌 포함), instructions 2,706토큰 그대로(`private/tmp/measure_tools.py` 방식 추정). 도구 설명·스키마가 바뀌어 **커넥터 재연결이 필요**하다.
- **남은 것(대기: 사용자)**: 실제 한글 프로그램이 만든 파일로 확인하지 못했다. 공개해도 되는 hwpx·hwp 원고 하나씩(개요 번호 '제^1장', 메모, 표, 각주가 든 것)을 `USER_ID=synthetic`으로
  `magus import`해 볼 것. 추정에 기댄 곳: hwpx 메모 인자 이름(Author·CreateDateTime), hwp 구역 정의의 개요 번호 id 자리(18바이트째)·번호 정의 id가 1부터인지·번호 모양 비트(5~8), 셀 머리 길이.
- 한계: hwp 메모는 가져오지 않는다. 글상자 안 글은 `[그림 N]`(docx와 같다). 덧말·글자 겹침·쪽 나눔은 무시. 표 안 각주는 표 다음에. 번호 목록의 번호는 붙이지 않는다(docx와 같다).
  docx_reader는 여전히 각주를 버린다(한글과 다름 — 맞출지는 후속 제안).

대안을 버린 이유: extract와 합치면 구조 없는 흐름 읽기와 섞이고 다른 작업과 겹치며, 외부 라이브러리·변환기는 라이선스·무게·메모 손실이 크고, 각주를 버리면 인용 점검이 각주의 인용을 못 본다.
