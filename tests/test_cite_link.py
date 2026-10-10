"""인용 점검이 쓰는 연결 노드는 지우지 않는다(2026-10-11 묶음 마무리, 결정 3). 문헌 글이 든 노드와 같은 규칙:
웹 확인 창에는 까닭 한 줄과 '닫기'만, 보내도 막힌다. 올린 문서가 없는 프로젝트의 연결 노드나 문헌이 없는 노드로 가는 연결 노드는 지울 수 있다."""

from __future__ import annotations

import httpx2

from magus.category.moves import add_link
from magus.melchior.bibliography import import_bibliography
from magus.store import LocalStore
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

U = "alice"
BIB = "Clack, J. A. (2012). Gaining ground. Indiana University Press."


def _seed(data_dir) -> tuple[str, str]:
    store = LocalStore(data_dir)
    store.create_project(U, "물에서 뭍으로", project_id="book")
    store.write_chapter(U, "book", 1, "Clack(2012)에 따르면.", "x", title="하나")
    import_bibliography(store, U, BIB, "book")
    store.create_project(U, "둘째", project_id="second")
    store.write_chapter(U, "second", 1, "다시 Clack(2012).", "x", title="다시")
    import_bibliography(store, U, BIB, "second")  # 다른 프로젝트의 문헌: 둘째 지도에 서버가 연결 노드를 붙인다
    cited = next(n for n in store.get_map(U, "second").nodes if n.link)
    plain_target = store.add_node(U, "book", "메모")
    plain = add_link(store, U, "second", "book", plain_target.id)  # 문헌이 없는 노드로 가는 옛 연결 노드
    store.close()
    return cited.id, plain.id


def test_web_dialog_shows_the_reason_only(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    cited, plain = _seed(data_dir)
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get(f"/login?next=/shelf/p/second?node={cited}").text
        csrf = _csrf(page)
        box = page.split('aria-label="노드 휴지통으로">')[1].split("</details>")[0]
        assert "인용 점검이 이 문헌을 씁니다(「참고문헌」). 그래서 이 연결 노드는 지울 수 없습니다." in box
        assert 'value="trash"' not in box and "닫기" in box
        refused = c.post("/shelf/p/second/map", data={"csrf": csrf, "action": "trash", "node": cited})
        assert "maperr=cite_link" in str(refused.url) and "인용 점검이 이 문헌을 씁니다" in refused.text
        ok = c.post("/shelf/p/second/map", data={"csrf": csrf, "action": "trash", "node": plain})
        assert "노드를 휴지통으로 옮겼습니다." in ok.text
    store = LocalStore(data_dir)
    nodes = {n.id for n in store.get_map(U, "second").nodes}
    assert cited in nodes and plain not in nodes and store.cite_scope(U, "second") == ("second", "book")
    store.close()
