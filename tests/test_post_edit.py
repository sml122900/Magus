"""글 고치기 되돌림(2026-10-09 저자 요청: 고칠 길이 없으면 불편).

글 보기의 '고치기' → 글쓰기와 같은 화면(제목·본문·첨부가 채워진 채) → 저장하면 글 보기로 '고쳤습니다.'
- 제목·본문·고친 시각만 파일에서 고친다. 누가(author)·이유·위치·쓸 부분·태그·칸·응답 관계·이 코드가 모르는 칸은 바이트까지 그대로.
  AI가 쓴 글을 고쳐도 'AI' 표시는 그대로(고친 사람 = 저자는 따로).
- 기존 첨부마다 ✕(빼기): 지우지 않고 휴지통으로. 프로젝트 휴지통에 "첨부 「이름」 · 글 「제목」", 되살리면 그 글로 돌아간다.
- 문헌 글은 본문(메모)·첨부만. 서지·쓸 부분·원문 확인 표시(와 그 기록)는 그대로, 인용 점검 수도 그대로.
- 다른 사용자의 글은 고치지 못하고, 뺀 첨부도 되살리지 못한다."""

from __future__ import annotations

import json

import httpx2
from test_node_trash import _hashes, _seed
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.store import CategoryItem, LocalStore, Passage

FIRST = "20261009000000000-aaaaaa"  # 「장날 메모」의 첫 글(첨부 장터.png)
AI_POST = "20261009000000006-dddddd"


def _setup(data_dir, user: str = "alice") -> dict[str, str]:
    store = LocalStore(data_dir)
    try:
        ids = _seed(store, user)
        store.put_category_item(user, CategoryItem(
            AI_POST, ids["notes"], "AI가 정리한 장날 이야기", "ai", title="장날 정리", title_by="ai", fields={"장소": "강가"},
            tags=("장날", "소금"), reason="저자가 다시 볼 것", where="2장 3쪽", passages=(Passage("소금 배", "근거", "12쪽"),),
            parent_id=FIRST, origin="대화", kind="ai", tags_by="ai"))
        store.put_attachment(user, f"{ids['notes']}/{AI_POST}", "지도.pdf", b"%PDF-1.4 demo")
        return ids
    finally:
        store.close()


