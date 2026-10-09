"""코드 점검 높음 5건(2026-10-09): 7-a 그림 폭탄, 7-c docx 압축 폭탄, 12-b 깨진 파일 하나에 색인이 멈춤, 15-1 아주 큰 장 번호,
10-b 대화로 글을 고치면 ★·고친 기록·누가가 지워짐. 고치기 전 재현은 private/tmp/fix6/*_repro.py(전후 표는 보고서)."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from PIL import Image
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus import thumbs, zipguard
from magus.book.docx_reader import read_docx
from magus.config import Settings
from magus.extract import extract
from magus.server import build_server
from magus.store import CategoryItem, LocalStore, Passage
from magus.store.schema import SCHEMA_VERSION

pytestmark = pytest.mark.anyio
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _bomb(path: Path, paragraphs: int = 3_000_000) -> Path:
    """빈 문단 수백만 개 — 압축하면 수십 KB, 풀면 수십 MB."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", b'<?xml version="1.0"?><w:document ' + W.encode() + b"><w:body>"
                   + b"<w:p/>" * paragraphs + b"</w:body></w:document>")
    return path


# ---- 7-a 그림 폭탄 ----

def _post(store: LocalStore) -> str:
    store.create_category("alice", "사진", "blank", "#1f2f5c", (), "common", category_id="pics")
    store.put_category_item("alice", CategoryItem("20261009000000000-aaaaaa", "pics", "사진 글", "me"))
    return "pics/20261009000000000-aaaaaa"


def test_too_many_pixels_are_not_decoded(store: LocalStore, monkeypatch):
    owner = _post(store)
    out = io.BytesIO()
    Image.new("1", (6_000, 6_000)).save(out, "PNG", optimize=True)  # 3,600만 픽셀 > 상한 3,000만(파일은 수 KB)
    att = store.put_attachment("alice", owner, "큰 그림.png", out.getvalue())
    assert store.attachment_thumb("alice", owner, att.id) is None
    folder = store.attachment_path("alice", owner, att.id)[0].parent
    assert (folder / thumbs.THUMB_DIR / thumbs.FAILED_NAME).read_text(encoding="utf-8") == "too_big"
    assert [p.name for p in folder.iterdir() if p.is_file()] == ["큰 그림.png"]  # 원본은 그대로(내려받기 그대로)
    monkeypatch.setattr(thumbs, "make_thumb", lambda *a: pytest.fail("실패 표시가 있으면 다시 풀지 않는다"))
    assert store.attachment_thumb("alice", owner, att.id) is None


def test_bomb_warning_is_an_error_and_big_jpeg_uses_draft(store: LocalStore, tmp_path: Path):
    bomb = tmp_path / "bomb.png"
    Image.new("1", (10_000, 10_000)).save(bomb, "PNG", optimize=True)  # 1억 픽셀: Pillow 폭탄 경고 범위
    assert thumbs.make_thumb(bomb, tmp_path / "t1" / thumbs.THUMB_NAME) is False
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (7_000, 6_000), (120, 90, 60)).save(photo, quality=5)  # 4,200만 화소 사진: JPEG는 줄여 풀므로 만든다
    made = tmp_path / "t2" / thumbs.THUMB_NAME
    assert thumbs.make_thumb(photo, made) is True
    with Image.open(made) as im:
        assert max(im.size) == thumbs.THUMB_EDGE


# ---- 7-c docx 압축 폭탄 ----

def test_zip_bomb_is_refused_before_unzipping(tmp_path: Path):
    bomb = _bomb(tmp_path / "폭탄.docx")
    assert bomb.stat().st_size < 100_000
    started = time.monotonic()
    with pytest.raises(zipguard.UnsafeDocument, match="열 수 없는 문서입니다."):
        read_docx(bomb)
    assert time.monotonic() - started < 1.0
    assert extract(bomb, 5.0).status == "failed"  # 첨부 글자 뽑기도 풀지 않는다
    many = tmp_path / "많음.docx"
    with zipfile.ZipFile(many, "w") as z:
        for n in range(zipguard.MAX_ENTRIES + 1):
            z.writestr(f"x/{n}.xml", "<a/>")
    with pytest.raises(zipguard.UnsafeDocument, match="항목이 너무 많습니다"):
        read_docx(many)


