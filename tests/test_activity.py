"""활동 기록(2026-10-14 사용자 요청, magus.activity): 사용자 폴더의 .activity.log에 한 줄
`시각 · 동작 · 대상 종류 · 대상 id · 경로(웹·대화·운영자)`. 이메일·제목·본문·파일 이름은 넣지 않는다. 90일 지난 줄은 지운다.
한 동작 안에서 저장소가 다른 동작을 불러도(노드째 휴지통, 올린 문서 휴지통 = 옮기기 + 빈 프로젝트 만들기) 바깥 동작 한 줄만."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus import activity
from magus.docupdate import update_document
from magus.server import build_server
from magus.store import CategoryItem, LocalStore

pytestmark = pytest.mark.anyio
U = "alice"
ITEM = "20261014000000001-aaaaaa"
LIMITS = {"max_attach": 20_000_000, "max_upload": 50_000_000, "max_user": 1_000_000_000}


def _log(store_root: Path, user: str = U) -> list[list[str]]:
    """줄마다 [동작, 대상 종류, 대상 id, 경로](시각은 형식만 본다)."""
    path = store_root / "users" / user / activity.LOG_NAME
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        at, *rest = line.split(" · ")
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", at), line
        out.append(rest)
    return out


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_line_and_ninety_days(tmp_path: Path):
    now = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)
    user = tmp_path / "users" / "alice"
    activity.write(user, activity.TRASH, "project", "book", now=now - timedelta(days=120))
    activity.write(user, activity.RESTORE, "project", "book", now=now - timedelta(days=89))
    assert len((user / activity.LOG_NAME).read_text(encoding="utf-8").splitlines()) == 2  # 89일 전 기록 때는 120일 전 줄이 아직 90일 안
    activity.write(user, activity.CREATE, "project", "새 프로젝트·id", now=now)
    assert (user / activity.LOG_NAME).read_text(encoding="utf-8").splitlines() == [
        f"{_iso(now - timedelta(days=89))} · 되살리기 · 프로젝트 · book · 운영자",
        f"{_iso(now)} · 프로젝트 만들기 · 프로젝트 · 새_프로젝트_id · 운영자",  # 대상 id의 공백·가운뎃점은 _
    ]
    other = tmp_path / "users" / "bob"
    activity.write(other, activity.PURGE, "inbox", "x", now=now - timedelta(days=100))
    assert activity.prune_all(tmp_path / "users", now) == 1 and (other / activity.LOG_NAME).read_text(encoding="utf-8") == ""
    with activity.via(activity.WEB):
        assert activity.line(activity.EMPTY, "trash", "전체", at="t").endswith(" · 휴지통 비우기 · 휴지통 · 전체 · 웹")
    assert activity.VIA.get() == activity.OPERATOR


def test_store_actions_one_line_each_without_names(store: LocalStore):
    store.create_project(U, "비밀 제목", project_id="city")
    store.write_chapter(U, "city", 1, "본문 내용", "x", title="장 제목")
    node = store.add_node(U, "city", "답사")
    store.create_category(U, "장날", "blank", "#1f2f5c", (), "city", node.id, category_id="market")
    store.put_category_item(U, CategoryItem(ITEM, "market", "장날 기록", "me", title="장날 글", title_by="author"))
    att = store.put_attachment(U, f"market/{ITEM}", "현장 사진 메모.txt", "사진".encode())
    store.trash_attachment(U, f"market/{ITEM}", att.id, "뺌")
    store.restore_trash(U, "attachment", f"market/{ITEM}/{att.id}")
    store.trash_node_with_books(U, "city", node.id, "노드째")  # 책도 함께 옮기지만 한 줄
    store.restore_trash(U, "node", f"city/{node.id}")
    with pytest.raises(ValueError):
        store.trash_project(U, "city", "x")  # 막힌 동작은 적지 않는다
    with pytest.raises(ValueError):
        store.restore_project(U, "없는-휴지통")
    trash_id = store.trash_project(U, "city", "x", confirm_name="비밀 제목")
    store.restore_project(U, trash_id)
    store.trash_manuscript(U, "city", "x", confirm_name="비밀 제목")  # 옮기기 + 같은 id의 빈 프로젝트 만들기 → 한 줄
    [ms] = store.list_trashed_manuscripts(U)
    store.purge_trash(U, "manuscript", ms.id, confirm_name="비밀 제목")
    store.put_inbox(U, "예전 원고.docx", b"PK0")
    inbox = store.trash_inbox(U, "예전 원고.docx", "바꿈")
    store.restore_inbox(U, inbox)
    assert _log(store.root) == [
        ["프로젝트 만들기", "프로젝트", "city", "운영자"],
        ["휴지통으로", "첨부", f"market/{ITEM}/{att.id}", "운영자"],
        ["되살리기", "첨부", f"market/{ITEM}/{att.id}", "운영자"],
        ["휴지통으로", "노드", f"city/{node.id}", "운영자"],
        ["되살리기", "노드", f"city/{node.id}", "운영자"],
        ["휴지통으로", "프로젝트", "city", "운영자"],
        ["되살리기", "프로젝트", "city", "운영자"],
        ["휴지통으로", "올린 문서", ms.id, "운영자"],
        ["영구 삭제", "올린 문서", ms.id, "운영자"],
        ["휴지통으로", "올린 파일", inbox, "운영자"],  # 파일 이름 대신 휴지통 id
        ["되살리기", "올린 파일", inbox, "운영자"],
    ]
    text = (store.root / "users" / U / activity.LOG_NAME).read_text(encoding="utf-8")
    for secret in ("비밀 제목", "본문", "장 제목", "답사", "장날", "현장 사진", "예전 원고", "@"):
        assert secret not in text
    assert not (store.root / "users" / "bob").exists()  # 다른 사용자 폴더는 만들지 않는다


def test_document_update_is_one_line(store: LocalStore):
    store.create_project(U, "자료", project_id="lib")
    store.create_category(U, "자료", "blank", "#1f2f5c", (), "lib", category_id="bk")
    store.put_category_item(U, CategoryItem(ITEM, "bk", "본문", "me"))
    att = store.put_attachment(U, f"bk/{ITEM}", "회의록.md", "첫 판".encode())
    store.put_inbox(U, "메모.md", "옛 메모".encode())
    data = "새 판".encode()
    update_document(store, U, f"att:{att.id}", "회의록 2.md", io.BytesIO(data), len(data), None, **LIMITS)
    update_document(store, U, "inbox:메모.md", "새 메모.md", io.BytesIO(data), len(data), "메모", **LIMITS)
    [(trash_id, _, _)] = store.list_trashed_inbox(U)
    assert _log(store.root)[1:] == [["문서 업데이트", "첨부", f"bk/{ITEM}/{att.id}", "운영자"],
                                    ["문서 업데이트", "올린 파일", trash_id, "운영자"]]  # 안에서 옮긴 이전 파일은 따로 적지 않는다
    assert "회의록" not in (store.root / "users" / U / activity.LOG_NAME).read_text(encoding="utf-8")


async def test_chat_path(settings, store: LocalStore):
    store.create_project(U, "자료", project_id="lib")
    store.create_category(U, "메모", "blank", "#1f2f5c", (), "lib", category_id="memo")
    store.put_category_item(U, CategoryItem(ITEM, "memo", "버릴 글", "me"))
    async with Client(build_server(settings, store)) as c:
        result = await c.call_tool("category_trash", {"note": "지워 줘", "book": "메모", "item_id": ITEM, "project": "lib"})
        assert not result.is_error
    assert _log(store.root)[-1] == ["휴지통으로", "글", f"memo/{ITEM}", "대화"]


def test_web_path(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        csrf = _csrf(c.get("/login?next=/shelf").text)
        made = c.post("/shelf/projects", data={"csrf": csrf, "title": "웹에서 만든 비밀 제목"})
        pid = made.url.path.split("/")[3]
        c.post(f"/shelf/p/{pid}/discard", data={"csrf": csrf})
        trash_id = re.search(r'name="trash" value="([^"]+)"', c.get("/shelf/trash").text).group(1)
        c.post("/shelf/trash", data={"csrf": csrf, "empty": "1"})
    assert _log(data_dir) == [["프로젝트 만들기", "프로젝트", pid, "웹"], ["휴지통으로", "프로젝트", pid, "웹"],
                              ["휴지통 비우기", "휴지통", "전체", "웹"], ["영구 삭제", "프로젝트", trash_id, "웹"]]
    assert "비밀 제목" not in (data_dir / "users" / U / activity.LOG_NAME).read_text(encoding="utf-8")
