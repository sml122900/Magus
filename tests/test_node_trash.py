"""노드 삭제(사용자 요청 #97 2, 2026-10-09, 웹 전용): 노드를 그 책·글·첨부·문서와 선째 휴지통으로(지우지 않음), 되살리면 그대로.
휴지통에 있는 것은 검색·전체 현황·지도·MCP 결과에서 빠진다. 가운데 노드·다른 프로젝트가 연결 중인 노드·문헌 글이 든 책은 막는다."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from mcp import Client

from magus.book.documents import build_source_check
from magus.config import Settings
from magus.maps import CENTER
from magus.server import build_server
from magus.store import CategoryItem, Document, LocalStore, Passage, Ref
from magus.store.maps import MapError

from conftest import with_library

CHAPTER = "물고기가 뭍으로 올라왔다(Clack, 2012). 강가의 장날 이야기."


def _hashes(root: Path) -> dict[str, str]:
    """원본 파일의 해시. 색인과 파생 캐시(.cache — 서버가 뒤에서 인용 계산을 데운다, 결정 f), 활동 기록(옮기고 되살릴 때마다 한 줄씩)은 뺀다."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.name.startswith("index.sqlite") and ".cache" not in p.parts
            and p.name != ".activity.log"}


def _seed(store: LocalStore, user: str = "alice") -> dict[str, str]:
    """프로젝트 book(원고 1장) + 노드 「답사」(책 둘: 글·첨부 / 출처 확인 문서) + 노드 「참고문헌」(문헌 글) + 「내 서재」의 노드 「사례」."""
    store.create_project(user, "물에서 뭍으로", project_id="book")
    store.write_chapter(user, "book", 1, CHAPTER, "x", title="물고기의 결심")
    walk = store.add_node(user, "book", "답사", x=320, y=-140)
    notes = store.create_category(user, "장날 메모", "blank", "#1f2f5c", (), "book", walk.id).id
    photos = store.create_category(user, "사진", "blank", "#2f6db5", (), "book", walk.id).id
    for n, text in enumerate(("강가 장날의 소금 장수", "장날 아침의 물안개", "소금 배가 들어오던 나루")):
        store.put_category_item(user, CategoryItem(f"2026100900000000{n}-aaaaaa", notes, text, "me", reason="이유는 파일에"))
    store.put_attachment(user, f"{notes}/20261009000000000-aaaaaa", "장터.png", b"\x89PNG demo")
    store.put_category_item(user, CategoryItem("20261009000000009-bbbbbb", photos, "", "me", title="나루 사진"))
    store.put_attachment(user, f"{photos}/20261009000000009-bbbbbb", "나루.jpg", b"\xff\xd8\xff demo")
    content, version = build_source_check(store, user, "book", "물에서 뭍으로 출처 확인 문서")
    doc = store.create_document(user, Document("", "물에서 뭍으로 출처 확인 문서", "author", "source_check", "book", "book", "#5b6b7a",
                                               versions=(version,)), content, walk.id)
    refs = store.add_node(user, "book", "참고문헌")
    shelf = store.create_category(user, "읽은 논문", "blank", "#1f2f5c", (), "book", refs.id).id
    store.put_ref(user, Ref(key="clack2012", status="verified", bib={"title": "Gaining Ground"}, book=shelf),
                  passages=[Passage("네발동물이 뭍으로", "근거")])
    other = store.add_node(user, "book", "강")
    store.connect_nodes(user, "book", walk.id, other.id)
    with_library(store, user)
    case = store.add_node(user, "common", "사례")
    store.ensure_maps(user)
    return {"walk": walk.id, "notes": notes, "photos": photos, "doc": doc.id, "refs": refs.id, "other": other.id, "case": case.id}


