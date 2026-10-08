"""웹 도움말 챗봇(사용자 요청 #97 D, 2026-10-08). 화면의 설명 문장을 걷어 낸 대신, 오른쪽 아래 '?'에서 묻는다.

- API는 서버에서만 부른다(Anthropic 공식 SDK). 키(ANTHROPIC_API_KEY)는 브라우저로 내려가지 않는다.
- 모델은 claude-haiku-4-5-20251001(HELP_MODEL), max_tokens는 작게(HELP_MAX_TOKENS, 기본 600).
- 시스템 프롬프트 = 안내 몇 줄 + docs/help/*.md 전체(검색 없이 통째로). 프롬프트 캐싱(ephemeral)을 건다.
  Haiku 4.5의 캐시 최소 길이는 4,096토큰이라 도움말 문서가 그보다 짧으면 캐시가 걸리지 않는다(오류 없이). 내부 이름·도구 이름은 문서에 없다.
- API로 보내는 것은 질문, 도움말 문서, 지금 화면 이름(정해 둔 목록 SCREENS의 이름만)뿐이다. 글·문서 내용·메일은 보내지 않는다.
  이어지는 질문(2026-10-09): 브라우저가 들고 있던 최근 3번의 질문·답을 함께 보낸다(서버 저장 없음, 3,000자 상한). 문서는 캐시되는 앞부분, 대화는 그 뒤.
- 로그인한 허용 사용자만(웹이 확인한다). 사용자별 하루 질문 수 HELP_DAILY_LIMIT(기본 30, 서버 시간대의 날짜 기준, 프로세스 메모리).
- 키가 없거나 API 오류면 "지금은 도움말을 쓸 수 없어요."만 준다. 다른 기능과는 상관없다.
- 로그에는 질문·답·메일을 남기지 않는다. 호출 수·토큰 수·응답 시간·오류 코드만.
- 대화는 서버에 저장하지 않는다. 브라우저 localStorage(로그인한 사용자별 열쇠)에만 두어 페이지를 옮겨도 남고,
  '새 대화'·20턴 넘음(오래된 것부터)·마지막 질문 뒤 24시간·로그아웃 때 지운다(2026-10-09 사용자 요청).
"""

from __future__ import annotations

import logging
import re
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("magus.help")

UNAVAILABLE = "지금은 도움말을 쓸 수 없어요."
QUOTA = "오늘 도움말 질문을 다 썼어요. 내일 다시 물어 주세요."
EMPTY = "질문을 적어 주세요."
QUESTION_MAX = 300
BAD_REQUEST = "잘못된 요청입니다. 화면을 새로 고쳐 주세요."
# 이어지는 질문(#97 m, 2026-10-09 사용자 답): 브라우저가 들고 있는 최근 주고받기(질문 + 답)를 새 질문과 함께 받는다.
# 서버는 저장하지 않고, 최근 3번·합쳐 3,000자까지만 쓴다(넘으면 오래된 것부터 뺀다).
HISTORY_TURNS = 3
HISTORY_CHARS = 3000
HISTORY_ITEMS_MAX = 20  # 이보다 긴 목록은 형식이 틀린 것으로 본다
ANSWER_MAX = 1500  # 이전 답 하나의 글자 상한
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "docs" / "help"  # 저장소(Docker: /app)의 docs/help

PREAMBLE = """너는 Magus 웹 화면의 도움말이다. Magus는 책을 쓰는 저자가 자기 자료(프로젝트·지도·노드·책·글)와 올린 문서를 관리하고 Claude 대화와 함께 쓰는 서비스다.
아래 '도움말 문서'만 근거로 답한다.
- 문서에 없는 것은 지어내지 않는다. 그때는 "도움말에 없는 내용이에요."라고 말하고, Claude 대화에서 묻거나 운영자에게 알려 달라고 한다.
- 한국어 존댓말로 짧게(보통 2~5문장) 답한다. 마크다운 표·제목·굵은 글씨는 쓰지 않는다. 순서가 있으면 1. 2. 3.으로 줄을 나눈다.
- 화면의 단추·입력칸 이름과 용어 사전의 이름은 문서에 적힌 그대로 쓴다.
- 너는 사용자의 글·문서 내용을 볼 수 없다. 자기 자료의 내용을 물으면 볼 수 없다고 말하고, Claude 대화에서 물어보라고 한다.
- 질문 앞에 '지금 화면' 이름이 온다. 그 화면에 맞춰 답한다."""

