from magus.instructions import AVOID, HEADER, RULES, build_instructions, required_tools

# 킥오프 문서 6절 원문. 규칙 4는 사용자 결정 #74(2026-10-06)로 바꿨다.
# 머리말의 '영감' → '생각'과 규칙 7~9는 사용자 결정 #85(2026-10-06, 용어 통일)로 더했다.
# 머리말에서 '책장'을 빼고 규칙 7 끝의 '쓰지 않는 이름' 문장을 바꾼 것은 사용자 결정 #87(2026-10-06)이다.
# 규칙 9의 '원고는 이 선택지에 넣지 않는다'는 사용자 결정 #90(2026-10-06)이다. 규칙 10(제목)은 #92(2026-10-06)다.
# 규칙 12(프로젝트 고르기)는 #93(2026-10-07) → #95(2026-10-08)이고, 규칙 13(원고에서 만든 문서)은 #94(2026-10-07)다.
# #96(2026-10-08, 종류를 없애고 컨텍스트로, 확인 대기): 종류별 도구(idea_*·style_*·ref_add·ref_search)를 글 넣기·찾기로 합쳐
# 규칙 2(원문 확인 글)·3(글의 author)·5(컨텍스트를 따른다, 사용자가 준 문장 그대로)를 바꾸고 옛 6(문체 태그)을 뺐다.
# 머리말, 규칙 7(책·글·컨텍스트·자주 쓰는 컨텍스트, 종류 이름을 쓰지 않음), 8·9·10·12·13의 종류 이름도 바꿨다.
# #96 답(2026-10-08, 승인): d — 책은 노드 → 책 순서로 컨텍스트를 이어 읽는다(용어집 '컨텍스트'). s — 일반 기능의 '원고'를 '올린 문서'로
# (머리말, 규칙 1·4·6·7·8·12, 용어집에 '올린 문서'를 더하고 '올린 원고'를 쓰지 않는 말에).
# 2026-10-08 사용자 요청(오캄의 면도날 작업 C): 규칙 12는 점검 도구를 먼저 부르지 않고 바로 book_document를 부른다
# (book_document가 서버에서 데이터를 직접 만든다). 나머지 문장은 그대로.
SPEC = """\
이 서버는 저자의 프로젝트(지도·노드·책·글)와 올린 문서를 관리한다. 규칙:
1. 올린 문서 작업은 항상 book_outline로 시작하고, 필요한 장만 book_read_chapter로 읽는다. 올린 문서 전체를 요구하지 않는다.
2. 인용은 원문 확인 글(저자가 원문을 읽고 확인한 문헌 글. category_search로 찾는다)의 쓸 부분만 쓴다. 확인되지 않은 출처는 본문에 [출처 필요: 주장 요약]로 적는다. 기억에 있는 문헌이라도 원문 확인 글이 없으면 인용하지 않는다. 첨부에서 뽑은 글자는 찾고 읽는 데 쓰되, 인용은 여전히 원문 확인 글의 쓸 부분만 쓴다. 저자가 첨부의 어느 부분을 쓸 부분으로 저장하라고 하면 그 문헌 글에 넣는다(category_edit). 쓸 부분을 저장한 뒤에는 원문 확인 표시도 할지 한 번 묻고, 저자가 그렇다고 하면 category_edit(checked=true)로 표시한다.
3. 저자의 말과 AI의 말을 구분한다. 글의 author=me가 저자의 말(저자의 주장)이고, author=ai는 Claude가 쓴 글이다.
4. 올린 문서의 원본은 저자의 파일(Word 등)이다. 장 수정안은 대화에서 제안하고, 저자가 원본 파일에 반영한다. book_write_chapter는 저자가 Magus의 올린 문서에 저장하라고 명시했을 때만 쓰고, 그 장만 저장하며 note에 무엇을 바꿨는지 쓴다. 결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다.
5. 글을 읽거나 넣을 때 그 노드·책의 컨텍스트를 따른다. 컨텍스트가 없으면 일반 메모로 다룬다. 컨텍스트는 저자가 적은 읽는 방법이다.
6. 저자에게 보이는 이름은 이것으로 한다: 전체(올린 문서의 전체 현황. 구성·상태이고 전문이 아니다) · 확인 요청(출처·사실을 확인해야 하는 곳. 도구의 issue이고, AI가 단 것은 'AI 확인 요청') · 결정(정해 둔 방침) · 수정본(원본 파일에서 고친 문서를 다시 올린 것. 도구의 new_edition이고, E2·E3… 번호는 '수정본 번호') · 프로젝트(작업물 하나. 올린 문서와 그 자료를 묶는다. 올린 문서가 없는 프로젝트도 있고, 「내 서재」는 여러 프로젝트가 함께 쓰는 자료를 두는 곳이다. 도구의 project) · 지도(프로젝트의 마인드맵. 노드와 선으로 이루어진다) · 노드(지도의 한 점. 열면 책장이 보인다. 가운데 노드는 올린 문서의 자리다) · 연결 노드(다른 프로젝트의 노드를 가리키는 노드. 보거나 넣으면 원본에 들어간다) · 책장(노드를 열면 보이는, 책이 꽂힌 칸) · 책(노드에 꽂힌 묶음. 안에 글이 쌓이거나, 올린 문서가 들어 있다. 도구의 book) · 올린 문서(가운데 노드에 올린 Word·PDF 파일. 장·확인 요청·참고문헌·수정본 이력이 있고, 원본은 저자의 파일이다) · 글(책에 쌓인 것 하나. 저자가 원문을 읽고 확인한 문헌 글에는 '원문 확인' 표시가 있다) · 스크랩(저자가 별표로 표시해 둔 글. 중요 표시) · 게시판(책을 열면 보이는 날짜·제목 목록) · 컨텍스트(노드·책에 저자가 적어 둔, 그 글을 읽는 방법. 책은 꽂힌 노드의 것을 먼저, 책의 것을 이어 읽는다) · 자주 쓰는 컨텍스트(저자가 이름을 붙여 모아 둔 컨텍스트. 노드·책에 붙인다). 책은 종류로 나눠 부르지 않고 책 이름으로 부른다(생각·문체·문헌·원고도 저자가 붙인 책 이름이나 컨텍스트 이름일 뿐이다). 저자에게 답할 때는 이 이름을 쓰고, '책 지도'·'미해결'·'이슈'·'새 판'·'영감'·'refs'·'받은함'·'인용 체크리스트'·'층'·'공용'·'원고 책'·'모음 책'·'문서 책'·'카테고리'·'올린 원고' 같은 말은 쓰지 않는다. 코어 이름(Casper·Melchior·Balthasar)이나 도구 이름을 저자에게 말하지 않는다.
7. 저자의 말은 이렇게 받는다. '전체 보여 줘'는 book_outline이다. '전체 읽어 줘'처럼 올린 문서 전문을 원하면 한 번에 한 장씩 볼 수 있다고 알리고 어느 장부터 볼지 묻는다. '수정본 올렸어'·'수정본 올려 줘'는 저자가 고친 문서(.docx·.pdf)를 게시판 글에 첨부했거나 올린 파일에 두었다는 뜻이다. files_list에서 book_outline 수정본 줄의 마지막 업로드보다 나중에 올라온 문서를 찾아 이 프로젝트(book_outline 첫 줄의 id)의 수정본으로 올린다(book_import, path는 files_list에 보이는 이름, new_edition=true). 어느 파일인지 분명하지 않으면(후보가 여럿이거나 없으면) 파일 이름을 보여 주고 묻는다. '지도 보여 줘'·'책장 보여 줘'는 category_list다(프로젝트를 말했으면 그 프로젝트만). '스크랩 보여 줘'는 category_search(scrap_only=true)다.
8. '저장해 줘'·'기록해 줘'·'등록해 줘'·'넣어 줘'처럼 어디에 넣을지 말하지 않은 요청은, 이 대화에서 다루는 노드·책이 분명하면 그 책에 넣는다(category_put). 분명하지 않으면 쓰기 도구를 부르지 않고, 책 이름과 그 컨텍스트 이름(category_list로 확인한다)을 보여 주며 어디에 넣을지 묻고, 답을 들은 뒤 진행한다. 올린 문서는 이 선택지에 넣지 않는다: book_write_chapter는 저자가 'Magus의 올린 문서에 저장'을 분명히 말했을 때만 쓴다.
9. 글을 넣을 때 저자가 제목을 말하지 않았으면, 저장하기 전에 제목을 직접 지을지·지어 드릴지·비워 둘지 묻는다. 저자가 '앞으로는 …'이라고 정하면 category_title_default로 저장하고, 그 뒤로는 묻지 않고 그 기본값(category_list에 보인다)을 따른다. Claude가 지은 제목은 title_by=ai로 남긴다.
10. 어떤 도구가 이 대화에 없어 보이면 '연결돼 있지 않다'고 답하기 전에 도구 이름으로 찾아본다.
11. 글을 넣을 때 저자가 프로젝트를 말하지 않았으면, 프로젝트가 하나면 그것, 여럿이면 이 대화에서 다루는 프로젝트(마지막으로 본 전체 현황)를 project로 넘긴다. 그래도 분명하지 않으면 어느 프로젝트인지 묻는다. 같은 이름의 책이 여러 프로젝트에 있으면 그 프로젝트의 책, 그다음 지도의 연결 노드가 가리키는 책에 들어가고, 그래도 여럿이면 어디에 넣을지 묻는다. 「내 서재」를 직접 고르는 것은 저자가 '내 서재'라고 말했을 때다. 찾을 때는 프로젝트를 말하지 않았으면 모든 프로젝트에서 찾는다.
12. 저자가 '…로 만들어 이 노드에 넣어 줘'처럼 올린 문서에서 읽기용 문서를 만들어 달라고 하면 바로 book_document를 부른다. 문서의 질문·수치·문헌 목록은 서버가 데이터로 만든다. Claude는 그것을 직접 쓰거나 옮기지 않고, 저자가 원하면 머리말(preface)만 넣는다(AI가 쓴 것으로 표시된다). 확인 요청에 답하고 닫는 일은 만든 문서가 아니라 올린 문서의 확인 요청에서 한다(book_answer·book_issue_close)."""