def test_trash_with_books_and_restore_round_trip_keeps_every_file(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    root = data_dir / "users" / "alice"
    before = _hashes(root)
    info = store.node_trash_info("alice", "book", ids["walk"])
    assert (info.books, info.items, info.blocked) == (3, 4, None)
    gone = store.trash_node_with_books("alice", "book", ids["walk"], "웹 지도에서 옮김")
    assert gone.name == "답사" and store.get_map("alice", "book").node(ids["walk"]) is None
    assert all(ids["walk"] not in e for e in store.get_map("alice", "book").edges)
    # 지우지 않고 사용자 폴더 안의 휴지통으로(백업에 그대로 들어간다)
    bundle = root / "trash" / "shelf" / "nodes" / "book" / ids["walk"]
    assert (bundle / "categories" / ids["notes"] / "files").is_dir() and (bundle / "documents" / ids["doc"] / "document.json").exists()
    assert not (root / "shelf" / "categories" / ids["notes"]).exists()
    [t] = [t for t in store.list_trash("alice") if t.kind == "node"]
    assert t.id == f"book/{ids['walk']}" and t.preview == "노드 「답사」" and t.detail.startswith("책 3권·글 ")
    # 휴지통에 있는 것은 목록·검색·색인에서 빠진다
    assert store.get_category("alice", ids["notes"]) is None and store.get_document("alice", ids["doc"]) is None
    assert store.list_category_items("alice", ids["notes"]) == []
    assert not store.search_substring("alice", ["category", "document"], "장날", 50)
    # 되살리면 파일이 하나도 다르지 않다(지도 파일까지 바이트 그대로)
    assert store.restore_trash("alice", "node", t.id) == [f"book/{ids['walk']}"]
    assert _hashes(root) == before
    back = store.get_map("alice", "book")
    node = back.node(ids["walk"])
    assert (node.x, node.y, len(node.books)) == (320.0, -140.0, 3) and tuple(sorted((ids["walk"], ids["other"]))) in back.edges
    assert [a.name for a in store.list_attachments("alice", f"{ids['notes']}/20261009000000000-aaaaaa")] == ["장터.png"]
    assert len(store.list_category_items("alice", ids["notes"])) == 3 and store.get_document("alice", ids["doc"]) is not None
    assert store.search_substring("alice", ["category"], "소금", 50)
    assert not list((root / "trash" / "shelf" / "nodes" / "book").iterdir())  # 빈 휴지통 폴더도 치운다(파일은 없음)


def test_restore_after_the_map_changed_drops_lines_to_missing_nodes(store: LocalStore):
    ids = _seed(store)
    store.trash_node_with_books("alice", "book", ids["walk"], "x")
    store.update_node("alice", "book", ids["refs"], x=10, y=10)  # 그사이 지도가 바뀜
    store.trash_node("alice", "book", ids["other"], "선의 반대쪽 노드를 치움")
    store.restore_trash("alice", "node", f"book/{ids['walk']}")
    back = store.get_map("alice", "book")
    node = back.node(ids["walk"])
    assert (node.x, node.y) == (320.0, -140.0) and set(node.books) == {ids["notes"], ids["photos"], f"doc.{ids['doc']}"}
    assert all(ids["other"] not in e for e in back.edges) and tuple(sorted((CENTER, ids["walk"]))) in back.edges
    assert back.node(ids["refs"]).x == 10.0


def test_restore_refuses_when_a_same_named_book_appeared(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    store.trash_node_with_books("alice", "book", ids["walk"], "x")
    store.create_category("alice", "사진", "blank", "#000000", (), "book")
    with pytest.raises(ValueError, match="「사진」 책이 이미 있어"):
        store.restore_trash("alice", "node", f"book/{ids['walk']}")
    bundle = data_dir / "users" / "alice" / "trash" / "shelf" / "nodes" / "book" / ids["walk"]
    assert (bundle / "categories" / ids["notes"]).is_dir() and (bundle / "categories" / ids["photos"]).is_dir()  # 반쯤 되살리지 않는다


def test_blocked_nodes_and_link_nodes(store: LocalStore):
    ids = _seed(store)
    with pytest.raises(MapError) as e:
        store.trash_node_with_books("alice", "book", CENTER, "x")
    assert e.value.code == "center" and store.node_trash_info("alice", "book", CENTER).blocked == "center"
    with pytest.raises(MapError) as e:  # 문헌 글이 든 책(인용 점검이 보는 기록)
        store.trash_node_with_books("alice", "book", ids["refs"], "x")
    assert e.value.code == "has_refs" and e.value.info["name"] == "읽은 논문"
    # 다른 프로젝트의 연결 노드가 가리키는 노드(「내 서재」의 「사례」)
    store.create_project("alice", "강과 사람", project_id="river")
    link = store.add_link_node("alice", "river", "common", ids["case"])
    info = store.node_trash_info("alice", "common", ids["case"])
    assert info.blocked == "linked" and info.linked_from == ("강과 사람",)
    with pytest.raises(MapError) as e:
        store.trash_node_with_books("alice", "common", ids["case"], "x")
    assert e.value.code == "linked" and e.value.info["projects"] == "「강과 사람」"
    # 연결 노드를 지우면 연결 노드만 휴지통으로, 원본 노드와 그 책·글은 그대로
    case_books = store.get_map("alice", "common").node(ids["case"]).books
    gone = store.trash_node_with_books("alice", "river", link.id, "x")
    assert gone.link == ("common", ids["case"]) and store.get_map("alice", "river").node(link.id) is None
    assert store.get_map("alice", "common").node(ids["case"]).books == case_books
    assert store.node_trash_info("alice", "common", ids["case"]).blocked is None  # 이제 아무도 연결하지 않는다
    store.restore_trash("alice", "node", f"river/{link.id}")
    assert store.get_map("alice", "river").node(link.id).link == ("common", ids["case"])


def test_other_user_cannot_trash_or_restore(store: LocalStore, data_dir: Path):
    ids = _seed(store, "alice")
    _seed(store, "bob")  # 같은 프로젝트 id를 밥도 쓴다
    with pytest.raises(MapError):
        store.trash_node_with_books("bob", "book", ids["walk"], "x")  # 노드 id는 사람마다 다르다
    store.trash_node_with_books("alice", "book", ids["walk"], "x")
    with pytest.raises(ValueError):
        store.restore_trash("bob", "node", f"book/{ids['walk']}")
    assert (data_dir / "users" / "alice" / "trash" / "shelf" / "nodes" / "book" / f"{ids['walk']}.json").exists()
    assert store.get_map("bob", "book") is not None and len(store.list_categories("bob", floors=["book"])) == 3


@pytest.mark.anyio
async def test_trashed_node_is_gone_from_mcp_results(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        def text(r) -> str:
            return r.content[0].text

        assert "장날" in text(await c.call_tool("category_search", {"query": "장날"}))
        assert "답사" in text(await c.call_tool("book_outline", {})) and "장날 메모" in text(await c.call_tool("category_list", {}))
        store.trash_node_with_books("alice", "book", ids["walk"], "x")
        assert "결과 없음" in text(await c.call_tool("category_search", {"query": "장날"}))
        outline = text(await c.call_tool("book_outline", {}))
        listed = text(await c.call_tool("category_list", {}))
        assert "답사" not in outline and "장날 메모" not in listed and "사진" not in listed and "답사" not in listed
        # 대화로는 책이 꽂힌 노드를 지우지 못한다(도구는 그대로, 빈 노드만)
        refused = await c.call_tool("category_trash", {"node": "참고문헌", "project": "book", "note": "x"})
        assert refused.is_error
