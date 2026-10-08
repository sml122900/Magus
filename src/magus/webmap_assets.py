"""프로젝트·지도 화면(#95)의 스타일과 스크립트. 값은 여기 한 곳(web-style.md "지도").

- 노드: 둥근 알약 모양, 이름 18px·600, 둘째 줄 14px. 가운데 노드는 크고(21px) 짙은 보라 바탕(#2e2b8c, 흰 글자 11.9:1).
  연결 노드는 점선 테두리와 둘째 줄 '연결 · 원본 프로젝트'. 저자가 고른 노드 색은 책 색과 같은 규칙으로 글자색을 정한다.
- 선: #7b8597(지도 바탕 위 3.6:1), 굵기 2.5px. 누르는 자리는 18px(보이지 않음). 고른 선은 보라 4px.
  선은 노드 아래에 그려 노드를 가리지 않는다.
- 확대는 0.35~2배. 처음에는 노드가 모두 들어오게 맞추되 0.6배(휴대폰 폭은 0.45배) 아래로는 줄이지 않는다(글자가 읽히게).
- 스크립트가 꺼지면: 지도는 가운데 노드를 화면 가운데에 두고 그대로 보이며(끌기·확대 없음), 목록 보기·노드 설정·'+ 노드' 폼으로 모든 일을 한다.
"""

