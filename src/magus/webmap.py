"""웹 프로젝트·지도(사용자 결정 #95, 2026-10-08. #93의 3D 책장을 대신한다). Web에 섞어 쓰는 MapPages.

- 첫 화면(/shelf): 프로젝트 목록(이름·최근 수정·노드 수)과 '+ 프로젝트'(제목만, 2026-10-10). 검색은 모든 프로젝트에서.
  올린 문서는 올린 파일(내 정보)이나 게시판 글의 첨부로 두고 대화에서 가져온다(book_import, 올린 문서 없는 project_id).
- 프로젝트 화면(/shelf/p/<프로젝트>)에서 끝낸다: 지도(마인드맵) + 패널. 상태는 주소에 둔다(?node=…&book=…&at=…, pushState).
  노드를 누르면 패널에 그 노드의 정면 2D 책장, 책을 누르면 같은 패널 아래(게시판 자리, iframe)에 그 책 화면
  (책은 게시판, 올린 문서는 탭, 올린 문서에서 만든 문서는 본문)이 뜬다. #96: 노드 머리에 노드의 컨텍스트, '+ 노드'와 노드 설정에서 컨텍스트를 붙인다. 데스크톱(1200px 이상)은 패널이 지도 오른쪽, 좁으면 아래.
- 지도 조작(스크립트, magus.webmap_assets): 노드 끌어 옮기기(위치 저장), 빈 곳 두 번 누르기·'+ 노드'로 만들기, 노드 가장자리의 ＋를
  다른 노드로 끌거나 '선 잇기'로 선 잇기, 선을 눌러 끊기, 휠·핀치·끌기로 확대·축소·이동, '가운데로'.
  패널의 책을 지도의 노드로 끌어 놓으면 그 노드로 옮긴다(키보드는 책 설정의 '위치').
- 스크립트 없이도, 키보드·낭독기로도 모든 일을 할 수 있게: 노드는 링크(Tab으로 이동, Enter로 열기), 목록 보기(노드 → 책 → 게시판),
  노드 설정(이름·색·선 잇기·끊기·휴지통)과 '+ 노드'는 폼이다. 휴대폰(768px 미만)은 목록이 먼저이고 '지도 보기'로 지도도 본다.
- 내려받기: 프로젝트 하나 또는 전체를 마크다운 폴더(zip)로(magus.export_zip).
- 외부 라이브러리·이미지·글꼴 없음(#56). 모든 POST는 CSRF를 확인하고, 이름은 모든 출력에서 이스케이프한다.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from magus.category.moves import (add_link, book_name, error_message, move_book, restore_node, trash_node_with_books, undo_move,
                                  web_message)
from magus.category.rules import PALETTE, parse_color
from magus.floors import MAX_FLOORS, josa
from magus.ids import local_time
from magus.melchior.check import after_refs_changed
from magus.maps import CENTER, LIBRARY_NAME, MAX_NODES, NODE_NAME_MAX
from magus.store import Floor, MapNode, ProjectMap, Store
from magus.store.floors import MoveError
from magus.store.formats import UNTITLED, clip, display_title, one_line
from magus.store.maps import MapError
from magus.webboard import marked_query, post_row_html, search_line
from magus.webmap_assets import MAP_SCRIPT, MAP_STYLE, PROJECTS_STYLE, TRASH_STYLE
from magus.contexts import Context, View
from magus.webcontexts import (CONTEXT_SCRIPT, CONTEXT_STYLE, context_fieldset, contexts_as_typed, contexts_from_form, contexts_view_html,
                               register_row)
from magus.webshelf import (
    GROUP_SIZE, Book, Kind, add_book, book_html, category_kind, clean_query, find,
    safe_at, shelf_html, state_url, text_color,
)

PROJECT_TITLE_MAX = 120
Hits = tuple[list[Any], list[tuple[Any, Any, list[Any], bool]]]  # 찾기: (이름이 맞은 노드, [(노드, 책, 맞은 글, 책 이름이 맞음)])


def _any_full(found: list[Hits]) -> bool:
    """모두 맞는 글이 하나라도 있나(후속 C). 없으면 일부 낱말만 맞는 글을 보인다."""
    return any(not r.partial for _, entries in found for _, _, rows, _ in entries for r in rows)


@dataclass(frozen=True)
class NodeDraft:
    """거절(400)한 노드 폼에 적었던 것(2026-10-09 결정 d). action: add_node(이름·고른 단추·직접 적은 글) | contexts(줄 그대로)."""

    action: str
    name: str = ""
    contexts: tuple[Context, ...] = ()
    picks: frozenset[str] = frozenset()
    new_text: str = ""


WHEN = "%m-%d %H:%M"
_NEXT = re.compile(r"/shelf(/[A-Za-z0-9_.\-/%]*)?")
_ID = re.compile(r"[A-Za-z0-9_.\-]{1,80}")
TRASH_FIELD = {"node": "node", "attachment": "attachment"}  # 휴지통 목록의 되살리기 폼 이름(그 밖은 글 item)
MAP_DONE = ("node", "link", "rename", "color", "connect", "disconnect", "node_trash", "project", "contexts", "ctx_saved",
            "restored", "project_restored")  # 지도 바꾸기 뒤 한 줄의 종류


def done_text(done: str, name: str) -> str:
    """지도 바꾸기 뒤 한 줄(정해진 문장만. name은 주소의 노드 id로 찾은 「이름」, 없으면 빈 문자열)."""
    return {
        "node": f"노드 {josa(name, '을/를')} 만들었습니다." if name else "노드를 만들었습니다.",
        "link": f"연결 노드 {josa(name, '을/를')} 만들었습니다." if name else "연결 노드를 만들었습니다.",
        "rename": f"노드 이름을 {josa(name, '으로/로')} 바꿨습니다." if name else "노드 이름을 바꿨습니다.",
        "color": "노드 색을 바꿨습니다.", "connect": "선을 이었습니다.", "disconnect": "선을 끊었습니다.",
        "node_trash": "노드를 휴지통으로 옮겼습니다.",
        "project": "프로젝트를 만들었습니다.",
        "contexts": "컨텍스트를 저장했습니다.",
        "restored": "되살렸습니다.",
        "project_restored": "프로젝트를 되살렸습니다.",
        "ctx_saved": "자주 쓰는 컨텍스트에 등록했습니다.",
    }[done]


def safe_next(value: str, fallback: str = "/shelf") -> str:
    """돌아갈 주소: 책장 아래의 주소만(질의 문자열 포함)."""
    path, _, query = (value or "").partition("?")
    if not _NEXT.fullmatch(path) or "//" in value or ".." in value:
        return fallback
    return path + (f"?{query}" if query else "")


def with_query(path: str, **params: str) -> str:
    """주소에 값을 더한다(같은 이름은 바꾼다)."""
    base, _, query = path.partition("?")
    pairs = [(k, v) for k, v in urllib.parse.parse_qsl(query) if k not in params] + [(k, v) for k, v in params.items() if v]
    return base + ("?" + urllib.parse.urlencode(pairs) if pairs else "")


def when_text(iso: str) -> str:
    return f"최근 수정 {local_time(iso, WHEN)}" if iso else "아직 없음"


def project_name(floor: Floor) -> str:
    return LIBRARY_NAME if floor.common else floor.title


def short_title(title: str, width: int = 24) -> str:
    """긴 제목은 부제('—', ':' 뒤)를 떼고 width자까지."""
    head = title.split(" — ")[0].split(":")[0].strip() or title
    return head if len(head) <= width else head[: width - 1] + "…"


def node_label(node: MapNode) -> str:
    """저자에게 보이는 노드 이름: 가운데 노드는 '가운데', 연결 노드는 '연결 · 이름'."""
    if node.center:
        return "가운데"
    return f"연결 · {node.name}" if node.link else node.name


def json_script(data: Any) -> str:
    """<script type="application/json">에 넣을 JSON(</script>로 끝나지 않게)."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


