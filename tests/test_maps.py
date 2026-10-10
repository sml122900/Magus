"""프로젝트·지도(#95): 프로젝트(옛 층) → 지도 → 노드 → 책. 「내 서재」(옛 공용 층), 연결 노드, 자유로운 선.
#96: 기본 책(생각·문체·문헌)이 없다. 새 사용자에게는 책이 없고, 옛 데이터는 이전(magus maps apply)으로 여느 책 + 컨텍스트가 된다.

- 계산한 지도: 지도 파일이 없으면 지금 배치에서 지도를 계산한다(가운데 노드에 원고·문서 책, 기본 책·카테고리는 이름이 같은 노드 하나씩,
  「내 서재」의 문헌(과, 자기 문체가 없으면 문체)으로 가는 연결 노드). 이전은 그 지도를 파일로 적는 일이다.
- 노드·선: 만들기·이름·색·위치·잇기·끊기·휴지통(가운데·책이 꽂힌 노드는 막음)·되살리기, 한도.
- 연결 노드: 원본을 가리키고(연결의 연결은 원본으로), 원본이 없어지면 '원본 없음'.
- 책 옮기기: 같은 프로젝트에서는 노드만, 다른 프로젝트로는 항목이 함께(기본 책은 합침, 같은 이름의 카테고리는 막음), 되돌리기(노드까지).
- 인용 점검: 자기 문헌 + 연결 노드가 가리키는 문헌. 이전 전후·옛 규칙(그 층 + 공용)과 같다(필수 시험).
  다른 프로젝트에만 있던 문헌을 쓰게 되면 「내 서재」로 옮기고 두 지도에 연결 노드를 붙인다.
- 이전: 층 이전 전·뒤 어느 데이터에서 시작해도 같은 지도. revert는 "floor"를 떼고 지도 폴더를 비켜 둔다.
- 도구: project 인자, 묻기, 지도 보기(category_list)·전체 현황의 지도 줄, 노드 만들기·연결 노드·선·휴지통, 책 옮기기.
- 격리: 다른 사용자의 지도·노드를 바꿀 수 없고 보이지 않는다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import with_library
from mcp import Client

from magus import map_migrate
from magus.category.moves import error_message, move_book, trash_node, undo_move
from magus.config import Settings
from magus.floors import COMMON, MAX_FLOORS, josa
from magus.maps import CENTER, MAX_BOOKS_PER_NODE, MAX_NODES
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import after_refs_changed, check_chapter
from magus.server import build_server
from magus.store import CategoryItem, LocalStore, Passage, Ref
from magus.store.floors import MoveError
from magus.store.maps import MapError
from magus.synthetic import build_manuscript_docx

pytestmark = pytest.mark.anyio

CHAPTER = "물고기는 뭍으로 올라왔다(Daeschler, Shubin & Jenkins, 2006). 그 뒤의 일은 Clack(2012)이 정리했다."
BIB = ("Daeschler, E. B., Shubin, N. H., & Jenkins, F. A. (2006). A Devonian tetrapod-like fish. Nature, 440, 757–763.\n"
       "Clack, J. A. (2012). Gaining ground. Indiana University Press.")
TAGS = {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": [], "어미": "-다", "톤": "건조"}
T0 = "2026-10-01T00:00:00.000Z"


def _text(result) -> str:
    return "\n".join(block.text for block in result.content)


def _book(store: LocalStore, user: str = "alice", pid: str = "book", title: str = "물에서 뭍으로") -> None:
    store.create_project(user, title, project_id=pid)
    store.write_chapter(user, pid, 1, CHAPTER, "x", title="물고기의 결심")


def _gate(store: LocalStore, user: str, pid: str, number: int = 1) -> dict[str, list[str]]:
    result = check_chapter(store, user, pid, number)
    assert result is not None
    return {s: sorted(g.key for g in result.of(s)) for s in ("verified", "unverified", "unknown", "uncertain")}


def _names(store: LocalStore, floor: str, user: str = "alice") -> list[tuple[str, tuple[str, ...]]]:
    found = store.get_map(user, floor)
    assert found is not None
    return [("가운데" if n.center else f"연결 {n.name}" if n.link else n.name, n.books) for n in found.nodes]


def _node(store: LocalStore, floor: str, name: str, user: str = "alice") -> str:
    found = store.get_map(user, floor)
    return next(n.id for n in found.nodes if (n.name == name and not n.link) or (n.link and f"연결 {n.name}" == name))


# ---- 계산한 지도 -------------------------------------------------------------------------------

def test_new_users_have_no_kind_books(store: LocalStore):
    """#96: 새 사용자에게는 기본 책이 없다. 지도에는 가운데 노드(올린 문서 자리)만.
    2026-10-11: 「내 서재」도 자동으로 생기지 않는다(프로젝트 0개로 시작)."""
    assert store.list_floors("alice") == [] and store.get_map("alice", COMMON) is None
    _book(store)
    floors = store.list_floors("alice")
    assert [(f.label, f.id, f.common, f.builtins) for f in floors] == [("물에서 뭍으로", "book", False, ())]
    assert not (store.root / "users/alice/shelf/maps/common.json").exists()
    assert _names(store, "book") == [("가운데", ("ms.book",))]
    found = store.get_map("alice", "book")
    assert found.stored and store.cite_scope("alice", "book") == ("book",)
    layout = json.loads((store.root / "users/alice/shelf/floors.json").read_text(encoding="utf-8"))
    assert layout["schema_version"] == 2 and "builtins" not in layout  # 기본 카테고리가 없는 형식(#96)


def test_legacy_derived_maps_follow_the_old_layout(store: LocalStore):
    """옛 데이터(이전 전)는 이전 규칙대로 계산한 지도로 보인다: 이전(#96)이 이 모습을 책으로 바꾼다."""
    _book(store)
    _legacy(store)
    assert _names(store, "book") == [("가운데", ("ms.book",)), ("생각", ("ideas.book",)), ("문헌", ("refs.book",)),
                                     ("연결 문체", ("styles.common",))]
    found = store.get_map("alice", "book")
    link = found.nodes[3]
    assert link.link == (COMMON, _node(store, COMMON, "문체")) and link.link_title == "내 서재" and not link.missing
    assert set(found.edges) == {tuple(sorted((CENTER, n.id))) for n in found.nodes if not n.center}  # 새 노드는 가운데와 잇는다


def test_new_books_land_on_a_node_of_the_same_name(store: LocalStore):
    _book(store)
    c = store.create_category("alice", "인물", "person", "#2a7f86", ("시기",), "book")
    found = store.get_map("alice", "book")
    node = found.node_of(c.id)
    assert node.name == "인물" and not node.center and tuple(sorted((CENTER, node.id))) in found.edges
    mine = store.add_node("alice", "book", "사례")
    case = store.create_category("alice", "사례", "case", "#b8923a", (), "book")
    assert store.get_map("alice", "book").node_of(case.id).id == mine.id  # 이름이 같은 노드가 있으면 그 노드에


def test_project_limits_and_reserved_id(store: LocalStore):
    with pytest.raises(ValueError, match="내 서재"):
        store.create_project("alice", "x", project_id=COMMON)
    for n in range(MAX_FLOORS):
        store.create_project("alice", f"책 {n}", project_id=f"p{n}")
    with pytest.raises(ValueError, match=f"{MAX_FLOORS}개까지"):
        store.create_project("alice", "넘침", project_id="over")


# ---- 노드·선 --------------------------------------------------------------------------------

def test_node_edit_connect_trash_restore(store: LocalStore):
    _book(store)
    store.create_category("alice", "생각", "blank", "#1f2f5c", (), "book")
    city = store.add_node("alice", "book", "도시", x=200, y=-100, color="#B3261E")
    assert (city.x, city.y, city.color) == (200.0, -100.0, "#b3261e")
    with pytest.raises(MapError) as e:
        store.add_node("alice", "book", " 도시 ")
    assert e.value.code == "name_taken"
    with pytest.raises(MapError) as e:
        store.add_node("alice", "book", "")
    assert e.value.code == "bad_name"
    ideas = _node(store, "book", "생각")
    assert store.connect_nodes("alice", "book", city.id, ideas) and not store.connect_nodes("alice", "book", ideas, city.id)
    assert tuple(sorted((city.id, ideas))) in store.get_map("alice", "book").edges
    assert store.disconnect_nodes("alice", "book", city.id, CENTER) and not store.disconnect_nodes("alice", "book", city.id, CENTER)
    renamed = store.update_node("alice", "book", city.id, name="도시와 강", color="", x=10, y=20)
    assert (renamed.name, renamed.color, renamed.x) == ("도시와 강", None, 10.0)
    with pytest.raises(MapError) as e:
        store.update_node("alice", "book", CENTER, name="새 이름")
    assert e.value.code == "center_name"
    for code, node in (("center", CENTER), ("not_empty", ideas)):
        with pytest.raises(MapError) as e:
            store.trash_node("alice", "book", node, "x")
        assert e.value.code == code
    # 노드의 컨텍스트(#96): 지도 파일에 적히고, 휴지통·되살리기에도 함께 간다
    from magus.contexts import Context

    store.set_node_contexts("alice", "book", city.id, (Context("", "도시 현장 메모다."),))
    assert store.get_map("alice", "book").node(city.id).contexts == (Context("", "도시 현장 메모다."),)
    gone = store.trash_node("alice", "book", city.id, "안 씀")
    assert gone.name == "도시와 강" and store.get_map("alice", "book").node(city.id) is None
    assert all(city.id not in edge for edge in store.get_map("alice", "book").edges)
    [trashed] = [t for t in store.list_trash("alice") if t.kind == "node"]
    assert trashed.id == f"book/{city.id}" and trashed.note == "안 씀" and trashed.preview == "노드 「도시와 강」"
    assert store.restore_trash("alice", "node", trashed.id) == [f"book/{city.id}"]
    back = store.get_map("alice", "book")
    assert back.node(city.id).name == "도시와 강" and tuple(sorted((city.id, ideas))) in back.edges  # 이어졌던 선도 함께
    assert back.node(city.id).contexts[0].text == "도시 현장 메모다."


def test_node_and_book_limits(store: LocalStore):
    _book(store)
    for n in range(MAX_NODES - len(store.get_map("alice", "book").nodes)):
        store.add_node("alice", "book", f"노드 {n}")
    with pytest.raises(MapError) as e:
        store.add_node("alice", "book", "넘침")
    assert e.value.code == "nodes_full"
    target = _node(store, "book", "노드 0")
    for n in range(MAX_BOOKS_PER_NODE):
        c = store.create_category("alice", f"모음 {n}", "blank", "#2a7f86", (), "book")
        store.place_book("alice", "book", c.id, target)
    extra = store.create_category("alice", "하나 더", "blank", "#2a7f86", (), "book")
    with pytest.raises(MapError) as e:
        store.place_book("alice", "book", extra.id, target)
    assert e.value.code == "node_full"
    with pytest.raises(MapError) as e:
        store.place_book("alice", "book", "ms.book", target)
    assert e.value.code == "ms_center"


def test_link_nodes_point_to_the_original(store: LocalStore):
    _book(store)
    store.create_project("alice", "둘째", project_id="second")
    person = store.create_category("alice", "인물", "person", "#2a7f86", (), "book")
    source = store.get_map("alice", "book").node_of(person.id)
    link = store.add_link_node("alice", "second", "book", source.id)
    assert (link.name, link.link, link.link_title, link.books) == ("인물", ("book", source.id), "물에서 뭍으로", (person.id,))
    with pytest.raises(MapError) as e:
        store.add_link_node("alice", "second", "book", source.id)
    assert e.value.code == "link_exists"
    with pytest.raises(MapError) as e:
        store.add_link_node("alice", "book", "book", CENTER)
    assert e.value.code == "link_self"
    store.create_project("alice", "셋째", project_id="third")
    again = store.add_link_node("alice", "third", "second", link.id)  # 연결 노드를 고르면 그 원본으로
    assert again.link == ("book", source.id)
    store.place_book("alice", "book", person.id, CENTER)
    store.trash_node("alice", "book", source.id, "원본을 치움")
    shown = store.get_map("alice", "second").node(link.id)
    assert shown.missing and shown.name == "원본 없음" and shown.books == ()


# ---- 책 옮기기 -------------------------------------------------------------------------------

def test_move_books_between_nodes_and_projects(store: LocalStore):
    _book(store)
    store.create_project("alice", "둘째", project_id="second")
    shelf = store.add_node("alice", "book", "자료")
    b = store.create_category("alice", "사례", "case", "#b3261e", (), "book")
    store.put_category_item("alice", CategoryItem("x1", b.id, "엘알토", "me"))
    from_node = store.get_map("alice", "book").node_of(b.id).id
    move, lost = move_book(store, "alice", b.id, "book", shelf.id)  # 같은 프로젝트: 노드만
    assert lost == [] and (move.from_floor, move.to_floor, move.from_node, move.to_node) == ("book", "book", from_node, shelf.id)
    assert store.get_map("alice", "book").node_of(b.id).id == shelf.id and store.last_move("alice") == move
    with pytest.raises(MoveError) as e:
        move_book(store, "alice", b.id, "book", shelf.id)
    assert e.value.code == "same"
    undo_move(store, "alice", move.id)
    assert store.get_map("alice", "book").node_of(b.id).id == from_node
    # 다른 프로젝트로: 항목이 함께, 받는 지도에서는 이름이 같은 노드(없으면 새 노드). 되돌리면 원래 노드로
    move, _ = move_book(store, "alice", b.id, "second")
    assert store.get_category("alice", b.id).floor == "second" and store.get_category("alice", b.id).items == 1
    assert store.get_map("alice", "second").node_of(b.id).name == "사례"
    undo_move(store, "alice", move.id)
    assert store.get_category("alice", b.id).floor == "book" and store.get_map("alice", "book").node_of(b.id).id == from_node
    # 같은 이름의 카테고리가 받는 프로젝트에 있으면 옮기지 않는다. 원고 책은 옮기지 않는다
    store.create_category("alice", "사례", "case", "#b3261e", (), "second")
    for book, code in ((b.id, "clash"), ("ms.book", "fixed")):
        with pytest.raises(MoveError) as e:
            move_book(store, "alice", book, "second")
        assert e.value.code == code
    # 연결 노드로 옮기면 원본 노드로
    target = store.add_node("alice", "second", "받는 곳")
    link = store.add_link_node("alice", "book", "second", target.id)
    other = store.create_category("alice", "용어", "term", "#2a7f86", (), "book")
    move, _ = move_book(store, "alice", other.id, "book", link.id)
    assert (move.to_floor, move.to_node) == ("second", target.id) and store.get_category("alice", other.id).floor == "second"


def test_move_book_with_refs_takes_them_along(store: LocalStore):
    """#96: 문헌 글이 든 책을 다른 프로젝트로 옮기면 그 문헌도 그 프로젝트의 것이 되고, 되돌리면 돌아온다."""
    _book(store)
    store.create_project("alice", "둘째", project_id="second")
    import_bibliography(store, "alice", BIB, "book")
    book = store.source_book("alice", "book")
    assert book and store.get_category("alice", book).name == "참고문헌"
    move, lost = move_book(store, "alice", book, "second")
    assert lost == ["book"]  # 이 원고는 그 문헌을 더는 보지 않는다(알린다)
    assert {r.floor for r in store.list_refs("alice")} == {"second"}
    undo_move(store, "alice", move.id)
    assert {r.floor for r in store.list_refs("alice")} == {"book"} and _gate(store, "alice", "book")["unverified"] == ["clack2012", "daeschler2006"]


# ---- 인용 점검 -------------------------------------------------------------------------------

def test_cite_check_sees_own_and_linked_refs(store: LocalStore):
    _book(store)
    with_library(store, "alice")  # 「내 서재」가 있는 옛 사용자
    import_bibliography(store, "alice", BIB, "book")
    book = store.source_book("alice", "book")
    store.put_ref("alice", Ref("daeschler2006", "verified", store.get_ref("alice", "daeschler2006").bib))
    after_refs_changed(store, "alice")
    before = _gate(store, "alice", "book")
    assert before["verified"] == ["daeschler2006"] and before["unverified"] == ["clack2012"]
    outline_keys = [c.unverified_cite_keys for c in store.list_chapters("alice", "book")]
    # 문헌이 든 책을 「내 서재」로 옮기고 연결 노드로 이으면 확인 상태·집계가 그대로다(필수 시험)
    move, lost = move_book(store, "alice", book, COMMON)
    assert lost == ["book"]  # 연결 노드가 없으면 이 원고는 그 문헌을 더는 보지 않는다(알린다)
    assert _gate(store, "alice", "book")["unknown"] == ["clack2012", "daeschler2006"]
    assert store.ensure_link("alice", "book", COMMON, book) is not None
    after_refs_changed(store, "alice")
    assert store.cite_scope("alice", "book") == ("book", COMMON)
    assert _gate(store, "alice", "book") == before
    assert [c.unverified_cite_keys for c in store.list_chapters("alice", "book")] == outline_keys
    # 인용 점검이 쓰는 연결 노드는 휴지통으로 옮기지 않는다(2026-10-11, 문헌 글이 든 노드와 같다)
    link = next(n for n in store.get_map("alice", "book").nodes if n.link and book in n.books)
    assert store.node_trash_info("alice", "book", link.id).blocked == "cite_link"
    with pytest.raises(MapError) as refused:
        trash_node(store, "alice", "book", link.id, "x")
    assert refused.value.code == "cite_link" and "인용 점검이 이 문헌을 씁니다" in error_message(refused.value, polite=True)
    assert _gate(store, "alice", "book") == before
    undo_move(store, "alice", move.id)
    assert _gate(store, "alice", "book") == before


def test_shared_refs_stay_and_the_new_project_links_to_them(store: LocalStore):
    """2026-10-11: 다른 프로젝트의 문헌을 이 원고도 쓰게 되면 문헌은 제자리, 이 지도에 그 문헌 책의 노드로 가는 연결 노드(「내 서재」로 옮기지 않는다)."""
    _book(store)
    import_bibliography(store, "alice", BIB, "book")
    book_refs = store.source_book("alice", "book")
    store.create_project("alice", "둘째", project_id="second")
    store.write_chapter("alice", "second", 1, "다시 Clack(2012)을 본다.", "x", title="다시")
    report = import_bibliography(store, "alice", BIB.splitlines()[1] + "\nZimmer, C. (1998). At the water's edge. Free Press.", "second")
    assert report.shared == ["clack2012"] and report.created == ["zimmer1998"] and report.links == 1
    assert store.get_ref("alice", "clack2012").floor == "book" and store.get_ref("alice", "clack2012").book == book_refs
    assert store.get_ref("alice", "clack2012").moved is None and store.get_map("alice", COMMON) is None
    assert store.get_ref("alice", "zimmer1998").floor == "second" and store.get_ref("alice", "daeschler2006").floor == "book"
    assert store.cite_scope("alice", "second") == ("second", "book") and store.cite_scope("alice", "book") == ("book",)
    assert ("연결 참고문헌", (book_refs,)) in _names(store, "second")
    assert _gate(store, "alice", "book")["unverified"] == ["clack2012", "daeschler2006"]
    assert _gate(store, "alice", "second", 1)["unverified"] == ["clack2012"]
    assert ("- 다른 프로젝트에 있는 문헌 1편(이 올린 문서도 씀. 문헌은 그대로 두고 이 프로젝트 지도의 연결 노드로 봄, 연결 노드 1개를 새로 붙임): "
            "clack2012") in report.render()
    again = import_bibliography(store, "alice", BIB.splitlines()[1], "second")  # 이미 보는 문헌: 연결 노드를 또 붙이지 않는다
    assert again.shared == ["clack2012"] and again.links == 0


# ---- 이전 ---------------------------------------------------------------------------------

def _legacy(store: LocalStore, user: str = "alice", refs: bool = True, extra: bool = False) -> None:
    """#96 전·층 전(옛 구조) 책장 파일을 만든다: 생각·문체 파일, 책이 없는 문헌, 층이 없는 저자의 카테고리.
    floors.json·지도·이 시험이 만든 책(새 형식)은 지운 뒤 다시 색인한다."""
    root = store.root / "users" / user / "shelf"

    def write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    if refs:
        import_bibliography(store, user, BIB, "book")
    for bib in root.glob("melchior/*/bib.json"):
        data = json.loads(bib.read_text(encoding="utf-8"))
        write(bib, {k: v for k, v in data.items() if k not in ("floor", "book")})
    for cat in list(root.glob("categories/*/category.json")):
        shutil.rmtree(cat.parent)
    write(root / "casper" / "i1.json", {"id": "i1", "text": "생각", "kind": "thought", "author": "me", "origin": None,
                                        "parent_id": None, "created_at": T0, "title": "첫 생각", "title_by": "author"})
    write(root / "casper" / "i2.json", {"id": "i2", "text": "그 답", "kind": "conversation", "author": "ai", "origin": "대화",
                                        "parent_id": "i1", "created_at": "2026-10-01T00:00:01.000Z"})
    write(root / "balthasar" / "s1.json", {"id": "s1", "passage": "구절", "reason": "이유", "tags": TAGS, "work": "출전",
                                           "created_at": T0, "tags_by": "ai"})
    write(root / "categories" / "c1" / "category.json", {"schema_version": 1, "id": "c1", "name": "인물", "template": "person",
                                                         "color": "#2a7f86", "fields": ["원어 표기"], "created_at": T0, "updated_at": T0})
    write(root / "categories" / "c1" / "items" / "p1.json", {"schema_version": 1, "id": "p1", "title": None, "title_by": None,
                                                             "content": "애덤 스미스", "fields": {}, "author": "me", "tags": [],
                                                             "chapters": [], "created_at": T0, "updated_at": T0})
    if extra:  # 휴지통의 생각(#88)과 컨텍스트가 없는 문서 책(#94)
        write(store.root / "users" / user / "trash" / "shelf" / "casper" / "i3.json",
              {"id": "i3", "text": "버린 생각", "kind": "thought", "author": "me", "origin": None, "parent_id": None,
               "created_at": T0, "_trash": {"at": T0, "note": "안 씀"}})
        write(root / "documents" / "d1" / "document.json",
              {"schema_version": 1, "id": "d1", "title": "출처 확인", "title_by": "author", "doc_type": "source_check",
               "project_id": "book", "floor": "book", "color": "#7a4b2a", "created_at": T0, "updated_at": T0,
               "versions": [{"number": 1, "at": T0, "edition": None, "method": "server", "preface_by": None, "stats": {}}]})
        (root / "documents" / "d1" / "v1.md").write_text("# 출처 확인\n", encoding="utf-8")
    (root / "floors.json").unlink(missing_ok=True)
    shutil.rmtree(root / "maps", ignore_errors=True)
    store.reindex()


def _files(store: LocalStore, user: str) -> dict:
    """이전 결과 비교용: 지도·층 배치·책·글·문헌·프로젝트 컨텍스트(시각 칸은 뺀다)."""
    shelf = store.root / "users" / user / "shelf"
    out = {}
    for path in sorted([*shelf.glob("maps/*.json"), shelf / "floors.json", *shelf.glob("categories/*/category.json"),
                        *shelf.glob("categories/*/items/*.json"), *shelf.glob("melchior/*/bib.json"),
                        *shelf.glob("documents/*/document.json"),
                        *(store.root / "users" / user / "trash" / "shelf").glob("category-items/*/*.json"),
                        *(store.root / "users" / user / "projects").glob("*/project.json")]):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("updated_at", "changed_at"):
            data.pop(key, None)
        out[path.relative_to(store.root).as_posix()] = data
    return out


def _maps(store: LocalStore, user: str) -> dict:
    out = {}
    for path in sorted((store.root / "users" / user / "shelf" / "maps").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("updated_at")
        out[path.name] = data
    return out


def test_migration_plan_apply_revert_from_both_layouts(store: LocalStore, tmp_path: Path):
    """이전(#95 지도 + #96 책): 층 전 데이터에서 바로 apply한 결과와, 층·지도를 먼저 적은(#95) 데이터에서 apply한 결과가 같다.
    전후로 글 수·장별 인용 점검·전체 현황 수·확인 요청 수·수정본 이력이 같고, revert 뒤 다시 apply해도 같다."""
    _book(store)
    store.create_project("alice", "둘째", project_id="second")
    store.write_chapter("alice", "second", 1, "다시 Clack(2012)을 본다.", "x", title="다시")
    _legacy(store, extra=True)
    after_refs_changed(store, "alice")
    # 이전 전에도 이전 규칙과 같은 모습: 작업물이 둘이면 문헌은 「내 서재」, 두 지도에 연결 노드
    assert store.get_ref("alice", "clack2012").floor == COMMON
    assert ("연결 문헌", ("refs.common",)) in _names(store, "second")
    plan = "\n".join(map_migrate.plan(store, "alice"))
    assert "사용자 alice: 이전 전(층 배치 파일 없음)" in plan and "옛 규칙(그 층 + 공용)으로 낸 인용 점검과: 같음" in plan
    assert "- 프로젝트 내 서재 · 노드 4 · 선 3" in plan and "연결 「문헌」(내 서재): 문헌 2(확인 0)" in plan
    assert "글: 생각 2 · 문체 1 · 문헌 2(확인 0) · 저자의 책(옛 카테고리) 1(글 1)" in plan
    assert not (store.root / "users/alice/shelf/maps").exists()  # 미리보기는 쓰지 않는다
    lines, same = map_migrate.apply(store, "alice", tmp_path / "backup")
    assert same and "전후 비교: 같음(항목 수·장별 인용 점검·전체 현황 수)" in lines, "\n".join(lines)
    assert ("책 이전(#96): 책 「문체」 1 · 책 「문헌」 3 · 책 「생각」 2 · 생각 → 글 2 · 문체 → 글 1 · 문헌에 책 적음 2 · 휴지통 글 1 · "
            "지도 3 · 원고 컨텍스트 2 · 문서 컨텍스트 1") in lines, lines  # 옛 배치: 「내 서재」에 문체·문헌, 두 프로젝트마다 생각·문헌
    first = _files(store, "alice")
    # 옛 기본 책 → 이름이 같은 책 + 컨텍스트, 생각·문체 → 그 책의 글, 문헌 → 책을 적음, 원고 → 「원고」
    ideas = store.get_category("alice", "ideas-book")
    assert (ideas.name, ideas.items, [c.name for c in ideas.contexts]) == ("생각", 2, ["생각 메모"])
    [i1, i2] = store.list_category_items("alice", "ideas-book")
    assert (i1.title, i1.title_by, i2.author, i2.parent_id, i2.origin, i2.kind) == ("첫 생각", "author", "ai", "i1", "대화", "conversation")
    [s1] = store.list_category_items("alice", "styles-common")
    assert (s1.content, s1.reason, s1.where, s1.tags_by) == ("구절", "이유", "출전", "ai") and "호흡: 짧음" in s1.tags
    assert [c.name for c in store.get_category("alice", "styles-common").contexts] == ["문체"]
    assert store.get_ref("alice", "clack2012").book == "refs-common" and store.get_category("alice", "refs-common").sources == 2
    assert [c.name for c in store.get_project("alice", "book").contexts] == ["원고"]
    assert store.get_category("alice", "c1").contexts == ()  # 저자의 카테고리는 컨텍스트 없이
    assert [c.name for c in store.get_document("alice", "d1").contexts] == ["출처 확인 문서"]  # 문서 책 → 「출처 확인 문서」
    [gone] = [t for t in store.list_trash("alice") if t.kind == "category_item"]  # 휴지통의 생각 → 그 책의 휴지통 글
    assert (gone.id, gone.note) == ("ideas-book/i3", "안 씀")
    assert not list((store.root / "users/alice/shelf/casper").glob("*.json"))
    assert map_migrate.state(store, "alice") == "책·컨텍스트까지 바꿈(#96)"
    # 되돌리기 → 층 전 형식. 그다음 층·지도를 먼저 적은(#95) 상태에서 apply해도 같은 결과
    reverted = map_migrate.revert(store, "alice")
    assert "maps 1" in reverted[0] and "floors.json 1" in reverted[0] and "글 → 생각 2 · 휴지통 글 되돌림 1 · 책 「생각」 비켜 둠 2" in reverted[0]
    old = json.loads((store.root / "users/alice/shelf/casper/i2.json").read_text(encoding="utf-8"))
    assert "floor" not in old and (old["author"], old["parent_id"], old["kind"]) == ("ai", "i1", "conversation")
    assert (store.root / "users/alice/trash/shelf/casper/i3.json").exists()
    style = json.loads((store.root / "users/alice/shelf/balthasar/s1.json").read_text(encoding="utf-8"))
    assert style["tags"]["호흡"] == "짧음" and style["work"] == "출전"
    assert "book" not in json.loads((store.root / "users/alice/shelf/melchior/clack2012/bib.json").read_text(encoding="utf-8"))
    assert list((store.root / "users/alice/shelf").glob("maps.reverted-*"))
    assert list((store.root / "users/alice/shelf").glob("categories.reverted-*"))
    store.reindex()
    store.ensure_maps("alice")  # #95까지(층 배치·지도)를 먼저 적는다
    assert json.loads((store.root / "users/alice/shelf/floors.json").read_text(encoding="utf-8"))["schema_version"] == 1
    store.reindex()
    lines, same = map_migrate.apply(store, "alice", tmp_path / "backup2")
    assert same and _files(store, "alice") == first


def test_josa():
    assert josa("「생각」", "을/를") == "「생각」을" and josa("「문체」", "을/를") == "「문체」를"
    assert josa("내 서재", "으로/로") == "내 서재로" and josa("서울", "으로/로") == "서울로" and josa("집", "으로/로") == "집으로"
    assert josa("Rome", "을/를") == "Rome을(를)"


# ---- 도구 ----------------------------------------------------------------------------------

async def test_tools_project_args_and_map(settings: Settings, store: LocalStore):
    _book(store)
    async with Client(build_server(settings, store)) as c:
        created = _text(await c.call_tool("category_create", {"name": "생각", "context": ["생각 메모"]}))
        assert "「물에서 뭍으로」 · 노드 「생각」에 꽂혔다." in created  # 프로젝트가 하나면 그것
        made = _text(await c.call_tool("book_import", {"title": "도시의 시간"}))
        assert made.startswith("올린 문서가 없는 프로젝트를 만듦: 「도시의 시간」(") and "지도에 가운데 노드가 있다" in made
        second = next(f.id for f in store.list_floors("alice") if f.title == "도시의 시간")
        ask = await c.call_tool("category_create", {"name": "어디"})
        assert ask.is_error and "프로젝트가 2개라 어디에 넣을지 모른다" in _text(ask) and "저자에게 묻는다" in _text(ask)
        await c.call_tool("category_create", {"name": "생각", "project": "도시의 시간"})
        same_name = await c.call_tool("category_put", {"book": "생각", "author": "me", "content": "도시 메모", "untitled": True})
        assert same_name.is_error and "「생각」 책이 여러 프로젝트에 있다" in _text(same_name)
        put = _text(await c.call_tool("category_put", {"book": "생각", "author": "me", "content": "도시 메모", "untitled": True,
                                                        "project": "도시의 시간"}))
        assert put.startswith("컨텍스트: 없음(일반 메모로 다룬다) — 책 「생각」") and "넣음: 「생각」" in put
        # 노드·연결 노드·선
        node = _text(await c.call_tool("category_create", {"name": "골목", "template": "노드", "project": "도시의 시간"}))
        assert node.endswith("노드를 만듦: 「골목」(「도시의 시간」 지도, 가운데 노드와 이음).")
        refused = await c.call_tool("category_create", {"name": "물에서 뭍으로 · 생각", "template": "연결 노드", "project": "도시의 시간"})
        assert refused.is_error  # 대화로는 연결 노드를 만들지 않는다(2026-10-11). 이미 있는 연결 노드는 그대로 동작한다
        from magus.category.moves import add_link  # noqa: PLC0415

        add_link(store, "alice", second, "book", next(n.id for n in store.get_map("alice", "book").nodes if n.name == "생각"))
        joined = _text(await c.call_tool("category_edit", {"node": "골목", "project": "도시의 시간", "link": "가운데"}))
        assert joined == "「도시의 시간」 지도: 이미 이어져 있음 「골목」–「가운데」."
        cut = _text(await c.call_tool("category_edit", {"node": "골목", "project": "도시의 시간", "unlink": "가운데",
                                                        "new_name": "골목길"}))
        assert cut == "「도시의 시간」 지도: 노드 「골목」 → 「골목길」 · 선 끊음 「골목」–「가운데」."
        # 책을 노드에 만들고, 다른 노드·다른 프로젝트로 옮긴다
        created = _text(await c.call_tool("category_create", {"name": "인물", "template": "인물", "project": "도시의 시간", "node": "골목길"}))
        assert created.endswith("「도시의 시간」 · 노드 「골목길」에 꽂혔다.")
        moved = _text(await c.call_tool("category_edit", {"book": "인물", "move_to": "생각"}))
        assert moved.startswith("책 「인물」을 고침: 옮김: 「인물」 「도시의 시간」 · 노드 「골목길」 → 노드 「생각」.")
        across = _text(await c.call_tool("category_edit", {"book": "인물", "move_to": "물에서 뭍으로"}))
        assert "옮김: 「인물」 「도시의 시간」 · 노드 「생각」 → 「물에서 뭍으로」 · 노드 「인물」(글 모두 함께)" in across
        assert "undo_move=true" in across
        undone = _text(await c.call_tool("category_edit", {"book": "인물", "undo_move": True}))
        assert undone == "되돌림: 「인물」 → 「도시의 시간」 · 노드 「생각」(옮기기 전 자리)."
        # 지도 보기·전체 현황: 컨텍스트는 이름만([ ])
        listed = _text(await c.call_tool("category_list", {}))
        assert listed.startswith("책장: 프로젝트 2개(「물에서 뭍으로」(book) · 「도시의 시간」(")  # 「내 서재」는 자동으로 없다(2026-10-11)
        assert f"## 「도시의 시간」({second}) · 올린 문서 없음 · 노드 4 · 선 2" in listed
        assert "- 「골목길」: 책 없음" in listed and "- 연결 「생각」(물에서 뭍으로): 「생각」 0[생각 메모]" in listed
        assert "- 「생각」: 「생각」 1 · 「인물」 0 (인물 칸: 원어 표기, 생몰, 소속·국적)" in listed
        outline = _text(await c.call_tool("book_outline", {"project_id": "book"}))
        assert "지도(노드 2 · 선 1): 가운데: 「물에서 뭍으로」 올린 문서 1장 · 「생각」: 「생각」 0[생각 메모]" in outline
        # 찾기: 프로젝트를 주면 그 프로젝트(와 연결 노드가 가리키는 프로젝트)만
        assert "결과 없음" in _text(await c.call_tool("category_search", {"query": "도시 메모", "project": "물에서 뭍으로"}))
        assert "도시 메모" in _text(await c.call_tool("category_search", {"query": "도시 메모", "project": "도시의 시간"}))
        # 노드 휴지통: 책이 있으면 막고, 비면 옮긴다
        busy = await c.call_tool("category_trash", {"node": "생각", "project": "도시의 시간", "note": "x"})
        assert busy.is_error and "책이 꽂힌 노드는 휴지통으로 옮기지 않는다" in _text(busy)
        gone = _text(await c.call_tool("category_trash", {"node": "골목길", "project": "도시의 시간", "note": "안 씀"}))
        assert gone.startswith("휴지통으로 옮김: 「도시의 시간」 지도의 노드 「골목길」.")


async def test_put_asks_with_book_names_and_contexts(settings: Settings, store: LocalStore):
    """넣을 책을 모르면 책 이름과 컨텍스트 이름을 보여 주며 묻게 한다(instructions 규칙: 넣을 곳 묻기)."""
    _book(store)
    make_book_ = store.create_category
    from magus.contexts import Context

    make_book_("alice", "문체", "blank", "#6e1f2f", (), "book", contexts=(Context("문체", "문학적 부분…"),))
    make_book_("alice", "메모", "blank", "#1f2f5c", (), "book")
    async with Client(build_server(settings, store)) as c:
        ask = await c.call_tool("category_put", {"book": "생각", "author": "me", "content": "어디?", "untitled": True})
        assert ask.is_error and "'생각' 책이 없다. 저자에게 어느 책인지 묻는다. 책: 「문체」[문체] · 「메모」" in _text(ask)


async def test_import_into_project_without_manuscript(settings: Settings, store: LocalStore, tmp_path: Path):
    store.create_project("alice", "원고 없는 프로젝트", project_id="later")
    c = store.create_category("alice", "인물", "person", "#2a7f86", (), "later")
    path = build_manuscript_docx(tmp_path / "닿으려는_종_합성.docx")
    store.put_inbox("alice", path.name, path.read_bytes())
    async with Client(build_server(settings, store)) as client:
        report = await client.call_tool("book_import", {"path": path.name, "project_id": "later"})
        assert not report.is_error, _text(report)
    assert store.get_project("alice", "later").title == "원고 없는 프로젝트" and store.list_chapters("alice", "later")
    found = store.get_map("alice", "later")
    assert found.nodes[0].books[0] == "ms.later" and found.node_of(c.id).name == "인물"  # 원고 책은 가운데 노드에


def test_isolation(store: LocalStore):
    _book(store, "alice")
    _book(store, "bob")
    c = store.create_category("alice", "인물", "person", "#2a7f86", (), "book")
    with_library(store, "alice")
    with_library(store, "bob")
    with pytest.raises(MoveError):
        move_book(store, "bob", c.id, COMMON)  # bob의 책장에는 없는 카테고리
    move, _ = move_book(store, "alice", c.id, COMMON)
    with pytest.raises(MoveError):
        undo_move(store, "bob", move.id)
    node = store.add_node("alice", "book", "앨리스의 노드")
    with pytest.raises(MapError):
        store.update_node("bob", "book", node.id, name="밥이 바꿈")
    with pytest.raises(MapError):
        store.trash_node("bob", "book", node.id, "x")
    assert store.get_map("bob", "book").node(node.id) is None and store.list_categories("bob") == []
    assert store.get_map("alice", "book").node(node.id).name == "앨리스의 노드"


async def test_ref_add_tells_when_it_links_another_projects_source(settings: Settings, store: LocalStore):
    _book(store)
    import_bibliography(store, "alice", BIB, "book")
    store.create_project("alice", "둘째", project_id="second")
    store.create_category("alice", "읽은 것", "blank", "#1f2f5c", (), "second")
    async with Client(build_server(settings, store)) as c:
        added = _text(await c.call_tool("category_put", {"book": "읽은 것", "author": "me", "source": {"key": "clack2012"}, "checked": True,
                                                          "parts": [{"text": "네발동물의 기원", "reason": "둘째 1장의 근거"}]}))
        assert ("책 「참고문헌」(「물에서 뭍으로」) · 다른 프로젝트 「물에서 뭍으로」에 있는 문헌이라 그대로 두고, 이 프로젝트 지도에 "
                "그 노드로 가는 연결 노드를 붙임(저자에게 알린다)") in added
        again = _text(await c.call_tool("category_put", {"book": "읽은 것", "author": "me", "source": {"key": "clack2012"}, "checked": True,
                                                          "parts": [{"text": "더 고른 문장", "reason": "보탬"}]}))
        assert "연결 노드를 붙임" not in again and "옮김" not in again  # 이미 두 원고가 보면 다시 붙이지 않는다


def test_passage_ref_keeps_floor(store: LocalStore):
    _book(store)
    with_library(store, "alice")
    store.put_ref("alice", Ref("kremer1993", "unverified", {"title": "Population growth"}, floor=COMMON))
    stored = store.put_ref("alice", Ref("kremer1993", "verified", {"title": "Population growth"}), [Passage("인구", "이유")])
    assert stored.floor == COMMON  # 고칠 때 프로젝트를 주지 않으면 그대로