MAP_STYLE = """
main{max-width:1560px}
main>h1{display:none}
.pm-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;margin:0 0 8px}
.pm-title{margin:0;font-size:26px}
.pm-head .pm-meta{margin:0}
.pm-bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:4px 0 12px}
.pm-bar .search{margin:0;flex:1 1 320px}
.pm-tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
a.btn,summary.btn{display:inline-flex;align-items:center;min-height:40px;padding:8px 16px;border-radius:9999px;border:1px solid var(--primary);
background:var(--canvas);color:var(--primary);text-decoration:none;font-size:16px;line-height:1.2;cursor:pointer}
a.btn:hover,summary.btn:hover{background:var(--soft)}
button[aria-pressed=true]{background:var(--primary);color:#ffffff}
.pm-meta{color:var(--ink2);margin:0 0 8px}
.pm-head{position:relative}
.pm-new{margin:0}.pm-new>summary{list-style:none}.pm-new>summary::-webkit-details-marker{display:none}
.pm-new>summary.primary-ish{background:var(--primary);color:#ffffff;font-weight:600;border-color:var(--primary)}
.pm-new>summary.primary-ish:hover{background:var(--deep)}
.pm-new-in{position:absolute;left:0;top:100%;z-index:30;width:min(820px,calc(100vw - 32px));display:grid;
grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:8px 24px;background:var(--canvas);border:1px solid var(--line);
border-radius:12px;padding:8px 20px;margin-top:8px;box-shadow:0 12px 32px rgb(13 37 61/.22)}
.pm-form{margin:8px 0}.pm-form label{margin:4px 8px 4px 0}
.pm-results{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:8px 16px;margin:0 0 12px}
.pm-body{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}
@media (min-width:1200px){.pm-body{grid-template-columns:minmax(0,1fr) 520px;align-items:start}}
.pm-main{min-width:0}
.map-view{position:relative;overflow:hidden;height:clamp(440px,calc(100vh - 250px),860px);background:#f9fafc;border:1px solid var(--line);
border-radius:12px;touch-action:none;cursor:grab;user-select:none;-webkit-user-select:none}
.map-view.panning{cursor:grabbing}
.world{position:absolute;left:50%;top:50%;width:0;height:0;transform-origin:0 0}
.js .world{left:0;top:0}
svg.edges{position:absolute;overflow:visible;z-index:1}
.edge .ln{stroke:#7b8597;stroke-width:2.5;stroke-linecap:round;pointer-events:none}
.edge .hit{stroke:transparent;stroke-width:18;pointer-events:stroke;cursor:pointer}
.edge:hover .ln{stroke:#4d5668}
.edge.sel .ln{stroke:var(--primary);stroke-width:4}
line.band{stroke:var(--primary);stroke-width:3;stroke-dasharray:8 6;stroke-linecap:round;visibility:hidden;pointer-events:none}
line.band.on{visibility:visible}
.node{position:absolute;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:2px;width:max-content;min-width:150px;max-width:280px;
padding:12px 26px;border-radius:9999px;background:var(--canvas);border:2px solid var(--ink2);color:var(--ink);text-decoration:none;text-align:center;
box-shadow:0 2px 6px rgb(13 37 61/.14);cursor:pointer;touch-action:none;z-index:2;white-space:nowrap}
.node .nname{font-size:22px;font-weight:600;line-height:1.25;max-width:100%;overflow:hidden;text-overflow:ellipsis}
.node .nsub{font-size:16px;color:var(--ink2);line-height:1.3}
.node.center{min-width:220px;max-width:340px;padding:18px 34px;background:#2e2b8c;border:3px solid #2e2b8c;color:#ffffff;z-index:3}
.node.center .nname{font-size:25px;white-space:normal;line-height:1.3}
.node.center .nsub{color:#e6e4ff}
.node.link{border-style:dashed;background:#fbfbfe}
.node.missing{border-color:var(--mute);color:var(--ink2)}
.node.colored{background:var(--nc);color:var(--nfg);border-color:rgb(0 0 0/.35)}
.node.colored .nsub{color:var(--nfg)}
.node:hover{border-color:var(--primary);color:inherit}
.node.center:hover{border-color:#ffffff}
.node.on{outline:3px solid var(--primary);outline-offset:3px}
.node.center.on{outline-color:#b8923a}
.node:focus-visible{outline:3px solid var(--primary);outline-offset:3px}
.node.drop{outline:3px dashed var(--primary);outline-offset:4px;background:#ecebff;color:var(--ink)}
.node.dragging{box-shadow:0 12px 26px rgb(13 37 61/.30);z-index:6;cursor:grabbing}
.node.pick{outline:3px solid #b8923a;outline-offset:3px}
.knob{position:absolute;right:-17px;top:50%;transform:translateY(-50%);width:32px;height:32px;border-radius:50%;background:var(--primary);
color:#ffffff;font-size:20px;line-height:32px;text-align:center;display:none;cursor:crosshair;box-shadow:0 1px 3px rgb(0 0 0/.3)}
.js .node:hover .knob,.js .node:focus-visible .knob,.js .node.on .knob,.js .node.pick .knob{display:block}
.edge-cut{position:absolute;transform:translate(-50%,-50%);z-index:7;background:var(--canvas);box-shadow:var(--shadow)}
.zoom{position:absolute;right:12px;bottom:12px;flex-direction:column;gap:6px;z-index:8}
.zoom button{width:44px;height:44px;padding:0;font-size:22px;background:var(--canvas)}
.map-say{position:absolute;left:12px;bottom:8px;margin:0;padding:6px 12px;background:var(--canvas);border:1px solid var(--line);border-radius:8px;
color:var(--ink);max-width:70%;z-index:8}
.map-say:empty{display:none}
.map-hint{color:var(--ink2);font-size:15px;margin:8px 0}
.js-only{display:none!important}.js .js-only{display:inline-flex!important}
.map-list{display:none}
.nlist{list-style:none;padding:0;margin:0;background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.nlist>li{border-bottom:1px solid var(--line)}.nlist>li:last-child{border-bottom:0}
.nlist summary{padding:12px 16px 12px 44px;min-height:48px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;cursor:pointer;
list-style:none;position:relative}
.nlist summary::-webkit-details-marker{display:none}
.nlist summary::before{content:"▸";position:absolute;left:16px;top:10px;color:var(--ink2);font-size:20px;line-height:1.4}
.nlist details[open]>summary::before{content:"▾"}
.nlist summary b{font-size:18px}
.nlist details>p,.nlist details>.muted{margin:4px 16px 12px 40px}
.nl-books{margin:0 16px 8px 40px;padding-left:16px}.nl-books li{margin:8px 0}.nl-books a{font-weight:600;font-size:17px}
.sr-title{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;margin:0}
.pm[data-view=list] .map-view,.pm[data-view=list] .map-hint,.pm[data-view=list] [data-act=link],.pm[data-view=list] [data-act=fit]{display:none!important}
.pm[data-view=list] .map-list{display:block}
.pm[data-view=list] .view-list,.pm[data-view=map] .view-map{display:none}
@media (min-width:768px){.pm[data-view=auto] .view-map{display:none}}
@media (max-width:767px){
.pm[data-view=auto] .map-view,.pm[data-view=auto] .map-hint,.pm[data-view=auto] [data-act=link],.pm[data-view=auto] [data-act=fit]{display:none!important}
.pm[data-view=auto] .map-list{display:block}.pm[data-view=auto] .view-list{display:none}
.map-view{height:68vh}.pm-bar .search{flex-basis:100%}.pm-title{font-size:22px}}
.pm-panel{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:12px 16px 12px;box-shadow:var(--shadow);min-width:0}
.pp-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}
.pp-title{margin:4px 0;font-size:22px}.pp-title:focus{outline:none}.pp-title:focus-visible{outline:3px solid var(--primary)}
.pp-kind{color:var(--ink2)}
.pp-link{background:var(--soft);border-radius:8px;padding:8px 12px}
.pm-panel .case{margin:12px 0}.pm-panel .books{padding:26px 10px 0}
.pp-hint{color:var(--ink2);font-size:15px;margin:4px 0 8px}
.pp-set{border-top:1px solid var(--line);padding-top:4px}.pp-set>summary{font-weight:600;color:var(--ink2);min-height:44px;display:flex;align-items:center}
.pp-set h3{font-size:16px;margin:12px 0 4px}.pp-lines{margin:4px 0;padding-left:20px}.pp-lines li{margin:4px 0}
.pp-book{border-top:2px solid var(--line);margin-top:12px;padding-top:4px}
.bp-head{display:flex;justify-content:space-between;align-items:center;gap:12px}
.bp-title{margin:8px 0;font-size:20px}.bp-title:focus{outline:none}
.bp-close{display:inline-flex;align-items:center;min-height:40px;padding:8px 16px;border-radius:9999px;border:1px solid var(--primary);text-decoration:none}
.bp-frame{display:block;width:100%;height:max(560px,75vh);border:1px solid var(--line);border-radius:8px;background:var(--canvas)}
a.book.lifting{opacity:.4}
.ghost{position:fixed!important;left:0;top:0;pointer-events:none;z-index:50;transform:translate(-50%,-60%) rotate(-4deg);opacity:.92;list-style:none}
"""

