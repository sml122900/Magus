"""모든 동작을 책장에서(#94 → #96 종류 없음): 책 추가(새 책·문서 올리기·올린 문서에서 만든 문서), 올린 문서 화면(탭),
올린 문서에서 만든 문서(옛 판 기준·다시 만들기·내려받기), 컨텍스트(올린 문서 「원고」·문서의 설명), 옛 주소, 격리.

시나리오(사용자 요청 6절, #95부터 프로젝트·지도): 프로젝트 만들기 → 원고 책 만들기(파일 올리기) → 대화 없이 웹에서 원고 책 열기
→ 문서 책 만들기 도구 호출(Claude 역할은 시험에서 대신) → 문서 책이 그 프로젝트의 가운데 노드에 꽂힘 → 수정본 올리기 → '옛 판 기준' 표시.
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
        # 상단 메뉴는 프로젝트 하나(#94·#95)
        nav = shelf.split("<nav>")[1].split("</nav>")[0]
        assert 'href="/shelf"' in nav and ">프로젝트</a>" in nav and "/book" not in nav and "/inbox" not in nav
        # 1. 프로젝트 만들기(원고 없이 제목만)
        floor_page = c.post("/shelf/projects", data={"csrf": csrf, "title": "닿으려는 종"})
        floor_id = urllib.parse.urlparse(str(floor_page.url)).path.split("/")[-1]  # /shelf/p/<프로젝트>
        assert "프로젝트를 만들었습니다." in floor_page.text
        assert f'<a class="book add" href="/shelf/add?project={floor_id}&amp;node=center" aria-label="책 추가">' in floor_page.text
        # 2. 책 추가: 종류 고르기
        add = c.get(f"/shelf/add?project={floor_id}&node=center").text
        assert "<h2>새 책</h2>" in add and "<h2>문서 올리기</h2>" in add  # 만든 문서는 대화로(설명은 도움말, #97)
        assert "원고 책" not in add and "모음 책" not in add and "문서 책" not in add and "올린 원고" not in add  # 종류 이름·옛 이름을 쓰지 않는다(#96, #96-s)
        assert 'action="/shelf/manuscript" enctype="multipart/form-data" data-progress=' in add
        assert 'name="project" value="new"' in c.get("/shelf/add?project=common").text  # 「내 서재」에서 올리면 새 프로젝트
        # 3. 원고 책 만들기: 파일을 고르면 바로 올라가고 가져온다(받은함을 거치지 않음)
        assert c.post("/shelf/manuscript", data={"csrf": "틀림", "floor": floor_id},
                      files={"file": (manuscript.name, manuscript.read_bytes(), DOCX)}).status_code == 403
        bad = c.post("/shelf/manuscript", data={"csrf": csrf, "floor": floor_id}, files={"file": ("메모.txt", b"x", "text/plain")})
        assert bad.status_code == 400 and "올릴 문서는 docx 또는 pdf 파일이어야 합니다." in bad.text
        made = c.post("/shelf/manuscript", data={"csrf": csrf, "floor": floor_id},
                      files={"file": (manuscript.name, manuscript.read_bytes(), DOCX)})
        assert str(made.url).endswith(f"/shelf/book/{floor_id}?done=imported")
        assert re.search(r"올렸습니다: 7장 · 3부 · 확인 요청 \d+ · 문헌 \d+", made.text)
        assert '<details class="ctx"><summary>원고</summary><p>내가 쓰고 있는 책의 원고다.' in made.text  # 「원고」 컨텍스트가 붙는다
        assert c.get("/me/files").text.count("<tr><td>") == 0  # 올린 파일에는 남지 않는다
        # 4. 원고 책 화면: 탭
        tabs = {tab: c.get(f"/shelf/book/{floor_id}?tab={tab}").text for tab in ("chapters", "issues", "cites", "editions")}
        assert '<nav class="tabs" aria-label="올린 문서">' in tabs["chapters"] and "aria-current=page>장 목록</a>" in tabs["chapters"]
        assert "<td>제4장</td><td>닿으려는 손</td>" in tabs["chapters"] and "내려받기(docx)" in tabs["chapters"]
        assert "확인 요청" in tabs["issues"] and "<th>번호</th>" in tabs["issues"]
        assert "답해 주실 질문" in tabs["cites"] and "<h2>장별</h2>" in tabs["cites"]
        assert "<h2>답해 주실 질문" in c.get(f"/shelf/book/{floor_id}?tab=cites&view=questions").text
        assert "수정본 올리기" in tabs["editions"] and "처음 올린 문서 E1" in tabs["editions"]
        assert "리포트 — 처음 올린 문서" in c.get(f"/shelf/book/{floor_id}?tab=editions&report=1").text
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
        floor = c.get(f"/shelf/p/{floor_id}?node=center").text  # 원고 책과 문서 책은 가운데 노드에
        assert f'data-key="doc.{doc_id}"' in floor and '<span class="band bottom" aria-hidden="true"><span class="line">E1 기준</span>' in floor
        assert f'data-key="ms.{floor_id}"' in floor and '<span class="band top" aria-hidden="true">원고</span>' in floor
        doc = c.get(f"/shelf/doc/{doc_id}").text
        assert "출처 확인 문서 · 『" in doc
        assert '<details class="ctx"><summary>출처 확인 문서</summary>' in doc  # 문서의 설명이 컨텍스트로 붙는다(#96)
        assert "<h2>닿으려는 종 출처 확인 문서</h2>" in doc and "<i>Claude(AI)가 쓴 머리말입니다.</i>" in doc
        assert "<h3>1. 답해 주실 질문" in doc and "<h3>6. 이전 수정본 대비 바뀐 점</h3>" in doc and "만든 이력 1" in doc
        assert "window.print()" in doc and 'class="msg stale"' not in doc
        got = c.get(f"/shelf/doc/{doc_id}/docx")
        assert got.status_code == 200 and got.content[:2] == b"PK" and "attachment" in got.headers["content-disposition"]
        # 6. 수정본 올리기 → 문서 책은 옛 판 기준
        edition = c.post(f"/shelf/book/{floor_id}/edition", data={"csrf": csrf},
                         files={"file": (manuscript.name, manuscript.read_bytes(), DOCX)})
        assert str(edition.url).endswith("tab=editions&done=edition") and '<p class="msg">수정본 E2</p>' in edition.text
        assert "리포트 — 수정본 E2" in edition.text
        floor = c.get(f"/shelf/p/{floor_id}?node=center").text
        assert '<span class="band bottom stale" aria-hidden="true"><span class="line">옛 판</span><span class="line">기준</span>' in floor
        assert f"닿으려는 종 출처 확인 문서, 컨텍스트 출처 확인 문서, {STALE}" in floor
        doc = c.get(f"/shelf/doc/{doc_id}").text
        assert f"{STALE} · E1 → E2" in doc and "다시 만들기</button>" in doc
        redo = c.post(f"/shelf/doc/{doc_id}/redo", data={"csrf": csrf})
        assert "다시 만들었습니다." in redo.text and 'class="msg stale"' not in redo.text and "만든 이력 2" in redo.text
        assert "이 문서의 이전 판(v1, E1 기준" in redo.text  # 이전 것과 견준 수치
        assert "1번째 · " in c.get(f"/shelf/doc/{doc_id}?v=1").text
        # 7. 문서 책 설정: 이름·색, 위치는 원고가 있는 프로젝트의 노드만
        edit = c.get(f"/shelf/edit/doc.{doc_id}").text
        assert '<option value="common:' not in edit
        assert 'name="ctx_text"' in edit and ">올린 문서의 인용과 사실 확인 상태를 서버가 정리한 읽기용 문서다." in edit  # 그 자리에서 고친다
        assert re.search(rf'<option value="{floor_id}:center" selected>[^<]+ · 가운데 노드</option>', edit)
        blocked = c.post("/shelf/move", data={"csrf": csrf, "book": f"doc.{doc_id}", "to": "common", "next": f"/shelf/p/{floor_id}"})
        assert "올린 문서에서 만든 문서는 올린 문서가 있는 프로젝트에만 둘 수 있습니다." in blocked.text
        renamed = c.post(f"/shelf/edit/doc.{doc_id}", data={"csrf": csrf, "name": "출처 확인", "color": "#2f6db5"})
        assert "「출처 확인」 저장했습니다." in renamed.text and "--c:#2f6db5;" in renamed.text
        assert "<h2>위치</h2>" not in c.get(f"/shelf/edit/ms.{floor_id}").text  # 올린 문서는 가운데 노드 자체라 옮기지 않는다
        # 올린 문서의 컨텍스트도 책 설정에서: 단추를 끄면 뗀다(#96)
        c.post(f"/shelf/edit/ms.{floor_id}", data={"csrf": csrf, "name": "닿으려는 종", "color": "#4b2e1e"})
        assert '<span class="band top" aria-hidden="true"></span>' in c.get(f"/shelf/p/{floor_id}?node=center").text.split(f'data-key="ms.{floor_id}"')[1][:400]
        # 8. 원고 책 휴지통: 프로젝트는 원고 없는 프로젝트로 남고 문서 책은 그대로
        confirm = c.get(f"/shelf/trash/ms.{floor_id}").text
        assert "장 7 · " in confirm
        gone = c.post(f"/shelf/trash/ms.{floor_id}", data={"csrf": csrf})
        assert "휴지통으로 옮겼습니다." in gone.text and str(gone.url).startswith(f"{base}/shelf/p/{floor_id}")
        assert f'data-key="doc.{doc_id}"' in c.get(f"/shelf/p/{floor_id}?node=center").text
        assert c.get(f"/shelf/book/{floor_id}").status_code == 404
    store = LocalStore(data_dir)
    assert store.list_chapters("alice", floor_id) == [] and store.get_document("alice", doc_id) is not None
    assert list((data_dir / "users" / "alice" / "trash").glob(f"{floor_id}-*/project.json"))
    store.close()


STALE = "옛 판 기준"


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
        assert moved.headers["location"] == "/shelf"  # 밥에게는 올린 문서가 없다
    after = {p: p.read_bytes() for p in (data_dir / "users" / "alice").rglob("*") if p.is_file()}
    assert before == after
