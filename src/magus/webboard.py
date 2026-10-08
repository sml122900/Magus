"""책 = 게시판 페이지(2026-10-09 사용자 요청). Web에 섞어 쓰는 BoardPages.

흐름: 지도 → 노드 → 책장(책 목록) → 책을 누르면 **별도 페이지**의 게시판(지도 옆 패널에 열리던 방식은 없앴다).
- 위치 표시(제목 위): 프로젝트 › 「프로젝트」 › 노드 › 책. 누르면 그 단계로 돌아간다.
- 게시판(/shelf/<책>): 한 줄 = 제목 · 첨부 표시(📎, 그림이면 작은 미리보기) · 날짜. 최신 글이 위, 20개씩, 오른쪽 위 '글쓰기' 하나.
  문헌 글(서지가 있는 글)도 같은 목록에 섞인다(제목은 서지). 거르기(전체·나·AI)·찾기·책 설정(⚙)은 그대로.
- 글쓰기(/shelf/write/<책>): 제목·본문·첨부. 파일을 끌어다 놓거나 '파일 고르기', 휴대폰은 '사진 찍기'(capture). 누가 = 저자.
- 글 보기(/shelf/<책>/<글>): 제목·본문·그림(글 안에 바로)·파일 목록(이름을 누르면 내려받기)·🗑(화면 안 확인 창 → 휴지통.
  응답한 글·첨부도 함께, 되살리기는 프로젝트의 휴지통 화면). 웹에서 글 고치기·원문 확인 체크는 없다(MCP 도구는 그대로).
  칸(인물·사례 등)은 본문 아래 "칸: 값" 줄. 이유·위치·쓸 부분(일반 글)·태그·원문 확인 표시는 파일에 그대로 있고 보이지 않는다.
- 모든 출력은 이스케이프하고, 첨부 주소는 세션의 사용자 폴더에서만 찾는다(magus.webshelf.shelf_file).
"""

from __future__ import annotations

import html
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from magus.attachments import ACCEPT, MAX_FILES, kind_of, media_type, size_text
from magus.book_migrate import legacy_book_id
from magus.category.rules import BUILTINS, CONTENT_MAX, TITLE_MAX
from magus.contexts import view_for_book
from magus.ids import local_time, new_id
from magus.melchior.author_report import cite_label
from magus.store import Attachment, CategoryItem, Store
from magus.store.formats import one_line
from magus.webcontexts import contexts_view_html
from magus.webshelf import (
    AI_MARK, AI_TITLE, GEAR, Book, Kind, clean_query, find, mark, paragraphs, snippet, state_url,
)

BOARD_SIZE = 20  # 게시판 한 쪽
SEP = ' <span aria-hidden="true">›</span> '
WHEN = "%Y-%m-%d %H:%M"
DONE = {"made": "만들었습니다.", "edit": "저장했습니다.", "trashed": "휴지통으로 옮겼습니다.", "restored": "되살렸습니다."}