async def test_zip_bomb_through_book_import(store: LocalStore, settings: Settings):
    inbox = store.root / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    _bomb(inbox / "폭탄.docx")
    async with Client(build_server(settings, store)) as c:
        r = await c.call_tool("book_import", {"path": "폭탄.docx", "project_id": "bomb"})
    assert r.is_error and "열 수 없는 문서입니다." in r.content[0].text


def test_zip_bomb_through_web_upload(server_proc, tmp_path: Path):  # noqa: F811
    base, _, _ = server_proc({})
    data = _bomb(tmp_path / "폭탄.docx").read_bytes()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        started = time.monotonic()
        r = c.post("/shelf/manuscript", data={"csrf": csrf, "project": "new"}, files={"file": ("폭탄.docx", data, "application/octet-stream")})
        assert r.status_code == 400 and "열 수 없는 문서입니다." in r.text and time.monotonic() - started < 5


# ---- 12-b·15-1 색인 다시 만들기 ----

def _seed(store: LocalStore) -> None:
    store.create_project("alice", "책", project_id="b")
    for n in range(1, 4):
        store.write_chapter("alice", "b", n, f"{n}장 본문", "x", title=f"{n}장")
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    for n in range(5):
        store.put_category_item("alice", CategoryItem(f"2026100900000000{n}-aaaaaa", "notes", f"글 {n}", "me"))


def _count(store: LocalStore, table: str) -> int:
    return store._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_one_broken_file_does_not_stop_reindex(data_dir: Path):
    store = LocalStore(data_dir)
    _seed(store)
    bad = data_dir / "users" / "alice" / "shelf" / "categories" / "notes" / "items" / "20261009000000002-aaaaaa.json"
    bad.write_text('{"id": "깨진', encoding="utf-8")
    huge = data_dir / "users" / "alice" / "projects" / "b" / "book" / "ch-9223372036854775808.md"
    huge.write_text((huge.parent / "ch-01.md").read_text(encoding="utf-8"), encoding="utf-8")
    skipped = store.reindex()
    assert sorted(skipped) == sorted(["users/alice/shelf/categories/notes/items/20261009000000002-aaaaaa.json",
                                      "users/alice/projects/b/book/ch-9223372036854775808.md"])
    assert (_count(store, "category_items"), _count(store, "chapters"), _count(store, "projects")) == (4, 3, 1)
    store._db.execute("PRAGMA user_version = 0")  # 스키마를 올린 배포처럼: 시작할 때 다시 만든다
    store._db.commit()
    store.close()
    again = LocalStore(data_dir)  # 전에는 JSONDecodeError·OverflowError로 서버가 뜨지 않았다
    assert _count(again, "category_items") == 4 and again._db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert not (data_dir / "index.sqlite.new").exists()
    again.close()


def test_failed_rebuild_keeps_the_current_index(data_dir: Path, monkeypatch):
    store = LocalStore(data_dir)
    _seed(store)
    monkeypatch.setattr(LocalStore, "_index_user", lambda self, *a: (_ for _ in ()).throw(RuntimeError("디스크")))
    store.reindex()  # 예외를 올리지 않는다
    assert _count(store, "category_items") == 5  # 지금 색인은 그대로
    store._db.execute("PRAGMA user_version = 0")
    store._db.commit()
    store.close()
    again = LocalStore(data_dir)  # 스키마가 다른데 다시 만들기도 실패: 빈 새 스키마로 뜨고, 다음 시작 때 다시 만든다
    assert _count(again, "category_items") == 0 and again._db.execute("PRAGMA user_version").fetchone()[0] == 0
    again.close()
    monkeypatch.undo()
    third = LocalStore(data_dir)
    assert _count(third, "category_items") == 5
    third.close()


