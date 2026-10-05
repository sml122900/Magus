"""웹 책장(2026-10-06): 생각·문체·문헌(기본 카테고리)을 책장에 꽂힌 양장본으로 보이고,
책을 누르면 게시판형 목록(한 줄 = 제목 · 작성 시각 · 보조 정보, 누르면 그 자리에서 펼침)과 검색이 열린다.

- 항목마다 고유 주소(/shelf/ideas/<id> 등)가 있고, 그 주소로 들어오면 그 항목이 펼쳐진 채 보인다.
- 검색은 서버에서 한다(GET ?q=). 두 글자 이상은 기존 FTS 인덱스(2글자 조각)로 찾아 많이 맞은 것부터,
  한 글자는 2글자 조각 색인으로 찾을 수 없어 그 글자가 그대로 들어 있는 항목을 최근 것부터 보인다.
- 책장 전용 색(책 색 격자·선반 나무색)은 이 파일에만 있다. 다른 화면에는 쓰지 않는다(docs/decisions/web-style.md "책장 전용").
- 책 색은 ^#[0-9a-fA-F]{6}$ 형식만 스타일에 넣는다. 글자색은 책 색에 맞춰 흰색·짙은 색 중 대비가 높은 쪽(4.5:1 이상)이고,
  결·띠·가운데 밝은 줄은 글자와 반대 방향(글자가 희면 어둡게, 짙으면 밝게)으로만 얹어 글자 대비를 낮추지 않는다.
"""

from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from magus.ids import local_time
from magus.melchior.author_report import chapters_text, cite_label
from magus.melchior.report import build_cite_report
from magus.store import Store
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

# ---- 책 색(책장 전용) ----------------------------------------------------------------------
# 기본 색 격자. 이름은 대화로 색을 바꿀 때도 쓴다("사례 카테고리를 빨강으로"). 색에 뜻을 붙이지 않는다(뜻은 저자가 정한다).
PALETTE: tuple[tuple[str, str], ...] = (
    ("빨강", "#b3261e"), ("주황", "#d2691e"), ("노랑", "#e8c547"), ("초록", "#2e7d4f"), ("파랑", "#2f6db5"),
    ("남색", "#1f2f5c"), ("보라", "#6b3fa0"), ("분홍", "#e58fb0"), ("갈색", "#7a4e2d"), ("회색", "#8a8d91"),
    ("검정", "#1e1e1e"), ("미색", "#f1e9d2"), ("자주", "#6e1f2f"), ("짙은 초록", "#1f4a3a"), ("청록", "#2a7f86"),
    ("겨자", "#b8923a"), ("하늘", "#8db8de"), ("먹색", "#3b4652"),
)
HEX = re.compile(r"#[0-9a-fA-F]{6}")
LIGHT_TEXT, DARK_TEXT = "#ffffff", "#1a1a1a"


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
    """책장에 꽂힌 책 하나(카테고리 하나)."""

    key: str  # 주소에 쓰는 이름: ideas | styles | refs
    name: str
    band: str  # 위쪽 띠: 기본 카테고리면 "기본", 저자의 카테고리면 템플릿 이름
    count: int
    color: str
    href: str


def book_html(book: Book) -> str:
    color = safe_color(book.color, "#3b4652")
    fg = text_color(color)
    light_text = fg in (LIGHT_TEXT, "#ffffff")
    n = len(book.name)
    size = 26 if n <= 2 else 24 if n <= 4 else 22 if n <= 6 else 20 if n <= 9 else 18
    # 높이: 카테고리마다 조금 다르게(이름의 해시라 같은 카테고리는 언제나 같다), 이름이 길면 이름이 다 들어가게 키운다.
    height = max(252 + int(hashlib.sha256(book.key.encode()).hexdigest()[:4], 16) % 41, 108 + round(n * size * 1.12))
    width = 56 if book.count < 10 else 64 if book.count < 50 else 74 if book.count < 200 else 86  # 많을수록 두껍게
    count = f"{book.count}개" if book.count < 10000 else f"{book.count / 10000:.1f}만개"
    style = (f"--c:{color};--fg:{fg};--fgrgb:{' '.join(str(int(fg[i:i + 2], 16)) for i in (1, 3, 5))};"
             f"--away:{'0 0 0' if light_text else '255 255 255'};"
             f"--glow:{0 if light_text else .14};--fs:{size}px;height:{height}px;width:{width}px")
    label = f"{book.name}, 항목 {book.count}개"
    return (f'<li><a class="book" href="{html.escape(book.href)}" style="{style}" aria-label="{html.escape(label)}">'
            f'<span class="band top" aria-hidden="true">{html.escape(book.band)}</span>'
            f'<span class="spine-title" aria-hidden="true">{html.escape(book.name)}</span>'
            f'<span class="band bottom" aria-hidden="true">{count}</span></a></li>')


