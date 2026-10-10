"""노드를 다른 프로젝트로 복사(2026-10-11 묶음 5, 연결 노드 대신, 웹만. docs/decisions/2026-10-11-batch.md).

책·글·첨부(.text·.thumb 포함)·컨텍스트·스크랩·응답 관계까지 복사해, 받는 프로젝트에 선 없이 따로 놓인 노드로 만든다.
복사본은 원본과 따로 산다(새 책·첨부 id). 가운데 노드·연결 노드·문헌 글이 든 노드·만든 문서가 든 노드는 복사하지 않는다(까닭 한 줄).
선 없는 노드는 패널 머리에 '선 잇기'가 바로 보인다. '+ 노드'의 연결 노드 고르기는 없다."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx2
import pytest

from magus.category.moves import add_link
from magus.contexts import Context
from magus.search import find_chunks
from magus.store import CategoryItem, LocalStore, Passage, Ref
from magus.store.maps import MapError
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

U = "alice"
FIRST, REPLY, SECOND = "20261011000000001-aaaaaa", "20261011000000002-bbbbbb", "20261011000000003-cccccc"


def _hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def _seed(store: LocalStore, user: str = U) -> str:
    """city 프로젝트의 노드 「답사」: 책 둘(장날 메모: 글·AI 답·스크랩·첨부 둘(파생 파일), 사진첩), 노드 색·컨텍스트. river는 빈 프로젝트."""
    store.create_project(user, "도시", project_id="city")
    store.create_project(user, "강", project_id="river")
    node = store.add_node(user, "city", "답사", color="#2f6db5", contexts=(Context("", "현장에서 쓴 메모다."),))
    store.create_category(user, "장날 메모", "blank", "#b3261e", (), "city", node.id, category_id="market",
                          contexts=(Context("생각 메모", "다듬어지지 않은 생각"),))
    store.put_category_item(user, CategoryItem(FIRST, "market", "엘알토 장날", "me", "장날", "author", tags=("시장",), scrap=True))
    store.put_category_item(user, CategoryItem(REPLY, "market", "AI의 정리", "ai", parent_id=FIRST))
    first = store.put_attachment(user, f"market/{FIRST}", "1_답사지도.txt", "옹기장수 골목".encode())
    second = store.put_attachment(user, f"market/{FIRST}", "2_사진.txt", "둘째 첨부".encode())
    for att in (first, second):
        folder = store.root / "users" / user / "shelf" / "categories" / "market" / "files" / FIRST / att.id
        (folder / ".text").mkdir()
        (folder / ".text" / "status.json").write_text('{"status": "ok"}', encoding="utf-8")
        (folder / ".thumb").mkdir()
        (folder / ".thumb" / "thumb.jpg").write_bytes(b"\xff\xd8thumb")
    store.create_category(user, "사진첩", "blank", "#1f2f5c", (), "city", node.id, category_id="album")
    store.put_category_item(user, CategoryItem(SECOND, "album", "강가 사진", "me"))
    return node.id


def test_copy_makes_an_independent_unlinked_node(store: LocalStore):
    node = _seed(store)
    city = store.root / "users" / U / "shelf"
    before = {k: v for k, v in _hashes(city).items() if not k.startswith("maps/")}
    usage = store.usage_bytes(U)
    made = store.copy_node(U, "city", node, "river")
    river = store.get_map(U, "river")
    assert made.name == "답사" and made.color == "#2f6db5" and made.contexts == (Context("", "현장에서 쓴 메모다."),)
    assert not any(made.id in edge for edge in river.edges)  # 선 없이 따로
    books = [store.get_category(U, b) for b in made.books]
    assert [b.name for b in books] == ["장날 메모", "사진첩"] and not {"market", "album"} & set(made.books)
    assert all(b.floor == "river" for b in books) and books[0].contexts == (Context("생각 메모", "다듬어지지 않은 생각"),)
    items = {i.id: i for i in store.list_category_items(U, books[0].id)}
    assert set(items) == {FIRST, REPLY} and items[REPLY].parent_id == FIRST and items[FIRST].scrap and items[FIRST].tags == ("시장",)
    copied = store.list_attachments(U, f"{books[0].id}/{FIRST}")
    original = store.list_attachments(U, f"market/{FIRST}")
    assert [a.name for a in copied] == [a.name for a in original] == ["1_답사지도.txt", "2_사진.txt"]  # 올린 순서 그대로
    assert not {a.id for a in copied} & {a.id for a in original}  # 첨부 id는 새로('첨부:<id>'가 겹치지 않게)
    folder = city / "categories" / books[0].id / "files" / FIRST / copied[0].id
    assert (folder / ".text" / "status.json").is_file() and (folder / ".thumb" / "thumb.jpg").is_file()
    assert {o for o in (c.owner_id for c in find_chunks(store, U, ["category"], "엘알토", 10))} == {f"market/{FIRST}", f"{books[0].id}/{FIRST}"}
    assert store.usage_bytes(U) > usage  # 용량에 들어간다
    assert {k: v for k, v in _hashes(city).items() if not k.startswith("maps/") and not k.startswith(f"categories/{books[0].id}")
            and not k.startswith(f"categories/{books[1].id}")} == before  # 원본은 바이트까지 그대로
    # 따로 산다: 복사본을 고쳐도 원본은 그대로
    store.patch_category_item(U, books[0].id, FIRST, {"content": "복사본에서 고침"})
    assert store.get_category_item(U, "market", FIRST).content == "엘알토 장날"
    # 한 번 더 복사하면 노드·책 이름에 (복사)
    again = store.copy_node(U, "city", node, "river")
    assert again.name == "답사 (복사)" and [store.get_category(U, b).name for b in again.books] == ["장날 메모 (복사)", "사진첩 (복사)"]
    store.reindex()  # 파일에서 다시 만들어도 같다
    assert len(store.get_map(U, "river").nodes) == 3 and store.get_category(U, again.books[0]).floor == "river"


def test_copy_is_blocked_with_a_reason(store: LocalStore):
    node = _seed(store)
    with pytest.raises(MapError) as e:
        store.copy_node(U, "city", "center", "river")
    assert e.value.code == "copy_center"
    with pytest.raises(MapError) as e:
        store.copy_node(U, "city", node, "city")
    assert e.value.code == "copy_same"
    link = add_link(store, U, "river", "city", node)
    assert store.node_copy_block(U, "river", link.id) == ("copy_link", "")
    store.put_ref(U, Ref(key="clack2012", status="verified", bib={"title": "Gaining ground"}, book="album"), passages=[Passage("대목", "근거")])
    assert store.node_copy_block(U, "city", node) == ("copy_refs", "사진첩")
    with pytest.raises(MapError):
        store.copy_node(U, "city", node, "river")
    other = store.add_node(U, "city", "작은 노드")
    store.create_category(U, "메모", "blank", "#1f2f5c", (), "city", other.id, category_id="memo")
    store.put_category_item(U, CategoryItem("20261011000000009-dddddd", "memo", "x" * 5000, "me"))
    with pytest.raises(MapError) as e:
        store.copy_node(U, "city", other.id, "river", max_user_bytes=store.usage_bytes(U) + 100)
    assert e.value.code == "too_big"
    assert store.list_categories(U, floors=["river"]) == []  # 막히면 아무것도 만들지 않는다
    with pytest.raises(MapError):
        store.copy_node("bob", "city", other.id, "river")  # 남의 노드는 없다


def test_web_copy_then_connect_and_no_link_picker(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    setup = LocalStore(data_dir)
    node = _seed(setup)
    setup.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get(f"/login?next=/shelf/p/city?node={node}").text
        csrf = _csrf(page)
        assert "<h3>다른 프로젝트로 복사</h3>" in page and '<option value="river">강</option>' in page and 'value="copy"' in page
        assert "<optgroup" not in page and 'value="add_link"' not in page  # '+ 노드'의 연결 노드 고르기는 없다
        center = c.get("/shelf/p/city?node=center").text
        assert "가운데 노드는 복사할 수 없습니다(올린 문서의 자리입니다)." in center
        post = "/shelf/p/city/map"
        assert c.post(post, data={"csrf": "틀림", "action": "copy", "node": node, "to": "river"}).status_code == 403
        copied = c.post(post, data={"csrf": csrf, "action": "copy", "node": node, "to": "river"})
        assert copied.url.path == "/shelf/p/river" and "노드 「답사」를 복사했습니다." in copied.text
        new = re.search(r"[?&]node=([^&]+)", str(copied.url)).group(1)
        assert '<form method="post" action="/shelf/p/river/map" class="pp-alone">' in copied.text and "선이 없는 노드입니다." in copied.text
        joined = c.post("/shelf/p/river/map", data={"csrf": csrf, "action": "connect", "node": new, "other": "center"})
        assert "선을 이었습니다." in joined.text and "선이 없는 노드입니다." not in joined.text
        missing = c.post(post, data={"csrf": csrf, "action": "copy", "node": node, "to": "nowhere"})
        assert "maperr=unknown_floor" in str(missing.url)
    store = LocalStore(data_dir)
    river = store.get_map(U, "river")
    assert [n.name for n in river.nodes] == ["강", "답사"] and len(river.edges) == 1
    assert len(store.list_categories(U, floors=["river"])) == 2 and len(store.list_categories(U, floors=["city"])) == 2
    store.close()
