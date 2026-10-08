"""사진 썸네일(2026-10-09 사용자 요청): 긴 변 400px JPEG, EXIF 회전, 원본은 바이트까지 그대로, 못 만들면 원본으로,
첨부 목록·옛 코드가 보는 모양(첨부 폴더의 파일 하나)은 그대로, 다른 사용자는 못 봄, 운영자 명령 `magus thumbs`."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import httpx2
from PIL import Image
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from conftest import make_book
from magus.store import CategoryItem, LocalStore
from magus.thumbs import THUMB_DIR, THUMB_EDGE, THUMB_NAME

ITEM = "20261009000000000-aaaaaa"


def _jpeg(size: tuple[int, int], orientation: int | None = None, color=(200, 80, 40)) -> bytes:
    img = Image.new("RGB", size, color)
    img.paste((20, 60, 200), (0, 0, size[0] // 2, size[1] // 4))  # 위 왼쪽에 다른 색(회전 확인용)
    out = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation  # Orientation
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _post(store: LocalStore, user: str = "alice") -> str:
    book = make_book(store, user, "답사", floor="common")
    store.put_category_item(user, CategoryItem(ITEM, book, "사진들", "me"))
    return book


def test_thumb_is_small_jpeg_and_original_untouched(store: LocalStore):
    book = _post(store)
    owner = f"{book}/{ITEM}"
    att = store.put_attachment("alice", owner, "강변.jpg", _jpeg((1600, 1000)))
    original, _ = store.attachment_path("alice", owner, att.id)
    before = _sha(original)
    thumb = store.attachment_thumb("alice", owner, att.id)
    assert thumb == original.parent / THUMB_DIR / THUMB_NAME and thumb.is_file()
    with Image.open(thumb) as im:
        assert im.format == "JPEG" and max(im.size) == THUMB_EDGE and im.size == (400, 250)
    assert _sha(original) == before and thumb.stat().st_size < original.stat().st_size
    assert store.attachment_thumb("alice", owner, att.id) == thumb  # 다시 부르면 있는 것을 쓴다
    # 첨부 목록·문서 첨부 목록은 그대로(썸네일은 첨부가 아니다). 첨부 폴더의 '파일'은 원본 하나뿐(옛 코드가 보는 모양)
    assert [a.name for a in store.list_attachments("alice", owner)] == ["강변.jpg"]
    assert [p.name for p in original.parent.iterdir() if p.is_file()] == ["강변.jpg"]
    pdf = store.put_attachment("alice", owner, "표.pdf", b"%PDF-1.4")
    assert store.attachment_thumb("alice", owner, pdf.id) is None  # 사진이 아니면 없다


def test_portrait_photo_is_rotated_by_exif(store: LocalStore):
    book = _post(store)
    owner = f"{book}/{ITEM}"
    att = store.put_attachment("alice", owner, "세로.jpg", _jpeg((800, 400), orientation=6))  # 휴대폰 세로 사진: 가로로 저장 + 90° 돌려 보라는 표시
    with Image.open(store.attachment_thumb("alice", owner, att.id)) as im:
        assert im.size == (200, 400)  # 세로로 보인다
        assert im.getpixel((190, 10))[2] > 150  # 위 왼쪽의 파란 칸이 돌린 뒤 위 오른쪽에 온다


def test_transparent_png_gets_white_background(store: LocalStore):
    book = _post(store)
    owner = f"{book}/{ITEM}"
    img = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    out = io.BytesIO()
    img.save(out, "PNG")
    att = store.put_attachment("alice", owner, "투명.png", out.getvalue())
    with Image.open(store.attachment_thumb("alice", owner, att.id)) as im:
        assert im.getpixel((10, 10)) == (255, 255, 255)


def test_broken_image_falls_back_to_original(store: LocalStore):
    book = _post(store)
    owner = f"{book}/{ITEM}"
    att = store.put_attachment("alice", owner, "깨짐.png", b"\x89PNG\r\n\x1a\nnot really")
    assert store.attachment_thumb("alice", owner, att.id) is None
    folder = store.attachment_path("alice", owner, att.id)[0].parent
    assert not (folder / THUMB_DIR / THUMB_NAME).exists() and not list(folder.rglob("*.part"))


def test_web_upload_makes_thumb_and_route_falls_back(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    book = _post(store)
    store.close()
    photo = _jpeg((1200, 900))
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        csrf = _csrf(c.get(f"/login?next=/shelf/{book}").text)
        made = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": "사진 둘", "content": ""},
                      files=[("files", ("하나.jpg", photo, "image/jpeg")), ("files", ("깨짐.png", b"\x89PNG broken", "image/png"))])
        item = re.search(rf"/shelf/{book}/([^/?]+)$", str(made.url)).group(1)
        ids = re.findall(rf'/shelf/{book}/{item}/thumbs/([^"]+)"', made.text)
        assert len(ids) == 2 and 'class="pics"' in made.text and made.text.count("data-full>") == 2  # 여러 장이면 격자
        small = c.get(f"/shelf/{book}/{item}/thumbs/{ids[0]}")
        assert small.status_code == 200 and small.headers["content-type"] == "image/jpeg" and len(small.content) < len(photo)
        assert small.headers["x-content-type-options"] == "nosniff"
        fallback = c.get(f"/shelf/{book}/{item}/thumbs/{ids[1]}")  # 못 만들면 원본 그대로
        assert fallback.status_code == 200 and fallback.content == b"\x89PNG broken" and fallback.headers["content-type"] == "image/png"
        assert c.get(f"/shelf/{book}/{item}/files/{ids[0]}").content == photo  # 누르면 원본
        board = c.get(f"/shelf/{book}").text
        assert f'src="/shelf/{book}/{item}/thumbs/{ids[0]}" alt="" loading="lazy"' in board and "📎 2</span>" in board
    folder = data_dir / "users" / "alice" / "shelf" / "categories" / book / "files" / item
    assert (folder / ids[0] / THUMB_DIR / THUMB_NAME).is_file()  # 올릴 때 만들었다


def test_other_user_cannot_get_thumbs(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    book = _post(store, "alice")
    att = store.put_attachment("alice", f"{book}/{ITEM}", "비밀.jpg", _jpeg((900, 900), color=(1, 2, 3)))
    store.close()
    before = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*") if p.is_file()}
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert bob.get(f"/shelf/{book}/{ITEM}/thumbs/{att.id}", follow_redirects=False).status_code in (303, 307)  # 로그인 전
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        assert bob.get(f"/shelf/{book}/{ITEM}/thumbs/{att.id}").status_code == 404
    after = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*") if p.is_file()}
    assert before == after  # 밥의 요청으로 앨리스 폴더에 썸네일이 생기지도 않는다


def test_cli_makes_thumbs_for_existing_photos(store: LocalStore, data_dir: Path, monkeypatch, capsys):
    from magus.cli import main

    book = _post(store)
    owner = f"{book}/{ITEM}"
    att = store.put_attachment("alice", owner, "옛사진.jpg", _jpeg((1000, 700)))
    store.put_attachment("alice", owner, "깨짐.jpg", b"\xff\xd8\xff broken")
    store.put_attachment("alice", owner, "메모.txt", b"x")
    root = data_dir / "users" / "alice"
    originals = {p: _sha(p) for p in root.rglob("*") if p.is_file()}
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("USER_ID", "alice")
    main(["thumbs", "--all-users"])
    assert "alice: 만듦 1 · 이미 있음 0 · 못 만듦(원본으로 보임) 1" in capsys.readouterr().out
    main(["thumbs"])
    assert "alice: 만듦 0 · 이미 있음 1 · 못 만듦(원본으로 보임) 1" in capsys.readouterr().out
    assert {p: _sha(p) for p in originals} == originals  # 원본은 바이트까지 그대로
    assert (store.attachment_path("alice", owner, att.id)[0].parent / THUMB_DIR / THUMB_NAME).is_file()
