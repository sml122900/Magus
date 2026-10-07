"""모든 동작을 책장에서(#94): 책 추가(원고·모음·문서), 원고 책 화면(탭), 문서 책(옛 판 기준·다시 만들기·내려받기), 옛 주소, 격리.

시나리오(사용자 요청 6절): 층 만들기 → 원고 책 만들기(파일 올리기) → 대화 없이 웹에서 원고 책 열기 → 문서 책 만들기 도구 호출
(Claude 역할은 시험에서 대신) → 문서 책이 같은 층에 꽂힘 → 수정본 올리기 → 문서 책에 '옛 판 기준' 표시.
"""

from __future__ import annotations

import re
import urllib.parse

import httpx2
import pytest
from mcp import Client
from test_http import FIXTURES  # noqa: F401
from test_web import _csrf, _login, fake_issuer, server_proc  # noqa: F401 - 픽스처

from magus.config import Settings
from magus.server import build_server
from magus.store import LocalStore
from magus.synthetic import build_manuscript_docx

pytestmark = pytest.mark.anyio
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _text(result) -> str:
    return "\n".join(block.text for block in result.content)


async def _make_document(data_dir, user: str, **args) -> str:
    """Claude 역할: book_document 도구를 부른다(같은 데이터 폴더, 프로세스 안 서버)."""
    store = LocalStore(data_dir)
    try:
        async with Client(build_server(Settings.from_env({"USER_ID": user, "DATA_DIR": str(data_dir)}), store)) as c:
            result = await c.call_tool("book_document", args)
            assert not result.is_error, _text(result)
            return _text(result)
    finally:
        store.close()