def shelf_html(books: list[str], extra: str = "") -> str:
    """책 HTML 목록 → 선반(PER_SHELF권씩). extra(카테고리 추가 자리)는 마지막 선반 끝에 둔다."""
    items = [*books, *([extra] if extra else [])]
    shelves = [items[i : i + PER_SHELF] for i in range(0, len(items), PER_SHELF)] or [[]]
    return ('<section class="case" aria-label="책장">'
            + "".join(f'<div class="shelf"><ul class="books">{"".join(row)}</ul></div>' for row in shelves)
            + "</section>")


# 책장 전용 스타일. 선반 나무색과 책 음영은 여기에만 있다(web-style.md "책장 전용").
SHELF_STYLE = """
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
 repeating-linear-gradient(0deg,rgb(var(--away)/.05) 0 1px,transparent 1px 3px),
 repeating-linear-gradient(90deg,rgb(var(--away)/.04) 0 1px,transparent 1px 4px);
box-shadow:inset 0 1px 0 rgb(255 255 255/.25),1px 0 2px rgb(0 0 0/.25);transition:transform .15s ease,box-shadow .15s ease}
.book:hover,.book:focus-visible{color:var(--fg);transform:translateY(-14px);box-shadow:inset 0 1px 0 rgb(255 255 255/.25),0 10px 14px rgb(0 0 0/.3)}
.book:focus-visible{outline:3px solid var(--primary);outline-offset:3px}
.band{display:block;width:100%;text-align:center;font-size:14px;font-weight:600;line-height:1.2;
padding:6px 2px;background:rgb(var(--away)/.22);border-top:2px solid rgb(var(--fgrgb)/.45);
border-bottom:2px solid rgb(var(--fgrgb)/.45);font-variant-numeric:tabular-nums;white-space:nowrap}
.band.top{margin-top:14px}.band.bottom{margin-bottom:12px}
.spine-title{writing-mode:vertical-rl;text-orientation:mixed;font-size:var(--fs);font-weight:600;line-height:1.1;
letter-spacing:.06em;margin:auto 0;padding:10px 0;white-space:nowrap}
.book.add{background:transparent;color:var(--ink2);border:2px dashed var(--ink2);box-shadow:none;justify-content:center;gap:10px}
.book.add .plus{font-size:26px;line-height:1}
.book.add:hover,.book.add:focus-visible{background:rgb(255 255 255/.6);color:var(--ink)}
@media (prefers-reduced-motion:reduce){.book{transition:none}
.book:hover,.book:focus-visible{transform:none;outline:3px solid var(--primary);outline-offset:3px}}
.board{list-style:none;margin:12px 0;padding:0;background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.board>li{border-bottom:1px solid var(--line)}.board>li:last-child{border-bottom:0}
.board summary{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 16px;padding:12px 16px 12px 44px;min-height:48px;
cursor:pointer;list-style:none;position:relative}
.board summary::-webkit-details-marker{display:none}
.board summary::before{content:"▸";position:absolute;left:16px;top:10px;color:var(--ink2);font-size:20px;line-height:1.4}
.board details[open]>summary::before{content:"▾"}
.board details[open]{box-shadow:inset 4px 0 0 var(--primary)}
.board summary:hover .t{text-decoration:underline}
.board .t{flex:1 1 320px;font-weight:600;font-size:17px;color:var(--ink)}
.board .t.none{font-weight:400;color:var(--mute)}
.board .hit{flex:1 0 100%;order:5;color:var(--ink2);font-size:15px}
.board .when{color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap;min-width:9em}
.board .aux{color:var(--ink2);font-size:15px;min-width:4em;max-width:40%}
.board .body{padding:0 16px 16px 44px}
.board .body p{margin:8px 0}.board .body .muted{color:var(--ink2);font-size:15px}
mark{background:#fff0a8;color:var(--ink);border-radius:2px;padding:0 1px}
.group h2{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}.group h2 small{font-weight:400;font-size:16px}
@media (max-width:767px){.board summary{padding-left:40px}.board .t{flex-basis:100%}.board .when{min-width:0}
.board .aux{max-width:none}
.board .body{padding-left:40px}.books{padding:28px 10px 0}}
"""
# 고유 주소로 들어왔을 때 펼친 항목을 화면 위로(자바스크립트가 꺼져 있어도 펼쳐진 채 보인다)
SCROLL_SCRIPT = '<script>(function(){var d=document.querySelector("details[data-here]");if(d)d.scrollIntoView({block:"start"});})();</script>'


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
    """게시판 한 줄. title이 없으면 preview(내용 앞부분)를 흐리게 보인다. aux·body는 이미 이스케이프한 HTML."""

    id: str
    link: str  # 고유 주소
    at: str
    title: str | None
    preview: str
    aux: str
    body: str
    text: str  # 맞은 부분 찾기용 평문(제목 밖에서 맞았을 때 한 줄 보이기)


