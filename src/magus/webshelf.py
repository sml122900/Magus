"""웹 책장(2026-10-06, #92 → #96): 노드에 꽂힌 책을 양장본으로 보이고, 책을 누르면 게시판형 목록
(한 줄 = 제목 · 작성 시각 · 보조 정보, 누르면 그 자리에서 펼침)과 검색이 열린다.

#96(종류를 없애고 컨텍스트로): 책에는 종류가 없다. 모든 책이 같은 게시판(글 + 그 책의 문헌 글)이고, 책등 위 띠에는 컨텍스트 이름
(첫 것 + '외 N', 없으면 빈 띠)이 보인다. 게시판 머리에 컨텍스트(누르면 전문)가 있고, 만들기·설정 화면에서 단추로 붙이고 고친다
(magus.webcontexts). 옛 주소(/shelf/ideas…, ideas.<프로젝트>)는 이전으로 생긴 책(<종류>-<프로젝트>)으로 넘긴다.

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
- 프로젝트(#93 층 → #95): 기본 책은 프로젝트마다 따로 있으므로 주소 이름이 "<종류>.<프로젝트 id>"다(ideas.book, styles.common).
  저자의 카테고리는 id 그대로. 예전 주소(/shelf/ideas, /shelf/ideas/<id>)는 그 항목·종류가 있는 프로젝트의 주소로 넘긴다.
  프로젝트 목록·지도·노드의 책장(패널)·옮기기·되돌리기는 magus.webmap에 있다. 여기의 목록 화면은 패널 안에 게시판으로 뜬다.
"""

from __future__ import annotations

import contextvars
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

from magus.book_migrate import legacy_book_id
from magus.contexts import band as context_band
from magus.contexts import view_for_book
from magus.floors import COMMON
from magus.category.rules import (
    BUILTINS, COLOR_NAMES, CONTENT_MAX, FIELD_MAX, HEX, MAX_CATEGORIES, MAX_MY_COLORS, NEW_COLOR_ORDER,
    PALETTE, PALETTE_BY_NAME, TEMPLATE_BY_KEY, TEMPLATES, TITLE_MAX, check_name, name_key,
)
from magus.ids import local_time, new_id, utcnow
from magus.melchior.author_report import chapters_text, cite_label
from magus.melchior.report import build_cite_report
from magus.store import Category, CategoryItem, ShelfSettings, Store
from magus.webcontexts import CONTEXT_SCRIPT, CONTEXT_STYLE, context_fieldset, contexts_from_form, contexts_view_html, register_row
from magus.store.base import Lane
from magus.store.formats import one_line
from magus.textindex import match_query, tokens

PAGE_SIZE = 100  # 목록 한 쪽
GROUP_SIZE = 5  # 책장 전체 검색에서 카테고리마다 먼저 보이는 수
PER_SHELF = 6  # 선반 한 칸에 꽂는 책 수(넘으면 선반이 하나 늘어난다). 노드의 책장은 옆 패널이라 한 줄 여섯 권
SEARCH_LIMIT = 500
WHEN = "%Y-%m-%d %H:%M"
LIGHTS = {"verified": ("🟢", "원문 확인"), "unverified": ("🟡", "원문 확인 전")}
TAGS_BY = {"ai": "AI가 뽑은 태그", "author": "저자가 정한 태그"}
SAY = "Claude에게 이렇게 말하면 쌓입니다. 예: "
LIGHT_TEXT, DARK_TEXT = "#ffffff", "#1a1a1a"
AI_TITLE = '<span class="tag">AI가 지은 제목</span>'
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
    """책장에 꽂힌 책 하나(#96: 종류 없음). 글이 쌓이는 책(카테고리), 올린 원고가 든 책, 원고에서 만든 문서."""

    key: str  # 주소에 쓰는 이름: 카테고리 id | ms.<작업물 id> | doc.<문서 id>
    name: str
    band: str  # 위쪽 띠: 컨텍스트 이름(첫 것 + '외 N', #96). 없으면 빈 띠
    count: int
    color: str
    href: str | None  # None이면 누를 수 없는 미리보기
    # 문헌만: 원문을 확인한 편수. 책등 아래를 "확인 n · 전체 m" 두 줄로 보인다(두께는 전체 수 기준 그대로).
    # 문헌 수에는 원고 참고문헌에서 들여온 미확인 항목도 들어 있어, 전체만 보이면 '원문을 읽고 등록한 책'으로 오해한다.
    verified: int | None = None
    note: str | None = None  # 아래 띠 글(줄바꿈은 두 줄). 원고 책 "N장", 문서 책 "E2 기준"·"옛 판 기준"
    label: str | None = None  # 낭독기 이름(없으면 "이름, 항목 N개")
    movable: bool = True  # 끌어 옮길 수 있나(원고 책은 가운데 노드 자체라 옮기지 않는다)
    stale: bool = False  # 문서 책: 기준 원고에 새 수정본이 왔다


def color_style(color: str) -> str:
    """책등 색과 그 위 글자색 변수(큰 책·책장 전체의 작은 책이 함께 쓴다)."""
    color = safe_color(color, "#3b4652")
    fg = text_color(color)
    light_text = fg == LIGHT_TEXT or fg == "#ffffff"
    return (f"--c:{color};--fg:{fg};--fgrgb:{' '.join(str(int(fg[i:i + 2], 16)) for i in (1, 3, 5))};"
            f"--away:{'0 0 0' if light_text else '255 255 255'};--glow:{0 if light_text else .14};")


