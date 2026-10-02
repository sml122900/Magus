# 메타와 본문의 경계: 메타는 서버가 관리, 도구는 본문만

- 날짜: 2026-10-03
- 단계: 1단계(뼈대) + 1단계 검토 반영(수정 1: front matter는 도구 경계를 넘지 않는다)
- 코드: `src/magus/store/formats.py`, `src/magus/store/local.py` (`read_chapter`, `write_chapter`), `src/magus/book/tools.py`, `tests/test_server.py`, `tests/test_store.py`

## Problem

- 인덱스를 파일에서 다시 만들려면 장의 메타(제목·상태·부·버전·note·갱신 시각)가 파일 안에 있어야 한다.
- 그런데 메타를 본문과 같은 파일에 두면 두 가지 위험이 생긴다. Claude가 `book_write_chapter`로 본문을 보낼 때 메타까지 보내 버전 번호를 덮어쓸 수 있다. 또 읽기 응답에 메타 문법이 섞여 토큰을 낭비한다.
- 제약: 저자가 파일을 직접 열었을 때 한눈에 이해되고, 직접 고칠 수도 있어야 한다.

## Action

- 장 파일은 `ch-NN.md` 하나로 하고, 맨 위에 front matter(`title`, `status`, `part_number`, `version`, `updated_at`, `last_note`)를 둔다. **front matter에는 현재 상태만 둔다.** 이력은 `versions/`에만 남긴다. 제목은 front matter에만 두고, 본문에는 장 제목 줄을 넣지 않는다(export할 때 `# 제N장 제목`을 붙인다).
- **경계 규칙**
  - front matter는 서버만 쓴다. `version`은 서버가 1씩 올리고, `updated_at`은 서버 시각이며, `last_note`는 도구 인자 `note`로 받는다.
  - **front matter는 도구 경계를 넘지 않는다.**
    - `book_read_chapter`는 JSON을 돌려준다. `content`에는 본문(markdown)만 담고, 메타는 `title`, `status`, `part_number`, `version`, `last_note`, `unverified_cites`, `open_issues` 필드에 따로 담는다.
    - `book_write_chapter`는 `content`로 본문만 받는다. content가 `---`로 시작하는 front matter를 포함하면 서버가 벗겨 내고, 응답의 `warnings`에 경고를 넣는다. Store 층도 같은 처리를 한 번 더 한다(이중 방어).
    - 제목·상태는 `title`·`status` 인자로만 바꿀 수 있다.
  - JSON 응답은 `structured_output=False`인 텍스트 한 블록으로 보낸다. 장 본문이 `structuredContent`에 한 번 더 실려 응답이 두 배가 되는 것을 막는다.
- front matter는 YAML 라이브러리 없이 한 줄짜리 `key: value`만 쓴다. 값에 줄바꿈이 들어오면 공백으로 바꾼다. 파서가 단순해야 사람이 고쳐도 망가지지 않는다.
- 비교한 대안
  - **별도 메타 파일**(`book/toc.json` 또는 `ch-NN.meta.json`): 본문 파일은 깨끗해진다. 하지만 장 하나가 두 파일로 나뉘어, 사람이 고칠 때 둘이 어긋나기 쉽다(원고가 두 파일로 갈라진 사례를 되풀이).
  - **메타를 SQLite에만**: 인덱스를 재생성할 수 없게 된다(원칙 위반).
  - **도구가 front matter를 포함한 파일 전체를 주고받기**: 버전 번호를 호출자가 망가뜨릴 수 있고, 응답이 길어진다.

## Result

- `test_read_then_write_same_body_only_bumps_version`: 읽은 content를 그대로 write하면 버전만 1 오르고, 제목·상태·부·글자수와 본문은 그대로다. 경고는 없다.
- `test_write_with_front_matter_keeps_server_meta`: `title: 바꿔치기`, `status: done`, `version: 99`, `part_number: 7`을 붙여 보내도 서버 메타가 유지되고, 버전은 서버가 매긴 2다. 응답에 경고가 들어가고, 파일 안의 front matter 구분선은 한 쌍뿐이다.
- `test_read_returns_body_and_meta_separately`: content에 `---`나 `version:`이 없다.
- `test_caller_front_matter_is_ignored`(Store 층): 도구를 거치지 않아도 같은 규칙이 지켜진다.
- `test_write_keeps_meta_and_versions`: 두 번째 쓰기에서 제목과 부를 생략해도 이전 값이 유지되고, 버전과 note가 올바르게 갱신된다.
- `test_reindex_rebuilds_same_index`: 메타가 파일에만 있어도 인덱스가 같게 복원된다.

> 대안을 버린 이유: 메타를 별도 파일에 두면 장이 두 파일로 갈라지고, SQLite에만 두면 인덱스를 재생성할 수 없다. 그래서 한 파일에 두되 쓰는 권한만 서버로 제한했다.