BOARD_STYLE = """
.trail{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;margin:0 0 4px;color:var(--ink2);font-size:15px}
.trail a{text-decoration:none}.trail a:hover{text-decoration:underline}.trail [aria-current]{color:var(--ink);font-weight:600}
.board-bar{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:8px 0}
.board-bar .sum{margin:0;color:var(--ink2);display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center}
.board-bar .write-btn{margin-left:auto}
a.button{display:inline-flex;align-items:center;min-height:44px;padding:8px 18px;border-radius:9999px;background:var(--primary);color:#fff;
text-decoration:none;font-weight:600}a.button:hover{background:var(--press);color:#fff}
ol.posts{list-style:none;margin:8px 0;padding:0;background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
ol.posts>li{border-bottom:1px solid var(--line)}ol.posts>li:last-child{border-bottom:0}
a.post{display:grid;grid-template-columns:minmax(0,1fr) auto 10.5em;gap:4px 16px;align-items:center;padding:10px 16px;min-height:52px;
text-decoration:none;color:var(--ink)}
a.post:hover .pt,a.post:focus-visible .pt{text-decoration:underline}
.pt{font-weight:600;font-size:17px;overflow:hidden;text-overflow:ellipsis}.pt.none{font-weight:400;color:var(--mute)}
.pt .tag{font-size:13px;font-weight:400;margin-left:8px;vertical-align:1px}
.pa{display:flex;gap:6px;align-items:center;color:var(--ink2);white-space:nowrap}
.pa img.thumb{width:44px;height:44px;object-fit:cover;border-radius:6px;border:1px solid var(--line);background:var(--soft)}
.pd{color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}
ol.posts small.hit{display:block;padding:0 16px 10px;color:var(--ink2);font-size:15px}
.pages{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0}
.pages a,.pages span{display:inline-flex;min-width:40px;min-height:40px;align-items:center;justify-content:center;border-radius:9999px;
text-decoration:none;padding:0 10px}.pages [aria-current]{background:var(--primary);color:#fff}
.post-meta{color:var(--ink2);display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center}
.post-body{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:8px 20px;margin:12px 0;box-shadow:var(--shadow)}
.post-body blockquote{margin:8px 0;padding:4px 12px;border-left:3px solid var(--line);color:var(--ink2)}
.pics{display:grid;gap:12px;margin:12px 0}.pics img{display:block;max-width:100%;height:auto;border-radius:8px;border:1px solid var(--line)}
.post-acts{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:12px 0}
.post-acts details.del{position:relative}
.post-acts details.del>summary{list-style:none;display:inline-flex;align-items:center;justify-content:center;min-width:44px;min-height:44px;
border-radius:9999px;cursor:pointer;font-size:20px;border:1px solid var(--line);background:var(--canvas)}
.post-acts details.del>summary::-webkit-details-marker{display:none}.post-acts details.del>summary:hover{background:var(--soft)}
.post-acts .del-box{margin-top:8px;width:min(380px,100%);background:var(--canvas);border:1px solid var(--line);border-left:4px solid var(--ruby);
border-radius:10px;padding:4px 16px;box-shadow:0 8px 24px rgb(0 0 0/.18)}.post-acts .del-box p{margin:10px 0}
.write-form textarea{min-height:220px}
.dropzone{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;padding:16px;border:2px dashed var(--mute);border-radius:12px;background:var(--soft)}
.dropzone.over{border-color:var(--primary);background:#ecebff}
.dropzone label.pick{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;border-radius:9999px;border:1px solid var(--primary);
color:var(--primary);background:var(--canvas);cursor:pointer;margin:0;position:relative}
.dropzone label.pick:focus-within{outline:3px solid var(--primary);outline-offset:2px}
.dropzone input[type=file]{position:absolute;inset:0;opacity:0;width:1px;height:1px}
.dropzone .drop-word{color:var(--ink2)}
@media (pointer:fine){.dropzone label.camera{display:none}}
ul.chosen{list-style:none;padding:0;margin:8px 0;display:flex;flex-wrap:wrap;gap:8px}
ul.chosen li{display:flex;gap:6px;align-items:center;background:var(--canvas);border:1px solid var(--line);border-radius:8px;padding:4px 8px}
ul.chosen img{width:40px;height:40px;object-fit:cover;border-radius:4px}
@media (max-width:767px){a.post{grid-template-columns:minmax(0,1fr) auto;padding:10px 12px}.pd{grid-column:1/-1;text-align:left;font-size:14px}
.board-bar .write-btn{margin-left:0}}
"""

# 글 보기의 🗑 확인 창: 열면 첫 단추로 초점, Esc로 닫는다(스크립트가 없어도 details라 열고 닫힌다)
DEL_SCRIPT = """<script>
document.addEventListener("toggle", function (e) {
  var d = e.target;
  if (d.matches && d.matches("details.del") && d.open) { var b = d.querySelector(".del-box button"); if (b) b.focus(); }
}, true);
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  document.querySelectorAll("details.del[open]").forEach(function (d) { d.open = false; d.querySelector("summary").focus(); });
});
</script>"""

