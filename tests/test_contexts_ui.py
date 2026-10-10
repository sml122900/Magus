"""책 설정의 컨텍스트 칸(2026-10-11 묶음 6, docs/decisions/2026-10-11-batch.md).

단추 줄이 '자주 쓰는 컨텍스트'라는 것이 제목으로 보이고("자주 쓰는 컨텍스트에서 고르기"), 줄 끝에 [+ 새로 만들기]와 [관리 →].
내 정보 › 자주 쓰는 컨텍스트에서는 모두(다섯 개여도) 보이고 만들기·고치기·지우기가 된다. 붙어 있는 곳이 있으면 지우기 전에
어느 책·노드에서 떨어지는지 같은 자리 확인 창에 보이고, 지우면 그 곳들(같은 이름의 사본)에서도 뗀다."""

from __future__ import annotations

import re

import httpx2

from magus.contexts import Context, SavedContext
from magus.store import LocalStore
from magus.webcontexts import context_fieldset
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

U = "alice"


def _seed(data_dir) -> tuple[str, str]:
    store = LocalStore(data_dir)
    store.create_project(U, "도시", project_id="city")
    store.save_saved_context(U, SavedContext("", "답사 기록", "현장에서 본 것을 적은 기록이다."))  # 처음 넷 + 하나 = 다섯
    node = store.add_node(U, "city", "답사", contexts=(Context("답사 기록", "현장에서 본 것을 적은 기록이다."),))
    book = store.create_category(U, "장날", "blank", "#1f2f5c", (), "city", node.id,
                                 contexts=(Context("답사 기록", "고쳐 쓴 사본"), Context("문체", "문학적 부분")))
    store.close()
    return node.id, book.id


def test_fieldset_shows_pick_title_new_and_manage():
    html = context_fieldset([SavedContext("ctx-style", "문체", "구절")], ())
    assert '<p class="ctx-pick-title" id="ctx-pick-title">자주 쓰는 컨텍스트에서 고르기</p>' in html
    assert 'aria-labelledby="ctx-pick-title"' in html and "<summary>+ 새로 만들기</summary>" in html
    assert 'name="ctx_make_name"' in html and '<button name="register" value="new">등록하고 붙이기</button>' in html
    assert html.index("문체</label>") < html.index("+ 새로 만들기") < html.index('<a class="ctx-manage" href="/me/contexts">관리 →</a>')
    empty = context_fieldset([], ())
    assert "자주 쓰는 컨텍스트에서 고르기" in empty and "+ 새로 만들기" in empty  # 하나도 없어도 만들 길이 있다


