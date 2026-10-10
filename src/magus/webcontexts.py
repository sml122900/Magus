"""컨텍스트 화면 부품(사용자 결정 #96, 2026-10-08): 붙이기 단추, 그 자리에서 고치기, 직접 적기, 자주 쓰는 컨텍스트로 등록,
노드·책 머리의 컨텍스트 표시, 내 정보 아래 '자주 쓰는 컨텍스트' 관리(/me/contexts).

- 자주 쓰는 컨텍스트는 단추(체크 상자)로 보인다. 누르면 붙고(아래 목록에 사본이 생긴다), 다시 누르면 떨어진다.
  붙인 것은 그 자리에서 고칠 수 있다(등록해 둔 원본은 그대로). '자주 쓰는 컨텍스트로 등록'으로 지금 글을 목록에 더한다.
- 스크립트가 없어도 된다: 단추를 고르고 저장하면 붙고, 붙인 줄의 '떼기'를 고르고 저장하면 떨어진다.
- 컨텍스트는 저자가 적은 'AI가 이 글을 읽는 방법'이다. 서버의 일(장 나누기·확인 요청·인용 점검)은 컨텍스트와 상관없다.
"""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from magus.contexts import CONTEXT_MAX, CONTEXT_NAME_MAX, HEADER_MAX, MAX_SAVED, Context, SavedContext, View, clean_contexts, name_key
from magus.floors import josa
from magus.store import Store

CONTEXT_STYLE = """
fieldset.ctx .chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0;align-items:center}
fieldset.ctx .ctx-pick-title{margin:8px 0 0;font-weight:600}
.ctx-make{display:inline-block}.ctx-make>summary{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;border:1px dashed var(--mute);
border-radius:999px;cursor:pointer;font-weight:600;list-style:none}.ctx-make>summary::-webkit-details-marker{display:none}
.ctx-make[open]{display:block;flex-basis:100%;border:1px dashed var(--mute);border-radius:10px;padding:0 12px 8px}
.ctx-make[open]>summary{border:0;padding:0}
.ctx-manage{display:inline-flex;align-items:center;min-height:44px;padding:0 6px}
.saved-ctx .acts{margin-top:8px}.saved-ctx .node-del{margin-left:0}
.saved-ctx .del-box ul{margin:4px 0 8px;padding-left:20px}
.chip-toggle{display:inline-flex;align-items:center;gap:6px;margin:0;padding:6px 14px;min-height:44px;border:1px solid var(--mute);
border-radius:999px;background:var(--canvas);cursor:pointer;font-weight:600}
.chip-toggle input{width:18px;height:18px;margin:0}
.chip-toggle:has(input:checked){background:var(--primary);border-color:var(--primary);color:#fff}
.chip-toggle:has(input:focus-visible){outline:3px solid var(--primary);outline-offset:2px}
ol.ctx-rows{list-style:none;padding:0;margin:8px 0;display:grid;gap:8px}
ol.ctx-rows>li{border:1px solid var(--line);border-radius:10px;padding:8px 12px;background:var(--canvas)}
ol.ctx-rows .row-head{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
ol.ctx-rows .row-head input[name=ctx_name]{width:12em}
ol.ctx-rows textarea{min-height:72px;margin-top:6px}
fieldset.ctx textarea{min-height:72px}
ol.ctx-rows .drop{margin-left:auto}
.ctxs{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:baseline;margin:6px 0 10px}
.ctxs .ctx-label{color:var(--ink2);font-size:15px}
.ctxs .ctx-sep{color:var(--ink2);font-weight:600}
.ctxs details.ctx{display:inline-block}
.ctxs .ctx-chip{display:inline-block;padding:2px 12px;border-radius:999px;background:#eef0fb;border:1px solid #b9b9f9}
.ctxs details.ctx>summary{display:inline-block;padding:2px 12px;border-radius:999px;background:#eef0fb;border:1px solid #b9b9f9;
cursor:pointer;font-weight:600;list-style:none}
.ctxs details.ctx>summary::-webkit-details-marker{display:none}
.ctxs details.ctx[open]{display:block;flex-basis:100%}
.ctxs details.ctx>p{margin:6px 0 4px;padding:8px 12px;background:var(--canvas);border-left:4px solid #b9b9f9;white-space:pre-line}
.ctxs .none{color:var(--ink2);font-size:15px}.ctxs .nowrap{white-space:nowrap}
.saved-ctx{border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:12px 0;background:var(--canvas)}
.saved-ctx textarea{min-height:88px}
"""

