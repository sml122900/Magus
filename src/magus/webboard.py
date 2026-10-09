"""책 = 게시판 페이지(2026-10-09 사용자 요청). Web에 섞어 쓰는 BoardPages.

흐름: 지도 → 노드 → 책장(책 목록) → 책을 누르면 **별도 페이지**의 게시판(지도 옆 패널에 열리던 방식은 없앴다).
- 위치 표시(제목 위): 프로젝트 › 「프로젝트」 › 노드 › 책. 누르면 그 단계로 돌아간다.
- 게시판(/shelf/<책>): 한 줄 = 제목 · 첨부 표시(📎, 그림이면 작은 미리보기) · 날짜. 최신 글이 위, 20개씩, 오른쪽 위 '글쓰기' 하나.
  문헌 글(서지가 있는 글)도 같은 목록에 섞인다(제목은 서지). 거르기(전체·나·AI)·찾기·책 설정(⚙)은 그대로.
- 글쓰기(/shelf/write/<책>): 제목·본문·첨부. 파일을 끌어다 놓거나 '파일 고르기', 휴대폰은 '사진 찍기'(capture). 누가 = 저자.
- 글 보기(/shelf/<책>/<글>): 제목·본문·그림(글 안에 바로)·파일 목록(이름을 누르면 내려받기)·고치기·🗑(화면 안 확인 창 → 휴지통.
  응답한 글·첨부도 함께, 되살리기는 프로젝트의 휴지통 화면). 웹에서 원문 확인 체크는 없다(MCP 도구는 그대로).
- 글 고치기(/shelf/<책>/<글>/edit, 2026-10-09 되돌림: 고칠 길이 없으면 불편): 글쓰기와 같은 화면에 제목·본문·첨부가 채워져 열린다.
  기존 첨부마다 ✕(빼기 → 지우지 않고 휴지통, 프로젝트 휴지통에서 그 글로 되살린다), 새 첨부 더하기. 바꾼 칸(제목·본문·고친 시각)만
  파일에서 고치고 나머지 칸(누가·이유·위치·쓸 부분·태그·칸 등)은 바이트까지 그대로 둔다. 문헌 글은 본문(메모)·첨부만.
  칸(인물·사례 등)은 본문 아래 "칸: 값" 줄. 이유·위치·쓸 부분(일반 글)·태그·원문 확인 표시는 파일에 그대로 있고 보이지 않는다.
- 스크랩(별표, 2026-10-09): 게시판 줄 오른쪽과 글 보기 머리의 ☆를 누르면 ★(다시 누르면 해제). 스크립트가 있으면 새로고침 없이
  (POST …/scrap, JSON), 없으면 폼으로 돌아온다. 게시판 '★ 스크랩만'(?scrap=1)은 찾기와 함께 쓰고 개수를 보인다. 파일에는 표시 하나.
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
from starlette.responses import JSONResponse, RedirectResponse, Response

from magus.attachments import ACCEPT, MAX_FILES, kind_of, mb, media_type, shown_title, size_text, title_from_files
from magus.book_migrate import legacy_book_id
from magus.category.rules import BUILTINS, CONTENT_MAX, TITLE_MAX
from magus.ids import local_time, new_id, utcnow
from magus.melchior.author_report import cite_label
from magus.store import Attachment, CategoryItem, Store
from magus.store.formats import one_line
from magus.webshelf import (
    AI_MARK, AI_TITLE, Book, Kind, clean_query, find, mark, paragraphs, snippet, state_url,
)

BOARD_SIZE = 20  # 게시판 한 쪽
SEP = ' <span aria-hidden="true">›</span> '
WHEN = "%Y-%m-%d %H:%M"
DONE = {"made": "만들었습니다.", "edit": "저장했습니다.", "trashed": "휴지통으로 옮겼습니다.", "restored": "되살렸습니다.",
        "edited": "고쳤습니다."}

BOARD_STYLE = """
.trail{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;margin:0 0 4px;color:var(--ink2);font-size:15px}
.trail a{text-decoration:none}.trail a:hover{text-decoration:underline}.trail [aria-current]{color:var(--ink);font-weight:600}
.board-bar{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:8px 0}
.board-bar .sum{margin:0;color:var(--ink2);display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center}
.board-bar .write-btn{margin-left:auto}.board-bar a.gear{margin-left:0}
a.button{display:inline-flex;align-items:center;min-height:44px;padding:8px 18px;border-radius:9999px;background:var(--primary);color:#fff;
text-decoration:none;font-weight:600}a.button:hover{background:var(--press);color:#fff}
ol.posts{list-style:none;margin:8px 0;padding:0;background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
ol.posts>li{border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center}
ol.posts>li:last-child{border-bottom:0}ol.posts>li>small.hit{grid-column:1/-1}
form.star{margin:0 8px 0 0}form.star.head{margin:0}
form.star button{min-width:44px;min-height:44px;border:0;border-radius:9999px;background:transparent;color:var(--ink2);font-size:24px;line-height:1;
cursor:pointer;padding:0}form.star button:hover{background:var(--soft)}
form.star button[aria-pressed=true]{color:#b8860b}form.star button:focus-visible{outline:3px solid var(--primary);outline-offset:1px}
.post-head{display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center}.post-head .post-meta{margin:0}
a.scrap-only{display:inline-flex;align-items:center;gap:4px;min-height:44px;padding:0 14px;border-radius:9999px;border:1px solid var(--mute);
text-decoration:none;color:var(--ink);background:var(--canvas);font-weight:600}a.scrap-only:hover{background:var(--soft)}
a.scrap-only[aria-current=true]{background:#fff3c4;border-color:#b8860b}a.scrap-only .n{font-weight:400;color:var(--ink2)}
.search-row{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center}.search-row form.search{margin:0}
a.post{display:grid;grid-template-columns:minmax(0,1fr) auto 10.5em;gap:4px 16px;align-items:center;padding:10px 16px;min-height:52px;
text-decoration:none;color:var(--ink)}
a.post:hover .pt,a.post:focus-visible .pt{text-decoration:underline}
.pt{font-weight:600;font-size:17px;overflow:hidden;text-overflow:ellipsis}.pt.none{font-weight:400;color:var(--ink)}
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
.pics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:12px 0}
.pics a{display:block;border-radius:8px;overflow:hidden;border:1px solid var(--line);background:var(--soft)}
.pics img{display:block;width:100%;aspect-ratio:1;object-fit:cover}
.pics.one{grid-template-columns:minmax(0,400px)}.pics.one img{aspect-ratio:auto;height:auto;object-fit:contain}
@media (min-width:768px){.pics{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (min-width:1100px){.pics{grid-template-columns:repeat(4,minmax(0,1fr))}}
.lightbox{position:fixed;inset:0;z-index:80;background:rgb(0 0 0/.88);display:flex;align-items:center;justify-content:center;padding:56px 8px 64px}
.lightbox[hidden]{display:none}.lightbox img{max-width:100%;max-height:100%;object-fit:contain;border-radius:4px;background:#222}
.lightbox button{position:absolute;min-width:48px;min-height:48px;border:0;border-radius:9999px;background:rgb(255 255 255/.92);color:#111;font-size:18px;
font-weight:600;padding:0 16px;cursor:pointer}.lightbox button:focus-visible{outline:3px solid #ffd34d}
.lightbox .lb-close{top:8px;right:8px}.lightbox .lb-prev{left:8px;top:50%;transform:translateY(-50%)}
.lightbox .lb-next{right:8px;top:50%;transform:translateY(-50%)}
.lightbox .lb-count{position:absolute;bottom:16px;left:0;right:0;text-align:center;color:#fff;font-variant-numeric:tabular-nums}
.board-bar a.gear.labeled{font-size:16px;padding:0 12px;min-height:44px;gap:4px;color:var(--ink)}
.post-acts{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:flex-start;margin:12px 0}
.post-acts a.act{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-width:44px;min-height:44px;padding:0 18px;
border-radius:9999px;font-size:16px;font-weight:600;color:var(--ink);border:1px solid var(--mute);background:var(--canvas);text-decoration:none}
.post-acts a.act:hover{background:var(--soft)}
.post-acts details.del{position:relative}
.post-acts details.del>summary{list-style:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;min-width:44px;min-height:44px;
padding:0 18px;border-radius:9999px;cursor:pointer;font-size:16px;font-weight:600;color:var(--ink);border:1px solid var(--mute);background:var(--canvas)}
.post-acts details.del>summary::-webkit-details-marker{display:none}.post-acts details.del>summary:hover{background:var(--soft)}
.post-acts .del-box{margin-top:8px;width:min(380px,100%);background:var(--canvas);border:1px solid var(--line);border-left:4px solid var(--ruby);
border-radius:10px;padding:4px 16px;box-shadow:0 8px 24px rgb(0 0 0/.18)}.post-acts .del-box p{margin:10px 0}
.write-form textarea{min-height:220px}
ul.current{list-style:none;padding:0;margin:4px 0 12px;display:flex;flex-direction:column;gap:6px}
ul.current li{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;background:var(--canvas);border:1px solid var(--line);border-radius:8px;
padding:4px 6px 4px 12px}ul.current small{color:var(--ink2)}
ul.current label.drop{position:relative;margin:0 0 0 auto;display:inline-flex;align-items:center;justify-content:center;min-width:44px;
min-height:44px;padding:0 12px;border-radius:9999px;cursor:pointer;border:1px solid var(--mute);background:var(--canvas);font-weight:600}
ul.current label.drop:focus-within{outline:3px solid var(--primary);outline-offset:2px}
ul.current label.drop input{position:absolute;opacity:0;width:1px;height:1px}
ul.current li:has(input:checked) .fname{text-decoration:line-through;color:var(--ink2)}
ul.current li:has(input:checked) label.drop{background:var(--soft)}
ul.current .undo{display:none}ul.current li:has(input:checked) .undo{display:inline}ul.current li:has(input:checked) .x{display:none}
.dropzone{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;padding:16px;border:2px dashed var(--mute);border-radius:12px;background:var(--soft)}
.dropzone.over{border-color:var(--primary);background:#ecebff}
.dropzone label.pick{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;border-radius:9999px;border:1px solid var(--primary);
color:var(--primary);background:var(--canvas);cursor:pointer;margin:0;position:relative}
.dropzone label.pick:focus-within{outline:3px solid var(--primary);outline-offset:2px}
.dropzone input[type=file]{position:absolute;inset:0;opacity:0;width:1px;height:1px}
.dropzone .drop-word{color:var(--ink2)}
@media (pointer:fine){.dropzone label.camera{display:none}}
ul.chosen{list-style:none;padding:0;margin:8px 0;display:flex;flex-direction:column;gap:6px}
ul.chosen li{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;background:var(--canvas);border:1px solid var(--line);border-radius:8px;
padding:4px 6px 4px 8px}
ul.chosen img{width:40px;height:40px;object-fit:cover;border-radius:4px}ul.chosen small{color:var(--ink2)}
ul.chosen button.unpick{margin-left:auto;min-width:44px;min-height:44px;border-radius:9999px;border:1px solid var(--mute);background:var(--canvas);
font-size:16px;font-weight:600;cursor:pointer;padding:0 12px}ul.chosen button.unpick:hover{background:var(--soft)}
.pick-note{margin:4px 0;color:var(--ink)}.pick-note:empty{display:none}
@media (max-width:767px){a.post{grid-template-columns:minmax(0,1fr) auto;padding:10px 12px}.pd{grid-column:1/-1;text-align:left;font-size:14px}
.trail>a,.trail>span[aria-current]{max-width:11em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
}
"""

# 글 보기의 사진: 누르면 화면 안에서 크게(원본). 닫기·이전·다음, Esc·←·→, 밀어 넘기기. 스크립트가 없으면 링크로 원본이 새 창에 열린다
LIGHTBOX = """<div class="lightbox" role="dialog" aria-modal="true" aria-label="사진 크게 보기" hidden>
<img alt=""><button type="button" class="lb-close">닫기 ✕</button><button type="button" class="lb-prev" aria-label="이전 사진">‹</button>
<button type="button" class="lb-next" aria-label="다음 사진">›</button><p class="lb-count" aria-live="polite"></p></div>
<script>
(function () {
  var box = document.querySelector(".lightbox"), links = Array.prototype.slice.call(document.querySelectorAll(".pics a[data-full]"));
  if (!box || !links.length) return;
  var img = box.querySelector("img"), count = box.querySelector(".lb-count"), at = 0, back = null, startX = null;
  var prev = box.querySelector(".lb-prev"), next = box.querySelector(".lb-next");
  function show(i) {
    at = (i + links.length) % links.length;
    img.src = links[at].href; img.alt = links[at].querySelector("img").alt;
    count.textContent = links.length > 1 ? (at + 1) + " / " + links.length : "";
    prev.hidden = next.hidden = links.length < 2;
  }
  function open(i) { back = document.activeElement; show(i); box.hidden = false; document.body.style.overflow = "hidden"; box.querySelector(".lb-close").focus(); }
  function close() { box.hidden = true; img.removeAttribute("src"); document.body.style.overflow = ""; if (back) back.focus(); }
  links.forEach(function (a, i) {
    a.addEventListener("click", function (e) {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault(); open(i);
    });
  });
  box.querySelector(".lb-close").addEventListener("click", close);
  prev.addEventListener("click", function () { show(at - 1); });
  next.addEventListener("click", function () { show(at + 1); });
  box.addEventListener("click", function (e) { if (e.target === box) close(); });
  document.addEventListener("keydown", function (e) {
    if (box.hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") show(at - 1);
    else if (e.key === "ArrowRight") show(at + 1);
    else if (e.key === "Tab") {  // 창 안에서만 돈다
      var f = Array.prototype.filter.call(box.querySelectorAll("button"), function (b) { return !b.hidden; });
      var i = f.indexOf(document.activeElement);
      e.preventDefault(); f[(i + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus();
    }
  });
  box.addEventListener("pointerdown", function (e) { startX = e.clientX; });
  box.addEventListener("pointerup", function (e) {
    if (startX === null || links.length < 2) return;
    var dx = e.clientX - startX; startX = null;
    if (Math.abs(dx) > 50) show(at + (dx < 0 ? 1 : -1));
  });
})();
</script>"""

# 스크랩(별표): 새로고침 없이 켜고 끈다(fetch, JSON). 실패하면 폼을 그대로 보낸다(새로고침). 게시판 '스크랩만' 개수도 바꾼다
STAR_SCRIPT = """<script>
(function () {
  if (window.magusStar) return; window.magusStar = true;
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("form.star") || !window.fetch) return;
    e.preventDefault();
    var button = form.querySelector("button"), on = form.querySelector("input[name=on]");
    button.disabled = true;
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (d) {
        button.setAttribute("aria-pressed", d.scrap ? "true" : "false"); button.textContent = d.scrap ? "★" : "☆";
        on.value = d.scrap ? "0" : "1"; button.disabled = false;
        var n = document.querySelector("[data-scrap-count]"); if (n) n.textContent = String(d.count);
      })
      .catch(function () { button.disabled = false; form.submit(); });
  });
})();
</script>"""

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

# 글쓰기·고치기의 첨부: 담은 파일 목록을 스크립트가 들고 있다(2026-10-09). 고르기·끌어다 놓기는 목록에 더하고, 파일마다 ✕로 빼고,
# 10개 초과·한 개 한도 초과·받지 않는 형식은 담는 순간 그 파일만 빼고 알린다. 보낼 때 목록으로 FormData를 만든다.
# 스크립트가 꺼져 있으면 고르기·사진 찍기는 브라우저 기본대로 된다(다시 고르면 앞의 것이 바뀐다)
WRITE_SCRIPT = """<script>
(function () {
  var zone = document.querySelector("[data-dropzone]"), form = zone && zone.closest("form");
  if (!form || !window.FormData || !window.fetch) return;  // 스크립트가 없으면 고르기·사진 찍기는 브라우저 기본대로 된다
  var inputs = zone.querySelectorAll("input[type=file]"), list = form.querySelector("ul.chosen"), note = form.querySelector(".pick-note");
  var MAX = +zone.getAttribute("data-max"), LIMIT = +zone.getAttribute("data-limit");
  var LIMIT_TEXT = zone.getAttribute("data-limit-text"), TYPES = zone.getAttribute("data-types").split(",");
  var chosen = [];  // 담은 파일(고를 때마다 더한다. input.files에 두지 않으므로 다시 골라도 앞의 것이 남는다)
  function ext(name) { var i = name.lastIndexOf("."); return i < 0 ? "" : name.slice(i).toLowerCase(); }
  function size(n) { return n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1000)) + " KB"; }  // size_text와 같다
  function attached(f) {  // 고치기: 이미 붙어 있고 빼지 않은 첨부와 같은 파일
    return Array.prototype.some.call(form.querySelectorAll("ul.current li"), function (li) {
      var box = li.querySelector("input[name=drop]");
      return li.getAttribute("data-name") === f.name && +li.getAttribute("data-size") === f.size && !(box && box.checked);
    });
  }
  function add(files) {
    var said = [];
    Array.prototype.forEach.call(files || [], function (f) {
      var same = chosen.some(function (c) { return c.name === f.name && c.size === f.size; });
      if (same || attached(f)) return;  // 같은 파일(이름·크기)은 한 번만
      if (TYPES.indexOf(ext(f.name)) < 0) said.push("「" + f.name + "」은 받지 않는 형식이라 뺐어요.");
      else if (f.size > LIMIT) said.push("「" + f.name + "」은 " + LIMIT_TEXT + "를 넘어 뺐어요.");
      else if (chosen.length >= MAX) said.push("첨부는 한 번에 " + MAX + "개까지라 「" + f.name + "」은 뺐어요.");
      else chosen.push(f);
    });
    note.textContent = said.join(" ");
    show();
  }
  function show() {
    list.textContent = "";
    chosen.forEach(function (f, i) {
      var li = document.createElement("li");
      if (/^image\\//.test(f.type) && window.URL) { var img = document.createElement("img"); img.alt = ""; img.src = URL.createObjectURL(f); li.appendChild(img); }
      var name = document.createElement("span"); name.className = "fname"; name.textContent = f.name; li.appendChild(name);
      var small = document.createElement("small"); small.textContent = size(f.size); li.appendChild(small);
      var x = document.createElement("button"); x.type = "button"; x.className = "unpick"; x.textContent = "✕";
      x.setAttribute("aria-label", f.name + " 빼기"); x.title = "빼기";
      x.addEventListener("click", function () {
        chosen.splice(i, 1); note.textContent = "「" + f.name + "」을 뺐어요."; show();
        var next = list.querySelectorAll("button.unpick")[Math.min(i, chosen.length - 1)];
        (next || zone.querySelector("input[type=file]")).focus();
      });
      li.appendChild(x);
      list.appendChild(li);
    });
  }
  inputs.forEach(function (input) { input.addEventListener("change", function () { add(input.files); input.value = ""; }); });
  ["dragenter", "dragover"].forEach(function (t) { zone.addEventListener(t, function (e) { e.preventDefault(); zone.classList.add("over"); }); });
  ["dragleave", "drop"].forEach(function (t) { zone.addEventListener(t, function () { zone.classList.remove("over"); }); });
  zone.addEventListener("drop", function (e) { e.preventDefault(); if (e.dataTransfer) add(e.dataTransfer.files); });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var data = new FormData(form), button = form.querySelector("button.primary");
    data.delete("files");
    chosen.forEach(function (f) { data.append("files", f, f.name); });
    button.disabled = true; note.textContent = "저장하는 중…";
    fetch(form.action, { method: "POST", body: data, credentials: "same-origin" }).then(function (r) {
      if (r.redirected) { location.href = r.url; return; }
      return r.text().then(function (page) { document.open(); document.write(page); document.close(); });
    }).catch(function () { button.disabled = false; note.textContent = "저장하지 못했어요. 다시 눌러 주세요."; });
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
    scrap: bool = False  # 스크랩(별표, 2026-10-09)


def item_preview(item: CategoryItem, files: list[Attachment] | tuple[Attachment, ...]) -> str:
    """제목이 없을 때 보일 본문 앞부분(게시판 줄·글 보기·휴지통이 같은 규칙): 본문, 없으면 칸 값, 없으면 첨부 이름."""
    return one_line(item.content or " · ".join(f"{k}: {v}" for k, v in item.fields.items() if v) or " · ".join(a.name for a in files))


def _inline_image(name: str) -> bool:
    media, inline = media_type(name)
    return inline and media.startswith("image/")


def star_html(link: str, on: bool, csrf: str, back: str, head: bool = False) -> str:
    """스크랩(별표) 단추: 누르면 켜고 다시 누르면 끈다. 스크립트가 있으면 새로고침 없이(STAR_SCRIPT), 없으면 폼으로 back에 돌아온다.
    csrf는 이미 만든 숨은 칸 HTML."""
    return (f'<form class="star{" head" if head else ""}" method="post" action="{html.escape(link)}/scrap">{csrf}'
            f'<input type="hidden" name="on" value="{"0" if on else "1"}"><input type="hidden" name="next" value="{html.escape(back)}">'
            f'<button aria-pressed="{"true" if on else "false"}" aria-label="스크랩" title="스크랩">{"★" if on else "☆"}</button></form>')


def post_row_html(post: Post, q: str = "", star: str = "") -> str:
    """게시판 한 줄: 제목 · 첨부 표시(📎, 그림이면 작은 미리보기) · 날짜 · 스크랩(☆). 누르면 글 보기 페이지.
    star: 별표 단추 HTML(게시판). 없으면(찾기 결과 등) 스크랩한 글에 ★ 표시만."""
    if post.title:
        shown = mark(post.title, q)
        head = f'<span class="pt">{shown}{post.badge}</span>'
    else:
        preview = one_line(post.preview)
        shown = mark(preview[:80] + ("…" if len(preview) > 80 else "") or "(제목 없음)", q)
        head = f'<span class="pt none">{shown}{post.badge}</span>'
    hit = snippet(post.text, q) if q and "<mark>" not in shown else ""  # 제목 밖에서 맞았으면 맞은 곳 한 줄
    pic = next((a for a in post.files if _inline_image(a.name)), None)
    thumb = (f'<img class="thumb" src="{html.escape(post.link)}/thumbs/{html.escape(pic.id)}" alt="" loading="lazy">' if pic else "")
    count = len(post.files)
    clip = f'<span class="clip" aria-label="첨부 {count}개" title="첨부 {count}개">📎 {count}</span>' if count else ""
    mark_only = '<span class="scrapped" title="스크랩" aria-label="스크랩">★</span>' if post.scrap and not star else ""
    return (f'<li><a class="post" href="{html.escape(post.link)}">{head}<span class="pa">{mark_only}{thumb}{clip}</span>'
            f'<time class="pd" datetime="{html.escape(post.at)}">{local_time(post.at, WHEN)}</time></a>{star}'
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
    _post_actions: Callable[..., str]  # 글 고치기·지우기(🗑, webshelf)
    _editable: Callable[[str, str, str], tuple[Kind, Any] | None]
    _owner: Callable[[Kind, Any], str]

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
        scrap = filters.get("scrap") == "1"
        pairs: list[tuple[str, Post]] = []
        for i in self.store.list_category_items(uid, c.id):
            if (author and i.author != author) or (tag and tag not in i.tags) or (scrap and not i.scrap):
                continue
            link = f"/shelf/{c.id}/{i.id}"
            files = tuple(self.store.list_attachments(uid, f"{c.id}/{i.id}"))
            preview = item_preview(i, files)
            badge = (AI_MARK if i.author == "ai" else "") + (AI_TITLE if i.title and i.title_by == "ai" else "")
            text = "\n".join([i.content, i.reason or "", i.where or "", *(p.text for p in i.passages),
                              *(f"{k} {v}" for k, v in i.fields.items()), " ".join(i.tags)]) if q else ""
            title = shown_title(i.title, (a.name for a in files))
            pairs.append((i.id, Post(i.id, link, i.created_at, title, preview, badge, files, text, i.scrap)))
        if not author and not tag:
            for r in self.store.list_refs(uid, book=c.id):
                if scrap and not r.scrap:
                    continue
                link = f"/shelf/{c.id}/{urllib.parse.quote(r.key)}"
                files = tuple(self.store.list_attachments(uid, f"ref:{r.key}"))
                text = ("\n".join([str(r.bib.get("authors") or r.bib.get("raw") or ""), str(r.bib.get("container") or ""),
                                   str(r.bib.get("memo") or ""), *(p.text for p in self.store.get_passages(uid, r.key))]) if q else "")
                pairs.append((r.key, Post(r.key, link, r.created_at, cite_label(r, r.key), "", "", files, text, r.scrap)))
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
        filters = {k: params.get(k, "") for k in ("author", "tag", "scrap")}
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
        bar = (f'<div class="board-bar"><p class="sum">글 {len(items) + c.sources}' + (f' · {" · ".join(links)}' if links else "") + "</p>"
               f'<a class="gear labeled" href="/shelf/edit/{c.id}"><span aria-hidden="true">⚙</span> 책 설정</a>'
               f'<a class="button write-btn" href="/shelf/write/{c.id}">글쓰기</a></div>')
        search = (f'<form method="get" action="{base}" class="search" role="search">'
                  f'<input type="search" name="q" value="{html.escape(q)}" aria-label="{html.escape(c.name)}에서 찾기">'
                  + "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in filters.items() if v)
                  + "<button>찾기</button></form>")
        scrap_on = filters.get("scrap") == "1"
        starred = sum(1 for i in items if i.scrap) + sum(1 for r in self.store.list_refs(uid, book=c.id) if r.scrap)
        toggle = [(k, v) for k, v in [("q", q), *((k, v) for k, v in filters.items() if k != "scrap")] if v]
        toggle += [] if scrap_on else [("scrap", "1")]
        scrap_link = (f'<a class="scrap-only" href="{base}{"?" + html.escape(urllib.parse.urlencode(toggle)) if toggle else ""}" '
                      f'aria-current="{"true" if scrap_on else "false"}"><span aria-hidden="true">★</span> 스크랩만 '
                      f'<span class="n" data-scrap-count>{starred}</span></a>')
        search = f'<div class="search-row">{search}{scrap_link}</div>'
        found = f'<p>「{html.escape(q)}」 {len(posts)} · <a href="{base}">지우기</a></p>' if q else ""
        back = base + ("?" + urllib.parse.urlencode([(k, v) for k, v in params.multi_items() if k != "done"])
                       if any(k != "done" for k in params.keys()) else "")
        csrf = self._csrf_input(session)
        if shown:
            board = (f'<ol class="posts">{"".join(post_row_html(p, q, star_html(p.link, p.scrap, csrf, back)) for p in shown)}</ol>'
                     + STAR_SCRIPT)
        elif q:
            board = '<p class="msg">없음</p>'
        else:
            board = '<p class="empty">스크랩한 글이 없습니다.</p>' if scrap_on else '<p class="empty">글이 없습니다.</p>'
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
        return f"{message}{bar}{search}{found}{board}{pager}"

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
            preview = item_preview(obj, files)  # 게시판 줄과 같은 규칙
            title = shown_title(obj.title, (a.name for a in files)) or (preview[:40] + ("…" if len(preview) > 40 else "")) or "제목 없음"
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
            f'<a href="{html.escape(link)}/files/{html.escape(a.id)}" target="_blank" rel="noopener" data-full>'
            f'<img src="{html.escape(link)}/thumbs/{html.escape(a.id)}" alt="{html.escape(a.name)}" loading="lazy"></a>' for a in pics)
        others = "".join(
            f'<li><a href="{html.escape(link)}/files/{html.escape(a.id)}" download>{html.escape(a.name)}</a> '
            f'<small>{html.escape(kind_of(a.name))} · {size_text(a.size)}</small></li>' for a in rest)
        done = DONE.get(params.get("done") or "")
        star = star_html(link, obj.scrap, self._csrf_input(session), link, head=True) + STAR_SCRIPT
        body = ((f'<p class="msg">{done}</p>' if done else "")
                + f'<div class="post-head">{star}<p class="post-meta">{html.escape(" · ".join(meta))}</p></div>'
                + (f'<div class="post-body">{text}</div>' if text.strip() else "")
                + (f'<div class="pics{" one" if len(pics) == 1 else ""}">{pictures}</div>{LIGHTBOX}' if pictures else "")
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
            title = title or title_from_files(name for name, _ in files)  # 제목이 비고 첨부가 있으면 첫 첨부의 파일 이름(2026-10-09)

            def save() -> CategoryItem:
                item = self.store.put_category_item(uid, CategoryItem(new_id(), book, content, "me", title, "author" if title else None))
                for name, data in files:
                    att = self.store.put_attachment(uid, f"{book}/{item.id}", name, data)
                    self.store.attachment_thumb(uid, f"{book}/{item.id}", att.id)  # 사진이면 썸네일(못 만들면 화면이 원본을 쓴다)
                return item

            item = await run_in_threadpool(save)
            return RedirectResponse(f"/shelf/{book}/{item.id}", status_code=303)
        error = self._write_error(request.query_params.get("error") or "")
        body = (f'<p class="msg err">{error}</p>' if error else "") + self._write_form(session, here, f"/shelf/{book}")
        lead = await run_in_threadpool(self.trail, uid, kind.key, "글쓰기")
        return self._shelf_page("글쓰기", body, session, 400 if error else 200, lead=lead)

    def _write_form(self, session: tuple[str, str], action: str, cancel: str, *, title: str = "", content: str = "",
                    heading: str = "", current: list[Attachment] | tuple[Attachment, ...] = ()) -> str:
        """글쓰기·고치기가 함께 쓰는 폼: 제목(문헌 글이면 서지 제목을 머리로)·본문·첨부(고치기면 기존 첨부마다 ✕ 빼기)."""
        limit = int(self.settings.max_attach_bytes)
        rows = "".join(
            f'<li data-name="{html.escape(a.name)}" data-size="{a.size}"><span class="fname">{html.escape(a.name)}</span> <small>{html.escape(kind_of(a.name))} · {size_text(a.size)}</small>'
            f'<label class="drop" title="첨부 빼기"><input type="checkbox" name="drop" value="{html.escape(a.id)}" '
            f'aria-label="{html.escape(a.name)} 빼기"><span class="x" aria-hidden="true">✕ 빼기</span>'
            '<span class="undo" aria-hidden="true">빼지 않기</span></label></li>' for a in current)
        head = (f'<h2 class="ref-title">{html.escape(heading)}</h2>' if heading else
                f'<label class="block">제목 <input name="title" value="{html.escape(title)}" maxlength="{TITLE_MAX}"></label>')
        return (
            f'<form method="post" action="{html.escape(action)}" enctype="multipart/form-data" class="card write-form">'
            f'{self._csrf_input(session)}{head}'
            f'<label class="block">본문 <textarea name="content" rows="10" maxlength="{CONTENT_MAX}">{html.escape(content)}</textarea></label>'
            '<fieldset><legend>첨부</legend>'
            + (f'<ul class="current" aria-label="지금 첨부">{rows}</ul>' if rows else "")
            + f'<div class="dropzone" data-dropzone data-max="{MAX_FILES}" data-limit="{limit}" data-limit-text="{mb(limit)}" '
            f'data-types="{ACCEPT}">'
            f'<label class="pick">파일 고르기<input type="file" name="files" multiple accept="{ACCEPT}"></label>'
            '<label class="pick camera">사진 찍기<input type="file" name="files" accept="image/*" capture="environment"></label>'
            f'<span class="drop-word">끌어다 놓기 · {MAX_FILES}개까지</span></div>'
            '<ul class="chosen" aria-label="담은 파일"></ul><p class="pick-note" role="status" aria-live="polite"></p></fieldset>'
            f'<p><button class="primary">저장</button> <a href="{html.escape(cancel)}">취소</a></p></form>{WRITE_SCRIPT}'
        )

    # ---- 스크랩(별표, 2026-10-09) ------------------------------------------------------------------
    async def board_scrap(self, request: Request) -> Response:
        """☆ → ★(on=1), ★ → ☆(on=0). 자기 글만(다른 사용자의 글은 404). 스크립트가 부르면 JSON {scrap, count}, 폼이면 next로."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        try:
            form = await self._form(request, session)
        except PermissionError:
            return self._shelf_page("스크랩", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
        found = await run_in_threadpool(self._editable, uid, request.path_params["kind"], request.path_params["item"])
        if found is None:
            return self._shelf_page("스크랩", '<p class="msg err">없는 글입니다. <a href="/shelf">프로젝트</a></p>', session, 404)
        kind, obj = found
        assert kind.category is not None
        on = form.get("on") == "1"
        now = await run_in_threadpool(self.store.set_scrap, uid, self._owner(kind, obj), on)

        def count() -> int:
            assert kind.category is not None
            return (sum(1 for i in self.store.list_category_items(uid, kind.category.id) if i.scrap)
                    + sum(1 for r in self.store.list_refs(uid, book=kind.category.id) if r.scrap))

        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"scrap": now, "count": await run_in_threadpool(count)})
        back = str(form.get("next") or "")
        ok = back.startswith(f"/shelf/{kind.category.id}") and "//" not in back and ".." not in back
        return RedirectResponse(back if ok else f"/shelf/{kind.category.id}", status_code=303)

    # ---- 글 고치기(2026-10-09 되돌림) -------------------------------------------------------------
    async def board_edit(self, request: Request) -> Response:
        """글쓰기와 같은 화면(채워진 채). 저장하면 글 보기로 돌아가 '고쳤습니다.' 뺀 첨부는 휴지통으로(지우지 않는다).
        글: 제목·본문만 파일에서 고치고(고친 시각·고친 사람=저자), 누가(author)·이유·위치·쓸 부분·태그·칸 등은 그대로.
        문헌 글: 본문(메모)만. 서지·쓸 부분·원문 확인 표시는 그대로(인용 점검 수가 바뀌지 않는다)."""
        session = self.user_of(request)
        if not session:
            return self._need_login(request)
        uid = session[0]
        found = await run_in_threadpool(self._editable, uid, request.path_params["kind"], request.path_params["item"])
        if found is None:
            return self._shelf_page("고치기", '<p class="msg err">고칠 수 있는 글이 아닙니다. <a href="/shelf">프로젝트</a></p>',
                                    session, 404)
        kind, obj = found
        assert kind.category is not None
        is_item = isinstance(obj, CategoryItem)
        owner = self._owner(kind, obj)
        link = f"/shelf/{kind.category.id}/{urllib.parse.quote(obj.id if is_item else obj.key)}"
        here = f"{link}/edit"
        title_text = (obj.title or "") if is_item else ""
        text = obj.content if is_item else str(obj.bib.get("memo") or "")
        error = ""
        if request.method == "POST":
            if self._too_big(request):
                return RedirectResponse(f"{here}?error=big", status_code=303)
            try:
                form = await self._form(request, session)
            except PermissionError:
                return self._shelf_page("고치기", '<p class="msg err">잘못된 요청입니다.</p>', session, 403)
            content = str(form.get("content") or "").strip()[:CONTENT_MAX]
            title = one_line(str(form.get("title") or ""))[:TITLE_MAX] or None
            files, code = await self._read_files(uid, form)
            current = await run_in_threadpool(self.store.list_attachments, uid, owner)
            asked = {str(v) for v in form.getlist("drop")}
            drops = [a.id for a in current if a.id in asked]
            left = len(current) - len(drops) + len(files)
            if code:
                return RedirectResponse(f"{here}?error={code}", status_code=303)
            if is_item and not (content or title or any(obj.fields.values()) or obj.passages or left > 0):
                error, title_text, text = self._write_error("empty"), title or "", content
            else:
                if is_item and not title:  # 제목이 비고 첨부가 남으면 첫 첨부의 파일 이름(2026-10-09)
                    title = title_from_files([*(a.name for a in current if a.id not in drops), *(name for name, _ in files)])
                await run_in_threadpool(self._save_edit, uid, kind, obj, owner, title, content, files, drops)
                return RedirectResponse(f"{link}?done=edited", status_code=303)
        else:
            error = self._write_error(request.query_params.get("error") or "")
        current = await run_in_threadpool(self.store.list_attachments, uid, owner)
        heading = "" if is_item else cite_label(obj, obj.key)
        body = ((f'<p class="msg err">{error}</p>' if error else "")
                + self._write_form(session, here, link, title=title_text, content=text, heading=heading, current=current))
        lead = await run_in_threadpool(self.trail, uid, kind.key, "고치기")
        return self._shelf_page("고치기", body, session, 400 if error else 200, lead=lead)

    def _save_edit(self, uid: str, kind: Kind, obj: Any, owner: str, title: str | None, content: str,
                   files: list[tuple[str, bytes]], drops: list[str]) -> None:
        assert kind.category is not None
        if isinstance(obj, CategoryItem):
            changes: dict[str, Any] = {}
            if title != obj.title:  # 제목을 그대로 두면 누가 지었는지도 그대로, 새로 적으면 저자가 지은 제목, 지우면 없음
                changes |= {"title": title, "title_by": "author" if title else None}
            if content != obj.content:
                changes["content"] = content
            if changes or files or drops:  # 고친 시각(목록 정렬은 그대로 만든 순서)
                changes |= {"edited_at": utcnow(), "edited_by": "author"}
                self.store.patch_category_item(uid, kind.category.id, obj.id, changes)
        else:
            self.store.set_ref_memo(uid, obj.key, content)
        for att in drops:  # 뺀 첨부는 지우지 않고 휴지통으로(프로젝트 휴지통에서 되살린다)
            self.store.trash_attachment(uid, owner, att, "웹에서 뺌")
        for name, data in files:
            att = self.store.put_attachment(uid, owner, name, data)
            self.store.attachment_thumb(uid, owner, att.id)
