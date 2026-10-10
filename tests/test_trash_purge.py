"""휴지통 비우기(2026-10-11 묶음 3, docs/decisions/2026-10-11-batch.md): 항목마다 [영구 삭제], 화면마다 [휴지통 비우기].

지우면 그 항목의 파일(첨부 폴더 안 .text·.thumb, 프로젝트 폴더 안 .cache 포함)이 사라지고 용량이 준다. 휴지통에 옮길 때 이미
색인에서 빠지므로 색인에 지운 것을 가리키는 줄이 없다. 확인은 같은 자리의 창(브라우저 confirm 없음). 백업에는 최대 1년까지 남을 수 있다는 안내."""

from __future__ import annotations

import re
from pathlib import Path

import httpx2
import pytest

from magus.store import CategoryItem, LocalStore
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

U = "alice"
POST, REPLY, GONE, KEEP = (f"2026101100000000{n}-aaaaaa" for n in range(4))


def _derived(att_dir: Path) -> None:
    """뽑은 글자·썸네일처럼 첨부 폴더 안에 생기는 파생 파일."""
    (att_dir / ".text").mkdir(exist_ok=True)
    (att_dir / ".text" / "status.json").write_text('{"status": "ok"}', encoding="utf-8")
    (att_dir / ".thumb").mkdir(exist_ok=True)
    (att_dir / ".thumb" / "thumb.jpg").write_bytes(b"\xff\xd8" + b"0" * 5000)


def _seed(store: LocalStore, user: str = U) -> dict[str, str]:
    """프로젝트 둘(city·river). city: 글·응답 글·첨부(파생 파일)를 휴지통에, 첨부 하나만 뺌, 노드째(책·글) 휴지통, 책째 휴지통,
    올린 문서 휴지통(장 2), 만든 문서 휴지통. river는 프로젝트째 휴지통. 예전 올린 파일 하나도 휴지통."""
    store.create_project(user, "도시", project_id="city")
    store.create_category(user, "메모", "blank", "#1f2f5c", (), "city", category_id="memo")
    store.put_category_item(user, CategoryItem(POST, "memo", "버릴 글", "me", title="버릴 글", title_by="author"))
    store.put_category_item(user, CategoryItem(REPLY, "memo", "AI 답", "ai", parent_id=POST))
    att = store.put_attachment(user, f"memo/{POST}", "답사.txt", ("가" * 3000).encode())
    _derived(store.root / "users" / user / "shelf" / "categories" / "memo" / "files" / POST / att.id)
    store.put_category_item(user, CategoryItem(KEEP, "memo", "남길 글", "me"))
    pulled = store.put_attachment(user, f"memo/{KEEP}", "뺄 사진.txt", ("나" * 2000).encode())
    store.trash_attachment(user, f"memo/{KEEP}", pulled.id, "뺌")
    store.trash_item_with_replies(user, "memo", POST, "버림")
    node = store.add_node(user, "city", "답사")
    store.create_category(user, "장날", "blank", "#1f2f5c", (), "city", node.id, category_id="market")
    store.put_category_item(user, CategoryItem(GONE, "market", "장날 기록", "me"))
    store.trash_node_with_books(user, "city", node.id, "노드째")
    store.create_category(user, "버린 책", "blank", "#1f2f5c", (), "city", category_id="oldbook")
    store.put_category_item(user, CategoryItem("20261011000000009-bbbbbb", "oldbook", "책과 함께", "me"))
    store.trash_category(user, "oldbook", "책째")
    store.write_chapter(user, "city", 1, "본문 " * 500, "x", title="하나")
    store.write_chapter(user, "city", 2, "둘째 " * 500, "x", title="둘")
    store.trash_manuscript(user, "city", "올린 문서 휴지통")
    doc = store.root / "users" / user / "trash" / "shelf" / "documents" / "doc1"
    doc.mkdir(parents=True)
    (doc / "document.json").write_text('{"title": "출처 확인 문서", "floor": "city", "versions": [{}], "_trash": {"at": '
                                       '"2026-10-11T00:00:00.000Z"}}', encoding="utf-8")
    (doc / "v1.md").write_text("문서 " * 300, encoding="utf-8")
    store.create_project(user, "강", project_id="river")
    store.create_category(user, "물길", "blank", "#1f2f5c", (), "river", category_id="water")
    store.put_category_item(user, CategoryItem("20261011000000008-cccccc", "water", "물길 메모", "me"))
    store.put_attachment(user, "water/20261011000000008-cccccc", "큰 자료.txt", b"x" * 400_000)  # 비우면 용량 표시(0.1MB 단위)가 준다
    river = store.trash_project(user, "river", "프로젝트째")
    store.put_inbox(user, "예전원고.docx", b"PK" + b"0" * 4000)
    inbox = store.trash_inbox(user, "예전원고.docx", "바꿈")
    return {"att": att.id, "pulled": pulled.id, "node": node.id, "river": river, "inbox": inbox}


