"""첨부 글자 뽑기(2026-10-09, #100-3): 게시판에 붙인 문서(docx·pdf·txt·md)에서 글자를 뽑아 찾고 읽는다. 새 도구 없음(23개).

- 저장: 첨부 폴더 안 .text/<이름>.txt + .text/status.json. 원본은 읽기만, 첨부 목록은 그대로(옛 코드도 파일만 센다).
- 30만 자 상한(truncated), 그림만 있는 PDF는 글자 없음(empty), 깨진 파일은 failed, 시간 초과는 later(처음 열 때 다시).
- 찾기: 웹·대화 모두(제목·본문·파일 이름 다음 순위), 맞은 첨부와 앞뒤 100자. 읽기: category_search(attachment, page) 3,000자씩, 웹 '글자 보기'.
- 다른 사용자의 첨부는 찾지도 읽지도 못한다. 휴지통 왕복에 함께 움직인다. 로그에 파일 이름·글자가 없다."""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import docx
import httpx2
import pymupdf
import pytest
from mcp import Client
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus import extract as ex
from magus.config import Settings
from magus.server import build_server
from magus.store import CategoryItem, LocalStore, Ref

POST = "20261009000000000-aaaaaa"


def _docx(paragraphs: list[str]) -> bytes:
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "표 칸", "나루터 통행료"
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def _pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontname="korea")
    data = doc.tobytes()
    doc.close()
    return data


