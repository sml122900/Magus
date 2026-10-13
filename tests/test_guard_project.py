"""원고 프로젝트 삭제 보호(2026-10-14 사용자 결정, docs/decisions/guard-project.md).

- 올린 문서가 든 프로젝트를 휴지통으로 옮길 때: 확인 창에 "이 프로젝트에는 올린 문서(장 N개 · 수정본 EN)가 있습니다."와 이름 칸,
  이름을 그대로 적어야 [옮기기]가 켜진다. 서버도 다시 본다(이름이 틀리면 400, 아무것도 옮기지 않음).
- 휴지통에서: 그런 프로젝트(와 휴지통의 올린 문서)는 하나씩, 이름을 적어야 영구 삭제. [휴지통 비우기]는 그것을 빼고 비운 뒤
  "올린 문서가 든 프로젝트 N개는 남겼습니다."로 알린다.
- 올린 문서 휴지통(책 설정 🗑)도 같은 이름 칸. 대화(category_trash)로는 프로젝트를 휴지통으로 옮기지 못한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.server import build_server
from magus.store import LocalStore
from magus.store.base import UploadGuard, same_name

pytestmark = pytest.mark.anyio
U = "alice"


def _manuscript(store: LocalStore, pid: str = "city", title: str = "도시의 책", editions: int = 3) -> None:
    store.create_project(U, title, project_id=pid)
    store.write_chapter(U, pid, 1, "도시는 자란다.", "x", title="하나")
    store.write_chapter(U, pid, 2, "골목이 남는다.", "x", title="둘")
    pj = store.root / "users" / U / "projects" / pid / "project.json"
    data = json.loads(pj.read_text(encoding="utf-8"))  # 수정본 기록(시험용)
    data["editions"] = [{"number": n, "file": f"e{n}.docx", "uploaded_at": f"2026-10-0{n}T00:00:00.000Z"} for n in range(1, editions + 1)]
    pj.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_same_name_and_guard_text():
    assert same_name("도시의 책", "도시의 책") and same_name("  「도시의  책」 ", "도시의 책") and same_name("“도시의 책”", "도시의 책")
    assert not same_name("도시", "도시의 책") and not same_name("", "도시의 책") and not same_name(None, "도시의 책")
    assert UploadGuard("project", "도시의 책", 42, 3).sentence == "이 프로젝트에는 올린 문서(장 42개 · 수정본 E3)가 있습니다."
    assert UploadGuard("project", "도시의 책", 3, 1).what == "장 3개"  # 처음 올린 문서뿐이면 장 수만
    assert UploadGuard("manuscript", "도시의 책", 2, 0).sentence == "올린 문서(장 2개)입니다."


def test_store_trash_and_purge_need_the_name(store: LocalStore):
    _manuscript(store)
    store.create_project(U, "강", project_id="river")  # 올린 문서 없는 프로젝트는 이름 없이
    info = store.project_trash_info(U, "city")
    assert info.guard == UploadGuard("project", "도시의 책", 2, 3) and store.project_trash_info(U, "river").guard is None
    for typed in (None, "", "도시", "도시의 책들"):
        with pytest.raises(ValueError) as e:
            store.trash_project(U, "city", "x", confirm_name=typed)
        assert e.value.args == ("name", "도시의 책")
    assert [f.id for f in store.list_floors(U)] == ["city", "river"] and store.list_trashed_projects(U) == []  # 아무것도 옮기지 않음
    river = store.trash_project(U, "river", "x")
    city = store.trash_project(U, "city", "x", confirm_name=" 도시의 책 ")
    assert store.trash_guard(U, "project", city) == UploadGuard("project", "도시의 책", 2, 3)
    assert store.trash_guard(U, "project", river) is None and store.trash_guard(U, "project", "없음") is None
    assert [t.edition for t in store.list_trashed_projects(U) if t.trash_id == city] == [3]
    with pytest.raises(ValueError) as e:
        store.purge_trash(U, "project", city)
    assert e.value.args == ("name", "도시의 책") and (store.root / "users" / U / "trash" / "projects" / city).is_dir()
    store.purge_trash(U, "project", river)  # 올린 문서가 없으면 이름 없이
    assert store.purge_trash(U, "project", city, confirm_name="도시의 책") > 0
    assert store.list_trashed_projects(U) == []


def test_store_manuscript_trash_needs_the_name(store: LocalStore):
    _manuscript(store, editions=2)
    with pytest.raises(ValueError) as e:
        store.trash_manuscript(U, "city", "x")
    assert e.value.args == ("name", "도시의 책") and len(store.list_chapters(U, "city")) == 2
    store.trash_manuscript(U, "city", "x", confirm_name="도시의 책")
    [ms] = store.list_trashed_manuscripts(U)
    assert store.trash_guard(U, "manuscript", ms.id) == UploadGuard("manuscript", "도시의 책", 2, 2)
    store.trash_manuscript(U, "city", "x")  # 남은 빈 프로젝트(장·수정본 없음)의 올린 문서 자리는 이름 없이


def test_web_project_trash_dialog_needs_the_name(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    setup = LocalStore(data_dir)
    _manuscript(setup)
    setup.create_project(U, "강", project_id="river")
    setup.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        page = c.get("/login?next=/shelf/p/city").text
        csrf = _csrf(page)
        box = page.split('aria-label="프로젝트 휴지통으로">')[1].split("</details>")[0]
        assert '<p class="big-warn">이 프로젝트에는 올린 문서(장 2개 · 수정본 E3)가 있습니다.</p>' in box
        assert "확인을 위해 이름을 적어 주세요: 「도시의 책」" in box and 'name="confirm_name" data-confirm-name="도시의 책"' in box
        assert '<button class="primary" disabled>옮기기</button>' in box and "magusNameGuard" in page
        plain = c.get("/shelf/p/river").text.split('aria-label="프로젝트 휴지통으로">')[1].split("</details>")[0]
        assert "confirm_name" not in plain and '<button class="primary">옮기기</button>' in plain  # 올린 문서가 없으면 그대로
        for typed in ({}, {"confirm_name": "도시"}):
            refused = c.post("/shelf/p/city/discard", data={"csrf": csrf, **typed})
            assert refused.status_code == 400 and "프로젝트 이름이 맞지 않아 휴지통으로 옮기지 않았습니다." in refused.text
        assert c.get("/shelf/p/city").status_code == 200
        gone = c.post("/shelf/p/city/discard", data={"csrf": csrf, "confirm_name": "「도시의 책」"})
        assert str(gone.url).startswith(f"{base}/shelf?done=project_trashed")
        c.post("/shelf/p/river/discard", data={"csrf": csrf})
        # 휴지통: 원고 프로젝트 줄은 이름 칸, 비우기 확인 창은 남길 것을 미리 알린다
        trash = c.get("/shelf/trash").text
        assert '<p class="trash-count">2개</p>' in trash and "올린 문서가 든 프로젝트 1개는 남깁니다." in trash
        assert trash.count('name="confirm_name"') == 1 and '<button class="primary" disabled>영구 삭제</button>' in trash
        city = re.search(r'name="purge" value="(project:city-[^"]+)"', trash).group(1)
        wrong = c.post("/shelf/trash", data={"csrf": csrf, "purge": city})
        assert "err=confirm" in str(wrong.url) and "이름이 맞지 않아 영구 삭제하지 않았습니다." in wrong.text
        emptied = c.post("/shelf/trash", data={"csrf": csrf, "empty": "1"})
        assert "휴지통을 비웠습니다. 올린 문서가 든 프로젝트 1개는 남겼습니다." in emptied.text
        assert '<p class="trash-count">1개</p>' in emptied.text and "프로젝트 「도시의 책」" in emptied.text and "프로젝트 「강」" not in emptied.text
        purged = c.post("/shelf/trash", data={"csrf": csrf, "purge": city, "confirm_name": "도시의 책"})
        assert "영구 삭제했습니다." in purged.text and '<p class="empty">휴지통이 비었습니다.</p>' in purged.text


def test_web_manuscript_trash_needs_the_name(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    setup = LocalStore(data_dir)
    _manuscript(setup, "harbor", "항구", editions=1)
    setup.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        page = c.get("/login?next=/shelf/trash/ms.harbor").text
        csrf = _csrf(page)
        assert '<p class="big-warn">올린 문서(장 2개)입니다.</p>' in page and '<button class="primary" disabled>옮기기</button>' in page
        refused = c.post("/shelf/trash/ms.harbor", data={"csrf": csrf, "confirm_name": "항"})
        assert refused.status_code == 400 and "이름이 맞지 않아 휴지통으로 옮기지 않았습니다." in refused.text
        moved = c.post("/shelf/trash/ms.harbor", data={"csrf": csrf, "confirm_name": "항구"})
        assert moved.url.path == "/shelf/p/harbor"
        trash = c.get("/shelf/p/harbor/trash").text
        assert "올린 문서 「항구」 · 2장" in trash and "확인을 위해 이름을 적어 주세요: 「항구」" in trash


async def test_chat_cannot_move_a_project_to_the_trash(settings, store: LocalStore):
    _manuscript(store)
    async with Client(build_server(settings, store)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert set(tools["category_trash"].input_schema["properties"]) == {"note", "book", "item_id", "project", "node"}
        for args in ({"node": "도시의 책"}, {"node": "center"}, {"book": "도시의 책"}, {"book": "ms.city"}):
            result = await c.call_tool("category_trash", {"note": "지워 줘", "project": "city", **args})
            assert result.is_error, args
    assert [f.id for f in store.list_floors(U)] == ["city"] and len(store.list_chapters(U, "city")) == 2
    assert store.list_trashed_projects(U) == [] and store.list_trashed_manuscripts(U) == []
    log = (Path(store.root) / "users" / U / ".activity.log").read_text(encoding="utf-8")
    assert "휴지통으로" not in log and "대화" not in log  # 아무 일도 없었다(프로젝트 만들기 한 줄만)