def _chunks(store: LocalStore, user: str = U) -> set[str]:
    return {r[0] for r in store._db.execute("SELECT owner_id FROM chunks WHERE user_id = ?", (user,))}


def test_purge_each_kind_removes_files_and_frees_space(store: LocalStore):
    ids = _seed(store)
    _seed(store, "bob")
    trash = store.root / "users" / U / "trash"
    before_usage, before_bob, before_chunks = store.usage_bytes(U), store.usage_bytes("bob"), _chunks(store)
    assert not any("memo/" + POST in o or "market/" in o or "oldbook/" in o for o in before_chunks)  # 휴지통 것은 색인에 없다
    kinds = {(t.kind, t.id) for t in store.list_trash(U)}
    assert ("category_item", f"memo/{POST}") in kinds and ("node", f"city/{ids['node']}") in kinds and ("category", "oldbook") in kinds
    # 글: 응답 글·첨부(파생 파일 포함) 함께
    freed = store.purge_trash(U, "category_item", f"memo/{POST}")
    assert freed > 3000 and not (trash / "shelf" / "category-items" / "memo" / f"{POST}.json").exists()
    assert not (trash / "shelf" / "category-items" / "memo" / f"{REPLY}.json").exists()
    assert not (trash / "shelf" / "category-items" / "memo" / "files" / POST).exists()
    # 첨부 하나
    assert store.purge_trash(U, "attachment", f"memo/{KEEP}/{ids['pulled']}") >= 2000
    assert not (trash / "shelf" / "attachments" / "memo" / KEEP).exists() and store.get_category_item(U, "memo", KEEP) is not None
    # 노드째(책·글), 책째, 올린 문서, 만든 문서, 프로젝트째, 예전 올린 파일
    store.purge_trash(U, "node", f"city/{ids['node']}")
    assert not (trash / "shelf" / "nodes" / "city").exists()
    store.purge_trash(U, "category", "oldbook")
    [ms] = store.list_trashed_manuscripts(U)
    assert ms.project_id == "city" and ms.detail == "2장" and (trash / ms.id / "book" / "ch-01.md").exists()
    store.purge_trash(U, "manuscript", ms.id)
    [doc] = store.list_trashed_documents(U)
    assert (doc.project_id, doc.title) == ("city", "출처 확인 문서")
    store.purge_trash(U, "document", doc.id)
    store.purge_trash(U, "project", ids["river"])
    store.purge_trash(U, "inbox", ids["inbox"])
    assert store.list_trash(U) == [] and store.list_trashed_projects(U) == [] and store.list_trashed_inbox(U) == []
    assert store.list_trashed_documents(U) == [] and store.list_trashed_manuscripts(U) == []
    left = [p for p in trash.rglob("*") if p.is_file()] if trash.exists() else []
    assert left == [], left
    assert store.usage_bytes(U) < before_usage - 20_000  # 용량이 줄었다
    assert _chunks(store) == before_chunks  # 색인은 그대로(휴지통 것은 처음부터 없다)
    store.reindex()
    assert _chunks(store) == before_chunks
    assert store.usage_bytes("bob") == before_bob  # 다른 사용자는 그대로
    assert store.get_category_item(U, "memo", KEEP).content == "남길 글"  # 휴지통 밖의 것은 그대로


def test_purge_refuses_unknown_and_outside_paths(store: LocalStore):
    _seed(store)
    for kind, ident in (("category_item", "memo/없음"), ("node", "../city/x"), ("attachment", "memo/../../x/y"), ("manuscript", "../../x"),
                        ("project", "../projects"), ("inbox", ".."), ("document", "../../shelf"), ("category", "..")):
        with pytest.raises(ValueError):
            store.purge_trash(U, kind, ident)
    with pytest.raises(ValueError):
        store.purge_trash(U, "everything", "x")
    assert store.get_category("alice", "memo") is not None and (store.root / "users" / U / "shelf").exists()


