"""웹 프로젝트·지도(사용자 결정 #95, 2026-10-08. #93의 3D 책장을 대신한다). Web에 섞어 쓰는 MapPages.

- 첫 화면(/shelf): 프로젝트 목록(이름·최근 수정·노드 수)과 '+ 프로젝트'(원고 올리기 또는 제목만). 검색은 모든 프로젝트에서.
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
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from magus.category.moves import add_link, book_name, error_message, move_book, trash_node, undo_move, web_message
from magus.category.rules import PALETTE, parse_color
from magus.floors import MAX_FLOORS, josa
from magus.ids import local_time
from magus.maps import CENTER, LIBRARY_NAME, MAX_NODES, NODE_NAME_MAX
from magus.store import Floor, MapNode, ProjectMap, Store
from magus.store.floors import MoveError
from magus.store.formats import one_line
from magus.store.maps import MapError
from magus.webmap_assets import MAP_SCRIPT, MAP_STYLE, PROJECTS_STYLE
from magus.contexts import View
from magus.webcontexts import CONTEXT_SCRIPT, CONTEXT_STYLE, context_fieldset, contexts_from_form, contexts_view_html, register_row
from magus.webshelf import (
    EMBED, GROUP_SIZE, Book, Kind, add_book, book_html, category_kind, clean_query, find, row_html,
    safe_at, shelf_html, state_url, text_color,
)

PROJECT_TITLE_MAX = 120
WHEN = "%m-%d %H:%M"
_NEXT = re.compile(r"/shelf(/[A-Za-z0-9_.\-/%]*)?")
_ID = re.compile(r"[A-Za-z0-9_.\-]{1,80}")
MAP_DONE = ("node", "link", "rename", "color", "connect", "disconnect", "node_trash", "project", "contexts", "ctx_saved")  # 지도 바꾸기 뒤 한 줄의 종류


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
    _rows: Callable[..., list[Any]]
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
            ("/shelf/floor/{floor}", ["GET"], self.floor_redirect),
            ("/shelf/move", ["POST"], self.shelf_move),
            ("/shelf/undo", ["POST"], self.shelf_undo),
        ]

    def _map_page(self, title: str, body: str, session: tuple[str, str], status: int = 200, css: str = "") -> Response:
        from magus.webbooks import BOOK_STYLE  # noqa: PLC0415  (올리기 진행 막대)
        from magus.webshelf import SHELF_STYLE  # noqa: PLC0415

        return self._page(title, body, session, status, current="프로젝트", css=SHELF_STYLE + BOOK_STYLE + CONTEXT_STYLE + css)

    def _break_out(self, request: Request) -> Response:
        """패널(iframe) 안에서 프로젝트 화면 주소가 열리면(저장·휴지통 뒤 넘어오기) 바깥 화면을 그 주소로 바꾼다."""
        url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return HTMLResponse(f'<!doctype html><meta charset="utf-8"><a id="go" href="{html.escape(url)}" target="_top">지도로 가기</a>'
                            '<script>window.top.location.replace(document.getElementById("go").href)</script>')

    # ---- 프로젝트 목록 ------------------------------------------------------------------------
    def locate(self, uid: str, at: str) -> tuple[str | None, str | None]:
        """게시판 자리의 주소(책 화면) → (프로젝트, 책). 책 추가·새 책처럼 책이 없는 화면은 (프로젝트, None)."""
        path, _, query = at.partition("?")
        parts = [urllib.parse.unquote(x) for x in path.split("/")[2:] if x]
        if not parts:
            return None, None
        head = parts[0]
        if head in ("add", "new"):
            params = dict(urllib.parse.parse_qsl(query))
            return params.get("project") or params.get("floor"), None
        if head == "book" and len(parts) > 1:
            key = f"ms.{parts[1]}"
        elif head == "doc" and len(parts) > 1:
            key = f"doc.{parts[1]}"
        elif head in ("edit", "trash") and len(parts) > 1:
            key = parts[1]
        else:
            key = head
        try:
            return self.store.book_floor(uid, key), key
        except ValueError:
            return None, None

    async def project_list(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        if EMBED.get():
            return self._break_out(request)
        uid = session[0]
        params = request.query_params
        # 옛 주소(층·한 화면 책장: ?floor=·?at=·?zoom=)는 그 프로젝트 화면으로
        at = safe_at(params.get("at")) or safe_at(params.get("next"))
        floor = params.get("floor") or params.get("zoom")
        if at or floor:
            book = params.get("book")
            if at and not floor:
                floor, found_book = await run_in_threadpool(self.locate, uid, at)
                book = book or found_book
            if floor and await run_in_threadpool(self.store.get_floor, uid, floor):
                keep = {k: v for k, v in params.items() if k in ("done", "c", "full", "moved", "undone", "moveerr", "b", "t")}
                return RedirectResponse(state_url(floor, book, at, **keep), status_code=303)
        q = clean_query(params.get("q"))
        floors = await run_in_threadpool(self.store.list_floors, uid)
        form = (f'<form method="get" action="/shelf" class="search" role="search">'
                f'<input type="search" name="q" value="{html.escape(q)}" aria-label="모든 프로젝트에서 찾기"><button>찾기</button></form>')
        if q:
            groups = await run_in_threadpool(self._search_all, uid, floors, q)
            hits = [g for g in groups if g]
            head = (f'<p class="crumb"><a href="/shelf">← 프로젝트</a></p>{form}'
                    f"<p>「{html.escape(q)}」 " + (f"{len(hits)}" if hits else "없음") + "</p>")
            return self._map_page("프로젝트", head + "".join(hits), session, css=PROJECTS_STYLE)
        notices = await run_in_threadpool(self._notices, uid, request, session, "/shelf")
        cards = await run_in_threadpool(self._project_cards, uid, floors, session)
        from magus.webbooks import UPLOAD_PROGRESS  # noqa: PLC0415

        body = (f"{notices}{form}<ul class=\"projects\">{cards}</ul>{UPLOAD_PROGRESS}"
                '<p class="muted"><a href="/shelf/export.zip">전체 내려받기(zip)</a></p>')
        return self._map_page("프로젝트", body, session, css=PROJECTS_STYLE)

    def _project_cards(self, uid: str, floors: list[Floor], session: tuple[str, str]) -> str:
        from magus.webbooks import IMPORTING, progress_box  # noqa: PLC0415

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
        new = (
            '<li class="pcard new"><h2>+ 프로젝트</h2>'
            f'<form method="post" action="/shelf/manuscript" enctype="multipart/form-data" data-progress="{IMPORTING}">{csrf}'
            '<input type="hidden" name="project" value="new">'
            '<input type="file" name="file" accept=".docx,.pdf" required aria-label="문서 파일(docx·pdf)">'
            f'<p><button class="primary">올리기</button></p>{progress_box()}</form>'
            f'<form method="post" action="/shelf/projects">{csrf}'
            f'<label class="block">제목 <input name="title" maxlength="{PROJECT_TITLE_MAX}" required></label>'
            '<p><button>만들기</button></p></form></li>'
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
        title = one_line(str(form.get("title") or ""))[:PROJECT_TITLE_MAX]
        if not title:
            return RedirectResponse("/shelf?projecterr=empty", status_code=303)
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
            out += f'<p class="msg">{html.escape(text, quote=False)}</p>'
        if err := {"empty": "제목을 적어 주세요.", "full": f"프로젝트는 {MAX_FLOORS}개까지입니다."}.get(
                params.get("projecterr") or ""):
            out += f'<p class="msg err">{err}</p>'
        if code := params.get("maperr"):
            out += f'<p class="msg err">{html.escape(error_message(MapError(code, code, name=params.get("name") or ""), polite=True))}</p>'
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
    def _view(self, uid: str, found: ProjectMap, params: Any) -> tuple[MapNode | None, Book | None, str | None, str | None]:
        """주소 → (열린 노드, 열린 책, 게시판 자리에 열 주소, 그 주소가 책 첫 화면과 다르면 at). 맞지 않는 값은 버린다."""
        at = safe_at(params.get("at"))
        node = found.node(params.get("node") or "")
        book_key = params.get("book") or None
        if at and not book_key:
            _, book_key = self.locate(uid, at)
        if book_key and node is None:
            node = found.node_of(book_key)
        if node is None and at and not book_key:  # 책 추가·새 책 화면: 주소의 노드
            query = dict(urllib.parse.parse_qsl(at.partition("?")[2]))
            node = found.node(query.get("node") or "") or (found.nodes[0] if query.get("project") == found.floor else None)
        book = None
        if node is not None and book_key and book_key in node.books:
            book = next(iter(self.book_objects(uid, [book_key])), None)
        if book is not None and at == book.href:
            at = None
        if book is None and not (at and (at.startswith("/shelf/add") or at.startswith("/shelf/new"))):
            at = None
        return node, book, at or (book.href if book else None), at

    async def project_page(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        if EMBED.get():
            return self._break_out(request)
        uid = session[0]
        floor_id = request.path_params["project"]
        found = await run_in_threadpool(self.store.get_map, uid, floor_id)
        floor = await run_in_threadpool(self.store.get_floor, uid, floor_id)
        if found is None or floor is None:
            return self._map_page("프로젝트", '<p class="msg err">없는 프로젝트입니다. <a href="/shelf">프로젝트 목록</a>으로 돌아가세요.</p>',
                                  session, 404)
        params = request.query_params
        node, book, src, at = await run_in_threadpool(self._view, uid, found, params)
        here = state_url(floor_id, book.key if book else None, at, node.id if node else None)
        notices = await run_in_threadpool(self._notices, uid, request, session, here, found)
        q = clean_query(params.get("q"))
        view = params.get("view") if params.get("view") in ("map", "list") else "auto"
        search = ""
        if q:
            result = await run_in_threadpool(self._search_project, uid, floor, found, q)
            search = (f'<section class="pm-results" aria-label="찾은 것"><p>「{html.escape(q)}」 '
                      + ("" if result else "없음 · ")
                      + f'<a href="{html.escape(state_url(floor_id))}">지우기</a></p>{result}</section>')
        bar = self._toolbar(floor, found, q, view)
        new_node = await run_in_threadpool(self._new_node_form, uid, session, floor, found)
        map_html = await run_in_threadpool(self._map_html, uid, found, node)
        list_html = await run_in_threadpool(self._list_html, uid, floor, found, node, book)
        panel = await run_in_threadpool(self._panel_html, uid, session, floor, found, node)
        book_title = book.name if book else ("책 추가" if src else "")
        board = (f'<section class="pp-book" id="book-panel" aria-labelledby="bp-title"{"" if src else " hidden"}>'
                 f'<div class="bp-head"><h2 class="bp-title" id="bp-title" tabindex="-1">{html.escape(book_title)}</h2>'
                 f'<a class="bp-close" href="{html.escape(state_url(floor_id, node=node.id if node else None))}">닫기</a></div>'
                 f'<iframe class="bp-frame" title="{html.escape(book_title or "책")}" src="{html.escape(src or "about:blank")}"></iframe></section>')
        data = {"project": floor_id, "csrf": self.csrf(session[1]), "post": f"/shelf/p/{urllib.parse.quote(floor_id)}/map",
                "panel": f"/shelf/p/{urllib.parse.quote(floor_id)}/panel", "page": f"/shelf/p/{urllib.parse.quote(floor_id)}",
                "nodes": [{"id": n.id, "x": n.x, "y": n.y} for n in found.nodes], "edges": [list(e) for e in found.edges]}
        state = "".join(f' data-{k}="{html.escape(v)}"' for k, v in (("node", node.id if node else ""), ("book", book.key if book else ""),
                                                                        ("at", at or "")) if v)
        head = (f'<div class="pm-head"><h1 class="pm-title">{html.escape(project_name(floor))}</h1>{new_node}'
                f'<p class="pm-meta">노드 {len(found.nodes)} · 선 {len(found.edges)} · {when_text(floor.updated_at)}</p></div>')
        body = (f'{notices}<p class="crumb"><a href="/shelf">← 프로젝트</a></p><div class="pm" data-view="{view}">{head}{bar}{search}'
                f'<div class="pm-body"{state}><div class="pm-main">{map_html}{list_html}</div>'
                f'<aside class="pm-panel" id="panel" aria-label="노드의 책장">{panel}{board}</aside></div></div>'
                f'<script type="application/json" id="map-data">{json_script(data)}</script>'
                + self._move_form(session, here) + MAP_SCRIPT)
        return self._map_page(project_name(floor), body, session, css=MAP_STYLE)

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
            f'<a class="btn" href="/shelf/p/{urllib.parse.quote(floor.id)}/export.zip">내려받기</a></div></div>'
        )

    def _new_node_form(self, uid: str, session: tuple[str, str], floor: Floor, found: ProjectMap) -> str:
        """'+ 노드': 새 노드(이름) 또는 다른 프로젝트의 노드를 연결. 지도의 빈 곳을 두 번 누르면 그 자리로 열린다."""
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
        chips = "".join(
            f'<label class="chip-toggle"><input type="checkbox" name="ctx_pick" value="{html.escape(c.id)}">{html.escape(c.name)}</label>'
            for c in saved)
        contexts = (
            '<fieldset class="ctx ctx-mini"><legend>컨텍스트</legend>'
            + (f'<div class="chips" role="group" aria-label="자주 쓰는 컨텍스트">{chips}</div>' if chips else "")
            + '<details><summary>직접 적기</summary><label class="block">내용 <textarea name="ctx_new" maxlength="500" rows="2">'
            "</textarea></label></details></fieldset>"
        )
        return (
            '<details class="pm-new" id="new-node"><summary class="btn primary-ish">+ 노드</summary><div class="pm-new-in">'
            f'<form method="post" action="{post}" class="pm-form">{csrf}<input type="hidden" name="action" value="add_node">'
            '<input type="hidden" name="x"><input type="hidden" name="y">'
            f'<label class="block">이름 <input name="name" maxlength="{NODE_NAME_MAX}" required></label>'
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

    def _list_html(self, uid: str, floor: Floor, found: ProjectMap, node: MapNode | None, book: Book | None) -> str:
        """목록 보기(휴대폰의 첫 모습, 키보드·낭독기): 노드 → 책 → 게시판."""
        items = []
        for n in found.nodes:
            books = self.book_objects(uid, n.books)
            here = book.key if book is not None and node is not None and node.id == n.id else None
            links = "".join(
                f'<li><a href="{html.escape(state_url(floor.id, b.key, node=n.id))}#book-panel"'
                + (' aria-current="true"' if b.key == here else "") + ">"
                f'{html.escape(b.name)}</a> <small>{html.escape(b.band + " · " if b.band else "")}{html.escape(_count_text(b))}</small></li>'  # 컨텍스트 · 수(#96)
                for b in books)
            sub = node_sub(n, books)
            title = ("가운데 · " + found.title) if n.center else node_label(n)
            items.append(f'<li><details{" open" if node is not None and node.id == n.id else ""}><summary><b>{html.escape(title)}</b> '
                         f'<small>{html.escape(sub)}</small></summary>'
                         + (f'<ul class="nl-books">{links}</ul>' if links else '<p class="muted">책 없음</p>')
                         + f'<p><a href="{html.escape(state_url(floor.id, node=n.id))}#panel">열기</a></p></details></li>')
        edges = {n.id: node_label(n) for n in found.nodes}
        pairs = [(b, a) if b == CENTER else (a, b) for a, b in found.edges]  # 가운데를 앞에
        lines = " · ".join(f"{html.escape(edges[a])}–{html.escape(edges[b])}" for a, b in pairs if a in edges and b in edges)
        return (f'<section class="map-list" aria-label="노드 목록"><h2 class="sr-title">노드 목록</h2><ul class="nlist">{"".join(items)}</ul>'
                f'<p class="muted">선: {lines or "없음"}</p></section>')

    # ---- 패널(노드의 책장) ----------------------------------------------------------------------
    def _panel_html(self, uid: str, session: tuple[str, str], floor: Floor, found: ProjectMap, node: MapNode | None) -> str:
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
        settings = self._node_settings(uid, session, floor, found, node)
        context = "" if node.missing else contexts_view_html(View(node.contexts, node=node.name))  # 노드의 컨텍스트(#96)
        return (f'<div class="pp-node" id="pp-node" data-node="{html.escape(node.id)}">'
                f'<div class="pp-head"><h2 class="pp-title" id="pp-title" tabindex="-1">{html.escape(title)}</h2>'
                f'<span class="pp-kind">{kind} · 책 {len(books)}권</span></div>{context}{intro}{shelf}{hint}{settings}</div>')

    def _node_settings(self, uid: str, session: tuple[str, str], floor: Floor, found: ProjectMap, node: MapNode) -> str:
        """노드 설정(스크립트 없이도): 이름·색·선 잇기·끊기·휴지통."""
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
                  f'<label>이름 <input name="name" value="{html.escape(node.name)}" maxlength="{NODE_NAME_MAX}" required></label> '
                  '<button>바꾸기</button></form>')
        swatches = "".join(f'<option value="{value}"{" selected" if node.color == value else ""}>{html.escape(name)}</option>'
                           for name, value in PALETTE)
        color = (f'<form method="post" action="{post}" class="pm-form">{hidden}<input type="hidden" name="action" value="color">'
                 f'<label>노드 색 <select name="color"><option value=""{"" if node.color else " selected"}>기본(흰색)</option>{swatches}</select></label> '
                 '<button>바꾸기</button></form>')
        # 가운데 노드·책이 꽂힌 노드는 휴지통으로 옮기지 않는다(그때는 휴지통 칸을 보이지 않는다. 까닭은 도움말)
        trash = ("" if node.center or (node.books and not node.link) else
                 f'<form method="post" action="{post}" class="pm-form">{hidden}<input type="hidden" name="action" value="trash">'
                 '<p><button>휴지통으로 옮기기</button></p></form>')
        contexts = ""
        if not node.link:  # 연결 노드의 컨텍스트는 원본 지도에서 바꾼다
            saved = self.store.list_saved_contexts(uid)
            contexts = (f'<h3>컨텍스트</h3><form method="post" action="{post}" class="pm-form">{hidden}'
                        '<input type="hidden" name="action" value="contexts">'
                        + context_fieldset(saved, node.contexts) + '<p><button>저장</button></p></form>')
        return (f'<details class="pp-set"><summary>⚙ 설정</summary>{rename}{color}{contexts}'
                f'<h3>선</h3><ul class="pp-lines">{lines or "<li>없음</li>"}</ul>{connect}'
                + (f"<h3>휴지통</h3>{trash}" if trash else "") + f"</details>{CONTEXT_SCRIPT}")

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
            elif action == "trash":
                _, lost = await run_in_threadpool(trash_node, self.store, uid, floor_id, node, "웹 지도에서 옮김")
                result["lost"] = lost
                done, back = "node_trash", state_url(floor_id, lost=",".join(lost))
            else:
                raise MapError("unknown_action", "모르는 동작")
        except (MapError, MoveError) as e:
            text = error_message(e, polite=True)
            if wants_json:
                return JSONResponse({"ok": False, "error": text}, status_code=400)
            return RedirectResponse(with_query(back, maperr=e.code, name=str(e.info.get("name") or "")), status_code=303)
        except ValueError as e:  # 색 이름·컨텍스트 길이 등
            if wants_json:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
            return RedirectResponse(with_query(back, maperr="bad_context" if action in ("add_node", "contexts") else "bad_color"),
                                    status_code=303)
        if wants_json:
            return JSONResponse(result)
        target = result.get("node") or node
        return RedirectResponse(with_query(back, done=done, n=target) if done else back, status_code=303)

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
        needle = q.replace(" ", "").lower()
        parts = []
        named = [n for n in found.nodes if needle and needle in n.name.replace(" ", "").lower()]
        if named:
            parts.append("<p>노드: " + " · ".join(
                f'<a href="{html.escape(state_url(floor.id, node=n.id))}">{html.escape(node_label(n) if not n.center else n.name)}</a>'
                for n in named) + "</p>")
        doc_hits = set(find(self.store, uid, ["document"], q))
        seen: set[str] = set()
        for n in found.nodes:
            for b in self.book_objects(uid, n.books):
                if b.key in seen:
                    continue
                seen.add(b.key)
                in_name = needle and needle in b.name.replace(" ", "").lower()
                kind = self._kind_of(uid, b.key)
                rows = self._rows(uid, kind, None, q) if kind is not None else []
                if b.key.startswith("doc.") and b.key[4:] in doc_hits:
                    rows = rows or []
                    in_name = True
                if not rows and not in_name:
                    continue
                where = "" if n.name == b.name else f'{html.escape(node_label(n) if not n.center else "가운데")} · '
                more = (f' <small><a href="{html.escape(state_url(floor.id, b.key, f"/shelf/{b.key}?q={urllib.parse.quote(q)}", n.id))}">'
                        "모두 보기</a></small>" if len(rows) > GROUP_SIZE else "")
                items = "".join(_retarget(row_html(r, q), floor.id, b.key, n.id) for r in rows[:GROUP_SIZE])
                band = f"{html.escape(b.band)} · " if b.band else ""
                parts.append(f'<section class="group"><h3>{where}<a href="{html.escape(state_url(floor.id, b.key, node=n.id))}">'
                             f'{html.escape(b.name)}</a> <small>{band}{len(rows)}개</small>{more}</h3>'
                             + (f'<ol class="board">{items}</ol>' if items else "") + "</section>")
        return "".join(parts)

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
        needle = q.replace(" ", "").lower()
        out = []
        for f in floors:
            found = self.store.get_map(uid, f.id)
            if found is None:
                out.append("")
                continue
            own = ProjectMap(found.floor, found.title, tuple(n for n in found.nodes if not n.link), found.edges, found.stored)
            inner = self._search_project(uid, f, own, q)
            named = needle in project_name(f).replace(" ", "").lower()
            if not inner and not named:
                out.append("")
                continue
            out.append(f'<section class="fgroup"><h2><a href="{html.escape(state_url(f.id))}">{html.escape(project_name(f))}</a> '
                       f'<small>{when_text(f.updated_at)}</small></h2>'
                       + inner + "</section>")
        return out

    # ---- 내려받기 ----------------------------------------------------------------------------
    async def export_project(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        floor = await run_in_threadpool(self.store.get_floor, uid, request.path_params["project"])
        if floor is None:
            return self._map_page("프로젝트", '<p class="msg err">없는 프로젝트입니다.</p>', session, 404)
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


def _retarget(row: str, floor: str, key: str, node: str) -> str:
    """검색 결과 줄의 '이 항목의 주소'를 프로젝트 화면(그 노드·책, 게시판 자리에 그 항목)으로."""
    def swap(m: re.Match[str]) -> str:
        at = html.unescape(m.group(1))
        return f'href="{html.escape(state_url(floor, key, at, node))}"'

    return re.sub(r'href="(/shelf/[^"]+)"', swap, row, count=1)


def _zip_response(data: bytes, name: str) -> Response:
    quoted = urllib.parse.quote(name)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=\"magus.zip\"; filename*=UTF-8''{quoted}"})
