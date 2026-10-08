"""웹 책장에서 글 고치기와 휴지통(2026-10-06 사용자 요청 → #96: 모든 책의 글).

자기 책장의 글만, 모든 POST는 CSRF, 휴지통은 확인 화면을 한 번 거친다. AI가 쓴 글을 저자가 고치면
처음 쓴 사람(author=ai)은 그대로 두고 고친 사람(edited_by=author)과 시각을 따로 남긴다.
옛 주소(/shelf/ideas…)는 이전으로 생긴 책(ideas-<프로젝트>)으로 넘어간다.
"""

from __future__ import annotations

import json
import re

import httpx2
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.store import CategoryItem, LocalStore

AI = "20261006000000001-aaaaab"
ME = "20261006000000000-aaaaaa"
IDEAS = "ideas-common"  # 옛 기본 책 「생각」을 이전한 책의 id 모양(#96)


def _seed(data_dir, user: str = "alice") -> str:
    store = LocalStore(data_dir)
    store.create_category(user, "생각", "blank", "#1f2f5c", (), "common", category_id=IDEAS)
    store.put_category_item(user, CategoryItem(ME, IDEAS, "물가는 궁지다", "me"))
    store.put_category_item(user, CategoryItem(AI, IDEAS, "그 관점은 흥미롭습니다", "ai", origin="대화", parent_id=ME))
    c = store.create_category(user, "사례", "case", "#b3261e", ("시기", "장소", "출처"))
    store.put_category_item(user, CategoryItem("20261006000000002-cccccc", c.id, "Claude가 쓴 요약", "ai", "요약", "ai",
                                               {"시기": "1850년대"}))
    styles = store.create_category(user, "문체", "blank", "#6e1f2f", (), "common")
    store.put_category_item(user, CategoryItem("20261006000000003-dddddd", styles.id, "짧다.", "me", reason="짧은 호흡"))
    store.close()
    return c.id


def _book_id(data_dir, name: str) -> str:
    store = LocalStore(data_dir)
    try:
        return next(c.id for c in store.list_categories("alice") if c.name == name)
    finally:
        store.close()


