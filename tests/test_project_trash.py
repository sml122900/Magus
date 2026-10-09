"""프로젝트 휴지통(2026-10-09 구조·버그 점검 3번): 프로젝트를 통째로 휴지통으로 옮기고 되살린다. 지우지 않는다.
왕복 뒤 파일 해시가 같고, 휴지통에 있는 동안 목록·검색·문헌·전체 현황에서 빠지고, 다른 사용자·다른 프로젝트는 그대로다."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from magus.book.outline import build_outline
from magus.melchior.bibliography import import_bibliography
from magus.melchior.check import after_refs_changed
from magus.search import find_chunks
from magus.store import CategoryItem, LocalStore, Passage, Ref
from test_web import server_proc  # noqa: F401 - 픽스처


def _hashes(folder: Path) -> dict[str, str]:
    """사용자 폴더의 파일 해시(휴지통·계산 캐시는 빼고)."""
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*"))
            if p.is_file() and not p.relative_to(folder).as_posix().startswith("trash/projects") and ".cache" not in p.parts}


def _seed(store: LocalStore, user: str = "alice") -> None:
    store.create_project(user, "도시의 책", project_id="city")
    store.write_chapter(user, "city", 1, "도시는 자란다(Clack, 2012).", "x", title="하나")
    import_bibliography(store, user, "Clack, J. (2012). Gaining ground. Indiana.\n", floor="city")
    store.create_project(user, "강의 책", project_id="river")
    store.create_category(user, "답사", "blank", "#1f2f5c", (), "city", category_id="walk")
    store.put_category_item(user, CategoryItem("20261009000000000-aaaaaa", "walk", "골목 답사 메모", "me"))
    store.put_attachment(user, "walk/20261009000000000-aaaaaa", "사진.txt", "골목".encode())
    store.put_category_item(user, CategoryItem("20261009000000001-bbbbbb", "walk", "버린 글", "me"))
    store.trash_item_with_replies(user, "walk", "20261009000000001-bbbbbb", "먼저 버림")
    store.create_category(user, "물길", "blank", "#1f2f5c", (), "river", category_id="water")
    store.put_category_item(user, CategoryItem("20261009000000002-cccccc", "water", "물길 메모", "me"))
    store.put_ref(user, Ref(key="daeschler2006", status="verified", bib={"title": "A Devonian fish", "authors": "Daeschler, E."},
                            book="water"), passages=[Passage("물고기 쓸 부분", "근거", "p.1")])
    after_refs_changed(store, user)


def test_project_trash_round_trip(store: LocalStore):
    _seed(store)
    _seed(store, "bob")
    udir = store.root / "users" / "alice"
    before = _hashes(udir)
    bob_before = _hashes(store.root / "users" / "bob")
    info = store.project_trash_info("alice", "city")
    assert info is not None and info.blocked is None and info.books == 2 and info.items == 1 and info.refs == 1 and info.chapters == 1
    assert store.project_trash_info("alice", "common").blocked == "library"
    trash_id = store.trash_project("alice", "city", "웹에서 옮김")
    # 휴지통에 있는 동안: 목록·책·문헌·검색·현황에서 빠진다
    assert [f.id for f in store.list_floors("alice")] == ["common", "river"]
    assert store.get_project("alice", "city") is None and store.get_category("alice", "walk") is None
    assert store.get_ref("alice", "clack2012") is None and store.get_ref("alice", "daeschler2006") is not None
    assert not find_chunks(store, "alice", ["category"], "골목", 10)
    assert "강의 책" in build_outline(store, "alice", "river") and "도시의 책" not in build_outline(store, "alice", "river")
    assert [t.project_id for t in store.list_trashed_projects("alice")] == ["city"]
    assert not any(t.kind == "category_item" and t.id.startswith("walk/") for t in store.list_trash("alice"))  # 그 프로젝트의 휴지통 기록도 함께
    assert (udir / "trash" / "projects" / trash_id / "manifest.json").exists()
    assert _hashes(store.root / "users" / "bob") == bob_before  # 다른 사용자는 그대로
    # 되살리기: 파일 해시까지 같고, 다시 보인다
    assert store.restore_project("alice", trash_id) == "city"
    assert _hashes(udir) == before
    assert not (udir / "trash" / "projects" / trash_id).exists()
    assert [f.id for f in store.list_floors("alice")] == ["common", "city", "river"]
    assert find_chunks(store, "alice", ["category"], "골목", 10) and store.get_ref("alice", "clack2012") is not None
    assert any(t.id == "walk/20261009000000001-bbbbbb" for t in store.list_trash("alice"))  # 먼저 버린 글도 따로 되살릴 수 있게 남는다


def test_project_trash_blocks(store: LocalStore):
    _seed(store)
    from magus.category.moves import add_link  # noqa: PLC0415

    add_link(store, "alice", "river", "city", "center")
    info = store.project_trash_info("alice", "city")
    assert info.blocked == "linked" and info.linked_from == ("강의 책",)
    with pytest.raises(ValueError) as e:
        store.trash_project("alice", "city", "x")
    assert e.value.args == ("linked", "「강의 책」")
    with pytest.raises(ValueError) as e:
        store.trash_project("alice", "common", "x")
    assert e.value.args[0] == "library"
    trash_id = store.trash_project("alice", "river", "x")  # 연결하는 쪽은 옮길 수 있다
    store.create_project("alice", "같은 id", project_id="river")
    with pytest.raises(ValueError) as e:
        store.restore_project("alice", trash_id)
    assert e.value.args[0] == "taken"
    assert [t.project_id for t in store.list_trashed_projects("alice")] == ["river"]  # 막혀도 휴지통에 그대로


def test_project_trash_web(server_proc):  # noqa: F811
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    import httpx2  # noqa: PLC0415
    from test_web import _csrf  # noqa: PLC0415

    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    _seed(store)
    pj = data_dir / "users" / "alice" / "projects" / "city" / "project.json"
    data = json.loads(pj.read_text(encoding="utf-8"))  # 수정본 기록(시험용: E1 + E2)
    data["editions"] = [{"number": 1, "file": "a.docx", "uploaded_at": "2026-10-01T00:00:00.000Z"},
                        {"number": 2, "file": "b.docx", "uploaded_at": "2026-10-02T00:00:00.000Z"}]
    pj.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        page = c.get("/login?next=/shelf/p/city").text
        csrf = _csrf(page)
        assert '<summary><span aria-hidden="true">🗑</span> 휴지통으로</summary>' in page
        assert "프로젝트 「도시의 책」을 휴지통으로 옮길까요?" in page and '<p class="big-warn">수정본 1개가 함께 옮겨집니다.</p>' in page
        assert "node-del proj-del" not in c.get("/shelf/p/common").text  # 「내 서재」에는 없다
        gone = c.post("/shelf/p/city/discard", data={"csrf": csrf})
        assert str(gone.url).startswith(f"{base}/shelf?done=project_trashed")
        assert "「도시의 책」 프로젝트를 휴지통으로 옮겼습니다." in gone.text and '<a href="/shelf/trash">휴지통 1</a>' in gone.text
        assert "도시의 책" not in re.sub(r'<p class="msg">.*?</p>', "", gone.text)  # 목록에서 빠짐
        assert c.get("/shelf/p/city").status_code == 404
        trash = c.get("/shelf/trash").text
        assert '<p class="trash-count">1개</p>' in trash and "<b>프로젝트 「도시의 책」</b>" in trash and "수정본 1개" in trash
        trash_id = re.search(r'name="trash" value="([^"]+)"', trash).group(1)
        back = c.post("/shelf/trash", data={"csrf": csrf, "trash": trash_id})
        assert str(back.url).endswith("/shelf/p/city?done=project_restored") and "프로젝트를 되살렸습니다." in back.text
        assert '<p class="empty">휴지통이 비었습니다.</p>' in c.get("/shelf/trash").text
        # 다른 프로젝트가 연결 중이면 막는다(까닭과 닫기만, 보내도 400)
        c.post("/shelf/p/river/map", data={"csrf": csrf, "action": "add_link", "target": "city:center"})
        blocked = c.get("/shelf/p/city").text
        assert "「강의 책」에서 연결하고 있어 휴지통으로 옮길 수 없습니다." in blocked
        refused = c.post("/shelf/p/city/discard", data={"csrf": csrf})
        assert refused.status_code == 400 and "「강의 책」에서 연결하고 있어 휴지통으로 옮길 수 없습니다." in refused.text
        assert c.post("/shelf/p/common/discard", data={"csrf": csrf}).status_code == 400