def test_web_purge_one_and_empty_with_in_page_confirm(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    setup = LocalStore(data_dir)
    ids = _seed(setup)
    _seed(setup, "bob")
    setup.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get("/login?next=/shelf/p/city/trash").text
        csrf = _csrf(page)
        assert "되살릴 수 없습니다. 영구 삭제할까요?" in page and "백업에는 최대 1년까지 남을 수 있습니다." in page
        assert '<summary class="btn quiet">휴지통 비우기</summary>' in page and page.count('<summary class="btn quiet">영구 삭제</summary>') >= 5
        assert "confirm(" not in page and "alert(" not in page  # 브라우저 확인 창은 쓰지 않는다
        assert "책 「버린 책」" in page and "올린 문서 「도시」 · 2장" in page and "올린 문서에서 만든 문서 「출처 확인 문서」" in page
        assert "되살리기는 운영자에게 알려 주세요." in page
        # 다른 프로젝트·다른 사용자의 것은 이 화면에서 지우지 못한다
        assert "err=purge" in str(c.post("/shelf/p/city/trash", data={"csrf": csrf, "purge": f"project:{ids['river']}"}).url)
        assert c.post("/shelf/p/city/trash", data={"csrf": "틀림", "purge": f"category_item:memo/{POST}"}).status_code == 403
        one = c.post("/shelf/p/city/trash", data={"csrf": csrf, "purge": f"category_item:memo/{POST}"})
        assert "영구 삭제했습니다." in one.text and "글 「버릴 글」" not in one.text
        restored = c.post("/shelf/p/city/trash", data={"csrf": csrf, "book": "oldbook"})  # 책째 옮긴 책은 웹에서 되살린다
        assert restored.url.path == "/shelf/oldbook" and "책과 함께" in restored.text
        emptied = c.post("/shelf/p/city/trash", data={"csrf": csrf, "empty": "1"})
        assert "휴지통을 비웠습니다." in emptied.text and '<p class="empty">휴지통이 비었습니다.</p>' in emptied.text
        # 프로젝트 목록의 휴지통: 프로젝트·예전 올린 파일
        listed = c.get("/shelf/trash").text
        assert "프로젝트 「강」" in listed and "올린 파일 「예전원고.docx」" in listed and "휴지통 비우기" in listed
        assert "영구 삭제했습니다." in c.post("/shelf/trash", data={"csrf": csrf, "purge": f"inbox:{ids['inbox']}"}).text
        usage_before = re.search(r'<p class="usage">([^<]+)</p>', c.get("/me/documents").text).group(1)
        assert "휴지통을 비웠습니다." in c.post("/shelf/trash", data={"csrf": csrf, "empty": "1"}).text
        usage_after = re.search(r'<p class="usage">([^<]+)</p>', c.get("/me/documents").text).group(1)
        assert usage_after != usage_before
    store = LocalStore(data_dir)
    assert store.list_trash(U) == [] and store.list_trashed_projects(U) == [] and store.list_trashed_inbox(U) == []
    assert store.list_trash("bob") and store.list_trashed_projects("bob")  # 밥의 휴지통은 그대로
    store.close()


def test_orphans_of_a_trashed_project_show_in_the_project_list_trash(server_proc):  # noqa: F811
    """프로젝트째 휴지통으로 가면 그 프로젝트의 올린 문서·만든 문서 휴지통은 프로젝트 목록의 휴지통에 보인다(영구 삭제만)."""
    base, data_dir, _ = server_proc({})
    setup = LocalStore(data_dir)
    _seed(setup)
    setup.trash_project(U, "city", "통째")
    setup.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        listed = c.get("/login?next=/shelf/trash").text
        assert "프로젝트 「도시」" in listed and "올린 문서 「도시」 · 2장" in listed and "프로젝트가 없어진 휴지통 항목입니다" in listed
        assert "책 「버린 책」" not in listed  # 책째 옮긴 책은 프로젝트와 함께 휴지통 묶음 안에
