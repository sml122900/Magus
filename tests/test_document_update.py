"""내 정보 › 문서 업데이트(2026-10-10, docs/decisions/document-update.md).

- 목록: 게시판 첨부 문서 + 예전 올린 파일, 새것부터, 줄마다 프로젝트·노드·책·글. 찾기(앞 글자·가운데 글자).
- 바꾸기: 같은 첨부 id 자리에 새 파일, 이전 파일은 휴지통(되살리기), 글 제목이 이전 파일 이름이면 새 이름으로, 첨부 글자는 새 파일로.
- 올린 문서의 원본이면 바꾸기 = 수정본(먼저 수정본을 만들고 성공해야 파일을 바꾼다). 같은 파일·다른 책 같으면 멈춤(아무것도 바뀌지 않음).
- 글 고치기의 바꾸기도 같은 동작. 옛 올리기·지우기 POST는 410. 수정본은 프로젝트 제목을 바꾸지 않는다.
"""

from __future__ import annotations

import io
import re
import urllib.parse
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_docx_features import Manuscript
from test_reupload import edition
from test_web import _csrf, attach_files, server_proc  # noqa: F401 - 픽스처

from magus.book.importer import import_manuscript
from magus.docupdate import UpdateError, find_rows, list_documents, update_document
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

pytestmark = pytest.mark.anyio
U = "alice"
ITEM = "20261010000000001-aaaaaa"
LIMITS = {"max_attach": 20_000_000, "max_upload": 50_000_000, "max_user": 1_000_000_000}


def _post(store: LocalStore, title: str | None = "회의록", floor: str = "common", book: str = "bk") -> str:
    if store.get_category(U, book) is None:
        store.create_category(U, "자료", "blank", "#1f2f5c", (), floor, category_id=book)
    store.put_category_item(U, CategoryItem(ITEM, book, "본문", "me", title, "author" if title else None))
    return f"{book}/{ITEM}"


def _update(store: LocalStore, key: str, chosen: str, data: bytes, stem: str | None = None, **more):
    return update_document(store, U, key, chosen, io.BytesIO(data), len(data), stem, **LIMITS, **more)


@pytest.mark.parametrize(("title", "after"), [("회의록", "새 회의록"), ("회의록.txt", "새 회의록.txt"), ("다른 제목", "다른 제목")])
def test_update_in_place_title_rule_text_and_trash(store: LocalStore, title: str, after: str):
    owner = _post(store, title)
    old = store.put_attachment(U, owner, "회의록.txt", "옛 글자 물안개".encode())
    store.attachment_text(U, owner, old.id)
    result = _update(store, f"att:{old.id}", "C:\\fakepath\\아무 이름.txt", "새 글자 해오름".encode(), stem="새 회의록")
    # 같은 자리(같은 첨부 id), 저자가 고친 이름, 확장자는 고른 파일 것
    assert [(a.id, a.name) for a in store.list_attachments(U, owner)] == [(old.id, "새 회의록.txt")]
    assert store.get_category_item(U, "bk", ITEM).title == after and result.title_changed is (title != "다른 제목")
    assert store.attachment_text(U, owner, old.id, make=False)[1] == "새 글자 해오름"  # 첨부 글자도 새 파일로
    found = {c.owner_id for c in store.search_substring(U, ["attach_text"], "해오름", 10)}
    assert found == {owner} and not store.search_substring(U, ["attach_text"], "물안개", 10)
    # 이전 파일은 첨부 휴지통 → 되살리면 그 글에 첨부 하나로(지금 첨부와 겹치지 않는다)
    [trashed] = [t for t in store.list_trash(U) if t.kind == "attachment"]
    assert trashed.preview == "회의록.txt" and trashed.note.startswith("문서 업데이트")
    store.restore_trash(U, "attachment", trashed.id)
    assert sorted(a.name for a in store.list_attachments(U, owner)) == ["새 회의록.txt", "회의록.txt"]
    assert result.trash == "/shelf/p/common/trash"