# 글쓰기: 끌어다 놓은 파일을 '파일 고르기' 칸에 더하고, 고른 파일(그림은 작은 미리보기)을 보인다. 스크립트가 꺼져 있어도 고르기·사진 찍기는 된다
WRITE_SCRIPT = """<script>
(function () {
  var zone = document.querySelector("[data-dropzone]");
  if (!zone) return;
  var pick = zone.querySelector("input[name=files][multiple]"), inputs = zone.querySelectorAll("input[type=file]");
  var list = document.querySelector("ul.chosen");
  function show() {
    list.textContent = "";
    inputs.forEach(function (input) {
      Array.prototype.forEach.call(input.files || [], function (f) {
        var li = document.createElement("li");
        if (/^image\\//.test(f.type) && window.URL) { var img = document.createElement("img"); img.alt = ""; img.src = URL.createObjectURL(f); li.appendChild(img); }
        li.appendChild(document.createTextNode(f.name));
        list.appendChild(li);
      });
    });
  }
  inputs.forEach(function (input) { input.addEventListener("change", show); });
  ["dragenter", "dragover"].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.add("over"); }); });
  ["dragleave", "drop"].forEach(function (t) { zone.addEventListener(t, function () { zone.classList.remove("over"); }); });
  zone.addEventListener("drop", function (e) {
    e.preventDefault();
    if (!e.dataTransfer || !e.dataTransfer.files.length || !window.DataTransfer) return;
    var dt = new DataTransfer();
    Array.prototype.forEach.call(pick.files || [], function (f) { dt.items.add(f); });
    Array.prototype.forEach.call(e.dataTransfer.files, function (f) { dt.items.add(f); });
    pick.files = dt.files; show();
  });
})();
</script>"""


@dataclass
class Post:
    """게시판 한 줄. title이 없으면 preview(본문 앞부분)를 흐리게. badge는 이미 이스케이프한 HTML."""

    id: str
    link: str
    at: str
    title: str | None
    preview: str
    badge: str
    files: tuple[Attachment, ...]
    text: str = ""  # 찾기의 맞은 곳 한 줄(제목 밖에서 맞았을 때)


def _inline_image(name: str) -> bool:
    media, inline = media_type(name)
    return inline and media.startswith("image/")


def post_row_html(post: Post, q: str = "") -> str:
    """게시판 한 줄: 제목 · 첨부 표시(📎, 그림이면 작은 미리보기) · 날짜. 누르면 글 보기 페이지."""
    if post.title:
        shown = mark(post.title, q)
        head = f'<span class="pt">{shown}{post.badge}</span>'
    else:
        preview = one_line(post.preview)
        shown = mark(preview[:80] + ("…" if len(preview) > 80 else "") or "(제목 없음)", q)
        head = f'<span class="pt none">{shown}{post.badge}</span>'
    hit = snippet(post.text, q) if q and "<mark>" not in shown else ""  # 제목 밖에서 맞았으면 맞은 곳 한 줄
    pic = next((a for a in post.files if _inline_image(a.name)), None)
    thumb = (f'<img class="thumb" src="{html.escape(post.link)}/files/{html.escape(pic.id)}" alt="" loading="lazy">' if pic else "")
    count = len(post.files)
    clip = (f'<span aria-label="첨부 {count}개" title="첨부 {count}개">📎{count if count > 1 else ""}</span>' if count else "")
    return (f'<li><a class="post" href="{html.escape(post.link)}">{head}<span class="pa">{thumb}{clip}</span>'
            f'<time class="pd" datetime="{html.escape(post.at)}">{local_time(post.at, WHEN)}</time></a>'
            + (f'<small class="hit">{hit}</small>' if hit else "") + "</li>")