# 단추를 누르면 그 자리에 사본 줄을 더하고, 다시 누르면 뺀다. '떼기'를 누르면 그 줄을 바로 뺀다. 등록 단추의 번호를 맞춘다.
CONTEXT_SCRIPT = """<script>
(function () {
  document.querySelectorAll("fieldset.ctx").forEach(function (fs) {
    var list = fs.querySelector("ol.ctx-rows"), tpl = fs.querySelector("template.ctx-row");
    if (!list || !tpl) return;
    function renumber() {
      list.querySelectorAll("li").forEach(function (li, i) {
        var reg = li.querySelector("button[name=register]"); if (reg) reg.value = String(i);
        var drop = li.querySelector("input[name=ctx_drop]"); if (drop) drop.value = String(i);
      });
      var empty = fs.querySelector(".ctx-empty"); if (empty) empty.hidden = list.children.length > 0;
    }
    function add(chip) {
      var li = tpl.content.firstElementChild.cloneNode(true);
      li.dataset.from = chip.value;
      li.querySelector("input[name=ctx_from]").value = chip.value;
      li.querySelector("input[name=ctx_name]").value = chip.dataset.name || "";
      li.querySelector("textarea[name=ctx_text]").value = chip.dataset.text || "";
      list.appendChild(li); renumber();
    }
    fs.querySelectorAll("input[name=ctx_pick]").forEach(function (chip) {
      chip.addEventListener("change", function () {
        var row = list.querySelector('li[data-from="' + chip.value + '"]');
        if (chip.checked && !row) add(chip);
        if (!chip.checked && row) { row.remove(); renumber(); }
      });
    });
    list.addEventListener("change", function (e) {
      if (!e.target.matches("input[name=ctx_drop]")) return;
      var li = e.target.closest("li"), from = li.dataset.from;
      if (from) { var chip = fs.querySelector('input[name=ctx_pick][value="' + from + '"]'); if (chip) chip.checked = false; }
      li.remove(); renumber();
    });
    renumber();
  });
})();
</script>"""


def _row(index: int, ctx: Context, from_id: str) -> str:
    return (
        f'<li data-from="{html.escape(from_id)}"><div class="row-head">'
        f'<label>이름 <input name="ctx_name" value="{html.escape(ctx.name)}" data-count-max="{CONTEXT_NAME_MAX}"></label>'
        f'<input type="hidden" name="ctx_from" value="{html.escape(from_id)}">'
        f'<button name="register" value="{index}" aria-label="자주 쓰는 컨텍스트로 등록" title="자주 쓰는 컨텍스트로 등록">등록</button>'
        f'<label class="drop"><input type="checkbox" name="ctx_drop" value="{index}"> 떼기</label></div>'
        f'<label class="block">내용 <textarea name="ctx_text" data-count-max="{CONTEXT_MAX}" rows="3">{html.escape(ctx.text)}</textarea></label></li>'
    )


PICK_TITLE = "자주 쓰는 컨텍스트에서 고르기"
MANAGE = '<a class="ctx-manage" href="/me/contexts">관리 →</a>'


def make_box() -> str:
    """칩 줄 끝 '+ 새로 만들기'(2026-10-11): 그 자리에서 이름·내용을 적고 [등록하고 붙이기] → 자주 쓰는 컨텍스트에 더하고 여기에 붙인다.
    스크립트 없이도 된다(폼의 register=new). 저장만 누르면 적은 것은 이름 붙은 사본으로 붙는다(등록은 하지 않는다)."""
    return ('<details class="ctx-make"><summary>+ 새로 만들기</summary>'
            f'<label class="block">이름 <input name="ctx_make_name" data-count-max="{CONTEXT_NAME_MAX}"></label>'
            f'<label class="block">내용 <textarea name="ctx_make_text" data-count-max="{CONTEXT_MAX}" rows="3"></textarea></label>'
            '<p><button name="register" value="new">등록하고 붙이기</button></p></details>')


