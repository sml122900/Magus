"""게시판 = 제목 + 글 + 첨부(사용자 요청 #97, 2026-10-08). 웹에서 글에 파일을 여러 개 붙이고 보고 빼기,
문헌 글의 '원문 확인' 체크 하나(쓸 부분·서지는 그대로, 인용 점검 수가 바뀐다), 다른 사용자의 첨부·체크에는 닿지 못한다."""

from __future__ import annotations

import re
import urllib.parse

import httpx2
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.store import CategoryItem, LocalStore, Passage, Ref

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
NOTES = "notes-common"


def _seed(data_dir, user: str, word: str) -> None:
    store = LocalStore(data_dir)
    store.create_project(user, f"{word}의 책", project_id="b")
    store.write_chapter(user, "b", 1, f"{word}의 문장(Clack, 2012).", "x", title="하나")
    store.create_category(user, "메모", "blank", "#1f2f5c", (), "common", category_id=NOTES)
    store.create_category(user, "문헌", "blank", "#1f2f5c", (), "b", category_id="refs-b")
    store.put_ref(user, Ref(key="clack2012", status="unverified", bib={"title": "Gaining ground", "authors": "Clack, J."}, book="refs-b"),
                  passages=[Passage(f"{word}의 쓸 부분", "근거", "p.3")])
    store.put_category_item(user, CategoryItem("20261008000000000-aaaaaa", NOTES, f"{word}의 글", "me", reason="이유는 그대로"))
    from magus.melchior.check import refresh_cite_counts  # noqa: PLC0415

    refresh_cite_counts(store, user)
    store.close()


def test_write_view_edit_attachments_and_check(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({"MAX_ATTACH_MB": "0.01"})  # 첨부 한 개 10KB까지(시험용)
    _seed(data_dir, "alice", "앨리스")
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        board = c.get(f"/login?next=/shelf/{NOTES}").text
        csrf = _csrf(board)
        assert 'enctype="multipart/form-data"' in board and 'name="files" multiple accept=".pdf,' in board
        # 새 글: 제목·본문·첨부 둘
        made = c.post(f"/shelf/write/{NOTES}", data={"csrf": csrf, "title": "답사", "content": "시장 사진"},
                      files=[("files", ("C:\\fakepath\\시장.png", PNG, "image/png")), ("files", ("표.pdf", b"%PDF-1.4 x", "application/pdf"))])
        item = re.search(rf"/shelf/{NOTES}/(\d{{17}}-[0-9a-f]{{6}})$", str(made.url)).group(1)
        assert ">시장.png</a> <small>그림 · 1 KB</small>" in made.text and ">표.pdf</a> <small>PDF · 1 KB</small>" in made.text
        links = re.findall(rf'href="(/shelf/{NOTES}/{item}/files/[^"]+)"', made.text)
        assert len(links) == 2
        png = c.get(links[0], headers={"sec-fetch-dest": "document", "sec-fetch-mode": "navigate"})  # 지도로 넘기지 않는다
        assert png.status_code == 200 and png.content == PNG and png.headers["content-type"] == "image/png"
        assert png.headers["x-content-type-options"] == "nosniff" and png.headers["content-disposition"].startswith("inline")
        # 첨부만 있는 글도 된다(목록에는 파일 이름이 앞부분으로)
        only = c.post(f"/shelf/write/{NOTES}", data={"csrf": csrf, "title": "", "content": ""},
                      files={"files": ("녹취.txt", "음성 받아쓰기".encode(), "text/plain")})
        assert '<span class="t none">녹취.txt</span>' in only.text
        txt = c.get(re.search(rf'href="(/shelf/{NOTES}/[^"]+/files/[^"]+)"[^>]*>녹취.txt', only.text).group(1))
        assert txt.headers["content-disposition"].startswith("attachment") and "filename*=utf-8''" in txt.headers["content-disposition"].lower()
        # 받지 않는 형식·너무 큰 파일·많은 파일은 아무것도 저장하지 않는다
        for files, code in (([("files", ("x.svg", b"<svg/>", "image/svg+xml"))], "type"),
                            ([("files", ("x.exe", b"MZ", "application/octet-stream"))], "type"),
                            ([("files", ("큰.pdf", b"0" * 20_000, "application/pdf"))], "big"),
                            ([("files", (f"{n}.txt", b"x", "text/plain")) for n in range(11)], "many")):
            bad = c.post(f"/shelf/write/{NOTES}", data={"csrf": csrf, "title": "막혀야 함", "content": "x"}, files=files)
            assert f"error={code}" in str(bad.url) and '<p class="msg err">' in bad.text and "막혀야 함" not in bad.text, code
        assert c.post(f"/shelf/write/{NOTES}", data={"csrf": "틀림", "content": "x"}).status_code == 403
        # 고치기: 첨부 하나 빼고(휴지통으로) 하나 더하기. 이유 칸은 화면에 없어도 파일에 그대로
        edit = c.get(f"/shelf/{NOTES}/{item}/edit").text
        drop = re.findall(r'name="drop" value="([^"]+)"', edit)
        assert len(drop) == 2 and 'name="reason"' not in edit
        c.post(f"/shelf/{NOTES}/{item}/edit", data={"csrf": csrf, "title": "답사", "content": "시장 사진 둘", "drop": drop[1]},
               files={"files": ("지도.jpg", b"\xff\xd8\xff", "image/jpeg")})
        old = c.post(f"/shelf/{NOTES}/20261008000000000-aaaaaa/edit", data={"csrf": csrf, "title": "", "content": "고친 글"})
        assert "고친 글" in old.text and "이유는 그대로" not in old.text
        # 문헌 글: 원문 확인 체크 하나(누르면 바로 저장)
        refs = c.get("/shelf/refs-b").text
        assert re.search(r'action="/shelf/refs-b/clack2012/check" class="check">.*?value="1"> 원문 확인</label>', refs)
        assert "<blockquote>「앨리스의 쓸 부분」</blockquote>" in refs and "근거" not in refs
        checked = c.post("/shelf/refs-b/clack2012/check", data={"csrf": csrf, "set": "1", "checked": "1"})
        assert str(checked.url).endswith("/shelf/refs-b/clack2012?done=checked") and 'value="1" checked> 원문 확인' in checked.text
        ref_edit = c.post("/shelf/refs-b/clack2012/edit", data={"csrf": csrf, "content": "1장에 씀"},
                          files={"files": ("clack.pdf", b"%PDF-1.4", "application/pdf")})
        assert "<p>1장에 씀</p>" in ref_edit.text and ">clack.pdf</a>" in ref_edit.text
        assert c.get("/shelf/refs-b/clack2012/trash").status_code == 404  # 문헌 글은 휴지통으로 옮기지 않는다
    store = LocalStore(data_dir)
    files = store.list_attachments("alice", f"{NOTES}/{item}")
    assert [a.name for a in files] == ["시장.png", "지도.jpg"]
    assert list((data_dir / "users" / "alice" / "trash" / "shelf" / "attachments" / NOTES / item).rglob("표.pdf"))
    assert store.get_category_item("alice", NOTES, "20261008000000000-aaaaaa").reason == "이유는 그대로"
    ref = store.get_ref("alice", "clack2012")
    assert ref.status == "verified" and ref.bib["memo"] == "1장에 씀" and ref.bib["title"] == "Gaining ground"
    assert store.get_passages("alice", "clack2012") == [Passage("앨리스의 쓸 부분", "근거", "p.3")]
    assert store.list_chapters("alice", "b")[0].unverified_cite_count == 0  # 인용 점검이 확인으로 본다
    assert [a.name for a in store.list_attachments("alice", "ref:clack2012")] == ["clack.pdf"]
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get(f"/login?next=/shelf/{NOTES}").text)
        c.post("/shelf/refs-b/clack2012/check", data={"csrf": csrf, "set": "1"})  # 체크를 끄면 원문 확인 전으로
    store = LocalStore(data_dir)
    assert store.get_ref("alice", "clack2012").status == "unverified" and store.list_chapters("alice", "b")[0].unverified_cite_count == 1
    assert store.get_passages("alice", "clack2012") == [Passage("앨리스의 쓸 부분", "근거", "p.3")]  # 쓸 부분은 지우지 않는다
    store.close()