# 화면 이름(정해 둔 목록만 API로 보낸다. 주소에 든 프로젝트·책 이름이나 id는 보내지 않는다)
SCREENS = {
    "projects": "프로젝트 목록", "map": "프로젝트 지도", "board": "게시판", "item_edit": "글 고치기", "trash": "휴지통 확인",
    "add": "책 추가", "new_book": "새 책", "book_settings": "책 설정",
    "doc_chapters": "올린 문서 · 장 목록", "doc_issues": "올린 문서 · 확인 요청", "doc_cites": "올린 문서 · 인용 상태",
    "doc_questions": "올린 문서 · 답해 주실 질문", "doc_editions": "올린 문서 · 수정본 이력", "made_doc": "올린 문서에서 만든 문서",
    "me": "내 정보", "files": "올린 파일", "contexts": "자주 쓰는 컨텍스트", "node_trash": "휴지통(지운 노드)", "other": "기타",
}
_TABS = {"issues": "doc_issues", "cites": "doc_cites", "editions": "doc_editions"}


def screen_key(path: str, query: str = "") -> str:
    """요청 주소 → 화면 이름 열쇠(SCREENS). 모르는 주소는 other."""
    parts = [p for p in path.split("/") if p]
    params = dict(urllib.parse.parse_qsl(query))
    if parts[:1] == ["me"]:
        return {(): "me", ("files",): "files", ("contexts",): "contexts"}.get(tuple(parts[1:]), "other")
    if parts[:1] != ["shelf"]:
        return "other"
    rest = parts[1:]
    if not rest:
        return "projects"
    head = rest[0]
    if head == "p":
        return "node_trash" if rest[2:3] == ["trash"] else "map"
    if head in ("add", "new"):
        return {"add": "add", "new": "new_book"}[head]
    if head == "edit":
        return "book_settings"
    if head == "trash":
        return "trash"
    if head == "book":
        if params.get("tab") == "cites" and params.get("view") == "questions":
            return "doc_questions"
        return _TABS.get(params.get("tab") or "", "doc_chapters")
    if head == "doc":
        return "made_doc"
    if len(rest) == 3 and rest[2] in ("edit", "trash"):
        return "item_edit" if rest[2] == "edit" else "trash"
    return "board" if len(rest) <= 2 else "other"


def screen_label(key: str, sub: str = "") -> str:
    """브라우저가 보낸 화면 열쇠(지도 화면이면 패널 안 화면도) → 이름. 목록에 없는 값은 '기타'."""
    main = SCREENS.get(key, SCREENS["other"])
    inner = SCREENS.get(sub)
    return f"{main} · 패널: {inner}" if inner and sub != key else main


def load_docs(folder: Path) -> str:
    """docs/help/*.md를 이름 순서로 이어 붙인다. 폴더가 없으면 빈 문자열(도움말이 꺼진다)."""
    if not folder.is_dir():
        return ""
    return "\n\n".join(p.read_text(encoding="utf-8").strip() for p in sorted(folder.glob("*.md")))


def _local_day() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


