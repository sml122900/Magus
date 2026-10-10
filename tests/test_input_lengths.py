"""입력 길이·검증(2026-10-09 구조·버그 점검 5번): 말없이 자르지 않는다. 칸 옆에 'n/한도'(스크립트), 넘치면 저장을 막고 안내하며
적은 것은 그대로 다시 보인다. 새 책·책 설정이 거절되어도 '직접 고르기'와 고른 색이 남는다. 400 문구는 '~습니다'·「」."""

from __future__ import annotations

import httpx2
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.category.rules import NAME_MAX, TITLE_MAX
from magus.store import CategoryItem, LocalStore

from conftest import with_library

BOOK = "notes-common"
ITEM = "20261009000000000-aaaaaa"


def test_lengths_are_shown_and_not_cut(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    store = LocalStore(data_dir)
    with_library(store, "alice")
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id=BOOK)
    store.put_category_item("alice", CategoryItem(ITEM, BOOK, "본문", "me", "제목", "author"))
    store.close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=60) as c:
        write = c.get(f"/login?next=/shelf/write/{BOOK}").text
        csrf = _csrf(write)
        assert f'name="title" value="" data-count-max="{TITLE_MAX}"' in write and "maxlength" not in write.split("<main>")[1]
        assert 'document.addEventListener("submit"' in write  # 넘치면 그 칸에 머문 채 저장을 막는 스크립트
        long_title = "가" * (TITLE_MAX + 1)
        refused = c.post(f"/shelf/write/{BOOK}", data={"csrf": csrf, "title": long_title, "content": "적은 본문"})
        assert refused.status_code == 400 and f"제목은 {TITLE_MAX}자까지입니다. 지금 {TITLE_MAX + 1}자입니다." in refused.text
        assert f'value="{long_title}"' in refused.text and ">적은 본문</textarea>" in refused.text  # 적은 것 그대로
        assert len(LocalStore(data_dir).list_category_items("alice", BOOK)) == 1  # 저장하지 않았다
        edit = c.post(f"/shelf/{BOOK}/{ITEM}/edit", data={"csrf": csrf, "title": long_title, "content": "고친 본문"})
        assert edit.status_code == 400 and ">고친 본문</textarea>" in edit.text
        assert LocalStore(data_dir).get_category_item("alice", BOOK, ITEM).title == "제목"
        # 책 이름: 12자 넘으면 막고, '직접 고르기'와 고른 색을 그대로
        new = c.get("/shelf/new?project=common").text
        assert f'name="name" value="" data-count-max="{NAME_MAX}"' in new
        bad = c.post("/shelf/new?project=common", data={"csrf": csrf, "name": "가" * (NAME_MAX + 1), "color": "custom", "hex": "#123456",
                                                         "was": "#1f2f5c", "picker": "#123456"})
        assert bad.status_code == 400 and f"책 이름은 {NAME_MAX}자까지입니다(책등에 들어가는 길이). 지금 {NAME_MAX + 1}자입니다." in bad.text
        assert '<input type="radio" name="color" value="custom" checked>' in bad.text and 'name="hex" value="#123456"' in bad.text
        palette = c.post("/shelf/new?project=common", data={"csrf": csrf, "name": "수정본", "color": "#b3261e", "hex": "#1f2f5c",
                                                             "was": "#1f2f5c", "picker": "#1f2f5c"})
        assert palette.status_code == 400 and '<input type="radio" name="color" value="#b3261e" checked>' in palette.text
        reserved = c.post(f"/shelf/edit/{BOOK}", data={"csrf": csrf, "name": "전체", "color": "custom", "hex": "#654321"})
        assert reserved.status_code == 400 and "「전체」는 Magus가 쓰는 말이라 책 이름으로 쓸 수 없습니다." in reserved.text
        assert '<input type="radio" name="color" value="custom" checked>' in reserved.text and 'name="hex" value="#654321"' in reserved.text
        # 프로젝트 제목·컨텍스트
        long_project = c.post("/shelf/projects", data={"csrf": csrf, "title": "가" * 121})
        assert long_project.status_code == 400 and "제목은 120자까지입니다. 지금 121자입니다." in long_project.text
        assert 'name="title" value="' + "가" * 121 + '"' in long_project.text  # 적은 제목 그대로(결정 e)
        ctx = c.post(f"/shelf/edit/{BOOK}", data={"csrf": csrf, "name": "메모", "ctx_new": "가" * 501})
        assert ctx.status_code == 400 and "컨텍스트 내용은 하나에 500자까지입니다. 지금 501자입니다." in ctx.text
        me = c.post("/me", data={"csrf": csrf, "display_name": "나" * 41})
        assert me.status_code == 400 and 'value="' + "나" * 41 + '"' in me.text  # 적은 이름 그대로