async def test_chapter_number_range(store: LocalStore, settings: Settings):
    store.create_project("alice", "책", project_id="b")
    async with Client(build_server(settings, store)) as c:
        tool = next(t for t in (await c.list_tools()).tools if t.name == "book_write_chapter")
        assert tool.input_schema["properties"]["number"] == {"maximum": 9999, "minimum": 0, "title": "Number", "type": "integer"}
        for bad in (2**63, -1, 10_000, "x"):
            r = await c.call_tool("book_write_chapter", {"number": bad, "content": "본문", "note": "x", "project_id": "b"})
            assert r.is_error, bad
        ok = await c.call_tool("book_write_chapter", {"number": 0, "content": "서장 본문", "note": "x", "project_id": "b"})
        assert not ok.is_error  # 0은 서장
    with pytest.raises(ValueError, match="장 번호는 0~9,999입니다"):
        store.write_chapter("alice", "b", 10_000, "본문", "x")
    assert not list((store.root / "users" / "alice" / "projects" / "b" / "book").glob("ch-10000.md"))


# ---- 10-b 대화로 글 고치기 ----

async def test_chat_edit_keeps_scrap_record_author_and_hidden_fields(store: LocalStore, settings: Settings):
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="notes")
    item = "20261009000000000-aaaaaa"
    store.put_category_item("alice", CategoryItem(item, "notes", "처음 본문", "me", "저자가 지은 제목", "author", reason="장터 답사",
                                                  where="3쪽", passages=(Passage("고른 대목", "근거", "p.3"),), tags=("시장",)))
    store.patch_category_item("alice", "notes", item, {"edited_at": "2026-10-09T01:00:00.000Z", "edited_by": "author"})
    store.set_scrap("alice", f"notes/{item}", True)
    path = store.root / "users" / "alice" / "shelf" / "categories" / "notes" / "items" / f"{item}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "future_mark": "앞으로 더할 표시"}, ensure_ascii=False), encoding="utf-8")
    store.reindex()
    async with Client(build_server(settings, store)) as c:
        r = await c.call_tool("category_put", {"book": "메모", "author": "ai", "item_id": item, "content": "Claude가 고친 본문"})
        assert not r.is_error and "누가: 저자의 말(me) 그대로" in r.content[0].text and "★ 스크랩 그대로" in r.content[0].text
        after = json.loads(path.read_text(encoding="utf-8"))
        assert after["content"] == "Claude가 고친 본문" and after["author"] == "me" and after["scrap"] is True
        assert after["title"] == "저자가 지은 제목" and after["title_by"] == "author"
        assert after["edited_by"] == "ai" and after["edited_at"] > "2026-10-09T01:00:00.000Z"
        assert (after["reason"], after["where"], after["tags"], len(after["passages"]), after["future_mark"]) == (
            "장터 답사", "3쪽", ["시장"], 1, "앞으로 더할 표시")
        # 웹에서 같은 함수로 고친 것과 같은 칸만 바뀐다: 제목을 주면 제목·지은 사람만
        await c.call_tool("category_put", {"book": "메모", "author": "me", "item_id": item, "title": "새 제목", "title_by": "author"})
        again = json.loads(path.read_text(encoding="utf-8"))
        assert again["title"] == "새 제목" and again["content"] == "Claude가 고친 본문" and again["edited_by"] == "author"
        # 읽은 뒤 다른 곳에서 저장했으면 덮어쓰지 않는다
        real = store.get_category_item

        def stale(user_id, category_id, item_id):
            found = real(user_id, category_id, item_id)
            from dataclasses import replace  # noqa: PLC0415

            return replace(found, updated_at="2000-01-01T00:00:00.000Z") if found else None

        store.get_category_item = stale  # type: ignore[method-assign]
        late = await c.call_tool("category_put", {"book": "메모", "author": "ai", "item_id": item, "content": "늦은 고침"})
        store.get_category_item = real  # type: ignore[method-assign]
        assert "그사이 다른 곳(웹 등)에서 저장된 글이라 바꾸지 않았다." in late.content[0].text
        assert json.loads(path.read_text(encoding="utf-8"))["content"] == "Claude가 고친 본문"