def test_new_context_from_book_settings_and_node(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    node, book = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        form = c.get(f"/login?next=/shelf/edit/{book}").text
        csrf = _csrf(form)
        assert "자주 쓰는 컨텍스트에서 고르기" in form and 'href="/me/contexts">관리 →</a>' in form and "+ 새로 만들기" in form
        rows_now = {"ctx_name": ["답사 기록", "문체"], "ctx_text": ["고쳐 쓴 사본", "문학적 부분"], "ctx_from": ["", ""]}  # 화면에 있던 줄
        made = c.post(f"/shelf/edit/{book}", data={"csrf": csrf, "name": "장날", "color": "#1f2f5c", "register": "new", **rows_now,
                                                    "ctx_make_name": "장터 말투", "ctx_make_text": "장터 사람들의 말을 그대로 적는다."})
        assert "「장터 말투」 등록하고 붙였습니다." in made.text
        assert re.search(r'<input type="checkbox" name="ctx_pick" value="ctx-[^"]+" data-name="장터 말투"[^>]* checked>', made.text)
        rows = re.findall(r'name="ctx_name" value="([^"]*)"', made.text)[:-1]  # 끝은 스크립트가 쓰는 빈 줄 틀(template)
        assert rows == ["답사 기록", "문체", "장터 말투"]  # 적은 것은 그대로, 새 것은 끝에 붙는다
        saved = c.post(f"/shelf/edit/{book}", data={"csrf": csrf, "name": "장날", "color": "#1f2f5c",
                                                     "ctx_name": rows, "ctx_text": ["고쳐 쓴 사본", "문학적 부분", "장터 사람들의 말을 그대로 적는다."],
                                                     "ctx_from": ["", "", ""]})
        assert "저장했습니다." in saved.text
        dup = c.post(f"/shelf/edit/{book}", data={"csrf": csrf, "name": "장날", "color": "#1f2f5c", "register": "new",
                                                   "ctx_make_name": "문체", "ctx_make_text": "겹치는 이름"})
        assert "이미 있습니다" in dup.text
        # 노드 설정의 '+ 새로 만들기'도 등록하고 그 노드에 붙인다
        post = c.post("/shelf/p/city/map", data={"csrf": csrf, "action": "contexts", "node": node, "register": "new",
                                                  "ctx_name": "답사 기록", "ctx_text": "현장에서 본 것을 적은 기록이다.", "ctx_from": "",
                                                  "ctx_make_name": "골목 지도", "ctx_make_text": "골목마다 그린 지도다."})
        assert "자주 쓰는 컨텍스트에 등록했습니다." in post.text
        new_node = c.get(f"/shelf/p/city?node={node}").text
        assert "자주 쓰는 컨텍스트에서 고르기" in new_node and "관리 →" in new_node  # '+ 노드' 칸에도 제목과 관리
    store = LocalStore(data_dir)
    names = [s.name for s in store.list_saved_contexts(U)]
    assert names[-2:] == ["장터 말투", "골목 지도"]
    assert [ctx.name for ctx in store.get_category(U, book).contexts] == ["답사 기록", "문체", "장터 말투"]
    assert [ctx.name for ctx in store.get_map(U, "city").node(node).contexts] == ["답사 기록", "골목 지도"]
    store.close()


def test_saved_contexts_page_shows_all_and_delete_detaches(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    node, book = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get("/login?next=/me/contexts").text
        csrf = _csrf(page)
        assert page.count('class="saved-ctx"') == 5  # 다섯 개 모두
        for name in ("문체", "원고", "논문", "생각 메모", "답사 기록"):
            assert f'name="name" value="{name}"' in page
        # 지우기는 같은 자리 확인 창. 붙은 곳을 먼저 보인다
        box = page.split('aria-label="답사 기록"')[1].split("</section>")[0]
        assert '<summary class="btn quiet">지우기</summary>' in box and "지우면 이 2곳에서도 떨어집니다." in box
        assert "<li>책 「장날」 · 「도시」</li>" in box and "<li>노드 「답사」 · 「도시」</li>" in box
        lone = page.split('aria-label="논문"')[1].split("</section>")[0]
        assert "<p>「논문」을 지울까요?</p>" in lone
        assert "confirm(" not in page
        # 만들기·고치기
        assert "더했습니다." in c.post("/me/contexts", data={"csrf": csrf, "action": "add", "name": "여섯째", "text": "여섯째 글"}).text
        ident = re.search(r'name="id" value="(ctx-[^"]+)">\s*<label class="block">이름 <input name="name" value="여섯째"', c.get("/me/contexts").text)
        assert ident is not None
        assert "저장했습니다." in c.post("/me/contexts", data={"csrf": csrf, "action": "save", "id": ident.group(1), "name": "여섯째",
                                                               "text": "고친 여섯째"}).text
        # 지우면 그 곳들에서도 뗀다(같은 이름의 사본, 고쳐 쓴 것도)
        target = re.search(r'name="id" value="(ctx-[^"]+)">\s*<label class="block">이름 <input name="name" value="답사 기록"', page).group(1)
        gone = c.post("/me/contexts", data={"csrf": csrf, "action": "delete", "id": target})
        assert "지웠습니다. 붙어 있던 2곳에서도 뗐습니다." in gone.text and 'value="답사 기록"' not in gone.text
    store = LocalStore(data_dir)
    assert store.get_map(U, "city").node(node).contexts == ()
    assert store.get_category(U, book).contexts == (Context("문체", "문학적 부분"),)  # 다른 이름은 그대로
    assert [s.name for s in store.list_saved_contexts(U)] == ["문체", "원고", "논문", "생각 메모", "여섯째"]
    store.close()
