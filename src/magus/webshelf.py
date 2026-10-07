"""웹 책장(2026-10-06, #92): 생각·문체·문헌(기본 카테고리)과 저자가 만든 카테고리를 책장에 꽂힌 양장본으로 보이고,
책을 누르면 게시판형 목록(한 줄 = 제목 · 작성 시각 · 보조 정보, 누르면 그 자리에서 펼침)과 검색이 열린다.

- 항목마다 고유 주소(/shelf/ideas/<id>, /shelf/<카테고리 id>/<항목 id> 등)가 있고, 그 주소로 들어오면 그 항목이 펼쳐진 채 보인다.
- 검색은 서버에서 한다(GET ?q=). 두 글자 이상은 기존 FTS 인덱스(2글자 조각)로 찾아 많이 맞은 것부터,
  한 글자는 2글자 조각 색인으로 찾을 수 없어 그 글자가 그대로 들어 있는 항목을 최근 것부터 보인다.
- 카테고리 만들기·이름 바꾸기·색 바꾸기·휴지통은 이 화면과 대화(category_* 도구) 양쪽에서 된다.
  저자가 만든 카테고리와 생각에는 제목(선택)과 내용을 바로 적는 폼이 있다(누가 = 저자). 문체·문헌은 대화로 넣는다.
- 책장 전용 색(책 색 격자·선반 나무색)은 이 파일과 magus.category.rules에만 있다. 다른 화면에는 쓰지 않는다
  (docs/decisions/web-style.md "책장 전용").
- 책 색은 ^#[0-9a-fA-F]{6}$ 형식만 스타일에 넣는다. 글자색은 책 색에 맞춰 흰색·짙은 색 중 대비가 높은 쪽(4.5:1 이상)이고,
  결·띠·가운데 밝은 줄은 글자와 반대 방향(글자가 희면 어둡게, 짙으면 밝게)으로만 얹어 글자 대비를 낮추지 않는다.
- 모든 POST는 CSRF 토큰을 확인한다(Web._form). 카테고리 이름·항목 내용은 모든 출력에서 이스케이프한다.
- 층(#93): 기본 카테고리는 층마다 따로 꽂히므로 주소 이름이 "<종류>.<층 id>"다(ideas.book, styles.common).
  저자의 카테고리는 id 그대로. 예전 주소(/shelf/ideas, /shelf/ideas/<id>)는 그 항목·종류가 꽂힌 층의 주소로 넘긴다.
  책장 전체(3D)·한 층 화면·옮기기·되돌리기는 magus.webfloors에 있다.
"""

from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from magus.floors import COMMON
from magus.category.rules import (
    BUILTINS, COLOR_NAMES, CONTENT_MAX, DEFAULT_COLORS, FIELD_MAX, HEX, MAX_CATEGORIES, MAX_MY_COLORS, NEW_COLOR_ORDER,
    PALETTE, PALETTE_BY_NAME, TEMPLATE_BY_KEY, TEMPLATES, TITLE_MAX, check_name, name_key,
)
from magus.ids import local_time, new_id, utcnow
from magus.melchior.author_report import chapters_text, cite_label
from magus.melchior.report import build_cite_report
from magus.store import Category, CategoryItem, Idea, ShelfSettings, Store
from magus.store.base import Lane
from magus.store.formats import one_line
from magus.textindex import match_query, tokens

PAGE_SIZE = 100  # 목록 한 쪽
GROUP_SIZE = 5  # 책장 전체 검색에서 카테고리마다 먼저 보이는 수
PER_SHELF = 10  # 선반 한 칸에 꽂는 책 수(넘으면 선반이 하나 늘어난다)
SEARCH_LIMIT = 500
WHEN = "%Y-%m-%d %H:%M"
LIGHTS = {"verified": ("🟢", "확인"), "unverified": ("🟡", "미확인")}
TAGS_BY = {"ai": "AI가 뽑은 태그", "author": "저자가 정한 태그"}
SAY = "Claude에게 이렇게 말하면 쌓입니다. 예: "
LIGHT_TEXT, DARK_TEXT = "#ffffff", "#1a1a1a"
AI_TITLE = '<span class="tag">AI가 지은 제목</span>'
EMPTY_IDEA = "내용을 적어 주세요."
EMPTY_ITEM = "제목·내용·칸 중 하나는 적어 주세요."