def test_edit_and_trash_on_the_shelf(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    cid = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        opened = c.get("/login?next=/shelf/ideas")  # 예전 주소: 이전으로 생긴 책의 주소로 넘어간다(#93·#96)
        listed, ideas = opened.text, opened.url.path
        csrf = _csrf(listed)
        assert ideas == f"/shelf/{IDEAS}"
        assert f'<a class="post" href="{ideas}/{AI}">' in listed
        form = c.get(f"/shelf/ideas/{AI}/edit").text  # 옛 주소의 고치기도 그 책으로
        assert ">그 관점은 흥미롭습니다</textarea>" in form and 'name="files" multiple' in form  # 제목·본문·첨부(#97)
        assert 'name="reason"' not in form and 'name="where"' not in form
        assert c.post(f"{ideas}/{AI}/edit", data={"csrf": "틀림", "content": "x"}).status_code == 403
        assert c.post(f"{ideas}/{AI}/edit", data={"csrf": csrf, "title": "", "content": "  "}).status_code == 400
        done = c.post(f"{ideas}/{AI}/edit", data={"csrf": csrf, "title": "관점", "content": "그 관점은 <b>새롭다</b>",
                                                  "reason": "다시 볼 것"})
        assert str(done.url).endswith(f"{ideas}/{AI}?done=edited") and "<p class=\"msg\">저장했습니다.</p>" in done.text
        assert "그 관점은 &lt;b&gt;새롭다&lt;/b&gt;" in done.text and "다시 볼 것" not in done.text  # 웹은 제목·본문만 고친다
        # 문체도 여느 책의 글이라 고칠 수 있다(#96). 이유는 화면에 없어도 파일에 그대로(#97)
        style_book = _book_id(data_dir, '문체')
        style_form = c.get(f"/shelf/{style_book}/20261006000000003-dddddd/edit")
        assert style_form.status_code == 200 and "짧은 호흡" not in style_form.text
        c.post(f"/shelf/{style_book}/20261006000000003-dddddd/edit", data={"csrf": csrf, "title": "", "content": "짧다. 아주."})
        # 책의 글: 칸은 화면에서 고치지 않아도 그대로, AI가 지은 제목을 그대로 두면 'AI 제목'도 그대로
        item = c.post(f"/shelf/{cid}/20261006000000002-cccccc/edit",
                      data={"csrf": csrf, "title": "요약", "content": "저자가 다듬은 요약", "f:시기": "1860년대", "f:장소": "강가"}).text
        assert "<p>시기: 1850년대</p>" in item and "장소: 강가" not in item  # 칸은 본문의 일부로 보이고, 웹에서는 바꾸지 않는다
        assert "<h1>요약</h1>" in item and "제목은 AI가 지음" in item
        # 휴지통: 확인 화면 한 번, 이 글에 응답한 글도 함께
        confirm = c.get(f"{ideas}/{ME}/trash").text
        assert "물가는 궁지다" in confirm and "응답한 글 1" in confirm
        assert c.post(f"{ideas}/{ME}/trash", data={"csrf": "틀림"}).status_code == 403
        gone = c.post(f"{ideas}/{ME}/trash", data={"csrf": csrf})
        assert str(gone.url).endswith(f"{ideas}?done=trashed") and "휴지통으로 옮겼습니다." in gone.text
        assert c.get(f"{ideas}/{AI}").status_code == 404
        c.post(f"/shelf/{cid}/20261006000000002-cccccc/trash", data={"csrf": csrf})
        assert c.get(f"/shelf/{cid}/20261006000000002-cccccc").status_code == 404
    folder = data_dir / "users" / "alice"
    reply = json.loads((folder / "trash" / "shelf" / "category-items" / IDEAS / f"{AI}.json").read_text(encoding="utf-8"))
    assert reply["author"] == "ai" and reply["edited_by"] == "author" and reply["title_by"] == "author" and reply["edited_at"]
    assert reply["_trash"]["with"] == ME and reply["origin"] == "대화" and reply["parent_id"] == ME  # 화면에 없는 칸도 그대로
    trashed = json.loads((folder / "trash" / "shelf" / "category-items" / cid / "20261006000000002-cccccc.json").read_text(encoding="utf-8"))
    assert trashed["author"] == "ai" and trashed["edited_by"] == "author" and trashed["title_by"] == "ai"
    assert trashed["fields"] == {"시기": "1850년대"}  # 웹에서 고쳐도 칸은 지우지 않는다(#97)
    style = json.loads((folder / "shelf" / "categories" / _book_id(data_dir, "문체") / "items" / "20261006000000003-dddddd.json")
                       .read_text(encoding="utf-8"))
    assert style["content"] == "짧다. 아주." and style["reason"] == "짧은 호흡"
    store = LocalStore(data_dir)  # 되살리면 함께 옮긴 응답 글도 함께
    assert store.restore_trash("alice", "category_item", f"{IDEAS}/{ME}") == [f"{IDEAS}/{ME}", f"{IDEAS}/{AI}"]
    store.close()


def test_cannot_edit_or_trash_other_users_items(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    _seed(data_dir, "alice")
    bob_cid = _seed(data_dir, "bob")  # 같은 책 id·글 id를 밥도 쓴다
    before = {p: p.read_bytes() for p in (data_dir / "users" / "bob").rglob("*.json")}
    with httpx2.Client(base_url=base, timeout=120) as alice:
        assert _login(alice, issuer_state, "sub-alice").status_code == 303
        csrf = _csrf(alice.get("/shelf").text)
        for path in (f"/shelf/{bob_cid}/20261006000000002-cccccc/edit", f"/shelf/{bob_cid}/20261006000000002-cccccc/trash"):
            assert alice.get(path).status_code == 404
            assert alice.post(path, data={"csrf": csrf, "content": "침입"}).status_code == 404
        # 같은 id라도 앨리스가 고치면 앨리스의 것만 바뀐다
        alice.post(f"/shelf/{IDEAS}/{ME}/edit", data={"csrf": csrf, "content": "앨리스가 고침"})
    after = {p: p.read_bytes() for p in (data_dir / "users" / "bob").rglob("*.json")}
    assert before == after
    store = LocalStore(data_dir)
    assert store.get_category_item("alice", IDEAS, ME).content == "앨리스가 고침"
    assert store.get_category_item("bob", IDEAS, ME).content == "물가는 궁지다"
    store.reindex()  # 고친 사람·시각은 파일이 원본이다
    assert store.get_category_item("alice", IDEAS, ME).edited_by == "author" and store.get_category_item("bob", IDEAS, ME).edited_by is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT.*Z", store.get_category_item("alice", IDEAS, ME).edited_at or "")
    store.close()
