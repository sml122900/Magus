from magus.instructions import HEADER, build_instructions, required_tools

# 킥오프 문서 6절 원문
SPEC = """\
이 서버는 사용자의 책장(영감·문헌·문체)과 원고를 관리한다. 규칙:
1. 원고 작업은 항상 book_outline로 시작하고, 필요한 장만 book_read_chapter로 읽는다. 책 전체를 요구하지 않는다.
2. 인용은 ref_search로 확인된(verified) 출처만 쓴다. 확인되지 않은 출처는 본문에 [출처 필요: 주장 요약]로 적는다. 기억에 있는 문헌이라도 refs에 없으면 인용하지 않는다.
3. 사용자의 생각과 AI의 생각을 구분한다. idea_search 결과의 author=me 항목이 사용자의 주장이다.
4. 장을 고치면 book_write_chapter로 그 장만 저장하고 note에 무엇을 바꿨는지 쓴다. 결정은 book_decide에, 열린 문제는 book_issue_add에 남긴다.
5. 문체 작업은 style_search로 사용자의 취향을 먼저 꺼내고, 그 근거를 밝히며 제안한다.
6. style_add를 호출할 때는 구절과 이유에서 태그(호흡·시점·열기·장치·어미·톤)를 먼저 추출해 함께 넘긴다."""

ALL_TOOLS = {
    "book_outline", "book_read_chapter", "book_write_chapter", "book_decide", "book_issue_add",
    "ref_search", "idea_search", "style_search", "style_add",
}


def test_all_tools_reproduce_spec_verbatim():
    assert build_instructions(ALL_TOOLS) == SPEC


def test_stage1_mentions_no_unregistered_tools():
    text = build_instructions({"book_outline"})
    for name in ("ref_search", "idea_search", "style_search", "style_add", "book_read_chapter"):
        assert name not in text
    assert text == HEADER


def test_rules_are_renumbered():
    text = build_instructions({"book_outline", "book_read_chapter", "style_search"})
    assert text.splitlines()[1].startswith("1. 원고 작업은")
    assert text.splitlines()[2].startswith("2. 문체 작업은")
    assert required_tools(text) == {"book_outline", "book_read_chapter", "style_search"}
