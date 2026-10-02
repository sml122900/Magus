import pytest

from magus.melchior.bibliography import import_bibliography, parse_bib_line, ref_from_bib
from magus.store import LocalStore


@pytest.mark.parametrize(
    ("line", "key", "title"),
    [
        (
            "Daeschler, E. B., Shubin, N. H., & Jenkins, F. A. (2006). A Devonian tetrapod-like fish. Nature, 440, 757–763.",
            "daeschler2006",
            "A Devonian tetrapod-like fish",
        ),
        ("12. Clack, J. A. (2012). Gaining ground (2nd ed.). Indiana University Press.", "clack2012", "Gaining ground (2nd ed.)"),
        ("김영민 (2020). 『아침에는 죽음을 생각하는 것이 좋다』. 사회평론.", "김영민2020", "아침에는 죽음을 생각하는 것이 좋다"),
        ("최재천·김산하 (2014). 『통섭의 식탁』. 움직이는서재.", "최재천2014", "통섭의 식탁"),
        ("Niedźwiedzki, G., & Ahlberg, P. E. (2010). Tetrapod trackways. Nature.", "niedzwiedzki2010", "Tetrapod trackways"),
        ("Romer, A. S. Vertebrate paleontology. University of Chicago Press, 1966.", "romer1966", "Vertebrate paleontology"),
        ("World Health Organization. (2020). A report. WHO.", "worldhealthorganization2020", "A report"),
        ("Clack, J. A. (2012a). Part one. Press.", "clack2012a", "Part one"),
    ],
)
def test_parse_lines(line, key, title):
    bib = parse_bib_line(line)
    assert bib is not None
    assert ref_from_bib(bib).key == key
    assert bib["title"] == title
    assert bib["raw"] == line.strip()


@pytest.mark.parametrize("line", ["편집부. 『자연사 연표』. 출판사 미상.", "Smith, J. Unpublished manuscript.", "——— 앞의 책, 23쪽."])
def test_unparseable_lines(line):
    assert parse_bib_line(line) is None


def test_translation_aliases():
    bib = parse_bib_line(
        "Henrich, J. (2016). The secret of our success. Princeton. "
        "[국역: 조지프 헨릭, 『호모 사피엔스, 그 성공의 비밀』, 주명진·이병권 옮김, 뿌리와이파리, 2019]"
    )
    ref = ref_from_bib(bib)
    assert ref.key == "henrich2016" and ref.aliases == ("헨릭2016", "헨릭2019")
    assert bib["translation"].startswith("조지프 헨릭") and "국역" not in bib["title"]


def test_import_keeps_failures_as_raw_and_is_idempotent(store: LocalStore):
    text = "참고문헌\nClack, J. A. (2012). Gaining ground. Press.\n\n편집부. 연도 없는 책.\nClack, J. B. (2012). Other. Press."
    report = import_bibliography(store, "alice", text)
    assert report.lines == 3 and report.created[0] == "clack2012" and report.created[2] == "clack2012-2"
    raw = store.get_ref("alice", report.created[1])
    assert raw.key.startswith("raw-") and raw.bib == {"raw": "편집부. 연도 없는 책."}
    again = import_bibliography(store, "alice", text)
    assert again.created == [] and len(again.existing) == 3
    assert store.list_refs("bob") == []


def test_shelf_files_are_the_source(store: LocalStore, data_dir):
    import_bibliography(store, "alice", "Galor, O. (2022). The journey. Dutton. [국역: 오데드 갤러, 『인류의 여정』, 시공사, 2023]")
    before = store.list_refs("alice")
    store.reindex()
    assert store.list_refs("alice") == before
    assert store.resolve_ref("alice", "갤러2023").key == "galor2022"
    assert store.resolve_ref("bob", "갤러2023") is None
