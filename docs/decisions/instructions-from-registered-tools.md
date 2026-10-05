# instructions는 등록된 도구만 언급한다 (도구 목록에서 조립)

- 날짜: 2026-10-03
- 단계: 1단계 검토 반영(수정 2)
- 코드: `src/magus/instructions.py`, `src/magus/server.py`, `tests/test_instructions.py`

## Problem

- 킥오프 6절의 instructions 원문은 여섯 규칙에서 `ref_search`, `idea_search`, `style_search`, `style_add`, `book_decide` 등을 언급한다.
- 1단계에서 이 원문을 고정 문자열로 넣었더니, 실제로는 `book_outline`만 있는데 Claude가 존재하지 않는 도구 안내를 받게 됐다. 단계가 진행되는 동안 매번 이 어긋남이 생긴다.
- 제약: 규칙 문장은 6절 원문 그대로 써야 한다. 고쳐 쓰거나 요약하면 안 된다.

## Action

- 규칙 문장은 원문 그대로 `RULES` 튜플에 두었다. 각 규칙에 필요한 도구는 **문장에서 정규식으로 뽑는다**(`(?:book|ref|idea|style)_[a-z_]+`).
  - 규칙과 도구의 매핑을 따로 적지 않으므로, 원문과 매핑이 어긋날 일이 없다.
  - 한글 조사가 붙어도(`book_outline로`) `\b`를 쓰지 않으므로 이름만 정확히 잡힌다.
- `build_instructions(tool_names)`는 머리말에, 필요한 도구가 모두 등록된 규칙만 붙인다. 번호는 실린 규칙끼리 1부터 다시 매긴다.
- `MCPServer`는 생성자에서만 instructions를 받는다. 그래서 `build_server`의 순서를 바꿨다: `Tool.from_function`으로 도구 목록을 먼저 만들고 → 그 이름들로 instructions를 조립하고 → `MCPServer(tools=..., instructions=...)`를 만든다. SDK의 비공개 속성은 쓰지 않는다.
- 비교한 대안
  - **규칙마다 필요한 도구를 손으로 적은 매핑**: 원문과 매핑이 따로 놀 수 있다.
  - **단계별 instructions 사본**: 원문이 여러 벌로 갈라진다.
  - **서버를 만든 뒤 `_lowlevel_server.instructions`를 덮어쓰기**: 비공개 API에 의존하게 된다.

## Result

- `test_all_tools_reproduce_spec_verbatim`: 도구가 모두 등록되면 6절 원문과 글자 하나까지 같다.
- `test_stage1_mentions_no_unregistered_tools`: `book_outline`만 있으면 머리말만 남고, `ref_search`, `idea_search`, `style_search`, `style_add`, `book_read_chapter`가 등장하지 않는다.
- `test_server_identity_and_tools`: 실제 서버의 instructions가 등록된 도구 목록으로 조립된 결과와 같고, 언급된 도구는 모두 등록돼 있다.
- 현재 서버(outline·read·write)에는 1번 규칙만 실린다. 4번 규칙은 `book_decide`와 `book_issue_add`가 생기는 3단계에서 자동으로 들어간다.

> 대안을 버린 이유: 손으로 적은 매핑이나 단계별 사본은 원문과 어긋날 수 있다. 사후 덮어쓰기는 비공개 API에 의존한다. 그래서 원문에서 필요한 도구를 뽑아 조립하는 방식을 택했다.

> 후속(2026-10-06, 사용자 결정 #74): 규칙 4를 바꿨다. 원고 본문의 원본이 저자 파일이 되어(#68) Claude는 장 수정안을 대화로 제안하고, book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓴다. `tests/test_instructions.py`의 원문도 같은 문장으로 고쳤다.