@dataclass
class HelpBot:
    api_key: str | None
    docs: str
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 600
    daily_limit: int = 30
    client_factory: Callable[[], Any] | None = None  # 시험에서 가짜 클라이언트를 끼운다
    today: Callable[[], str] = field(default_factory=lambda: _local_day)  # 하루 한도의 날짜(서버 시간대, 컨테이너는 Asia/Seoul)
    _counts: dict[tuple[str, str], int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _client: Any = None

    @classmethod
    def from_settings(cls, settings: Any) -> HelpBot:
        folder = getattr(settings, "help_dir", None) or DEFAULT_DIR
        docs = load_docs(Path(folder))
        if not docs:
            log.warning("help: no help documents (%s)", "folder missing" if not Path(folder).is_dir() else "empty")
        return cls(settings.anthropic_api_key, docs, settings.help_model, settings.help_max_tokens, settings.help_daily_limit)

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.docs)

    def system(self) -> list[dict[str, Any]]:
        """한 덩어리(안내 + 문서)에 캐시 표시. 바뀌지 않는 앞부분이라 요청마다 같은 바이트다(화면·질문은 messages에)."""
        return [{"type": "text", "text": f"{PREAMBLE}\n\n# 도움말 문서\n\n{self.docs}", "cache_control": {"type": "ephemeral"}}]

    def used(self, uid: str) -> int:
        with self._lock:
            return self._counts.get((uid, self.today()), 0)

    def _take(self, uid: str) -> int | None:
        """하루 한도 안이면 하나 쓰고 쓴 수를, 넘으면 None."""
        with self._lock:
            day = self.today()
            for key in [k for k in self._counts if k[1] != day]:  # 지난 날짜는 버린다
                del self._counts[key]
            n = self._counts.get((uid, day), 0)
            if n >= self.daily_limit:
                return None
            self._counts[(uid, day)] = n + 1
            return n + 1

    def _refund(self, uid: str) -> None:
        with self._lock:
            key = (uid, self.today())
            if self._counts.get(key):
                self._counts[key] -= 1

    def _api(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory()
        if self._client is None:
            import anthropic  # noqa: PLC0415  (도움말을 쓸 때만 불러온다)

            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=30.0, max_retries=1)
        return self._client

    def ask(self, uid: str, question: str, screen: str, history: Any = None) -> tuple[int, dict[str, Any]]:
        """(HTTP 상태, JSON). history: 브라우저가 보낸 이전 주고받기 [{"q", "a"}](없으면 None). 질문·답은 로그에 남기지 않는다."""
        text = _one_line(question)[:QUESTION_MAX]
        if not text:
            return 400, {"ok": False, "error": EMPTY}
        try:
            pairs = clean_history(history)
        except ValueError:
            return 400, {"ok": False, "error": BAD_REQUEST}
        if not self.available:
            log.info("help unavailable user=%s code=%s", uid, "no_key" if not self.api_key else "no_docs")
            return 503, {"ok": False, "error": UNAVAILABLE}
        n = self._take(uid)
        if n is None:
            log.info("help quota user=%s n=%d limit=%d", uid, self.daily_limit, self.daily_limit)
            return 429, {"ok": False, "error": QUOTA}
        started = time.monotonic()
        try:
            response = self._api().messages.create(
                model=self.model, max_tokens=self.max_tokens, system=self.system(),
                messages=conversation(pairs, screen, text),
            )
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 도움말만 꺼지고 다른 기능은 그대로
            self._refund(uid)
            code = getattr(e, "status_code", None) or type(e).__name__
            log.warning("help error user=%s code=%s ms=%d", uid, code, (time.monotonic() - started) * 1000)
            return 503, {"ok": False, "error": UNAVAILABLE}
        ms = (time.monotonic() - started) * 1000
        answer = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text").strip()
        usage = response.usage
        if not answer or response.stop_reason == "refusal":
            self._refund(uid)
            log.warning("help error user=%s code=%s ms=%d", uid, response.stop_reason or "empty", ms)
            return 503, {"ok": False, "error": UNAVAILABLE}
        log.info("help ok user=%s n=%d hist=%d in=%d cache_write=%d cache_read=%d out=%d ms=%d stop=%s", uid, n, len(pairs),
                 usage.input_tokens or 0, getattr(usage, "cache_creation_input_tokens", 0) or 0,
                 getattr(usage, "cache_read_input_tokens", 0) or 0, usage.output_tokens or 0, ms, response.stop_reason)
        return 200, {"ok": True, "answer": _plain(answer), "left": max(0, self.daily_limit - n)}