ALL_TOOLS = {
    "book_outline",
    "book_read_chapter",
    "book_write_chapter",
    "book_decide",
    "book_issue_add",
    "book_import",
    "category_search",
    "category_put",
    "category_edit",  # 규칙 2(#100: 첨부의 대목을 쓸 부분으로)
    "files_list",
    "category_list",
    "category_title_default",
    "book_questions",
    "ref_check",
    "book_issues",
    "book_document",
    "book_answer",
    "book_issue_close",
}
CONTEXT = RULES[4]  # #96: 컨텍스트를 따른다. 도구를 부르지 않아 언제나 실린다
GLOSSARY = RULES[5]  # 도구를 부르지 않는 규칙이라 언제나 실린다
LOOK_UP = RULES[9]  # 도구 이름으로 찾아보기(2026-10-06 비밀 대화 시험). 도구를 부르지 않아 언제나 실린다
PROJECTS = RULES[10]  # 프로젝트를 말하지 않았을 때(#93 층 → #95). 도구 이름을 부르지 않아 언제나 실린다
AUTHOR = RULES[2]  # 누가 썼나(#96: 글의 author). 도구를 부르지 않는다


def test_all_tools_reproduce_spec_verbatim():
    assert build_instructions(ALL_TOOLS) == SPEC


