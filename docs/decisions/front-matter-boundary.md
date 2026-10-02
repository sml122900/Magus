# 메타와 본문의 경계: 메타는 서버가 관리, 도구는 본문만

- 날짜: 2026-10-03
- 단계: 1단계(뼈대) + 검토 반영
- 코드: `src/magus/store/formats.py`, `src/magus/store/local.py` (`write_chapter`), `tests/test_store.py::test_caller_front_matter_is_ignored`

## Problem

- 인덱스를 파일에서 다시 만들려면 장의 메타(제목·상태·부·버전·note·갱신 시각)가 파일 안에 있어야 한다.
- 그런데 메타를 본문과 같은 파일에 두면 두 가지 위험이 생긴다. Claude가 `book_write_chapter`로 본문을 보낼 때 메타까지 보내 버전 번호를 덮어쓸 수 있다. 또 읽기 응답에 메타 문법이 섞여 토큰을 낭비한다.
- 제약: 저자가 파일을 직접 열었을 때 한눈에 이해되고, 직접 고칠 수도 있어야 한다.

## Action

- 장 파일은 `ch-NN.md` 하나로 하고, 맨 위에 front matter(`title`, `status`, `part`, `version`, `updated_at`, `note`)를 둔다. 제목은 front matter에만 두고, 본문에는 장 제목 줄을 넣지 않는다(export할 때 `# 제N장 제목`을 붙인다).
- **경계 규칙**
  - front matter는 서버만 쓴다. `version`은 서버가 1씩 올리고, `updated_at`은 서버 시각이며, `note`는 도구 인자로 받는다.
  - 도구는 본문만 주고받는다. `book_read_chapter`는 본문과 메타를 따로 돌려준다. `book_write_chapter`는 본문만 받는다(3단계).
  - 호출자가 본문 앞에 front matter를 붙여 보내면 `write_chapter`가 그 부분을 버리고 본문만 저장한다. 제목·상태·부는 명시적인 인자로만 바꿀 수 있다.
- front matter는 YAML 라이브러리 없이 한 줄짜리 `key: value`만 쓴다. 값에 줄바꿈이 들어오면 공백으로 바꾼다. 파서가 단순해야 사람이 고쳐도 망가지지 않는다.
- 비교한 대안
  - **별도 메타 파일**(`book/toc.json` 또는 `ch-NN.meta.json`): 본문 파일은 깨끗해진다. 하지만 장 하나가 두 파일로 나뉘어, 사람이 고칠 때 둘이 어긋나기 쉽다(원고가 두 파일로 갈라진 사례를 되풀이).
  - **메타를 SQLite에만**: 인덱스를 재생성할 수 없게 된다(원칙 위반).
  - **도구가 front matter를 포함한 파일 전체를 주고받기**: 버전 번호를 호출자가 망가뜨릴 수 있고, 응답이 길어진다.

## Result

- `test_caller_front_matter_is_ignored`: `title: 바꿔치기`, `version: 99`를 붙여 보내도 제목은 그대로이고 버전은 서버가 매긴 3이다. 파일 안의 front matter 구분선은 한 쌍뿐이다.
- `test_write_keeps_meta_and_versions`: 두 번째 쓰기에서 제목과 부를 생략해도 이전 값이 유지되고, 버전과 note가 올바르게 갱신된다.
- `test_reindex_rebuilds_same_index`: 메타가 파일에만 있어도 인덱스가 같게 복원된다.

> 대안을 버린 이유: 메타를 별도 파일에 두면 장이 두 파일로 갈라지고, SQLite에만 두면 인덱스를 재생성할 수 없다. 그래서 한 파일에 두되 쓰는 권한만 서버로 제한했다.