def context_fieldset(saved: list[SavedContext], attached: tuple[Context, ...]) -> str:
    """노드·책 만들기와 설정 화면의 컨텍스트 칸. attached: 지금 붙은 것(사본).
    2026-10-11: 단추 줄이 '자주 쓰는 컨텍스트'라는 것을 제목으로 보이고, 줄 끝에 '+ 새로 만들기'와 '관리 →'(내 정보 › 자주 쓰는 컨텍스트)."""
    by_name = {s.name: s for s in saved}
    picked = {by_name[c.name].id for c in attached if c.name in by_name and by_name[c.name].text == c.text}
    chips = "".join(
        f'<label class="chip-toggle"><input type="checkbox" name="ctx_pick" value="{html.escape(s.id)}"'
        f' data-name="{html.escape(s.name)}" data-text="{html.escape(s.text)}"{" checked" if s.id in picked else ""}>{html.escape(s.name)}</label>'
        for s in saved
    )
    rows = "".join(_row(i, c, by_name[c.name].id if c.name in by_name and by_name[c.name].id in picked else "")
                   for i, c in enumerate(attached))
    template = _row(0, Context("", ""), "")
    return (
        '<fieldset class="ctx"><legend>컨텍스트</legend>'
        f'<p class="ctx-pick-title" id="ctx-pick-title">{PICK_TITLE}</p>'
        f'<div class="chips" role="group" aria-labelledby="ctx-pick-title">{chips}{make_box()}{MANAGE}</div>'
        + f'<ol class="ctx-rows">{rows}</ol>'
        f'<template class="ctx-row">{template}</template>'
        f'<details><summary>직접 적기</summary><label class="block">내용 <textarea name="ctx_new" data-count-max="{CONTEXT_MAX}" rows="3">'
        "</textarea></label></details></fieldset>"
    )


def contexts_from_form(form: Any, saved: list[SavedContext]) -> tuple[Context, ...]:
    """폼 → 붙일 컨텍스트(붙인 순서). 줄(ctx_name·ctx_text·ctx_from) 중 떼기를 고른 것과, 단추를 끈 자주 쓰는 컨텍스트의 줄은 뺀다.
    고른 단추 중 아직 줄이 없는 것은 그 사본을 끝에 더한다(스크립트 없이 고른 경우). 직접 적은 글(ctx_new)도 끝에. ValueError 가능."""
    return clean_contexts(contexts_as_typed(form, saved))


def contexts_as_typed(form: Any, saved: list[SavedContext]) -> tuple[Context, ...]:
    """contexts_from_form과 같은 줄을 검사 없이(길이·개수를 넘어도) 적은 그대로. 거절(400) 화면에 다시 채운다(2026-10-09 결정 d)."""
    names, texts, froms = form.getlist("ctx_name"), form.getlist("ctx_text"), form.getlist("ctx_from")
    drops = {str(v) for v in form.getlist("ctx_drop")}
    picks = [str(v) for v in form.getlist("ctx_pick")]
    rows: list[Context] = []
    seen: set[str] = set()
    for i, text in enumerate(texts):
        source = str(froms[i]) if i < len(froms) else ""
        if str(i) in drops or (source and source not in picks) or not str(text).strip():
            continue
        rows.append(Context(" ".join(str(names[i] if i < len(names) else "").split()), str(text).strip()))
        seen.add(source)
    by_id = {s.id: s for s in saved}
    for sid in picks:
        if sid in by_id and sid not in seen and all(r.name != by_id[sid].name for r in rows):
            rows.append(Context(by_id[sid].name, by_id[sid].text))
    if new := str(form.get("ctx_new") or "").strip():
        rows.append(Context("", new))
    if made := str(form.get("ctx_make_text") or "").strip():  # '+ 새로 만들기'(2026-10-11): 이름 붙은 사본으로 붙는다
        name = " ".join(str(form.get("ctx_make_name") or "").split())
        if all(not (r.name == name and r.text == made) for r in rows):
            rows.append(Context(name, made))
    return tuple(rows)


def register_row(store: Store, uid: str, form: Any) -> str:
    """'자주 쓰는 컨텍스트로 등록'(그 줄의 이름·내용) 또는 '+ 새로 만들기'의 [등록하고 붙이기](register=new). 결과 한 줄(HTML, 이스케이프됨)."""
    if str(form.get("register") or "") == "new":
        name, text = " ".join(str(form.get("ctx_make_name") or "").split()), str(form.get("ctx_make_text") or "").strip()
        if not name or not text:
            return '<p class="msg err">새 컨텍스트의 이름과 내용을 적어 주세요.</p>'
        try:
            store.save_saved_context(uid, SavedContext("", name, text))
        except ValueError as e:
            return f'<p class="msg err">{html.escape(str(e))}</p>'
        return f'<p class="msg">「{html.escape(name)}」 등록하고 붙였습니다. 저장을 눌러야 이 책에 남습니다.</p>'
    try:
        index = int(str(form.get("register") or ""))
        texts, names = form.getlist("ctx_text"), form.getlist("ctx_name")
        text, name = str(texts[index]).strip(), " ".join(str(names[index]).split())
    except (ValueError, IndexError):
        return '<p class="msg err">등록하지 못했습니다.</p>'
    if not name:
        return '<p class="msg err">이름을 적어 주세요.</p>'
    try:
        store.save_saved_context(uid, SavedContext("", name, text))
    except ValueError as e:
        return f'<p class="msg err">{html.escape(str(e))}</p>'
    return f'<p class="msg">「{html.escape(name)}」 등록했습니다.</p>'


