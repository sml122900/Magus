"""층(#93): 공용 층 + 작업물마다 한 층. 카테고리(기본 카테고리 포함)는 층에 꽂히고 층 사이를 옮긴다.

- 배치: 새 작업물 층에는 생각·문헌, 문체는 공용. 빈 층(원고 없음)과 그 층으로 원고 가져오기.
- 옮기기: 저자의 카테고리(같은 이름이면 막음), 기본 카테고리(받는 층에 있으면 합침), 마지막 옮기기 되돌리기.
- 인용 점검: 작업물 원고는 그 층 문헌 + 공용 문헌만 본다. 문헌을 공용으로 옮겨도 결과가 같다(필수 시험).
  두 작업물이 같은 문헌을 쓰게 되면 그 문헌은 공용으로 간다.
- 이전: 옛 구조(층 없음)는 이전 규칙과 같은 배치로 보이고, apply 전후로 항목 수·인용 점검이 같다. revert는 "floor"를 뗀다.
- 도구: floor 인자, 작업물이 여럿인데 층을 말하지 않으면 묻게 한다, category_edit move_to·undo_move, 빈 층 book_import.
- 격리: 다른 사용자의 층·카테고리를 옮길 수 없고 보이지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from magus import floor_migrate
from magus.config import Settings
from magus.floors import COMMON, MAX_FLOORS, josa
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import after_refs_changed, check_chapter
from magus.server import build_server
from magus.store import CategoryItem, Idea, LocalStore, Passage, Ref, StyleEntry
from magus.store.floors import MoveError
from magus.synthetic import build_manuscript_docx

pytestmark = pytest.mark.anyio

CHAPTER = "물고기는 뭍으로 올라왔다(Daeschler, Shubin & Jenkins, 2006). 그 뒤의 일은 Clack(2012)이 정리했다."
BIB = ("Daeschler, E. B., Shubin, N. H., & Jenkins, F. A. (2006). A Devonian tetrapod-like fish. Nature, 440, 757–763.\n"
       "Clack, J. A. (2012). Gaining ground. Indiana University Press.")


def _text(result) -> str:
    return "\n".join(block.text for block in result.content)


def _book(store: LocalStore, user: str = "alice", pid: str = "book", title: str = "물에서 뭍으로") -> None:
    store.create_project(user, title, project_id=pid)
    store.write_chapter(user, pid, 1, CHAPTER, "x", title="물고기의 결심")


def _gate(store: LocalStore, user: str, pid: str, number: int = 1) -> dict[str, list[str]]:
    result = check_chapter(store, user, pid, number)
    assert result is not None
    return {s: sorted(g.key for g in result.of(s)) for s in ("verified", "unverified", "unknown", "uncertain")}


# ---- 배치 ----------------------------------------------------------------------------------

def test_new_floors_get_ideas_and_refs_styles_stay_common(store: LocalStore):
    assert [(f.id, f.builtins) for f in store.list_floors("alice")] == [(COMMON, ("ideas", "styles", "refs"))]  # 작업물 없음: 모두 공용
    _book(store)
    floors = store.list_floors("alice")
    assert [(f.label, f.id, f.builtins, f.has_manuscript) for f in floors] == [
        ("공용", COMMON, ("styles",), False), ("1층", "book", ("ideas", "refs"), True)]  # 비어 있던 공용 생각·문헌은 1층으로
    store.create_project("alice", "두 번째 책", project_id="second")
    assert [f.label for f in store.list_floors("alice")] == ["공용", "1층", "2층"]
    [idea] = store.add_ideas("alice", [Idea("i1", "물가의 망설임", "thought", "me")])
    assert idea.floor == "book"  # 층을 주지 않으면 위에서부터 생각이 꽂힌 첫 층
    assert store.add_style("alice", StyleEntry("s1", "구절", "이유", {})).floor == COMMON
    assert json.loads((store.root / "users/alice/shelf/casper/i1.json").read_text(encoding="utf-8"))["floor"] == "book"
    assert store.place("alice", "styles", "second") == COMMON  # 그 층에 문체가 없으면 공용의 문체
    assert store.place("alice", "ideas", "second") == "second"


def test_floor_limits_and_reserved_id(store: LocalStore):
    with pytest.raises(ValueError, match="공용 층"):
        store.create_project("alice", "x", project_id=COMMON)
    for n in range(MAX_FLOORS):
        store.create_project("alice", f"책 {n}", project_id=f"p{n}")
    with pytest.raises(ValueError, match=f"{MAX_FLOORS}개까지"):
        store.create_project("alice", "넘침", project_id="over")


def test_updated_at_per_floor(store: LocalStore):
    _book(store)
    before = store.get_floor("alice", COMMON).updated_at
    store.add_style("alice", StyleEntry("s1", "구절", "이유", {}))
    assert store.get_floor("alice", COMMON).updated_at > before
    c = store.create_category("alice", "인물", "person", "#2a7f86", ("시기",), "book")
    assert store.get_floor("alice", "book").updated_at >= c.updated_at
    assert store.category_updated("alice", c.id) == c.updated_at
    assert store.builtin_updated("alice", "styles", COMMON) != ""


def test_reindex_keeps_floors(store: LocalStore):
    _book(store)
    c = store.create_category("alice", "인물", "person", "#2a7f86", (), "book")
    store.add_ideas("alice", [Idea("i1", "생각", "thought", "me", floor=COMMON)])  # 공용에는 생각이 없지만 파일의 층대로
    store.reindex()
    assert store.get_category("alice", c.id).floor == "book"
    assert store.get_ideas("alice", ["i1"])["i1"].floor == COMMON


# ---- 옮기기 ---------------------------------------------------------------------------------

def test_move_category_clash_and_undo(store: LocalStore):
    _book(store)
    a = store.create_category("alice", "인물", "person", "#2a7f86", (), "book")
    store.create_category("alice", "인물", "person", "#2a7f86", (), COMMON)  # 이름은 층마다 하나: 다른 층에는 같은 이름이 있어도 된다
    with pytest.raises(MoveError) as e:
        store.move_category("alice", a.id, COMMON)
    assert e.value.code == "clash" and e.value.info["floor"] == "공용"
    with pytest.raises(MoveError) as e:
        store.move_category("alice", a.id, "book")
    assert e.value.code == "same"
    b = store.create_category("alice", "사례", "case", "#b3261e", (), "book")
    store.put_category_item("alice", CategoryItem("x1", b.id, "엘알토", "me"))
    move = store.move_category("alice", b.id, COMMON)
    assert store.get_category("alice", b.id).floor == COMMON and store.get_category("alice", b.id).items == 1
    assert store.last_move("alice") == move
    with pytest.raises(MoveError) as e:
        store.undo_move("alice", "다른 id")
    assert e.value.code == "not_last"
    store.undo_move("alice", move.id)
    assert store.get_category("alice", b.id).floor == "book" and store.last_move("alice") is None
    with pytest.raises(MoveError):
        store.undo_move("alice", move.id)  # 한 번만


def test_move_builtin_merge_and_undo(store: LocalStore):
    _book(store)
    store.create_project("alice", "둘째", project_id="second")
    store.add_ideas("alice", [Idea("a1", "1층 생각", "thought", "me", floor="book"),
                              Idea("a2", "그 답", "ai", "ai", parent_id="a1", floor="book"),
                              Idea("b1", "2층 생각", "thought", "me", floor="second")])
    move = store.move_builtin("alice", "ideas", "book", COMMON)  # 공용에 생각이 없다: 새로 꽂힌다
    assert not move.merged and set(move.items) == {"a1", "a2"}
    assert {f.id: f.builtins for f in store.list_floors("alice")}[COMMON] == ("ideas", "styles")
    assert "ideas" not in store.get_floor("alice", "book").builtins
    assert store.place("alice", "ideas", "book") == COMMON  # 1층에 생각이 없으니 공용의 생각에 들어간다
    merged = store.move_builtin("alice", "ideas", "second", COMMON)  # 공용에 생각이 있다: 합친다
    assert merged.merged and merged.items == ("b1",)
    assert sorted(i.id for i in store.list_ideas("alice", floors=[COMMON])) == ["a1", "a2", "b1"]
    store.undo_move("alice", merged.id)
    assert [i.id for i in store.list_ideas("alice", floors=["second"])] == ["b1"]
    assert "ideas" in store.get_floor("alice", COMMON).builtins  # 합친 쪽은 그대로
    with pytest.raises(MoveError) as e:
        store.move_builtin("alice", "ideas", "book", COMMON)
    assert e.value.code == "no_builtin"


# ---- 인용 점검 -------------------------------------------------------------------------------

def test_cite_check_sees_floor_and_common_only(store: LocalStore):
    _book(store)
    import_bibliography(store, "alice", BIB, "book")
    store.put_ref("alice", Ref("daeschler2006", "verified", store.get_ref("alice", "daeschler2006").bib))
    after_refs_changed(store, "alice")
    before = _gate(store, "alice", "book")
    assert before["verified"] == ["daeschler2006"] and before["unverified"] == ["clack2012"]
    outline_keys = [c.unverified_cite_keys for c in store.list_chapters("alice", "book")]
    # 문헌을 공용으로 옮겨도 확인 상태·집계가 바뀌지 않는다(필수 시험)
    move = store.move_builtin("alice", "refs", "book", COMMON)
    after_refs_changed(store, "alice")
    assert _gate(store, "alice", "book") == before
    assert [c.unverified_cite_keys for c in store.list_chapters("alice", "book")] == outline_keys
    assert store.get_ref("alice", "daeschler2006").status == "verified"
    store.undo_move("alice", move.id)
    # 다른 작업물 층으로 옮기면 1층 원고는 그 문헌을 보지 않는다(참고문헌에 없음)
    store.create_project("alice", "둘째", project_id="second")
    store.move_builtin("alice", "refs", "book", "second")
    after_refs_changed(store, "alice")
    assert _gate(store, "alice", "book")["unknown"] == ["clack2012", "daeschler2006"]


def test_shared_refs_move_to_common(store: LocalStore):
    _book(store)
    import_bibliography(store, "alice", BIB, "book")
    store.create_project("alice", "둘째", project_id="second")
    store.write_chapter("alice", "second", 1, "다시 Clack(2012)을 본다.", "x", title="다시")
    report = import_bibliography(store, "alice", BIB.splitlines()[1] + "\nZimmer, C. (1998). At the water's edge. Free Press.", "second")
    assert report.shared == ["clack2012"] and report.created == ["zimmer1998"]
    assert store.get_ref("alice", "clack2012").floor == COMMON and store.get_ref("alice", "zimmer1998").floor == "second"
    assert store.get_ref("alice", "daeschler2006").floor == "book"
    assert "refs" in store.get_floor("alice", COMMON).builtins  # 공용에 문헌이 새로 꽂혔다
    assert _gate(store, "alice", "book")["unverified"] == ["clack2012", "daeschler2006"]  # 1층은 그대로 본다
    assert _gate(store, "alice", "second", 1)["unverified"] == ["clack2012"]
    # 저자 모르게 배치가 바뀌지 않게(#93-a 더함): 리포트 한 줄 + 문헌 항목에 옮긴 시각·원래 층·이유
    assert "- 공용으로 옮긴 문헌 1편(다른 작업물의 원고도 쓰는 문헌. 각 문헌에 옮긴 시각과 이유를 남김): clack2012" in report.render()
    moved = store.get_ref("alice", "clack2012").moved
    assert moved and moved["from"] == "book" and moved["to"] == COMMON and moved["at"]
    assert moved["reason"] == "1층 「물에서 뭍으로」·2층 「둘째」 원고가 함께 쓰는 문헌이라 공용으로 옮김"
    from magus.melchior.refs import add_alias  # noqa: PLC0415

    add_alias(store, "alice", "clack2012", "클랙(2012)")  # 문헌을 고쳐도(put_ref) 기록은 그대로
    store.reindex()  # 원본은 bib.json
    assert store.get_ref("alice", "clack2012").moved == moved
    bib = json.loads((store.root / "users/alice/shelf/melchior/clack2012/bib.json").read_text(encoding="utf-8"))
    assert bib["moved"] == moved and bib["floor"] == COMMON


# ---- 이전 ---------------------------------------------------------------------------------

def _strip_floors(store: LocalStore, user: str) -> None:
    """옛 구조로 만든다: 항목 파일에서 "floor"를 떼고 floors.json을 지운 뒤 다시 색인."""
    root = store.root / "users" / user / "shelf"
    for path in [*root.glob("casper/*.json"), *root.glob("balthasar/*.json"), *root.glob("melchior/*/bib.json"),
                 *root.glob("categories/*/category.json")]:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("floor", None)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (root / "floors.json").unlink()
    store.reindex()


def test_migration_plan_apply_revert(store: LocalStore, tmp_path: Path):
    _book(store)
    import_bibliography(store, "alice", BIB, "book")
    store.add_ideas("alice", [Idea("i1", "생각", "thought", "me")])
    store.add_style("alice", StyleEntry("s1", "구절", "이유", {}))
    store.create_category("alice", "인물", "person", "#2a7f86", ())
    _strip_floors(store, "alice")
    # 이전 전에도 이전 규칙과 같은 배치로 보인다
    assert store.get_ideas("alice", ["i1"])["i1"].floor == "book" and store.get_ref("alice", "clack2012").floor == "book"
    assert store.list_styles("alice")[0].floor == COMMON and store.list_categories("alice")[0].floor == COMMON
    plan = "\n".join(floor_migrate.plan(store, "alice"))
    assert "이전 전" in plan and "- 생각: 1층 1개 (새로 적음)" in plan and "- 문헌: 1층 2개 (새로 적음)" in plan
    assert "카테고리 「인물」 → 공용" in plan
    assert not (store.root / "users/alice/shelf/floors.json").exists()  # 미리보기는 쓰지 않는다
    lines, same = floor_migrate.apply(store, "alice", tmp_path / "backup")
    assert same and any(line.startswith("백업: ") for line in lines)
    assert next((tmp_path / "backup").glob("alice-shelf-*/casper/i1.json")).exists()
    assert json.loads((store.root / "users/alice/shelf/casper/i1.json").read_text(encoding="utf-8"))["floor"] == "book"
    reverted = floor_migrate.revert(store, "alice")
    assert "floors.json 1" in reverted[0]
    assert "floor" not in json.loads((store.root / "users/alice/shelf/casper/i1.json").read_text(encoding="utf-8"))
    assert list((store.root / "users/alice/shelf").glob("floors.json.reverted-*"))


def test_josa():
    assert josa("「생각」", "을/를") == "「생각」을" and josa("「문체」", "을/를") == "「문체」를"
    assert josa("공용", "으로/로") == "공용으로" and josa("1층", "으로/로") == "1층으로" and josa("서울", "으로/로") == "서울로"
    assert josa("Rome", "을/를") == "Rome을(를)"


# ---- 도구 ----------------------------------------------------------------------------------

async def test_tools_floor_args(settings: Settings, store: LocalStore):
    _book(store)
    async with Client(build_server(settings, store)) as c:
        one = _text(await c.call_tool("idea_add", {"text": "작업물이 하나", "kind": "thought", "untitled": True}))
        assert "1층 「물에서 뭍으로」의 생각" in one
        empty = _text(await c.call_tool("book_import", {"title": "도시의 시간"}))
        assert empty.startswith("빈 층을 만듦: 2층 「도시의 시간」(") and "생각·문헌이 꽂혀 있다" in empty
        second = store.list_floors("alice")[2].id
        ask = await c.call_tool("idea_add", {"text": "어느 층?", "kind": "thought", "untitled": True})
        assert ask.is_error and "작업물이 2개라 어느 층에 넣을지 모른다" in _text(ask) and "저자에게 묻는다" in _text(ask)
        put = _text(await c.call_tool("idea_add", {"text": "도시 메모", "kind": "thought", "untitled": True, "floor": "2층"}))
        assert "2층 「도시의 시간」의 생각" in put
        assert "공용의 문체" in _text(await c.call_tool("style_add", {
            "passage": "짧다.", "reason": "리듬", "floor": "도시의 시간",
            "tags": {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": [], "어미": "-다", "톤": "건조"}}))
        made = _text(await c.call_tool("category_create", {"name": "인물", "template": "인물", "floor": "2층"}))
        assert made.endswith("2층에 꽂혔다.")
        assert _text(await c.call_tool("category_create", {"name": "인물", "template": "인물", "floor": "공용"})).endswith("공용에 꽂혔다.")
        both = await c.call_tool("category_put", {"category": "인물", "author": "me", "content": "갤러", "untitled": True})
        assert both.is_error and "여러 층에 있다(공용, 2층)" in _text(both)
        assert "넣음" in _text(await c.call_tool("category_put", {"category": "인물", "author": "me", "content": "갤러",
                                                                "untitled": True, "floor": "2층"}))
        listed = _text(await c.call_tool("category_list", {}))
        assert listed.startswith("책장: 층 3개(공용 · 1층 「물에서 뭍으로」(book) · 2층 「도시의 시간」(")
        assert f"## 2층 「도시의 시간」({second}) · 원고 없음\n- 생각 1개 · 기본(idea_add)" in listed
        # 옮기기: 기본 카테고리는 어느 층의 것인지 가린다
        moved = await c.call_tool("category_edit", {"category": "생각", "move_to": "공용"})
        assert moved.is_error and "생각이 여러 층에 있다(1층, 2층)" in _text(moved)
        moved = _text(await c.call_tool("category_edit", {"category": "생각", "floor": "2층", "move_to": "공용"}))
        assert "옮김: 「생각」 2층 → 공용(항목 1개 함께)" in moved and "undo_move=true" in moved
        clash = await c.call_tool("category_edit", {"category": "인물", "floor": "2층", "move_to": "공용"})
        assert clash.is_error and "공용에 같은 이름 「인물」이 있어 옮기지 않았다" in _text(clash)
        wrong = await c.call_tool("category_edit", {"category": "인물", "floor": "공용", "undo_move": True})
        assert wrong.is_error and "마지막으로 옮긴 것: 「생각」" in _text(wrong)
        undone = _text(await c.call_tool("category_edit", {"category": "생각", "floor": "공용", "undo_move": True}))
        assert undone == "되돌림: 「생각」 공용 → 2층(옮기기 전 자리)."
        outline = _text(await c.call_tool("book_outline", {"project_id": "book"}))
        assert "이 작업물 층(1층)의 카테고리: 생각 1 · 문헌 0(확인 0)" in outline and "공용 층: 문체 1 · 인물 0" in outline
        found = _text(await c.call_tool("idea_search", {"query": "도시 메모", "author": "all"}))
        assert "· 2층 ·" in found  # 생각이 여러 층에 있어 결과마다 층을 적는다
        assert "결과 없음" in _text(await c.call_tool("idea_search", {"query": "도시 메모", "floor": "1층"}))


async def test_import_into_empty_floor(settings: Settings, store: LocalStore, tmp_path: Path):
    store.create_project("alice", "빈 층", project_id="later")
    c = store.create_category("alice", "인물", "person", "#2a7f86", (), "later")
    path = build_manuscript_docx(tmp_path / "닿으려는_종_합성.docx")
    store.put_inbox("alice", path.name, path.read_bytes())
    async with Client(build_server(settings, store)) as client:
        report = await client.call_tool("book_import", {"path": path.name, "project_id": "later"})
        assert not report.is_error, _text(report)
    project = store.get_project("alice", "later")
    assert project.title == "빈 층" and store.list_chapters("alice", "later")  # 저자가 지은 층 제목은 그대로, 원고가 채워졌다
    assert store.get_category("alice", c.id).floor == "later"
    again = None
    async with Client(build_server(settings, store)) as client:
        again = await client.call_tool("book_import", {"path": path.name, "project_id": "later"})
    assert again.is_error and "이미 있다" in _text(again)  # 원고가 생긴 뒤에는 수정본으로


def test_isolation(store: LocalStore):
    _book(store, "alice")
    _book(store, "bob")
    c = store.create_category("alice", "인물", "person", "#2a7f86", (), "book")
    with pytest.raises(MoveError):
        store.move_category("bob", c.id, COMMON)  # bob의 책장에는 없는 카테고리
    move = store.move_category("alice", c.id, COMMON)
    with pytest.raises(MoveError):
        store.undo_move("bob", move.id)
    assert store.last_move("bob") is None and store.list_categories("bob") == []
    store.add_ideas("bob", [Idea("b1", "밥의 생각", "thought", "me")])
    assert store.list_ideas("alice") == [] and [i.id for i in store.list_ideas("bob", floors=["book"])] == ["b1"]
    with pytest.raises(MoveError):
        store.move_builtin("bob", "ideas", "book", "no-such-floor")
    store.add_ideas("alice", [Idea("a1", "앨리스", "thought", "me")])
    store.move_builtin("alice", "ideas", "book", COMMON)
    assert [i.id for i in store.list_ideas("bob")] == ["b1"] and store.get_ideas("bob", ["b1"])["b1"].floor == "book"


async def test_ref_add_tells_when_moved_to_common(settings: Settings, store: LocalStore):
    _book(store)
    import_bibliography(store, "alice", BIB, "book")
    store.create_project("alice", "둘째", project_id="second")
    async with Client(build_server(settings, store)) as c:
        added = _text(await c.call_tool("ref_add", {"bib": {"key": "clack2012"}, "floor": "2층",
                                                    "passages": [{"text": "네발동물의 기원", "reason": "2층 1장의 근거"}]}))
        assert "공용의 문헌 (방금 옮김: 1층 「물에서 뭍으로」·2층 「둘째」 원고가 함께 쓰는 문헌이라 공용으로 옮김. 저자에게 알린다)" in added
        again = _text(await c.call_tool("ref_add", {"bib": {"key": "clack2012"}, "floor": "2층",
                                                    "passages": [{"text": "더 고른 문장", "reason": "보탬"}]}))
        assert "방금 옮김" not in again  # 이미 공용이면 다시 알리지 않는다


def test_passage_ref_keeps_floor(store: LocalStore):
    _book(store)
    store.put_ref("alice", Ref("kremer1993", "unverified", {"title": "Population growth"}, floor=COMMON))
    stored = store.put_ref("alice", Ref("kremer1993", "verified", {"title": "Population growth"}), [Passage("인구", "이유")])
    assert stored.floor == COMMON  # 고칠 때 층을 주지 않으면 그대로