def luminance(color: str) -> float:
    """WCAG 상대 휘도."""
    def channel(i: int) -> float:
        c = int(color[i : i + 2], 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_color(background: str) -> str:
    """책 색 위 글자색: 흰색과 짙은 색 중 대비가 높은 쪽. 둘 다 4.5:1에 못 미치면(가운데 밝기) 흰색·검정 중 높은 쪽(언제나 4.58 이상)."""
    best = max((LIGHT_TEXT, DARK_TEXT), key=lambda c: contrast(background, c))
    if contrast(background, best) >= 4.5:
        return best
    return max(("#ffffff", "#000000"), key=lambda c: contrast(background, c))


def safe_color(value: str | None, fallback: str) -> str:
    """스타일에 넣을 수 있는 색만(#RRGGBB). 그 밖의 문자열은 버리고 fallback."""
    return value.lower() if isinstance(value, str) and HEX.fullmatch(value) else fallback


@dataclass(frozen=True)
class Book:
    """책장에 꽂힌 책 하나: 원고 책·모음 책(기본 카테고리와 저자의 카테고리)·문서 책(#94)."""

    key: str  # 주소에 쓰는 이름: <종류>.<층>(ideas.book) | 카테고리 id | ms.<작업물 id> | doc.<문서 id>
    name: str
    band: str  # 위쪽 띠: 책 종류(원고·모음·문서, #94)
    count: int
    color: str
    href: str | None  # None이면 누를 수 없는 미리보기
    # 문헌만: 원문을 확인한 편수. 책등 아래를 "확인 n · 전체 m" 두 줄로 보인다(두께는 전체 수 기준 그대로).
    # 문헌 수에는 원고 참고문헌에서 들여온 미확인 항목도 들어 있어, 전체만 보이면 '원문을 읽고 등록한 책'으로 오해한다.
    verified: int | None = None
    note: str | None = None  # 아래 띠 글(줄바꿈은 두 줄). 원고 책 "N장", 문서 책 "E2 기준"·"옛 판 기준"
    label: str | None = None  # 낭독기 이름(없으면 "이름, 항목 N개")
    movable: bool = True  # 끌어 옮길 수 있나(원고 책은 그 층 자체라 옮기지 않는다)
    stale: bool = False  # 문서 책: 기준 원고에 새 수정본이 왔다


def book_style(book: Book) -> str:
    color = safe_color(book.color, "#3b4652")
    fg = text_color(color)
    light_text = fg == LIGHT_TEXT or fg == "#ffffff"
    n = len(book.name)
    size = 26 if n <= 2 else 24 if n <= 4 else 22 if n <= 6 else 20 if n <= 9 else 18
    # 높이: 카테고리마다 조금 다르게(주소 이름의 해시라 같은 카테고리는 언제나 같다), 이름이 길면 이름이 다 들어가게 키운다.
    height = max(252 + int(hashlib.sha256(book.key.encode()).hexdigest()[:4], 16) % 41, 108 + round(n * size * 1.12))
    width = 56 if book.count < 10 else 64 if book.count < 50 else 74 if book.count < 200 else 86  # 많을수록 두껍게
    return (f"--c:{color};--fg:{fg};--fgrgb:{' '.join(str(int(fg[i:i + 2], 16)) for i in (1, 3, 5))};"
            f"--away:{'0 0 0' if light_text else '255 255 255'};"
            f"--glow:{0 if light_text else .14};--fs:{size}px;height:{height}px;width:{width}px")


def book_html(book: Book, floor: str | None = None) -> str:
    """floor를 주면 끌어 옮길 수 있는 책(data-book·data-from, #93)."""
    count = f"{book.count}개" if book.count < 10000 else f"{book.count / 10000:.1f}만개"
    label = html.escape(f"{book.name}, 항목 {book.count}개")
    if book.verified is not None:
        count = f'<span class="line">확인 {book.verified}</span><span class="line">전체 {book.count}</span>'
        label = html.escape(f"{book.name}, 확인 {book.verified}편, 전체 {book.count}편")
    if book.note is not None:
        count = "".join(f'<span class="line">{html.escape(line)}</span>' for line in book.note.split("\n"))
    if book.label is not None:
        label = html.escape(book.label)
    inner = (f'<span class="band top" aria-hidden="true">{html.escape(book.band)}</span>'
             f'<span class="spine-title" aria-hidden="true">{html.escape(book.name)}</span>'
             f'<span class="band bottom{" stale" if book.stale else ""}" aria-hidden="true">{count}</span>')
    if book.href is None:
        return f'<li><span class="book" style="{book_style(book)}" role="img" aria-label="{label}">{inner}</span></li>'
    drag = f' data-book="{html.escape(book.key)}" data-from="{html.escape(floor)}"' if floor and book.movable else ""
    return (f'<li><a class="book" href="{html.escape(book.href)}" style="{book_style(book)}" aria-label="{label}"{drag}>'
            f'{inner}</a></li>')


def add_book(floor: str) -> str:
    """'책 추가' 자리(#94): 누르면 책 종류(원고·모음·문서)를 고른다. 그 층에 꽂는다."""
    return (f'<li><a class="book add" href="/shelf/add?floor={urllib.parse.quote(floor)}" aria-label="책 추가">'
            '<span class="plus" aria-hidden="true">+</span><span class="spine-title" aria-hidden="true">책 추가</span></a></li>')


def shelf_html(books: list[str], extra: str = "") -> str:
    """책 HTML 목록 → 선반(PER_SHELF권씩). extra(카테고리 추가 자리)는 마지막 선반 끝에 둔다."""
    items = [*books, *([extra] if extra else [])]
    shelves = [items[i : i + PER_SHELF] for i in range(0, len(items), PER_SHELF)] or [[]]
    return ('<section class="case" aria-label="책장">'
            + "".join(f'<div class="shelf"><ul class="books">{"".join(row)}</ul></div>' for row in shelves)
            + "</section>")


# 책장 전용 스타일. 선반 나무색과 책 음영은 여기에만 있다(web-style.md "책장 전용").
SHELF_STYLE = """
@media (prefers-reduced-motion:no-preference){@view-transition{navigation:auto}
::view-transition-old(root),::view-transition-new(root){animation-duration:.28s}}
.crumb{margin:0 0 8px}.crumb a{text-decoration:none}
.search{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0 16px}
.search label{margin:0;flex:1 1 260px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.search input[type=search]{flex:1 1 200px;font-size:17px}
.case{--wood:#8a5a32;--wood2:#6f4524;--back:#f2ebdd;--board:#e7dcc3;--board-edge:#cbbb98;
background:var(--wood);background-image:repeating-linear-gradient(90deg,rgb(0 0 0/.05) 0 2px,transparent 2px 9px);
border-radius:8px;padding:12px 12px 4px;box-shadow:inset 0 0 0 2px var(--wood2),var(--shadow);margin:8px 0 16px}
.shelf{background:var(--back);border-radius:2px;margin:0 0 8px;box-shadow:inset 0 10px 14px -10px rgb(0 0 0/.35)}
.shelf::after{content:"";display:block;height:16px;background:linear-gradient(var(--board) 0 9px,var(--board-edge) 9px);
border-top:1px solid #fbf7ee;box-shadow:0 3px 4px rgb(0 0 0/.25)}
.books{list-style:none;margin:0;padding:28px 16px 0;display:flex;align-items:flex-end;gap:3px;overflow-x:auto;
scroll-snap-type:x proximity;scrollbar-width:thin}
.books>li{flex:0 0 auto;scroll-snap-align:start;display:flex}
.book{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:space-between;
color:var(--fg);text-decoration:none;border-radius:4px 4px 2px 2px;background-color:var(--c);
background-image:
 linear-gradient(90deg,rgb(0 0 0/.30),rgb(0 0 0/0) 15%,rgb(0 0 0/0) 85%,rgb(0 0 0/.28)),
 linear-gradient(90deg,transparent 30%,rgb(255 255 255/var(--glow)) 50%,transparent 70%),
 repeating-linear-gradient(0deg,rgb(var(--away)/.035) 0 1px,transparent 1px 3px),
 repeating-linear-gradient(90deg,rgb(var(--away)/.025) 0 1px,transparent 1px 4px);
box-shadow:inset 0 1px 0 rgb(255 255 255/.25),1px 0 2px rgb(0 0 0/.25);transition:transform .15s ease,box-shadow .15s ease}
a.book:hover,a.book:focus-visible{color:var(--fg);transform:translateY(-14px);box-shadow:inset 0 1px 0 rgb(255 255 255/.25),0 10px 14px rgb(0 0 0/.3)}
.book:focus-visible{outline:3px solid var(--primary);outline-offset:3px}
.band{display:block;width:100%;text-align:center;font-size:14px;font-weight:600;line-height:1.2;
padding:6px 2px;background:rgb(var(--away)/.22);border-top:2px solid rgb(var(--fgrgb)/.45);
border-bottom:2px solid rgb(var(--fgrgb)/.45);font-variant-numeric:tabular-nums;white-space:nowrap}
.band.top{margin-top:14px}.band.bottom{margin-bottom:12px}.band .line{display:block;font-size:13px;line-height:1.35}
.band.bottom.stale{background:#fff0a8;color:#1a1a1a;border-color:#1a1a1a}
.spine-title{writing-mode:vertical-rl;text-orientation:mixed;font-size:var(--fs);font-weight:600;line-height:1.1;
letter-spacing:.06em;margin:auto 0;padding:10px 0;white-space:nowrap}
.book.add{--fs:18px;background:transparent;color:var(--ink2);border:2px dashed var(--ink2);box-shadow:none;justify-content:center;
gap:10px;width:60px;height:252px}
.book.add .plus{font-size:28px;line-height:1;font-weight:600}
.book.add .spine-title{margin:0;padding:0}
a.book.add:hover,a.book.add:focus-visible{background:rgb(255 255 255/.6);color:var(--ink)}
@media (prefers-reduced-motion:reduce){.book{transition:none}
a.book:hover,a.book:focus-visible{transform:none;outline:3px solid var(--primary);outline-offset:3px}}
.board{list-style:none;margin:12px 0;padding:0;background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.board>li{border-bottom:1px solid var(--line)}.board>li:last-child{border-bottom:0}
.board summary{display:grid;grid-template-columns:minmax(0,1fr) 9em 15em;align-items:baseline;gap:4px 16px;
padding:12px 16px 12px 44px;min-height:48px;cursor:pointer;list-style:none;position:relative}
.board summary::-webkit-details-marker{display:none}
.board summary::before{content:"▸";position:absolute;left:16px;top:10px;color:var(--ink2);font-size:20px;line-height:1.4}
.board details[open]>summary::before{content:"▾"}
.board details[open]{box-shadow:inset 4px 0 0 var(--primary)}
.board summary:hover .t{text-decoration:underline}
.board .t{font-weight:600;font-size:17px;color:var(--ink)}
.board .t.none{font-weight:400;color:var(--mute)}
.board .t .tag{font-size:14px;font-weight:400;margin-left:8px;vertical-align:1px}
.board .hit{grid-column:1/-1;color:var(--ink2);font-size:15px}
.board .when{color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap}
.board .aux{color:var(--ink2);font-size:15px}
.muted{color:var(--ink2)}
.board .body{padding:0 16px 16px 44px}
.board .body p{margin:8px 0}.board .body .muted{color:var(--ink2);font-size:15px}
mark{background:#fff0a8;color:var(--ink);border-radius:2px;padding:0 1px}
.group h2{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}.group h2 small{font-weight:400;font-size:16px}
dl.fields{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:8px 0}
dl.fields dt{color:var(--ink2);font-weight:600}dl.fields dd{margin:0}
.write>summary{font-weight:600;color:var(--ink);font-size:17px}
label.block{display:block;margin:12px 0 4px}label.block>input,label.block>textarea{display:block;width:100%;margin-top:4px}
textarea{font:inherit;color:var(--ink);background:var(--canvas);border:1px solid var(--mute);border-radius:6px;padding:8px 12px;
width:100%;min-height:150px;max-width:100%}
textarea:focus{border-color:var(--primary)}
fieldset{border:1px solid var(--line);border-radius:12px;padding:12px 16px 16px;margin:16px 0;background:var(--canvas);min-width:0}
legend{font-weight:600;padding:0 4px}
.tpl{display:flex;gap:8px;align-items:baseline;margin:8px 0}.tpl .muted{color:var(--ink2);font-size:15px}
.sw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin:8px 0 12px}
.sw{display:flex;align-items:center;gap:8px;margin:0;padding:6px 8px;min-height:44px;border:1px solid var(--line);border-radius:8px;
background:var(--canvas);cursor:pointer}
.sw .chip{width:28px;height:28px;border-radius:6px;border:1px solid rgb(0 0 0/.3);flex:0 0 auto}
.sw:has(input:checked){border-color:var(--primary);box-shadow:0 0 0 2px var(--primary)}
.picker{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:8px 0}
.picker label{margin:0}.picker input[type=number]{width:5.5em}.picker input[name=hex]{width:7.5em}
.picker input[type=color]{width:56px;height:44px;padding:2px;border:1px solid var(--mute);border-radius:6px;background:var(--canvas);vertical-align:middle}
.preview .case{display:inline-block;margin:0}.preview .books{padding:28px 24px 0}
.mycolors{list-style:none;padding:0;margin:8px 0;display:flex;flex-wrap:wrap;gap:8px 16px}
.mycolors li{display:flex;align-items:center;gap:8px}.mycolors .chip{width:28px;height:28px;border-radius:6px;border:1px solid rgb(0 0 0/.3)}
@media (max-width:767px){.board summary{display:flex;flex-wrap:wrap;padding-left:40px}.board .t{flex-basis:100%}
.board .hit{flex-basis:100%}.board .body{padding-left:40px}.books{padding:28px 10px 0}.sw-grid{grid-template-columns:repeat(2,1fr)}}
"""
# 고유 주소로 들어왔을 때 펼친 항목을 화면 위로(자바스크립트가 꺼져 있어도 펼쳐진 채 보인다)
SCROLL_SCRIPT = '<script>(function(){var d=document.querySelector("details[data-here]");if(d)d.scrollIntoView({block:"start"});})();</script>'
# 색 고르기: 색 선택기·#RRGGBB·R·G·B를 서로 맞추고 미리보기 책의 색과 글자색을 바꾼다. 서버는 이것과 상관없이 값을 다시 검사한다.
COLOR_SCRIPT = """<script>
(function () {
  var form = document.querySelector("form.colors");
  if (!form) return;
  var pick = form.querySelector("input[name=picker]"), hex = form.querySelector("input[name=hex]");
  var rgb = ["r", "g", "b"].map(function (n) { return form.querySelector("input[name=" + n + "]"); });
  var custom = form.querySelector("input[name=color][value=custom]"), book = document.querySelector(".preview .book");
  function lum(h) {
    return [1, 3, 5].map(function (i) { var c = parseInt(h.substr(i, 2), 16) / 255;
      return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); })
      .reduce(function (s, c, i) { return s + c * [0.2126, 0.7152, 0.0722][i]; }, 0);
  }
  function ratio(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function show(h) {  // 서버의 text_color와 같은 규칙
    if (!book || !/^#[0-9a-fA-F]{6}$/.test(h)) return;
    var fg = ratio(h, "#ffffff") >= ratio(h, "#1a1a1a") ? "#ffffff" : "#1a1a1a";
    if (ratio(h, fg) < 4.5) fg = ratio(h, "#ffffff") >= ratio(h, "#000000") ? "#ffffff" : "#000000";
    var light = fg === "#ffffff";
    book.style.setProperty("--c", h); book.style.setProperty("--fg", fg);
    book.style.setProperty("--fgrgb", [1, 3, 5].map(function (i) { return parseInt(fg.substr(i, 2), 16); }).join(" "));
    book.style.setProperty("--away", light ? "0 0 0" : "255 255 255"); book.style.setProperty("--glow", light ? "0" : ".14");
  }
  function fill(h, mark) {
    h = h.toLowerCase(); pick.value = h; hex.value = h;
    rgb.forEach(function (el, i) { el.value = parseInt(h.substr(1 + 2 * i, 2), 16); });
    if (mark) custom.checked = true;
    show(h);
  }
  pick.addEventListener("input", function () { fill(pick.value, true); });
  hex.addEventListener("input", function () { if (/^#[0-9a-fA-F]{6}$/.test(hex.value)) fill(hex.value, true); });
  rgb.forEach(function (el) { el.addEventListener("input", function () {
    var h = "#" + rgb.map(function (e) { var v = Math.max(0, Math.min(255, parseInt(e.value || "0", 10) || 0));
      return (v < 16 ? "0" : "") + v.toString(16); }).join("");
    pick.value = h; hex.value = h; custom.checked = true; show(h); }); });
  form.querySelectorAll("input[name=color]").forEach(function (el) { el.addEventListener("change", function () {
    if (el.value !== "custom") fill(el.value, false); else show(hex.value); }); });
  var name = form.querySelector("input[name=name]"), title = document.querySelector(".preview .spine-title");
  var initial = title ? title.textContent : "";
  if (name && title) name.addEventListener("input", function () { title.textContent = name.value.trim() || initial; });
})();
</script>"""


# ---- 검색 ----------------------------------------------------------------------------------

def clean_query(q: str | None) -> str:
    return " ".join((q or "").split())[:100]


def find(store: Store, user_id: str, lanes: list[Lane], q: str) -> list[str]:
    """검색어에 맞는 항목 id(owner_id)를 차례대로. 두 글자 이상 → FTS(많이 맞은 것부터), 한 글자 → 그대로 포함(최근 것부터)."""
    if not q:
        return []
    words = tokens(q)
    if any(len(t) >= 2 for t in words) and (match := match_query(q)):
        chunks = store.search_fts(user_id, lanes, match, SEARCH_LIMIT)
    else:
        chunks = store.search_substring(user_id, lanes, q, SEARCH_LIMIT)
    return list(dict.fromkeys(c.owner_id for c in chunks))


def one_char(q: str) -> bool:
    return bool(q) and not any(len(t) >= 2 for t in tokens(q))


def _pattern(q: str, text: str) -> re.Pattern[str] | None:
    """맞은 부분 표시: 검색어의 낱말이 그대로 있으면 그것을, 없으면 색인 조각(2글자·영단어)을 표시한다."""
    for terms in (q.split(), tokens(q)):
        terms = sorted({t for t in terms if t}, key=len, reverse=True)
        if terms:
            pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
            if pattern.search(text):
                return pattern
    return None


def mark(text: str, q: str) -> str:
    """text를 이스케이프하면서 맞은 부분을 <mark>로 감싼다."""
    pattern = _pattern(q, text) if q else None
    if pattern is None:
        return html.escape(text)
    out, last = [], 0
    for m in pattern.finditer(text):
        out += [html.escape(text[last : m.start()]), f"<mark>{html.escape(m.group())}</mark>"]
        last = m.end()
    return "".join([*out, html.escape(text[last:])])


def snippet(text: str, q: str, width: int = 40) -> str:
    """맞은 곳 앞뒤 width자(HTML). 맞은 곳이 없으면 빈 문자열."""
    text = one_line(text)
    pattern = _pattern(q, text) if q else None
    m = pattern.search(text) if pattern else None
    if m is None:
        return ""
    start, end = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if start else "") + mark(text[start:end], q) + ("…" if end < len(text) else "")