PROJECTS_STYLE = """
.projects{list-style:none;padding:0;margin:16px 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}
.pcard{background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.pcard>a{display:flex;flex-direction:column;gap:6px;padding:20px 24px;min-height:150px;text-decoration:none;color:var(--ink);border-radius:12px}
.pcard>a:hover .pname,.pcard>a:focus-visible .pname{text-decoration:underline;color:var(--primary)}
.pname{font-size:22px;font-weight:600;line-height:1.3}
.pmeta{color:var(--ink2)}
.pcard.library{border-left:6px solid #2e2b8c}
.pcard.new{border:2px dashed var(--ink2);box-shadow:none;padding:16px 20px}
.pcard.new h2{margin:4px 0 8px}.pcard.new form{margin:8px 0}
.fgroup{background:var(--canvas);border:1px solid var(--line);border-radius:12px;padding:8px 16px;margin:12px 0}
.fgroup h2{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}.fgroup h2 small{font-weight:400;font-size:16px}
"""

# 지도 조작. JSON(#map-data): {project, csrf, post, panel, page, nodes:[{id,x,y}], edges:[[a,b]]}
MAP_SCRIPT = r"""<script>
(function () {
  var dataEl = document.getElementById("map-data");
  if (!dataEl) return;
  var D = JSON.parse(dataEl.textContent);
  document.documentElement.classList.add("js");
  var pm = document.querySelector(".pm"), body = document.querySelector(".pm-body");
  var viewEl = document.querySelector(".map-view"), world = viewEl.querySelector(".world");
  var svg = world.querySelector("svg.edges"), band = svg.querySelector("line.band"), cut = world.querySelector(".edge-cut");
  var say = viewEl.querySelector(".map-say"), panel = document.getElementById("panel");
  var bookBox = document.getElementById("book-panel"), frame = bookBox.querySelector("iframe");
  var bookTitle = document.getElementById("bp-title"), closeLink = bookBox.querySelector(".bp-close");
  var moveForm = document.getElementById("move-form");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var pos = {};
  D.nodes.forEach(function (n) { pos[n.id] = {x: n.x, y: n.y}; });
  var V = {x: 0, y: 0, k: 1}, KEY = "magus-map-" + D.project;
  var MIN = 0.35, MAX = 2;

  function nodeEl(id) { return world.querySelector('.node[data-node="' + CSS.escape(id) + '"]'); }
  function apply() { world.style.transform = "translate(" + V.x + "px," + V.y + "px) scale(" + V.k + ")"; }
  function save() {  // 화면 폭과 함께 적어 두고, 폭이 비슷할 때만 다시 쓴다(새로 고침·되돌아오기)
    try { sessionStorage.setItem(KEY, JSON.stringify({x: V.x, y: V.y, k: V.k, w: viewEl.clientWidth})); } catch (e) { /* 저장 못 해도 된다 */ }
  }
  function tell(text) { say.textContent = text || ""; }
  function bounds() {
    var b = {x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity};
    Object.keys(pos).forEach(function (id) { var p = pos[id];
      b.x0 = Math.min(b.x0, p.x); b.x1 = Math.max(b.x1, p.x); b.y0 = Math.min(b.y0, p.y); b.y1 = Math.max(b.y1, p.y); });
    return b;
  }
  function fit() {  // 노드 상자(지도 좌표)가 모두 들어오게. 글자가 읽히게 0.6배 아래로는 줄이지 않는다
    var w = viewEl.clientWidth, h = viewEl.clientHeight, b = {x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity};
    if (!w) return;
    world.querySelectorAll(".node").forEach(function (el) {
      var p = pos[el.getAttribute("data-node")], hw = el.offsetWidth / 2 + 20, hh = el.offsetHeight / 2 + 12;
      if (!p) return;
      b.x0 = Math.min(b.x0, p.x - hw); b.x1 = Math.max(b.x1, p.x + hw); b.y0 = Math.min(b.y0, p.y - hh); b.y1 = Math.max(b.y1, p.y + hh);
    });
    if (!isFinite(b.x0)) return;
    V.k = Math.max(w < 600 ? 0.45 : 0.6, Math.min(1, (w - 24) / (b.x1 - b.x0), (h - 24) / (b.y1 - b.y0)));
    V.x = w / 2 - (b.x0 + b.x1) / 2 * V.k; V.y = h / 2 - (b.y0 + b.y1) / 2 * V.k;
    apply(); save();
  }
  var saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (e) { saved = null; }
  if (saved && isFinite(saved.k) && isFinite(saved.x) && isFinite(saved.y) && Math.abs((saved.w || 0) - viewEl.clientWidth) < 40) {
    V = {x: saved.x, y: saved.y, k: saved.k}; apply();
  } else { saved = null; fit(); }
  function toWorld(cx, cy) { var r = viewEl.getBoundingClientRect(); return {x: (cx - r.left - V.x) / V.k, y: (cy - r.top - V.y) / V.k}; }
  function zoomAt(cx, cy, k) {
    k = Math.max(MIN, Math.min(MAX, k));
    var r = viewEl.getBoundingClientRect(), p = toWorld(cx, cy);
    V.k = k; V.x = cx - r.left - p.x * k; V.y = cy - r.top - p.y * k; apply(); save();
  }
  function post(fields) {
    var fd = new FormData();
    fd.append("csrf", D.csrf);
    Object.keys(fields).forEach(function (k) { fd.append(k, fields[k]); });
    return fetch(D.post, {method: "POST", body: fd, headers: {"Accept": "application/json"}, credentials: "same-origin", keepalive: true})
      .then(function (r) { return r.json().catch(function () { return {ok: false, error: "저장하지 못했습니다."}; }); })
      .then(function (res) { if (!res.ok) tell(res.error || "저장하지 못했습니다."); return res; })
      .catch(function () { tell("저장하지 못했습니다."); return {ok: false}; });
  }
  function reload() { save(); location.reload(); }

  // ---- 선 ----
  function grow() {
    var b = bounds(), pad = 260, x0 = b.x0 - pad, y0 = b.y0 - pad, w = b.x1 - b.x0 + 2 * pad, h = b.y1 - b.y0 + 2 * pad;
    svg.style.left = x0 + "px"; svg.style.top = y0 + "px"; svg.style.width = w + "px"; svg.style.height = h + "px";
    svg.setAttribute("viewBox", x0 + " " + y0 + " " + w + " " + h);
  }
  function redraw(id) {
    svg.querySelectorAll(".edge").forEach(function (g) {
      var a = g.getAttribute("data-a"), b = g.getAttribute("data-b");
      if (id && a !== id && b !== id) return;
      g.querySelectorAll("line").forEach(function (l) {
        l.setAttribute("x1", pos[a].x); l.setAttribute("y1", pos[a].y); l.setAttribute("x2", pos[b].x); l.setAttribute("y2", pos[b].y);
      });
    });
    grow();
  }
  var selected = null;
  function unselect() { if (selected) selected.classList.remove("sel"); selected = null; cut.hidden = true; }
  function selectEdge(g) {
    unselect(); selected = g; g.classList.add("sel");
    var a = pos[g.getAttribute("data-a")], b = pos[g.getAttribute("data-b")];
    cut.style.left = (a.x + b.x) / 2 + "px"; cut.style.top = (a.y + b.y) / 2 + "px"; cut.hidden = false;
    tell("선을 골랐습니다.");
  }
  cut.addEventListener("click", function (e) {
    e.stopPropagation();
    if (!selected) return;
    post({action: "disconnect", node: selected.getAttribute("data-a"), other: selected.getAttribute("data-b")})
      .then(function (res) { if (res.ok) reload(); });
  });
  cut.addEventListener("pointerdown", function (e) { e.stopPropagation(); });

  // ---- 주소와 패널 ----
  var state = {node: body.getAttribute("data-node") || "", book: body.getAttribute("data-book") || "", at: body.getAttribute("data-at") || ""};
  function url(s) {
    var q = [];
    if (s.node) q.push("node=" + encodeURIComponent(s.node));
    if (s.book) q.push("book=" + encodeURIComponent(s.book));
    if (s.at) q.push("at=" + encodeURIComponent(s.at));
    if (pm.getAttribute("data-view") !== "auto") q.push("view=" + pm.getAttribute("data-view"));
    return D.page + (q.length ? "?" + q.join("&") : "");
  }
  function push(s, replace) { state = s; history[replace ? "replaceState" : "pushState"](s, "", url(s)); }
  window.addEventListener("popstate", function () { save(); location.reload(); });
  function markNode(id) {
    world.querySelectorAll(".node.on").forEach(function (el) { el.classList.remove("on"); el.removeAttribute("aria-current"); });
    var el = id && nodeEl(id);
    if (el) { el.classList.add("on"); el.setAttribute("aria-current", "true"); }
  }
  function closeBook(silent) {
    bookBox.hidden = true; frame.src = "about:blank";
    if (!silent) push({node: state.node, book: "", at: ""});
  }
  function openNode(id, opts) {
    opts = opts || {};
    markNode(id);
    return fetch(D.panel + "?node=" + encodeURIComponent(id), {credentials: "same-origin"})
      .then(function (r) { return r.text(); })
      .then(function (h) {
        var box = document.getElementById("pp-node");
        box.insertAdjacentHTML("beforebegin", h); box.remove(); wirePanel();
        if (opts.refresh) return;
        closeBook(true);
        push({node: id, book: "", at: ""});
        var t = document.getElementById("pp-title");
        if (t) t.focus({preventScroll: true});
        if (window.matchMedia("(max-width:1199px)").matches) panel.scrollIntoView({block: "start", behavior: reduce ? "auto" : "smooth"});
      });
  }
  var first = "", loads = 0;
  function openBook(a, title) {
    var key = a.getAttribute("data-key") || "", href = a.getAttribute("href");
    title = title || a.getAttribute("data-name") || a.textContent.trim();
    bookBox.hidden = false; bookTitle.textContent = title; frame.title = title; first = href; loads = 0; frame.src = href;
    closeLink.setAttribute("href", url({node: state.node}));
    push({node: state.node, book: key, at: key ? "" : href});
    bookTitle.focus({preventScroll: true});
    bookBox.scrollIntoView({block: "start", behavior: reduce ? "auto" : "smooth"});
  }
  if (!bookBox.hidden) first = state.at ? "" : frame.getAttribute("src");
  frame.addEventListener("load", function () {
    loads += 1;
    var loc;
    try { loc = frame.contentWindow.location; } catch (e) { return; }
    if (!loc || loc.href === "about:blank") return;
    var here = loc.pathname + loc.search;
    if (state.book && first && here !== first && here.indexOf("/shelf/") === 0) push({node: state.node, book: state.book, at: here}, true);
    else if (state.book && here === first && state.at) push({node: state.node, book: state.book, at: ""}, true);
    if (loads > 1 && state.node) openNode(state.node, {refresh: true});  // 게시판에서 적거나 고친 뒤 책장의 수를 맞춘다
  });
  closeLink.addEventListener("click", function (e) { e.preventDefault(); closeBook(false); });

  // ---- 패널의 책: 누르면 열고, 끌어 지도의 노드에 놓으면 옮긴다 ----
  function wirePanel() {
    var box = document.getElementById("pp-node");
    if (!box) return;
    box.querySelectorAll("a.book").forEach(function (a) {
      a.addEventListener("click", function (e) {
        if (a.getAttribute("data-dragged")) { e.preventDefault(); a.removeAttribute("data-dragged"); return; }
        e.preventDefault();
        openBook(a, a.classList.contains("add") ? "책 추가" : "");
      });
      if (a.getAttribute("data-book")) wireBookDrag(a);
    });
  }
  function wireBookDrag(a) {
    a.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      var start = {x: e.clientX, y: e.clientY}, ghost = null, lifted = false, touch = e.pointerType === "touch", timer = null;
      function lift(ev) {
        lifted = true; ghost = document.createElement("div"); ghost.className = "ghost"; ghost.appendChild(a.cloneNode(true));
        document.body.appendChild(ghost); a.classList.add("lifting"); place(ev);
        tell("노드 위에 놓으세요.");
      }
      function place(ev) { ghost.style.left = ev.clientX + "px"; ghost.style.top = ev.clientY + "px"; }
      if (touch) timer = setTimeout(function () { lift(e); }, 350);
      function target(ev) {
        var over = document.elementFromPoint(ev.clientX, ev.clientY);
        return over && over.closest ? over.closest(".node") : null;
      }
      function move(ev) {
        if (!lifted) {
          if (touch || Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 6) { if (touch && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) > 8) cancel(); return; }
          lift(ev);
        }
        ev.preventDefault(); place(ev);
        var node = target(ev);
        world.querySelectorAll(".node.drop").forEach(function (n) { if (n !== node) n.classList.remove("drop"); });
        if (node) node.classList.add("drop");
      }
      function cancel() { clearTimeout(timer); document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up); }
      function up(ev) {
        cancel();
        if (!lifted) return;
        a.setAttribute("data-dragged", "1"); ghost.remove(); a.classList.remove("lifting");
        var node = target(ev);
        world.querySelectorAll(".node.drop").forEach(function (n) { n.classList.remove("drop"); });
        if (!node) { tell(""); return; }
        moveForm.elements.book.value = a.getAttribute("data-book");
        moveForm.elements.to.value = D.project + ":" + node.getAttribute("data-node");
        save(); moveForm.submit();
      }
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    });
  }
  wirePanel();
  // 링크(노드·책)를 끌면 브라우저가 링크 끌기(drag and drop)를 시작해 포인터 이벤트를 끊는다. 지도 화면에서는 막는다
  document.addEventListener("dragstart", function (e) { if (e.target.closest && e.target.closest(".pm")) e.preventDefault(); });

  // ---- 노드: 누르기·끌어 옮기기·＋를 끌어 선 잇기 ----
  var drag = null, bandFrom = null, linkMode = false, linkFirst = null, suppress = false;
  var linkButton = document.querySelector("[data-act=link]");
  function startBand(id) {
    bandFrom = id; var p = pos[id];
    band.setAttribute("x1", p.x); band.setAttribute("y1", p.y); band.setAttribute("x2", p.x); band.setAttribute("y2", p.y);
    band.classList.add("on");
  }
  function stopBand() { bandFrom = null; band.classList.remove("on"); world.querySelectorAll(".node.drop").forEach(function (n) { n.classList.remove("drop"); }); }
  function connect(a, b) {
    if (!a || !b || a === b) return;
    tell("선을 잇는 중…");
    post({action: "connect", node: a, other: b}).then(function (res) { if (res.ok) reload(); });
  }
  function setLinkMode(on) {
    linkMode = on; linkButton.setAttribute("aria-pressed", on ? "true" : "false");
    if (linkFirst) { var el = nodeEl(linkFirst); if (el) el.classList.remove("pick"); }
    linkFirst = null; stopBand();
    tell(on ? "첫 노드를 누르세요." : "");
  }
  linkButton.addEventListener("click", function () { setLinkMode(!linkMode); });
  world.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    var el = e.target.closest(".node");
    if (e.target.closest(".knob") && el) {
      e.preventDefault(); e.stopPropagation(); unselect();
      startBand(el.getAttribute("data-node")); viewEl.setPointerCapture(e.pointerId);
      tell("노드 위에 놓으세요.");
      return;
    }
    if (el) {
      e.stopPropagation(); unselect();
      var id = el.getAttribute("data-node");
      drag = {id: id, el: el, sx: e.clientX, sy: e.clientY, ox: pos[id].x, oy: pos[id].y, moved: false};
      el.setPointerCapture(e.pointerId);
      return;
    }
    var g = e.target.closest(".edge");
    if (g) { e.stopPropagation(); selectEdge(g); }
  });
  document.addEventListener("pointermove", function (e) {
    if (drag) {
      var dx = (e.clientX - drag.sx) / V.k, dy = (e.clientY - drag.sy) / V.k;
      if (!drag.moved && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 5) return;
      drag.moved = true; drag.el.classList.add("dragging");
      pos[drag.id] = {x: Math.round(drag.ox + dx), y: Math.round(drag.oy + dy)};
      drag.el.style.left = pos[drag.id].x + "px"; drag.el.style.top = pos[drag.id].y + "px";
      redraw(drag.id);
      return;
    }
    if (bandFrom || (linkMode && linkFirst)) {
      var p = toWorld(e.clientX, e.clientY);
      band.setAttribute("x2", p.x); band.setAttribute("y2", p.y);
      var over = document.elementFromPoint(e.clientX, e.clientY), node = over && over.closest ? over.closest(".node") : null;
      world.querySelectorAll(".node.drop").forEach(function (n) { if (n !== node) n.classList.remove("drop"); });
      if (node && node.getAttribute("data-node") !== (bandFrom || linkFirst)) node.classList.add("drop");
    }
  });
  document.addEventListener("pointerup", function (e) {
    if (drag) {
      var d = drag; drag = null; d.el.classList.remove("dragging");
      if (d.moved) {
        suppress = true; setTimeout(function () { suppress = false; }, 0);
        post({action: "move_node", node: d.id, x: pos[d.id].x, y: pos[d.id].y}).then(function (res) { if (res.ok) tell(""); });
      }
      return;
    }
    if (bandFrom) {
      var from = bandFrom, over = document.elementFromPoint(e.clientX, e.clientY);
      var node = over && over.closest ? over.closest(".node") : null;
      stopBand();
      suppress = true; setTimeout(function () { suppress = false; }, 0);
      if (node) connect(from, node.getAttribute("data-node")); else tell("");
    }
  });
  world.addEventListener("click", function (e) {
    var el = e.target.closest(".node");
    if (!el) return;
    e.preventDefault();
    if (suppress) return;
    var id = el.getAttribute("data-node");
    if (linkMode) {
      if (!linkFirst) { linkFirst = id; el.classList.add("pick"); startBand(id); tell("둘째 노드를 누르세요."); return; }
      var a = linkFirst; setLinkMode(false); connect(a, id);
      return;
    }
    openNode(id);
  });

  // ---- 지도 움직이기: 끌기·휠·두 손가락·두 번 누르기 ----
  var pointers = {}, pan = null, pinch = null;
  viewEl.addEventListener("pointerdown", function (e) {
    if (e.target.closest(".node, .edge, .edge-cut, .zoom, button")) return;
    unselect();
    pointers[e.pointerId] = {x: e.clientX, y: e.clientY};
    var ids = Object.keys(pointers);
    if (ids.length === 2) {
      var a = pointers[ids[0]], b = pointers[ids[1]];
      pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), k: V.k}; pan = null;
    } else {
      pan = {x: e.clientX, y: e.clientY, vx: V.x, vy: V.y}; viewEl.classList.add("panning");
    }
    viewEl.setPointerCapture(e.pointerId);
  });
  viewEl.addEventListener("pointermove", function (e) {
    if (!(e.pointerId in pointers)) return;
    pointers[e.pointerId] = {x: e.clientX, y: e.clientY};
    var ids = Object.keys(pointers);
    if (pinch && ids.length === 2) {
      var a = pointers[ids[0]], b = pointers[ids[1]];
      zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, pinch.k * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d);
    } else if (pan) {
      V.x = pan.vx + e.clientX - pan.x; V.y = pan.vy + e.clientY - pan.y; apply();
    }
  });
  function release(e) {
    delete pointers[e.pointerId];
    if (Object.keys(pointers).length < 2) pinch = null;
    if (!Object.keys(pointers).length) { pan = null; viewEl.classList.remove("panning"); save(); }
  }
  viewEl.addEventListener("pointerup", release);
  viewEl.addEventListener("pointercancel", release);
  viewEl.addEventListener("wheel", function (e) {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, V.k * Math.exp(-e.deltaY * 0.0015));
  }, {passive: false});
  viewEl.addEventListener("dblclick", function (e) {
    if (e.target.closest(".node, .edge, .edge-cut, .zoom, button")) return;
    var p = toWorld(e.clientX, e.clientY), box = document.getElementById("new-node");
    if (!box) return;
    box.querySelectorAll("input[name=x]").forEach(function (i) { i.value = Math.round(p.x); });
    box.querySelectorAll("input[name=y]").forEach(function (i) { i.value = Math.round(p.y); });
    box.open = true;
    var name = box.querySelector("input[name=name]");
    box.scrollIntoView({block: "nearest", behavior: reduce ? "auto" : "smooth"});
    if (name) name.focus();
    tell("새 노드 이름을 적으세요.");
  });
  document.querySelectorAll(".zoom [data-act]").forEach(function (b) {
    b.addEventListener("click", function () {
      var r = viewEl.getBoundingClientRect();
      zoomAt(r.left + r.width / 2, r.top + r.height / 2, V.k * (b.getAttribute("data-act") === "in" ? 1.25 : 0.8));
    });
  });
  document.querySelector("[data-act=fit]").addEventListener("click", fit);
  document.querySelectorAll("[data-view-to]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      pm.setAttribute("data-view", a.getAttribute("data-view-to"));
      push(state, true);
      if (a.getAttribute("data-view-to") === "map" && !saved) fit();
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (linkMode) setLinkMode(false);
    stopBand(); unselect();
    var box = document.getElementById("new-node");
    if (box && box.open) { box.open = false; box.querySelector("summary").focus(); }
  });
})();
</script>"""
