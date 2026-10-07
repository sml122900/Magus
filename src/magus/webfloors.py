"""웹 책장 전체(3D)·한 층 화면·옮기기·되돌리기·층 만들기(사용자 결정 #93, 2026-10-07). Web에 섞어 쓰는 FloorPages.

- 책장 전체(/shelf): 정면·오른쪽 옆면·윗면이 보이는 비스듬한 장(CSS 3D: perspective·rotateX/Y·preserve-3d).
  맨 위가 공용 층, 그 아래로 작업물 층. 층 앞 선반 가장자리에 층 이름·작업물 제목·최근 수정, 층 안에는 카테고리 책이 작게 꽂힌다.
  층을 누르거나(키보드는 선반 가장자리 링크) 고르면 그 층으로 다가가며 회전이 풀리고(0.65초) 한 층 화면으로 넘어간다.
  움직임 줄이기(prefers-reduced-motion)면 바로 넘어간다. 주소가 바뀌므로 뒤로 가기로 돌아온다.
- 한 층 화면(/shelf/floor/<층 id>): 지금의 책장(책등이 큰 화면)에 위쪽 층 이름 띠(공용·1층·2층…)와 '전체 책장' 버튼.
- 옮기기: 책을 다른 층으로 끌어 놓는다(전체 보기: 층 위에, 한 층 화면: 위쪽 층 이름 띠 위에). 마우스는 6px 움직이면,
  손가락은 길게 눌러(0.35초) 들어 올린다. 키보드 사용자는 책 설정의 '위치'로 옮긴다. 놓으면 POST /shelf/move(CSRF).
  옮긴 뒤 "○○를 공용으로 옮겼습니다. [되돌리기]"(마지막 옮기기만, POST /shelf/undo).
- 검색: 층 이름(작업물 제목)·카테고리 이름·항목 내용을 한 번에, 층 → 카테고리 순으로 묶고 최근 수정을 붙인다.
  결과를 누르면 책장 전체에서 그 층으로 다가간 뒤 그 자리로 간다(/shelf?zoom=<층>&next=<주소>, 뒤로 가기에 남지 않게 replace).
- 외부 라이브러리·이미지·글꼴 없음(#56). 색은 책장 전용 색(web-style.md "책장 전용")만 쓴다.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from magus.category.moves import error_message, move_book, undo_move, web_message
from magus.floors import MAX_FLOORS
from magus.ids import local_time
from magus.store import Floor, Store
from magus.store.floors import KINDS as BUILTIN_KINDS
from magus.store.floors import MoveError
from magus.store.formats import one_line
from magus.webshelf import (
    GROUP_SIZE, KINDS, Book, Kind, add_book, book_html, builtin_kind, category_kind, clean_query, find, one_char, row_html,
    safe_color, shelf_html, text_color,
)

FLOOR_TITLE_MAX = 120
WHEN = "%m-%d %H:%M"
_NEXT = re.compile(r"/shelf(/[A-Za-z0-9_.\-/]*)?")

FLOOR_STYLE = """
.bc-wrap{overflow-x:clip;margin:8px -16px 8px;padding:0 16px}
.bc-scene{perspective:5200px;perspective-origin:60% 45%;padding:30px 48px 24px 8px;max-width:1040px}
.bc{--depth:120px;position:relative;transform-style:preserve-3d;transform-origin:100% 0;
transform:translate3d(0,0,0) scale(1) rotateY(-18deg) rotateX(-6deg);transition:transform .65s cubic-bezier(.25,.75,.25,1)}
.bc-front{position:relative;background:var(--wood);background-image:repeating-linear-gradient(90deg,rgb(0 0 0/.05) 0 2px,transparent 2px 9px);
border-radius:4px;padding:12px 12px 2px;box-shadow:inset 0 0 0 2px var(--wood2)}
.bc-side{position:absolute;top:0;left:100%;width:var(--depth);height:100%;transform-origin:0 50%;transform:rotateY(90deg);
background:linear-gradient(90deg,#6a4122,#55331a);border-radius:0 4px 4px 0;transition:opacity .4s}
.bc-top{position:absolute;left:0;bottom:100%;width:100%;height:var(--depth);transform-origin:50% 100%;transform:rotateX(90deg);
background:linear-gradient(#b38559,#986741);border-radius:4px 4px 0 0;transition:opacity .4s}
.bc,.bc-front,.bc-side,.bc-top{--wood:#8a5a32;--wood2:#6f4524;--back:#f2ebdd;--board:#e7dcc3;--board-edge:#cbbb98}
.fl{position:relative;margin:0 0 12px;background:var(--back);border-radius:2px;cursor:pointer;transition:filter .15s ease,opacity .4s}
.fl:hover,.fl:focus-within{filter:brightness(1.1) saturate(1.08);box-shadow:0 0 0 3px rgb(255 255 255/.75)}
.site{position:relative;z-index:5}
.fl .mini{list-style:none;margin:0;padding:16px 14px 0;display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px 3px;min-height:132px;
box-shadow:inset 0 10px 14px -10px rgb(0 0 0/.35)}
.fl .mini>li{display:flex}
.mini-empty{align-self:center;color:var(--ink2);font-size:16px;padding:0 4px 40px}
.mbook{display:flex;align-items:center;justify-content:center;border-radius:3px 3px 1px 1px;background-color:var(--c);color:var(--fg);
background-image:linear-gradient(90deg,rgb(0 0 0/.3),rgb(0 0 0/0) 18%,rgb(0 0 0/0) 82%,rgb(0 0 0/.28));
box-shadow:inset 0 1px 0 rgb(255 255 255/.25),1px 0 2px rgb(0 0 0/.25);cursor:grab;touch-action:pan-y;
user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
.mb-name{writing-mode:vertical-rl;font-size:15px;font-weight:600;line-height:1.1;letter-spacing:.04em;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis;max-height:calc(100% - 14px)}
.fl-ledge{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 14px;padding:7px 14px 9px;color:#1a1a1a;text-decoration:none;
background:linear-gradient(var(--board) 0 72%,var(--board-edge));border-top:1px solid #fbf7ee;box-shadow:0 3px 4px rgb(0 0 0/.25)}
.fl-ledge:hover{color:#1a1a1a}.fl-ledge:focus-visible{outline:3px solid var(--primary);outline-offset:2px}
.fl-name{font-weight:600;font-size:19px}
.fl-title{font-size:17px;font-weight:600;flex:1 1 10em;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fl-when{font-size:15px;color:#3d3326;margin-left:auto;white-space:nowrap;font-variant-numeric:tabular-nums}
.fl.drop-on{outline:4px solid var(--primary);outline-offset:-2px;filter:brightness(1.1)}
.bc.zoom .fl:not(.zoom-target),.bc.zoom .bc-side,.bc.zoom .bc-top{opacity:0}
.bc.zoom .zoom-target{filter:none}
.dragging{opacity:.35}
.drag-ghost{position:fixed;left:0;top:0;z-index:50;pointer-events:none;margin:0;opacity:.95;
box-shadow:0 14px 24px rgb(0 0 0/.35);rotate:-4deg}
body.is-dragging{cursor:grabbing;user-select:none;-webkit-user-select:none}
.floor-head{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin:0 0 8px}
a.all-shelf{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:8px 16px;border:1px solid var(--mute);border-radius:8px;
background:var(--canvas);color:var(--ink);text-decoration:none;font-weight:600}
a.all-shelf:hover{border-color:var(--primary);color:var(--primary)}
.fband{display:flex;flex-wrap:wrap;gap:8px;margin:0}
.fband a{display:inline-flex;align-items:center;min-height:44px;padding:8px 14px;border:1px solid var(--line);border-radius:8px;
background:var(--canvas);color:var(--ink2);text-decoration:none;font-weight:600}
.fband a[aria-current=page]{border-color:var(--primary);color:var(--primary);box-shadow:inset 0 -3px 0 var(--primary)}
.fband a.drop-on{background:var(--primary);border-color:var(--primary);color:#fff}
.floor-meta{color:var(--ink2);margin:4px 0 8px}
form.inline{display:inline}
.msg .undo{margin-left:12px}
.fgroup{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:4px 16px 8px;margin:16px 0;box-shadow:var(--shadow)}
.fgroup>h2{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}.fgroup>h2 small,.fgroup h3 small{font-weight:400;font-size:15px}
.fgroup h3{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;margin:16px 0 8px}
@media (max-width:767px){
.bc-scene{perspective:3200px;perspective-origin:60% 45%;padding:22px 26px 20px 0}
.bc{--depth:52px;transform:translate3d(0,0,0) scale(1) rotateY(-11deg) rotateX(-5deg)}
.fl .mini{padding:12px 8px 0;min-height:104px;gap:8px 2px}.fl-ledge{padding:6px 10px 8px}
.fl-name{font-size:18px}.fl-title{font-size:16px;flex-basis:100%}.fl-when{margin-left:0}}
@media (prefers-reduced-motion:reduce){.bc,.fl,.bc-side,.bc-top{transition:none}}
"""

# 끌어 옮기기(마우스·펜: pointer, 손가락: 길게 누르기) + 층으로 다가가기. 서버는 이것과 상관없이 POST를 다시 검사한다.
FLOOR_SCRIPT = """<script>
(function () {
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var form = document.getElementById("move-form"), drag = null, suppress = false;
  function targetAt(x, y) { var el = document.elementFromPoint(x, y); return el && el.closest ? el.closest("[data-drop-floor]") : null; }
  function start(book, x, y) {
    var r = book.getBoundingClientRect(), ghost = book.cloneNode(true);
    ghost.classList.add("drag-ghost"); ghost.removeAttribute("href"); ghost.setAttribute("aria-hidden", "true");
    ghost.style.width = r.width + "px"; ghost.style.height = r.height + "px";
    document.body.appendChild(ghost);
    drag = { book: book, ghost: ghost, dx: x - r.left, dy: y - r.top, over: null };
    book.classList.add("dragging"); document.body.classList.add("is-dragging"); move(x, y);
  }
  function move(x, y) {
    drag.ghost.style.transform = "translate(" + (x - drag.dx) + "px," + (y - drag.dy) + "px)";
    var t = targetAt(x, y);
    if (t && t.getAttribute("data-drop-floor") === drag.book.getAttribute("data-from")) t = null;
    if (t !== drag.over) { if (drag.over) drag.over.classList.remove("drop-on"); drag.over = t; if (t) t.classList.add("drop-on"); }
    if (y < 56) window.scrollBy(0, -14); else if (y > window.innerHeight - 56) window.scrollBy(0, 14);
  }
  function finish(x, y, drop) {
    var d = drag; drag = null; if (!d) return;
    d.ghost.remove(); d.book.classList.remove("dragging"); document.body.classList.remove("is-dragging");
    if (d.over) d.over.classList.remove("drop-on");
    var t = drop ? targetAt(x, y) : null;
    if (t && form && t.getAttribute("data-drop-floor") !== d.book.getAttribute("data-from")) {
      form.elements.book.value = d.book.getAttribute("data-book");
      form.elements.to.value = t.getAttribute("data-drop-floor");
      form.submit();
    }
  }
  if (form) {
    document.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "touch" || e.button !== 0) return;
      var book = e.target.closest && e.target.closest("[data-book]"); if (!book) return;
      var sx = e.clientX, sy = e.clientY, started = false;
      function mv(ev) {
        if (!started && Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 6) { started = true; start(book, ev.clientX, ev.clientY); }
        if (started) move(ev.clientX, ev.clientY);
      }
      function up(ev) {
        document.removeEventListener("pointermove", mv); document.removeEventListener("pointerup", up);
        if (started) { suppress = true; finish(ev.clientX, ev.clientY, true); }
      }
      document.addEventListener("pointermove", mv); document.addEventListener("pointerup", up);
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && drag) finish(0, 0, false); });
    document.addEventListener("dragstart", function (e) { if (e.target.closest && e.target.closest("[data-book]")) e.preventDefault(); });
    document.addEventListener("contextmenu", function (e) { if (drag || (e.target.closest && e.target.closest(".mbook"))) e.preventDefault(); });
    document.addEventListener("touchstart", function (e) {
      var book = e.target.closest && e.target.closest("[data-book]"); if (!book || e.touches.length > 1) return;
      var t0 = e.touches[0], sx = t0.clientX, sy = t0.clientY, lx = sx, ly = sy, started = false;
      var timer = setTimeout(function () { started = true; start(book, lx, ly); if (navigator.vibrate) navigator.vibrate(12); }, 350);
      function stop() { clearTimeout(timer); document.removeEventListener("touchmove", mv); document.removeEventListener("touchend", end);
        document.removeEventListener("touchcancel", cancel); }
      function mv(ev) { var t = ev.touches[0]; lx = t.clientX; ly = t.clientY;
        if (!started) { if (Math.abs(lx - sx) + Math.abs(ly - sy) > 10) stop(); return; }
        ev.preventDefault(); move(lx, ly); }
      function end(ev) { var was = started; stop(); if (was) { ev.preventDefault(); suppress = true; finish(lx, ly, true); } }
      function cancel() { var was = started; stop(); if (was) finish(0, 0, false); }
      document.addEventListener("touchmove", mv, { passive: false });
      document.addEventListener("touchend", end); document.addEventListener("touchcancel", cancel);
    }, { passive: true });
  }
  document.addEventListener("click", function (e) { if (suppress) { suppress = false; e.preventDefault(); e.stopPropagation(); } }, true);

  // 층으로 다가가기: 그 층이 화면 왼쪽 위로 오며 커지고 회전이 풀린다. 그다음 한 층 화면(또는 검색 결과의 자리)으로 간다.
  var bc = document.querySelector(".bc");
  function zoom(floorId, href, replace) {
    var fl = bc && bc.querySelector('.fl[data-floor="' + floorId + '"]');
    var go = function () { if (!href) return; if (replace) location.replace(href); else location.assign(href); };
    if (!fl || reduce) { go(); return; }
    // 회전이 풀린 뒤의 평면 배치로 계산한다: 원점(오른쪽 위) 기준으로 커진 층의 왼쪽 위가 본문 왼쪽·화면 위(64px)에 오게
    var scene = bc.parentElement, s = scene.getBoundingClientRect(), cs = getComputedStyle(scene), mini = fl.querySelector(".mbook");
    var scale = Math.max(1.6, Math.min(3, 270 / (mini ? mini.offsetHeight : 120)));
    var by = s.top + parseFloat(cs.paddingTop), w = bc.offsetWidth;
    var tx = (scale - 1) * w - scale * fl.offsetLeft, ty = 64 - by - scale * fl.offsetTop;
    fl.classList.add("zoom-target"); bc.classList.add("zoom");
    bc.style.transform = "translate3d(" + tx + "px," + ty + "px,0) scale(" + scale + ") rotateY(0deg) rotateX(0deg)";
    setTimeout(go, 650);
  }
  window.MagusShelf = { zoom: zoom };
  window.addEventListener("pageshow", function (e) {  // 뒤로 가기로 돌아오면(bfcache) 원래 모습으로
    if (!bc) return; bc.classList.remove("zoom"); bc.style.transform = "";
    var t = bc.querySelector(".zoom-target"); if (t) t.classList.remove("zoom-target");
  });
  if (bc) {
    bc.addEventListener("click", function (e) {
      var fl = e.target.closest(".fl"); if (!fl || e.defaultPrevented) return;
      var link = fl.querySelector(".fl-ledge"); e.preventDefault(); zoom(fl.getAttribute("data-floor"), link.getAttribute("href"));
    });
    var auto = document.querySelector("[data-zoom-floor]");
    if (auto && auto.getAttribute("data-zoom-next")) {
      requestAnimationFrame(function () { zoom(auto.getAttribute("data-zoom-floor"), auto.getAttribute("data-zoom-next"), true); });
    }
  }
  // 검색 결과: 누르면 책장 전체에서 그 층으로 다가간 뒤 그 자리로(뒤로 가기에는 검색 결과가 남는다)
  document.querySelectorAll("[data-result-floor]").forEach(function (box) {
    box.addEventListener("click", function (e) {
      var a = e.target.closest("a[href^='/shelf/']"); if (!a || reduce) return;
      e.preventDefault();
      location.assign("/shelf?zoom=" + encodeURIComponent(box.getAttribute("data-result-floor")) + "&next=" + encodeURIComponent(a.getAttribute("href")));
    });
  });
})();
</script>"""


def safe_next(value: str, fallback: str = "/shelf") -> str:
    """돌아갈 주소: 책장 안의 주소만(바깥 주소·//로 시작하는 주소는 받지 않는다)."""
    return value if _NEXT.fullmatch(value or "") and "//" not in value else fallback


def with_query(path: str, **params: str) -> str:
    base, _, query = path.partition("?")
    pairs = [(k, v) for k, v in urllib.parse.parse_qsl(query) if k not in params and k not in ("moved", "undone", "moveerr", "b", "t")]
    return base + "?" + urllib.parse.urlencode([*pairs, *params.items()])


def when_text(iso: str) -> str:
    return f"최근 수정 {local_time(iso, WHEN)}" if iso else "최근 수정 없음"


def floor_name(floor: Floor) -> str:
    return floor.label if floor.common else f"{floor.label} · {floor.title}"


def mini_book_html(book: Book, floor: str) -> str:
    """책장 전체에 꽂히는 작은 책(지금 책등을 줄인 모습). 끌어 옮길 수 있다."""
    color = safe_color(book.color, "#3b4652")
    n = len(book.name)
    height = 104 + min(26, n * 2) + (int(book.key.encode().hex()[-2:], 16) % 9)
    width = 26 if book.count < 10 else 30 if book.count < 50 else 34 if book.count < 200 else 38
    label = (f"{book.name}, 확인 {book.verified}편, 전체 {book.count}편" if book.verified is not None
             else f"{book.name}, 항목 {book.count}개")
    drag = f' data-book="{html.escape(book.key)}" data-from="{html.escape(floor)}"' if book.movable else ""
    return (f'<li><span class="mbook"{drag} role="img" '
            f'aria-label="{html.escape(label)}" title="{html.escape(label)}" '
            f'style="--c:{color};--fg:{text_color(color)};height:{height}px;width:{width}px">'
            f'<span class="mb-name" aria-hidden="true">{html.escape(book.name)}</span></span></li>')


class FloorPages:
    """Web에 섞어 쓰는 층 화면들. ShelfPages의 books·_rows·_done_message·_shelf_page와 Web의 공통 도구를 쓴다."""

    store: Store
    _page: Callable[..., Response]
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]
    _csrf_input: Callable[[tuple[str, str]], str]
    _form: Callable[[Request, tuple[str, str]], Awaitable[Any]]
    _shelf_page: Callable[..., Response]
    books: Callable[[str, str], list[Book]]
    _rows: Callable[..., list[Any]]
    _done_message: Callable[[str, Request], str]

    def floor_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [
            ("/shelf", ["GET"], self.overview),
            ("/shelf/floor/{floor}", ["GET"], self.floor_page),
            ("/shelf/move", ["POST"], self.shelf_move),
            ("/shelf/undo", ["POST"], self.shelf_undo),
            ("/shelf/floors", ["POST"], self.floor_new),
        ]

    def _shelf_floor_page(self, title: str, body: str, session: tuple[str, str], status: int = 200) -> Response:
        from magus.webshelf import SHELF_STYLE

        return self._page(title, body, session, status, current="책장", css=SHELF_STYLE + FLOOR_STYLE)

    def _move_form(self, session: tuple[str, str], here: str) -> str:
        """끌어 놓으면 스크립트가 채워 보내는 폼(CSRF)."""
        return (f'<form id="move-form" method="post" action="/shelf/move" hidden>{self._csrf_input(session)}'
                f'<input type="hidden" name="book"><input type="hidden" name="to">'
                f'<input type="hidden" name="next" value="{html.escape(here)}"></form>')

    # ---- 안내 한 줄 ---------------------------------------------------------------------------
    def _notices(self, uid: str, request: Request, session: tuple[str, str], here: str) -> str:
        out = self._done_message(uid, request)
        params = request.query_params
        done = {"floor": "새 층을 만들었습니다. 원고는 아래 점선 자리 '책 추가'에서 원고 파일을 고르면 이 층의 원고 책이 됩니다."}.get(
            params.get("done") or "")
        if done:
            out += f'<p class="msg">{done}</p>'
        if err := {"empty": "작업물 제목을 적어 주세요.", "full": f"층은 공용 빼고 {MAX_FLOORS}개까지 만들 수 있습니다."}.get(
                params.get("floorerr") or ""):
            out += f'<p class="msg err">{err}</p>'
        if (moved := params.get("moved")) and (last := self.store.last_move(uid)) and last.id == moved:
            undo = (f'<form method="post" action="/shelf/undo" class="inline undo">{self._csrf_input(session)}'
                    f'<input type="hidden" name="move" value="{html.escape(last.id)}">'
                    f'<input type="hidden" name="next" value="{html.escape(here)}"><button>되돌리기</button></form>')
            out += f'<div class="msg">{html.escape(web_message(self.store, uid, last))}{undo}</div>'
        if (undone := params.get("undone")) and (last := self.store.last_undone(uid)) and last.id == undone:
            out += f'<p class="msg">{html.escape(web_message(self.store, uid, last, undone=True))}</p>'
        if code := params.get("moveerr"):
            info = {}
            if code in ("clash", "undo_clash"):
                info = {"name": self._book_name(uid, params.get("b") or ""), "floor": self._floor_label(uid, params.get("t") or "")}
            out += f'<p class="msg err">{html.escape(error_message(MoveError(code, code, **info), polite=True))}</p>'
        return out

    def _book_name(self, uid: str, key: str) -> str:
        base, _, _ = key.partition(".")
        if base in BUILTIN_KINDS:
            return KINDS[base].name
        try:
            found = self.store.get_category(uid, key)
        except ValueError:
            found = None
        return found.name if found else ""

    def _floor_label(self, uid: str, floor_id: str) -> str:
        found = self.store.get_floor(uid, floor_id) if floor_id else None
        return found.label if found else ""

    # ---- 책장 전체 ----------------------------------------------------------------------------
    def _case_html(self, uid: str, floors: list[Floor], zoom: tuple[str, str] | None) -> str:
        rows = []
        for f in floors:
            books = self.books(uid, f.id)
            minis = "".join(mini_book_html(b, f.id) for b in books) or '<li class="mini-empty">비어 있음</li>'
            title = "" if f.common else f'<span class="fl-title" title="{html.escape(f.title)}">{html.escape(f.title)}</span>'
            ledge_label = f"{floor_name(f)}, {when_text(f.updated_at)}, 책 {len(books)}권"
            rows.append(
                f'<section class="fl" data-floor="{html.escape(f.id)}" data-drop-floor="{html.escape(f.id)}">'
                f'<ul class="mini" aria-label="{html.escape(f.label)}에 꽂힌 카테고리">{minis}</ul>'
                f'<a class="fl-ledge" href="/shelf/floor/{html.escape(f.id)}" aria-label="{html.escape(ledge_label)}">'
                f'<span class="fl-name">{f.label}</span>{title}<span class="fl-when">{when_text(f.updated_at)}</span></a></section>'
            )
        auto = (f' data-zoom-floor="{html.escape(zoom[0])}" data-zoom-next="{html.escape(zoom[1])}"' if zoom else "")
        return (f'<div class="bc-wrap"><div class="bc-scene"{auto}><div class="bc">'
                '<div class="bc-top" aria-hidden="true"></div><div class="bc-side" aria-hidden="true"></div>'
                f'<div class="bc-front">{"".join(rows)}</div></div></div></div>')

    async def overview(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        q = clean_query(request.query_params.get("q"))
        form = (f'<form method="get" action="/shelf" class="search" role="search"><label>책장 전체에서 찾기 '
                f'<input type="search" name="q" value="{html.escape(q)}"></label><button>찾기</button></form>')
        floors = await run_in_threadpool(self.store.list_floors, uid)
        if q:
            return await self._search(request, session, floors, q, form)
        zoom = None
        if (zf := request.query_params.get("zoom")) and any(f.id == zf for f in floors):
            zoom = (zf, safe_next(request.query_params.get("next") or "", f"/shelf/floor/{zf}"))
        notices = await run_in_threadpool(self._notices, uid, request, session, "/shelf")
        case = await run_in_threadpool(self._case_html, uid, floors, zoom)
        room = sum(1 for f in floors if not f.common) < MAX_FLOORS
        new_floor = (
            '<details class="card"><summary>새 층 만들기</summary>'
            "<p>원고 없이 제목만 있는 층을 만듭니다. 원고는 그 층의 '책 추가'에서 원고 파일을 고르면 원고 책이 됩니다.</p>"
            f'<form method="post" action="/shelf/floors">{self._csrf_input(session)}'
            f'<label class="block">작업물 제목 <input name="title" maxlength="{FLOOR_TITLE_MAX}" required></label>'
            '<p><button>층 만들기</button></p></form></details>'
            if room else f'<p class="muted">층은 공용 빼고 {MAX_FLOORS}개까지 만들 수 있습니다.</p>'
        )
        body = (f"{notices}{form}{case}"
                "<p>층을 누르면 그 층이 크게 열립니다. 모음 책과 문서 책은 다른 층으로 끌어 놓으면 그 층으로 옮겨집니다"
                "(책 설정의 '위치'로도 옮길 수 있습니다). 원고 책은 그 층 자체라 옮기지 않습니다.</p>"
                f"{new_floor}{self._move_form(session, '/shelf')}{FLOOR_SCRIPT}")
        return self._shelf_floor_page("책장", body, session)

    async def _search(self, request: Request, session: tuple[str, str], floors: list[Floor], q: str, form: str) -> Response:
        uid = session[0]
        found = await run_in_threadpool(self._search_groups, uid, floors, q)
        hits = [g for g in found if g]
        head = (f'<p class="crumb"><a href="/shelf">← 책장</a></p>{form}'
                f"<p>「{html.escape(q)}」 " + (f"찾은 층 {len(hits)}곳" if hits else "찾는 말이 들어간 층·카테고리·항목이 없습니다.")
                + (" · 한 글자는 그 글자가 들어간 항목을 최근 것부터 보입니다." if one_char(q) else "") + "</p>")
        missing = [f.label for f, g in zip(floors, found, strict=True) if not g]
        if hits and missing:
            head += f'<p class="muted">찾는 말이 없는 층: {" · ".join(missing)}</p>'
        return self._shelf_floor_page("책장", head + "".join(hits) + FLOOR_SCRIPT, session)

    def _search_groups(self, uid: str, floors: list[Floor], q: str) -> list[str]:
        """층마다 한 덩어리(HTML). 찾은 것이 없으면 빈 문자열."""
        needle = q.replace(" ", "").lower()
        doc_hits = set(find(self.store, uid, ["document"], q))  # 문서 책 내용(웹 검색 전용 레인)
        out = []
        for f in floors:
            kinds: list[Kind] = [builtin_kind(k, f.id) for k in f.builtins]
            kinds += [category_kind(c) for c in self.store.list_categories(uid, floors=[f.id])]
            named = needle in f.label.replace(" ", "").lower() or needle in f.title.replace(" ", "").lower()
            parts, by_name = [], []
            for kind in kinds:
                rows = self._rows(uid, kind, None, q)
                if needle and needle in kind.name.replace(" ", "").lower():
                    by_name.append(kind)
                if not rows:
                    continue
                updated = (self.store.category_updated(uid, kind.category.id) if kind.category
                           else self.store.builtin_updated(uid, kind.base, f.id))
                more = (f' <small><a href="/shelf/{kind.key}?q={urllib.parse.quote(q)}">{html.escape(kind.name)}에서 {len(rows)}개 모두 보기</a></small>'
                        if len(rows) > GROUP_SIZE else "")
                parts.append(f'<section class="group"><h3><a href="/shelf/{kind.key}">{html.escape(kind.name)}</a> '
                             f'<small>{len(rows)}개 · {when_text(updated)}</small>{more}</h3>'
                             f'<ol class="board">{"".join(row_html(r, q) for r in rows[:GROUP_SIZE])}</ol></section>')
            for d in self.store.list_documents(uid, floors=[f.id]):  # 문서 책(#94): 제목·내용
                in_title = needle and needle in d.title.replace(" ", "").lower()
                if in_title or d.id in doc_hits:
                    parts.append(f'<section class="group"><h3><a href="/shelf/doc/{html.escape(d.id)}">{html.escape(d.title)}</a> '
                                 f'<small>문서 책 · {when_text(d.updated_at)}</small></h3></section>')
            if not (parts or by_name or named):
                out.append("")
                continue
            names = ""
            if by_name:
                names = "<p>카테고리 이름에 찾는 말이 들어 있습니다: " + " · ".join(
                    f'<a href="/shelf/{k.key}">{html.escape(k.name)}</a>' for k in by_name) + "</p>"
            title = "" if f.common else f" · {html.escape(f.title)}"
            out.append(f'<section class="fgroup" data-result-floor="{html.escape(f.id)}">'
                       f'<h2><a href="/shelf/floor/{html.escape(f.id)}">{f.label}{title}</a> <small>{when_text(f.updated_at)}</small></h2>'
                       + ('<p class="muted">층 이름에 찾는 말이 들어 있습니다.</p>' if named else "") + names + "".join(parts)
                       + "</section>")
        return out

    # ---- 한 층 ---------------------------------------------------------------------------------
    async def floor_page(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        floors = await run_in_threadpool(self.store.list_floors, uid)
        floor = next((f for f in floors if f.id == request.path_params["floor"]), None)
        if floor is None:
            return self._shelf_floor_page("책장", '<p class="msg err">없는 층입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>',
                                          session, 404)
        here = f"/shelf/floor/{floor.id}"
        band = "".join(
            f'<a href="/shelf/floor/{html.escape(f.id)}" data-drop-floor="{html.escape(f.id)}"'
            f'{" aria-current=page" if f.id == floor.id else ""}>{f.label}</a>' for f in floors)
        if floor.common:
            meta = f"{when_text(floor.updated_at)} · 공용 층은 모든 작업물이 함께 쓰는 층입니다."
        elif floor.has_manuscript:
            meta = f'{when_text(floor.updated_at)} · 이 층의 원고는 <a href="/shelf/book/{html.escape(floor.id)}">원고 책</a>을 누르면 열립니다.'
        else:
            meta = (f"{when_text(floor.updated_at)} · 원고가 아직 없습니다. 아래 점선 자리 '책 추가'에서 원고 파일을 고르면 "
                    "이 층의 원고 책이 됩니다.")
        notices = await run_in_threadpool(self._notices, uid, request, session, here)
        books = await run_in_threadpool(self.books, uid, floor.id)
        body = (
            f'<div class="floor-head"><a class="all-shelf" href="/shelf">전체 책장</a>'
            f'<nav class="fband" aria-label="층">{band}</nav></div>'
            f'<p class="floor-meta">{meta}</p>{notices}'
            + shelf_html([book_html(b, floor.id) for b in books], add_book(floor.id))
            + "<p>책을 누르면 그 책이 열립니다. 모음 책과 문서 책은 위의 층 이름으로 끌어 놓으면 그 층으로 옮겨집니다"
            "(책 설정의 '위치'로도 옮길 수 있습니다).</p>"
            + self._move_form(session, here) + FLOOR_SCRIPT
        )
        return self._shelf_floor_page(floor_name(floor), body, session)

    # ---- 위치(카테고리 설정 화면) ---------------------------------------------------------------
    def location_form(self, uid: str, session: tuple[str, str], kind: Kind) -> str:
        floors = [f for f in self.store.list_floors(uid) if not (kind.base == "doc" and f.common)]  # 공용에는 모음 책만(#94)
        options = "".join(
            f'<option value="{html.escape(f.id)}"{" selected" if f.id == kind.floor else ""}>{html.escape(floor_name(f))}</option>'
            for f in floors)
        rule = ("문서 책은 작업물 층에만 둘 수 있습니다(공용 층에는 모음 책만)." if kind.base == "doc"
                else "받는 층에 같은 기본 카테고리가 있으면 하나로 합쳐집니다." if kind.category is None
                else "받는 층에 같은 이름의 카테고리가 있으면 옮기지 않습니다.")
        refs = " 원고의 인용 점검은 그 작업물 층과 공용의 문헌만 봅니다." if kind.base == "refs" else ""
        return (f'<h2>위치</h2><form method="post" action="/shelf/move" class="card">{self._csrf_input(session)}'
                f'<input type="hidden" name="book" value="{html.escape(kind.key)}"><input type="hidden" name="next" value="dest">'
                f'<label class="block">꽂힌 층 <select name="to">{options}</select></label>'
                f'<p class="muted">{"" if kind.base == "doc" else "항목은 모두 함께 옮겨집니다. "}{rule}{refs}</p>'
                "<p><button>옮기기</button></p></form>")

    # ---- 옮기기·되돌리기·층 만들기 ---------------------------------------------------------------
    async def shelf_move(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._shelf_floor_page("책장", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        book, to = str(form.get("book") or ""), str(form.get("to") or "")
        nxt = str(form.get("next") or "/shelf")
        back = safe_next(nxt) if nxt != "dest" else "/shelf"
        base, _, source = book.partition(".")
        try:
            if book.startswith(("doc.", "ms.")):  # 문서 책·원고 책(#94): 옮기기 규칙은 move_book이 안다
                move = await run_in_threadpool(move_book, self.store, uid, book, "", to)
            elif base in BUILTIN_KINDS and source:
                move = await run_in_threadpool(move_book, self.store, uid, base, source, to)
            else:
                try:
                    category = await run_in_threadpool(self.store.get_category, uid, book)
                except ValueError:
                    category = None
                if category is None:
                    raise MoveError("unknown_category", "없는 카테고리")
                move = await run_in_threadpool(move_book, self.store, uid, book, category.floor, to)
        except MoveError as e:
            return RedirectResponse(with_query(back, moveerr=e.code, b=book, t=to), status_code=303)
        target = f"/shelf/floor/{move.to_floor}" if nxt == "dest" else back
        return RedirectResponse(with_query(target, moved=move.id), status_code=303)

    async def shelf_undo(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._shelf_floor_page("책장", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        back = safe_next(str(form.get("next") or "/shelf"))
        try:
            move = await run_in_threadpool(undo_move, self.store, uid, str(form.get("move") or ""))
        except MoveError as e:
            return RedirectResponse(with_query(back, moveerr=e.code), status_code=303)
        return RedirectResponse(with_query(back, undone=move.id), status_code=303)

    async def floor_new(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._shelf_floor_page("책장", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        title = one_line(str(form.get("title") or ""))[:FLOOR_TITLE_MAX]
        if not title:
            return RedirectResponse("/shelf?floorerr=empty", status_code=303)
        try:
            project = await run_in_threadpool(self.store.create_project, uid, title)
        except ValueError:
            return RedirectResponse("/shelf?floorerr=full", status_code=303)
        return RedirectResponse(f"/shelf/floor/{project.id}?done=floor", status_code=303)
