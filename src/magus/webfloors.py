"""웹 책장 전체(3D)·한 층 화면·옮기기·되돌리기·층 만들기(사용자 결정 #93, 2026-10-07). Web에 섞어 쓰는 FloorPages.

- 책장 전체(/shelf): 하나의 장을 위쪽에서 비스듬히 본다(정면·오른쪽 옆면·윗면, CSS 3D: perspective 1500px·rotateX(-16°)·rotateY(-30°)).
  바깥 틀(양옆 기둥·윗판·옆판·윗면)은 한 번만 그리고, 층은 그 안의 칸이다. 칸마다 뒤판·바닥판·안벽·천장이 있어 깊이가 있고,
  책은 앞면(책등: 종류 띠·이름·아래 숫자)·오른쪽 면·윗면이 있는 상자로 칸 안에 선다. 층 이름표는 선반 앞판에 붙어 장과 함께 기운다
  (기울어 보이는 것은 의도다. 원근을 펴지 않는다, 2026-10-07 사용자 판단). 맨 위가 공용 층, 그 아래로 작업물 층.
  층을 누르거나(키보드는 이름표 링크) 고르면 회전이 0으로 풀리며 그 층 정면으로 다가가고(0.76초) 한 층 화면으로 넘어간다.
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
    GROUP_SIZE, KINDS, Book, Kind, add_book, book_html, builtin_kind, category_kind, clean_query, color_style, find, key_jitter,
    one_char, row_html, shelf_html, spine_parts,
)

FLOOR_TITLE_MAX = 120
WHEN = "%m-%d %H:%M"
_NEXT = re.compile(r"/shelf(/[A-Za-z0-9_.\-/]*)?")

FLOOR_STYLE = """
.site{position:relative;z-index:5}
.cab-wrap{overflow-x:clip;margin:0 -16px;padding:0 16px}
.cab-stage{--persp:1500px;position:relative;display:flex;justify-content:center;padding:64px 0 24px;
perspective:calc(var(--persp) + var(--persp-add,0px));perspective-origin:50% 35%;transition:perspective-origin .76s cubic-bezier(.4,0,.2,1)}
.cab{--T:16px;--TOP:18px;--R:34px;--D:150px;--BD:104px;--pad:10px;--rx:-16deg;--ry:-30deg;--cx:-36px;
--wood:#8a5a32;--wood-top:#a9764a;--wood-side:#6a4325;--ledge:#7f5130;--in-back:#3a2617;--in-wall:#5a3b22;--in-ceil:#2c1d12;
--in-floor:#9b6a3f;--paper:#efe4cc;
position:relative;flex:none;width:600px;box-sizing:border-box;padding:var(--TOP) var(--T) 0;transform-style:preserve-3d;
transform:translate3d(var(--cx),0,0) scale(1) rotateX(calc(var(--rx) * var(--rk,1))) rotateY(var(--ry));
transition:transform .76s cubic-bezier(.4,0,.2,1)}
/* 면이 아닌 틀 상자(장·층·칸·목록)는 앞면(z=0)에 투명하게 놓여 안쪽 책을 가린다: 누름은 보이는 면·책·이름표만 받는다 */
.cab,.fl,.cell,.fl .mini,.fl .mini>li{pointer-events:none}
.cab .pl,.mbook,a.madd,.mini-empty,.fl-ledge{pointer-events:auto}
.cab .pl{position:absolute;display:block;box-sizing:border-box;backface-visibility:hidden;-webkit-backface-visibility:hidden}
.cab-top{left:0;top:calc(-1 * var(--D));width:100%;height:var(--D);transform-origin:0 100%;transform:rotateX(90deg);
background:var(--wood-top) repeating-linear-gradient(0deg,rgb(0 0 0/.04) 0 2px,transparent 2px 10px)}
.cab-side{left:100%;top:0;width:var(--D);height:100%;transform-origin:0 0;transform:rotateY(90deg);
background:var(--wood-side) repeating-linear-gradient(90deg,rgb(0 0 0/.05) 0 2px,transparent 2px 10px)}
.cab-crown,.cab-post{background:var(--wood) repeating-linear-gradient(90deg,rgb(0 0 0/.05) 0 2px,transparent 2px 9px)}
.cab-crown{left:0;top:0;width:100%;height:var(--TOP)}
.cab-post{top:0;width:var(--T);height:100%}.cab-post.l{left:0}.cab-post.r{right:0}
.fl{position:relative;transform-style:preserve-3d;cursor:pointer}
.cell{position:relative;transform-style:preserve-3d;display:flex;flex-direction:column;justify-content:flex-end;
min-height:150px;box-sizing:border-box;padding:24px var(--pad) 0}
.c-back{inset:0;transform:translateZ(calc(-1 * var(--D)));background:var(--in-back) linear-gradient(rgb(0 0 0/.35),rgb(0 0 0/0) 45%)}
.c-floor{left:0;top:calc(100% - var(--D));width:100%;height:var(--D);transform-origin:0 100%;transform:rotateX(90deg);
background:var(--in-floor) linear-gradient(rgb(0 0 0/.28),rgb(0 0 0/0))}
.c-ceil{left:0;top:0;width:100%;height:var(--D);transform-origin:0 0;transform:rotateX(-90deg);background:var(--in-ceil)}
.c-left,.c-right{top:0;width:var(--D);height:100%;background:var(--in-wall) linear-gradient(90deg,rgb(0 0 0/.3),rgb(0 0 0/0))}
.c-left{left:0;transform-origin:0 0;transform:rotateY(90deg)}
.c-right{left:calc(100% - var(--D));transform-origin:100% 0;transform:rotateY(-90deg)}
.fl .mini{position:relative;list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;align-items:flex-end;align-content:flex-end;
gap:0 4px;transform-style:preserve-3d}
.fl .mini>li{display:flex;transform-style:preserve-3d}
.fl .mini>li.brk{display:none;position:relative;flex:0 0 calc(100% + 2 * var(--pad));height:8px;margin:0 calc(-1 * var(--pad)) 18px;
background:var(--ledge)}
.brk .pl{left:0;top:calc(-1 * var(--D));width:100%;height:var(--D);transform-origin:0 100%;transform:rotateX(90deg);
background:var(--in-floor) linear-gradient(rgb(0 0 0/.28),rgb(0 0 0/0))}
.fl .mini>li.brk.d{display:flex}
.mini-empty{align-self:center;color:#f3e6cc;font-size:14px;padding:0 6px 40px;transform:translateZ(-14px)}
.mbook{position:relative;display:block;transform-style:preserve-3d;transform:translateZ(-14px);cursor:grab;touch-action:pan-y;
user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
.mb-front{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:space-between;overflow:hidden;
border-radius:2px 2px 1px 1px;background-color:var(--c);color:var(--fg);backface-visibility:hidden;-webkit-backface-visibility:hidden;
background-image:linear-gradient(90deg,rgb(0 0 0/.28),rgb(0 0 0/0) 16%,rgb(0 0 0/0) 84%,rgb(0 0 0/.22)),
 linear-gradient(90deg,transparent 30%,rgb(255 255 255/var(--glow)) 50%,transparent 70%)}
.mb-side{left:100%;top:0;width:var(--BD);height:100%;transform-origin:0 0;transform:rotateY(90deg);
background-color:var(--c);background-image:linear-gradient(rgb(0 0 0/.36),rgb(0 0 0/.36))}
.mb-top{left:0;top:calc(-1 * var(--BD));width:100%;height:var(--BD);transform-origin:0 100%;transform:rotateX(90deg);
background:var(--paper) repeating-linear-gradient(90deg,rgb(0 0 0/.07) 0 1px,transparent 1px 3px)}
.mb-band{display:block;width:100%;box-sizing:border-box;text-align:center;font-size:11px;font-weight:600;line-height:1.2;padding:3px 1px;
background:rgb(var(--away)/.22);border-top:1px solid rgb(var(--fgrgb)/.45);border-bottom:1px solid rgb(var(--fgrgb)/.45);
font-variant-numeric:tabular-nums;word-break:keep-all;overflow-wrap:anywhere}
.mb-band.top{margin-top:8px}.mb-band.bottom{margin-bottom:7px}.mb-band .line{display:block}
.mb-band.stale{background:#fff0a8;color:#1a1a1a;border-color:#1a1a1a}
.mb-name{writing-mode:vertical-rl;text-orientation:mixed;font-size:14px;font-weight:600;line-height:1.1;letter-spacing:.04em;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-height:0;flex:0 1 auto;margin:auto 0;padding:4px 0}
a.madd{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;width:36px;height:124px;box-sizing:border-box;
border:2px dashed #e9dcc0;border-radius:3px;color:#f6ecd8;text-decoration:none;font-weight:600;transform:translateZ(-14px)}
a.madd .plus{font-size:18px;line-height:1}a.madd .t{writing-mode:vertical-rl;font-size:12px;letter-spacing:.04em}
a.madd:hover,a.madd:focus-visible{background:rgb(255 255 255/.12);color:#fff}a.madd:focus-visible{outline:3px solid #fff;outline-offset:2px}
.fl-ledge{display:flex;align-items:center;gap:6px;height:var(--R);box-sizing:border-box;padding:0 12px;white-space:nowrap;
background:var(--ledge) linear-gradient(rgb(255 255 255/.12),rgb(255 255 255/0) 35%);color:#fbf3e3;text-decoration:none;
font-size:15px;line-height:1.2}
.fl-ledge:hover{color:#fbf3e3}.fl-ledge:focus-visible{outline:none;box-shadow:inset 0 0 0 3px #fff,inset 0 0 0 5px var(--primary)}
.fl-name,.fl-sep{font-weight:600;flex:none}
.fl-title{font-weight:600;min-width:0;flex:0 1 auto;overflow:hidden;text-overflow:ellipsis}
.fl-when{margin-left:auto;padding-left:10px;flex:none;color:#f3e6cc;font-size:14px;font-variant-numeric:tabular-nums}
.fl:hover .c-back{background-color:#55391f}.fl:hover .fl-ledge{box-shadow:inset 0 0 0 2px #f6ecd8}
.fl.drop-on .c-back{background-color:#3b2d72}.fl.drop-on .fl-ledge{box-shadow:inset 0 0 0 3px #fff,inset 0 0 0 6px var(--primary)}
.book.dragging,.mbook.dragging>span,.dragging.madd{opacity:.35}
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
@media (max-width:700px){
.cab-stage{--persp:1000px;padding:44px 0 16px}
.cab{--T:10px;--TOP:12px;--D:80px;--BD:54px;--pad:8px;--rx:-12deg;--ry:-20deg;--cx:-12px;width:300px}
.cell{min-height:132px;padding-top:18px}
.fl .mini>li.brk.d{display:none}.fl .mini>li.brk.m{display:flex}
.cab{--R:30px}.fl-ledge{padding:0 8px;gap:4px;font-size:13px}.fl-when{font-size:12px;padding-left:6px}}
@media (prefers-reduced-motion:reduce){.cab,.cab-stage{transition:none}}
"""

# 칸 안 너비(책 줄 바꿈 계산용). 장 600 - 기둥 16×2 - 안쪽 여백 10×2 / 모바일 장 300 - 기둥 10×2 - 안쪽 여백 8×2(여유 6)
CAB_ROW = {"d": 548, "m": 258}
MINI_GAP = 4
MINI_ADD_WIDTH = 36

# 끌어 옮기기(마우스·펜: pointer, 손가락: 길게 누르기) + 층으로 다가가기. 서버는 이것과 상관없이 POST를 다시 검사한다.
FLOOR_SCRIPT = """<script>
(function () {
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var form = document.getElementById("move-form"), drag = null, suppress = false;
  function targetAt(x, y) { var el = document.elementFromPoint(x, y); return el && el.closest ? el.closest("[data-drop-floor]") : null; }
  function start(book, x, y) {
    var r = book.getBoundingClientRect(), ghost = book.cloneNode(true), box = book.classList.contains("mbook");
    // 장 안의 작은 책은 상자라 화면에 보이는 크기가 기울어 있다: 앞면(책등)만 제 크기로 들고 다닌다
    var w = box ? book.offsetWidth : r.width, h = box ? book.offsetHeight : r.height;
    ghost.querySelectorAll(".pl").forEach(function (n) { n.remove(); });
    ghost.classList.add("drag-ghost"); ghost.removeAttribute("href"); ghost.setAttribute("aria-hidden", "true");
    ghost.style.width = w + "px"; ghost.style.height = h + "px";
    document.body.appendChild(ghost);
    drag = { book: book, ghost: ghost, dx: box ? w / 2 : x - r.left, dy: box ? h / 3 : y - r.top, over: null };
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

  // 층으로 다가가기: 회전이 0으로 풀리며 그 층이 본문 너비로 커져 화면 위쪽에 정면으로 온다. 그다음 한 층 화면(또는 검색 결과의 자리)으로 간다.
  // 변환 함수 목록(translate3d·scale·rotateX·rotateY)을 전체 보기와 같게 두어 함수마다 이어서 움직인다(중간 장면이 비지 않게).
  var cab = document.querySelector(".cab");
  function zoom(floorId, href, replace) {
    var fl = cab && cab.querySelector('.fl[data-floor="' + floorId + '"]');
    var go = function () { if (!href) return; if (replace) location.replace(href); else location.assign(href); };
    if (!fl || reduce) { go(); return; }
    var stage = cab.parentElement, sr = stage.getBoundingClientRect(), main = document.querySelector("main") || stage;
    var mr = main.getBoundingClientRect(), mcs = getComputedStyle(main);
    var left = mr.left + parseFloat(mcs.paddingLeft), width = mr.width - parseFloat(mcs.paddingLeft) - parseFloat(mcs.paddingRight);
    var W = cab.offsetWidth, H = cab.offsetHeight, s = Math.max(1, Math.min(2.4, width / W));
    var top = Math.max(16, Math.min(140, window.innerHeight * 0.16));
    // 회전이 풀린 평면에서: 변환 원점(장 가운데) 기준으로 커진 층의 왼쪽 위가 본문 왼쪽·화면 위쪽에 오게
    var bx = sr.left + cab.offsetLeft, by = sr.top + cab.offsetTop, ox = W / 2, oy = H / 2;
    var tx = left - bx - ox + s * ox, ty = top - by - oy - s * (fl.offsetTop - oy);
    stage.style.perspectiveOrigin = (left + s * W / 2 - sr.left) + "px " + (top + s * fl.offsetHeight / 2 - sr.top) + "px";
    fl.classList.add("zoom-target"); cab.classList.add("zoom");
    cab.style.transform = "translate3d(" + tx + "px," + ty + "px,0) scale(" + s + ") rotateX(0deg) rotateY(0deg)";
    setTimeout(go, 780);
  }
  window.MagusShelf = { zoom: zoom };
  window.addEventListener("pageshow", function (e) {  // 뒤로 가기로 돌아오면(bfcache) 원래 모습으로
    if (!cab || !e.persisted) return; cab.classList.remove("zoom"); cab.style.transform = ""; cab.parentElement.style.perspectiveOrigin = "";
    var t = cab.querySelector(".zoom-target"); if (t) t.classList.remove("zoom-target");
  });
  if (cab) {
    cab.addEventListener("click", function (e) {
      var fl = e.target.closest(".fl"); if (!fl || e.defaultPrevented || e.target.closest("a.madd")) return;  // 책 추가는 그 화면으로
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


def mini_size(book: Book) -> tuple[int, int]:
    """(폭, 높이). 한 층 화면의 큰 책과 같은 규칙을 줄인 것: 항목이 많을수록 두껍고, 높이는 책마다 조금 다르고 이름이 길면 높다."""
    width = 38 if book.count < 10 else 42 if book.count < 50 else 48 if book.count < 200 else 54
    return width, 124 + min(24, len(book.name) * 3) + key_jitter(book.key, 11)


def mini_book_html(book: Book, floor: str) -> str:
    """책장 전체에 꽂히는 작은 책: 앞면(책등: 종류 띠·이름·아래 숫자)·오른쪽 면·윗면이 있는 상자. 끌어 옮길 수 있다."""
    width, height = mini_size(book)
    count, label = spine_parts(book)
    drag = f' data-book="{html.escape(book.key)}" data-from="{html.escape(floor)}"' if book.movable else ""
    return (f'<li><span class="mbook"{drag} role="img" aria-label="{label}" title="{label}" '
            f'style="{color_style(book.color)}width:{width}px;height:{height}px">'
            f'<span class="mb-front" aria-hidden="true"><span class="mb-band top">{html.escape(book.band)}</span>'
            f'<span class="mb-name">{html.escape(book.name)}</span>'
            f'<span class="mb-band bottom{" stale" if book.stale else ""}">{count}</span></span>'
            '<span class="pl mb-side" aria-hidden="true"></span><span class="pl mb-top" aria-hidden="true"></span></span></li>')


def mini_add_html(floor: str) -> str:
    """장 안의 '책 추가' 점선 자리(누르면 그 층의 책 추가 화면)."""
    return (f'<li><a class="madd" href="/shelf/add?floor={urllib.parse.quote(floor)}" aria-label="책 추가">'
            '<span class="plus" aria-hidden="true">+</span><span class="t" aria-hidden="true">책 추가</span></a></li>')


def row_breaks(widths: list[int], room: int) -> set[int]:
    """칸 안 너비(room)에 책을 차례로 세울 때 새 줄이 시작되는 자리(그 앞에 보조 선반을 둔다)."""
    out, used = set(), 0
    for i, w in enumerate(widths):
        if used and used + MINI_GAP + w > room:
            out.add(i)
            used = w
        else:
            used = used + MINI_GAP + w if used else w
    return out


def with_shelves(items: list[str], widths: list[int]) -> str:
    """책 사이에 줄 바꿈(보조 선반)을 데스크톱(d)·모바일(m)용으로 넣는다. 화면 너비에 맞는 것만 CSS가 보인다."""
    breaks = {k: row_breaks(widths, room) for k, room in CAB_ROW.items()}
    out = []
    for i, item in enumerate(items):
        if kinds := [k for k in CAB_ROW if i in breaks[k]]:
            out.append(f'<li class="brk {" ".join(kinds)}" aria-hidden="true"><span class="pl"></span></li>')
        out.append(item)
    return "".join(out)


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
        """하나의 장: 바깥 틀(윗면·옆판·윗판·기둥)은 한 번, 층은 그 안의 칸(뒤판·바닥판·안벽·천장 + 책 + 앞판 이름표)."""
        faces = "".join(f'<span class="pl {c}" aria-hidden="true"></span>' for c in ("c-back", "c-ceil", "c-left", "c-right", "c-floor"))
        rows = []
        for f in floors:
            books = self.books(uid, f.id)
            items = [mini_book_html(b, f.id) for b in books] or ['<li class="mini-empty">비어 있음</li>']
            widths = [mini_size(b)[0] for b in books] or [80]
            minis = with_shelves([*items, mini_add_html(f.id)], [*widths, MINI_ADD_WIDTH])
            title = ("" if f.common else '<span class="fl-sep" aria-hidden="true">·</span>'
                     f'<span class="fl-title" title="{html.escape(f.title)}">{html.escape(f.title)}</span>')
            ledge_label = f"{floor_name(f)}, {when_text(f.updated_at)}, 책 {len(books)}권"
            rows.append(
                f'<section class="fl" data-floor="{html.escape(f.id)}" data-drop-floor="{html.escape(f.id)}">'
                f'<div class="cell">{faces}<ul class="mini" aria-label="{html.escape(f.label)}에 꽂힌 책">{minis}</ul></div>'
                f'<a class="fl-ledge" href="/shelf/floor/{html.escape(f.id)}" aria-label="{html.escape(ledge_label)}">'
                f'<span class="fl-name">{f.label}</span>{title}<span class="fl-when">{when_text(f.updated_at)}</span></a></section>'
            )
        auto = (f' data-zoom-floor="{html.escape(zoom[0])}" data-zoom-next="{html.escape(zoom[1])}"' if zoom else "")
        # 층이 많아 장이 길면 위아래 원근 차이가 커진다: 기울기를 줄이고 원근 거리를 늘린다(층 다섯까지는 그대로)
        n = len(floors)
        tilt = "" if n <= 5 else f' style="--rk:{max(.4, round(5 / n, 3))};--persp-add:{(n - 5) * 160}px"'
        frame = "".join(f'<span class="pl {c}" aria-hidden="true"></span>'
                        for c in ("cab-top", "cab-side", "cab-crown", "cab-post l", "cab-post r"))
        return (f'<div class="cab-wrap"><div class="cab-stage"{auto}{tilt}><div class="cab">{frame}{"".join(rows)}</div></div></div>')

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
