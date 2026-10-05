from magus.instructions import AVOID, HEADER, RULES, build_instructions, required_tools

# 킥오프 문서 6절 원문. 규칙 4는 사용자 결정 #74(2026-10-06)로 바꿨다.
# 머리말의 '영감' → '생각'과 규칙 7~9는 사용자 결정 #85(2026-10-06, 용어 통일)로 더했다.
# 머리말에서 '책장'을 빼고 규칙 7 끝의 '쓰지 않는 이름' 문장을 바꾼 것은 사용자 결정 #87(2026-10-06)이다.
SPEC = """\
이 서버는 사용자의 생각·문헌·문체와 원고를 관리한다. 규칙:
1. 원고 작업은 항상 book_outline로 시작하고, 필요한 장만 book_read_chapter로 읽는다. 책 전체를 요구하지 않는다.
2. 인용은 ref_search로 확인된(verified) 출처만 쓴다. 확인되지 않은 출처는 본문에 [출처 필요: 주장 요약]로 적는다. 기억에 있는 문헌이라도 refs에 없으면 인용하지 않는다.
3. 사용자의 생각과 AI의 생각을 구분한다. idea_search 결과의 author=me 항목이 사용자의 주장이다.
4. 장 수정안은 대화에서 제안하고, 저자가 Word 원고에 반영한다. book_write_chapter는 저자가 Magus 원고에 저장하라고 명시했을 때만 쓰고, 그 장만 저장하며 note에 무엇을 바꿨는지 쓴다. 결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다.
5. 문체 작업은 style_search로 사용자의 취향을 먼저 꺼내고, 그 근거를 밝히며 제안한다.
6. style_add를 호출할 때는 구절과 이유에서 태그(호흡·시점·열기·장치·어미·톤)를 먼저 추출해 함께 넘긴다.
7. 저자에게 보이는 이름은 이것으로 한다: 전체(책 전체 현황. 구성·상태이고 원고 전문이 아니다) · 확인 요청(출처·사실을 확인해야 하는 곳. 도구의 issue이고, AI가 단 것은 'AI 확인 요청') · 생각(떠오른 아이디어 메모. 도구의 idea) · 문체(좋아서 모은 구절. 도구의 style) · 문헌(원문을 읽고 등록한 책·논문. 도구의 ref) · 결정(정해 둔 방침) · 수정본(Word에서 고친 원고를 다시 올린 것. 도구의 new_edition이고, E2·E3… 번호는 '수정본 번호'). 저자에게 답할 때는 이 이름을 쓰고, '책 지도'·'미해결'·'이슈'·'새 판'·'영감'·'책장'·'refs' 같은 말은 쓰지 않는다. 코어 이름(Casper·Melchior·Balthasar)이나 도구 이름을 저자에게 말하지 않는다.
8. 저자의 말은 이렇게 받는다. '전체 보여 줘'는 book_outline이다. '전체 읽어 줘'처럼 원고 전문을 원하면 한 번에 한 장씩 볼 수 있다고 알리고 어느 장부터 볼지 묻는다. '수정본 올렸어'·'수정본 올려 줘'는 files_list에서 가장 최근에 올린 원고 파일(.docx·.pdf)을 이 책(book_outline 첫 줄의 id)의 수정본으로 올린다(book_import, new_edition=true). 마지막 업로드 뒤에 올린 원고 파일이 여럿이거나 어느 것인지 분명하지 않으면 파일 이름을 보여 주고 묻는다.
9. '저장해 줘'·'기록해 줘'·'등록해 줘'·'넣어 줘'처럼 어디에 넣을지 말하지 않은 요청에는 쓰기 도구를 바로 부르지 않는다. 생각·문체·문헌 중 어디에 넣을지 먼저 묻고, 답을 들은 뒤 진행한다. book_write_chapter는 저자가 'Magus 원고에 저장'을 분명히 말했을 때만 쓴다."""

ALL_TOOLS = {
    "book_outline", "book_read_chapter", "book_write_chapter", "book_decide", "book_issue_add", "book_import",
    "ref_search", "idea_search", "style_search", "style_add", "files_list",
}
GLOSSARY = RULES[6]  # 도구를 부르지 않는 규칙이라 언제나 실린다


def test_all_tools_reproduce_spec_verbatim():
    assert build_instructions(ALL_TOOLS) == SPEC


def test_stage1_mentions_no_unregistered_tools():
    text = build_instructions({"book_outline"})
    for name in ("ref_search", "idea_search", "style_search", "style_add", "book_read_chapter", "files_list", "book_import"):
        assert name not in text
    assert text == f"{HEADER}\n1. {GLOSSARY}"


def test_rules_are_renumbered():
    text = build_instructions({"book_outline", "book_read_chapter", "style_search"})
    assert text.splitlines()[1].startswith("1. 원고 작업은")
    assert text.splitlines()[2].startswith("2. 문체 작업은")
    assert text.splitlines()[3].startswith("3. 저자에게 보이는 이름은")
    assert required_tools(text) == {"book_outline", "book_read_chapter", "style_search"}


def test_rule4_keeps_author_file_as_source():
    """#68·#74: Claude는 Magus 원고를 기본으로 고쳐 쓰지 않는다. 쓰기는 저자가 명시했을 때만."""
    rule4 = build_instructions(ALL_TOOLS).splitlines()[4]
    assert rule4.startswith("4. 장 수정안은 대화에서 제안하고, 저자가 Word 원고에 반영한다.")
    assert "명시했을 때만" in rule4
    assert "장을 고치면" not in rule4


def test_author_terms_and_ambiguous_saves():
    """#85: 저자에게는 용어집 이름으로 말하고, 넣을 곳을 말하지 않은 '저장해 줘'에는 쓰기 도구를 바로 부르지 않는다."""
    text = build_instructions(ALL_TOOLS)
    assert text.startswith("이 서버는 사용자의 생각·문헌·문체와 원고를 관리한다.") and "영감" not in text.replace(AVOID, "")
    assert "코어 이름(Casper·Melchior·Balthasar)이나 도구 이름을 저자에게 말하지 않는다." in text.splitlines()[7]
    for name in ("전체(", "확인 요청(", "생각(", "문체(", "문헌(", "결정(", "수정본("):
        assert name in text
    rule9 = text.splitlines()[9]
    assert rule9.startswith("9. '저장해 줘'·'기록해 줘'·'등록해 줘'·'넣어 줘'")
    assert "쓰기 도구를 바로 부르지 않는다" in rule9 and "먼저 묻고" in rule9
    assert "files_list" in required_tools(RULES[7])  # 수정본 올리기는 받은함을 먼저 본다
