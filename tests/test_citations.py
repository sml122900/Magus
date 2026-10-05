import pytest

from magus.book.comments import classify_comment, is_citation_comment
from magus.melchior.citations import find_citations, make_ref_key


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("그 물고기는 (Daeschler, Shubin & Jenkins, 2006) 이후 유명해졌다.", "daeschler2006"),
        ("Clack(2012)은 길게 다룬다.", "clack2012"),
        ("Hu et al.(2023)에 따르면", "hu2023"),
        ("갤러(2022)의 말처럼", "갤러2022"),
        ("협력은 진화했다(헨릭, 2016).", "헨릭2016"),
        ("(Hu et al., 2023)", "hu2023"),
        ("Shubin and Daeschler (2006)", "shubin2006"),
    ],
)
def test_spec_patterns(text, key):
    assert [c.key for c in find_citations(text)] == [key]


def test_bare_form_only_when_asked():
    assert find_citations("Daeschler 2006 원문 확인") == []
    assert [c.key for c in find_citations("Daeschler 2006 원문 확인", bare=True)] == ["daeschler2006"]
    assert [c.key for c in find_citations("Hu et al. 2023, Clack, 2012", bare=True)] == ["hu2023", "clack2012"]
    assert find_citations("In 2006 그는 떠났다. 확인 2006", bare=True) == []


def test_order_and_dedup():
    text = "Clack(2012)과 (Daeschler, Shubin & Jenkins, 2006)를 보라."
    assert [c.key for c in find_citations(text, bare=True)] == ["clack2012", "daeschler2006"]


def test_make_ref_key_folds_diacritics():
    assert make_ref_key("Müller", "1999") == "muller1999"
    assert make_ref_key("O'Brien", "2001") == "obrien2001"


@pytest.mark.parametrize(
    ("comment", "anchor", "expected"),
    [
        ("Daeschler 2006 원문 확인 필요", None, ("citation", "daeschler2006")),
        ("인용 확인필요", "Clack(2012)은 길게 다룬다.", ("citation", "clack2012")),  # 공백 차이 무시, 원문에서 key
        ("서지 정보 누락", None, ("fact", None)),  # 출처 확인 요청인데 문헌 지목 없음
        ("원문 대조: Hu et al. 2023 p.12", None, ("citation", "hu2023")),
        ("이 문단은 너무 길다", "Clack(2012)", ("general", None)),
        # 최신본의 [점검·…] 태그(#72): "확인 필요"가 없어도 확인 요청이다
        ("[점검·인용] Xu et al. 2020의 기후 틈새 수치를 원문으로.", None, ("citation", "xu2020")),
        ("[점검·인용] \"경계 지대\"라는 표현의 출처.", "숲 가장자리(Potts, 1998)", ("citation", "potts1998")),
        ("[점검·인용] 인용문의 출처를 밝힐 것.", "긴 인용문", ("fact", None)),  # 문헌이 지목되지 않음
        ("[점검·서지] 감사원 보고서의 정확한 제목·발간일 확인.", None, ("fact", None)),
        ("[점검·통계] 동해 명태 어획량의 연도별 수치.", "Clack(2012)", ("fact", None)),  # 문헌이 있어도 수치 확인
        ("[점검·수치] 해발고도 출처 통일.", None, ("fact", None)),
        ("[점검 · 연도] 윤중제 준공(1968)", None, ("fact", None)),
        ("[점검·사실] 마추픽추 건설 시기", None, ("fact", None)),
        ("[점검·사례] 2010년 파키스탄 홍수", None, ("fact", None)),
        ("[점검·계산] 배수 계산 다시", None, ("fact", None)),
        ("[사진] 저자가 찍은 태백 사진으로 교체", None, ("general", None)),
        ("[점검·표현] 문장이 길다", None, ("general", None)),  # 모르는 태그는 본문 표현으로 가른다
    ],
)
def test_classify_comment(comment, anchor, expected):
    assert classify_comment(comment, anchor) == expected


def test_multiple_citations_in_one_parenthesis():
    assert [c.key for c in find_citations("(Clack, 2012; Hu et al., 2023; 헨릭, 2016)")] == ["clack2012", "hu2023", "헨릭2016"]


def test_korean_particle_is_stripped_but_original_kept_as_candidate():
    [c] = find_citations("갤러는(2022) 이것을 넓힌다.")
    assert c.key == "갤러2022" and c.lookup_keys == ("갤러는2022", "갤러2022")
    [c] = find_citations("카를로(2010)는")  # 이름 끝에 흔한 글자(로·은·만)는 조사로 보지 않는다
    assert c.lookup_keys == ("카를로2010",)
    [c] = find_citations("김성은·테르틸트·염민철(2024)")  # 실원고: '김성은'이 '김성'으로 잘리던 문제
    assert c.key == "김성은2024"


def test_korean_non_author_words_are_ignored():
    assert find_citations("그 논문(2006)에서, 당시(1998) 상황은") == []


def test_year_suffix_is_part_of_key():
    assert [c.key for c in find_citations("Clack(2012a)과 (Clack, 2012b)")] == ["clack2012a", "clack2012b"]


@pytest.mark.parametrize(
    ("comment", "is_request"),
    [
        ("물고기가 일어서지 못하는 장면 보강", False),
        ("서지 정보 누락", True),
        ("서지정보 확인", True),
        ("서지", True),
        ("출간 전에 원문과 대조해 주세요", True),  # 실원고 변형
        ("표현을 확인할 필요가 있습니다", True),
    ],
)
def test_citation_request_markers(comment, is_request):
    assert is_citation_comment(comment) is is_request


# 실원고(닿으려는 종)에서 확인한 표기들
@pytest.mark.parametrize(
    ("text", "keys"),
    [
        ("(Araújo et al., 2022)", ["araujo2022"]),
        ("(Myrskylä, Kohler & Billari, 2009)", ["myrskyla2009"]),
        ("(Huerta-Sánchez et al., 2014)", ["huertasanchez2014"]),
        ("(de Vries, 1984)", ["devries1984"]),
        ("(Bolt & van Zanden, 2024)", ["bolt2024"]),
        ("(della Paolera & Taylor, 2003)", ["dellapaolera2003"]),
        ("(Ibn Khaldun, 1967)", ["ibnkhaldun1967"]),
        ("(Korea JoongAng Daily, 2025a)", ["koreajoongangdaily2025a"]),
        ("(田代和生, 1981)", ["田代和生1981"]),
        ("(1990년 국제달러, Maddison, 2001)", ["maddison2001"]),
        ("(경향신문, 2013)", ["경향신문2013"]),
        ("셰 등(2019)", ["셰2019"]),
        ("넌·첸(2011)", ["넌2011"]),
        ("애쓰모글루와 로빈슨(2012)", ["애쓰모글루2012"]),
        ("모스크바 회사(1555), 합계출산율(2023), 곡물법 반대 동맹(1838)", []),
        ("(예: 한국의 1913~1950년)", []),
    ],
)
def test_real_manuscript_forms(text, keys):
    assert [c.key for c in find_citations(text)] == keys
