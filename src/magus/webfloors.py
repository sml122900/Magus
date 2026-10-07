"""웹 책장: 한 화면(/shelf)의 3D 장·층으로 다가가기·책 패널·옮기기·되돌리기·층 만들기(사용자 결정 #93, 2026-10-07). Web에 섞어 쓰는 FloorPages.

- 한 화면(2026-10-07 밤, 사용자 요청): /shelf 하나에서 끝낸다. 상태는 주소에 둔다(/shelf?floor=<층>&book=<책>&at=<패널 안 주소>, pushState).
  새로고침·뒤로 가기·주소로 바로 들어와도 같은 상태로 열린다. 옛 한 층 화면(/shelf/floor/<층>)은 이 주소로 넘긴다.
- 전체 보기: 하나의 장을 조금 위·오른쪽에서 본다(정면·오른쪽 옆면·윗면, rotateX(-8°)·rotateY(-15°), 원근 1600px). 글자가 읽히는 것이 먼저다.
  바깥 틀(양옆 기둥·윗판·옆판·윗면)은 한 번만, 층은 그 안의 칸(뒤판·바닥판·안벽·천장), 책은 앞면(책등)·오른쪽 면·윗면이 있는 상자.
- 층 확대: 층(또는 위의 층 버튼)을 누르면 카메라가 그 층으로 다가가 멈춘다(rotateX(-4°)·rotateY(-6°)로 줄이고 본문 너비로 확대, 0.76초).
  그 상태가 한 층 화면이다. 위아래 층이 조금 보여 끌어 놓을 수 있다. 전체 보기에서 책을 누르면 먼저 그 층으로 다가간다.
- 책 열기: 확대된 층에서 책을 누르면 책이 살짝 앞으로 나오고, 장면 아래 패널(iframe)에 그 책 화면(모음 책 목록·원고 책 탭·문서 책)이 열린다.
  패널 안 화면은 머리(메뉴) 없이 그린다(web.py EMBED). 패널 안에서 바뀐 것(done=…)이 있으면 장면만 다시 받아 그린다.
- 움직임 줄이기(prefers-reduced-motion)면 전환 없이 바로 바뀐다. 이름표는 장과 함께 조금 기운다(원근을 완전히 펴지 않는다).
- 옮기기: 책을 다른 층이나 위의 층 버튼으로 끌어 놓는다. 마우스는 6px 움직이면, 손가락은 길게 눌러(0.35초) 들어 올린다.
  키보드 사용자는 책 설정의 '위치'로 옮긴다. 놓으면 POST /shelf/move(CSRF). 옮긴 뒤 "○○를 공용으로 옮겼습니다. [되돌리기]".
- 검색: 층 이름(작업물 제목)·카테고리 이름·항목 내용을 한 번에, 층 → 카테고리 순으로 묶는다. 결과를 누르면 그 층으로 다가가 그 책이 열린다(/shelf?at=<주소>).
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
from starlette.responses import HTMLResponse, RedirectResponse, Response

from magus.category.moves import error_message, move_book, undo_move, web_message
from magus.floors import MAX_FLOORS
from magus.ids import local_time
from magus.store import Floor, Store
from magus.store.floors import KINDS as BUILTIN_KINDS
from magus.store.floors import MoveError
from magus.store.formats import one_line
from magus.webshelf import (
    EMBED, GROUP_SIZE, KINDS, Book, Kind, builtin_kind, category_kind, clean_query, color_style, find, key_jitter, one_char, row_html,
    safe_at, spine_parts, state_url,
)

FLOOR_TITLE_MAX = 120
WHEN = "%m-%d %H:%M"
_NEXT = re.compile(r"/shelf(/[A-Za-z0-9_.\-/]*)?")
_STATE_ID = re.compile(r"[A-Za-z0-9_.\-]{1,80}")
PASS_ON = ("done", "c", "full", "moved", "undone", "moveerr", "b", "t", "floorerr")  # 옛 한 층 화면 주소에서 넘겨 줄 값

FLOOR_STYLE = """
.site{position:relative;z-index:5}
/* 장면: 카메라가 층으로 다가가면 그 층(과 위아래 조금)만 보이게 높이를 줄인다 */
.scene{position:relative;overflow:hidden;transition:height .76s cubic-bezier(.4,0,.2,1)}
.cab-stage{--persp:1600px;position:relative;display:flex;justify-content:center;padding:40px 0 28px;
perspective:calc(var(--persp) + var(--persp-add,0px));perspective-origin:50% 30%;transition:perspective-origin .76s cubic-bezier(.4,0,.2,1)}
.cab{--T:16px;--TOP:18px;--R:34px;--D:150px;--BD:104px;--pad:10px;--rx:-8deg;--ry:-15deg;--frx:-4deg;--fry:-6deg;--cx:-24px;
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
.mbook{position:relative;display:block;transform-style:preserve-3d;transform:translateZ(-14px);cursor:pointer;touch-action:pan-y;
color:inherit;text-decoration:none;outline:none;transition:transform .3s ease;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
/* 연 책: 칸에서 살짝 앞으로 뽑혀 나온다(선택 표시). 키보드 초점도 같은 테두리 */
.mbook.open{transform:translateZ(34px) translateY(-6px)}
.mbook.open .mb-front,.mbook:focus-visible .mb-front{box-shadow:0 0 0 3px #fff,0 0 0 6px var(--primary)}
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
.fband a.all-shelf{border-color:var(--mute);color:var(--ink)}
a.all-shelf{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:8px 16px;border:1px solid var(--mute);border-radius:8px;
background:var(--canvas);color:var(--ink);text-decoration:none;font-weight:600}
a.all-shelf:hover{border-color:var(--primary);color:var(--primary)}
.fband{display:flex;flex-wrap:wrap;gap:8px;margin:0}
.fband a{display:inline-flex;align-items:center;min-height:44px;padding:8px 14px;border:1px solid var(--line);border-radius:8px;
background:var(--canvas);color:var(--ink2);text-decoration:none;font-weight:600}
.fband a[aria-current]{border-color:var(--primary);color:var(--primary);box-shadow:inset 0 -3px 0 var(--primary)}
.fband a.drop-on{background:var(--primary);border-color:var(--primary);color:#fff}
.floor-meta{color:var(--ink2);margin:4px 0 8px}.floor-meta[hidden],[data-guide][hidden]{display:none}
/* 책 패널: 장면 아래. 안에는 지금의 책 화면(머리 없이)이 뜬다 */
.book-panel{margin:4px 0 16px;background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);overflow:hidden}
.book-panel[hidden]{display:none}
.bp-head{display:flex;align-items:center;gap:12px;padding:8px 8px 8px 16px;border-bottom:1px solid var(--line)}
.bp-title{margin:0;flex:1;min-width:0;font-size:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bp-title:focus{outline:none}.bp-title:focus-visible{outline:3px solid var(--primary);outline-offset:2px}
a.bp-close{display:inline-flex;align-items:center;min-height:44px;padding:0 18px;border:1px solid var(--mute);border-radius:9999px;
color:var(--ink);text-decoration:none;font-weight:600;flex:none}a.bp-close:hover{border-color:var(--primary);color:var(--primary)}
.bp-frame{display:block;width:100%;height:420px;border:0;background:var(--canvas)}
form.inline{display:inline}
.msg .undo{margin-left:12px}
.fgroup{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:4px 16px 8px;margin:16px 0;box-shadow:var(--shadow)}
.fgroup>h2{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}.fgroup>h2 small,.fgroup h3 small{font-weight:400;font-size:15px}
.fgroup h3{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;margin:16px 0 8px}
@media (max-width:700px){
.cab-stage{--persp:1100px;padding:28px 0 18px}
.cab{--T:10px;--TOP:12px;--D:80px;--BD:54px;--pad:8px;--rx:-6deg;--ry:-10deg;--frx:-3deg;--fry:-4deg;--cx:-8px;width:300px}
.cell{min-height:132px;padding-top:18px}
.fl .mini>li.brk.d{display:none}.fl .mini>li.brk.m{display:flex}
.cab{--R:30px}.fl-ledge{padding:0 8px;gap:4px;font-size:14px}.fl-when{font-size:12px;padding-left:6px}
.bp-title{font-size:18px}}
@media (prefers-reduced-motion:reduce){.scene,.cab,.cab-stage,.mbook{transition:none}}
"""

# 칸 안 너비(책 줄 바꿈 계산용). 장 600 - 기둥 16×2 - 안쪽 여백 10×2 / 모바일 장 300 - 기둥 10×2 - 안쪽 여백 8×2(여유 6)
CAB_ROW = {"d": 548, "m": 258}
MINI_GAP = 4
MINI_ADD_WIDTH = 36

# 끌어 옮기기(마우스·펜: pointer, 손가락: 길게 누르기) + 한 화면 책장(카메라·책 패널). 서버는 이것과 상관없이 POST를 다시 검사한다.
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
      form.elements.next.value = location.pathname + location.search;  // 옮긴 뒤 지금 상태(층·열린 책)로 돌아온다
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
    document.addEventListener("dragstart", function (e) { if (e.target.closest && e.target.closest("[data-book],.mbook")) e.preventDefault(); });
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

  // 한 화면 책장: 카메라(층으로 다가가기)·열린 책·패널. 상태는 주소에 둔다(/shelf?floor=&book=&at=).
  var scene = document.querySelector(".scene");
  if (scene) {
    var stage = scene.querySelector(".cab-stage"), cab = stage.querySelector(".cab");
    var panel = document.getElementById("book-panel"), frame = panel.querySelector("iframe"), ptitle = panel.querySelector(".bp-title");
    var pclose = panel.querySelector(".bp-close");
    var state = { floor: null, book: null, at: null }, openTimer = null, lastDone = "", opener = null, posted = false;
    var css = function (name) { return parseFloat(getComputedStyle(cab).getPropertyValue(name)) || 0; };
    var tf = function (x, y, s, rx, ry) {
      return "translate3d(" + x + "px," + y + "px,0) scale(" + s + ") rotateX(" + rx + "deg) rotateY(" + ry + "deg)";
    };
    var floorEl = function (id) { return id ? cab.querySelector('.fl[data-floor="' + id + '"]') : null; };
    var bookEl = function (key) { return key ? cab.querySelector('.mbook[data-key="' + key + '"]') : null; };
    var small = function () { return window.matchMedia("(max-width:700px)").matches; };

    // 전체 보기: CSS의 각도(층이 많으면 --rk로 줄인 것)
    function overview() {
      var rk = parseFloat(getComputedStyle(stage).getPropertyValue("--rk")) || 1;
      return { t: tf(css("--cx"), 0, 1, css("--rx") * rk, css("--ry")), h: stage.offsetHeight, po: "" };
    }
    // 층 확대: 각도를 줄이고 그 층이 본문 너비를 채우게. 원근이 있어 한 번에 맞지 않으므로 재어 가며 맞춘다.
    function closeUp(fl) {
      var rx = css("--frx"), ry = css("--fry"), peek = small() ? 26 : 40;
      var oldT = cab.style.transform, oldPo = stage.style.perspectiveOrigin;
      cab.style.transition = stage.style.transition = "none";
      var sr = scene.getBoundingClientRect(), W = sr.width, want = W * (small() ? 0.95 : 0.94);
      var s = want / cab.offsetWidth, x = 0, y = 0, r;
      stage.style.perspectiveOrigin = (W / 2) + "px " + (peek + fl.offsetHeight * s / 2) + "px";
      for (var i = 0; i < 5; i++) {
        cab.style.transform = tf(x, y, s, rx, ry); r = fl.getBoundingClientRect();
        if (i < 2) { s = s * want / r.width; continue; }
        x += sr.left + (W - r.width) / 2 - r.left; y += sr.top + peek - r.top;
      }
      cab.style.transform = tf(x, y, s, rx, ry); r = fl.getBoundingClientRect();
      var below = fl.nextElementSibling ? peek : 12;  // 맨 아래 층이면 아래로 비울 것이 없다
      var view = { t: tf(x, y, s, rx, ry), h: Math.round(r.bottom - sr.top + below), po: stage.style.perspectiveOrigin };
      cab.style.transform = oldT; stage.style.perspectiveOrigin = oldPo;
      void cab.offsetWidth; cab.style.transition = stage.style.transition = "";
      return view;
    }
    function camera(id, instant) {
      var fl = floorEl(id), v = fl ? closeUp(fl) : overview(), quick = instant || reduce;
      if (quick) cab.style.transition = stage.style.transition = scene.style.transition = "none";
      cab.style.transform = v.t; stage.style.perspectiveOrigin = v.po; scene.style.height = v.h + "px";
      scene.classList.toggle("zoomed", !!fl);
      if (quick) { void cab.offsetWidth; cab.style.transition = stage.style.transition = scene.style.transition = ""; }
    }
    function urlOf(st) {
      var q = [];
      if (st.floor) q.push("floor=" + encodeURIComponent(st.floor));
      if (st.book) q.push("book=" + encodeURIComponent(st.book));
      if (st.at) q.push("at=" + encodeURIComponent(st.at));
      return "/shelf" + (q.length ? "?" + q.join("&") : "");
    }
    function parse(u) {
      var p = u.searchParams;
      return { floor: p.get("floor"), book: p.get("book"), at: p.get("at") };
    }
    function srcOf(st) {
      if (st.at) return st.at;
      var b = bookEl(st.book);
      return b ? b.getAttribute("data-open") : null;
    }
    // 층 버튼·층 안내·안내 문구·책 순서(Tab)는 상태를 따른다
    function marks(st) {
      cab.querySelectorAll(".mbook.open").forEach(function (b) { b.classList.remove("open"); b.setAttribute("aria-expanded", "false"); });
      var b = bookEl(st.book);
      if (b) { b.classList.add("open"); b.setAttribute("aria-expanded", "true"); }
      cab.querySelectorAll(".mbook,a.madd").forEach(function (el) {
        el.tabIndex = st.floor && el.closest(".fl").getAttribute("data-floor") === st.floor ? 0 : -1;
      });
      document.querySelectorAll(".fband a[data-go]").forEach(function (a) {
        if (a.getAttribute("data-go") === (st.floor || "")) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
      });
      document.querySelectorAll("[data-meta]").forEach(function (p) { p.hidden = p.getAttribute("data-meta") !== (st.floor || ""); });
      document.querySelectorAll("[data-guide]").forEach(function (p) { p.hidden = p.getAttribute("data-guide") !== (st.floor ? "floor" : "all"); });
      var fl = floorEl(st.floor);
      document.title = (fl ? fl.getAttribute("data-name") + " · " : "") + "책장 · Magus";
    }
    function openPanel(src, name, focus) {
      panel.hidden = false; ptitle.textContent = name; frame.title = name;
      pclose.setAttribute("href", urlOf({ floor: state.floor }));
      if (frame.getAttribute("src") !== src) { frame.style.height = "420px"; frame.setAttribute("src", src); }
      if (focus) {
        var top = panel.getBoundingClientRect().top;
        if (top > window.innerHeight * 0.7) window.scrollBy({ top: top - window.innerHeight * 0.45, behavior: reduce ? "auto" : "smooth" });
        ptitle.focus({ preventScroll: true });
      }
    }
    function closePanel() {
      if (panel.hidden) return;
      panel.hidden = true; frame.setAttribute("src", "about:blank");
      if (opener && document.contains(opener) && opener.tabIndex === 0) opener.focus({ preventScroll: true });
    }
    // 상태 바꾸기. push: 주소 기록에 남긴다(뒤로 가기). instant: 움직임 없이
    function go(next, push, instant) {
      next = { floor: next.floor || null, book: next.book || null, at: next.at || null };
      if (!floorEl(next.floor)) next = { floor: null, book: null, at: null };
      var moving = next.floor !== state.floor, sameBook = next.book === state.book && next.at === state.at;
      if (moving || instant) camera(next.floor, instant);
      var be = bookEl(next.book), name = be ? be.getAttribute("data-name") : (next.at ? "책 추가" : "");
      state = next; marks(next);
      clearTimeout(openTimer);
      var src = srcOf(next);
      if (src) {
        if (!(sameBook && !panel.hidden)) {
          var wait = moving && !instant && !reduce ? 640 : 0;
          openTimer = setTimeout(function () { openPanel(src, name, !instant); }, wait);
        }
      } else closePanel();
      if (push) history.pushState(next, "", urlOf(next));
    }
    window.MagusShelf = { go: function (floor, book, at) { go({ floor: floor, book: book, at: at }, true, false); } };

    // 누름: 장면(층·책·책 추가), 층 버튼·층 안내·패널 머리의 책장 주소(/shelf?…)
    document.addEventListener("click", function (e) {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var fl = e.target.closest && e.target.closest(".cab .fl");
      if (fl) {
        var id = fl.getAttribute("data-floor"), book = e.target.closest(".mbook"), add = e.target.closest("a.madd");
        e.preventDefault();
        if (state.floor !== id) { go({ floor: id }, true); return; }  // 먼저 그 층으로 다가간다
        if (book) {
          var key = book.getAttribute("data-key"); opener = book;
          go(state.book === key && !state.at ? { floor: id } : { floor: id, book: key }, true);
        } else if (add) { opener = add; go({ floor: id, at: add.getAttribute("href") }, true); }
        return;
      }
      var a = e.target.closest && e.target.closest("a[href]");
      if (!a || !a.closest(".fband,.floor-metas,.book-panel")) return;
      var u = new URL(a.href, location.href);
      if (u.origin === location.origin && u.pathname === "/shelf" && !u.searchParams.get("q")) { e.preventDefault(); go(parse(u), true); }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || drag) return;
      if (srcOf(state)) go({ floor: state.floor }, true); else if (state.floor) go({}, true);
    });
    window.addEventListener("popstate", function (e) { go(e.state || parse(new URL(location.href)), false); });
    var resized = null;
    window.addEventListener("resize", function () { clearTimeout(resized); resized = setTimeout(function () { camera(state.floor, true); }, 120); });

    // 패널 안 화면: 높이 맞추기, 책장 주소는 이 화면에서, 바뀐 것이 있으면 장면만 다시 받기, 패널 안 위치를 주소에 남기기
    frame.addEventListener("load", function () {
      var w = frame.contentWindow, d;
      try { d = frame.contentDocument; } catch (err) { return; }
      if (!d || !d.body || !frame.getAttribute("src") || w.location.href === "about:blank") return;
      var fit = function () { frame.style.height = Math.max(160, d.body.scrollHeight + 4) + "px"; };
      fit(); if (window.ResizeObserver) new ResizeObserver(fit).observe(d.body);
      var h1 = d.querySelector("main > h1"); if (h1) { ptitle.textContent = h1.textContent; frame.title = h1.textContent; }
      d.addEventListener("click", function (ev) {
        var a = ev.target.closest && ev.target.closest("a[href]"); if (!a || ev.defaultPrevented || a.target) return;
        var u = new URL(a.href, w.location.href);
        if (u.origin === location.origin && u.pathname === "/shelf") { ev.preventDefault(); go(parse(u), true); }
      });
      d.addEventListener("submit", function (ev) { if ((ev.target.method || "").toLowerCase() === "post") posted = true; });
      var here = w.location.pathname + w.location.search;
      var done = /[?&](done|moved|undone)=/.test(w.location.search);
      if (posted || (done && here !== lastDone)) { posted = false; lastDone = here; refresh(); }  // 패널 안에서 저장했으면 장면(항목 수·이름·색)을 다시
      if (!done && here !== srcOf(state) && !panel.hidden) {
        state.at = here; history.replaceState(state, "", urlOf(state));
      }
    });
    // 패널 안에서 책이 바뀌면(항목 수·이름·색) 장면만 다시 그린다. 카메라·패널은 그대로
    function refresh() {
      fetch(urlOf({ floor: state.floor }), { credentials: "same-origin" }).then(function (r) { return r.ok ? r.text() : ""; }).then(function (t) {
        if (!t) return;
        var doc = new DOMParser().parseFromString(t, "text/html");
        [".cab", ".fband", ".floor-metas"].forEach(function (sel) {
          var a = document.querySelector(sel), b = doc.querySelector(sel); if (a && b) a.innerHTML = b.innerHTML;
        });
        camera(state.floor, true); marks(state);
      });
    }

    // 처음: 서버가 주소에서 읽어 확인한 상태로(움직임 없이)
    var first = { floor: scene.getAttribute("data-floor"), book: scene.getAttribute("data-book"), at: scene.getAttribute("data-at") };
    go(first, false, true);
    history.replaceState(state, "", location.href);
  }
  // 검색 결과: 누르면 그 층으로 다가가 그 책(그 자리)이 열린다
  document.querySelectorAll("[data-result-floor]").forEach(function (box) {
    box.addEventListener("click", function (e) {
      var a = e.target.closest("a[href^='/shelf/']"); if (!a) return;
      e.preventDefault(); location.assign("/shelf?at=" + encodeURIComponent(a.getAttribute("href")));
    });
  });
})();
</script>"""


def safe_next(value: str, fallback: str = "/shelf") -> str:
    """돌아갈 주소: 책장 안의 주소만(바깥 주소·//로 시작하는 주소는 받지 않는다). 한 화면 책장의 상태(floor·book·at)는 남긴다."""
    path, _, query = (value or "").partition("?")
    if not _NEXT.fullmatch(path) or "//" in path:
        return fallback
    if not query:
        return path
    if path != "/shelf":
        return fallback
    keep: dict[str, str] = {}
    for k, v in urllib.parse.parse_qsl(query):
        if (k in ("floor", "book") and _STATE_ID.fullmatch(v)) or (k == "at" and safe_at(v)):
            keep[k] = v
    return state_url(keep.get("floor"), keep.get("book"), keep.get("at"))


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
    """책장에 꽂힌 작은 책: 앞면(책등: 종류 띠·이름·아래 숫자)·오른쪽 면·윗면이 있는 상자.
    그 층에 다가가 있을 때 누르면 장면 아래 패널에 열린다(data-open = 책 화면 주소). 끌어 옮길 수 있다."""
    width, height = mini_size(book)
    count, label = spine_parts(book)
    drag = f' data-book="{html.escape(book.key)}" data-from="{html.escape(floor)}"' if book.movable else ""
    return (f'<li><a class="mbook" href="{html.escape(state_url(floor, book.key))}"{drag} data-key="{html.escape(book.key)}" '
            f'data-open="{html.escape(book.href or "")}" data-name="{html.escape(book.name)}" aria-label="{label}" title="{label}" '
            f'aria-controls="book-panel" aria-expanded="false" style="{color_style(book.color)}width:{width}px;height:{height}px">'
            f'<span class="mb-front" aria-hidden="true"><span class="mb-band top">{html.escape(book.band)}</span>'
            f'<span class="mb-name">{html.escape(book.name)}</span>'
            f'<span class="mb-band bottom{" stale" if book.stale else ""}">{count}</span></span>'
            '<span class="pl mb-side" aria-hidden="true"></span><span class="pl mb-top" aria-hidden="true"></span></a></li>')


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
            ("/shelf/floor/{floor}", ["GET"], self.floor_redirect),
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
    def _case_html(self, uid: str, floors: list[Floor]) -> str:
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
                f'<section class="fl" data-floor="{html.escape(f.id)}" data-drop-floor="{html.escape(f.id)}" data-name="{html.escape(floor_name(f))}">'
                f'<div class="cell">{faces}<ul class="mini" aria-label="{html.escape(f.label)}에 꽂힌 책">{minis}</ul></div>'
                f'<a class="fl-ledge" href="{html.escape(state_url(f.id))}" aria-label="{html.escape(ledge_label)}">'
                f'<span class="fl-name">{f.label}</span>{title}<span class="fl-when">{when_text(f.updated_at)}</span></a></section>'
            )
        # 층이 많아 장이 길면 위아래 원근 차이가 커진다: 기울기를 줄이고 원근 거리를 늘린다(층 다섯까지는 그대로)
        n = len(floors)
        tilt = "" if n <= 5 else f' style="--rk:{max(.4, round(5 / n, 3))};--persp-add:{(n - 5) * 160}px"'
        frame = "".join(f'<span class="pl {c}" aria-hidden="true"></span>'
                        for c in ("cab-top", "cab-side", "cab-crown", "cab-post l", "cab-post r"))
        return f'<div class="cab-stage"{tilt}><div class="cab">{frame}{"".join(rows)}</div></div>'

    # ---- 한 화면의 상태(층·열린 책·패널 안 주소) ------------------------------------------------------
    def _key_floor(self, uid: str, key: str) -> str | None:
        """책 주소 이름(ms.<작업물>·doc.<id>·<종류>.<층>·카테고리 id) → 그 책이 꽂힌 층."""
        if key.startswith("ms."):
            return key[3:]
        if key.startswith("doc."):
            doc = self.store.get_document(uid, key[4:])
            return doc.floor if doc else None
        base, _, floor = key.partition(".")
        if base in BUILTIN_KINDS:
            return floor or None
        try:
            category = self.store.get_category(uid, key)
        except ValueError:
            return None
        return category.floor if category else None

    def locate(self, uid: str, at: str) -> tuple[str | None, str | None]:
        """패널 안 주소(책 화면) → (층, 책). 책 추가·모음 책 만들기처럼 책이 없는 화면은 (층, None)."""
        path, _, query = at.partition("?")
        parts = [urllib.parse.unquote(x) for x in path.split("/")[2:] if x]
        if not parts:
            return None, None
        head = parts[0]
        if head in ("add", "new"):
            return dict(urllib.parse.parse_qsl(query)).get("floor"), None
        if head == "book" and len(parts) > 1:
            key = f"ms.{parts[1]}"
        elif head == "doc" and len(parts) > 1:
            key = f"doc.{parts[1]}"
        elif head in ("edit", "trash") and len(parts) > 1:
            key = parts[1]
        else:
            key = head
        return self._key_floor(uid, key), key

    def _view(self, uid: str, floors: list[Floor], params: Any) -> tuple[str | None, str | None, str | None, str | None, str]:
        """주소 → (층, 책, 패널 안 주소, 패널에 열 주소, 패널 제목). 맞지 않는 값은 버린다(전체 보기)."""
        at = safe_at(params.get("at")) or safe_at(params.get("next"))  # next: 옛 검색 결과 주소(zoom·next)
        floor, book = params.get("floor") or params.get("zoom") or None, params.get("book") or None
        if at and not (floor and book):
            found_floor, found_book = self.locate(uid, at)
            floor, book = floor or found_floor, book or found_book
        if floor not in {f.id for f in floors}:
            return None, None, None, None, ""
        found = next((b for b in self.books(uid, floor) if b.key == book), None) if book else None
        if found is None:
            book = None
        elif at == found.href:
            at = None
        src = at or (found.href if found else None)
        return floor, book, at, src, found.name if found else ("책 추가" if at else "")

    def _break_out(self, request: Request) -> Response:
        """패널(iframe) 안에서 책장 주소가 열리면(저장·휴지통 뒤 넘어오기, 층 이름 누르기) 바깥 화면을 그 주소로 바꾼다."""
        url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return HTMLResponse(f'<!doctype html><meta charset="utf-8"><a id="go" href="{html.escape(url)}" target="_top">책장으로 가기</a>'
                            '<script>window.top.location.replace(document.getElementById("go").href)</script>')

    @staticmethod
    def _floor_meta(f: Floor, shown: bool) -> str:
        if f.common:
            tail = "공용 층은 모든 작업물이 함께 쓰는 층입니다."
        elif f.has_manuscript:
            tail = f'이 층의 원고는 <a href="{html.escape(state_url(f.id, "ms." + f.id))}">원고 책</a>을 누르면 열립니다.'
        else:
            tail = "원고가 아직 없습니다. 아래 점선 자리 '책 추가'에서 원고 파일을 고르면 이 층의 원고 책이 됩니다."
        return (f'<p class="floor-meta" data-meta="{html.escape(f.id)}"{"" if shown else " hidden"}>'
                f'<b>{html.escape(floor_name(f))}</b> · {when_text(f.updated_at)} · {tail}</p>')

    async def overview(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        if EMBED.get():
            return self._break_out(request)
        uid = session[0]
        q = clean_query(request.query_params.get("q"))
        form = (f'<form method="get" action="/shelf" class="search" role="search"><label>책장 전체에서 찾기 '
                f'<input type="search" name="q" value="{html.escape(q)}"></label><button>찾기</button></form>')
        floors = await run_in_threadpool(self.store.list_floors, uid)
        if q:
            return await self._search(request, session, floors, q, form)
        floor, book, at, src, title = await run_in_threadpool(self._view, uid, floors, request.query_params)
        here = state_url(floor, book, at)
        notices = await run_in_threadpool(self._notices, uid, request, session, here)
        case = await run_in_threadpool(self._case_html, uid, floors)

        def current(f: str | None) -> str:
            return ' aria-current="true"' if f == floor else ""

        band = (f'<a class="all-shelf" href="/shelf" data-go=""{current(None)}>전체 책장</a>'
                + "".join(f'<a href="{html.escape(state_url(f.id))}" data-go="{html.escape(f.id)}" data-drop-floor="{html.escape(f.id)}"'
                          f'{current(f.id)}>{f.label}</a>' for f in floors))
        metas = "".join(self._floor_meta(f, f.id == floor) for f in floors)
        guides = ('<p data-guide="all"' + (" hidden" if floor else "") + ">층을 누르면 그 층이 크게 열립니다. 모음 책과 문서 책은 다른 층으로 끌어 놓으면 "
                  "그 층으로 옮겨집니다(책 설정의 '위치'로도 옮길 수 있습니다). 원고 책은 그 층 자체라 옮기지 않습니다.</p>"
                  '<p data-guide="floor"' + ("" if floor else " hidden") + ">책을 누르면 그 책이 열립니다. 모음 책과 문서 책은 위의 층 이름으로 "
                  "끌어 놓으면 그 층으로 옮겨집니다(책 설정의 '위치'로도 옮길 수 있습니다).</p>")
        panel = (f'<section class="book-panel" id="book-panel" aria-labelledby="bp-title"{"" if src else " hidden"}>'
                 f'<div class="bp-head"><h2 class="bp-title" id="bp-title" tabindex="-1">{html.escape(title)}</h2>'
                 f'<a class="bp-close" href="{html.escape(state_url(floor))}">닫기</a></div>'
                 f'<iframe class="bp-frame" title="{html.escape(title or "책")}" src="{html.escape(src or "about:blank")}"></iframe></section>')
        state = "".join(f' data-{k}="{html.escape(v)}"' for k, v in (("floor", floor), ("book", book), ("at", at)) if v)
        room = sum(1 for f in floors if not f.common) < MAX_FLOORS
        new_floor = (
            '<details class="card"><summary>새 층 만들기</summary>'
            "<p>원고 없이 제목만 있는 층을 만듭니다. 원고는 그 층의 '책 추가'에서 원고 파일을 고르면 원고 책이 됩니다.</p>"
            f'<form method="post" action="/shelf/floors">{self._csrf_input(session)}'
            f'<label class="block">작업물 제목 <input name="title" maxlength="{FLOOR_TITLE_MAX}" required></label>'
            '<p><button>층 만들기</button></p></form></details>'
            if room else f'<p class="muted">층은 공용 빼고 {MAX_FLOORS}개까지 만들 수 있습니다.</p>'
        )
        body = (f'{notices}{form}<div class="floor-head"><nav class="fband" aria-label="층">{band}</nav></div>'
                f'<div class="floor-metas" aria-live="polite">{metas}</div>'
                f'<div class="scene"{state}>{case}</div>{guides}{panel}'
                f"{new_floor}{self._move_form(session, here)}{FLOOR_SCRIPT}")
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
                       f'<h2><a href="{html.escape(state_url(f.id))}">{f.label}{title}</a> <small>{when_text(f.updated_at)}</small></h2>'
                       + ('<p class="muted">층 이름에 찾는 말이 들어 있습니다.</p>' if named else "") + names + "".join(parts)
                       + "</section>")
        return out

    # ---- 옛 한 층 화면 ---------------------------------------------------------------------------
    async def floor_redirect(self, request: Request) -> Response:
        """옛 한 층 화면(/shelf/floor/<층>)은 한 화면 책장의 그 층으로 넘긴다(안내·되돌리기 값은 그대로 넘긴다)."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        floors = await run_in_threadpool(self.store.list_floors, session[0])
        floor = next((f for f in floors if f.id == request.path_params["floor"]), None)
        if floor is None:
            return self._shelf_floor_page("책장", '<p class="msg err">없는 층입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>',
                                          session, 404)
        keep = {k: v for k, v in request.query_params.items() if k in PASS_ON}
        book = keep.get("c") if keep.get("done") in ("edit", "made") else None
        return RedirectResponse(state_url(floor.id, book, **keep), status_code=303)

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
        target = state_url(move.to_floor) if nxt == "dest" else back
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
        return RedirectResponse(state_url(project.id, done="floor"), status_code=303)