def test_names_types_and_limits_refuse_without_changes(store: LocalStore):
    owner = _post(store)
    old = store.put_attachment(U, owner, "회의록.txt", b"x")
    for chosen, stem, code in (("a.txt", "나쁜:이름", "name"), ("a.txt", "../밖", "name"), ("그림.png", None, "type"),
                               ("a.exe", None, "type")):
        with pytest.raises(UpdateError) as e:
            _update(store, f"att:{old.id}", chosen, b"y", stem)
        assert e.value.code == code, (chosen, stem)
    with pytest.raises(UpdateError) as e:
        update_document(store, U, f"att:{old.id}", "a.txt", io.BytesIO(b"y" * 30), 30, None, max_attach=10, max_upload=50, max_user=10**9)
    assert e.value.code == "big"
    with pytest.raises(UpdateError) as e:
        _update(store, "att:20261010000000000-ffffff", "a.txt", b"y")
    assert e.value.code == "missing"
    assert [(a.name, store.attachment_path(U, owner, a.id)[0].read_bytes()) for a in store.list_attachments(U, owner)] == [("회의록.txt", b"x")]
    # 이름 칸에 확장자까지 적어도 한 번만, 확장자는 고른 파일 것
    assert _update(store, f"att:{old.id}", "고른.md", b"z", stem="새 이름.md").new_name == "새 이름.md"


def test_manuscript_attachment_update_is_a_revision(store: LocalStore, tmp_path: Path):
    owner = _post(store, "원고", floor="common")
    e1 = edition(tmp_path / "e1.docx", 1)
    att = store.put_attachment(U, owner, "원고.docx", e1.read_bytes())
    import_manuscript(store, U, e1, project_id="b")
    rows = list_documents(store, U)
    assert rows[0].source is not None and rows[0].source.label() == "「가상 책」 올린 문서 원본 · 처음 올린 문서 E1"
    # 같은 파일 → 멈춤(아무것도 바뀌지 않음)
    with pytest.raises(UpdateError) as same:
        _update(store, f"att:{att.id}", "원고.docx", e1.read_bytes())
    assert same.value.code == "same" and "이미 올린 파일입니다" in str(same.value) and len(store.list_editions(U, "b")) == 1
    # 다른 책 같은 파일 → 멈춤, '같은 책이 맞습니다'(force)면 올린다
    other = Manuscript().heading("제1장 전혀 다른").para("글.").heading("제2장 책").para("글.").bibliography().save(tmp_path / "x.docx")
    with pytest.raises(UpdateError) as far:
        _update(store, f"att:{att.id}", "x.docx", other.read_bytes())
    assert far.value.code == "overlap" and "같은 책이 맞습니다" in str(far.value)
    assert store.attachment_path(U, owner, att.id)[0].read_bytes() == e1.read_bytes() and len(store.list_editions(U, "b")) == 1
    # 고친 원고 → 수정본 E2, 파일도 바뀜, 프로젝트 제목은 그대로(문서 속 부제가 달라도)
    e2 = edition(tmp_path / "e2.docx", 2)
    result = _update(store, f"att:{att.id}", "e2.docx", e2.read_bytes(), stem="원고 10월")
    assert result.revision is not None and result.revision.edition == 2 and result.project_id == "b"
    assert (len(result.revision.changed), len(result.revision.added), len(result.revision.removed)) == (1, 1, 1)
    assert store.attachment_path(U, owner, att.id)[0].name == "원고 10월.docx" and store.get_category_item(U, "bk", ITEM).title == "원고 10월"
    project = store.get_project(U, "b")
    assert (project.title, project.subtitle) == ("가상 책", "첫 부제") and "문서 제목이 다릅니다(바꾸지 않음)" in result.revision.full()
    assert list_documents(store, U)[0].source.label() == "「가상 책」 올린 문서 원본 · 수정본 E2"
    # 원본은 docx·pdf로만
    with pytest.raises(UpdateError) as typ:
        _update(store, f"att:{att.id}", "메모.txt", b"x")
    assert typ.value.code == "type"