# ---- 목록 한 줄 ------------------------------------------------------------------------------

@dataclass
class Row:
    """게시판 한 줄. title이 없으면 preview(내용 앞부분)를 흐리게 보인다. aux·body·badge는 이미 이스케이프한 HTML."""

    id: str
    link: str  # 고유 주소
    at: str
    title: str | None
    preview: str
    aux: str
    body: str
    text: str  # 맞은 부분 찾기용 평문(제목 밖에서 맞았을 때 한 줄 보이기)
    badge: str = ""  # 제목 뒤 표시(AI가 지은 제목)
    actions: bool = False  # 고치기·휴지통으로(생각과 저자의 카테고리 항목만)


def row_html(row: Row, q: str = "", open_: bool = False) -> str:
    if row.title:
        head = f'<span class="t">{mark(row.title, q)}{row.badge}</span>'
        hit = "" if (q and _pattern(q, row.title)) else snippet(row.text, q)
    else:
        preview = one_line(row.preview)
        short = preview[:80] + ("…" if len(preview) > 80 else "")
        head = f'<span class="t none">{mark(short, q)}</span>'
        hit = "" if (q and _pattern(q, short)) else snippet(row.text, q)
    when = local_time(row.at, WHEN)
    return (f'<li><details id="i-{html.escape(row.id)}"{" open data-here" if open_ else ""}><summary>{head}'
            f'<time class="when" datetime="{html.escape(row.at)}">{when}</time><span class="aux">{row.aux}</span>'
            + (f'<small class="hit">{hit}</small>' if hit else "")
            + f'</summary><div class="body">{row.body}'
            f'<p class="muted"><a href="{html.escape(row.link)}">이 항목의 주소</a>'
            + (f' · <a href="{html.escape(row.link)}/edit">고치기</a> · <a href="{html.escape(row.link)}/trash">휴지통으로</a>'
               if row.actions else "")
            + "</p></div></details></li>")


def paragraphs(text: str, q: str = "") -> str:
    """여러 줄 글 → 문단(맞은 부분 표시)."""
    return "".join(f"<p>{mark(p, q).replace(chr(10), '<br>')}</p>" for p in re.split(r"\n\s*\n", text.strip()) if p.strip())


def style_tags(entry: Any) -> list[str]:
    """문체 태그 값들(호흡·시점·열기·어미·톤과 장치 목록)."""
    out: list[str] = []
    for value in entry.tags.values():
        out += [str(v) for v in value] if isinstance(value, list) else [str(value)] if value else []
    return list(dict.fromkeys(v for v in out if v.strip()))


@dataclass
class Kind:
    """목록 화면 하나(기본 카테고리 또는 저자의 카테고리)."""

    key: str  # 주소 이름: <종류>.<층 id>(ideas.book) | 카테고리 id
    name: str
    lanes: list[Lane]
    empty: str  # 빈 목록 안내
    category: Category | None = None  # 저자의 카테고리면 그 카테고리
    floor: str = COMMON  # 꽂힌 층(#93)
    base: str = ""  # 기본 카테고리면 종류(ideas|styles|refs), 저자의 카테고리면 ""


KINDS: dict[str, Kind] = {
    "ideas": Kind("ideas", "생각", ["idea_me", "idea_ai"], f'아직 쌓인 생각이 없습니다. {SAY}"생각에 기록해 줘: …"'),
    "styles": Kind("styles", "문체", ["style", "style_passage"],
                   f'아직 모은 문장이 없습니다. {SAY}"이 문장을 문체에 넣어 줘: 「…」 — 짧게 끊어 읽히는 호흡이 좋다"'),
    "refs": Kind("refs", "문헌", ["ref_bib", "ref_picked"],
                 f'아직 등록한 문헌이 없습니다. {SAY}"받은함의 kremer1993.pdf를 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …"'),
}


def category_kind(c: Category) -> Kind:
    return Kind(c.id, c.name, ["category"],
                f'아직 적은 것이 없습니다. 위에서 바로 적거나, {SAY}"{html.escape(c.name)}에 넣어 줘: …"', c, c.floor)


def builtin_kind(base: str, floor: str) -> Kind:
    """그 층에 꽂힌 기본 카테고리(#93). 주소 이름은 '<종류>.<층 id>'."""
    return replace(KINDS[base], key=f"{base}.{floor}", floor=floor, base=base)