def _scan_pdf() -> bytes:
    """글자 없이 그림(사각형)만 있는 PDF: 스캔한 문서처럼."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    data = doc.tobytes()
    doc.close()
    return data


def test_extract_kinds(tmp_path: Path):
    (tmp_path / "a.docx").write_bytes(_docx(["강가 장날의 소금 장수", "둘째 문단"]))
    (tmp_path / "b.pdf").write_bytes(_pdf(["first page salt market", "second page ferry"]))
    (tmp_path / "c.txt").write_bytes("나루터 일지\n아침 물안개".encode())
    (tmp_path / "d.md").write_bytes("# 제목\n본문".encode("cp949"))  # UTF-8이 아니면 cp949로
    (tmp_path / "scan.pdf").write_bytes(_scan_pdf())
    (tmp_path / "broken.docx").write_bytes(b"not a zip")
    (tmp_path / "long.txt").write_text("가" * 400_000, encoding="utf-8")
    got = {p.name: ex.extract(p) for p in sorted(tmp_path.iterdir())}
    assert got["a.docx"].status == "ok" and "강가 장날의 소금 장수" in got["a.docx"].text and "나루터 통행료" in got["a.docx"].text
    assert got["b.pdf"].status == "ok" and "salt market" in got["b.pdf"].text and "second page ferry" in got["b.pdf"].text
    assert got["c.txt"].text == "나루터 일지\n아침 물안개" and got["d.md"].text == "# 제목\n본문"
    assert (got["scan.pdf"].status, got["scan.pdf"].text) == ("empty", "")
    assert got["broken.docx"].status == "failed"
    assert got["long.txt"].status == "truncated" and len(got["long.txt"].text) == ex.TEXT_MAX
    assert ex.extract(tmp_path / "long.txt", deadline=-1).status == "later"  # 시간을 넘기면 '나중에'
    # 쪽: 3,000자씩(문단 경계 가까이), 이어 붙이면 원래 글
    text = "\n".join(f"{n}번째 줄 " + "나" * 90 for n in range(200))
    parts = ex.pages(text)
    assert "".join(parts) == text and all(len(p) <= ex.PAGE_CHARS for p in parts) and len(parts) >= 7
    assert ex.page_of(text, "150번째 줄") == next(i for i, p in enumerate(parts, 1) if "150번째 줄" in p)


def _seed(store: LocalStore, user: str = "alice") -> dict[str, str]:
    book = store.create_category(user, "장날 메모", "blank", "#1f2f5c", (), "common").id
    refs = store.create_category(user, "읽은 논문", "blank", "#1f2f5c", (), "common").id
    store.put_category_item(user, CategoryItem(POST, book, "답사 자료 모음", "me", title="답사 자료"))
    owner = f"{book}/{POST}"
    long_text = "\n".join(f"{n}쪽 근처 기록 " + "물" * 80 for n in range(120)) + "\n끝부분에 숨은 옹기장수 이야기"
    ids = {"book": book, "refs": refs}
    for name, data in (("답사기록.docx", _docx(["강가 장날의 소금 장수가 새벽에 왔다"])), ("통계.pdf", _pdf(["ferry tolls 1785 ledger"])),
                       ("긴 일지.txt", long_text.encode()), ("스캔.pdf", _scan_pdf()), ("사진.png", b"\x89PNG x")):
        att = store.put_attachment(user, owner, name, data)
        store.attachment_text(user, owner, att.id)
        ids[name] = att.id
    store.put_ref(user, Ref(key="kim2001", status="unverified", bib={"authors": "Kim", "year": 2001, "title": "Markets"}, book=refs))
    att = store.put_attachment(user, "ref:kim2001", "kim_fulltext.txt", "시장 상인들의 하루는 해 뜨기 전에 시작된다".encode())
    store.attachment_text(user, "ref:kim2001", att.id)
    ids["kim"] = att.id
    return ids


def _hashes(root: Path, skip_text: bool = False) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*")
            if p.is_file() and not (skip_text and "/.text/" in p.as_posix())}


def test_store_keeps_text_beside_attachment_and_moves_with_trash(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    owner = f"{ids['book']}/{POST}"
    folder = data_dir / "users" / "alice" / "shelf" / "categories" / ids["book"] / "files" / POST
    status, text = store.attachment_text("alice", owner, ids["답사기록.docx"], make=False)
    assert status["status"] == "ok" and "소금 장수" in text
    assert (folder / ids["답사기록.docx"] / ".text" / "답사기록.docx.txt").read_text(encoding="utf-8") == text
    assert store.attachment_text("alice", owner, ids["스캔.pdf"])[0]["status"] == "empty"
    assert store.attachment_text("alice", owner, ids["사진.png"]) == (None, None)  # 그림은 아직(OCR은 다음 결정)
    names = [a.name for a in store.list_attachments("alice", owner)]
    assert names == ["답사기록.docx", "통계.pdf", "긴 일지.txt", "스캔.pdf", "사진.png"]  # .text/는 첨부로 세지 않는다(옛 코드도)
    assert store.find_attachment("alice", ids["통계.pdf"]) == (owner, store.list_attachments("alice", owner)[1])
    assert store.find_attachment("bob", ids["통계.pdf"]) is None
    before = _hashes(data_dir / "users" / "alice")
    hits = lambda q: [c for c in store.search_fts("alice", ["attach_text"], f'"{q}"', 10)]  # noqa: E731
    assert hits("옹기") and hits("옹기")[0].part == ids["긴 일지.txt"]
    store.trash_item_with_replies("alice", ids["book"], POST, "x")
    assert not hits("옹기") and store.find_attachment("alice", ids["통계.pdf"]) is None  # 휴지통에 있는 것은 찾지 않는다
    store.restore_trash("alice", "category_item", f"{ids['book']}/{POST}")
    assert hits("옹기") and _hashes(data_dir / "users" / "alice") == before  # 글자 파일까지 함께 갔다 왔다
    store.reindex()  # 색인은 파일에서 다시(뽑은 글자도)
    assert hits("옹기")


def test_extract_all_command_counts_and_keeps_originals(data_dir: Path, tmp_path: Path):
    store = LocalStore(data_dir)
    book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(POST, book, "옛 글", "me"))
    for name, data in (("a.docx", _docx(["옛 문서"])), ("b.pdf", _scan_pdf()), ("c.png", b"\x89PNG"), ("d.txt", "옛 글자".encode())):
        store.put_attachment("alice", f"{book}/{POST}", name, data)  # 배포 전에 올라간 첨부(아직 글자 없음)
    store.close()
    originals = _hashes(data_dir / "users")
    env = {"DATA_DIR": str(data_dir), "USER_ID": "alice", "PYTHONIOENCODING": "utf-8", "EMBEDDINGS": "none", "PATH": ""}
    import os  # noqa: PLC0415

    run = subprocess.run([sys.executable, "-m", "magus", "extract", "--all-users"], capture_output=True, text=True, encoding="utf-8",
                         env={**os.environ, **env}, timeout=120)
    assert run.returncode == 0, run.stderr
    assert "alice: 대상 3 · 뽑음 2 · 앞부분만 0 · 글자 없음 1 · 실패 0 · 나중에 0 · 이미 0 · 형식 아님 1" in run.stdout
    assert "a.docx" not in run.stdout + run.stderr and "옛 문서" not in run.stdout + run.stderr  # 이름·글자는 보이지 않는다
    after = _hashes(data_dir / "users")
    assert {k: v for k, v in after.items() if "/.text/" not in k} == originals  # 원본 그대로, 늘어난 것은 .text/뿐
    assert sorted(k.rsplit("/", 1)[1] for k in after if "/.text/" in k) == ["a.docx.txt", "d.txt.txt", "status.json", "status.json", "status.json"]
    again = subprocess.run([sys.executable, "-m", "magus", "extract", "--all-users"], capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, **env}, timeout=120)
    assert "이미 3" in again.stdout


@pytest.mark.anyio
async def test_chat_finds_and_reads_pages(store: LocalStore, data_dir: Path):
    ids = _seed(store)
    settings = Settings.from_env({"USER_ID": "alice", "DATA_DIR": str(data_dir)})
    async with Client(build_server(settings, store)) as c:
        def text(r) -> str:
            return r.content[0].text

        found = text(await c.call_tool("category_search", {"query": "옹기장수"}))
        assert f"📎 첨부 「긴 일지.txt」(첨부:{ids['긴 일지.txt']}) 글자에서 맞음 · 쪽 " in found and "옹기장수" in found
        page = int(re.search(r"글자에서 맞음 · 쪽 (\d+)/", found).group(1))
        assert f'category_search(attachment="{ids["긴 일지.txt"]}", page={page})' in found
        assert "첨부:" + ids["통계.pdf"] in found and "글자 1쪽" in found and "글자 없음" in found  # 첨부 목록에 id·쪽 수
        # 순위: 제목·본문으로 맞은 글이 먼저, 첨부 글자는 그 뒤
        both = text(await c.call_tool("category_search", {"query": "장날"}))
        assert "답사 자료" in both
        read = text(await c.call_tool("category_search", {"attachment": "첨부:" + ids["긴 일지.txt"], "page": page}))
        assert read.startswith(f"첨부 「긴 일지.txt」(첨부:{ids['긴 일지.txt']}) · 「장날 메모」 책의 글 「답사 자료」 · 쪽 {page}/")
        assert "옹기장수" in read and "인용은 원문 확인 글의 쓸 부분만" in read and "마지막 쪽이다." in read
        first = text(await c.call_tool("category_search", {"attachment": ids["긴 일지.txt"]}))
        body = first.split("---\n")[1]
        assert len(body) <= ex.PAGE_CHARS + 1 and "0쪽 근처" in body and "옹기" not in body  # 한 번에 전체를 주지 않는다
        assert "글자 없음" in text(await c.call_tool("category_search", {"attachment": ids["스캔.pdf"]}))
        assert "뽑지 않는 형식" in text(await c.call_tool("category_search", {"attachment": ids["사진.png"]}))
        assert (await c.call_tool("category_search", {"attachment": "20991231000000000-ffffff"})).is_error
        # 문헌 글의 첨부 글자도 찾고, 저자가 고른 대목을 쓸 부분으로
        ref_found = text(await c.call_tool("category_search", {"query": "상인들"}))
        assert "kim2001 · 문헌 글 · 미확인" in ref_found and f"첨부:{ids['kim']}" in ref_found
        added = text(await c.call_tool("category_edit", {"item_id": "kim2001", "parts": [{"text": "시장 상인들의 하루는 해 뜨기 전에 시작된다",
                                                                                         "reason": "장날의 시간", "where": "첨부 1쪽"}]}))
        assert "쓸 부분 1개 더함(모두 1개" in added and "원문 확인 전이라 아직 인용하지 않는다" in added
    assert store.get_ref("alice", "kim2001").status == "unverified" and store.get_passages("alice", "kim2001")[0].locator == "첨부 1쪽"


def test_web_upload_extracts_search_and_text_page(server_proc):  # noqa: F811
    base, data_dir, log_path = server_proc({})
    store = LocalStore(data_dir)
    book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.close()
    big = ("머리말\n" + "물안개 낀 나루터의 하루\n" * 520_000).encode()  # 약 19MB(첨부 한도 20MB 안)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get(f"/login?next=/shelf/write/{book}").text
        csrf = _csrf(page)
        made = c.post(f"/shelf/write/{book}", data={"csrf": csrf, "title": "답사", "content": "본문"},
                      files=[("files", ("나루 기록.docx", _docx(["옹기장수가 나루를 건넜다"]), "application/octet-stream")),
                             ("files", ("큰 일지.txt", big, "text/plain"))])
        assert made.status_code == 200 and "글자 보기</a>" in made.text
        post = str(made.url).rsplit("/", 1)[1]
        text_link = re.search(rf'href="(/shelf/{book}/{post}/text/[^"]+)">글자 보기', made.text).group(1)
        shown = c.get(text_link).text
        assert "옹기장수가 나루를 건넜다" in shown and '<pre class="att-text">' in shown and "글자 " in shown
        board = c.get(f"/shelf/{book}", params={"q": "옹기장수"}).text
        assert '<small class="hit"><span aria-hidden="true">📎</span> 나루 기록.docx · ' in board and "<mark>옹기" in board
        whole = c.get("/shelf", params={"q": "옹기장수"}).text  # 전체 찾기에도
        assert "나루 기록.docx" in whole
    store = LocalStore(data_dir)
    owner = f"{book}/{post}"
    big_att = next(a for a in store.list_attachments("alice", owner) if a.name == "큰 일지.txt")
    assert store.attachment_text("alice", owner, big_att.id, make=False)[0]["status"] == "truncated"  # 30만 자에서 멈춤
    store.close()
    log = Path(log_path).read_text(encoding="utf-8")
    assert "extract status=ok" in log and "나루 기록" not in log and "옹기" not in log  # 로그에는 상태·글자 수·시간만


def test_other_user_cannot_read_or_find_attachment_text(server_proc, fake_issuer):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    ids = _seed(store, "alice")
    store.create_category("bob", "장날 메모", "blank", "#1f2f5c", (), "common")
    store.close()
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        assert bob.get(f"/shelf/{ids['book']}/{POST}/text/{ids['답사기록.docx']}").status_code == 404
        assert '<a class="post"' not in bob.get("/shelf", params={"q": "소금 장수"}).text
    store = LocalStore(data_dir)
    assert store.find_attachment("bob", ids["답사기록.docx"]) is None
    assert not store.search_fts("bob", ["attach_text"], '"소금"', 10)
    store.close()


def test_late_extraction_is_retried_when_opened(store: LocalStore, data_dir: Path):
    book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(POST, book, "글", "me"))
    att = store.put_attachment("alice", f"{book}/{POST}", "느린 문서.txt", "늦게 뽑힌 글자".encode())
    status, text = store.attachment_text("alice", f"{book}/{POST}", att.id, deadline=-1)  # 시간 초과
    assert status["status"] == "later" and text is None
    status_file = data_dir / "users" / "alice" / "shelf" / "categories" / book / "files" / POST / att.id / ".text" / "status.json"
    assert json.loads(status_file.read_text(encoding="utf-8"))["status"] == "later"
    status, text = store.attachment_text("alice", f"{book}/{POST}", att.id)  # 60초 안에는 다시 뽑지 않는다(점검 7-e)
    assert status["status"] == "later" and text is None
    data = json.loads(status_file.read_text(encoding="utf-8"))
    status_file.write_text(json.dumps({**data, "at": "2026-01-01T00:00:00.000Z"}), encoding="utf-8")  # 마지막 시도가 오래전
    status, text = store.attachment_text("alice", f"{book}/{POST}", att.id)  # 그 뒤 처음 열 때 다시
    assert status["status"] == "ok" and text == "늦게 뽑힌 글자"