def row_html(row: Row, q: str = "", open_: bool = False) -> str:
    if row.title:
        head = f'<span class="t">{mark(row.title, q)}</span>'
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
            f'<p class="muted"><a href="{html.escape(row.link)}">이 항목의 주소</a></p></div></details></li>')


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
    """기본 카테고리 하나(생각·문체·문헌)의 목록 화면 정의."""

    key: str
    name: str
    lanes: list[Lane]
    empty: str  # 빈 책장 안내(기존 문구 그대로)


KINDS: dict[str, Kind] = {
    "ideas": Kind("ideas", "생각", ["idea_me", "idea_ai"], f'아직 쌓인 생각이 없습니다. {SAY}"생각에 기록해 줘: …"'),
    "styles": Kind("styles", "문체", ["style", "style_passage"],
                   f'아직 모은 문장이 없습니다. {SAY}"이 문장을 문체에 넣어 줘: 「…」 — 짧게 끊어 읽히는 호흡이 좋다"'),
    "refs": Kind("refs", "문헌", ["ref_bib", "ref_picked"],
                 f'아직 등록한 문헌이 없습니다. {SAY}"받은함의 kremer1993.pdf를 문헌으로 등록해 줘. 쓸 부분은 「…」, 이유는 …"'),
}
DEFAULT_COLORS = {"ideas": "#1f2f5c", "styles": "#6e1f2f", "refs": "#1f4a3a"}  # 남색·자주·짙은 초록