async def test_bookshelf_scenario(server_proc, tmp_path):  # noqa: F811
    base, data_dir, _ = server_proc({})
    manuscript = build_manuscript_docx(tmp_path / "닿으려는_종_합성.docx")
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        shelf = c.get("/login?next=/shelf").text
        csrf = _csrf(shelf)
        # 상단 메뉴는 책장 하나(#94)
        nav = shelf.split("<nav>")[1].split("</nav>")[0]
        assert 'href="/shelf"' in nav and "/book" not in nav and "/inbox" not in nav and "/checklist" not in nav
        # 1. 층 만들기
        floor_page = c.post("/shelf/floors", data={"csrf": csrf, "title": "닿으려는 종"})
        floor_id = urllib.parse.parse_qs(urllib.parse.urlparse(str(floor_page.url)).query)["floor"][0]  # 한 화면 책장의 그 층
        assert "원고가 아직 없습니다. 아래 점선 자리 '책 추가'에서 원고 파일을 고르면 이 층의 원고 책이 됩니다." in floor_page.text
        assert f'<a class="madd" href="/shelf/add?floor={floor_id}" aria-label="책 추가">' in floor_page.text
        # 2. 책 추가: 종류 고르기
        add = c.get(f"/shelf/add?floor={floor_id}").text
        assert "<h2>원고 책</h2>" in add and "<h2>모음 책</h2>" in add and "<h2>문서 책</h2>" in add
        assert 'action="/shelf/manuscript" enctype="multipart/form-data" data-progress=' in add
        assert "공용 층에는 모음 책만" in c.get("/shelf/add?floor=common").text
        # 3. 원고 책 만들기: 파일을 고르면 바로 올라가고 가져온다(받은함을 거치지 않음)
        assert c.post("/shelf/manuscript", data={"csrf": "틀림", "floor": floor_id},
                      files={"file": (manuscript.name, manuscript.read_bytes(), DOCX)}).status_code == 403
        bad = c.post("/shelf/manuscript", data={"csrf": csrf, "floor": floor_id}, files={"file": ("메모.txt", b"x", "text/plain")})
        assert bad.status_code == 400 and "원고는 docx 또는 pdf 파일이어야 합니다." in bad.text
        made = c.post("/shelf/manuscript", data={"csrf": csrf, "floor": floor_id},
                      files={"file": (manuscript.name, manuscript.read_bytes(), DOCX)})
        assert str(made.url).endswith(f"/shelf/book/{floor_id}?done=imported")
        assert re.search(r"원고 책을 만들었습니다: 7장 · 부 3개 · 확인 요청 \d+건\(원고 코멘트에서\) · 문헌 \d+편\(참고문헌에서\)", made.text)
        assert c.get("/me/files").text.count("<tr><td>") == 0  # 올린 파일에는 남지 않는다
        # 4. 원고 책 화면: 탭
        tabs = {tab: c.get(f"/shelf/book/{floor_id}?tab={tab}").text for tab in ("chapters", "issues", "cites", "editions")}
        assert '<nav class="tabs" aria-label="원고 책">' in tabs["chapters"] and "aria-current=page>장 목록</a>" in tabs["chapters"]
        assert "<td>제4장</td><td>닿으려는 손</td>" in tabs["chapters"] and "docx로 내려받기" in tabs["chapters"]
        assert "확인 요청" in tabs["issues"] and "<th>번호</th>" in tabs["issues"]
        assert "답해 주실 질문" in tabs["cites"] and "<h2>장별</h2>" in tabs["cites"]
        assert "<h2>답해 주실 질문" in c.get(f"/shelf/book/{floor_id}?tab=cites&view=questions").text
        assert "수정본 올리기" in tabs["editions"] and "처음 올린 원고 E1" in tabs["editions"]
        assert "리포트 — 처음 올린 원고" in c.get(f"/shelf/book/{floor_id}?tab=editions&report=1").text
        # 옛 주소는 새 화면으로
        for old, new in (("/book", "tab=chapters"), (f"/issues?project={floor_id}&kind=fact", "tab=issues&kind=fact"),
                         (f"/checklist?project={floor_id}&status=unknown", "tab=cites&status=unknown"),
                         (f"/questions?project={floor_id}", "tab=cites&view=questions")):
            moved = c.get(old, follow_redirects=False)
            assert moved.status_code == 302 and moved.headers["location"].startswith(f"/shelf/book/{floor_id}?") \
                and new in moved.headers["location"], old
        assert c.get("/inbox", follow_redirects=False).headers["location"] == "/me/files"
        # 5. 문서 책: Claude가 book_document를 부른다
        said = await _make_document(data_dir, "alice", project_id=floor_id, title="닿으려는 종 출처 확인 문서", title_by="author",
                                    preface="저자께서 먼저 보실 것을 모았습니다.")
        doc_id = re.search(r"\((\d{17}-[0-9a-f]{6})\)", said).group(1)
        floor = c.get(f"/shelf?floor={floor_id}").text
        assert f'data-open="/shelf/doc/{doc_id}"' in floor and '<span class="mb-band bottom"><span class="line">E1 기준</span>' in floor
        assert f'data-open="/shelf/book/{floor_id}"' in floor and '<span class="mb-band top">원고</span>' in floor
        doc = c.get(f"/shelf/doc/{doc_id}").text
        assert "문서 책 · 출처 확인 문서 · 기준 원고" in doc and "(머리말은 Claude가 씀)" in doc
        assert "<h2>닿으려는 종 출처 확인 문서</h2>" in doc and "<i>Claude(AI)가 쓴 머리말입니다.</i>" in doc
        assert "<h3>1. 답해 주실 질문" in doc and "<h3>6. 이전 수정본 대비 바뀐 점</h3>" in doc and "만든 이력 1" in doc
        assert "window.print()" in doc and f"{STALE}: 기준 원고에 새 수정본" not in doc
        got = c.get(f"/shelf/doc/{doc_id}/docx")
        assert got.status_code == 200 and got.content[:2] == b"PK" and "attachment" in got.headers["content-disposition"]
        # 6. 수정본 올리기 → 문서 책은 옛 판 기준
        edition = c.post(f"/shelf/book/{floor_id}/edition", data={"csrf": csrf},
                         files={"file": (manuscript.name, manuscript.read_bytes(), DOCX)})
        assert str(edition.url).endswith("tab=editions&done=edition") and "수정본 E2 올리기를 마쳤습니다." in edition.text
        assert "리포트 — 수정본 E2" in edition.text
        floor = c.get(f"/shelf?floor={floor_id}").text
        assert '<span class="mb-band bottom stale"><span class="line">옛 판</span><span class="line">기준</span>' in floor
        assert f"문서 책 닿으려는 종 출처 확인 문서, {STALE}" in floor
        doc = c.get(f"/shelf/doc/{doc_id}").text
        assert f"{STALE}: 기준 원고에 새 수정본(E2)이 올라왔습니다. 이 문서는 E1 기준입니다." in doc and "다시 만들기</button>" in doc
        redo = c.post(f"/shelf/doc/{doc_id}/redo", data={"csrf": csrf})
        assert "다시 만들었습니다." in redo.text and f"{STALE}: 기준 원고에 새 수정본" not in redo.text and "만든 이력 2" in redo.text
        assert "이 문서의 이전 판(v1, E1 기준" in redo.text  # 이전 것과 견준 수치
        assert "지금 보고 있는 것은 이력(1번째" in c.get(f"/shelf/doc/{doc_id}?v=1").text
        # 7. 문서 책 설정: 이름·색, 공용에는 못 옮김
        edit = c.get(f"/shelf/edit/doc.{doc_id}").text
        assert '<option value="common"' not in edit and "문서 책은 작업물 층에만 둘 수 있습니다(공용 층에는 모음 책만)." in edit
        blocked = c.post("/shelf/move", data={"csrf": csrf, "book": f"doc.{doc_id}", "to": "common", "next": f"/shelf?floor={floor_id}"})
        assert "공용 층에는 모음 책만 둘 수 있습니다." in blocked.text
        renamed = c.post(f"/shelf/edit/doc.{doc_id}", data={"csrf": csrf, "name": "출처 확인", "color": "#2f6db5"})
        assert "「출처 확인」 책을 고쳤습니다." in renamed.text and "--c:#2f6db5;" in renamed.text
        assert "원고 책은 그 층 자체라 다른 층으로 옮기지 않습니다." in c.get(f"/shelf/edit/ms.{floor_id}").text
        # 8. 원고 책 휴지통: 층은 빈 층으로 남고 문서 책은 그대로
        confirm = c.get(f"/shelf/trash/ms.{floor_id}").text
        assert "장 7개" in confirm and "이 층은 원고가 없는 빈 층이 됩니다." in confirm
        gone = c.post(f"/shelf/trash/ms.{floor_id}", data={"csrf": csrf})
        assert "책을 휴지통으로 옮겼습니다." in gone.text and "원고가 아직 없습니다." in gone.text and f'data-open="/shelf/doc/{doc_id}"' in gone.text
        assert c.get(f"/shelf/book/{floor_id}").status_code == 404
    store = LocalStore(data_dir)
    assert store.list_chapters("alice", floor_id) == [] and store.get_document("alice", doc_id) is not None
    assert list((data_dir / "users" / "alice" / "trash").glob(f"{floor_id}-*/project.json"))
    store.close()