def color_fieldset(current: str, my_colors: tuple[str, ...]) -> str:
    """책 색 고르기: 기본 색 격자 + 내 색 + 직접 고르기(색 선택기·#RRGGBB·R·G·B)."""
    current = safe_color(current, PALETTE[0][1])
    chosen = current if current in COLOR_NAMES or current in my_colors else "custom"

    def swatch(value: str, label: str) -> str:
        return (f'<label class="sw"><input type="radio" name="color" value="{value}"{" checked" if chosen == value else ""}>'
                f'<span class="chip" style="background:{value}" aria-hidden="true"></span>{html.escape(label)}</label>')

    r, g, b = (int(current[i : i + 2], 16) for i in (1, 3, 5))
    mine = "".join(swatch(c, c) for c in my_colors)
    return (
        '<fieldset><legend>책 색</legend><p class="muted">색의 뜻은 저자가 정합니다(예: 중요한 것은 빨간 책).</p>'
        f'<div class="sw-grid" role="group" aria-label="기본 색">{"".join(swatch(h, n) for n, h in PALETTE)}</div>'
        + (f'<p><b>내 색</b></p><div class="sw-grid" role="group" aria-label="내 색">{mine}</div>' if mine else "")
        + f'<div class="picker"><label class="sw"><input type="radio" name="color" value="custom"{" checked" if chosen == "custom" else ""}>'
        "직접 고르기</label>"
        f'<label>색 선택기 <input type="color" name="picker" value="{current}"></label>'
        f'<label>#RRGGBB <input name="hex" value="{current}" maxlength="7" pattern="#[0-9A-Fa-f]{{6}}" autocomplete="off"></label>'
        f'<label>R <input type="number" name="r" min="0" max="255" value="{r}"></label>'
        f'<label>G <input type="number" name="g" min="0" max="255" value="{g}"></label>'
        f'<label>B <input type="number" name="b" min="0" max="255" value="{b}"></label>'
        f'<label><input type="checkbox" name="keep" value="1"> 내 색에 저장(최대 {MAX_MY_COLORS}개)</label></div></fieldset>'
    )


def chosen_color(form: Any) -> str:
    """폼에서 고른 색 → #rrggbb. 직접 고르기면 #RRGGBB 칸을 먼저, 없으면 R·G·B 숫자를 본다. 그 밖에는 ValueError."""
    choice = str(form.get("color") or "")
    if choice == "custom":
        typed = str(form.get("hex") or "").strip()
        if HEX.fullmatch(typed):
            return typed.lower()
        try:
            values = [int(str(form.get(k) or "").strip()) for k in ("r", "g", "b")]
        except ValueError:
            values = []
        if len(values) != 3 or not all(0 <= v <= 255 for v in values):
            raise ValueError("직접 고른 색을 읽지 못했습니다. #RRGGBB(예: #b22222)나 R·G·B 숫자(0~255)로 적어 주세요.")
        return "#" + "".join(f"{v:02x}" for v in values)
    if HEX.fullmatch(choice):
        return choice.lower()
    raise ValueError("책 색을 골라 주세요.")


def edited_note(item: Any) -> str:
    """고친 적이 있으면 누가 언제 고쳤는지. 처음 쓴 사람(나·AI)은 그대로 두고 따로 보인다."""
    if not item.edited_by:
        return ""
    who = "저자가" if item.edited_by == "author" else "AI가"
    return f'<p class="muted">{who} 고침({local_time(item.edited_at or "", WHEN)})</p>'