class MapPages:
    """Web에 섞어 쓰는 프로젝트·지도 화면. ShelfPages의 book_objects·_rows·_done_message와 Web의 공통 도구를 쓴다."""

    store: Store
    settings: Any
    _page: Callable[..., Response]
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]
    _csrf_input: Callable[[tuple[str, str]], str]
    _form: Callable[[Request, tuple[str, str]], Awaitable[Any]]
    csrf: Callable[[str], str]
    books: Callable[[str, str], list[Book]]
    book_objects: Callable[[str, Any], list[Book]]
    _posts: Callable[..., list[Any]]  # BoardPages
    _done_message: Callable[[str, Request], str]

    def map_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [
            ("/shelf", ["GET"], self.project_list),
            ("/shelf/projects", ["POST"], self.project_new),
            ("/shelf/export.zip", ["GET"], self.export_all),
            ("/shelf/p/{project}", ["GET"], self.project_page),
            ("/shelf/p/{project}/panel", ["GET"], self.project_panel),
            ("/shelf/p/{project}/map", ["POST"], self.map_post),
            ("/shelf/p/{project}/export.zip", ["GET"], self.export_project),
            ("/shelf/p/{project}/trash", ["GET", "POST"], self.project_trash),  # 노드 휴지통·되살리기(#97)
            ("/shelf/p/{project}/discard", ["POST"], self.project_discard),  # 프로젝트째 휴지통으로(2026-10-09)
            ("/shelf/trash", ["GET", "POST"], self.projects_trash),  # 휴지통의 프로젝트·되살리기(2026-10-09)
            ("/shelf/floor/{floor}", ["GET"], self.floor_redirect),
            ("/shelf/move", ["POST"], self.shelf_move),
            ("/shelf/undo", ["POST"], self.shelf_undo),
        ]

    def _map_page(self, title: str, body: str, session: tuple[str, str], status: int = 200, css: str = "", lead: str = "") -> Response:
        from magus.webbooks import BOOK_STYLE  # noqa: PLC0415  (올리기 진행 막대)
        from magus.webshelf import SHELF_STYLE  # noqa: PLC0415

        from magus.webboard import BOARD_STYLE  # noqa: PLC0415

        return self._page(title, body, session, status, current="프로젝트", css=SHELF_STYLE + BOOK_STYLE + CONTEXT_STYLE + BOARD_STYLE + css,
                          lead=lead)

    # ---- 프로젝트 목록 ------------------------------------------------------------------------
    async def project_list(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        params = request.query_params
        # 옛 주소: 게시판 자리(?at=·?next=)는 그 화면(별도 페이지)으로, 층·한 화면 책장(?floor=·?zoom=)은 그 프로젝트 화면으로
        if at := safe_at(params.get("at")) or safe_at(params.get("next")):
            return RedirectResponse(at, status_code=303)
        floor = params.get("floor") or params.get("zoom")
        if floor and await run_in_threadpool(self.store.get_floor, uid, floor):
            keep = {k: v for k, v in params.items() if k in ("done", "c", "full", "moved", "undone", "moveerr", "b", "t")}
            return RedirectResponse(state_url(floor, params.get("book"), **keep), status_code=303)
        q = clean_query(params.get("q"))
        floors = await run_in_threadpool(self.store.list_floors, uid)
        form = (f'<form method="get" action="/shelf" class="search" role="search">'
                f'<input type="search" name="q" value="{html.escape(q)}" aria-label="모든 프로젝트에서 찾기"><button>찾기</button></form>')
        if q:
            groups, count, partial = await run_in_threadpool(self._search_all_counted, uid, floors, q)
            hits = [g for g in groups if g]
            head = f'<p class="crumb"><a href="/shelf">← 프로젝트</a></p>{form}{search_line(q, count, "/shelf", partial)}'
            return self._map_page("프로젝트", head + "".join(hits), session, css=PROJECTS_STYLE)
        return await self._project_list_page(request, session)

    async def _project_list_page(self, request: Request, session: tuple[str, str], error: str = "", status: int = 200,
                                 draft_title: str = "") -> Response:
        """프로젝트 목록. error·draft_title: 새 프로젝트 제목을 거절한 뒤(400) 오류 한 줄과 적었던 제목."""
        uid = session[0]
        floors = await run_in_threadpool(self.store.list_floors, uid)
        form = ('<form method="get" action="/shelf" class="search" role="search">'
                '<input type="search" name="q" value="" aria-label="모든 프로젝트에서 찾기"><button>찾기</button></form>')
        notices = error + await run_in_threadpool(self._notices, uid, request, session, "/shelf")
        cards = await run_in_threadpool(self._project_cards, uid, floors, session, draft_title)
        trashed = len(await run_in_threadpool(self.store.list_trashed_projects, uid))
        body = (f"{notices}{form}<ul class=\"projects\">{cards}</ul>"
                '<p class="muted"><a href="/shelf/export.zip">전체 내려받기(zip)</a> · '
                f'<a href="/shelf/trash">휴지통{f" {trashed}" if trashed else ""}</a></p>')
        return self._map_page("프로젝트", body, session, status, css=PROJECTS_STYLE)

    def _project_cards(self, uid: str, floors: list[Floor], session: tuple[str, str], draft_title: str = "") -> str:
        library = [f for f in floors if f.common]
        works = sorted((f for f in floors if not f.common), key=lambda f: f.updated_at, reverse=True)
        cards = []
        for f in [*works, *library]:
            found = self.store.get_map(uid, f.id)
            nodes = len(found.nodes) if found else 0
            what = f" · {len(self.store.list_chapters(uid, f.id))}장" if f.has_manuscript else ""
            cards.append(f'<li class="pcard{" library" if f.common else ""}"><a href="{html.escape(state_url(f.id))}">'
                         f'<span class="pname">{html.escape(project_name(f))}</span>'
                         f'<span class="pmeta">{when_text(f.updated_at)}</span>'
                         f'<span class="pmeta">노드 {nodes}{what}</span></a></li>')
        room = sum(1 for f in floors if not f.common) < MAX_FLOORS
        csrf = self._csrf_input(session)
        # '+ 프로젝트'는 제목만(2026-10-10). 만들면 올린 문서 없는 프로젝트(가운데 노드만)의 지도로 간다
        new = (
            '<li class="pcard new"><h2>+ 프로젝트</h2>'
            f'<form method="post" action="/shelf/projects">{csrf}'
            f'<label class="block">제목 <input name="title" value="{html.escape(draft_title)}" data-count-max="{PROJECT_TITLE_MAX}" required>'
            '</label>'
            '<p><button class="primary">만들기</button></p></form></li>'
            if room else f'<li class="pcard new"><p class="muted">{MAX_FLOORS}개 가득</p></li>'
        )
        return "".join(cards) + new

    async def project_new(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._map_page("프로젝트", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        title = one_line(str(form.get("title") or ""))
        if not title:
            return RedirectResponse("/shelf?projecterr=empty", status_code=303)
        if len(title) > PROJECT_TITLE_MAX:  # 자르지 않고 거절, 적은 제목은 칸에 그대로(2026-10-09 결정 e)
            said = f"제목은 {PROJECT_TITLE_MAX}자까지입니다. 지금 {len(title)}자입니다."
            return await self._project_list_page(request, session, f'<p class="msg err">{html.escape(said)}</p>', 400, title)
        try:
            project = await run_in_threadpool(self.store.create_project, uid, title)
        except ValueError:
            return RedirectResponse("/shelf?projecterr=full", status_code=303)
        return RedirectResponse(state_url(project.id, node=CENTER, done="project"), status_code=303)

    async def floor_redirect(self, request: Request) -> Response:
        """옛 층 주소(/shelf/floor/<층>)는 그 프로젝트 화면으로."""
        keep = {k: v for k, v in request.query_params.items() if k in ("done", "c", "moved", "undone", "moveerr", "b", "t")}
        return RedirectResponse(state_url(request.path_params["floor"], **keep), status_code=303)

    # ---- 안내 한 줄 ---------------------------------------------------------------------------
    def _notices(self, uid: str, request: Request, session: tuple[str, str], here: str, found: ProjectMap | None = None) -> str:
        params = request.query_params
        done = params.get("done") or ""
        out = "" if done in MAP_DONE else self._done_message(uid, request)
        if done in MAP_DONE:
            node = found.node(params.get("n") or "") if found else None
            text = done_text(done, f"「{node.name}」" if node and not node.center else "")
            if lost := [p for p in (params.get("lost") or "").split(",") if p and _ID.fullmatch(p)]:
                names = "·".join(f"「{f.label}」" for f in self.store.list_floors(uid) if f.id in lost)
                text += f" {names} 인용 점검에서 빠짐." if names else ""
            trash = (f' <a href="/shelf/p/{urllib.parse.quote(found.floor)}/trash">휴지통</a>'
                     if done == "node_trash" and found else "")
            out += f'<p class="msg">{html.escape(text, quote=False)}{trash}</p>'
        long = f"제목은 {PROJECT_TITLE_MAX}자까지입니다." + (f" 지금 {params.get('n')}자입니다." if (params.get("n") or "").isdigit() else "")
        if err := {"empty": "제목을 적어 주세요.", "full": f"프로젝트는 {MAX_FLOORS}개까지입니다.", "long": long}.get(
                params.get("projecterr") or ""):
            out += f'<p class="msg err">{err}</p>'
        if done == "project_trashed":  # 프로젝트째 휴지통으로(2026-10-09)
            gone = next((t for t in self.store.list_trashed_projects(uid) if t.trash_id == params.get("t")), None)
            name = f"「{gone.title}」 " if gone else ""
            out += f'<p class="msg">{html.escape(name)}프로젝트를 휴지통으로 옮겼습니다. <a href="/shelf/trash">휴지통</a></p>'
        if params.get("pick") == "book":  # /shelf/new를 프로젝트 없이 열었을 때
            out += '<p class="msg">새 책은 프로젝트 안에서 만듭니다. 프로젝트를 골라 노드를 열면 「새 책」이 있습니다.</p>'
        if code := params.get("maperr"):
            named = params.get("name") or ""
            out += f'<p class="msg err">{html.escape(error_message(MapError(code, code, name=named, projects=named), polite=True))}</p>'
        if (moved := params.get("moved")) and (last := self.store.last_move(uid)) and last.id == moved:
            lost = [p for p in (params.get("lost") or "").split(",") if p and _ID.fullmatch(p)]
            undo = (f'<form method="post" action="/shelf/undo" class="inline undo">{self._csrf_input(session)}'
                    f'<input type="hidden" name="move" value="{html.escape(last.id)}">'
                    f'<input type="hidden" name="next" value="{html.escape(here)}"><button>되돌리기</button></form>')
            out += f'<div class="msg">{html.escape(web_message(self.store, uid, last, lost=lost))}{undo}</div>'
        if (undone := params.get("undone")) and (last := self.store.last_undone(uid)) and last.id == undone:
            out += f'<p class="msg">{html.escape(web_message(self.store, uid, last, undone=True))}</p>'
        if code := params.get("moveerr"):
            info = {}
            if code in ("clash", "undo_clash"):
                info = {"name": book_name(self.store, uid, params.get("b") or ""), "floor": self._floor_title(uid, params.get("t") or "")}
            out += f'<p class="msg err">{html.escape(error_message(MoveError(code, code, **info), polite=True))}</p>'
        return out

    def _floor_title(self, uid: str, floor_id: str) -> str:
        floor_id = floor_id.partition(":")[0]
        found = self.store.get_floor(uid, floor_id) if floor_id else None
        return f"「{found.label}」" if found else ""

    # ---- 프로젝트 화면 -------------------------------------------------------------------------
    def _view(self, uid: str, found: ProjectMap, params: Any) -> MapNode | None:
        """주소 → 열린 노드. book이 있으면 그 책이 꽂힌 노드(옮긴 뒤·만든 뒤 알림에 쓴다)."""
        node = found.node(params.get("node") or "")
        book_key = params.get("book") or None
        if book_key and node is None:
            node = found.node_of(book_key)
        return node

    async def project_page(self, request: Request, error: str = "", status: int = 200, node_id: str | None = None,
                           draft: NodeDraft | None = None) -> Response:
        """error: 지도 위에 보일 오류 한 줄(이미 HTML, 예: 노드 컨텍스트가 너무 길 때 400). 없는 노드 주소는 지도에 '없는 노드입니다.'(404).
        draft: 거절한 폼에 적었던 것. 그 폼을 펼쳐 다시 채운다(2026-10-09 결정 d)."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        floor_id = request.path_params["project"]
        found = await run_in_threadpool(self.store.get_map, uid, floor_id)
        floor = await run_in_threadpool(self.store.get_floor, uid, floor_id)
        if found is None or floor is None:
            return self.not_found(request, session, "프로젝트")
        params = request.query_params
        if at := safe_at(params.get("at")):  # 예전 주소(옆 패널의 게시판 자리) → 그 화면을 별도 페이지로(2026-10-09)
            return RedirectResponse(at, status_code=303)
        node = found.node(node_id) if node_id else await run_in_threadpool(self._view, uid, found, params)
        if params.get("node") and node is None and not error:
            error, status = '<p class="msg err">없는 노드입니다.</p>', 404
        here = state_url(floor_id, node=node.id if node else None)
        notices = error + await run_in_threadpool(self._notices, uid, request, session, here, found)
        q = clean_query(params.get("q"))
        view = params.get("view") if params.get("view") in ("map", "list") else "auto"
        search = ""
        if q:
            result, count, partial = await run_in_threadpool(self._search_project_counted, uid, floor, found, q)
            search = (f'<section class="pm-results" aria-label="찾은 것">{search_line(q, count, state_url(floor_id), partial)}'
                      f"{result}</section>")
        bar = self._toolbar(floor, found, q, view)
        new_node = await run_in_threadpool(self._new_node_form, uid, session, floor, found,
                                           draft if draft and draft.action == "add_node" else None)
        map_html = await run_in_threadpool(self._map_html, uid, found, node)
        list_html = await run_in_threadpool(self._list_html, uid, floor, found, node)
        panel = await run_in_threadpool(self._panel_html, uid, session, floor, found, node,
                                        draft if draft and draft.action == "contexts" else None)
        data = {"project": floor_id, "csrf": self.csrf(session[1]), "post": f"/shelf/p/{urllib.parse.quote(floor_id)}/map",
                "panel": f"/shelf/p/{urllib.parse.quote(floor_id)}/panel", "page": f"/shelf/p/{urllib.parse.quote(floor_id)}",
                "nodes": [{"id": n.id, "x": n.x, "y": n.y} for n in found.nodes], "edges": [list(e) for e in found.edges]}
        state = f' data-node="{html.escape(node.id)}"' if node else ""
        discard = await run_in_threadpool(self._project_delete, uid, session, floor)
        head = (f'<div class="pm-head"><h1 class="pm-title">{html.escape(project_name(floor))}</h1>{new_node}{discard}'
                f'<p class="pm-meta">노드 {len(found.nodes)} · 선 {len(found.edges)} · {when_text(floor.updated_at)}</p></div>')
        body = (f'{notices}<p class="crumb"><a href="/shelf">← 프로젝트</a></p><div class="pm" data-view="{view}">{head}{bar}{search}'
                f'<div class="pm-body"{state}><div class="pm-main">{map_html}{list_html}</div>'
                f'<aside class="pm-panel" id="panel" aria-label="노드의 책장">{panel}</aside></div></div>'
                f'<script type="application/json" id="map-data">{json_script(data)}</script>'
                + self._move_form(session, here) + MAP_SCRIPT)
        return self._map_page(project_name(floor), body, session, status, css=MAP_STYLE)

    def _toolbar(self, floor: Floor, found: ProjectMap, q: str, view: str) -> str:
        base = state_url(floor.id)
        return (
            '<div class="pm-bar">'
            f'<form method="get" action="{html.escape(base)}" class="search" role="search">'
            f'<input type="search" name="q" value="{html.escape(q)}" aria-label="이 프로젝트에서 찾기"><button>찾기</button></form>'
            '<div class="pm-tools">'
            '<button type="button" class="js-only" data-act="link" aria-pressed="false">선 잇기</button>'
            '<button type="button" class="js-only" data-act="fit">가운데로</button>'
            f'<a class="btn view-list" href="{html.escape(with_query(base, view="list"))}" data-view-to="list">목록 보기</a>'
            f'<a class="btn view-map" href="{html.escape(with_query(base, view="map"))}" data-view-to="map">지도 보기</a>'
            f'<a class="btn" href="/shelf/p/{urllib.parse.quote(floor.id)}/export.zip">내려받기</a>'
            f'<a class="btn" href="/shelf/p/{urllib.parse.quote(floor.id)}/trash">휴지통</a></div></div>'
        )

    def _new_node_form(self, uid: str, session: tuple[str, str], floor: Floor, found: ProjectMap, draft: NodeDraft | None = None) -> str:
        """'+ 노드': 새 노드(이름) 또는 다른 프로젝트의 노드를 연결. 지도의 빈 곳을 두 번 누르면 그 자리로 열린다.
        draft가 있으면(거절한 뒤) 펼친 채 적었던 이름·고른 단추·직접 적은 글을 다시 채운다."""
        csrf = self._csrf_input(session)
        post = f"/shelf/p/{urllib.parse.quote(floor.id)}/map"
        groups = []
        linked = {n.link for n in found.nodes if n.link}
        for other in self.store.list_floors(uid):
            if other.id == floor.id:
                continue
            other_map = self.store.get_map(uid, other.id)
            options = "".join(
                f'<option value="{html.escape(other.id)}:{html.escape(n.id)}"{" disabled" if (other.id, n.id) in linked else ""}>'
                f'{html.escape(node_label(n) if not n.center else "가운데 · " + project_name(other))}'
                f'{" — 이미 연결됨" if (other.id, n.id) in linked else ""}</option>'
                for n in (other_map.nodes if other_map else ()) if not n.link)
            if options:
                groups.append(f'<optgroup label="{html.escape(project_name(other))}">{options}</optgroup>')
        room = len(found.nodes) < MAX_NODES
        if not room:
            return f'<p class="muted pm-full">노드 {MAX_NODES}개 가득</p>'
        link = (f'<form method="post" action="{post}" class="pm-form">{csrf}<input type="hidden" name="action" value="add_link">'
                '<input type="hidden" name="x"><input type="hidden" name="y">'
                f'<label class="block">연결 노드 <select name="target" required>{"".join(groups)}</select></label>'
                '<p><button>연결</button></p></form>' if groups else "")
        saved = self.store.list_saved_contexts(uid)
        picks = draft.picks if draft else frozenset()
        chips = "".join(
            f'<label class="chip-toggle"><input type="checkbox" name="ctx_pick" value="{html.escape(c.id)}"'
            f'{" checked" if c.id in picks else ""}>{html.escape(c.name)}</label>'
            for c in saved)
        typed = draft.new_text if draft else ""
        contexts = (
            '<fieldset class="ctx ctx-mini"><legend>컨텍스트</legend>'
            + (f'<div class="chips" role="group" aria-label="자주 쓰는 컨텍스트">{chips}</div>' if chips else "")
            + f'<details{" open" if typed else ""}><summary>직접 적기</summary>'
            f'<label class="block">내용 <textarea name="ctx_new" data-count-max="500" rows="2">{html.escape(typed)}'
            "</textarea></label></details></fieldset>"
        )
        return (
            f'<details class="pm-new" id="new-node"{" open" if draft else ""}><summary class="btn primary-ish">+ 노드</summary>'
            '<div class="pm-new-in">'
            f'<form method="post" action="{post}" class="pm-form">{csrf}<input type="hidden" name="action" value="add_node">'
            '<input type="hidden" name="x"><input type="hidden" name="y">'
            f'<label class="block">이름 <input name="name" value="{html.escape(draft.name if draft else "")}"'
            f' data-count-max="{NODE_NAME_MAX}" required></label>'
            f'{contexts}'
            f'<p><button class="primary">만들기</button></p></form>{link}</div></details>'
        )

    # ---- 지도 ------------------------------------------------------------------------------
    def _map_html(self, uid: str, found: ProjectMap, selected: MapNode | None) -> str:
        pad = 260
        xs, ys = [n.x for n in found.nodes] or [0.0], [n.y for n in found.nodes] or [0.0]
        x0, y0, w, h = min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad
        pos = {n.id: n for n in found.nodes}
        edges = "".join(
            f'<g class="edge" data-a="{html.escape(a)}" data-b="{html.escape(b)}">'
            f'<line class="hit" x1="{pos[a].x}" y1="{pos[a].y}" x2="{pos[b].x}" y2="{pos[b].y}"/>'
            f'<line class="ln" x1="{pos[a].x}" y1="{pos[a].y}" x2="{pos[b].x}" y2="{pos[b].y}"/></g>'
            for a, b in found.edges if a in pos and b in pos)
        nodes = "".join(self._node_html(found, n, selected is not None and n.id == selected.id, self.book_objects(uid, n.books))
                        for n in found.nodes)
        return (
            f'<section class="map-view" aria-label="{html.escape(found.title)} 지도" data-project="{html.escape(found.floor)}">'
            f'<div class="world"><svg class="edges" aria-hidden="true" style="left:{x0}px;top:{y0}px;width:{w}px;height:{h}px" '
            f'viewBox="{x0} {y0} {w} {h}">{edges}<line class="band" x1="0" y1="0" x2="0" y2="0"/></svg>{nodes}'
            '<button type="button" class="edge-cut" hidden>선 끊기</button></div>'
            '<div class="zoom js-only"><button type="button" data-act="in" aria-label="확대">＋</button>'
            '<button type="button" data-act="out" aria-label="축소">－</button></div>'
            '<p class="map-say" role="status" aria-live="polite"></p></section>'
        )

    def _node_html(self, found: ProjectMap, n: MapNode, selected: bool, books: list[Book]) -> str:
        """노드 하나: 이름과 둘째 줄(node_sub)."""
        sub = node_sub(n, books)
        classes = "node" + (" center" if n.center else "") + (" link" if n.link else "") + (" missing" if n.missing else "") + (
            " on" if selected else "")
        style = f"left:{n.x}px;top:{n.y}px"
        if n.color:
            style += f";--nc:{n.color};--nfg:{text_color(n.color)}"
            classes += " colored"
        label = f"{node_label(n) if not n.center else '가운데 노드 ' + found.title}, {sub}"
        current = ' aria-current="true"' if selected else ""
        name = short_title(n.name, 24) if n.center else n.name
        return (f'<a class="{classes}" href="{html.escape(state_url(found.floor, node=n.id))}" data-node="{html.escape(n.id)}" '
                f'style="{style}" aria-label="{html.escape(label)}" title="{html.escape(n.name)}" draggable="false"{current}>'
                f'<span class="nname">{html.escape(name)}</span><span class="nsub">{html.escape(sub)}</span>'
                '<span class="knob" aria-hidden="true">＋</span></a>')

    def _list_html(self, uid: str, floor: Floor, found: ProjectMap, node: MapNode | None) -> str:
        """목록 보기(휴대폰의 첫 모습, 키보드·낭독기): 노드 → 책(누르면 그 책의 게시판 페이지)."""
        items = []
        for n in found.nodes:
            books = self.book_objects(uid, n.books)
            links = "".join(
                f'<li><a href="{html.escape(b.href or "")}">'
                f'{html.escape(b.name)}</a> <small>{html.escape(b.band + " · " if b.band else "")}{html.escape(_count_text(b))}</small></li>'  # 컨텍스트 · 수(#96)
                for b in books)
            sub = node_sub(n, books)
            title = ("가운데 · " + found.title) if n.center else node_label(n)
            items.append(f'<li><details data-node="{html.escape(n.id)}"{" open" if node is not None and node.id == n.id else ""}>'
                         f'<summary><b>{html.escape(title)}</b> '
                         f'<small>{html.escape(sub)}</small></summary>'
                         + (f'<ul class="nl-books">{links}</ul>' if links else '<p class="muted">책 없음</p>')
                         + f'<p><a href="{html.escape(state_url(floor.id, node=n.id))}#panel">열기</a></p></details></li>')
        edges = {n.id: node_label(n) for n in found.nodes}
        pairs = [(b, a) if b == CENTER else (a, b) for a, b in found.edges]  # 가운데를 앞에
        lines = " · ".join(f"{html.escape(edges[a])}–{html.escape(edges[b])}" for a, b in pairs if a in edges and b in edges)
        return (f'<section class="map-list" aria-label="노드 목록"><h2 class="sr-title">노드 목록</h2><ul class="nlist">{"".join(items)}</ul>'
                f'<p class="muted">선: {lines or "없음"}</p></section>')

    # ---- 패널(노드의 책장) ----------------------------------------------------------------------
    def _panel_html(self, uid: str, session: tuple[str, str], floor: Floor, found: ProjectMap, node: MapNode | None,
                    draft: NodeDraft | None = None) -> str:
        if node is None:
            return ('<div class="pp-node" id="pp-node"><h2 class="pp-title" id="pp-title" tabindex="-1">노드를 고르세요</h2></div>')
        books = self.book_objects(uid, node.books)
        target_floor, target_node = node.link if node.link else (floor.id, node.id)
        movable_from = target_floor
        shelf = shelf_html([book_html(b, movable_from) for b in books],
                           "" if node.missing else add_book(target_floor, target_node))
        if node.link:
            source = self.store.get_floor(uid, node.link[0])
            where = f"「{html.escape(node.link_title)}」의 「{html.escape(node.name)}」" if not node.missing else ""
            intro = ('<p class="msg err">원본 없음</p>' if node.missing else
                     f'<p class="pp-link">→ {where} '
                     + (f'<a href="{html.escape(state_url(source.id, node=node.link[1]))}">원본 열기</a>' if source else "")
                     + "</p>")
            kind = "연결 노드"
        else:
            intro = ""
            kind = "가운데 노드" if node.center else "노드"
        title = found.title if node.center else node.name
        hint = ""  # 책 열기·끌어 옮기기 설명은 도움말(docs/help)
        settings = self._node_settings(uid, session, floor, found, node, draft)
        context = "" if node.missing else contexts_view_html(View(node.contexts, node=node.name))  # 노드의 컨텍스트(#96)
        delete = self._node_delete(uid, session, floor, node)
        return (f'<div class="pp-node" id="pp-node" data-node="{html.escape(node.id)}">'
                f'<div class="pp-head"><h2 class="pp-title" id="pp-title" tabindex="-1">{html.escape(title)}</h2>'
                f'<span class="pp-kind">{kind} · 책 {len(books)}권</span>{delete}</div>{context}{intro}{shelf}{hint}{settings}</div>')

    def _project_delete(self, uid: str, session: tuple[str, str], floor: Floor) -> str:
        """지도 머리의 '🗑 휴지통으로'와 화면 안 확인 창(2026-10-09). 프로젝트째(가운데 노드·올린 문서 포함) 휴지통으로.
        「내 서재」에는 없다. 다른 프로젝트가 연결 중이면 그 프로젝트 이름과 '닫기'만. 수정본이 있으면 크게 알린다."""
        if floor.common:
            return ""
        info = self.store.project_trash_info(uid, floor.id)
        if info is None:
            return ""
        close = '<button type="button" class="del-cancel" onclick="this.closest(\'details\').open=false">{}</button>'
        name = f"「{project_name(floor)}」"
        if info.blocked == "linked":
            inner = (f'<p>{html.escape("·".join(f"「{x}」" for x in info.linked_from))}에서 연결하고 있어 휴지통으로 옮길 수 없습니다. '
                     "그 프로젝트의 연결 노드를 먼저 휴지통으로 옮겨 주세요.</p>"
                     f"<p>{close.format('닫기')}</p>")
        else:
            along = [f"노드 {info.nodes}개", f"책 {info.books}권", f"글 {info.items}개"]
            along += [f"문헌 글 {info.refs}편"] if info.refs else []
            along += [f"올린 문서 {info.chapters}장"] if info.chapters else []
            ask = f"프로젝트 {josa(name, '을/를')} 휴지통으로 옮길까요? 가운데 노드를 포함해 {'·'.join(along)}이 함께 옮겨집니다."
            warn = f'<p class="big-warn">수정본 {info.revisions}개가 함께 옮겨집니다.</p>' if info.revisions else ""
            inner = (f"<p>{html.escape(ask)}</p>{warn}"
                     f'<form method="post" action="/shelf/p/{urllib.parse.quote(floor.id)}/discard">{self._csrf_input(session)}'
                     f'<p><button class="primary">옮기기</button> {close.format("취소")}</p></form>')
        return ('<details class="node-del proj-del"><summary><span aria-hidden="true">🗑</span> 휴지통으로</summary>'
                f'<div class="del-box" role="dialog" aria-label="프로젝트 휴지통으로">{inner}</div></details>')

    async def project_discard(self, request: Request) -> Response:
        """프로젝트째 휴지통으로(POST, CSRF). 막히면 지도에 까닭(400). 옮기면 프로젝트 목록에 한 줄과 휴지통 링크."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            await self._form(request, session)
        except PermissionError:
            return self._map_page("프로젝트", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        floor_id = request.path_params["project"]
        try:
            trash_id = await run_in_threadpool(self.store.trash_project, uid, floor_id, "웹 지도에서 옮김")
        except ValueError as e:
            code = e.args[0] if e.args else ""
            if code == "missing":
                return self.not_found(request, session, "프로젝트")
            said = ("「내 서재」는 휴지통으로 옮기지 않습니다." if code == "library" else
                    f"{e.args[1]}에서 연결하고 있어 휴지통으로 옮길 수 없습니다." if code == "linked" else "휴지통으로 옮기지 못했습니다.")
            return await self.project_page(request, f'<p class="msg err">{html.escape(said)}</p>', 400)
        await run_in_threadpool(after_refs_changed, self.store, uid)  # 장별 미확인 수는 파생값이라 색인을 다시 만든 뒤 맞춘다
        return RedirectResponse(with_query("/shelf", done="project_trashed", t=trash_id), status_code=303)

    async def projects_trash(self, request: Request) -> Response:
        """휴지통의 프로젝트(2026-10-09): 옮긴 날짜·이름·올린 문서·수정본·책·글과 [되살리기]. 되살리면 그 프로젝트 지도로."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._map_page("휴지통", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            try:
                project = await run_in_threadpool(self.store.restore_project, uid, str(form.get("trash") or ""))
            except ValueError as e:
                code = e.args[0] if e.args and e.args[0] in ("taken", "full", "clash") else "missing"
                return RedirectResponse(with_query("/shelf/trash", err=code, name=str(e.args[1]) if len(e.args) > 1 else ""),
                                        status_code=303)
            await run_in_threadpool(after_refs_changed, self.store, uid)
            return RedirectResponse(state_url(project, done="project_restored"), status_code=303)
        rows = await run_in_threadpool(self.store.list_trashed_projects, uid)
        params = request.query_params
        named = params.get("name") or ""
        message = {"taken": f"같은 id의 프로젝트(「{named}」)가 이미 있어 되살리지 못했습니다.",
                   "full": f"프로젝트는 {MAX_FLOORS}개까지라 되살리지 못했습니다. 다른 프로젝트를 먼저 휴지통으로 옮겨 주세요.",
                   "clash": f"같은 이름의 책·문헌 글·문서(「{named}」)가 그사이 생겨 되살리지 못했습니다.",
                   "missing": "휴지통에 없는 프로젝트입니다."}.get(params.get("err") or "", "")
        csrf = self._csrf_input(session)
        items = "".join(
            f'<li><time datetime="{html.escape(t.trashed_at)}">{local_time(t.trashed_at, "%Y-%m-%d %H:%M")}</time> '
            f"<b>프로젝트 「{html.escape(t.title)}」</b>"
            f'<small class="trash-sub">올린 문서 {t.chapters}장 · 수정본 {t.revisions}개 · 책 {t.books}권 · 글 {t.items}개</small>'
            f'<form method="post" action="/shelf/trash" class="inline">{csrf}<input type="hidden" name="trash" value="{html.escape(t.trash_id)}">'
            "<button>되살리기</button></form></li>" for t in rows)
        from magus.webboard import SEP  # noqa: PLC0415

        lead = f'<nav class="trail" aria-label="위치"><a href="/shelf">프로젝트</a>{SEP}<span aria-current="page">휴지통</span></nav>'
        body = ((f'<p class="msg err">{html.escape(message)}</p>' if message else "")
                + (f'<p class="trash-count">{len(rows)}개</p><ol class="trash-list">{items}</ol>' if rows
                   else '<p class="empty">휴지통이 비었습니다.</p>'))
        return self._map_page("휴지통", body, session, css=TRASH_STYLE, lead=lead)

    def _node_delete(self, uid: str, session: tuple[str, str], floor: Floor, node: MapNode) -> str:
        """노드를 고르면 보이는 🗑과 화면 안의 작은 확인 창(#97 노드 삭제, confirm() 쓰지 않음). 가운데 노드에는 없다.
        다른 프로젝트가 연결 중이거나 문헌 글이 든 책이 있으면 까닭 한 줄과 '닫기'만."""
        if node.center:
            return ""
        info = self.store.node_trash_info(uid, floor.id, node.id)
        if info is None:
            return ""
        close = '<button type="button" class="del-cancel" onclick="this.closest(\'details\').open=false">{}</button>'
        name = f"「{node.name}」"
        if info.blocked == "linked":
            inner = (f'<p>{html.escape("·".join(f"「{x}」" for x in info.linked_from))}에서 연결하고 있어 지울 수 없습니다.</p>'
                     f"<p>{close.format('닫기')}</p>")
        elif info.blocked == "has_refs":
            inner = f'<p>문헌 글이 든 책 「{html.escape(info.refs_book)}」이 있어 지울 수 없습니다.</p><p>{close.format("닫기")}</p>'
        elif info.blocked:
            inner = f'<p>지울 수 없는 노드입니다.</p><p>{close.format("닫기")}</p>'
        else:
            if node.link:
                ask = f"연결 노드 {josa(name, '을/를')} 휴지통으로 옮길까요? 원본 노드와 그 책·글은 그대로 남습니다."
            elif info.books:
                ask = f"노드 {josa(name, '과/와')} 책 {info.books}권·글 {info.items}개를 휴지통으로 옮길까요?"
            else:
                ask = f"노드 {josa(name, '을/를')} 휴지통으로 옮길까요?"
            inner = (f"<p>{html.escape(ask)}</p>"
                     f'<form method="post" action="/shelf/p/{urllib.parse.quote(floor.id)}/map">{self._csrf_input(session)}'
                     f'<input type="hidden" name="action" value="trash"><input type="hidden" name="node" value="{html.escape(node.id)}">'
                     f'<p><button class="primary">옮기기</button> {close.format("취소")}</p></form>')
        return ('<details class="node-del"><summary aria-label="노드 휴지통으로" title="노드 휴지통으로">🗑</summary>'
                f'<div class="del-box" role="dialog" aria-label="노드 휴지통으로">{inner}</div></details>')

    def _node_settings(self, uid: str, session: tuple[str, str], floor: Floor, found: ProjectMap, node: MapNode,
                       draft: NodeDraft | None = None) -> str:
        """노드 설정(스크립트 없이도): 이름·색·선 잇기·끊기·휴지통. draft(컨텍스트를 거절한 뒤)면 펼친 채 적었던 줄을 다시 채운다."""
        csrf = self._csrf_input(session)
        post = f"/shelf/p/{urllib.parse.quote(floor.id)}/map"
        here = state_url(floor.id, node=node.id)
        hidden = (f'{csrf}<input type="hidden" name="node" value="{html.escape(node.id)}">'
                  f'<input type="hidden" name="next" value="{html.escape(here)}">')
        names = {n.id: n for n in found.nodes}
        neighbors = [b if a == node.id else a for a, b in found.edges if node.id in (a, b)]
        lines = "".join(
            f'<li>{html.escape(node_label(names[other]))} '
            f'<form method="post" action="{post}" class="inline">{hidden}<input type="hidden" name="action" value="disconnect">'
            f'<input type="hidden" name="other" value="{html.escape(other)}"><button>끊기</button></form></li>'
            for other in neighbors if other in names)
        free = [n for n in found.nodes if n.id != node.id and n.id not in neighbors]
        choices = "".join(f'<option value="{html.escape(n.id)}">{html.escape(node_label(n))}</option>' for n in free)
        connect = (f'<form method="post" action="{post}" class="pm-form">{hidden}<input type="hidden" name="action" value="connect">'
                   f'<label>이을 노드 <select name="other">{choices}</select></label> <button>선 잇기</button></form>' if free else "")
        rename = ("" if node.center or node.link else
                  f'<form method="post" action="{post}" class="pm-form">{hidden}<input type="hidden" name="action" value="rename">'
                  f'<label>이름 <input name="name" value="{html.escape(node.name)}" data-count-max="{NODE_NAME_MAX}" required></label> '
                  '<button>바꾸기</button></form>')
        swatches = "".join(f'<option value="{value}"{" selected" if node.color == value else ""}>{html.escape(name)}</option>'
                           for name, value in PALETTE)
        color = (f'<form method="post" action="{post}" class="pm-form">{hidden}<input type="hidden" name="action" value="color">'
                 f'<label>노드 색 <select name="color"><option value=""{"" if node.color else " selected"}>기본(흰색)</option>{swatches}</select></label> '
                 '<button>바꾸기</button></form>')
        contexts = ""
        if not node.link:  # 연결 노드의 컨텍스트는 원본 지도에서 바꾼다
            saved = self.store.list_saved_contexts(uid)
            contexts = (f'<form method="post" action="{post}" class="pm-form" data-guard>{hidden}'
                        '<input type="hidden" name="action" value="contexts">'
                        + context_fieldset(saved, draft.contexts if draft else node.contexts) + '<p><button>저장</button></p></form>')
        return (f'<details class="pp-set"{" open" if draft else ""}><summary>⚙ 설정</summary>{rename}{color}{contexts}'
                f'<h3>선</h3><ul class="pp-lines">{lines or "<li>없음</li>"}</ul>{connect}'
                f"</details>{CONTEXT_SCRIPT}")

    async def project_panel(self, request: Request) -> Response:
        """패널 위쪽(노드의 책장)만: 스크립트가 노드를 열 때 받아 바꾼다."""
        session = self.user_of(request)
        if not session:
            return Response("로그인이 필요합니다.", status_code=401)
        uid = session[0]
        floor = await run_in_threadpool(self.store.get_floor, uid, request.path_params["project"])
        found = await run_in_threadpool(self.store.get_map, uid, request.path_params["project"])
        if floor is None or found is None:
            return Response("없는 프로젝트입니다.", status_code=404)
        node = found.node(request.query_params.get("node") or "")
        body = await run_in_threadpool(self._panel_html, uid, session, floor, found, node)
        return HTMLResponse(body)

    # ---- 지도 바꾸기 ---------------------------------------------------------------------------
    async def map_post(self, request: Request) -> Response:
        """노드 옮기기·만들기·연결·이름·색·선·휴지통. 스크립트(fetch, JSON)와 폼(되돌아가기) 둘 다 받는다."""
        session = self.user_of(request)
        wants_json = "application/json" in request.headers.get("accept", "")
        if not session:
            return JSONResponse({"ok": False, "error": "로그인이 필요합니다."}, status_code=401) if wants_json else self._need_login(request)
        uid = session[0]
        floor_id = request.path_params["project"]
        try:
            form = await self._form(request, session)
        except PermissionError:
            if wants_json:
                return JSONResponse({"ok": False, "error": "잘못된 요청입니다. 화면을 새로 고쳐 주세요."}, status_code=403)
            return self._map_page("프로젝트", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        action = str(form.get("action") or "")
        node = str(form.get("node") or "")
        back = safe_next(str(form.get("next") or ""), state_url(floor_id, node=node or None))

        def num(name: str) -> float | None:
            try:
                return float(str(form.get(name) or ""))
            except ValueError:
                return None

        result: dict[str, Any] = {"ok": True}
        try:
            if action == "move_node":
                await run_in_threadpool(lambda: self.store.update_node(uid, floor_id, node, x=num("x"), y=num("y")))
                done = ""
            elif action == "add_node":
                saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
                attached = contexts_from_form(form, saved)
                made = await run_in_threadpool(lambda: self.store.add_node(uid, floor_id, str(form.get("name") or ""), x=num("x"), y=num("y"),
                                                                           contexts=attached))
                result["node"], done, back = made.id, "node", state_url(floor_id, node=made.id)
            elif action == "contexts":  # 노드 설정의 컨텍스트(#96). '자주 쓰는 컨텍스트로 등록'이면 등록만 한다
                if form.get("register") is not None:
                    text = await run_in_threadpool(register_row, self.store, uid, form)
                    if "msg err" in text:
                        raise MapError("ctx_register", "등록하지 못했다")
                    done = "ctx_saved"
                else:
                    saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
                    attached = contexts_from_form(form, saved)
                    await run_in_threadpool(self.store.set_node_contexts, uid, floor_id, node, attached)
                    done = "contexts"
            elif action == "add_link":
                target_floor, _, target_node = str(form.get("target") or "").partition(":")
                made = await run_in_threadpool(lambda: add_link(self.store, uid, floor_id, target_floor, target_node, x=num("x"), y=num("y")))
                result["node"], done, back = made.id, "link", state_url(floor_id, node=made.id)
            elif action == "rename":
                await run_in_threadpool(lambda: self.store.update_node(uid, floor_id, node, name=str(form.get("name") or "")))
                done = "rename"
            elif action == "color":
                raw = str(form.get("color") or "")
                color = parse_color(raw) if raw else ""
                await run_in_threadpool(lambda: self.store.update_node(uid, floor_id, node, color=color))
                done = "color"
            elif action in ("connect", "disconnect"):
                other = str(form.get("other") or "")
                call = self.store.connect_nodes if action == "connect" else self.store.disconnect_nodes
                await run_in_threadpool(call, uid, floor_id, node, other)
                done = action
            elif action == "trash":  # 노드 삭제(#97): 책·글·첨부·문서와 선째 휴지통으로. 막는 경우는 MapError
                _, lost = await run_in_threadpool(trash_node_with_books, self.store, uid, floor_id, node, "웹 지도에서 옮김")
                result["lost"] = lost
                done, back = "node_trash", state_url(floor_id, lost=",".join(lost))
            else:
                raise MapError("unknown_action", "모르는 동작")
        except (MapError, MoveError) as e:
            text = error_message(e, polite=True)
            if wants_json:
                return JSONResponse({"ok": False, "error": text}, status_code=400)
            return RedirectResponse(with_query(back, maperr=e.code, name=str(e.info.get("name") or e.info.get("projects") or "")),
                                    status_code=303)
        except ValueError as e:  # 색 이름·컨텍스트 길이 등
            if wants_json:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
            if action in ("add_node", "contexts"):  # 책 설정과 같이 400으로 그 자리에서, 적은 내용은 폼에 그대로(2026-10-09 결정 d)
                said = f"컨텍스트를 저장하지 못했습니다. {e}" if action == "contexts" else f"노드를 만들지 못했습니다. {e}"
                saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
                draft = NodeDraft(action, name=str(form.get("name") or ""), contexts=contexts_as_typed(form, saved),
                                  picks=frozenset(str(v) for v in form.getlist("ctx_pick")), new_text=str(form.get("ctx_new") or ""))
                return await self.project_page(request, f'<p class="msg err">{html.escape(said)}</p>', 400, node or None, draft)
            return RedirectResponse(with_query(back, maperr="bad_color"), status_code=303)
        if wants_json:
            return JSONResponse(result)
        target = result.get("node") or node
        return RedirectResponse(with_query(back, done=done, n=target) if done else back, status_code=303)

    # ---- 노드 휴지통(#97) ------------------------------------------------------------------------
    async def project_trash(self, request: Request) -> Response:
        """이 프로젝트의 휴지통: 지운 날짜·노드 또는 글과 [되살리기]. 노드는 원래 자리·선·책·글·첨부가, 글은 그 책에 응답한 글·첨부와
        함께 돌아온다(2026-10-09). 글은 이 프로젝트의 책에 든 것만, 함께 옮긴 응답 글은 따로 보이지 않는다."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        floor = await run_in_threadpool(self.store.get_floor, uid, request.path_params["project"])
        if floor is None:
            return self.not_found(request, session, "프로젝트")
        here = f"/shelf/p/{urllib.parse.quote(floor.id)}/trash"
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._map_page("휴지통", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            if att := str(form.get("attachment") or ""):  # 글에서 뺀 첨부 되살리기(2026-10-09) → 그 글로
                owner = att.rpartition("/")[0]
                if await run_in_threadpool(self._owner_floor, uid, owner) != floor.id:
                    return RedirectResponse(with_query(here, err="missing"), status_code=303)
                try:
                    await run_in_threadpool(self.store.restore_trash, uid, "attachment", att)
                except ValueError as e:
                    return RedirectResponse(with_query(here, err="item" if len(e.args) > 1 else "missing"), status_code=303)
                book, _, item = owner.partition("/")
                link = (f"/shelf/{self.store.get_ref(uid, owner[4:]).book}/{urllib.parse.quote(owner[4:])}"  # type: ignore[union-attr]
                        if owner.startswith("ref:") else f"/shelf/{book}/{item}")
                return RedirectResponse(f"{link}?done=restored", status_code=303)
            if post := str(form.get("item") or ""):  # 글 되살리기
                book = post.partition("/")[0]
                try:
                    owner = await run_in_threadpool(self.store.get_category, uid, book) if book else None
                except ValueError:
                    owner = None
                if owner is None or owner.floor != floor.id:
                    return RedirectResponse(with_query(here, err="missing"), status_code=303)
                try:
                    await run_in_threadpool(self.store.restore_trash, uid, "category_item", post)
                except ValueError:
                    return RedirectResponse(with_query(here, err="missing"), status_code=303)
                return RedirectResponse(f"/shelf/{post}?done=restored", status_code=303)
            ref = str(form.get("node") or "")
            if not ref.startswith(f"{floor.id}/"):
                return RedirectResponse(with_query(here, err="missing"), status_code=303)
            try:
                [restored] = await run_in_threadpool(restore_node, self.store, uid, ref)  # 인용 수도 다시(점검 13-b)
            except MapError as e:
                return RedirectResponse(with_query(here, maperr=e.code), status_code=303)
            except ValueError as e:
                name = str(e.args[1]) if len(e.args) > 1 else ""
                return RedirectResponse(with_query(here, err="name" if name else "missing", name=name), status_code=303)
            return RedirectResponse(state_url(floor.id, node=restored.partition("/")[2], done="restored"), status_code=303)
        items = await run_in_threadpool(self._trash_rows, uid, floor)
        params = request.query_params
        message = ""
        if params.get("err") == "name":
            message = (f'<p class="msg err">「{html.escape(params.get("name") or "")}」 책이 이미 있어 되살리지 못했습니다. '
                       "그 책 이름을 바꾼 뒤 되살려 주세요.</p>")
        elif params.get("err") == "item":
            message = '<p class="msg err">그 첨부의 글이 휴지통에 있어 되살리지 못했습니다. 글을 먼저 되살려 주세요.</p>'
        elif params.get("err"):
            message = '<p class="msg err">되살리지 못했습니다.</p>'
        elif code := params.get("maperr"):
            message = f'<p class="msg err">{html.escape(error_message(MapError(code, code), polite=True))}</p>'
        csrf = self._csrf_input(session)
        rows = "".join(
            f'<li><time datetime="{html.escape(t.trashed_at)}">{local_time(t.trashed_at, "%Y-%m-%d %H:%M")}</time> '
            f"<b>{html.escape(label)}</b>"
            + (f'<form method="post" action="{here}" class="inline">{csrf}'
               f'<input type="hidden" name="{TRASH_FIELD.get(t.kind, "item")}" value="{html.escape(t.id)}">'
               "<button>되살리기</button></form>" if ok else "")
            + (f'<small class="trash-sub">{html.escape(sub)}</small>' if sub else "") + "</li>" for t, label, sub, ok in items)
        from magus.webboard import SEP  # noqa: PLC0415

        lead = (f'<nav class="trail" aria-label="위치"><a href="/shelf">프로젝트</a>{SEP}'
                f'<a href="{html.escape(state_url(floor.id))}">{html.escape(project_name(floor))}</a>{SEP}'
                '<span aria-current="page">휴지통</span></nav>')
        body = message + (f'<p class="trash-count">{len(items)}개</p><ol class="trash-list">{rows}</ol>' if rows
                          else '<p class="empty">휴지통이 비었습니다.</p>')
        return self._map_page("휴지통", body, session, css=TRASH_STYLE, lead=lead)

    def _owner_floor(self, uid: str, owner: str) -> str | None:
        """첨부의 글(owner)이 있는 프로젝트. 글은 그 책의 프로젝트, 문헌 글은 그 문헌이 든 책의 프로젝트."""
        if owner.startswith("ref:"):
            ref = self.store.get_ref(uid, owner[4:])
            book = ref.book if ref else None
        else:
            book = owner.partition("/")[0]
        try:
            found = self.store.get_category(uid, book) if book else None
        except ValueError:
            found = None
        return found.floor if found else None

    def _trash_rows(self, uid: str, floor: Floor) -> list[tuple[Any, str, str, bool]]:
        """(휴지통 항목, 보일 이름, 그 아래 한 줄, 되살릴 수 있나). 이 프로젝트의 노드(안에 있던 것 한 줄)와, 이 프로젝트의 책에 든 글
        (함께 옮긴 응답 글은 빼고), 그 글에서 뺀 첨부. 노드째 옮기기 전에 먼저 버린 글도 따로 남긴다(노드를 되살린 뒤 되살린다). 최근 것부터."""
        books = {c.id: c for c in self.store.list_categories(uid, floors=[floor.id])}
        in_nodes = self.store.trashed_node_books(uid, floor.id)
        out = []
        trash = self.store.list_trash(uid)
        for t in trash:
            if t.kind == "attachment" and t.owner and self._owner_floor(uid, t.owner) == floor.id:
                out.append((t, f"첨부 「{t.preview}」 · 글 「{self._post_name(uid, t.owner, trash)}」", "", True))
                continue
            if t.kind == "node" and t.id.startswith(f"{floor.id}/"):
                out.append((t, t.preview, t.detail, True))
            elif t.kind == "category_item" and not t.with_id and (held := in_nodes.get(t.id.partition("/")[0])) is not None:
                title = clip(t.preview, 60) or UNTITLED  # 휴지통 기록의 보일 이름(점검 22-a)
                out.append((t, f"글 「{title}」 · 책 「{held[0]}」",
                            f"노드 {josa(f'「{held[1]}」', '과/와')} 함께 휴지통에 있는 책의 글입니다. 노드를 먼저 되살리면 따로 되살릴 수 있습니다.",
                            False))
            elif t.kind == "category_item" and not t.with_id and (book := books.get(t.id.partition("/")[0])) is not None:
                replies = sum(1 for x in self.store.list_trash(uid) if x.kind == "category_item" and x.with_id
                              and x.id.partition("/")[0] == book.id and x.with_id == t.id.partition("/")[2])
                names = self.store.trashed_item_attachments(uid, book.id, t.id.partition("/")[2])
                title = clip(t.preview, 60) or UNTITLED  # 휴지통 기록의 보일 이름(점검 22-a)
                files = len(names)
                along = [f"응답한 글 {replies}개" if replies else "", f"첨부 {files}개" if files else ""]  # 확인 창 문구와 같게
                out.append((t, f"글 「{title}」 · 책 「{book.name}」"
                            + (f" · {'·'.join(a for a in along if a)} 함께" if any(along) else ""), "", True))
        return out

    def _post_name(self, uid: str, owner: str, trash: list[Any]) -> str:
        """휴지통 목록에 보일 글 이름(60자). 글이 휴지통에 있으면 그 기록에서."""
        from magus.melchior.author_report import cite_label  # noqa: PLC0415

        if owner.startswith("ref:"):
            ref = self.store.get_ref(uid, owner[4:])
            name = cite_label(ref, ref.key) if ref else owner[4:]
        else:
            book, _, item_id = owner.partition("/")
            item = self.store.get_category_item(uid, book, item_id)
            if item is not None:
                files = self.store.list_attachments(uid, owner)
                name = display_title(item.title, item.content, item.fields, (a.name for a in files))
            else:
                name = next((x.preview for x in trash if x.kind == "category_item" and x.id == owner), "")
        return clip(name or UNTITLED, 60)

    # ---- 책 옮기기·되돌리기 ---------------------------------------------------------------------
    def _move_form(self, session: tuple[str, str], here: str) -> str:
        """끌어 놓으면 스크립트가 채워 보내는 폼(CSRF)."""
        return (f'<form id="move-form" method="post" action="/shelf/move" hidden>{self._csrf_input(session)}'
                f'<input type="hidden" name="book"><input type="hidden" name="to">'
                f'<input type="hidden" name="next" value="{html.escape(here)}"></form>')

    def location_form(self, uid: str, session: tuple[str, str], kind: Kind) -> str:
        """책 설정의 '위치': 프로젝트 · 노드를 고른다(키보드로 옮기는 길). 올린 문서에서 만든 문서는 올린 문서가 있는 프로젝트에만."""
        here = self.store.node_of_book(uid, kind.key)
        groups = []
        for f in self.store.list_floors(uid):
            if kind.base == "doc" and not f.has_manuscript:
                continue
            found = self.store.get_map(uid, f.id)
            options = "".join(
                f'<option value="{html.escape(f.id)}:{html.escape(n.id)}"{" selected" if here == (f.id, n.id) else ""}>'
                f'{html.escape(project_name(f))} · {html.escape("가운데 노드" if n.center else n.name)}</option>'
                for n in (found.nodes if found else ()) if not n.link)
            groups.append(f'<optgroup label="{html.escape(project_name(f))}">{options}</optgroup>')
        return (f'<h2>위치</h2><form method="post" action="/shelf/move" class="card">{self._csrf_input(session)}'
                f'<input type="hidden" name="book" value="{html.escape(kind.key)}"><input type="hidden" name="next" value="dest">'
                f'<label class="block">프로젝트 · 노드 <select name="to">{"".join(groups)}</select></label>'
                "<p><button>옮기기</button></p></form>")

    async def shelf_move(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._map_page("프로젝트", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        book, to = str(form.get("book") or ""), str(form.get("to") or "")
        to_floor, _, to_node = to.partition(":")
        nxt = str(form.get("next") or "/shelf")
        back = safe_next(nxt) if nxt != "dest" else "/shelf"
        try:
            move, lost = await run_in_threadpool(move_book, self.store, uid, book, to_floor, to_node or None)
        except (MoveError, MapError) as e:
            return RedirectResponse(with_query(back, moveerr=e.code, b=book, t=to), status_code=303)
        if nxt == "dest":
            target = state_url(move.to_floor, move.book, node=move.to_node)
        else:
            target = back
        return RedirectResponse(with_query(target, moved=move.id, lost=",".join(lost)), status_code=303)

    async def shelf_undo(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._map_page("프로젝트", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        back = safe_next(str(form.get("next") or "/shelf"))
        try:
            move = await run_in_threadpool(undo_move, self.store, uid, str(form.get("move") or ""))
        except (MoveError, MapError) as e:
            return RedirectResponse(with_query(back, moveerr=e.code), status_code=303)
        return RedirectResponse(with_query(back, undone=move.id, moved=""), status_code=303)

    # ---- 검색 ------------------------------------------------------------------------------
    def _search_project(self, uid: str, floor: Floor, found: ProjectMap, q: str) -> str:
        """이 프로젝트에서: 노드 이름, 책 이름, 게시판 내용. 결과를 누르면 그 노드·책이 열린다."""
        return self._search_project_counted(uid, floor, found, q)[0]

    def _search_project_counted(self, uid: str, floor: Floor, found: ProjectMap, q: str) -> tuple[str, int, bool]:
        """(HTML, 찾은 글 수, 일부 낱말만 맞음). 이 프로젝트에 모두 맞는 글이 하나도 없을 때만 일부 낱말만 맞는 글(후속 C)."""
        hits = self._project_hits(uid, floor, found, q)
        partial = not _any_full([hits])
        result, count = self._project_html(floor, hits, q, partial)
        return result, count, partial and count > 0

    def _project_hits(self, uid: str, floor: Floor, found: ProjectMap, q: str) -> Hits:
        """(이름이 맞은 노드, [(노드, 책, 맞은 글, 책 이름이 맞음)]). 책마다 그 책 게시판의 찾기(_posts)."""
        needle = q.replace(" ", "").lower()
        named = [n for n in found.nodes if needle and needle in n.name.replace(" ", "").lower()]
        doc_hits = set(find(self.store, uid, ["document"], q))
        entries: list[tuple[Any, Any, list[Any], bool]] = []
        seen: set[str] = set()
        for n in found.nodes:
            for b in self.book_objects(uid, n.books):
                if b.key in seen:
                    continue
                seen.add(b.key)
                in_name = bool(needle and needle in b.name.replace(" ", "").lower())
                kind = self._kind_of(uid, b.key)
                rows = self._posts(uid, kind, None, q) if kind is not None else []
                if b.key.startswith("doc.") and b.key[4:] in doc_hits:
                    in_name = True
                if rows or in_name:
                    entries.append((n, b, rows, in_name))
        return named, entries

    def _project_html(self, floor: Floor, hits: Hits, q: str, partial: bool) -> tuple[str, int]:
        """(HTML, 찾은 글 수). partial이 아니면(찾는 범위에 모두 맞는 글이 있으면) 일부 낱말만 맞은 글은 뺀다."""
        named, entries = hits
        parts = []
        posts = 0
        if named:
            parts.append("<p>노드: " + " · ".join(
                f'<a href="{html.escape(state_url(floor.id, node=n.id))}">{html.escape(node_label(n) if not n.center else n.name)}</a>'
                for n in named) + "</p>")
        lit = marked_query(q, [r for _, _, rows, _ in entries for r in rows]) if partial else q
        for n, b, rows, in_name in entries:
            rows = rows if partial else [r for r in rows if not r.partial]
            if not rows and not in_name:
                continue
            posts += len(rows)
            where = "" if n.name == b.name else f'{html.escape(node_label(n) if not n.center else "가운데")} · '
            more = (f' <small><a href="/shelf/{html.escape(b.key)}?q={html.escape(urllib.parse.quote(q))}">모두 보기</a></small>'
                    if len(rows) > GROUP_SIZE else "")
            items = "".join(post_row_html(r, lit) for r in rows[:GROUP_SIZE])
            band = f"{html.escape(b.band)} · " if b.band else ""
            parts.append(f'<section class="group"><h3>{where}<a href="{html.escape(b.href or "")}">'
                         f'{html.escape(b.name)}</a> <small>{band}{len(rows)}개</small>{more}</h3>'
                         + (f'<ol class="posts">{items}</ol>' if items else "") + "</section>")
        return "".join(parts), posts

    def _kind_of(self, uid: str, key: str) -> Kind | None:
        base, _, rest = key.partition(".")
        if base in ("ms", "doc"):
            return None
        try:
            category = self.store.get_category(uid, key)
        except ValueError:
            return None
        return category_kind(category) if category else None

    def _search_all(self, uid: str, floors: list[Floor], q: str) -> list[str]:
        """모든 프로젝트에서: 프로젝트마다 한 덩어리(HTML). 찾은 것이 없으면 빈 문자열."""
        return self._search_all_counted(uid, floors, q)[0]

    def _search_all_counted(self, uid: str, floors: list[Floor], q: str) -> tuple[list[str], int, bool]:
        """(프로젝트마다 HTML, 찾은 글 수, 일부 낱말만 맞음). 모든 프로젝트에 모두 맞는 글이 하나도 없을 때만 일부 낱말만 맞는 글(후속 C)."""
        needle = q.replace(" ", "").lower()
        collected: list[tuple[Floor, Hits | None]] = []
        for f in floors:
            found = self.store.get_map(uid, f.id)
            if found is None:
                collected.append((f, None))
                continue
            own = ProjectMap(found.floor, found.title, tuple(n for n in found.nodes if not n.link), found.edges, found.stored)
            collected.append((f, self._project_hits(uid, f, own, q)))
        partial = not _any_full([hits for _, hits in collected if hits is not None])
        out = []
        posts = 0
        for f, hits in collected:
            if hits is None:
                out.append("")
                continue
            inner, count = self._project_html(f, hits, q, partial)
            posts += count
            named = needle in project_name(f).replace(" ", "").lower()
            if not inner and not named:
                out.append("")
                continue
            out.append(f'<section class="fgroup"><h2><a href="{html.escape(state_url(f.id))}">{html.escape(project_name(f))}</a> '
                       f'<small>{when_text(f.updated_at)}</small></h2>'
                       + inner + "</section>")
        return out, posts, partial and posts > 0

    # ---- 내려받기 ----------------------------------------------------------------------------
    async def export_project(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        floor = await run_in_threadpool(self.store.get_floor, uid, request.path_params["project"])
        if floor is None:
            return self.not_found(request, session, "프로젝트")
        from magus.export_zip import build_zip, zip_name  # noqa: PLC0415

        data = await run_in_threadpool(build_zip, self.store, uid, [floor.id])
        return _zip_response(data, zip_name(project_name(floor)))

    async def export_all(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        from magus.export_zip import build_zip, zip_name  # noqa: PLC0415

        floors = await run_in_threadpool(self.store.list_floors, uid)
        data = await run_in_threadpool(build_zip, self.store, uid, [f.id for f in floors])
        return _zip_response(data, zip_name("Magus 전체"))


def node_sub(n: MapNode, books: list[Book]) -> str:
    """노드의 둘째 줄: 책 하나면 그 책의 수(이름이 노드와 다르면 책 이름과), 여럿이면 책 수, 가운데는 원고 장 수,
    연결 노드는 원본 프로젝트. 지도와 목록 보기가 함께 쓴다."""
    if n.link:
        return "원본 없음" if n.missing else f"연결 · {short_title(n.link_title, 14)}"
    if n.center:
        ms = next((b for b in books if b.key.startswith("ms.")), None)
        rest = len(books) - (1 if ms else 0)
        return " · ".join(x for x in (f"문서 {ms.count}장" if ms else "", f"책 {rest}권" if rest else "") if x) or "가운데"
    if len(books) == 1:
        return _count_text(books[0]) if books[0].name == n.name else f"{books[0].name} {_count_text(books[0])}"
    return f"책 {len(books)}권" if books else "빈 노드"


def _count_text(book: Book) -> str:
    if book.note is not None:
        return book.note.replace("\n", " ")
    if book.verified is not None:
        return f"확인 {book.verified} · 전체 {book.count}"
    return f"{book.count}개"


def _zip_response(data: bytes, name: str) -> Response:
    quoted = urllib.parse.quote(name, safe="")  # '/'도 인코딩(점검 6-c)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=\"magus.zip\"; filename*=UTF-8''{quoted}"})