def _one_line(text: Any) -> str:
    return " ".join("".join(ch for ch in str(text) if ch.isprintable() or ch == "\n").split())


def clean_history(raw: Any) -> list[tuple[str, str]]:
    """브라우저가 보낸 이전 대화 → [(질문, 답)]: 최근 HISTORY_TURNS번, 합쳐 HISTORY_CHARS자(넘으면 오래된 것부터 뺀다).
    없으면 []. 목록이 아니거나 항목이 {"q": 글, "a": 글}이 아니면 ValueError(형식이 틀린 요청)."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > HISTORY_ITEMS_MAX:
        raise ValueError("history는 목록이어야 한다")
    pairs = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("q"), str) or not isinstance(item.get("a"), str):
            raise ValueError("history 항목은 {q, a} 글이어야 한다")
        q = _one_line(item["q"])[:QUESTION_MAX]
        a = "\n".join(_one_line(line) for line in item["a"].splitlines()).strip()[:ANSWER_MAX]
        if q and a:
            pairs.append((q, a))
    pairs = pairs[-HISTORY_TURNS:]
    while pairs and sum(len(q) + len(a) for q, a in pairs) > HISTORY_CHARS:
        pairs.pop(0)
    return pairs


def conversation(pairs: list[tuple[str, str]], screen: str, question: str) -> list[dict[str, str]]:
    """이전 주고받기 뒤에 새 질문. 화면 이름은 새 질문에만(문서는 system, 캐시되는 앞부분)."""
    out: list[dict[str, str]] = []
    for q, a in pairs:
        out += [{"role": "user", "content": f"질문: {q}"}, {"role": "assistant", "content": a}]
    return [*out, {"role": "user", "content": f"지금 화면: {screen}\n\n질문: {question}"}]


def _plain(text: str) -> str:
    """마크다운 굵게·제목 표시를 떼어 낸 평문(화면은 textContent로 넣는다)."""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


# ---- 화면 부품(Web._page가 로그인한 화면에만 붙인다. 패널(iframe) 안 화면에는 붙이지 않는다) ----------------------

HELP_STYLE = """
.help-btn{position:fixed;right:16px;bottom:16px;z-index:50;width:52px;height:52px;min-height:52px;padding:0;border-radius:50%;
font-size:24px;font-weight:600;background:var(--primary);color:#fff;border:0;box-shadow:0 4px 12px rgb(0 0 0/.25)}
.help-btn:hover{background:var(--deep)}
.help-btn.has-talk::after{content:"";position:absolute;top:4px;right:4px;width:12px;height:12px;border-radius:50%;background:#ffd34d;border:2px solid #fff}
.help-acts{display:flex;gap:4px;align-items:center}
.help-box{position:fixed;right:16px;bottom:80px;z-index:51;width:min(380px,calc(100vw - 32px));max-height:min(70vh,560px);
display:flex;flex-direction:column;background:var(--canvas);border:1px solid var(--line);border-radius:12px;box-shadow:0 8px 24px rgb(0 0 0/.2)}
.help-box[hidden]{display:none}
.help-head{display:flex;align-items:center;justify-content:space-between;padding:8px 8px 8px 16px;border-bottom:1px solid var(--line)}
.help-head button{min-height:40px;padding:4px 12px;border-color:transparent}
.help-log{list-style:none;margin:0;padding:12px 16px;overflow-y:auto;flex:1 1 auto;display:grid;gap:8px;align-content:start}
.help-log li{white-space:pre-line;padding:8px 12px;border-radius:10px;max-width:92%}
.help-log .me{justify-self:end;background:var(--tag);color:var(--deep)}
.help-log .bot{justify-self:start;background:var(--soft)}
.help-log .wait{color:var(--ink2)}
.help-form{display:flex;gap:8px;padding:8px;border-top:1px solid var(--line)}
.help-form textarea{flex:1 1 auto;min-height:44px;resize:vertical;font:inherit;border:1px solid var(--mute);border-radius:6px;padding:8px}
@media print{.help-btn,.help-box{display:none!important}}
"""

# 대화 보관(2026-10-09 사용자 요청): 브라우저 localStorage에 로그인한 사용자별 열쇠로 둔다(서버에는 저장하지 않는다).
# 페이지를 옮기거나 창을 접었다 펴도 그대로. 사라지는 때: '새 대화', 20턴(질문 + 답 20쌍)을 넘으면 오래된 것부터, 마지막 질문 뒤 24시간, 로그아웃.
# 순수 함수만 모았다(시험: tests/test_help_store_js.py가 node로 이 문자열을 돌린다).
HELP_STORE_JS = """var MagusHelpStore = (function () {
  var TTL = 24 * 3600 * 1000, MAX = 20, PREFIX = "magus-help:";
  function empty() { return {turns: [], last: 0, open: false}; }
  function read(storage, key, now) {
    var data = null;
    try { data = JSON.parse(storage.getItem(key) || "null"); } catch (e) { data = null; }
    if (!data || !Array.isArray(data.turns)) return empty();
    if (data.last && now - data.last > TTL) { try { storage.removeItem(key); } catch (e) { /* 막힌 저장소 */ } return empty(); }
    var turns = data.turns.filter(function (t) { return t && typeof t.q === "string" && typeof t.a === "string"; }).slice(-MAX);
    return {turns: turns, last: Number(data.last) || 0, open: !!data.open};
  }
  function write(storage, key, data) {
    try { storage.setItem(key, JSON.stringify({turns: data.turns, last: data.last, open: data.open})); } catch (e) { /* 막힌 저장소 */ }
  }
  function add(storage, key, data, q, a, now) {
    var next = {turns: data.turns.concat([{q: q, a: a}]).slice(-MAX), last: now, open: data.open};
    write(storage, key, next);
    return next;
  }
  function clear(storage, key) { try { storage.removeItem(key); } catch (e) { /* 막힌 저장소 */ } return empty(); }
  function clearAll(storage) {
    try {
      for (var i = storage.length - 1; i >= 0; i--) { var k = storage.key(i); if (k && k.indexOf(PREFIX) === 0) storage.removeItem(k); }
    } catch (e) { /* 막힌 저장소 */ }
  }
  return {TTL: TTL, MAX: MAX, PREFIX: PREFIX, read: read, write: write, add: add, clear: clear, clearAll: clearAll};
})();"""

HELP_SCRIPT = """<script>
""" + HELP_STORE_JS + """
(function () {
  var root = document.querySelector(".help");
  if (!root) return;
  var S = MagusHelpStore, key = S.PREFIX + root.getAttribute("data-user"), store = null;
  try { store = window.localStorage; } catch (e) { store = null; }
  if (!store) store = {getItem: function () { return null; }, setItem: function () {}, removeItem: function () {}, key: function () { return null; }, length: 0};
  var btn = root.querySelector(".help-btn"), box = root.querySelector(".help-box"), log = root.querySelector(".help-log");
  var form = root.querySelector(".help-form"), q = form.querySelector("textarea"), send = form.querySelector("button");
  var data = S.read(store, key, Date.now());
  function add(cls, text) {
    var li = document.createElement("li"); li.className = cls; li.textContent = text; log.appendChild(li);
    log.scrollTop = log.scrollHeight; return li;
  }
  function render() { log.textContent = ""; data.turns.forEach(function (t) { add("me", t.q); add("bot", t.a); }); mark(); }
  function mark() { btn.classList.toggle("has-talk", data.turns.length > 0 && box.hidden); }
  function show(on, focus) {  // ✕는 접기: 대화는 그대로 둔다
    box.hidden = !on; btn.setAttribute("aria-expanded", on ? "true" : "false");
    data.open = on; S.write(store, key, data); mark();
    if (on && focus) q.focus();
    if (!on && focus) btn.focus();
  }
  btn.addEventListener("click", function () { show(box.hidden, true); });
  root.querySelector(".help-close").addEventListener("click", function () { show(false, true); });
  root.querySelector(".help-new").addEventListener("click", function () {  // 새 대화: 이 사용자의 대화를 지운다
    data = S.clear(store, key); data.open = !box.hidden; S.write(store, key, data); render(); q.focus();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !box.hidden) show(false, true); });
  document.querySelectorAll('form[action="/logout"]').forEach(function (f) {  // 로그아웃하면 지운다
    f.addEventListener("submit", function () { S.clearAll(store); });
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = q.value.trim();
    if (!text || send.disabled) return;
    var history = data.turns.slice(-3);  // API로는 최근 3번만(서버가 3,000자로 다시 자른다)
    add("me", text); q.value = "";
    var wait = add("bot wait", "…"); send.disabled = true;
    fetch("/help/ask", {method: "POST", credentials: "same-origin", headers: {"content-type": "application/json", "accept": "application/json"},
      body: JSON.stringify({csrf: root.getAttribute("data-csrf"), q: text, screen: document.body.getAttribute("data-screen") || "", history: history})})
      .then(function (r) { return r.json().catch(function () { return {ok: false}; }); })
      .then(function (res) {
        wait.className = "bot"; wait.textContent = res.ok ? res.answer : (res.error || "지금은 도움말을 쓸 수 없어요.");
        if (res.ok) data = S.add(store, key, data, text, res.answer, Date.now());
      })
      .catch(function () { wait.className = "bot"; wait.textContent = "지금은 도움말을 쓸 수 없어요."; })
      .then(function () { send.disabled = false; q.focus(); });
  });
  q.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : send.click(); }
  });
  render();
  if (data.open) show(true, false);  // 페이지를 옮겨도 펼친 채(초점은 빼앗지 않는다)
})();
</script>"""

# 로그아웃 화면: 이 브라우저의 도움말 대화를 모두 지운다(스크립트가 꺼져 있으면 저장된 것도 없다)
CLEAR_SCRIPT = "<script>" + HELP_STORE_JS + "MagusHelpStore.clearAll(window.localStorage);</script>"


def user_key(uid: str) -> str:
    """localStorage 열쇠에 쓰는 사용자 표시(내부 이름의 해시 앞 16자). 다른 사람으로 로그인하면 다른 열쇠라 앞 사람의 대화가 보이지 않는다."""
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(f"magus-help:{uid}".encode()).hexdigest()[:16]


def widget(csrf: str, user: str) -> str:
    """오른쪽 아래 '?' 단추와 작은 대화창. 대화는 이 브라우저에만 보관한다(서버 저장 없음)."""
    return (
        f'<div class="help" data-csrf="{csrf}" data-user="{user}">'
        '<button type="button" class="help-btn" aria-label="도움말" title="도움말" aria-expanded="false" aria-controls="help-box">?</button>'
        '<section class="help-box" id="help-box" role="dialog" aria-label="도움말" hidden>'
        '<div class="help-head"><b>도움말</b><span class="help-acts">'
        '<button type="button" class="help-new">새 대화</button>'
        '<button type="button" class="help-close" aria-label="접기" title="접기">✕</button></span></div>'
        '<ol class="help-log" aria-live="polite"></ol>'
        f'<form class="help-form"><textarea name="q" rows="2" maxlength="{QUESTION_MAX}" aria-label="질문" placeholder="질문"></textarea>'
        '<button class="primary">묻기</button></form></section></div>' + HELP_SCRIPT
    )