def test_attachments_and_check_are_per_user(server_proc, fake_issuer):  # noqa: F811
    """같은 책 id·글 id·문헌 key를 써도 남의 첨부는 보지도, 빼지도, 더하지도 못하고 원문 확인도 바꾸지 못한다."""
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    _seed(data_dir, "alice", "앨리스")
    _seed(data_dir, "bob", "밥")
    store = LocalStore(data_dir)
    secret = store.put_attachment("alice", f"{NOTES}/20261008000000000-aaaaaa", "비밀.pdf", b"%PDF alice-only")
    ref_file = store.put_attachment("alice", "ref:clack2012", "원문.pdf", b"%PDF alice-ref")
    store.close()
    before = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*") if p.is_file()}
    url = f"/shelf/{NOTES}/20261008000000000-aaaaaa/files/{secret.id}"
    ref_url = f"/shelf/refs-b/clack2012/files/{ref_file.id}"
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert bob.get(url, follow_redirects=False).status_code in (303, 307)  # 로그인 전: 로그인으로
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        csrf = _csrf(bob.get("/shelf").text)
        assert bob.get(url).status_code == 404 and bob.get(ref_url).status_code == 404
        assert "비밀.pdf" not in bob.get(f"/shelf/{NOTES}").text and "원문.pdf" not in bob.get("/shelf/refs-b").text
        bob.post(f"/shelf/{NOTES}/20261008000000000-aaaaaa/edit", data={"csrf": csrf, "content": "밥이 고침", "drop": secret.id},
                 files={"files": ("밥.pdf", b"%PDF bob", "application/pdf")})
        bob.post("/shelf/refs-b/clack2012/check", data={"csrf": csrf, "set": "1", "checked": "1"})  # 밥의 것만 바뀐다
        for path in (url, ref_url, f"{url}/../../edit", "/shelf/notes-common/..%2F..%2Ffather/files/x"):
            got = bob.get(urllib.parse.quote(path, safe="/%"))  # ..는 밥의 공간 안으로만 풀린다
            assert b"alice" not in got.content and "앨리스".encode() not in got.content, path
    after = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*") if p.is_file()}
    assert before == after
    store = LocalStore(data_dir)
    assert store.get_ref("alice", "clack2012").status == "unverified" and store.get_ref("bob", "clack2012").status == "verified"
    assert [a.name for a in store.list_attachments("bob", f"{NOTES}/20261008000000000-aaaaaa")] == ["밥.pdf"]
    store.close()
