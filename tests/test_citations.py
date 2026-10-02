import pytest

from magus.book.comments import classify_comment
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
        ("서지 정보 누락", None, ("citation", None)),
        ("원문 대조: Hu et al. 2023 p.12", None, ("citation", "hu2023")),
        ("이 문단은 너무 길다", "Clack(2012)", ("general", None)),
    ],
)
def test_classify_comment(comment, anchor, expected):
    assert classify_comment(comment, anchor) == expected
