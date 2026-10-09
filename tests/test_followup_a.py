"""코드 점검 후속 A(2026-10-09): '바로 할 수 있는 것' 항목별 시험. 항목 번호는 docs/audit/2026-10-09-code-audit.md."""

from __future__ import annotations

import pytest
from mcp import Client
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio
RANGE = "장 번호는 0~9,999입니다(0은 서장)."


# ---- 15-2 읽기 도구의 장 번호 범위 ----

async def test_read_tools_check_chapter_range(store: LocalStore, settings: Settings):
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "본문", "x", title="하나")
    async with Client(build_server(settings, store)) as c:
        for name, args in [("book_read_chapter", {"number": 2**63}), ("book_read_chapter", {"number": -1}),
                           ("book_issues", {"chapter_number": 2**63}), ("ref_check", {"chapter_number": 10_000}),
                           ("book_issue_add", {"text": "x", "chapter_number": 2**63})]:
            r = await c.call_tool(name, {**args, "project_id": "b"})
            assert r.is_error and RANGE in r.content[0].text, (name, r.content[0].text)
        ok = await c.call_tool("book_read_chapter", {"number": 1, "project_id": "b"})
        assert not ok.is_error
    assert store.read_chapter("alice", "b", 2**63) is None and store.list_issues("alice", "b", None, chapter_number=2**63) == []


# ---- 13-b 연결 노드 되살리기 뒤 인용 수 ----

def _unverified(store: LocalStore) -> int:
    import re

    from magus.book.outline import build_outline

    return int(re.search(r"미확인 문헌 (\d+)편", build_outline(store, "alice", "book")).group(1))


async def test_restoring_link_node_recounts(store: LocalStore, settings: Settings):
    from pathlib import Path

    from magus.book.importer import import_manuscript
    from magus.category.moves import restore_node, trash_node_with_books

    import_manuscript(store, "alice", Path(__file__).parent / "fixtures" / "synthetic" / "닿으려는_종_합성.docx", project_id="book",
                      synthetic=True)
    async with Client(build_server(settings, store)) as c:
        await c.call_tool("category_create", {"name": "읽은 논문", "project": "내 서재"})
        r = await c.call_tool("category_put", {"book": "읽은 논문", "project": "내 서재", "author": "me", "source": {"key": "clack2012"},
                                               "checked": True, "parts": [{"text": "네발동물 대목", "reason": "근거"}]})
        assert not r.is_error, r.content[0].text
    shared = _unverified(store)
    link = next(n for n in store.get_map("alice", "book").nodes if n.link)
    trash_node_with_books(store, "alice", "book", link.id, "시험")
    assert _unverified(store) == shared + 1  # 연결 노드가 없으면 clack2012가 이 원고에서 미확인으로
    restore_node(store, "alice", f"book/{link.id}")
    assert _unverified(store) == shared  # 전에는 다음 문헌 변경·재시작까지 shared + 1이 남았다


# ---- 15-3 대화 기록이 Word·PDF·UTF-8 아님 ----

async def test_conversation_rejects_word_and_bad_encoding(store: LocalStore, settings: Settings):
    from pathlib import Path

    store.create_category("alice", "대화", "blank", "#1f2f5c", (), "common", category_id="talk")
    inbox = store.root / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True)
    synth = Path(__file__).parent / "fixtures" / "synthetic"
    (inbox / "기록.docx").write_bytes((synth / "닿으려는_종_합성.docx").read_bytes())
    (inbox / "기록.pdf").write_bytes((synth / "닿으려는_종_합성.pdf").read_bytes())
    (inbox / "옛기록.txt").write_bytes("**사용자:** 안녕\n**Claude:** 네\n".encode("cp949"))
    (inbox / "기록.md").write_text("**사용자:** 안녕\n\n**Claude:** 네\n", encoding="utf-8")
    async with Client(build_server(settings, store)) as c:
        for name in ("기록.docx", "기록.pdf"):
            r = await c.call_tool("idea_add_conversation", {"book": "대화", "path": name})
            assert r.is_error and "대화 기록은 .md·.txt 파일만 받는다" in r.content[0].text, r.content[0].text
        r = await c.call_tool("idea_add_conversation", {"book": "대화", "path": "옛기록.txt"})
        assert r.is_error and "UTF-8 글자로 읽지 못했다" in r.content[0].text
        ok = await c.call_tool("idea_add_conversation", {"book": "대화", "path": "기록.md"})
        assert not ok.is_error and "발화 2개" in ok.content[0].text