def _chips(contexts: tuple[Context, ...]) -> str:
    """이름(없으면 내용 앞부분)을 누르면 전문. 이름 없는 짧은 컨텍스트는 칩에 다 보이므로 펼치지 않는다(같은 글이 두 번 보이지 않게, 2026-10-09)."""
    out = []
    for c in contexts:
        first = c.text.splitlines()[0]
        if not c.name and first == c.text and len(first) <= 16:
            out.append(f'<span class="ctx ctx-chip">{html.escape(c.text)}</span>')
        else:
            label = c.name or first[:16] + ("…" if len(c.text) > 16 or first != c.text else "")
            out.append(f'<details class="ctx"><summary>{html.escape(label)}</summary><p>{html.escape(c.text)}</p></details>')
    return "".join(out)


def contexts_view_html(view: View, edit_href: str | None = None) -> str:
    """노드 패널 머리·책 게시판 머리: 붙은 컨텍스트 이름(누르면 전문). 책은 노드의 것 → 책의 것 순서(#96-d).
    없으면 아무것도 보이지 않는다(#97: 읽는 순서·없을 때의 뜻은 도움말)."""
    edit = f' <a href="{html.escape(edit_href)}">바꾸기</a>' if edit_href else ""
    if not view.book:  # 노드만
        if not view.contexts:
            return ""
        return f'<div class="ctxs" aria-label="컨텍스트"><span class="ctx-label">컨텍스트</span>{_chips(view.contexts)}{edit}</div>'
    if not view.all:
        return ""
    parts = []
    if view.node_contexts:
        parts.append(f'<span class="ctx-label">노드 「{html.escape(view.node)}」</span>{_chips(view.node_contexts)}')
    if view.contexts:
        parts.append(f'<span class="ctx-label">이 책</span>{_chips(view.contexts)}')
    elif view.node_contexts:
        parts.append('<span class="ctx-label nowrap">이 책 <span class="none">없음</span></span>')  # 줄바꿈으로 갈리지 않게
    order = '<span class="ctx-sep" aria-hidden="true">→</span>'.join(parts)
    cut = f'<span class="none">앞 {HEADER_MAX:,}자</span>' if view.too_long else ""
    return (f'<div class="ctxs" aria-label="컨텍스트(노드 다음 책 순서로 읽음)"><span class="ctx-label">컨텍스트</span>'
            f"{order}{edit}{cut}</div>")