def key_jitter(key: str, spread: int) -> int:
    """책마다 조금 다른 높이(주소 이름의 해시라 같은 책은 언제나 같다)."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:4], 16) % spread


# 지도 화면(#95): 책을 열면 그 책 화면이 패널의 게시판 자리(iframe)에 뜬다. 패널 안의 요청은 머리(메뉴) 없이 그린다.
EMBED: contextvars.ContextVar[bool] = contextvars.ContextVar("magus_panel", default=False)
_AT = re.compile(r"/shelf/(?!floor/|p/|export)[A-Za-z0-9_.\-/%]+(?:\?[A-Za-z0-9_.\-=&%+]*)?")


def is_panel_request(request: Request) -> bool:
    """책장 패널(iframe) 안에서 연 화면인가. 브라우저가 붙이는 Sec-Fetch-Dest, 패널 안 올리기(XHR)는 X-Magus-Embed."""
    return request.headers.get("sec-fetch-dest") == "iframe" or request.headers.get("x-magus-embed") == "1"


def safe_at(value: str | None) -> str | None:
    """패널에 열 주소: 책장 아래의 책 화면만(바깥 주소·//·..·프로젝트 화면 주소는 받지 않는다)."""
    return value if value and _AT.fullmatch(value) and "//" not in value and ".." not in value else None


def state_url(floor: str | None = None, book: str | None = None, at: str | None = None, node: str | None = None, **extra: str) -> str:
    """프로젝트 화면의 주소(#95): /shelf/p/<프로젝트>?node=<노드>&book=<책>&at=<게시판 자리의 주소>. 그 밖의 값(done 등)은 뒤에 붙인다.
    프로젝트가 없으면 /shelf(프로젝트 목록, at이 있으면 그 책이 있는 프로젝트로 넘어간다)."""
    pairs = [(k, v) for k, v in (("node", node), ("book", book), ("at", at)) if v] + [(k, v) for k, v in extra.items() if v]
    base = f"/shelf/p/{urllib.parse.quote(floor)}" if floor else "/shelf"
    return base + ("?" + urllib.parse.urlencode(pairs) if pairs else "")


def book_style(book: Book) -> str:
    n = len(book.name)
    size = 26 if n <= 2 else 24 if n <= 4 else 22 if n <= 6 else 20 if n <= 9 else 18
    # 높이: 카테고리마다 조금 다르게, 이름이 길면 이름이 다 들어가게 키운다.
    height = max(252 + key_jitter(book.key, 41), 108 + round(n * size * 1.12))
    width = 56 if book.count < 10 else 64 if book.count < 50 else 74 if book.count < 200 else 86  # 많을수록 두껍게
    return f"{color_style(book.color)}--fs:{size}px;height:{height}px;width:{width}px"


def spine_parts(book: Book) -> tuple[str, str]:
    """(책등 아래 띠 HTML, 낭독기 이름(이스케이프됨)). 큰 책과 책장 전체의 작은 책이 같은 규칙을 쓴다."""
    count = f"{book.count}개" if book.count < 10000 else f"{book.count / 10000:.1f}만개"
    context = f", 컨텍스트 {book.band}" if book.band else ""
    label = html.escape(f"{book.name}{context}, 글 {book.count}개")
    if book.verified is not None:
        count = f'<span class="line">확인 {book.verified}</span><span class="line">전체 {book.count}</span>'
        label = html.escape(f"{book.name}{context}, 원문 확인 {book.verified}편, 전체 {book.count}개")
    if book.note is not None:
        count = "".join(f'<span class="line">{html.escape(line)}</span>' for line in book.note.split("\n"))
    if book.label is not None:
        label = html.escape(book.label)
    return count, label


def book_html(book: Book, floor: str | None = None) -> str:
    """floor를 주면 끌어 옮길 수 있는 책(data-book·data-from, #93)."""
    count, label = spine_parts(book)
    inner = (f'<span class="band top" aria-hidden="true">{html.escape(book.band)}</span>'
             f'<span class="spine-title" aria-hidden="true">{html.escape(book.name)}</span>'
             f'<span class="band bottom{" stale" if book.stale else ""}" aria-hidden="true">{count}</span>')
    if book.href is None:
        return f'<li><span class="book" style="{book_style(book)}" role="img" aria-label="{label}">{inner}</span></li>'
    drag = f' data-book="{html.escape(book.key)}" data-from="{html.escape(floor)}"' if floor and book.movable else ""
    return (f'<li><a class="book" href="{html.escape(book.href)}" style="{book_style(book)}" aria-label="{label}" '
            f'data-key="{html.escape(book.key)}" data-name="{html.escape(book.name)}"{drag}>{inner}</a></li>')


def add_book(floor: str, node: str | None = None) -> str:
    """'책 추가' 자리: 누르면 새 책 만들기·문서 올리기를 고른다(#94 → #96). 그 프로젝트의 그 노드에 꽂는다(#95)."""
    query = urllib.parse.urlencode([("project", floor), *([("node", node)] if node else [])])
    return (f'<li><a class="book add" href="/shelf/add?{html.escape(query)}" aria-label="책 추가">'
            '<span class="plus" aria-hidden="true">+</span><span class="spine-title" aria-hidden="true">책 추가</span></a></li>')


def shelf_html(books: list[str], extra: str = "", per: int = PER_SHELF) -> str:
    """책 HTML 목록 → 선반(per권씩). extra(책 추가 자리)는 마지막 선반 끝에 둔다."""
    items = [*books, *([extra] if extra else [])]
    shelves = [items[i : i + per] for i in range(0, len(items), per)] or [[]]
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
.band.top{margin-top:14px;white-space:normal;word-break:keep-all;font-size:13px;min-height:2.6em;display:flex;align-items:center;
justify-content:center}.band.bottom{margin-bottom:12px}.band .line{display:block;font-size:13px;line-height:1.35}
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


@dataclass
class Kind:
    """목록 화면 하나 = 책 하나(#96: 종류 없음). 올린 원고·문서의 설정 화면은 base("ms"·"doc")로 이것을 함께 쓴다."""

    key: str  # 주소 이름: 카테고리 id(ms.<프로젝트>·doc.<id>는 설정 화면에서만)
    name: str
    lanes: list[Lane]
    empty: str  # 빈 목록 안내
    category: Category | None = None
    floor: str = COMMON  # 그 책이 있는 프로젝트(#93 층 → #95)
    base: str = ""  # 올린 원고(ms)·문서(doc) 설정 화면에서만


def category_kind(c: Category) -> Kind:
    return Kind(c.id, c.name, ["category", "ref_bib", "ref_picked"],
                f'아직 적은 글이 없습니다. 위에서 바로 적거나, {SAY}"{html.escape(c.name)}에 넣어 줘: …"', c, c.floor)


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
    # MapPages(webmap)가 구현한다
    map_routes: Callable[[], list[tuple[str, list[str], Callable[..., Any]]]]
    location_form: Callable[[str, tuple[str, str], Kind], str]
    # BookPages(webbooks)가 구현한다
    book_routes: Callable[[], list[tuple[str, list[str], Callable[..., Any]]]]
    book_edit: Callable[[Request, str], Awaitable[Response]]
    book_trash: Callable[[Request, str], Awaitable[Response]]
    ref_register_form: Callable[[str, tuple[str, str], str], str]

    def shelf_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        # 고정 주소를 먼저 둔다(/shelf/{kind}보다 앞에서 맞아야 한다).
        return [
            *self.map_routes(),  # 프로젝트 목록·프로젝트 지도·패널·지도 바꾸기·옮기기·되돌리기·내려받기(webmap, #95)
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
        return self._page(title, body, session, status, current="프로젝트", css=SHELF_STYLE + CONTEXT_STYLE)

    def _kind(self, uid: str, key: str) -> Kind | None:
        """주소 이름 → 책 화면. 옛 주소 이름 '<종류>.<프로젝트>'(ideas.book)는 이전으로 생긴 책(<종류>-<프로젝트>)으로 본다(#96)."""
        base, _, floor = key.partition(".")
        if floor and base in BUILTINS:
            key = legacy_book_id(base, floor)
        elif key in BUILTINS:
            return None
        try:
            category = self.store.get_category(uid, key)
        except ValueError:
            return None
        return category_kind(category) if category else None

    def _kind_any(self, uid: str, key: str, item: str | None = None) -> Kind | None:
        """_kind와 같되, 예전 주소 이름(ideas·styles·refs)이면 그 글이 든 책(이전으로 생긴 책)."""
        if key in BUILTINS:
            target = self._legacy_target(uid, key, item)
            return self._kind(uid, target) if target else None
        return self._kind(uid, key)

    def _legacy_target(self, uid: str, base: str, item: str | None) -> str | None:
        """예전 주소(/shelf/ideas, /shelf/ideas/<id>, /shelf/refs/<key>)가 가리킬 지금 책 id: 그 글이 든 책,
        없으면 이전으로 생긴 그 종류의 첫 책."""
        books = [c for c in self.store.list_categories(uid) if c.id.startswith(f"{base}-")]
        if item:
            if base == "refs":
                ref = self.store.get_ref(uid, item)
                if ref and ref.book:
                    return ref.book
            for c in books:
                try:
                    if self.store.get_category_item(uid, c.id, item):
                        return c.id
                except ValueError:
                    continue
        return books[0].id if books else None

    # --- 책장 ---
    def books(self, uid: str, floor: str) -> list[Book]:
        """그 프로젝트에 있는 책 모두(지도의 노드 순서대로, 노드 안에서는 꽂힌 순서대로)."""
        found = self.store.get_map(uid, floor)
        keys = [b for n in (found.nodes if found else ()) if not n.link for b in n.books]
        return self.book_objects(uid, keys)

    def book_objects(self, uid: str, keys: list[str] | tuple[str, ...]) -> list[Book]:
        """책 주소 이름 → 책등. 위 띠는 컨텍스트 이름(#96). 없는 책은 뺀다."""
        from magus.book.documents import STALE_WORDS, is_stale  # noqa: PLC0415
        from magus.webbooks import MANUSCRIPT_COLOR, short_name  # noqa: PLC0415

        out = []
        for key in keys:
            base, _, rest = key.partition(".")
            if base == "ms":  # 올린 원고가 든 책: 가운데 노드 자체라 옮기지 않는다
                project = self.store.get_project(uid, rest)
                if project is None:
                    continue
                chapters = len(self.store.list_chapters(uid, rest))
                band = context_band(project.contexts)
                out.append(Book(key, short_name(project.title), band, chapters, project.color or MANUSCRIPT_COLOR,
                                f"/shelf/book/{rest}", note=f"{chapters}장",
                                label=f"{project.title}" + (f", 컨텍스트 {band}" if band else "") + f", 올린 원고 {chapters}장",
                                movable=False))
            elif base == "doc":  # 원고에서 만든 문서: 기준 원고에 새 수정본이 오면 '옛 판 기준'
                d = self.store.get_document(uid, rest)
                if d is None:
                    continue
                stale = is_stale(self.store, uid, d)
                basis = f"E{d.versions[-1].edition} 기준" if d.versions[-1].edition else "기록 전"
                band = context_band(d.contexts)
                out.append(Book(key, short_name(d.title), band, len(d.versions), d.color, f"/shelf/doc/{d.id}",
                                note="옛 판\n기준" if stale else basis, stale=stale,
                                label=f"{d.title}" + (f", 컨텍스트 {band}" if band else "") + ", " + (STALE_WORDS if stale else basis)))
            else:
                try:
                    c = self.store.get_category(uid, key)
                except ValueError:
                    c = None
                if c is not None:
                    out.append(Book(c.id, c.name, context_band(c.contexts), c.items + c.sources, c.color, f"/shelf/{c.id}",
                                    c.verified if c.sources else None))
        return out

    def _done_message(self, uid: str, request: Request) -> str:
        """만들기·고치기·휴지통 뒤 책장으로 돌아왔을 때 한 줄(주소의 값을 그대로 보이지 않고 정해진 문장만)."""
        done, cid = request.query_params.get("done"), request.query_params.get("c") or ""
        try:
            category = self.store.get_category(uid, cid) if cid and "." not in cid else None
        except ValueError:
            category = None
        shown = category.name if category else ""
        if cid.startswith(("ms.", "doc.")):  # 올린 원고·문서의 이름
            ident = cid.partition(".")[2]
            book = self.store.get_project(uid, ident) if cid.startswith("ms.") else self.store.get_document(uid, ident)
            shown = book.title if book else ""
        name = f"「{html.escape(shown)}」 " if shown else ""
        text = {"made": f"{name}책을 꽂았습니다.", "edit": f"{name}책을 고쳤습니다.",
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
        if kind_key.startswith(("ms.", "doc.")):  # 올린 원고·문서는 각자의 화면(#94)
            kind_name, _, ident = kind_key.partition(".")
            return RedirectResponse(f"/shelf/{'book' if kind_name == 'ms' else 'doc'}/{urllib.parse.quote(ident)}", status_code=302)
        if kind_key in BUILTINS or kind_key.partition(".")[0] in BUILTINS:  # 예전 주소: 이전으로 생긴 책의 주소로(#93·#95·#96)
            target = await run_in_threadpool(lambda: self._legacy_target(uid, kind_key, item) if kind_key in BUILTINS
                                             else legacy_book_id(*kind_key.split(".", 1)))
            if target:
                query = f"?{request.url.query}" if request.url.query else ""
                return RedirectResponse(f"/shelf/{target}" + (f"/{urllib.parse.quote(item)}" if item else "") + query, status_code=302)
        kind = await run_in_threadpool(self._kind, uid, kind_key)
        if kind is None:
            return self._shelf_page("책장", '<p class="msg err">없는 책입니다. <a href="/shelf">프로젝트</a>로 돌아가세요.</p>',
                                    session, 404)
        crumb = await run_in_threadpool(self._crumb, uid, kind)
        crumb += await run_in_threadpool(lambda: contexts_view_html(view_for_book(self.store, uid, kind.key), f"/shelf/edit/{kind.key}"))
        done = {"edited": "고쳤습니다.", "trashed": "글을 휴지통으로 옮겼습니다. 지운 것이 아니라 운영자가 되살릴 수 있습니다."}.get(
            request.query_params.get("done") or "")  # 고치기·휴지통 뒤 한 줄(정해진 문장만)
        done = f'<p class="msg">{done}</p>' if done else ""
        from magus.webbooks import REGISTER_ERRORS  # noqa: PLC0415  # 어느 책에든 원문 확인 글을 넣는 길(#94 → #96)

        if text := REGISTER_ERRORS.get(request.query_params.get("registererr") or ""):
            done += f'<p class="msg err">{text}</p>'
        if request.query_params.get("done") == "registered":
            done += '<p class="msg">원문 확인 글로 넣었습니다.</p>'
        error = request.query_params.get("error") == "empty"
        missing = (f'{crumb}<p class="msg err">없는 글입니다(휴지통으로 옮겨졌을 수 있습니다). '
                   f'<a href="/shelf/{kind.key}">{html.escape(kind.name)} 목록</a></p>')
        register = await run_in_threadpool(self.ref_register_form, uid, session, kind.key)
        if not await run_in_threadpool(self._has_any, uid, kind):  # 비어 있으면 바로 적기 폼을 펼쳐 둔다
            if item:
                return self._shelf_page(kind.name, missing, session, 404)
            summary = await run_in_threadpool(self._summary, uid, kind, {})
            write = self._write_form(session, kind, error, opened=True)
            return self._shelf_page(kind.name, f'{crumb}{done}{summary}{write}{register}<p class="msg">{kind.empty}</p>', session)
        write = self._write_form(session, kind, error) + register
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
            found = (f"<p>「{html.escape(q)}」 찾은 글 {len(rows)}개 · "
                     + ("최근 것부터(한 글자는 그 글자가 들어간 글을 모두 찾습니다)" if one_char(q) else "많이 맞은 것부터")
                     + f' · <a href="/shelf/{kind.key}">검색 지우기</a></p>')
        board = (f'<ol class="board">{"".join(row_html(r, q, r.id == item) for r in shown)}</ol>'
                 if shown else '<p class="msg">찾는 말이 들어간 글이 없습니다.</p>' if q else '<p class="msg">없음</p>')
        body = f"{crumb}{done}{summary}{search}{write}{found}{pager}{board}{pager}" + (SCROLL_SCRIPT if item else "")
        return self._shelf_page(kind.name, body, session)

    def _crumb(self, uid: str, kind: Kind) -> str:
        """'← 프로젝트 · 「제목」' — 프로젝트 목록과 그 책이 있는 프로젝트 지도로 돌아가는 길(패널 안에서는 숨는다)."""
        floor = self.store.get_floor(uid, kind.floor)
        where = f' · <a href="{html.escape(state_url(kind.floor, kind.key))}">「{html.escape(floor.label)}」</a>' if floor else ""
        return f'<p class="crumb"><a href="/shelf">← 프로젝트</a>{where}</p>'

    def _has_any(self, uid: str, kind: Kind) -> bool:
        assert kind.category is not None
        return bool(self.store.list_category_items(uid, kind.category.id) or self.store.list_refs(uid, book=kind.category.id))

    def _summary(self, uid: str, kind: Kind, filters: dict[str, str]) -> str:
        """목록 위 한 줄: 글 수(나·AI)·문헌 글 수(원문 확인), 거르기 링크, 이름·색·컨텍스트 바꾸기."""
        assert kind.category is not None
        c = kind.category
        items = self.store.list_category_items(uid, c.id)
        mine = sum(1 for i in items if i.author == "me")
        base = f"/shelf/{c.id}"
        template = TEMPLATE_BY_KEY.get(c.template)
        fields = f" · 칸: {html.escape(', '.join(c.fields))}" if c.fields else ""
        sources = f" · 문헌 글 {c.sources}개(원문 확인 {c.verified})" if c.sources else ""
        trash = "" if c.sources else f' · <a href="/shelf/trash/{c.id}">휴지통으로</a>'
        tag = filters.get("tag", "")
        only = f' · 태그 「{html.escape(tag)}」만 · <a href="{base}">전체</a>' if tag else ""
        links = [f'<a href="{base}">전체</a>']
        if items:
            links += [f'<a href="{base}?author=me">나</a>', f'<a href="{base}?author=ai">AI</a>']
        if c.sources:
            links += [f'<a href="{base}?status=verified">{LIGHTS["verified"][0]} {LIGHTS["verified"][1]}</a>',
                      f'<a href="{base}?status=unverified">{LIGHTS["unverified"][0]} {LIGHTS["unverified"][1]}</a>']
        project = self._ref_project(uid, kind, filters) if c.sources else None
        checklist = (f' · 인용 현황은 원고의 <a href="/shelf/book/{urllib.parse.quote(project.id)}?tab=cites">인용 상태</a>'
                     if project else "")
        return (f"<p>글 {len(items)}개" + (f"(나 {mine} · AI {len(items) - mine})" if items else "") + sources + fields
                + (f" · {html.escape(template.name)}" if template and template.fields else "") + only + checklist
                + f' · <a href="/shelf/edit/{c.id}">이름·색·컨텍스트 바꾸기</a>{trash}</p>'
                + (f'<p>{" · ".join(links)}</p>' if len(links) > 1 else ""))

    def _ref_project(self, uid: str, kind: Kind, filters: dict[str, str]) -> Any:
        """'인용된 장'을 셀 작업물: 주소의 project, 없으면 그 책이 있는 작업물, 「내 서재」면 최근 작업물."""
        wanted = filters.get("project") or (kind.floor if kind.floor != COMMON else None)
        return self.store.get_project(uid, wanted) or self.store.get_project(uid)

    def _rows(self, uid: str, kind: Kind, filters: dict[str, str] | None, q: str) -> list[Row]:
        """그 책의 줄들: 글(최근 것부터) 뒤에 문헌 글(원문 확인 먼저, key 순). 검색어가 있으면 맞은 것만 검색 순서로.
        나·AI로 거르면 글만, 원문 확인으로 거르면 문헌 글만."""
        filters = filters or {}
        assert kind.category is not None
        pairs: list[tuple[str, Row]] = []
        if not filters.get("status"):
            pairs += self._item_rows(uid, kind.category, filters, q)
        if not filters.get("author") and not filters.get("tag"):
            pairs += self._ref_rows(uid, kind, filters, q)
        if not q:
            return [row for _, row in pairs]
        owners = []
        for owner in find(self.store, uid, kind.lanes, q):  # 글은 "<책 id>/<글 id>", 문헌 글은 key
            if owner.startswith(f"{kind.category.id}/"):
                owners.append(owner.split("/", 1)[1])
            elif "/" not in owner:
                owners.append(owner)
        order = {owner: n for n, owner in enumerate(owners)}
        return [row for owner, row in sorted((p for p in pairs if p[0] in order), key=lambda p: order[p[0]])]

    def _item_rows(self, uid: str, category: Category, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
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
                            *([html.escape(i.where[:24])] if i.where else []),
                            *(f'<span class="tag">{html.escape(t)}</span>' for t in i.tags[:2]),
                            *([f"외 {len(i.tags) - 2}"] if len(i.tags) > 2 else []),
                            *([html.escape(", ".join(chapters))] if chapters else [])])
            fields = "".join(f"<dt>{html.escape(k)}</dt><dd>{mark(v, q)}</dd>" for k, v in i.fields.items() if v)
            pills = " ".join(f'<a class="tag" href="/shelf/{category.id}?tag={urllib.parse.quote(t)}">{html.escape(t)}</a>' for t in i.tags)
            parts = "".join(f'<p>「{mark(p.text, q)}」<br><span class="muted">{html.escape(p.reason)}'
                            + (f" · {html.escape(p.locator)}" if p.locator else "") + "</span></p>" for p in i.passages)
            back = (f'<p class="muted">AI의 답입니다. <a href="/shelf/{category.id}/{html.escape(i.parent_id)}">응답한 글</a></p>'
                    if i.parent_id else "")
            by = TAGS_BY.get(i.tags_by or "")
            body = (paragraphs(i.content, q)
                    + (f"<p>이유: {mark(i.reason, q)}</p>" if i.reason else "")
                    + (f'<p class="muted">위치: {mark(i.where, q)}</p>' if i.where else "")
                    + parts
                    + (f'<dl class="fields">{fields}</dl>' if fields else "")
                    + (f"<p>{pills}</p>" if pills else "") + (f'<p class="muted">{by}</p>' if by and pills else "")
                    + (f"<p>연결된 장: {html.escape(', '.join(chapters))}</p>" if chapters else "")
                    + (f'<p class="muted">출처: {html.escape(i.origin)}</p>' if i.origin else "") + back
                    + f'<p class="muted">누가: {"저자의 말" if i.author == "me" else "Claude가 쓴 글"}'
                    + (" · 제목은 AI가 지었습니다." if i.title and i.title_by == "ai" else "") + "</p>" + edited_note(i))
            text = "\n".join([i.content, i.reason or "", i.where or "", *(p.text for p in i.passages),
                              *(f"{k} {v}" for k, v in i.fields.items()), " ".join(i.tags)])
            preview = i.content or " · ".join(f"{k}: {v}" for k, v in i.fields.items() if v)  # 내용이 없으면 채워진 칸
            rows.append((i.id, Row(i.id, f"/shelf/{category.id}/{i.id}", i.created_at, i.title, preview, aux, body, text,
                                   AI_TITLE if i.title and i.title_by == "ai" else "", True)))
        return rows

    def _ref_rows(self, uid: str, kind: Kind, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        """그 책의 문헌 글(#96: 문헌은 어느 책에든 든다)."""
        assert kind.category is not None
        status = filters.get("status") if filters.get("status") in ("verified", "unverified") else None
        refs = sorted((r for r in self.store.list_refs(uid, book=kind.category.id) if status is None or r.status == status),
                      key=lambda r: (r.status != "verified", r.key))
        if not refs:
            return []
        project = self._ref_project(uid, kind, filters)
        cited: dict[str, list[str]] = {}
        if project is not None:
            report = build_cite_report(self.store, uid, project.id)
            cited = {key: list(dict.fromkeys(d.chapters)) for key, d in report.docs.items()}
        rows = []
        for r in refs:
            light, word = LIGHTS[r.status]
            chapters = cited.get(r.key, [])
            aux = f"{light} {word}" + (f" · 인용된 장 {len(chapters)}" if chapters else "")
            passages = self.store.get_passages(uid, r.key)
            body = "".join([
                *([f"<p>{mark(str(r.bib.get('memo')), q)}</p>"] if r.bib.get("memo") else []),
                *([f'<p class="muted">{mark(str(r.bib.get("container")), q)}</p>'] if r.bib.get("container") else []),
                *([f'<p class="muted">서지: {mark(str(r.bib.get("authors") or r.bib.get("raw") or ""), q)}</p>']
                  if r.bib.get("authors") or r.bib.get("raw") else []),
                *(f'<p>쓸 부분 「{mark(p.text, q)}」<br><span class="muted">{html.escape(p.reason)}'
                  + (f" · {html.escape(p.locator)}" if p.locator else "") + "</span></p>" for p in passages),
                f"<p>인용된 장: {html.escape(chapters_text(chapters) or '-')}</p>",
                *([f'<p class="muted">한글 표기: {html.escape(", ".join(r.aliases))}</p>'] if r.aliases else []),
                *([f'<p class="muted">「내 서재」로 옮김({local_time(r.moved.get("at", ""), WHEN)}): {html.escape(r.moved.get("reason", ""))}</p>']
                  if r.moved and r.moved.get("to") == r.floor else []),  # 저자 모르게 배치가 바뀌지 않게(#93-a 더함)
                '<p class="muted">문헌 글: 서지와 원문 확인 표시가 있는 글입니다. 인용 점검은 원문 확인 글만 확인으로 봅니다.</p>',
            ])
            text = "\n".join([str(r.bib.get("authors") or ""), str(r.bib.get("container") or ""), *(p.text for p in passages)])
            rows.append((r.key, Row(r.key, f"/shelf/{kind.key}/{urllib.parse.quote(r.key)}", r.created_at, cite_label(r, r.key),
                                    "", aux, body, text)))
        return rows

    # --- 바로 적기(모든 책, #96) ---
    def _write_form(self, session: tuple[str, str], kind: Kind, error: bool, opened: bool = False) -> str:
        fields = kind.category.fields if kind.category else ()
        extra = "".join(f'<label class="block">{html.escape(f)} <input name="f:{html.escape(f)}" maxlength="{FIELD_MAX}"></label>'
                        for f in fields)
        extra += (f'<label class="block">이유(선택) <input name="reason" maxlength="{FIELD_MAX}"></label>'
                  f'<label class="block">위치(선택: 출전·쪽·장소) <input name="where" maxlength="{FIELD_MAX}"></label>')
        return (
            f'<details class="card write"{" open" if error or opened else ""}><summary>새로 적기</summary>'
            + (f'<p class="msg err">{EMPTY_ITEM}</p>' if error else "")
            + f'<form method="post" action="/shelf/write/{kind.key}">{self._csrf_input(session)}'
            f'<label class="block">제목(비워 둬도 됩니다) <input name="title" maxlength="{TITLE_MAX}"></label>'
            f'<label class="block">내용 <textarea name="content" rows="6" maxlength="{CONTENT_MAX}"></textarea></label>'
            f"<details><summary>칸 더 적기(선택)</summary>{extra}</details>"
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
        if kind is None or kind.category is None:
            return self._shelf_page("책장", '<p class="msg err">여기에는 바로 적을 수 없습니다.</p>', session, 404)
        content = str(form.get("content") or "").strip()[:CONTENT_MAX]
        title = one_line(str(form.get("title") or ""))[:TITLE_MAX] or None
        values = {f: one_line(str(form.get(f"f:{f}") or ""))[:FIELD_MAX] for f in kind.category.fields}
        reason = one_line(str(form.get("reason") or ""))[:FIELD_MAX] or None
        where = one_line(str(form.get("where") or ""))[:FIELD_MAX] or None
        if not content and not (title or any(values.values())):
            return RedirectResponse(f"/shelf/{kind.key}?error=empty", status_code=303)
        item = await run_in_threadpool(self.store.put_category_item, uid, CategoryItem(
            new_id(), kind.category.id, content, "me", title, "author" if title else None, {k: v for k, v in values.items() if v},
            reason=reason, where=where))
        return RedirectResponse(f"/shelf/{kind.category.id}/{item.id}", status_code=303)

    # --- 책 만들기·고치기·휴지통(#96: 모든 책, 컨텍스트) ---
    async def shelf_new(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        mine = await run_in_threadpool(self.store.list_categories, uid)
        settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
        default_color = PALETTE_BY_NAME[NEW_COLOR_ORDER[len(mine) % len(NEW_COLOR_ORDER)]]
        values = {"name": "", "template": "blank", "color": default_color}
        attached: tuple = ()
        error = ""
        # 꽂을 곳(#95): 노드의 '책 추가'에서 온 프로젝트와 노드. 없으면 「내 서재」(노드는 이름이 같은 새 노드)
        params = request.query_params
        floor = await run_in_threadpool(self.store.get_floor, uid, params.get("project") or params.get("floor") or COMMON)
        floor = floor or await run_in_threadpool(self.store.get_floor, uid, COMMON)
        found_map = await run_in_threadpool(self.store.get_map, uid, floor.id)
        node = found_map.node(params.get("node") or "") if found_map else None
        node = node if node is not None and not node.link else None
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("새 책", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            values = {"name": str(form.get("name") or ""), "template": str(form.get("template") or "blank"),
                      "color": safe_color(str(form.get("hex") or ""), default_color)}
            try:
                attached = contexts_from_form(form, saved)
            except ValueError as e:
                error = f'<p class="msg err">{html.escape(str(e))}</p>'
            if form.get("register") is not None:  # 자주 쓰는 컨텍스트로 등록만 하고 이 화면을 다시 보인다
                error = await run_in_threadpool(register_row, self.store, uid, form)
                saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
            elif not error:
                try:
                    if len(mine) >= MAX_CATEGORIES:
                        raise ValueError(f"책은 {MAX_CATEGORIES}권까지 만들 수 있습니다.")
                    name = check_name(values["name"], {name_key(c.name): c.name for c in mine if c.floor == floor.id})
                    template = TEMPLATE_BY_KEY.get(values["template"])
                    if template is None:
                        raise ValueError("칸 모양을 골라 주세요.")
                    color = chosen_color(form)
                    values["color"] = color
                    made = await run_in_threadpool(lambda: self.store.create_category(
                        uid, name, template.key, color, tuple(f for f, _ in template.fields), floor.id,
                        node.id if node is not None and not node.center else None, contexts=attached))
                    note = await run_in_threadpool(self._keep_color, uid, form, color)
                    return RedirectResponse(state_url(floor.id, made.id, done="made", c=made.id) + note, status_code=303)
                except ValueError as e:
                    error = f'<p class="msg err">{html.escape(str(e))}</p>'
        templates = "".join(
            f'<label class="tpl"><input type="radio" name="template" value="{t.key}"{" checked" if t.key == values["template"] else ""}>'
            f'<span><b>{html.escape(t.name)}</b> — {html.escape(t.about)} <span class="muted">'
            + (f"(칸: {' · '.join(f for f, _ in t.fields)})" if t.fields else "(제목·내용만)") + "</span></span></label>"
            for t in TEMPLATES
        )
        preview = shelf_html([book_html(Book("preview", values["name"] or "새 책", context_band(attached), 0, values["color"], None))])
        where = f"「{floor.label}」" + (f" · 노드 「{node.name}」" if node is not None and not node.center else " · 이름이 같은 새 노드")
        query = urllib.parse.urlencode([("project", floor.id), *([("node", node.id)] if node is not None else [])])
        body = (
            f'<p class="crumb"><a href="/shelf">← 프로젝트</a> · <a href="{html.escape(state_url(floor.id))}">「{html.escape(floor.label)}」</a></p>{error}'
            f'<p>꽂을 곳: <b>{html.escape(where)}</b></p>'
            f'<form method="post" action="/shelf/new?{html.escape(query)}" class="colors">{self._csrf_input(session)}'
            f'<label class="block">이름(12자까지) <input name="name" value="{html.escape(values["name"])}" maxlength="12"></label>'
            '<p class="muted">전체·확인 요청처럼 정해진 이름과, 이 프로젝트에 이미 있는 이름은 쓸 수 없습니다.</p>'
            + context_fieldset(saved, attached)
            + f"<fieldset><legend>칸(선택)</legend>{templates}</fieldset>"
            + color_fieldset(values["color"], settings.my_colors)
            + f'<div class="preview"><p><b>미리보기</b></p>{preview}</div>'
            f'<p><button class="primary">책장에 꽂기</button> <a href="{html.escape(state_url(floor.id))}">그만두기</a></p></form>'
            + COLOR_SCRIPT + CONTEXT_SCRIPT
        )
        return self._shelf_page("새 책", body, session, 400 if error.startswith('<p class="msg err">') else 200)

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
        if request.path_params["kind"].startswith(("ms.", "doc.")):  # 올린 원고·문서 설정(#94)
            return await self.book_edit(request, request.path_params["kind"])
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        kind = await run_in_threadpool(self._kind_any, uid, request.path_params["kind"])
        if kind is None or kind.category is None:
            return self._shelf_page("책장", '<p class="msg err">없는 책입니다. <a href="/shelf">프로젝트</a>로 돌아가세요.</p>', session, 404)
        category = kind.category
        settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
        current, name, attached, error = category.color, kind.name, category.contexts, ""
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("책 고치기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            name = str(form.get("name") or kind.name)
            current = safe_color(str(form.get("hex") or ""), current)
            try:
                attached = contexts_from_form(form, saved)
            except ValueError as e:
                error = f'<p class="msg err">{html.escape(str(e))}</p>'
            if form.get("register") is not None:
                error = await run_in_threadpool(register_row, self.store, uid, form)
                saved = await run_in_threadpool(self.store.list_saved_contexts, uid)
            elif not error:
                try:
                    color = chosen_color(form)
                    current = color
                    taken = {name_key(c.name): c.name for c in self.store.list_categories(uid, floors=[kind.floor]) if c.id != category.id}
                    clean = check_name(name, taken) if name_key(name) != name_key(category.name) else None
                    await run_in_threadpool(lambda: self.store.update_category(uid, category.id, name=clean, color=color))
                    await run_in_threadpool(self.store.set_book_contexts, uid, category.id, attached)
                    note = await run_in_threadpool(self._keep_color, uid, form, color)
                    return RedirectResponse(state_url(kind.floor, kind.key, done="edit", c=kind.key) + note, status_code=303)
                except ValueError as e:
                    error = f'<p class="msg err">{html.escape(str(e))}</p>'
            settings = await run_in_threadpool(self.store.get_shelf_settings, uid)
        count = category.items + category.sources
        preview = shelf_html([book_html(Book(kind.key, name, context_band(attached), count, current, None))])
        mine = "".join(
            f'<li><span class="chip" style="background:{c}" aria-hidden="true"></span>{c}'
            f'<form method="post" action="/shelf/colors" class="inline">{self._csrf_input(session)}'
            f'<input type="hidden" name="remove" value="{c}"><input type="hidden" name="next" value="/shelf/edit/{kind.key}">'
            f'<button aria-label="내 색 {c} 빼기">빼기</button></form></li>'
            for c in settings.my_colors
        )
        trash = (f'<h2>휴지통</h2><p class="muted">문헌 글이 {category.sources}개 있어 이 책은 휴지통으로 옮기지 않습니다'
                 "(인용 점검이 보는 기록입니다).</p>" if category.sources
                 else f'<h2>휴지통</h2><p><a href="/shelf/trash/{kind.key}">이 책을 휴지통으로 옮기기</a></p>')
        place = await run_in_threadpool(self.location_form, uid, session, kind)  # 위치(#95: 프로젝트 · 노드, webmap)
        body = (
            f'<p class="crumb"><a href="/shelf/{kind.key}">← {html.escape(kind.name)}</a></p>{error}'
            f'<form method="post" action="/shelf/edit/{kind.key}" class="colors">{self._csrf_input(session)}'
            f'<label class="block">이름(12자까지) <input name="name" value="{html.escape(name)}" maxlength="12" required></label>'
            + context_fieldset(saved, attached)
            + color_fieldset(current, settings.my_colors)
            + f'<div class="preview"><p><b>미리보기</b></p>{preview}</div>'
            f'<p><button class="primary">저장</button> <a href="/shelf/{kind.key}">그만두기</a></p></form>'
            + (f'<h2>내 색</h2><ul class="mycolors">{mine}</ul>' if mine else "") + place + trash + COLOR_SCRIPT + CONTEXT_SCRIPT
        )
        return self._shelf_page(f"{kind.name} — 이름·색·컨텍스트", body, session, 400 if error.startswith('<p class="msg err">') else 200)

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
        if request.path_params["kind"].startswith(("ms.", "doc.")):  # 올린 원고·문서 휴지통(#94)
            return await self.book_trash(request, request.path_params["kind"])
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        kind = await run_in_threadpool(self._kind, uid, request.path_params["kind"])
        if kind is None or kind.category is None:
            return self._shelf_page("책장", '<p class="msg err">없는 책입니다. <a href="/shelf">프로젝트</a>로 돌아가세요.</p>', session, 404)
        category = kind.category
        if category.sources:
            return self._shelf_page("책장", f'<p class="msg err">「{html.escape(category.name)}」에는 문헌 글이 있어 휴지통으로 옮기지 않습니다.</p>',
                                    session, 400)
        if request.method == "POST":
            try:
                await self._form(request, session)
            except PermissionError:
                return self._shelf_page("휴지통으로", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            await run_in_threadpool(self.store.trash_category, uid, category.id, "웹 책장에서 옮김")
            return RedirectResponse(state_url(category.floor, done="trash"), status_code=303)
        body = (
            f'<p class="crumb"><a href="/shelf/{category.id}">← {html.escape(category.name)}</a></p>'
            f'<div class="card"><p>「{html.escape(category.name)}」 책을 휴지통으로 옮길까요?</p>'
            f"<p>글 {category.items}개가 함께 옮겨집니다. 지우는 것이 아니라 옮기는 것이라 운영자가 되살릴 수 있습니다.</p>"
            f'<form method="post" action="/shelf/trash/{category.id}">{self._csrf_input(session)}'
            f'<p><button>휴지통으로 옮기기</button> <a href="/shelf/{category.id}">그만두기</a></p></form></div>'
        )
        return self._shelf_page("휴지통으로", body, session)

    # --- 글 고치기·휴지통(모든 책의 글. 자기 책장 안에서만, CSRF, 휴지통은 확인 한 번) ---
    def _editable(self, uid: str, kind_key: str, item_id: str) -> tuple[Kind, Any] | None:
        kind = self._kind_any(uid, kind_key, item_id)
        if kind is None or kind.category is None:
            return None
        try:
            item = self.store.get_category_item(uid, kind.category.id, item_id)
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
            return self._shelf_page("책장", '<p class="msg err">고칠 수 있는 글이 아닙니다. <a href="/shelf">프로젝트</a>로 돌아가세요.</p>',
                                    session, 404)
        kind, item = found
        assert kind.category is not None
        link = f"/shelf/{kind.key}/{item.id}"
        old_text, error = item.content, ""
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("글 고치기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            content = str(form.get("content") or "").strip()[:CONTENT_MAX]
            title = one_line(str(form.get("title") or ""))[:TITLE_MAX] or None
            values = {f: one_line(str(form.get(f"f:{f}") or ""))[:FIELD_MAX] for f in kind.category.fields}
            reason = one_line(str(form.get("reason") or ""))[:FIELD_MAX] or None
            where = one_line(str(form.get("where") or ""))[:FIELD_MAX] or None
            if content or title or any(values.values()) or item.passages:
                # 제목을 그대로 두면 누가 지었는지도 그대로, 저자가 새로 적으면 저자가 지은 제목, 지우면 없음
                title_by = item.title_by if title == item.title else ("author" if title else None)
                await run_in_threadpool(self.store.put_category_item, uid, replace(
                    item, content=content, title=title, title_by=title_by, fields={k: v for k, v in values.items() if v},
                    reason=reason, where=where, edited_at=utcnow(), edited_by="author"))
                return RedirectResponse(f"{link}?done=edited", status_code=303)
            error = f'<p class="msg err">{EMPTY_ITEM}</p>'
            old_text = content
        fields = "".join(
            f'<label class="block">{html.escape(f)} <input name="f:{html.escape(f)}" value="{html.escape(item.fields.get(f, ""))}" '
            f'maxlength="{FIELD_MAX}"></label>' for f in kind.category.fields)
        who = ('<p class="muted">처음 쓴 사람: Claude(AI). 고치면 "저자가 고침"으로 함께 남습니다.</p>' if item.author == "ai" else "")
        body = (
            f'<p class="crumb"><a href="{link}">← {html.escape(kind.name)}</a></p>{error}{who}'
            f'<form method="post" action="{link}/edit" class="card">{self._csrf_input(session)}'
            f'<label class="block">제목(비워 둬도 됩니다) <input name="title" value="{html.escape(item.title or "")}" maxlength="{TITLE_MAX}"></label>'
            f'<label class="block">내용 <textarea name="content" rows="8" maxlength="{CONTENT_MAX}">{html.escape(old_text)}</textarea></label>'
            f'<label class="block">이유(선택) <input name="reason" value="{html.escape(item.reason or "")}" maxlength="{FIELD_MAX}"></label>'
            f'<label class="block">위치(선택: 출전·쪽·장소) <input name="where" value="{html.escape(item.where or "")}" maxlength="{FIELD_MAX}"></label>'
            f'{fields}<p><button class="primary">저장</button> <a href="{link}">그만두기</a></p></form>'
        )
        return self._shelf_page("글 고치기", body, session, 400 if error else 200)

    async def shelf_item_trash(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        found = await run_in_threadpool(self._editable, uid, request.path_params["kind"], request.path_params["item"])
        if found is None:
            return self._shelf_page("책장", '<p class="msg err">옮길 수 있는 글이 아닙니다. <a href="/shelf">프로젝트</a>로 돌아가세요.</p>',
                                    session, 404)
        kind, item = found
        assert kind.category is not None
        link = f"/shelf/{kind.key}/{item.id}"
        if request.method == "POST":
            try:
                await self._form(request, session)
            except PermissionError:
                return self._shelf_page("휴지통으로", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            await run_in_threadpool(self.store.trash_item_with_replies, uid, kind.category.id, item.id, "웹 책장에서 옮김")
            return RedirectResponse(f"/shelf/{kind.key}?done=trashed", status_code=303)
        replies = sum(1 for i in await run_in_threadpool(self.store.list_category_items, uid, kind.category.id) if i.parent_id == item.id)
        preview = one_line(item.title or item.content)
        body = (
            f'<p class="crumb"><a href="{link}">← {html.escape(kind.name)}</a></p>'
            f'<div class="card"><p>이 글을 휴지통으로 옮길까요?</p><p><b>{html.escape(preview[:80])}{"…" if len(preview) > 80 else ""}</b></p>'
            + (f"<p>이 글에 응답한 글 {replies}개도 함께 옮겨집니다.</p>" if replies else "")
            + "<p>지우는 것이 아니라 옮기는 것이라 운영자가 되살릴 수 있습니다.</p>"
            f'<form method="post" action="{link}/trash">{self._csrf_input(session)}'
            f'<p><button>휴지통으로 옮기기</button> <a href="{link}">그만두기</a></p></form></div>'
        )
        return self._shelf_page("휴지통으로", body, session)
