"""웹 책장에서 생각·카테고리 항목 고치기와 휴지통(2026-10-06 사용자 요청).

자기 책장의 항목만, 모든 POST는 CSRF, 휴지통은 확인 화면을 한 번 거친다. AI가 쓴 항목을 저자가 고치면
처음 쓴 사람(author=ai)은 그대로 두고 고친 사람(edited_by=author)과 시각을 따로 남긴다.
"""

from __future__ import annotations

import json
import re

import httpx2
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.store import CategoryItem, Idea, LocalStore, StyleEntry

TAGS = {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": [], "어미": "-다", "톤": "건조"}
AI = "20261006000000001-aaaaab"
ME = "20261006000000000-aaaaaa"


def _seed(data_dir, user: str = "alice") -> str:
    store = LocalStore(data_dir)
    store.add_ideas(user, [Idea(ME, "물가는 궁지다", "thought", "me"),
                           Idea(AI, "그 관점은 흥미롭습니다", "conversation", "ai", "대화", ME)])
    c = store.create_category(user, "사례", "case", "#b3261e", ("시기", "장소", "출처"))
    store.put_category_item(user, CategoryItem("20261006000000002-cccccc", c.id, "Claude가 쓴 요약", "ai", "요약", "ai",
                                               {"시기": "1850년대"}))
    store.add_style(user, StyleEntry("20261006000000003-dddddd", "짧다.", "짧은 호흡", TAGS))
    store.close()
    return c.id


def test_edit_and_trash_on_the_shelf(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    cid = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        listed = c.get("/login?next=/shelf/ideas").text
        csrf = _csrf(listed)
        assert f'<a href="/shelf/ideas/{AI}/edit">고치기</a> · <a href="/shelf/ideas/{AI}/trash">휴지통으로</a>' in listed
        assert ">고치기</a>" not in c.get("/shelf/styles").text and c.get("/shelf/styles/20261006000000003-dddddd/edit").status_code == 404
        form = c.get(f"/shelf/ideas/{AI}/edit").text
        assert "처음 쓴 사람: Claude(AI)." in form and ">그 관점은 흥미롭습니다</textarea>" in form
        assert c.post(f"/shelf/ideas/{AI}/edit", data={"csrf": "틀림", "content": "x"}).status_code == 403
        assert c.post(f"/shelf/ideas/{AI}/edit", data={"csrf": csrf, "title": "", "content": "  "}).status_code == 400
        done = c.post(f"/shelf/ideas/{AI}/edit", data={"csrf": csrf, "title": "관점", "content": "그 관점은 <b>새롭다</b>"})
        assert str(done.url).endswith(f"/shelf/ideas/{AI}?done=edited") and "<p class=\"msg\">고쳤습니다.</p>" in done.text
        assert "그 관점은 &lt;b&gt;새롭다&lt;/b&gt;" in done.text and "저자가 고침(" in done.text
        # 카테고리 항목: 칸까지 고치고, AI가 지은 제목을 그대로 두면 'AI가 지은 제목'도 그대로
        item = c.post(f"/shelf/{cid}/20261006000000002-cccccc/edit",
                      data={"csrf": csrf, "title": "요약", "content": "저자가 다듬은 요약", "f:시기": "1860년대", "f:장소": "강가"}).text
        assert "<dt>시기</dt><dd>1860년대</dd><dt>장소</dt><dd>강가</dd>" in item and "누가: Claude가 쓴 글" in item
        assert '<span class="t">요약<span class="tag">AI가 지은 제목</span></span>' in item and "저자가 고침(" in item
        # 휴지통: 확인 화면 한 번, 생각이면 응답한 AI 발화도 함께
        confirm = c.get(f"/shelf/ideas/{ME}/trash").text
        assert "이 항목을 휴지통으로 옮길까요?" in confirm and "이 생각에 응답한 AI 발화 1건도 함께 옮겨집니다." in confirm
        assert c.post(f"/shelf/ideas/{ME}/trash", data={"csrf": "틀림"}).status_code == 403
        gone = c.post(f"/shelf/ideas/{ME}/trash", data={"csrf": csrf})
        assert str(gone.url).endswith("/shelf/ideas?done=trashed") and "항목을 휴지통으로 옮겼습니다." in gone.text
        assert c.get(f"/shelf/ideas/{AI}").status_code == 404
        c.post(f"/shelf/{cid}/20261006000000002-cccccc/trash", data={"csrf": csrf})
        assert c.get(f"/shelf/{cid}/20261006000000002-cccccc").status_code == 404
    folder = data_dir / "users" / "alice"
    reply = json.loads((folder / "trash" / "shelf" / "casper" / f"{AI}.json").read_text(encoding="utf-8"))
    assert reply["author"] == "ai" and reply["edited_by"] == "author" and reply["title_by"] == "author" and reply["edited_at"]
    trashed = json.loads((folder / "trash" / "shelf" / "category-items" / cid / "20261006000000002-cccccc.json").read_text(encoding="utf-8"))
    assert trashed["author"] == "ai" and trashed["edited_by"] == "author" and trashed["title_by"] == "ai"
    assert trashed["fields"] == {"시기": "1860년대", "장소": "강가"}


def test_cannot_edit_or_trash_other_users_items(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    _seed(data_dir, "alice")
    bob_cid = _seed(data_dir, "bob")  # 같은 생각 id를 밥도 쓴다
    before = {p: p.read_bytes() for p in (data_dir / "users" / "bob").rglob("*.json")}
    with httpx2.Client(base_url=base, timeout=120) as alice:
        assert _login(alice, issuer_state, "sub-alice").status_code == 303
        csrf = _csrf(alice.get("/shelf").text)
        for path in (f"/shelf/{bob_cid}/20261006000000002-cccccc/edit", f"/shelf/{bob_cid}/20261006000000002-cccccc/trash"):
            assert alice.get(path).status_code == 404
            assert alice.post(path, data={"csrf": csrf, "content": "침입"}).status_code == 404
        # 같은 id라도 앨리스가 고치면 앨리스의 것만 바뀐다
        alice.post(f"/shelf/ideas/{ME}/edit", data={"csrf": csrf, "content": "앨리스가 고침"})
    after = {p: p.read_bytes() for p in (data_dir / "users" / "bob").rglob("*.json")}
    assert before == after
    store = LocalStore(data_dir)
    assert store.get_ideas("alice", [ME])[ME].text == "앨리스가 고침" and store.get_ideas("bob", [ME])[ME].text == "물가는 궁지다"
    store.reindex()  # 고친 사람·시각은 파일이 원본이다
    assert store.get_ideas("alice", [ME])[ME].edited_by == "author" and store.get_ideas("bob", [ME])[ME].edited_by is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT.*Z", store.get_ideas("alice", [ME])[ME].edited_at or "")
    store.close()