# ---- 7-b 첨부 docx 글자 뽑기: 낱말(w:t) 단위로 모으고 버림 ----

def _docx(path, body: str):
    import zipfile

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>')
    return path


def test_docx_text_streams_by_run(tmp_path):
    import random
    import string
    import time

    from magus.extract import TEXT_MAX, extract

    small = _docx(tmp_path / "a.docx", "<w:p><w:pPr/><w:r><w:t>첫 </w:t></w:r><w:r><w:t>문단</w:t><w:tab/><w:t>탭</w:t></w:r></w:p>"
                  "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>칸</w:t><w:br/><w:t>둘째 줄</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
                  "<w:p><w:hyperlink><w:r><w:t>링크</w:t></w:r></w:hyperlink></w:p>")
    assert extract(small).text == "첫 문단\t탭\n칸\n둘째 줄\n링크\n"
    rnd = random.Random(7)
    runs = "".join(f"<w:r><w:t>{''.join(rnd.choices(string.ascii_letters, k=8))}</w:t></w:r>" for _ in range(200_000))
    one = _docx(tmp_path / "one.docx", f"<w:p>{runs}</w:p>")  # 문단 하나에 run 20만 개(160만 자)
    started = time.monotonic()
    got = extract(one)
    assert got.status == "truncated" and len(got.text) == TEXT_MAX and time.monotonic() - started < 2


# ---- 7-d 깨진 원고 올리기 → 500 대신 안내, CSRF만 403 ----

def _broken_files(tmp_path):
    import zipfile

    no_body = tmp_path / "본문없음.docx"
    with zipfile.ZipFile(no_body, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    bad_xml = tmp_path / "깨진XML.docx"
    with zipfile.ZipFile(bad_xml, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p>")
    return {"zip아님.docx": b"this is not a zip", no_body.name: no_body.read_bytes(), bad_xml.name: bad_xml.read_bytes(),
            "깨진.pdf": b"%PDF-1.7\n%broken\n"}


def test_broken_manuscript_upload_is_400(server_proc, tmp_path):  # noqa: F811
    import httpx2
    from test_web import _csrf

    from magus.book.importer import UNREADABLE

    base, _, log = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        for name, data in _broken_files(tmp_path).items():
            r = c.post("/shelf/manuscript", data={"csrf": csrf, "project": "new"}, files={"file": (name, data, "application/octet-stream")})
            assert r.status_code == 400 and UNREADABLE in r.text, (name, r.status_code)
        wrong = c.post("/shelf/manuscript", data={"csrf": "틀림", "project": "new"},
                       files={"file": ("a.docx", b"x", "application/octet-stream")})
        assert wrong.status_code == 403 and "잘못된 요청입니다." in wrong.text
    assert "Traceback" not in log.read_text(encoding="utf-8") and " ERROR " not in log.read_text(encoding="utf-8")


async def test_broken_manuscript_book_import(store: LocalStore, settings: Settings, tmp_path):
    from magus.book.importer import UNREADABLE

    inbox = store.root / "users" / "alice" / "inbox"
    inbox.mkdir(parents=True)
    for name, data in _broken_files(tmp_path).items():
        (inbox / name).write_bytes(data)
    async with Client(build_server(settings, store)) as c:
        for name in _broken_files(tmp_path):
            r = await c.call_tool("book_import", {"path": name, "project_id": "x"})
            assert r.is_error and UNREADABLE in r.content[0].text, (name, r.content[0].text)