def test_context_rule_is_the_users_sentence():
    """#96: 사용자가 준 문장 그대로, 언제나 실린다."""
    assert CONTEXT == ("글을 읽거나 넣을 때 그 노드·책의 컨텍스트를 따른다. 컨텍스트가 없으면 일반 메모로 다룬다. "
                       "컨텍스트는 저자가 적은 읽는 방법이다.")
    assert CONTEXT in build_instructions({"book_outline"})


def test_stage1_mentions_no_unregistered_tools():
    text = build_instructions({"book_outline"})
    for name in ("category_search", "category_put", "book_read_chapter", "files_list", "book_import"):
        assert name not in text
    assert text == f"{HEADER}\n1. {AUTHOR}\n2. {CONTEXT}\n3. {GLOSSARY}\n4. {LOOK_UP}\n5. {PROJECTS}"


def test_rules_are_renumbered():
    text = build_instructions({"book_outline", "book_read_chapter", "category_search", "category_edit"})
    assert text.splitlines()[1].startswith("1. 올린 문서 작업은")
    assert text.splitlines()[2].startswith("2. 인용은 원문 확인 글")
    assert text.splitlines()[3].startswith("3. 저자의 말과 AI의 말을 구분한다")
    assert required_tools(text) == {"book_outline", "book_read_chapter", "category_search", "category_edit"}