def test_old_upload_is_listed_and_updated_into_a_revision(store: LocalStore, tmp_path: Path):
    e1 = edition(tmp_path / "e1.docx", 1)
    inbox = store.root / "users" / U / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "원고.docx").write_bytes(e1.read_bytes())
    (inbox / "메모.md").write_text("메모", encoding="utf-8")
    import_manuscript(store, U, inbox / "원고.docx", project_id="b")
    rows = {r.key: r for r in list_documents(store, U)}
    assert rows["inbox:원고.docx"].source.label() == "「가상 책」 올린 문서 원본 · 처음 올린 문서 E1" and rows["inbox:메모.md"].source is None
    (inbox / "다른.docx").write_bytes(b"x")
    with pytest.raises(UpdateError) as taken:  # 다른 예전 파일 이름으로 덮지 않는다
        _update(store, "inbox:원고.docx", "e2.docx", edition(tmp_path / "e2.docx", 2).read_bytes(), stem="다른")
    assert taken.value.code == "taken" and len(store.list_editions(U, "b")) == 1
    (inbox / "다른.docx").unlink()
    result = _update(store, "inbox:원고.docx", "e2.docx", edition(tmp_path / "e2.docx", 2).read_bytes(), stem="원고")
    assert result.revision.edition == 2 and result.trash == "/shelf/trash"
    assert sorted(p.name for p in inbox.iterdir()) == ["메모.md", "원고.docx"]  # 같은 이름 자리에 새 파일
    [(trash_id, old, record)] = store.list_trashed_inbox(U)
    assert old.name == "원고.docx" and record["note"].startswith("문서 업데이트")
    with pytest.raises(ValueError, match="taken"):  # 같은 이름이 있으면 되살리지 않는다
        store.restore_inbox(U, trash_id)
    (inbox / "원고.docx").rename(inbox / "원고-E2.docx")
    assert store.restore_inbox(U, trash_id) == "원고.docx" and (inbox / "원고.docx").read_bytes() == e1.read_bytes()


def test_search_rows(store: LocalStore):
    owner = _post(store, "장날 답사 기록", floor="common")
    store.put_attachment(U, owner, "답사지도_Jongno.pdf", b"%PDF-1.4 x")
    store.put_attachment(U, owner, "인터뷰.docx", b"PK x")
    rows = list_documents(store, U)
    assert [r.name for r in rows] == ["인터뷰.docx", "답사지도_Jongno.pdf"]  # 새것부터
    assert [r.name for r in find_rows(rows, "jon")] == ["답사지도_Jongno.pdf"]  # 가운데 글자·대소문자 무시
    assert [r.name for r in find_rows(rows, "인터")] == ["인터뷰.docx"]  # 앞 글자
    assert len(find_rows(rows, "답사 기록")) == 2 and len(find_rows(rows, "자료")) == 2  # 글 제목·책 이름
    assert find_rows(rows, "없는말") == []


def test_web_documents_page_update_and_old_upload_gone(server_proc, tmp_path: Path):  # noqa: F811
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/me").text)
        assert '<a href="/me/documents">문서 업데이트</a>' in c.get("/me").text and "/me/files" not in c.get("/me").text
        made = c.post("/shelf/projects", data={"csrf": csrf, "title": "가상 책"})
        pid = urllib.parse.urlparse(str(made.url)).path.split("/")[-1]
        e1 = edition(tmp_path / "e1.docx", 1)
        ids = attach_files(c, data_dir, csrf, pid, {"원고.docx": e1.read_bytes(), "회의록.md": "물안개".encode()})
        store = LocalStore(data_dir)
        try:
            import_manuscript(store, U, store.attachment_path(U, store.find_attachment(U, ids["원고.docx"])[0], ids["원고.docx"])[0],
                              project_id=pid)
        finally:
            store.close()
        page = c.get("/me/documents").text
        assert "<h1>문서 업데이트</h1>" in page and "「가상 책」 올린 문서 원본 · 처음 올린 문서 E1" in page
        assert re.search(r'가상 책 › [^<]+ › 자료 › <a href="/shelf/[^"]+">원고</a>', page)
        assert page.count('<summary class="btn quiet">업데이트</summary>') == 2 and 'name="name"' in page and "data-stem" in page
        found = c.get("/me/documents", params={"q": "회의"}).text
        assert "「회의」 1건" in found and "회의록.md" in found and "원고.docx" not in found.split('<ol class="docs">')[1]
        # 원고 줄 업데이트 = 수정본(화면 위 한 줄과 리포트 링크). CSRF가 틀리면 403
        e2 = edition(tmp_path / "e2.docx", 2).read_bytes()
        assert c.post("/me/documents/update", data={"csrf": "x", "key": f"att:{ids['원고.docx']}"},
                      files={"file": ("e2.docx", e2)}).status_code == 403
        same = c.post("/me/documents/update", data={"csrf": csrf, "key": f"att:{ids['원고.docx']}"}, files={"file": ("e1.docx", e1.read_bytes())})
        assert same.status_code == 400 and "이미 올린 파일입니다." in same.text
        done = c.post("/me/documents/update", data={"csrf": csrf, "key": f"att:{ids['원고.docx']}", "name": "원고 10월"},
                      files={"file": ("e2.docx", e2)})
        assert "「가상 책」 수정본 E2로 올렸습니다 · 바뀐 장 1 · 새 장 1 · 빠진 장 1 · " in done.text
        assert f"/shelf/book/{pid}?tab=editions&amp;report=2" in done.text and "원고 10월.docx" in done.text
        # 보통 문서: 바꾸고 이전 파일은 프로젝트 휴지통
        swapped = c.post("/me/documents/update", data={"csrf": csrf, "key": f"att:{ids['회의록.md']}"},
                         files={"file": ("회의록 2.md", "해오름".encode())})
        assert "「회의록 2.md」로 바꿨습니다." in swapped.text and f'href="/shelf/p/{pid}/trash">휴지통</a>' in swapped.text
        assert "첨부 「회의록.md」" in c.get(f"/shelf/p/{pid}/trash").text
        # 내 정보의 올리기·지우기는 없다
        assert c.post("/inbox/upload", data={"csrf": csrf}, files={"files": ("a.md", b"a")}).status_code == 410
        assert c.post("/inbox/delete", data={"csrf": csrf, "name": "a.md"}).status_code == 410


