"""글의 첨부 파일(사용자 요청 #97): 저장 위치·이름 다듬기·휴지통·사용자 격리, 원문 확인 체크(쓸 부분은 그대로)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_book

from magus.attachments import clean_name, describe
from magus.melchior.check import refresh_cite_counts
from magus.store import CategoryItem, LocalStore, Passage, Ref


def _item(store: LocalStore, user: str, book: str, text: str = "글") -> str:
    return store.put_category_item(user, CategoryItem("20261008120000000-aaaaaa", book, text, "me")).id


def test_clean_name_blocks_paths_and_odd_types():
    assert clean_name("논문.pdf") == "논문.pdf"
    assert clean_name("C:\\fakepath\\사진.JPG") == "사진.JPG"  # 브라우저가 붙인 폴더는 뗀다
    assert clean_name("../../etc/메모.txt") == "메모.txt"  # 폴더는 떼고 이름만(경로로 쓰지 않는다)
    for bad in ("..", ".hidden.pdf", "a<b>.pdf", "x.svg", "x.html", "x.exe", "x.json", "", "CON.pdf", "가" * 80 + ".pdf"):
        with pytest.raises(ValueError):
            clean_name(bad)
    assert describe("a.pdf", 1_200_000) == "a.pdf(PDF, 1.2 MB)"


def test_put_list_read_and_folder_is_inside_user_dir(store: LocalStore, data_dir: Path):
    book = make_book(store, "alice", "생각")
    item = _item(store, "alice", book)
    owner = f"{book}/{item}"
    a = store.put_attachment("alice", owner, "논문.pdf", b"%PDF-1")
    b = store.put_attachment("alice", owner, "논문.pdf", b"%PDF-22")  # 같은 이름도 따로 남는다
    found = store.list_attachments("alice", owner)
    assert [x.id for x in found] == [a.id, b.id] and [x.size for x in found] == [6, 7]
    path, info = store.attachment_path("alice", owner, a.id)
    assert info.name == "논문.pdf" and path.read_bytes() == b"%PDF-1"
    assert path.is_relative_to(data_dir / "users" / "alice" / "shelf" / "categories" / book / "files" / item)
    assert store.usage_bytes("alice") >= 13  # 저장 용량에 들어간다
    with pytest.raises(ValueError):
        store.put_attachment("alice", f"{book}/없는글", "x.pdf", b"x")
    with pytest.raises(ValueError):
        store.put_attachment("alice", owner, "../x.pdf", b"x")
    with pytest.raises(ValueError):
        store.attachment_path("alice", owner, "../../x")


def test_other_user_cannot_reach_attachments(store: LocalStore):
    """같은 책 id·글 id를 써도 다른 사용자의 첨부는 보이지 않는다."""
    for user in ("alice", "bob"):
        store.create_category(user, "생각", "blank", "#1f2f5c", (), "common", category_id="ideas-x")
        _item(store, user, "ideas-x")
    owner = "ideas-x/20261008120000000-aaaaaa"
    a = store.put_attachment("alice", owner, "비밀.pdf", b"alice")
    assert store.list_attachments("bob", owner) == []
    assert store.attachment_path("bob", owner, a.id) is None
    assert store.trash_attachment("bob", owner, a.id, "x") is False
    assert store.attachment_path("alice", owner, a.id)[0].read_bytes() == b"alice"


def test_item_trash_and_restore_carry_attachments(store: LocalStore, data_dir: Path):
    book = make_book(store, "alice", "생각")
    item = _item(store, "alice", book)
    owner = f"{book}/{item}"
    a = store.put_attachment("alice", owner, "사진.png", b"png")
    store.trash_category_item("alice", book, item, "시험")
    assert store.list_attachments("alice", owner) == []
    kept = data_dir / "users" / "alice" / "trash" / "shelf" / "category-items" / book / "files" / item / a.id / "사진.png"
    assert kept.read_bytes() == b"png"
    assert [t.kind for t in store.list_trash("alice")] == ["category_item"]  # 첨부 폴더가 휴지통 목록을 어지럽히지 않는다
    store.restore_trash("alice", "category_item", f"{book}/{item}")
    assert [x.id for x in store.list_attachments("alice", owner)] == [a.id]


def test_one_attachment_goes_to_trash_not_deleted(store: LocalStore, data_dir: Path):
    book = make_book(store, "alice", "생각")
    owner = f"{book}/{_item(store, 'alice', book)}"
    a = store.put_attachment("alice", owner, "표.xlsx", b"x")
    assert store.trash_attachment("alice", owner, a.id, "웹에서 뺌")
    assert store.list_attachments("alice", owner) == []
    assert list((data_dir / "users" / "alice" / "trash" / "shelf" / "attachments").rglob("표.xlsx"))


def test_book_trash_carries_attachments(store: LocalStore, data_dir: Path):
    book = make_book(store, "alice", "사례")
    item = _item(store, "alice", book)
    store.put_attachment("alice", f"{book}/{item}", "a.pdf", b"x")
    store.trash_category("alice", book, "시험")
    assert list((data_dir / "users" / "alice" / "trash" / "shelf" / "categories" / book / "files").rglob("a.pdf"))
    store.reindex()  # files/ 폴더가 있어도 다시 만들기가 된다
    assert store.get_category("alice", book) is None


def test_ref_attachments_and_check_keep_passages(store: LocalStore, data_dir: Path):
    book = make_book(store, "alice", "문헌", floor="common")
    store.put_ref("alice", Ref(key="clack2012", status="unverified", bib={"title": "Gaining Ground"}, book=book),
                  passages=[Passage("네발동물", "근거", "p.3")])
    a = store.put_attachment("alice", "ref:clack2012", "clack.pdf", b"%PDF")
    assert store.attachment_path("alice", "ref:clack2012", a.id)[1].name == "clack.pdf"
    assert store.list_attachments("alice", "ref:없는문헌") == []
    ref = store.set_ref_status("alice", "clack2012", "verified")
    assert ref.status == "verified" and store.get_passages("alice", "clack2012") == [Passage("네발동물", "근거", "p.3")]
    store.set_ref_status("alice", "clack2012", "unverified")
    assert store.get_passages("alice", "clack2012") == [Passage("네발동물", "근거", "p.3")]  # 쓸 부분은 지우지 않는다
    store.reindex()
    refresh_cite_counts(store, "alice")
    assert store.get_ref("alice", "clack2012").status == "unverified"
    assert [x.name for x in store.list_attachments("alice", "ref:clack2012")] == ["clack.pdf"]
    with pytest.raises(ValueError):
        store.set_ref_status("alice", "clack2012", "maybe")


@pytest.mark.anyio
async def test_search_shows_attachment_name_kind_size_only(settings, store: LocalStore):
    """MCP: 글을 읽을 때 첨부는 이름·종류·크기만(내용은 읽지 않는다)."""
    from mcp import Client

    from magus.server import build_server

    book = make_book(store, "alice", "사례")
    item = store.put_category_item("alice", CategoryItem("20261008120000000-bbbbbb", book, "항구의 장날 이야기", "me")).id
    store.put_attachment("alice", f"{book}/{item}", "장날.pdf", b"%PDF secret-body " * 70_000)
    store.put_ref("alice", Ref(key="clack2012", status="verified", bib={"title": "Gaining Ground"}, book=book),
                  passages=[Passage("장날의 네발동물", "근거")])
    store.put_attachment("alice", "ref:clack2012", "clack.png", b"png")
    async with Client(build_server(settings, store)) as c:
        result = await c.call_tool("category_search", {"query": "장날", "book": "사례"})
    text = result.content[0].text
    assert "첨부 1개: 장날.pdf(PDF, 1.2 MB, 첨부:" in text  # #100: 읽을 때 쓰는 첨부 id
    assert "첨부 1개: clack.png(그림, 1 KB, 첨부:" in text
    assert "secret-body" not in text