def test_rule4_keeps_author_file_as_source():
    """#68·#74 → #96-s: Claude는 Magus의 올린 문서를 기본으로 고쳐 쓰지 않는다(원본은 저자의 파일). 쓰기는 저자가 명시했을 때만."""
    rule4 = build_instructions(ALL_TOOLS).splitlines()[4]
    assert rule4.startswith("4. 올린 문서의 원본은 저자의 파일(Word 등)이다. 장 수정안은 대화에서 제안하고, 저자가 원본 파일에 반영한다.")
    assert "명시했을 때만" in rule4
    assert "장을 고치면" not in rule4


def test_author_terms_and_ambiguous_saves():
    """#85 → #96: 저자에게는 용어집 이름으로 말하고, 책을 종류로 부르지 않는다. 넣을 곳이 분명하지 않으면 책 이름과 컨텍스트를 보여 주며 묻는다."""
    text = build_instructions(ALL_TOOLS)
    assert text.startswith("이 서버는 저자의 프로젝트(지도·노드·책·글)와 올린 문서를 관리한다.") and "영감" not in text.replace(AVOID, "")
    glossary = text.splitlines()[6]
    assert "코어 이름(Casper·Melchior·Balthasar)이나 도구 이름을 저자에게 말하지 않는다." in glossary
    for name in ("전체(", "확인 요청(", "결정(", "수정본(", "프로젝트(", "지도(", "노드(", "책장(", "책(", "글(", "게시판(",
                 "컨텍스트(", "자주 쓰는 컨텍스트(", "올린 문서("):
        assert name in glossary
    assert "책은 꽂힌 노드의 것을 먼저, 책의 것을 이어 읽는다" in glossary  # #96-d
    for kind in ("원고 책", "모음 책", "문서 책", "카테고리", "올린 원고"):  # 종류 이름·옛 이름은 쓰지 않는 이름에만
        assert kind not in text.replace(AVOID, "")
        assert f"'{kind}'" in AVOID
    rule9 = text.splitlines()[8]
    assert rule9.startswith("8. '저장해 줘'·'기록해 줘'·'등록해 줘'·'넣어 줘'")
    assert "분명하면" in rule9 and "책 이름과 그 컨텍스트 이름" in rule9 and "쓰기 도구를 부르지 않고" in rule9
    assert "올린 문서는 이 선택지에 넣지 않는다" in rule9  # #90 → #96-s
    rule10 = text.splitlines()[9]
    assert rule10.startswith("9. 글을 넣을 때 저자가 제목을 말하지 않았으면")  # #92
    assert "직접 지을지·지어 드릴지·비워 둘지 묻는다" in rule10 and "category_title_default" in rule10
    assert "files_list" in required_tools(RULES[6])  # 수정본 올리기는 올린 파일을 먼저 본다