class ShelfPages:
    """Web에 섞어 쓰는 책장 화면들. Web의 _page·user_of·_need_login·store를 쓴다."""

    store: Store
    _page: Callable[..., Response]
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]

    def shelf_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [
            ("/shelf", ["GET"], self.shelf),
            ("/shelf/{kind}", ["GET"], self.shelf_list),
            ("/shelf/{kind}/{item}", ["GET"], self.shelf_item),
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

    # --- 책장 ---
    def books(self, uid: str) -> list[Book]:
        counts = {"ideas": len(self.store.list_ideas(uid)), "styles": len(self.store.list_styles(uid)),
                  "refs": len(self.store.list_refs(uid))}
        return [Book(k, KINDS[k].name, "기본", counts[k], DEFAULT_COLORS[k], f"/shelf/{k}") for k in KINDS]

    async def shelf(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        q = clean_query(request.query_params.get("q"))
        form = (f'<form method="get" action="/shelf" class="search" role="search"><label>책장 전체에서 찾기 '
                f'<input type="search" name="q" value="{html.escape(q)}"></label><button>찾기</button></form>')
        if not q:
            body = (f"{form}{shelf_html([book_html(b) for b in self.books(uid)])}"
                    "<p>책을 누르면 그 카테고리의 목록이 열립니다.</p>")
            return self._shelf_page("책장", body, session)
        groups, total = [], 0
        for kind in KINDS.values():
            rows = await run_in_threadpool(self._rows, uid, kind.key, None, q)
            total += bool(rows)
            more = (f' <small><a href="/shelf/{kind.key}?q={urllib.parse.quote(q)}">{kind.name}에서 {len(rows)}개 모두 보기</a></small>'
                    if len(rows) > GROUP_SIZE else "")
            groups.append(
                f'<section class="group"><h2>{kind.name} <small>{len(rows)}개</small>{more}</h2>'
                + (f'<ol class="board">{"".join(row_html(r, q) for r in rows[:GROUP_SIZE])}</ol>' if rows else "<p>없음</p>")
                + "</section>"
            )
        head = (f'<p class="crumb"><a href="/shelf">← 책장</a></p>{form}'
                f"<p>「{html.escape(q)}」 " + ("찾은 카테고리 " + str(total) + "곳" if total else "찾는 말이 들어간 항목이 없습니다.")
                + (" · 한 글자는 그 글자가 들어간 항목을 최근 것부터 보입니다." if one_char(q) else "") + "</p>")
        return self._shelf_page("책장", head + "".join(groups), session)

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
        kind = KINDS.get(kind_key)
        if kind is None:
            return self._shelf_page("책장", '<p class="msg err">없는 카테고리입니다. <a href="/shelf">책장</a>으로 돌아가세요.</p>',
                                    session, 404)
        crumb = '<p class="crumb"><a href="/shelf">← 책장</a></p>'
        if not await run_in_threadpool(self._has_any, uid, kind.key):
            return self._shelf_page(kind.name, f'{crumb}<p class="msg">{kind.empty}</p>', session)
        params = request.query_params
        q = "" if item else clean_query(params.get("q"))
        filters = {} if item else {k: params.get(k, "") for k in ("author", "status", "tag", "project")}
        rows = await run_in_threadpool(self._rows, uid, kind.key, filters, q)
        page = 1
        if item:
            index = next((n for n, r in enumerate(rows) if r.id == item), None)
            if index is None:
                return self._shelf_page(kind.name, f'{crumb}<p class="msg err">없는 항목입니다(휴지통으로 옮겨졌을 수 있습니다). '
                                                   f'<a href="/shelf/{kind.key}">{kind.name} 목록</a></p>', session, 404)
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
        search = (f'<form method="get" action="/shelf/{kind.key}" class="search" role="search"><label>{kind.name}에서 찾기 '
                  f'<input type="search" name="q" value="{html.escape(q)}"></label>'
                  + "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in filters.items() if v)
                  + "<button>찾기</button></form>")
        summary = await run_in_threadpool(self._summary, uid, kind.key, filters)
        found = ""
        if q:
            found = (f"<p>「{html.escape(q)}」 찾은 항목 {len(rows)}개 · "
                     + ("최근 것부터(한 글자는 그 글자가 들어간 항목을 모두 찾습니다)" if one_char(q) else "많이 맞은 것부터")
                     + f' · <a href="/shelf/{kind.key}">검색 지우기</a></p>')
        board = (f'<ol class="board">{"".join(row_html(r, q, r.id == item) for r in shown)}</ol>'
                 if shown else '<p class="msg">찾는 말이 들어간 항목이 없습니다.</p>' if q else '<p class="msg">없음</p>')
        body = f"{crumb}{summary}{search}{found}{pager}{board}{pager}" + (SCROLL_SCRIPT if item else "")
        return self._shelf_page(kind.name, body, session)

    def _has_any(self, uid: str, kind: str) -> bool:
        return bool({"ideas": self.store.list_ideas, "styles": self.store.list_styles, "refs": self.store.list_refs}[kind](uid))

    def _summary(self, uid: str, kind: str, filters: dict[str, str]) -> str:
        """목록 위 한 줄: 개수와 거르기 링크(기존 화면과 같은 거르기)."""
        if kind == "ideas":
            ideas = self.store.list_ideas(uid)
            mine = sum(1 for i in ideas if i.author == "me")
            return (f"<p>생각 {len(ideas)}개(나 {mine} · AI {len(ideas) - mine}) · "
                    '<a href="/shelf/ideas">전체</a> · <a href="/shelf/ideas?author=me">나</a> · '
                    '<a href="/shelf/ideas?author=ai">AI</a></p>')
        if kind == "styles":
            tag = filters.get("tag", "")
            only = f' · 태그 「{html.escape(tag)}」만 · <a href="/shelf/styles">전체</a>' if tag else ""
            return f"<p>문장 {len(self.store.list_styles(uid))}개{only}</p>"
        refs = self.store.list_refs(uid)
        verified = sum(1 for r in refs if r.status == "verified")
        project = self.store.get_project(uid, filters.get("project") or None)
        q = f"project={urllib.parse.quote(project.id)}&" if project else ""
        checklist = f' · 인용 현황은 <a href="/checklist?{q}">인용 체크리스트</a>' if project else ""
        return (f"<p>문헌 {len(refs)}편(확인 {verified} · 미확인 {len(refs) - verified}){checklist}</p>"
                f'<p><a href="/shelf/refs?{q}">전체</a> · <a href="/shelf/refs?{q}status=verified">{LIGHTS["verified"][0]} '
                f'{LIGHTS["verified"][1]}</a> · <a href="/shelf/refs?{q}status=unverified">{LIGHTS["unverified"][0]} '
                f'{LIGHTS["unverified"][1]}</a></p>')

    def _rows(self, uid: str, kind: str, filters: dict[str, str] | None, q: str) -> list[Row]:
        """그 카테고리의 줄들. 검색어가 있으면 맞은 것만 검색 순서로, 없으면 기본 순서(생각·문체는 최근 것부터, 문헌은 확인한 것부터)."""
        filters = filters or {}
        build: dict[str, Callable[[str, dict[str, str], str], list[tuple[str, Row]]]] = {
            "ideas": self._idea_rows, "styles": self._style_rows, "refs": self._ref_rows}
        pairs = build[kind](uid, filters, q)
        if not q:
            return [row for _, row in pairs]
        order = {owner: n for n, owner in enumerate(find(self.store, uid, KINDS[kind].lanes, q))}
        return [row for owner, row in sorted((p for p in pairs if p[0] in order), key=lambda p: order[p[0]])]

    def _idea_rows(self, uid: str, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        ideas = list(reversed(self.store.list_ideas(uid)))
        author = filters.get("author") if filters.get("author") in ("me", "ai") else None
        rows = []
        for i in ideas:
            if author and i.author != author:
                continue
            who = "나" if i.author == "me" else '<span class="tag">AI</span>'
            back = (f'<p class="muted">AI의 답입니다. <a href="/shelf/ideas/{html.escape(i.parent_id)}">응답한 생각</a></p>'
                    if i.parent_id else "")
            origin = f'<p class="muted">출처: {html.escape(i.origin)}</p>' if i.origin else ""
            rows.append((i.id, Row(i.id, f"/shelf/ideas/{i.id}", i.created_at, None, i.text, who,
                                   paragraphs(i.text, q) + origin + back, i.text)))
        return rows

    def _style_rows(self, uid: str, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        tag = (filters.get("tag") or "").strip()
        rows = []
        for s in reversed(self.store.list_styles(uid)):
            tags = style_tags(s)
            if tag and tag not in tags:
                continue
            head = one_line(s.passage)
            title = f"「{head[:48]}{'…' if len(head) > 48 else ''}」"
            aux = " ".join([*([html.escape(s.work)] if s.work else []),
                            *(f'<span class="tag">{html.escape(t)}</span>' for t in tags[:2]),
                            *([f"외 {len(tags) - 2}"] if len(tags) > 2 else [])])
            pills = " ".join(f'<a class="tag" href="/shelf/styles?tag={urllib.parse.quote(t)}">{html.escape(t)}</a>' for t in tags)
            by = TAGS_BY.get(s.tags_by or "")  # 태그를 누가 정했나(#89). 기록 전 항목은 표시하지 않는다
            body = (f"<p>「{mark(s.passage, q).replace(chr(10), '<br>')}」</p>"
                    + (f'<p class="muted">출처: {mark(s.work, q)}</p>' if s.work else "")
                    + f"<p>이유: {mark(s.reason, q)}</p><p>{pills}</p>" + (f'<p class="muted">{by}</p>' if by else ""))
            rows.append((s.id, Row(s.id, f"/shelf/styles/{s.id}", s.created_at, title, s.passage, aux, body,
                                   f"{s.passage}\n{s.work or ''}\n{s.reason}")))
        return rows

    def _ref_rows(self, uid: str, filters: dict[str, str], q: str) -> list[tuple[str, Row]]:
        status = filters.get("status") if filters.get("status") in ("verified", "unverified") else None
        project = self.store.get_project(uid, filters.get("project") or None)
        cited: dict[str, list[str]] = {}
        if project is not None:
            report = build_cite_report(self.store, uid, project.id)
            cited = {key: list(dict.fromkeys(d.chapters)) for key, d in report.docs.items()}
        refs = sorted((r for r in self.store.list_refs(uid) if status is None or r.status == status),
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
            ])
            text = "\n".join([str(r.bib.get("authors") or ""), str(r.bib.get("container") or ""), *(p.text for p in passages)])
            rows.append((r.key, Row(r.key, f"/shelf/refs/{urllib.parse.quote(r.key)}", r.created_at, cite_label(r, r.key),
                                    "", aux, body, text)))
        return rows