def test_web_old_upload_trash_and_restore(server_proc, tmp_path: Path):  # noqa: F811
    base, data_dir, _ = server_proc({})
    inbox = data_dir / "users" / U / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "논문.pdf").write_bytes(b"%PDF-1.4 old")
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/me/documents").text)
        page = c.get("/me/documents").text
        assert "논문.pdf" in page and "예전에 올린 파일" in page
        done = c.post("/me/documents/update", data={"csrf": csrf, "key": "inbox:논문.pdf", "name": "논문 고친 판"},
                      files={"file": ("x.pdf", b"%PDF-1.4 new")})
        assert "「논문 고친 판.pdf」로 바꿨습니다." in done.text and 'href="/shelf/trash">휴지통</a>' in done.text
        assert sorted(p.name for p in inbox.iterdir()) == ["논문 고친 판.pdf"]
        trash = c.get("/shelf/trash").text
        assert "올린 파일 「논문.pdf」" in trash and "1개" in trash
        trash_id = re.search(r'name="inbox" value="([^"]+)"', trash).group(1)
        back = c.post("/shelf/trash", data={"csrf": csrf, "inbox": trash_id})
        assert str(back.url).endswith("/me/documents?done=restored&f=%EB%85%BC%EB%AC%B8.pdf") and "「논문.pdf」 파일을 되살렸습니다." in back.text
        assert (inbox / "논문.pdf").read_bytes() == b"%PDF-1.4 old"


def test_web_edit_form_swap_attachment(server_proc, tmp_path: Path):  # noqa: F811
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        made = c.post("/shelf/projects", data={"csrf": csrf, "title": "가상 책"})
        pid = urllib.parse.urlparse(str(made.url)).path.split("/")[-1]
        e1 = edition(tmp_path / "e1.docx", 1)
        ids = attach_files(c, data_dir, csrf, pid, {"원고.docx": e1.read_bytes(), "메모.txt": b"memo"})
        store = LocalStore(data_dir)
        try:
            owner, _ = store.find_attachment(U, ids["원고.docx"])
            import_manuscript(store, U, store.attachment_path(U, owner, ids["원고.docx"])[0], project_id=pid)
        finally:
            store.close()
        link = f"/shelf/{owner}"
        form = c.get(f"{link}/edit").text
        assert form.count('<summary class="btn quiet">바꾸기</summary>') == 2 and f'name="swap_{ids["원고.docx"]}"' in form
        # 한 번에 둘은 거절
        two = c.post(f"{link}/edit", data={"csrf": csrf, "title": "원고", "content": ""},
                     files=[(f"swap_{ids['원고.docx']}", ("a.docx", b"x")), (f"swap_{ids['메모.txt']}", ("b.txt", b"y"))])
        assert two.status_code == 400 and "첨부는 한 번에 하나만 바꿀 수 있습니다." in two.text
        # 원고 첨부를 고친 원고로 → 수정본, 글 보기에 한 줄
        e2 = edition(tmp_path / "e2.docx", 2).read_bytes()
        done = c.post(f"{link}/edit", data={"csrf": csrf, "title": "원고", "content": ""},
                      files=[(f"swap_{ids['원고.docx']}", ("e2.docx", e2))])
        assert "고쳤습니다. 「가상 책」 수정본 E2로 올렸습니다 · 바뀐 장 1" in done.text
    store = LocalStore(data_dir)
    try:
        assert store.attachment_path(U, owner, ids["원고.docx"])[0].name == "e2.docx" and len(store.list_editions(U, pid)) == 2
        assert store.get_category_item(U, *owner.split("/")).title == "e2"  # 제목이 이전 파일 이름(원고)이었으니 새 이름으로
    finally:
        store.close()