class ShelfPages:
    """Web에 섞어 쓰는 책장 화면들. Web의 _page·user_of·_need_login·_form·_csrf_input·store를 쓴다."""

    store: Store
    _page: Callable[..., Response]
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]
    _csrf_input: Callable[[tuple[str, str]], str]
    _form: Callable[[Request, tuple[str, str]], Awaitable[Any]]
    # FloorPages(webfloors)가 구현한다
    floor_routes: Callable[[], list[tuple[str, list[str], Callable[..., Any]]]]
    location_form: Callable[[str, tuple[str, str], Kind], str]
    # BookPages(webbooks)가 구현한다
    book_routes: Callable[[], list[tuple[str, list[str], Callable[..., Any]]]]
    book_edit: Callable[[Request, str], Awaitable[Response]]
    book_trash: Callable[[Request, str], Awaitable[Response]]
    ref_register_form: Callable[[str, tuple[str, str], str], str]

    def shelf_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        # 고정 주소를 먼저 둔다(/shelf/{kind}보다 앞에서 맞아야 한다).
        return [
            *self.floor_routes(),  # 책장 전체(3D)·한 층·옮기기·되돌리기·층 만들기(webfloors)
            *self.book_routes(),  # 책 추가·원고 책·문서 책·문헌 등록(webbooks, #94)
            ("/shelf/new", ["GET", "POST"], self.shelf_new),
            ("/shelf/edit/{kind}", ["GET", "POST"], self.shelf_edit),
            ("/shelf/trash/{kind}", ["GET", "POST"], self.shelf_trash),
            ("/shelf/write/{kind}", ["POST"], self.shelf_write),
            ("/shelf/colors", ["POST"], self.shelf_colors),
            ("/shelf/{kind}", ["GET"], self.shelf_list),
            ("/shelf/{kind}/{item}", ["GET"], self.shelf_item),
            ("/shelf/{kind}/{item}/edit", ["GET", "POST"], self.shelf_item_edit),
            ("/shelf/{kind}/{item}/trash", ["GET", "POST"], self.shelf_item_trash),
            # 예전 주소(생각·문헌·문체 메뉴)는 책장의 같은 목록으로 넘긴다. 거르기 조건은 그대로 이어 간다.
            ("/ideas", ["GET"], self._moved("ideas")), ("/refs", ["GET"], self._moved("refs")),
            ("/styles", ["GET"], self._moved("styles")),
        ]

    def _moved(self, kind: str) -> Callable[[Request], Any]:
        async def moved(request: Request) -> Response:
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"/shelf/{kind}{query}", status_code=302)

        return moved

    def _shelf_page(self, title: str, body: str, session: tuple[str, str], status: int = 200) -> Response:
        return self._page(title, body, session, status, current="책장", css=SHELF_STYLE)

    def _kind(self, uid: str, key: str) -> Kind | None:
        """주소 이름 → 목록 화면. '<종류>.<층 id>'는 그 층에 그 기본 카테고리가 꽂혀 있을 때만. 예전 주소(종류만)는 None."""
        base, _, floor = key.partition(".")
        if floor and base in KINDS:
            found = self.store.get_floor(uid, floor)
            return builtin_kind(base, floor) if found and base in found.builtins else None
        if key in KINDS:
            return None
        try:
            category = self.store.get_category(uid, key)
        except ValueError:
            return None
        return category_kind(category) if category else None

    def _kind_any(self, uid: str, key: str, item: str | None = None) -> Kind | None:
        """_kind와 같되, 예전 주소 이름(ideas·styles·refs)이면 그 항목이나 종류가 꽂힌 층의 것(층 전에 연 화면의 폼·링크)."""
        if key in KINDS:
            target = self._legacy_target(uid, key, item)
            return self._kind(uid, target) if target else None
        return self._kind(uid, key)

    def _legacy_target(self, uid: str, base: str, item: str | None) -> str | None:
        """예전 주소(/shelf/ideas, /shelf/ideas/<id>)가 가리킬 지금 주소 이름: 그 항목의 층, 없으면 위에서부터 그 종류가 있는 첫 층."""
        floor = None
        if item:
            if base == "ideas":
                found = self.store.get_ideas(uid, [item]).get(item)
            elif base == "styles":
                found = self.store.get_styles(uid, [item]).get(item)
            else:
                found = self.store.get_ref(uid, item)
            floor = found.floor if found else None
        if floor is None:
            floor = next((f.id for f in self.store.list_floors(uid) if base in f.builtins), None)
        return f"{base}.{floor}" if floor else None

    # --- 책장 ---
    def books(self, uid: str, floor: str) -> list[Book]:
        """그 층에 꽂힌 책(기본 카테고리 먼저, 그다음 저자의 카테고리를 만든 순서로)."""
        from magus.book.documents import STALE_WORDS, is_stale  # noqa: PLC0415
        from magus.webbooks import MANUSCRIPT_COLOR, short_name  # noqa: PLC0415

        settings = self.store.get_shelf_settings(uid)
        found = self.store.get_floor(uid, floor)
        out = []
        if found and found.has_manuscript:  # 원고 책(#94): 그 층 자체라 옮기지 않는다
            project = self.store.get_project(uid, floor)
            chapters = len(self.store.list_chapters(uid, floor))
            out.append(Book(f"ms.{floor}", short_name(project.title), "원고", chapters, project.color or MANUSCRIPT_COLOR,
                            f"/shelf/book/{floor}", note=f"{chapters}장", label=f"원고 책 {project.title}, {chapters}장", movable=False))
        for k in found.builtins if found else ():
            items = {"ideas": self.store.list_ideas, "styles": self.store.list_styles, "refs": self.store.list_refs}[k](uid, floors=[floor])
            verified = sum(1 for r in items if r.status == "verified") if k == "refs" else None
            out.append(Book(f"{k}.{floor}", KINDS[k].name, "모음", len(items), settings.colors.get(k, DEFAULT_COLORS[k]),
                            f"/shelf/{k}.{floor}", verified))
        out += [Book(c.id, c.name, "모음", c.items, c.color, f"/shelf/{c.id}") for c in self.store.list_categories(uid, floors=[floor])]
        for d in self.store.list_documents(uid, floors=[floor]):  # 문서 책(#94): 기준 원고에 새 수정본이 오면 '옛 판 기준'
            stale = is_stale(self.store, uid, d)
            basis = f"E{d.versions[-1].edition} 기준" if d.versions[-1].edition else "기록 전"
            out.append(Book(f"doc.{d.id}", short_name(d.title), "문서", len(d.versions), d.color, f"/shelf/doc/{d.id}",
                            note="옛 판\n기준" if stale else basis, stale=stale,
                            label=f"문서 책 {d.title}, " + (STALE_WORDS if stale else basis)))
        return out

    def _done_message(self, uid: str, request: Request) -> str:
        """만들기·고치기·휴지통 뒤 책장으로 돌아왔을 때 한 줄(주소의 값을 그대로 보이지 않고 정해진 문장만)."""
        done, cid = request.query_params.get("done"), request.query_params.get("c") or ""
        try:
            category = self.store.get_category(uid, cid) if cid and "." not in cid else None
        except ValueError:
            category = None
        shown = category.name if category else BUILTINS.get(cid.partition(".")[0], "")
        if cid.startswith(("ms.", "doc.")):  # 원고 책·문서 책 이름(#94)
            ident = cid.partition(".")[2]
            book = self.store.get_project(uid, ident) if cid.startswith("ms.") else self.store.get_document(uid, ident)
            shown = book.title if book else ""
        name = f"「{html.escape(shown)}」 " if shown else ""
        what = "책" if cid.startswith(("ms.", "doc.")) else "카테고리"
        text = {"made": f"{name}카테고리를 꽂았습니다.", "edit": f"{name}{what}을(를) 고쳤습니다." if what == "책" else f"{name}카테고리를 고쳤습니다.",
                "trash": "책을 휴지통으로 옮겼습니다. 지운 것이 아니라 운영자가 되살릴 수 있습니다."}.get(done or "")
        if text and request.query_params.get("full") == "1":
            text += f" 내 색은 {MAX_MY_COLORS}개까지라 이번 색은 내 색에 넣지 못했습니다. 하나를 뺀 뒤 다시 저장하세요."
        return f'<p class="msg">{text}</p>' if text else ""

    # --- 목록 ---
    async def shelf_list(self, request: Request) -> Response:
        return await self._list(request, request.path_params["kind"], None)

    async def shelf_item(self, request: Request) -> Response:
        return await self._list(request, request.path_params["kind"], request.path_params["item"])

    async def _list(self, request: Request, kind_key: str, item: str | None) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        if kind_key.startswith(("ms.", "doc.")):  # 원고 책·문서 책은 각자의 화면(#94)
            kind_name, _, ident = kind_key.partition(".")
            return RedirectResponse(f"/shelf/{'book' if kind_name == 'ms' else 'doc'}/{urllib.parse.quote(ident)}", status_code=302)
        if kind_key in KINDS:  # 예전 주소: 그 항목·종류가 꽂힌 층의 주소로 넘긴다(#93)
            target = await run_in_threadpool(self._legacy_target, uid, kind_key, item)
            if target:
                query = f"?{request.url.query}" if request.url.query else ""
                return RedirectResponse(f"/shelf/{target}" + (f"/{urllib.parse.quote(item)}" if item else "") + query, status_code=302)
        kind = await run_in_threadpool(self._kind, uid, kind_key)
        if kind is None:
            return self._shelf_page("책장", '<p class="msg err">없는 카테고리입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>',
                                    session, 404)
        crumb = await run_in_threadpool(self._crumb, uid, kind)
        done = {"edited": "고쳤습니다.", "trashed": "항목을 휴지통으로 옮겼습니다. 지운 것이 아니라 운영자가 되살릴 수 있습니다."}.get(
            request.query_params.get("done") or "")  # 고치기·휴지통 뒤 한 줄(정해진 문장만)
        done = f'<p class="msg">{done}</p>' if done else ""
        writable = kind.base == "ideas" or kind.category is not None
        if kind.base == "refs":  # 문헌 책에 논문 파일을 넣어 확인한 문헌으로 등록하는 길(#94)
            from magus.webbooks import REGISTER_ERRORS  # noqa: PLC0415

            if text := REGISTER_ERRORS.get(request.query_params.get("registererr") or ""):
                done += f'<p class="msg err">{text}</p>'
            if request.query_params.get("done") == "registered":
                done += '<p class="msg">확인한 문헌으로 등록했습니다.</p>'
        error = request.query_params.get("error") == "empty"
        missing = (f'{crumb}<p class="msg err">없는 항목입니다(휴지통으로 옮겨졌을 수 있습니다). '
                   f'<a href="/shelf/{kind.key}">{html.escape(kind.name)} 목록</a></p>')
        if not await run_in_threadpool(self._has_any, uid, kind):  # 비어 있으면 바로 적기 폼을 펼쳐 둔다
            if item:
                return self._shelf_page(kind.name, missing, session, 404)
            summary = await run_in_threadpool(self._summary, uid, kind, {})
            write = self._write_form(session, kind, error, opened=True) if writable else ""
            return self._shelf_page(kind.name, f'{crumb}{done}{summary}{write}<p class="msg">{kind.empty}</p>', session)
        write = self._write_form(session, kind, error) if writable else ""
        params = request.query_params
        q = "" if item else clean_query(params.get("q"))
        filters = {} if item else {k: params.get(k, "") for k in ("author", "status", "tag", "project")}
        rows = await run_in_threadpool(self._rows, uid, kind, filters, q)
        page = 1
        if item:
            index = next((n for n, r in enumerate(rows) if r.id == item), None)
            if index is None:
                return self._shelf_page(kind.name, missing, session, 404)
            page = index // PAGE_SIZE + 1
        else:
            try:
                page = max(1, int(params.get("page") or 1))
            except ValueError:
                page = 1
        pages = max(1, -(-len(rows) // PAGE_SIZE))
        page = min(page, pages)
        shown = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        keep = [(k, v) for k, v in params.multi_items() if k != "page"] if not item else []

        def link(n: int, label: str) -> str:
            return f'<a href="/shelf/{kind.key}?{html.escape(urllib.parse.urlencode([*keep, ("page", n)]))}">{label}</a>'

        pager = ""
        if pages > 1:
            start = (page - 1) * PAGE_SIZE
            nav = [f"{start + 1}–{min(start + PAGE_SIZE, len(rows))} / {len(rows)}"]
            nav += [link(page - 1, "이전")] if page > 1 else []
            nav += [link(page + 1, "다음")] if page < pages else []
            pager = f'<p class="pager">{" · ".join(nav)}</p>'
        search = (f'<form method="get" action="/shelf/{kind.key}" class="search" role="search"><label>{html.escape(kind.name)}에서 찾기 '
                  f'<input type="search" name="q" value="{html.escape(q)}"></label>'
                  + "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in filters.items() if v)
                  + "<button>찾기</button></form>")
        summary = await run_in_threadpool(self._summary, uid, kind, filters)
        found = ""
        if q:
            found = (f"<p>「{html.escape(q)}」 찾은 항목 {len(rows)}개 · "
                     + ("최근 것부터(한 글자는 그 글자가 들어간 항목을 모두 찾습니다)" if one_char(q) else "많이 맞은 것부터")
                     + f' · <a href="/shelf/{kind.key}">검색 지우기</a></p>')
        board = (f'<ol class="board">{"".join(row_html(r, q, r.id == item) for r in shown)}</ol>'
                 if shown else '<p class="msg">찾는 말이 들어간 항목이 없습니다.</p>' if q else '<p class="msg">없음</p>')
        if kind.base == "refs":
            write = await run_in_threadpool(self.ref_register_form, uid, session, kind.floor)
        body = f"{crumb}{done}{summary}{search}{write}{found}{pager}{board}{pager}" + (SCROLL_SCRIPT if item else "")
        return self._shelf_page(kind.name, body, session)

    def _crumb(self, uid: str, kind: Kind) -> str:
        """'← 책장 · 1층' — 책장 전체와 그 카테고리가 꽂힌 층으로 돌아가는 길."""
        floor = self.store.get_floor(uid, kind.floor)
        where = f' · <a href="/shelf/floor/{html.escape(kind.floor)}">{floor.label}</a>' if floor else ""
        return f'<p class="crumb"><a href="/shelf">← 책장</a>{where}</p>'

    def _has_any(self, uid: str, kind: Kind) -> bool:
        if kind.category is not None:
            return bool(self.store.list_category_items(uid, kind.category.id))
        return bool({"ideas": self.store.list_ideas, "styles": self.store.list_styles, "refs": self.store.list_refs}[kind.base](
            uid, floors=[kind.floor]))

    def _summary(self, uid: str, kind: Kind, filters: dict[str, str]) -> str:
        """목록 위 한 줄: 개수와 거르기 링크(기존 화면과 같은 거르기), 그리고 이름·색 바꾸기."""
        edit = f' · <a href="/shelf/edit/{kind.key}">{"이름·색 바꾸기" if kind.category else "책 색 바꾸기"}</a>'
        if kind.category is not None:
            c = kind.category
            items = self.store.list_category_items(uid, c.id)
            mine = sum(1 for i in items if i.author == "me")
            template = TEMPLATE_BY_KEY.get(c.template)
            base = f"/shelf/{c.id}"
            return (f"<p>{html.escape(c.name)} {len(items)}개" + (f"(나 {mine} · AI {len(items) - mine})" if items else "") + " · "
                    f"{html.escape(template.name if template else c.template)} 템플릿{edit}"
                    f' · <a href="/shelf/trash/{c.id}">휴지통으로</a></p>'
                    + (f'<p><a href="{base}">전체</a> · <a href="{base}?author=me">나</a> · <a href="{base}?author=ai">AI</a></p>'
                       if items else ""))
        here = f"/shelf/{kind.key}"
        if kind.base == "ideas":
            ideas = self.store.list_ideas(uid, floors=[kind.floor])
            mine = sum(1 for i in ideas if i.author == "me")
            if not ideas:
                return f"<p>생각 0개{edit}</p>"
            return (f"<p>생각 {len(ideas)}개(나 {mine} · AI {len(ideas) - mine}) · "
                    f'<a href="{here}">전체</a> · <a href="{here}?author=me">나</a> · '
                    f'<a href="{here}?author=ai">AI</a>{edit}</p>')
        if kind.base == "styles":
            tag = filters.get("tag", "")
            only = f' · 태그 「{html.escape(tag)}」만 · <a href="{here}">전체</a>' if tag else ""
            return f"<p>문장 {len(self.store.list_styles(uid, floors=[kind.floor]))}개{only}{edit}</p>"
        refs = self.store.list_refs(uid, floors=[kind.floor])
        verified = sum(1 for r in refs if r.status == "verified")
        project = self._ref_project(uid, kind, filters)
        q = f"project={urllib.parse.quote(project.id)}&" if project else ""
        checklist = f' · 인용 현황은 <a href="/checklist?{q}">인용 체크리스트</a>' if project else ""
        return (f"<p>문헌 확인 {verified}편 · 전체 {len(refs)}편(미확인 {len(refs) - verified}편){checklist}{edit}</p>"
                f'<p><a href="{here}?{q}">전체</a> · <a href="{here}?{q}status=verified">{LIGHTS["verified"][0]} '
                f'{LIGHTS["verified"][1]}</a> · <a href="{here}?{q}status=unverified">{LIGHTS["unverified"][0]} '
                f'{LIGHTS["unverified"][1]}</a></p>')

    def _ref_project(self, uid: str, kind: Kind, filters: dict[str, str]) -> Any:
        """'인용된 장'을 셀 작업물: 주소의 project, 없으면 그 문헌이 꽂힌 작업물 층, 공용이면 최근 작업물."""
        wanted = filters.get("project") or (kind.floor if kind.floor != COMMON else None)
        return self.store.get_project(uid, wanted) or self.store.get_project(uid)

    def _rows(self, uid: str, kind: Kind, filters: dict[str, str] | None, q: str) -> list[Row]:
        """그 카테고리의 줄들. 검색어가 있으면 맞은 것만 검색 순서로, 없으면 기본 순서(문헌은 확인한 것부터, 나머지는 최근 것부터)."""
        filters = filters or {}
        if kind.category is not None:
            pairs = self._category_rows(uid, kind.category, filters, q)
        else:
            build = {"ideas": self._idea_rows, "styles": self._style_rows, "refs": self._ref_rows}[kind.base]
            pairs = build(uid, kind, filters, q)
        if not q:
            return [row for _, row in pairs]
        owners = find(self.store, uid, kind.lanes, q)
        if kind.category is not None:  # 카테고리 항목의 owner_id는 "<카테고리 id>/<항목 id>"
            owners = [o.split("/", 1)[1] for o in owners if o.startswith(f"{kind.category.id}/")]
        order = {owner: n for n, owner in enumerate(owners)}
        return [row for owner, row in sorted((p for p in pairs if p[0] in order), key=lambda p: order[p[0]])]

    def _idea_rows(self, uid: str, kind: Kind, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        ideas = list(reversed(self.store.list_ideas(uid, floors=[kind.floor])))
        author = filters.get("author") if filters.get("author") in ("me", "ai") else None
        rows = []
        for i in ideas:
            if author and i.author != author:
                continue
            who = "나" if i.author == "me" else '<span class="tag">AI</span>'
            back = (f'<p class="muted">AI의 답입니다. <a href="/shelf/ideas/{html.escape(i.parent_id)}">응답한 생각</a></p>'
                    if i.parent_id else "")  # 예전 주소 모양: 응답한 생각이 어느 층에 있든 그 층으로 넘어간다
            origin = f'<p class="muted">출처: {html.escape(i.origin)}</p>' if i.origin else ""
            by = '<p class="muted">제목은 AI가 지었습니다.</p>' if i.title and i.title_by == "ai" else ""
            rows.append((i.id, Row(i.id, f"/shelf/{kind.key}/{i.id}", i.created_at, i.title, i.text, who,
                                   paragraphs(i.text, q) + origin + back + by + edited_note(i), i.text,
                                   AI_TITLE if i.title and i.title_by == "ai" else "", True)))
        return rows

    def _style_rows(self, uid: str, kind: Kind, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        tag = (filters.get("tag") or "").strip()
        rows = []
        for s in reversed(self.store.list_styles(uid, floors=[kind.floor])):
            tags = style_tags(s)
            if tag and tag not in tags:
                continue
            head = one_line(s.passage)
            title = f"「{head[:48]}{'…' if len(head) > 48 else ''}」"
            aux = " ".join([*([html.escape(s.work)] if s.work else []),
                            *(f'<span class="tag">{html.escape(t)}</span>' for t in tags[:2]),
                            *([f"외 {len(tags) - 2}"] if len(tags) > 2 else [])])
            pills = " ".join(f'<a class="tag" href="/shelf/{kind.key}?tag={urllib.parse.quote(t)}">{html.escape(t)}</a>' for t in tags)
            by = TAGS_BY.get(s.tags_by or "")  # 태그를 누가 정했나(#89). 기록 전 항목은 표시하지 않는다
            body = (f"<p>「{mark(s.passage, q).replace(chr(10), '<br>')}」</p>"
                    + (f'<p class="muted">출처: {mark(s.work, q)}</p>' if s.work else "")
                    + f"<p>이유: {mark(s.reason, q)}</p><p>{pills}</p>" + (f'<p class="muted">{by}</p>' if by else ""))
            rows.append((s.id, Row(s.id, f"/shelf/{kind.key}/{s.id}", s.created_at, title, s.passage, aux, body,
                                   f"{s.passage}\n{s.work or ''}\n{s.reason}")))
        return rows

    def _ref_rows(self, uid: str, kind: Kind, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        status = filters.get("status") if filters.get("status") in ("verified", "unverified") else None
        project = self._ref_project(uid, kind, filters)
        cited: dict[str, list[str]] = {}
        if project is not None:
            report = build_cite_report(self.store, uid, project.id)
            cited = {key: list(dict.fromkeys(d.chapters)) for key, d in report.docs.items()}
        refs = sorted((r for r in self.store.list_refs(uid, floors=[kind.floor]) if status is None or r.status == status),
                      key=lambda r: (r.status != "verified", r.key))
        rows = []
        for r in refs:
            light, word = LIGHTS[r.status]
            chapters = cited.get(r.key, [])
            aux = f"{light} {word}" + (f" · 인용된 장 {len(chapters)}" if chapters else "")
            passages = self.store.get_passages(uid, r.key)
            body = "".join([
                *([f'<p class="muted">{mark(str(r.bib.get("container")), q)}</p>'] if r.bib.get("container") else []),
                *([f'<p class="muted">서지: {mark(str(r.bib.get("authors") or r.bib.get("raw") or ""), q)}</p>']
                  if r.bib.get("authors") or r.bib.get("raw") else []),
                *(f'<p>「{mark(p.text, q)}」<br><span class="muted">{html.escape(p.reason)}'
                  + (f" · {html.escape(p.locator)}" if p.locator else "") + "</span></p>" for p in passages),
                f"<p>인용된 장: {html.escape(chapters_text(chapters) or '-')}</p>",
                *([f'<p class="muted">한글 표기: {html.escape(", ".join(r.aliases))}</p>'] if r.aliases else []),
                *([f'<p class="muted">공용으로 옮김({local_time(r.moved.get("at", ""), WHEN)}): {html.escape(r.moved.get("reason", ""))}</p>']
                  if r.moved and r.moved.get("to") == r.floor else []),  # 저자 모르게 배치가 바뀌지 않게(#93-a 더함)
            ])
            text = "\n".join([str(r.bib.get("authors") or ""), str(r.bib.get("container") or ""), *(p.text for p in passages)])
            rows.append((r.key, Row(r.key, f"/shelf/{kind.key}/{urllib.parse.quote(r.key)}", r.created_at, cite_label(r, r.key),
                                    "", aux, body, text)))
        return rows

    def _category_rows(self, uid: str, category: Category, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        author = filters.get("author") if filters.get("author") in ("me", "ai") else None
        tag = (filters.get("tag") or "").strip()
        names: dict[str, dict[int, str]] = {}

        def chapter_name(project: str, number: int) -> str:
            if project not in names:
                try:
                    names[project] = {c.number: c.display for c in self.store.list_chapters(uid, project)}
                except ValueError:
                    names[project] = {}
            return names[project].get(number, f"{number}(없는 장)")

        rows = []
        for i in reversed(self.store.list_category_items(uid, category.id)):
            if (author and i.author != author) or (tag and tag not in i.tags):
                continue
            chapters = [chapter_name(p, n) for p, n in i.chapters]
            aux = " ".join(["나" if i.author == "me" else '<span class="tag">AI</span>',
                            *(f'<span class="tag">{html.escape(t)}</span>' for t in i.tags[:2]),
                            *([html.escape(", ".join(chapters))] if chapters else [])])
            fields = "".join(f"<dt>{html.escape(k)}</dt><dd>{mark(v, q)}</dd>" for k, v in i.fields.items() if v)
            pills = " ".join(f'<a class="tag" href="/shelf/{category.id}?tag={urllib.parse.quote(t)}">{html.escape(t)}</a>' for t in i.tags)
            body = (paragraphs(i.content, q)
                    + (f'<dl class="fields">{fields}</dl>' if fields else "")
                    + (f"<p>{pills}</p>" if pills else "")
                    + (f"<p>연결된 장: {html.escape(', '.join(chapters))}</p>" if chapters else "")
                    + f'<p class="muted">누가: {"저자의 말" if i.author == "me" else "Claude가 쓴 글"}'
                    + (" · 제목은 AI가 지었습니다." if i.title and i.title_by == "ai" else "") + "</p>" + edited_note(i))
            text = "\n".join([i.content, *(f"{k} {v}" for k, v in i.fields.items()), " ".join(i.tags)])
            preview = i.content or " · ".join(f"{k}: {v}" for k, v in i.fields.items() if v)  # 내용이 없으면 채워진 칸
            rows.append((i.id, Row(i.id, f"/shelf/{category.id}/{i.id}", i.created_at, i.title, preview, aux, body, text,
                                   AI_TITLE if i.title and i.title_by == "ai" else "", True)))
        return rows

    # --- 바로 적기(생각·저자의 카테고리) ---
    def _write_form(self, session: tuple[str, str], kind: Kind, error: bool, opened: bool = False) -> str:
        fields = kind.category.fields if kind.category else ()
        extra = "".join(f'<label class="block">{html.escape(f)} <input name="f:{html.escape(f)}" maxlength="{FIELD_MAX}"></label>'
                        for f in fields)
        return (
            f'<details class="card write"{" open" if error or opened else ""}><summary>새로 적기</summary>'
            + (f'<p class="msg err">{EMPTY_IDEA if kind.category is None else EMPTY_ITEM}</p>' if error else "")
            + f'<form method="post" action="/shelf/write/{kind.key}">{self._csrf_input(session)}'
            f'<label class="block">제목(비워 둬도 됩니다) <input name="title" maxlength="{TITLE_MAX}"></label>'
            f'<label class="block">내용 <textarea name="content" rows="6" maxlength="{CONTENT_MAX}"'
            f'{" required" if kind.category is None else ""}></textarea></label>'
            + (f"<details><summary>칸 더 적기(선택)</summary>{extra}</details>" if extra else "")
            + '<p><button class="primary">적어 두기</button> 적은 사람은 저자(나)로 남습니다.</p></form></details>'
        )

    async def shelf_write(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._shelf_page("책장", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        kind = await run_in_threadpool(self._kind_any, uid, request.path_params["kind"])
        if kind is None or not (kind.base == "ideas" or kind.category is not None):
            return self._shelf_page("책장", '<p class="msg err">여기에는 바로 적을 수 없습니다.</p>', session, 404)
        content = str(form.get("content") or "").strip()[:CONTENT_MAX]
        title = one_line(str(form.get("title") or ""))[:TITLE_MAX] or None
        values = {f: one_line(str(form.get(f"f:{f}") or ""))[:FIELD_MAX] for f in (kind.category.fields if kind.category else ())}
        if not content and (kind.category is None or not (title or any(values.values()))):
            return RedirectResponse(f"/shelf/{kind.key}?error=empty", status_code=303)
        if kind.category is None:  # 생각(저자가 직접 적음)
            [idea] = await run_in_threadpool(self.store.add_ideas, uid, [
                Idea(new_id(), content, "thought", "me", title=title, title_by="author" if title else None, floor=kind.floor)])
            return RedirectResponse(f"/shelf/{kind.key}/{idea.id}", status_code=303)
        item = await run_in_threadpool(self.store.put_category_item, uid, CategoryItem(
            new_id(), kind.category.id, content, "me", title, "author" if title else None, {k: v for k, v in values.items() if v}))
        return RedirectResponse(f"/shelf/{kind.category.id}/{item.id}", status_code=303)

    # --- 카테고리 만들기·고치기·휴지통 ---
    async def shelf_new(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        mine = await run_in_threadpool(self.store.list_categories, uid)
        settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        default_color = PALETTE_BY_NAME[NEW_COLOR_ORDER[len(mine) % len(NEW_COLOR_ORDER)]]
        values = {"name": "", "template": "blank", "color": default_color}
        error = ""
        # 꽂을 층(#93): 한 층 화면의 '카테고리 추가'에서 온 층, 없으면 공용
        floor = await run_in_threadpool(self.store.get_floor, uid, request.query_params.get("floor") or COMMON)
        floor = floor or await run_in_threadpool(self.store.get_floor, uid, COMMON)
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("모음 책 만들기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            values = {"name": str(form.get("name") or ""), "template": str(form.get("template") or "blank"),
                      "color": safe_color(str(form.get("hex") or ""), default_color)}
            try:
                if len(mine) >= MAX_CATEGORIES:
                    raise ValueError(f"카테고리는 {MAX_CATEGORIES}개까지 만들 수 있습니다.")
                name = check_name(values["name"], {name_key(c.name): c.name for c in mine if c.floor == floor.id})
                template = TEMPLATE_BY_KEY.get(values["template"])
                if template is None:
                    raise ValueError("템플릿을 골라 주세요.")
                color = chosen_color(form)
                values["color"] = color
                made = await run_in_threadpool(self.store.create_category, uid, name, template.key, color,
                                               tuple(f for f, _ in template.fields), floor.id)
                note = await run_in_threadpool(self._keep_color, uid, form, color)
                return RedirectResponse(f"/shelf/floor/{floor.id}?done=made&c={made.id}" + note, status_code=303)
            except ValueError as e:
                error = f'<p class="msg err">{html.escape(str(e))}</p>'
        templates = "".join(
            f'<label class="tpl"><input type="radio" name="template" value="{t.key}"{" checked" if t.key == values["template"] else ""}>'
            f'<span><b>{html.escape(t.name)}</b> — {html.escape(t.about)} <span class="muted">'
            + (f"(칸: {' · '.join(f for f, _ in t.fields)})" if t.fields else "(제목·내용만)") + "</span></span></label>"
            for t in TEMPLATES
        )
        preview = shelf_html([book_html(Book("preview", values["name"] or "새 카테고리", "일반", 0, values["color"], None))])
        where = floor.label if floor.common else f"{floor.label} 「{floor.title}」"
        body = (
            f'<p class="crumb"><a href="/shelf">← 책장</a> · <a href="/shelf/floor/{html.escape(floor.id)}">{floor.label}</a></p>{error}'
            f'<p>꽂을 층: <b>{html.escape(where)}</b></p>'
            f'<form method="post" action="/shelf/new?floor={urllib.parse.quote(floor.id)}" class="colors">{self._csrf_input(session)}'
            f'<label class="block">이름(12자까지) <input name="name" value="{html.escape(values["name"])}" maxlength="12" required></label>'
            '<p class="muted">생각·문체·문헌·원고·전체·확인 요청처럼 정해진 이름과, 이미 있는 이름은 쓸 수 없습니다.</p>'
            f"<fieldset><legend>템플릿</legend>{templates}</fieldset>"
            + color_fieldset(values["color"], settings.my_colors)
            + f'<div class="preview"><p><b>미리보기</b></p>{preview}</div>'
            f'<p><button class="primary">책장에 꽂기</button> <a href="/shelf/floor/{html.escape(floor.id)}">그만두기</a></p></form>'
            + COLOR_SCRIPT
        )
        return self._shelf_page("모음 책 만들기", body, session, 400 if error else 200)

    def _keep_color(self, uid: str, form: Any, color: str) -> str:
        """'내 색에 저장'을 골랐으면 내 색에 더한다(기본 색 격자에 있는 색은 더하지 않는다). 다 찼으면 주소에 표시만 남긴다."""
        if form.get("keep") != "1" or color in COLOR_NAMES:
            return ""
        settings = self.store.get_shelf_settings(uid)
        if color in settings.my_colors:
            return ""
        if len(settings.my_colors) >= MAX_MY_COLORS:
            return "&full=1"
        self.store.save_shelf_settings(uid, ShelfSettings(settings.colors, (*settings.my_colors, color), settings.title_default))
        return ""

    async def shelf_edit(self, request: Request) -> Response:
        if request.path_params["kind"].startswith(("ms.", "doc.")):  # 원고 책·문서 책 설정(#94)
            return await self.book_edit(request, request.path_params["kind"])
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        kind = await run_in_threadpool(self._kind_any, uid, request.path_params["kind"])
        if kind is None:
            return self._shelf_page("책장", '<p class="msg err">없는 카테고리입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>', session, 404)
        settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        current = kind.category.color if kind.category else settings.colors.get(kind.base, DEFAULT_COLORS[kind.base])
        name, error = kind.name, ""
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("카테고리 고치기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            name = str(form.get("name") or kind.name)
            current = safe_color(str(form.get("hex") or ""), current)
            try:
                color = chosen_color(form)
                current = color
                if kind.category is None:  # 기본 카테고리: 색만(색은 종류마다 하나라 모든 층의 같은 기본 카테고리가 바뀐다)
                    await run_in_threadpool(self.store.save_shelf_settings, uid, ShelfSettings(
                        {**settings.colors, kind.base: color}, settings.my_colors, settings.title_default))
                else:
                    taken = {name_key(c.name): c.name for c in self.store.list_categories(uid, floors=[kind.floor])
                             if c.id != kind.category.id}
                    clean = check_name(name, taken) if name_key(name) != name_key(kind.category.name) else None
                    await run_in_threadpool(lambda: self.store.update_category(uid, kind.category.id, name=clean, color=color))
                note = await run_in_threadpool(self._keep_color, uid, form, color)
                return RedirectResponse(f"/shelf/floor/{kind.floor}?done=edit&c={kind.key}" + note, status_code=303)
            except ValueError as e:
                error = f'<p class="msg err">{html.escape(str(e))}</p>'
            settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        count = len(await run_in_threadpool(self._count_rows, uid, kind))
        band = ("기본" if kind.category is None else
                TEMPLATE_BY_KEY[kind.category.template].band if kind.category.template in TEMPLATE_BY_KEY else "일반")
        preview = shelf_html([book_html(Book(kind.key, name, band, count, current, None))])
        name_field = (f'<label class="block">이름(12자까지) <input name="name" value="{html.escape(name)}" maxlength="12" required></label>'
                      if kind.category else '<p class="muted">기본 카테고리라 이름은 바꿀 수 없습니다. 책 색만 바꿀 수 있습니다.</p>')
        mine = "".join(
            f'<li><span class="chip" style="background:{c}" aria-hidden="true"></span>{c}'
            f'<form method="post" action="/shelf/colors" class="inline">{self._csrf_input(session)}'
            f'<input type="hidden" name="remove" value="{c}"><input type="hidden" name="next" value="/shelf/edit/{kind.key}">'
            f'<button aria-label="내 색 {c} 빼기">빼기</button></form></li>'
            for c in settings.my_colors
        )
        trash = (f'<h2>휴지통</h2><p><a href="/shelf/trash/{kind.key}">이 카테고리를 휴지통으로 옮기기</a></p>' if kind.category else "")
        place = await run_in_threadpool(self.location_form, uid, session, kind)  # 위치(#93, webfloors)
        body = (
            f'<p class="crumb"><a href="/shelf/{kind.key}">← {html.escape(kind.name)}</a></p>{error}'
            f'<form method="post" action="/shelf/edit/{kind.key}" class="colors">{self._csrf_input(session)}{name_field}'
            + color_fieldset(current, settings.my_colors)
            + f'<div class="preview"><p><b>미리보기</b></p>{preview}</div>'
            f'<p><button class="primary">저장</button> <a href="/shelf/{kind.key}">그만두기</a></p></form>'
            + (f'<h2>내 색</h2><ul class="mycolors">{mine}</ul>' if mine else "") + place + trash + COLOR_SCRIPT
        )
        title = f"{kind.name} — {'이름·색 바꾸기' if kind.category else '책 색 바꾸기'}"
        return self._shelf_page(title, body, session, 400 if error else 200)

    def _count_rows(self, uid: str, kind: Kind) -> list[Any]:
        if kind.category is not None:
            return self.store.list_category_items(uid, kind.category.id)
        return {"ideas": self.store.list_ideas, "styles": self.store.list_styles, "refs": self.store.list_refs}[kind.base](
            uid, floors=[kind.floor])

    async def shelf_colors(self, request: Request) -> Response:
        """내 색 빼기."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._shelf_page("책장", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        remove = str(form.get("remove") or "").lower()
        settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        await run_in_threadpool(self.store.save_shelf_settings, uid, ShelfSettings(
            settings.colors, tuple(c for c in settings.my_colors if c != remove), settings.title_default))
        nxt = str(form.get("next") or "/shelf")
        return RedirectResponse(nxt if re.fullmatch(r"/shelf(/[A-Za-z0-9_/-]*)?", nxt) else "/shelf", status_code=303)

    async def shelf_trash(self, request: Request) -> Response:
        if request.path_params["kind"].startswith(("ms.", "doc.")):  # 원고 책·문서 책 휴지통(#94)
            return await self.book_trash(request, request.path_params["kind"])
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        key = request.path_params["kind"]
        if key.partition(".")[0] in BUILTINS:
            return self._shelf_page("책장", '<p class="msg err">기본 카테고리(생각·문체·문헌)는 휴지통으로 옮길 수 없습니다.</p>', session, 400)
        kind = await run_in_threadpool(self._kind, uid, key)
        if kind is None or kind.category is None:
            return self._shelf_page("책장", '<p class="msg err">없는 카테고리입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>', session, 404)
        category = kind.category
        if request.method == "POST":
            try:
                await self._form(request, session)
            except PermissionError:
                return self._shelf_page("휴지통으로", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            await run_in_threadpool(self.store.trash_category, uid, category.id, "웹 책장에서 옮김")
            return RedirectResponse(f"/shelf/floor/{category.floor}?done=trash", status_code=303)
        body = (
            f'<p class="crumb"><a href="/shelf/{category.id}">← {html.escape(category.name)}</a></p>'
            f'<div class="card"><p>「{html.escape(category.name)}」 카테고리를 휴지통으로 옮길까요?</p>'
            f"<p>항목 {category.items}개가 함께 옮겨집니다. 지우는 것이 아니라 옮기는 것이라 운영자가 되살릴 수 있습니다.</p>"
            f'<form method="post" action="/shelf/trash/{category.id}">{self._csrf_input(session)}'
            f'<p><button>휴지통으로 옮기기</button> <a href="/shelf/{category.id}">그만두기</a></p></form></div>'
        )
        return self._shelf_page("휴지통으로", body, session)

    # --- 항목 고치기·휴지통(생각과 저자의 카테고리 항목. 자기 책장 안에서만, CSRF, 휴지통은 확인 한 번) ---
    def _editable(self, uid: str, kind_key: str, item_id: str) -> tuple[Kind, Any] | None:
        kind = self._kind_any(uid, kind_key, item_id)
        if kind is None or not (kind.base == "ideas" or kind.category is not None):
            return None
        try:
            if kind.category is not None:
                item = self.store.get_category_item(uid, kind.category.id, item_id)
            else:
                item = self.store.get_ideas(uid, [item_id]).get(item_id)
                item = item if item is not None and item.floor == kind.floor else None
        except ValueError:
            return None
        return (kind, item) if item is not None else None

    async def shelf_item_edit(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        found = await run_in_threadpool(self._editable, uid, request.path_params["kind"], request.path_params["item"])
        if found is None:
            return self._shelf_page("책장", '<p class="msg err">고칠 수 있는 항목이 아닙니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>',
                                    session, 404)
        kind, item = found
        link = f"/shelf/{kind.key}/{item.id}"
        is_idea = kind.category is None
        old_text = item.text if is_idea else item.content
        error = ""
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("항목 고치기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            content = str(form.get("content") or "").strip()[:CONTENT_MAX]
            title = one_line(str(form.get("title") or ""))[:TITLE_MAX] or None
            values = {f: one_line(str(form.get(f"f:{f}") or ""))[:FIELD_MAX] for f in (() if is_idea else kind.category.fields)}
            if content or (not is_idea and (title or any(values.values()))):
                # 제목을 그대로 두면 누가 지었는지도 그대로, 저자가 새로 적으면 저자가 지은 제목, 지우면 없음
                title_by = item.title_by if title == item.title else ("author" if title else None)
                now = utcnow()
                if is_idea:
                    await run_in_threadpool(self.store.add_ideas, uid, [replace(
                        item, text=content, title=title, title_by=title_by, edited_at=now, edited_by="author")])
                else:
                    await run_in_threadpool(self.store.put_category_item, uid, replace(
                        item, content=content, title=title, title_by=title_by, fields={k: v for k, v in values.items() if v},
                        edited_at=now, edited_by="author"))
                return RedirectResponse(f"{link}?done=edited", status_code=303)
            error = f'<p class="msg err">{EMPTY_IDEA if is_idea else EMPTY_ITEM}</p>'
            old_text = content
        fields = "" if is_idea else "".join(
            f'<label class="block">{html.escape(f)} <input name="f:{html.escape(f)}" value="{html.escape(item.fields.get(f, ""))}" '
            f'maxlength="{FIELD_MAX}"></label>' for f in kind.category.fields)
        who = ('<p class="muted">처음 쓴 사람: Claude(AI). 고치면 "저자가 고침"으로 함께 남습니다.</p>' if item.author == "ai"
               else "")
        body = (
            f'<p class="crumb"><a href="{link}">← {html.escape(kind.name)}</a></p>{error}{who}'
            f'<form method="post" action="{link}/edit" class="card">{self._csrf_input(session)}'
            f'<label class="block">제목(비워 둬도 됩니다) <input name="title" value="{html.escape(item.title or "")}" maxlength="{TITLE_MAX}"></label>'
            f'<label class="block">내용 <textarea name="content" rows="8" maxlength="{CONTENT_MAX}"{" required" if is_idea else ""}>'
            f'{html.escape(old_text)}</textarea></label>'
            f'{fields}<p><button class="primary">저장</button> <a href="{link}">그만두기</a></p></form>'
        )
        return self._shelf_page("항목 고치기", body, session, 400 if error else 200)

    async def shelf_item_trash(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        found = await run_in_threadpool(self._editable, uid, request.path_params["kind"], request.path_params["item"])
        if found is None:
            return self._shelf_page("책장", '<p class="msg err">옮길 수 있는 항목이 아닙니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>',
                                    session, 404)
        kind, item = found
        link = f"/shelf/{kind.key}/{item.id}"
        is_idea = kind.category is None
        if request.method == "POST":
            try:
                await self._form(request, session)
            except PermissionError:
                return self._shelf_page("휴지통으로", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            if is_idea:
                await run_in_threadpool(self.store.trash_idea, uid, item.id, "웹 책장에서 옮김")
            else:
                await run_in_threadpool(self.store.trash_category_item, uid, kind.category.id, item.id, "웹 책장에서 옮김")
            return RedirectResponse(f"/shelf/{kind.key}?done=trashed", status_code=303)
        replies = (sum(1 for i in await run_in_threadpool(self.store.list_ideas, uid) if i.parent_id == item.id) if is_idea else 0)
        preview = one_line(item.title or (item.text if is_idea else item.content))
        body = (
            f'<p class="crumb"><a href="{link}">← {html.escape(kind.name)}</a></p>'
            f'<div class="card"><p>이 항목을 휴지통으로 옮길까요?</p><p><b>{html.escape(preview[:80])}{"…" if len(preview) > 80 else ""}</b></p>'
            + (f"<p>이 생각에 응답한 AI 발화 {replies}건도 함께 옮겨집니다.</p>" if replies else "")
            + "<p>지우는 것이 아니라 옮기는 것이라 운영자가 되살릴 수 있습니다.</p>"
            f'<form method="post" action="{link}/trash">{self._csrf_input(session)}'
            f'<p><button>휴지통으로 옮기기</button> <a href="{link}">그만두기</a></p></form></div>'
        )
        return self._shelf_page("휴지통으로", body, session)