STALE = "옛 판 기준"


async def test_ref_register_from_shelf(server_proc, tmp_path):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", "b", 1, "물고기가 올라왔다(Clack, 2012).", "x", title="물가")
    from magus.melchior.bibliography import import_bibliography  # noqa: PLC0415

    import_bibliography(store, "alice", "Clack, J. A. (2012). Gaining ground. Indiana University Press.", "b")
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        refs = c.get("/login?next=/shelf/refs.b").text
        csrf = _csrf(refs)
        assert "논문 파일로 문헌 등록" in refs and '<option value="clack2012">Clack(2012) 『Gaining ground』</option>' in refs
        empty = c.post("/shelf/refs/register", data={"csrf": csrf, "floor": "b", "key": "clack2012", "passage": "", "reason": ""})
        assert "쓸 부분과 고른 이유를 적어 주세요." in empty.text
        done = c.post("/shelf/refs/register", data={"csrf": csrf, "floor": "b", "key": "clack2012", "passage": "tetrapods came ashore",
                                                     "reason": "1장의 근거", "locator": "p.45"},
                      files={"file": ("clack.txt", "tetrapods came ashore".encode(), "text/plain")})
        assert "확인한 문헌으로 등록했습니다." in done.text and '<details id="i-clack2012" open data-here>' in done.text
    store = LocalStore(data_dir)
    ref = store.get_ref("alice", "clack2012")
    assert ref.status == "verified" and ref.file_path == "inbox/clack.txt" and store.list_chapters("alice", "b")[0].unverified_cite_count == 0
    store.close()


async def test_books_are_per_user(server_proc, fake_issuer, tmp_path):  # noqa: F811
    issuer, issuer_state, _ = fake_issuer
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": issuer, "ALLOWED_USERS": "sub-alice=alice,sub-bob=bob",
        "SESSION_SECRET": "x" * 40, "WEB_CLIENT_ID": "web-client",
    })
    store = LocalStore(data_dir)
    store.create_project("alice", "앨리스의 책", project_id="a")
    store.write_chapter("alice", "a", 1, "앨리스의 문장(Clack, 2012).", "x", title="하나")
    store.close()
    said = await _make_document(data_dir, "alice", project_id="a", untitled=True)
    doc_id = re.search(r"\((\d{17}-[0-9a-f]{6})\)", said).group(1)
    assert "「앨리스의 책 출처 확인 문서」" in said  # 제목 기본값 '매번 묻기'라도 untitled면 '원고 제목 + 문서 종류'
    before = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*") if p.is_file()}
    with httpx2.Client(base_url=base, timeout=120) as bob:
        assert _login(bob, issuer_state, "sub-bob").status_code == 303
        csrf = _csrf(bob.get("/shelf").text)
        for path in ("/shelf/book/a", f"/shelf/doc/{doc_id}", f"/shelf/doc/{doc_id}/docx", f"/shelf/edit/doc.{doc_id}",
                     "/shelf/edit/ms.a", f"/shelf/trash/doc.{doc_id}", "/shelf/add?floor=a"):
            assert bob.get(path).status_code == 404, path
        for path in (f"/shelf/doc/{doc_id}/redo", f"/shelf/trash/doc.{doc_id}", "/shelf/trash/ms.a"):
            assert bob.post(path, data={"csrf": csrf}).status_code == 404, path
        assert "moveerr=unknown_category" in bob.post("/shelf/move", data={"csrf": csrf, "book": f"doc.{doc_id}", "to": "common",
                                                                            "next": "/shelf"}).headers["location"]
        moved = bob.get("/book", follow_redirects=False)
        assert moved.headers["location"] == "/shelf"  # 밥에게는 원고 책이 없다
    after = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*") if p.is_file()}
    assert before == after