class BoardPages:
    """Web에 섞어 쓰는 게시판 페이지. ShelfPages의 _kind·_legacy_target·book_objects·_read_files·_too_big·_write_error와
    Web의 _page·user_of·_need_login·_form·_csrf_input·store를 쓴다."""

    store: Store
    settings: Any
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]
    _csrf_input: Callable[[tuple[str, str]], str]
    _form: Callable[[Request, tuple[str, str]], Awaitable[Any]]
    _shelf_page: Callable[..., Response]
    _kind: Callable[[str, str], Kind | None]
    _kind_any: Callable[..., Kind | None]
    _legacy_target: Callable[[str, str, str | None], str | None]
    book_objects: Callable[[str, Any], list[Book]]
    _read_files: Callable[[str, Any], Awaitable[tuple[list[tuple[str, bytes]], str]]]
    _too_big: Callable[[Request], bool]
    _write_error: Callable[[str], str]
    _post_actions: Callable[..., str]  # 글 지우기(🗑, webshelf)

    # ---- 위치 표시 -----------------------------------------------------------------------------
    def trail(self, uid: str, key: str, here: str | None = None) -> str:
        """프로젝트 › 「프로젝트」 › 노드 › 책(› here). here가 있으면 책도 링크다."""
        parts = ['<a href="/shelf">프로젝트</a>']
        where = self.store.node_of_book(uid, key)
        if where is not None:
            floor = self.store.get_floor(uid, where[0])
            found = self.store.get_map(uid, where[0])
            node = found.node(where[1]) if found else None
            if floor is not None:
                parts.append(f'<a href="{html.escape(state_url(floor.id))}">{html.escape(floor.label)}</a>')
                if node is not None:
                    parts.append(f'<a href="{html.escape(state_url(floor.id, node=node.id))}">'
                                 f'{html.escape("가운데" if node.center else node.name)}</a>')
        book = next(iter(self.book_objects(uid, [key])), None)
        if book is not None:
            parts.append(f'<a href="{html.escape(book.href or "")}">{html.escape(book.name)}</a>' if here
                         else f'<span aria-current="page">{html.escape(book.name)}</span>')
        if here:
            parts.append(f'<span aria-current="page">{html.escape(here)}</span>')
        return f'<nav class="trail" aria-label="위치">{SEP.join(parts)}</nav>'

    # ---- 게시판 ---------------------------------------------------------------------------------
    def _posts(self, uid: str, kind: Kind, filters: dict[str, str] | None, q: str) -> list[Post]:
        """그 책의 글과 문헌 글. 최신 글이 위(찾기면 많이 맞은 것부터). 나·AI·태그로 거르면 글만."""
        assert kind.category is not None
        c = kind.category
        filters = filters or {}
        author = filters.get("author") if filters.get("author") in ("me", "ai") else None
        tag = (filters.get("tag") or "").strip()
        pairs: list[tuple[str, Post]] = []
        for i in self.store.list_category_items(uid, c.id):
            if (author and i.author != author) or (tag and tag not in i.tags):
                continue
            link = f"/shelf/{c.id}/{i.id}"
            files = tuple(self.store.list_attachments(uid, f"{c.id}/{i.id}"))
            preview = i.content or " · ".join(f"{k}: {v}" for k, v in i.fields.items() if v) or " · ".join(a.name for a in files)
            badge = (AI_MARK if i.author == "ai" else "") + (AI_TITLE if i.title and i.title_by == "ai" else "")
            text = "\n".join([i.content, i.reason or "", i.where or "", *(p.text for p in i.passages),
                              *(f"{k} {v}" for k, v in i.fields.items()), " ".join(i.tags)]) if q else ""
            pairs.append((i.id, Post(i.id, link, i.created_at, i.title, preview, badge, files, text)))
        if not author and not tag:
            for r in self.store.list_refs(uid, book=c.id):
                link = f"/shelf/{c.id}/{urllib.parse.quote(r.key)}"
                files = tuple(self.store.list_attachments(uid, f"ref:{r.key}"))
                text = ("\n".join([str(r.bib.get("authors") or r.bib.get("raw") or ""), str(r.bib.get("container") or ""),
                                   str(r.bib.get("memo") or ""), *(p.text for p in self.store.get_passages(uid, r.key))]) if q else "")
                pairs.append((r.key, Post(r.key, link, r.created_at, cite_label(r, r.key), "", "", files, text)))
        if not q:
            return [p for _, p in sorted(pairs, key=lambda kv: (kv[1].at, kv[0]), reverse=True)]
        order: dict[str, int] = {}
        for owner in find(self.store, uid, kind.lanes, q):  # 글은 "<책 id>/<글 id>", 문헌 글은 key
            local = owner.split("/", 1)[1] if owner.startswith(f"{c.id}/") else owner if "/" not in owner else None
            if local is not None and local not in order:
                order[local] = len(order)
        return [p for k, p in sorted((kv for kv in pairs if kv[0] in order), key=lambda kv: order[kv[0]])]

    async def board_list(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        key = request.path_params["kind"]
        if key.startswith(("ms.", "doc.")):  # 올린 문서·만든 문서는 각자의 페이지(#94)
            base, _, ident = key.partition(".")
            return RedirectResponse(f"/shelf/{'book' if base == 'ms' else 'doc'}/{urllib.parse.quote(ident)}", status_code=302)
        if key in BUILTINS or key.partition(".")[0] in BUILTINS:  # 예전 주소(/shelf/ideas, ideas.<프로젝트>) → 이전으로 생긴 책
            target = await run_in_threadpool(lambda: self._legacy_target(uid, key, None) if key in BUILTINS
                                             else legacy_book_id(*key.split(".", 1)))
            if target:
                query = f"?{request.url.query}" if request.url.query else ""
                return RedirectResponse(f"/shelf/{target}{query}", status_code=302)
        kind = await run_in_threadpool(self._kind, uid, key)
        if kind is None or kind.category is None:
            return self._shelf_page("책장", '<p class="msg err">없는 책입니다. <a href="/shelf">프로젝트</a></p>', session, 404)
        params = request.query_params
        q = clean_query(params.get("q"))
        filters = {k: params.get(k, "") for k in ("author", "tag")}
        posts = await run_in_threadpool(self._posts, uid, kind, filters, q)
        try:
            page = max(1, int(params.get("page") or 1))
        except ValueError:
            page = 1
        pages = max(1, -(-len(posts) // BOARD_SIZE))
        page = min(page, pages)
        shown = posts[(page - 1) * BOARD_SIZE: page * BOARD_SIZE]
        body = await run_in_threadpool(self._board_body, uid, session, kind, filters, q, posts, shown, page, pages, params)
        lead = await run_in_threadpool(self.trail, uid, kind.key)
        return self._shelf_page(kind.name, body, session, lead=lead)

    def _board_body(self, uid: str, session: tuple[str, str], kind: Kind, filters: dict[str, str], q: str, posts: list[Post],
                    shown: list[Post], page: int, pages: int, params: Any) -> str:
        assert kind.category is not None
        c = kind.category
        base = f"/shelf/{c.id}"
        done = DONE.get(params.get("done") or "")
        name = f"「{c.name}」 " if params.get("done") in ("made", "edit") else ""
        trash = (f' <a href="/shelf/p/{urllib.parse.quote(c.floor)}/trash">휴지통</a>' if params.get("done") == "trashed" else "")
        message = f'<p class="msg">{html.escape(name)}{done}{trash}</p>' if done else ""
        items = self.store.list_category_items(uid, c.id)
        links = []
        if items and any(i.author == "ai" for i in items):
            links = [f'<a href="{base}">전체</a>', f'<a href="{base}?author=me">나</a>', f'<a href="{base}?author=ai">AI</a>']
        if tag := filters.get("tag", ""):
            links = [f'<span class="tag">{html.escape(tag)}</span>', f'<a href="{base}">전체</a>']
        context = contexts_view_html(view_for_book(self.store, uid, c.id))
        bar = (f'<div class="board-bar"><p class="sum">글 {len(items) + c.sources}' + (f' · {" · ".join(links)}' if links else "") + "</p>"
               + GEAR.format(href=f"/shelf/edit/{c.id}", label="책 설정")
               + f'<a class="button write-btn" href="/shelf/write/{c.id}">글쓰기</a></div>')
        search = (f'<form method="get" action="{base}" class="search" role="search">'
                  f'<input type="search" name="q" value="{html.escape(q)}" aria-label="{html.escape(c.name)}에서 찾기">'
                  + "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in filters.items() if v)
                  + "<button>찾기</button></form>")
        found = f'<p>「{html.escape(q)}」 {len(posts)} · <a href="{base}">지우기</a></p>' if q else ""
        if shown:
            board = f'<ol class="posts">{"".join(post_row_html(p, q) for p in shown)}</ol>'
        else:
            board = '<p class="msg">없음</p>' if q else '<p class="empty">글이 없습니다.</p>'
        keep = [(k, v) for k, v in params.multi_items() if k not in ("page", "done")]

        def link(n: int, label: str, current: bool = False) -> str:
            if current:
                return f'<span aria-current="page">{label}</span>'
            return f'<a href="{base}?{html.escape(urllib.parse.urlencode([*keep, ("page", n)]))}">{label}</a>'

        pager = ""
        if pages > 1:
            nums = [n for n in range(1, pages + 1) if n in (1, pages) or abs(n - page) <= 2]
            out, last = [], 0
            for n in nums:
                if n - last > 1:
                    out.append("<span>…</span>")
                out.append(link(n, str(n), n == page))
                last = n
            prev = [link(page - 1, "이전")] if page > 1 else []
            nxt = [link(page + 1, "다음")] if page < pages else []
            pager = f'<nav class="pages" aria-label="쪽">{"".join([*prev, *out, *nxt])}</nav>'
        return f"{message}{context}{bar}{search}{found}{board}{pager}"

    # ---- 글 보기 -------------------------------------------------------------------------------
    def _find_post(self, uid: str, kind: Kind, item_id: str) -> Any:
        """글(CategoryItem) 또는 그 책의 문헌 글(Ref). 없으면 None."""
        assert kind.category is not None
        try:
            item = self.store.get_category_item(uid, kind.category.id, item_id)
        except ValueError:
            item = None
        if item is not None:
            return item
        ref = self.store.get_ref(uid, item_id) if item_id and "/" not in item_id else None
        return ref if ref is not None and ref.key == item_id and ref.book == kind.category.id else None

    async def post_view(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        key, item_id = request.path_params["kind"], request.path_params["item"]
        if key in BUILTINS:  # 예전 주소(/shelf/ideas/<id>, /shelf/refs/<key>) → 그 글이 든 책
            target = await run_in_threadpool(self._legacy_target, uid, key, item_id)
            if target:
                return RedirectResponse(f"/shelf/{target}/{urllib.parse.quote(item_id)}", status_code=302)
        kind = await run_in_threadpool(self._kind_any, uid, key, item_id)
        if kind is None or kind.category is None:
            return self._shelf_page("책장", '<p class="msg err">없는 책입니다. <a href="/shelf">프로젝트</a></p>', session, 404)
        obj = await run_in_threadpool(self._find_post, uid, kind, item_id)
        if obj is None:
            return self._shelf_page(kind.name, f'<p class="msg err">없는 글입니다. <a href="/shelf/{kind.key}">{html.escape(kind.name)}</a></p>',
                                    session, 404, lead=await run_in_threadpool(self.trail, uid, kind.key, "글"))
        title, body = await run_in_threadpool(self._post_body, uid, session, kind, obj, request.query_params)
        lead = await run_in_threadpool(self.trail, uid, kind.key, title[:40] + ("…" if len(title) > 40 else ""))
        return self._shelf_page(title, body, session, lead=lead)

    def _post_body(self, uid: str, session: tuple[str, str], kind: Kind, obj: Any, params: Any) -> tuple[str, str]:
        assert kind.category is not None
        if isinstance(obj, CategoryItem):
            link = f"/shelf/{kind.category.id}/{obj.id}"
            owner = f"{kind.category.id}/{obj.id}"
            files = self.store.list_attachments(uid, owner)
            preview = one_line(obj.content or " · ".join(f"{k}: {v}" for k, v in obj.fields.items() if v)
                               or " · ".join(a.name for a in files))  # 게시판 줄과 같은 규칙
            title = obj.title or (preview[:40] + ("…" if len(preview) > 40 else "")) or "제목 없음"
            meta = ([local_time(obj.created_at, WHEN)] + (["AI가 쓴 글"] if obj.author == "ai" else [])
                    + (["제목은 AI가 지음"] if obj.title and obj.title_by == "ai" else []))
            # 칸(인물·사례 등)은 본문의 일부로 보인다. 이유·위치·쓸 부분·태그는 파일에 그대로(보이지 않을 뿐)
            text = paragraphs(obj.content) + "".join(f"<p>{html.escape(k)}: {html.escape(v)}</p>" for k, v in obj.fields.items() if v)
        else:
            link = f"/shelf/{kind.category.id}/{urllib.parse.quote(obj.key)}"
            owner = f"ref:{obj.key}"
            title = cite_label(obj, obj.key)
            meta = [local_time(obj.created_at, WHEN)]
            text = ((paragraphs(str(obj.bib.get("memo"))) if obj.bib.get("memo") else "")
                    + "".join(f"<blockquote>「{html.escape(p.text)}」</blockquote>" for p in self.store.get_passages(uid, obj.key))
                    + (f'<p class="muted">→ 「내 서재」 {local_time(obj.moved.get("at", ""), WHEN)} · {html.escape(obj.moved.get("reason", ""))}</p>'
                       if obj.moved and obj.moved.get("to") == obj.floor else ""))  # 저자 모르게 배치가 바뀌지 않게(#93-a)
            files = self.store.list_attachments(uid, owner)
        pics = [a for a in files if _inline_image(a.name)]
        rest = [a for a in files if not _inline_image(a.name)]
        pictures = "".join(
            f'<a href="{html.escape(link)}/files/{html.escape(a.id)}" target="_blank" rel="noopener">'
            f'<img src="{html.escape(link)}/files/{html.escape(a.id)}" alt="{html.escape(a.name)}" loading="lazy"></a>' for a in pics)
        others = "".join(
            f'<li><a href="{html.escape(link)}/files/{html.escape(a.id)}" download>{html.escape(a.name)}</a> '
            f'<small>{html.escape(kind_of(a.name))} · {size_text(a.size)}</small></li>' for a in rest)
        done = DONE.get(params.get("done") or "")
        body = ((f'<p class="msg">{done}</p>' if done else "")
                + f'<p class="post-meta">{html.escape(" · ".join(meta))}</p>'
                + (f'<div class="post-body">{text}</div>' if text.strip() else "")
                + (f'<div class="pics">{pictures}</div>' if pictures else "")
                + (f'<ul class="files" aria-label="첨부">{others}</ul>' if others else "")
                + self._post_actions(uid, session, kind, obj, link) + DEL_SCRIPT)
        return title, body

    # ---- 글쓰기 ---------------------------------------------------------------------------------
    async def board_write(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        kind = await run_in_threadpool(self._kind_any, uid, request.path_params["kind"])
        if kind is None or kind.category is None:
            return self._shelf_page("책장", '<p class="msg err">없는 책입니다. <a href="/shelf">프로젝트</a></p>', session, 404)
        book = kind.category.id
        here = f"/shelf/write/{book}"
        if request.method == "POST":
            if self._too_big(request):  # 다 받기 전에 거른다
                return RedirectResponse(f"{here}?error=big", status_code=303)
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("글쓰기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            content = str(form.get("content") or "").strip()[:CONTENT_MAX]
            title = one_line(str(form.get("title") or ""))[:TITLE_MAX] or None
            files, code = await self._read_files(uid, form)
            if code:
                return RedirectResponse(f"{here}?error={code}", status_code=303)
            if not content and not title and not files:
                return RedirectResponse(f"{here}?error=empty", status_code=303)

            def save() -> CategoryItem:
                item = self.store.put_category_item(uid, CategoryItem(new_id(), book, content, "me", title, "author" if title else None))
                for name, data in files:
                    self.store.put_attachment(uid, f"{book}/{item.id}", name, data)
                return item

            item = await run_in_threadpool(save)
            return RedirectResponse(f"/shelf/{book}/{item.id}", status_code=303)
        error = self._write_error(request.query_params.get("error") or "")
        body = (
            (f'<p class="msg err">{error}</p>' if error else "")
            + f'<form method="post" action="{here}" enctype="multipart/form-data" class="card write-form">{self._csrf_input(session)}'
            f'<label class="block">제목 <input name="title" maxlength="{TITLE_MAX}"></label>'
            f'<label class="block">본문 <textarea name="content" rows="10" maxlength="{CONTENT_MAX}"></textarea></label>'
            '<fieldset><legend>첨부</legend><div class="dropzone" data-dropzone>'
            f'<label class="pick">파일 고르기<input type="file" name="files" multiple accept="{ACCEPT}"></label>'
            '<label class="pick camera">사진 찍기<input type="file" name="files" accept="image/*" capture="environment"></label>'
            f'<span class="drop-word">끌어다 놓기 · {MAX_FILES}개까지</span></div>'
            '<ul class="chosen" aria-live="polite"></ul></fieldset>'
            f'<p><button class="primary">저장</button> <a href="/shelf/{book}">취소</a></p></form>{WRITE_SCRIPT}'
        )
        lead = await run_in_threadpool(self.trail, uid, kind.key, "글쓰기")
        return self._shelf_page("글쓰기", body, session, 400 if error else 200, lead=lead)