def test_edit_keeps_hidden_fields_and_trashes_dropped_files(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _setup(data_dir)
    notes = ids["notes"]
    root = data_dir / "users" / "alice"
    item_path = root / "shelf" / "categories" / notes / "items" / f"{AI_POST}.json"
    raw = json.loads(item_path.read_text(encoding="utf-8"))
    raw["future_mark"] = {"keep": True}  # 이 코드가 모르는 칸도 그대로 남아야 한다
    item_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    before = json.loads(item_path.read_text(encoding="utf-8"))
    store = LocalStore(data_dir)
    [pdf] = store.list_attachments("alice", f"{notes}/{AI_POST}")
    order = [i.id for i in store.list_category_items("alice", notes)]
    store.close()
    pdf_bytes = (root / "shelf" / "categories" / notes / "files" / AI_POST / pdf.id / "지도.pdf").read_bytes()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        view = c.get(f"/login?next=/shelf/{notes}/{AI_POST}").text
        csrf = _csrf(view)
        # 글 보기: '고치기'가 🗑 휴지통으로 옆에(같은 크기의 단추)
        assert (f'<div class="acts post-acts"><a class="btn quiet" href="/shelf/{notes}/{AI_POST}/edit"><span aria-hidden="true">✎</span> 고치기</a>'
                '<details class="del">') in view
        form = c.get(f"/shelf/{notes}/{AI_POST}/edit").text
        assert 'name="title" value="장날 정리"' in form and ">AI가 정리한 장날 이야기</textarea>" in form
        assert f'name="drop" value="{pdf.id}"' in form and "지도.pdf" in form and "✕ 빼기" in form
        assert 'name="files" multiple' in form and 'name="reason"' not in form and "저자가 다시 볼 것" not in form
        assert '<span aria-current="page">고치기</span>' in form  # 위치 표시
        assert c.post(f"/shelf/{notes}/{AI_POST}/edit", data={"csrf": "틀림", "content": "x"}).status_code == 403
        done = c.post(f"/shelf/{notes}/{AI_POST}/edit", data={"csrf": csrf, "title": "장날 <정리>", "content": "저자가 고친 이야기",
                                                              "drop": pdf.id, "reason": "바꾸려는 시도"},
                      files=[("files", ("새 사진.png", b"\x89PNG new", "image/png"))])
        assert str(done.url).endswith(f"/shelf/{notes}/{AI_POST}?done=edited") and '<p class="msg">고쳤습니다.</p>' in done.text
        assert "<h1>장날 &lt;정리&gt;</h1>" in done.text and "저자가 고친 이야기" in done.text
        assert "AI가 쓴 글" in done.text and "제목은 AI가 지음" not in done.text  # 'AI' 표시는 그대로, 제목은 이제 저자가 지음
        assert 'alt="새 사진.png"' in done.text and "지도.pdf" not in done.text
        board = c.get(f"/shelf/{notes}").text  # 목록 정렬은 그대로(만든 순서, 최신 위)
        assert board.index(f"/shelf/{notes}/{AI_POST}") < board.index(f"/shelf/{notes}/{FIRST}")
        # 뺀 첨부는 프로젝트 휴지통에: "첨부 「이름」 · 글 「제목」" → 되살리면 그 글로
        trash = c.get("/shelf/p/book/trash").text
        assert "첨부 「지도.pdf」 · 글 「장날 &lt;정리&gt;」" in trash
        assert f'name="attachment" value="{notes}/{AI_POST}/{pdf.id}"' in trash
        assert "지도.pdf" not in c.get("/shelf/p/common/trash").text  # 다른 프로젝트 휴지통에는 없다
        back = c.post("/shelf/p/book/trash", data={"csrf": csrf, "attachment": f"{notes}/{AI_POST}/{pdf.id}"})
        assert str(back.url).endswith(f"/shelf/{notes}/{AI_POST}?done=restored") and "지도.pdf" in back.text
        assert '<p class="empty">휴지통이 비었습니다.</p>' in c.get("/shelf/p/book/trash").text
        # 빈 글로는 저장하지 않는다(칸·쓸 부분이 있으면 그것으로 저장된다: 이 글은 칸이 있다)
        empty_try = c.post(f"/shelf/{notes}/{FIRST}/edit", data={"csrf": csrf, "title": "", "content": " ",
                                                                  "drop": [a.id for a in _files(data_dir, notes, FIRST)]})
        assert empty_try.status_code == 400 and "제목이나 본문을 적어 주세요." in empty_try.text
    after = json.loads(item_path.read_text(encoding="utf-8"))
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    assert changed == {"title", "title_by", "content", "updated_at", "edited_at", "edited_by"}
    assert after["author"] == "ai" and after["title_by"] == "author" and after["edited_by"] == "author" and after["edited_at"]
    assert after["future_mark"] == {"keep": True} and after["passages"] == before["passages"] and after["reason"] == "저자가 다시 볼 것"
    restored = root / "shelf" / "categories" / notes / "files" / AI_POST / pdf.id / "지도.pdf"
    assert restored.read_bytes() == pdf_bytes  # 되살린 첨부는 바이트 그대로
    assert not list((root / "trash" / "shelf" / "attachments").rglob("*.trash.json"))
    store = LocalStore(data_dir)
    assert [i.id for i in store.list_category_items("alice", notes)] == order
    assert store.get_category_item("alice", notes, FIRST).content == "강가 장날의 소금 장수"  # 400이면 아무것도 바뀌지 않는다
    store.reindex()  # 파일이 원본이다
    again = store.get_category_item("alice", notes, AI_POST)
    assert (again.author, again.edited_by, again.tags, again.where) == ("ai", "author", ("장날", "소금"), "2장 3쪽")
    store.close()


def test_long_post_from_chat_is_not_cut_when_edited(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _setup(data_dir)
    long = "가" * 25_000  # 대화로 넣은 긴 글(웹 글쓰기 한도 2만 자보다 길다)
    store = LocalStore(data_dir)
    store.put_category_item("alice", CategoryItem("20261009000000008-eeeeee", ids["notes"], long, "me", title="긴 글"))
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        form = c.get(f"/login?next=/shelf/{ids['notes']}/20261009000000008-eeeeee/edit").text
        assert 'data-count-max="25000"' in form
        c.post(f"/shelf/{ids['notes']}/20261009000000008-eeeeee/edit", data={"csrf": _csrf(form), "title": "긴 글 고침", "content": long})
    store = LocalStore(data_dir)
    item = store.get_category_item("alice", ids["notes"], "20261009000000008-eeeeee")
    assert item.title == "긴 글 고침" and item.content == long
    store.close()


def _files(data_dir, book: str, item: str):
    store = LocalStore(data_dir)
    try:
        return store.list_attachments("alice", f"{book}/{item}")
    finally:
        store.close()


def test_edit_source_post_keeps_check_and_citation_counts(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    _setup(data_dir)
    store = LocalStore(data_dir)
    refs_book = next(c.id for c in store.list_categories("alice") if c.name == "읽은 논문")
    store.set_ref_status("alice", "clack2012", "unverified", via="chat")
    store.set_ref_status("alice", "clack2012", "verified", via="chat")  # status_by 기록이 생긴다
    counts = [(ch.number, ch.unverified_cite_count) for ch in store.list_chapters("alice", "book")]
    store.close()
    folder = data_dir / "users" / "alice" / "shelf" / "melchior" / "clack2012"
    bib_before = json.loads((folder / "bib.json").read_text(encoding="utf-8"))
    passages_before = (folder / "passages.json").read_bytes()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        view = c.get(f"/login?next=/shelf/{refs_book}/clack2012").text
        csrf = _csrf(view)
        assert f'<a class="btn quiet" href="/shelf/{refs_book}/clack2012/edit">' in view and 'class="del"' not in view  # 문헌 글: 🗑 없음
        form = c.get(f"/shelf/{refs_book}/clack2012/edit").text
        assert '<h2 class="ref-title">' in form and 'name="title"' not in form and 'type="checkbox" name="checked"' not in form
        done = c.post(f"/shelf/{refs_book}/clack2012/edit", data={"csrf": csrf, "content": "다시 읽을 것"},
                      files=[("files", ("원문.pdf", b"%PDF-1.4 x", "application/pdf"))])
        assert '<p class="msg">고쳤습니다.</p>' in done.text and "다시 읽을 것" in done.text and "원문.pdf" in done.text
    bib_after = json.loads((folder / "bib.json").read_text(encoding="utf-8"))
    assert bib_after["bib"] == {**bib_before["bib"], "memo": "다시 읽을 것"}
    assert {k: v for k, v in bib_after.items() if k not in ("bib", "updated_at")} == \
        {k: v for k, v in bib_before.items() if k not in ("bib", "updated_at")}  # 원문 확인 표시·그 기록·책·프로젝트 그대로
    assert (folder / "passages.json").read_bytes() == passages_before
    store = LocalStore(data_dir)
    assert store.get_ref("alice", "clack2012").status == "verified"
    assert [(ch.number, ch.unverified_cite_count) for ch in store.list_chapters("alice", "book")] == counts
    store.close()


def test_restore_attachment_needs_its_post(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    ids = _setup(data_dir)
    notes = ids["notes"]
    store = LocalStore(data_dir)
    [png] = store.list_attachments("alice", f"{notes}/{FIRST}")
    assert store.trash_attachment("alice", f"{notes}/{FIRST}", png.id, "웹에서 뺌")
    store.trash_item_with_replies("alice", notes, FIRST, "웹 게시판에서 옮김")  # 글도 휴지통으로
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        trash = c.get("/login?next=/shelf/p/book/trash").text
        csrf = _csrf(trash)
        assert "첨부 「장터.png」 · 글 「강가 장날의 소금 장수」" in trash  # 글이 휴지통에 있어도 이름은 보인다
        tried = c.post("/shelf/p/book/trash", data={"csrf": csrf, "attachment": f"{notes}/{FIRST}/{png.id}"})
        assert "그 첨부의 글이 휴지통에 있어 되살리지 못했습니다. 글을 먼저 되살려 주세요." in tried.text
        c.post("/shelf/p/book/trash", data={"csrf": csrf, "item": f"{notes}/{FIRST}"})
        back = c.post("/shelf/p/book/trash", data={"csrf": csrf, "attachment": f"{notes}/{FIRST}/{png.id}"})
        assert str(back.url).endswith(f"/shelf/{notes}/{FIRST}?done=restored") and 'alt="장터.png"' in back.text


def test_other_user_cannot_edit_or_restore_attachments(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    ids = _setup(data_dir, "alice")
    mine = _setup(data_dir, "bob")  # 같은 글 id를 밥도 쓴다(책 id는 사람마다 다르다)
    store = LocalStore(data_dir)
    [png] = store.list_attachments("alice", f"{ids['notes']}/{FIRST}")
    store.trash_attachment("alice", f"{ids['notes']}/{FIRST}", png.id, "웹에서 뺌")
    alice_refs = next(c.id for c in store.list_categories("alice") if c.name == "읽은 논문")
    store.close()
    alice_before = _hashes(data_dir / "users" / "alice")
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        csrf = _csrf(bob.get("/shelf").text)
        for path in (f"/shelf/{ids['notes']}/{AI_POST}/edit", f"/shelf/{alice_refs}/clack2012/edit"):
            assert bob.get(path).status_code == 404
            assert bob.post(path, data={"csrf": csrf, "content": "침입"}).status_code == 404
        tried = bob.post("/shelf/p/book/trash", data={"csrf": csrf, "attachment": f"{ids['notes']}/{FIRST}/{png.id}"})
        assert tried.status_code == 303 and "err=missing" in tried.headers["location"]
        assert "장터.png" not in bob.get("/shelf/p/book/trash").text
        own = bob.post(f"/shelf/{mine['notes']}/{AI_POST}/edit", data={"csrf": csrf, "title": "밥", "content": "밥이 고침"})
        assert own.status_code == 303
    assert _hashes(data_dir / "users" / "alice") == alice_before
    store = LocalStore(data_dir)
    assert store.get_category_item("alice", ids["notes"], AI_POST).content == "AI가 정리한 장날 이야기"
    assert store.get_category_item("bob", mine["notes"], AI_POST).content == "밥이 고침"
    store.close()