class ContextPages:
    """내 정보 → 자주 쓰는 컨텍스트(/me/contexts). Web에 섞어 쓴다(_page·user_of·_need_login·_form·_csrf_input·store)."""

    store: Store
    _page: Callable[..., Response]
    user_of: Callable[[Request], tuple[str, str] | None]
    _need_login: Callable[[Request], Response]
    _csrf_input: Callable[[tuple[str, str]], str]
    _form: Callable[[Request, tuple[str, str]], Awaitable[Any]]

    def context_routes(self) -> list[tuple[str, list[str], Callable[..., Any]]]:
        return [("/me/contexts", ["GET", "POST"], self.saved_contexts)]

    async def saved_contexts(self, request: Request) -> Response:
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        message = ""
        if request.method == "POST":
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._page("자주 쓰는 컨텍스트", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            action, ident = str(form.get("action") or ""), str(form.get("id") or "")
            try:
                if action == "delete":  # 붙어 있던 곳(같은 이름의 사본)에서도 뗀다(2026-10-11, 확인 창에 먼저 보인다)
                    target = next((c for c in await run_in_threadpool(self.store.list_saved_contexts, uid) if c.id == ident), None)
                    await run_in_threadpool(self.store.delete_saved_context, uid, ident)
                    dropped = await run_in_threadpool(self.store.detach_context, uid, target.name) if target else 0
                    return RedirectResponse(f"/me/contexts?done=deleted&n={dropped}", status_code=303)
                saved = SavedContext(ident if action == "save" else "", str(form.get("name") or ""), str(form.get("text") or ""))
                await run_in_threadpool(self.store.save_saved_context, uid, saved)
                return RedirectResponse(f"/me/contexts?done={'saved' if action == 'save' else 'added'}", status_code=303)
            except ValueError as e:
                message = f'<p class="msg err">{html.escape(str(e))}</p>'
        dropped = request.query_params.get("n") or "0"
        done = {"saved": "저장했습니다.", "added": "더했습니다.",
                "deleted": f"지웠습니다. 붙어 있던 {dropped}곳에서도 뗐습니다." if dropped.isdigit() and int(dropped) else "지웠습니다."
                }.get(request.query_params.get("done") or "")
        message = message or (f'<p class="msg">{done}</p>' if done else "")
        items = await run_in_threadpool(self.store.list_saved_contexts, uid)
        csrf = self._csrf_input(session)
        places = await run_in_threadpool(self.store.context_places, uid)
        cards = "".join(
            f'<section class="saved-ctx" aria-label="{html.escape(c.name)}"><form method="post" action="/me/contexts" data-guard>{csrf}'
            f'<input type="hidden" name="id" value="{html.escape(c.id)}">'
            f'<label class="block">이름 <input name="name" value="{html.escape(c.name)}" data-count-max="{CONTEXT_NAME_MAX}" required></label>'
            f'<label class="block">내용 <textarea name="text" data-count-max="{CONTEXT_MAX}" rows="3" required>{html.escape(c.text)}</textarea></label>'
            '<p><button name="action" value="save">저장</button></p></form>'
            + _delete_box(c, places.get(name_key(c.name), []), csrf) + "</section>"
            for c in items
        ) or '<p class="empty">없습니다.</p>'
        room = len(items) < MAX_SAVED
        add = (
            f'<h2>새로 더하기</h2><form method="post" action="/me/contexts" class="card" data-guard>{csrf}'
            f'<label class="block">이름 <input name="name" data-count-max="{CONTEXT_NAME_MAX}" required></label>'
            f'<label class="block">내용 <textarea name="text" data-count-max="{CONTEXT_MAX}" rows="3" required></textarea></label>'
            '<p><button name="action" value="add" class="primary">더하기</button></p></form>'
            if room else f'<p class="muted">{MAX_SAVED}개 가득</p>'
        )
        body = (
            f'<p class="crumb"><a href="/me">← 내 정보</a></p>{message}'
            f"{cards}{add}"
        )
        from magus.webshelf import SHELF_STYLE  # noqa: PLC0415  # 입력칸·글 상자 모양(책장 화면과 같다)

        from magus.webmap_assets import MAP_STYLE  # noqa: PLC0415  # 같은 자리 확인 창(.node-del·.del-box)
        from magus.webtrash import TRASH_SCRIPT  # noqa: PLC0415  # Esc로 닫기·초점

        return self._page("자주 쓰는 컨텍스트", body + TRASH_SCRIPT, session, 400 if message.startswith('<p class="msg err">') else 200,
                          current="", css=SHELF_STYLE + MAP_STYLE + CONTEXT_STYLE)


def _delete_box(c: SavedContext, places: list[str], csrf: str) -> str:
    """지우기: 같은 자리 확인 창(2026-10-11). 붙어 있는 곳이 있으면 어디서 떨어지는지 먼저 보인다."""
    close = '<button type="button" class="del-cancel" onclick="this.closest(\'details\').open=false">취소</button>'
    said = (f"<p>지우면 이 {len(places)}곳에서도 떨어집니다.</p><ul>" + "".join(f"<li>{html.escape(p)}</li>" for p in places) + "</ul>"
            if places else f"<p>{html.escape(josa(f'「{c.name}」', '을/를'))} 지울까요?</p>")
    return (f'<details class="node-del ctx-del"><summary class="btn quiet">지우기</summary>'
            f'<div class="del-box" role="dialog" aria-label="「{html.escape(c.name)}」 지우기">{said}'
            f'<form method="post" action="/me/contexts">{csrf}<input type="hidden" name="id" value="{html.escape(c.id)}">'
            f'<p><button name="action" value="delete" class="primary">지우기</button> {close}</p></form></div></details>')