async def test_chat_outputs_after_cleanups(store: LocalStore, settings, tmp_path: Path):
    """같이 고친 것(4절): 장 상태는 웹과 같은 말, 도구 출력에 서버 내부 경로 없음, project를 준 찾기의 머리."""
    inbox = store.root / "users" / U / "inbox"
    inbox.mkdir(parents=True)
    edition(inbox / "e1.docx", 1)
    edition(inbox / "e2.docx", 2)
    async with Client(build_server(settings, store)) as c:
        first = (await c.call_tool("book_import", {"path": "e1.docx", "project_id": "b"})).content[0].text
        again = (await c.call_tool("book_import", {"path": "e2.docx", "project_id": "b", "new_edition": True})).content[0].text
        outline = (await c.call_tool("book_outline", {"project_id": "b"})).content[0].text
        read = (await c.call_tool("book_read_chapter", {"number": 1, "project_id": "b"})).content[0].text
        found = (await c.call_tool("category_search", {"query": "없는말", "project": "가상 책"})).content[0].text
    for text in (first, again):
        assert "users/" not in text and "original/" not in text and "removed/" not in text and "수정본 이력" in text
    assert "그대로 둔 것: 결정 0건, 직접 남긴 확인 요청 0건, 다른 책의 글" in again and "생각·문헌·문체" not in again
    assert "· 초안 ·" in outline and "· draft ·" not in outline and '"status": "초안"' in read
    assert found.startswith("category_search '없는말' (「가상 책」의 책): 결과 없음")


async def test_unexpected_swap_failure_logs_kind_and_stack_only(store: LocalStore, settings, monkeypatch, caplog):
    """바꾸기에서 예상 못 한 실패(문서 업데이트·글 고치기의 바꾸기, 2026-10-10): 로그에는 예외 종류와 스택만
    (파일 이름·글 내용·메일 없음), 화면은 한국어 한 줄(500). 첨부는 그대로."""
    import logging

    from magus.transports import http_app
    from magus.web import Web
    from magus.webdocs import FAILED

    owner = _post(store)
    att = store.put_attachment(U, owner, "회의록.md", "물안개 회의".encode())
    secret = "비밀원고.md 물안개 본문 alice@example.com"

    def boom(*_args, **_kwargs):
        raise OSError(secret)

    monkeypatch.setattr(LocalStore, "replace_attachment", boom)
    server = build_server(settings, store)
    web = Web.create(store, settings, "http://127.0.0.1:8000", None)
    web.register(server)
    app = http_app(server, "127.0.0.1", None, settings.max_request_bytes, web.http_error, web.body_limit)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                                  follow_redirects=True) as c:
        csrf = _csrf((await c.get("/login?next=/me/documents")).text)
        with caplog.at_level(logging.INFO, logger="magus"):
            docs = await c.post("/me/documents/update", data={"csrf": csrf, "key": f"att:{att.id}"},
                                files={"file": ("비밀원고.md", "물안개 본문".encode())})
            edit = await c.post(f"/shelf/{owner}/edit", data={"csrf": csrf, "title": "회의록", "content": "물안개 본문"},
                                files=[(f"swap_{att.id}", ("비밀원고.md", "물안개 본문".encode()))])
    for page in (docs, edit):
        assert page.status_code == 500 and FAILED in page.text
    logged = [r.getMessage() for r in caplog.records if r.name == "magus.docupdate"]
    assert len(logged) == 2 and all(r.levelno == logging.ERROR for r in caplog.records if r.name == "magus.docupdate")
    assert "(문서 업데이트)" in logged[0] and "(글 고치기 바꾸기)" in logged[1]
    for line in logged:
        assert "builtins.OSError at " in line and "docupdate.py:" in line and "test_document_update.py:" in line
        assert not any(w in line for w in ("비밀원고", "물안개", "회의록", "example.com", "alice"))
    assert store.attachment_path(U, owner, att.id)[0].read_text(encoding="utf-8") == "물안개 회의"
