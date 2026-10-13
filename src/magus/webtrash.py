"""휴지통 목록 그리기(2026-10-11 묶음 3: 영구 삭제·휴지통 비우기). 프로젝트 휴지통과 프로젝트 목록의 휴지통이 함께 쓴다.

- 줄마다 [되살리기](되살릴 수 있을 때)와 [영구 삭제], 맨 위에 [휴지통 비우기](그 화면의 전부).
- 누르면 같은 자리에서 확인 창: "되살릴 수 없습니다. 영구 삭제할까요?" [영구 삭제][취소]. 브라우저 alert·confirm은 쓰지 않는다.
  Esc로 닫고, 열면 첫 단추에 초점(지도 화면의 노드 삭제 확인 창과 같은 모양 `.node-del`·`.del-box`).
- 안내 한 줄: "백업에는 최대 1년까지 남을 수 있습니다."
- 원고 프로젝트 삭제 보호(2026-10-14): 올린 문서가 든 줄(guard)은 확인 창에 "이 프로젝트에는 올린 문서(장 N개 · 수정본 EN)가 있습니다."와
  이름 칸이 있고, 이름을 그대로 적어야 [영구 삭제]가 켜진다(서버도 다시 본다). [휴지통 비우기]는 그 줄을 빼고 비운 뒤
  "올린 문서가 든 프로젝트 N개는 남겼습니다."로 알린다. 프로젝트를 휴지통으로 옮기는 확인 창(webmap)과 올린 문서 휴지통(webbooks)도 같은 이름 칸.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from magus.ids import local_time
from magus.store.base import UploadGuard

CONFIRM = "되살릴 수 없습니다. 영구 삭제할까요?"
BACKUP_NOTE = "백업에는 최대 1년까지 남을 수 있습니다."
EMPTY = '<p class="empty">휴지통이 비었습니다.</p>'
PURGED = {"purged": "영구 삭제했습니다.", "emptied": "휴지통을 비웠습니다."}
NAME_ERROR = "이름이 맞지 않아 영구 삭제하지 않았습니다. 확인 창에 보이는 이름을 그대로 적어 주세요."


def kept_text(projects: int, manuscripts: int, done: bool = True) -> str:
    """휴지통 비우기에서 남기는 것: '올린 문서가 든 프로젝트 1개는 남겼습니다.'(done이 아니면 '남깁니다.'). 남긴 것이 없으면 빈 글."""
    parts = ([f"올린 문서가 든 프로젝트 {projects}개"] if projects else []) + ([f"올린 문서 {manuscripts}개"] if manuscripts else [])
    return f"{'와 '.join(parts)}는 {'남겼습니다' if done else '남깁니다'}." if parts else ""


def done_message(params: Any) -> str:
    """?done=purged|emptied(&kept=N&kept_ms=M) → 알림 한 줄."""
    said = PURGED.get(params.get("done") or "", "")
    if said and params.get("done") == "emptied":
        extra = kept_text(_count(params.get("kept")), _count(params.get("kept_ms")))
        said = f"{said} {extra}" if extra else said
    return said


def _count(value: object) -> int:
    return int(value) if isinstance(value, str) and value.isdigit() else 0


# 이름 칸(data-confirm-name)에 그 이름을 그대로 적어야 같은 폼의 채운 단추가 켜진다. 규칙은 store.base.same_name과 같다
# (공백 차이·앞뒤 따옴표·NFC). 뒤로 가기(bfcache)로 돌아오면 FORM_SCRIPT가 폼을 비우고 단추를 켜므로 다시 맞춘다.
NAME_SCRIPT = """<script>
(function () {
  if (window.magusNameGuard) return;
  window.magusNameGuard = true;
  var Q = /^[「」『』"'“”‘’]+|[「」『』"'“”‘’]+$/g;
  function norm(s) { return (s || "").normalize("NFC").split(/\\s+/).join(" ").trim().replace(Q, "").trim(); }
  function sync(input) {
    var b = input.form && input.form.querySelector("button.primary");
    if (b) b.disabled = !norm(input.value) || norm(input.value) !== norm(input.getAttribute("data-confirm-name"));
  }
  function all() { document.querySelectorAll("input[data-confirm-name]").forEach(sync); }
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches("input[data-confirm-name]")) sync(e.target);
  });
  window.addEventListener("pageshow", function () { setTimeout(all, 0); });
  all();
})();
</script>"""


def name_field(guard: UploadGuard) -> str:
    """확인 창 안: 올린 문서 한 줄 + 이름 칸(채운 단추는 disabled로 그리고 NAME_SCRIPT가 켠다)."""
    name = html.escape(guard.name)
    return (f'<p class="big-warn">{html.escape(guard.sentence)}</p>'
            f'<p><label>확인을 위해 이름을 적어 주세요: 「{name}」'
            f'<input name="confirm_name" data-confirm-name="{name}" autocomplete="off" spellcheck="false" required></label></p>')


# 휴지통 화면에서만: Esc로 확인 창을 닫고, 열면 첫 단추로 초점(지도 화면의 MAP_SCRIPT와 같은 동작)
TRASH_SCRIPT = """<script>
(function () {
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.node-del[open]").forEach(function (d) { d.open = false; d.querySelector("summary").focus(); });
  });
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (d.matches && d.matches("details.node-del") && d.open) { var b = d.querySelector(".del-box button"); if (b) b.focus(); }
  }, true);
})();
</script>"""


@dataclass(frozen=True)
class TrashRow:
    """휴지통 한 줄. restore: 되살리기 폼의 칸 이름(그 값은 id). 없으면 되살리기 단추가 없다(영구 삭제만)."""

    kind: str
    id: str
    at: str
    label: str
    sub: str = ""
    restore: str | None = None
    guard: UploadGuard | None = None  # 올린 문서가 든 것: 영구 삭제에 이름, 비우기에서 뺀다(2026-10-14)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"


def _confirm(action: str, csrf: str, name: str, value: str, summary: str, label: str, guard: UploadGuard | None = None,
             note: str = "") -> str:
    close = '<button type="button" class="del-cancel" onclick="this.closest(\'details\').open=false">취소</button>'
    lock = " disabled" if guard else ""
    return (f'<details class="node-del purge"><summary class="btn quiet">{summary}</summary>'
            f'<div class="del-box" role="dialog" aria-label="{html.escape(label)}"><p>{CONFIRM}</p>'
            + (f"<p>{html.escape(note)}</p>" if note else "")
            + f'<form method="post" action="{html.escape(action)}">{csrf}<input type="hidden" name="{name}" value="{html.escape(value)}">'
            + (name_field(guard) if guard else "")
            + f'<p><button class="primary"{lock}>영구 삭제</button> {close}</p></form></div></details>')


def trash_list_html(rows: list[TrashRow], action: str, csrf: str) -> str:
    """개수 · [휴지통 비우기] · 백업 안내 · 목록. 비면 '휴지통이 비었습니다.'"""
    if not rows:
        return EMPTY
    items = []
    for r in rows:
        restore = (f'<form method="post" action="{html.escape(action)}" class="inline">{csrf}'
                   f'<input type="hidden" name="{r.restore}" value="{html.escape(r.id)}"><button>되살리기</button></form>' if r.restore else "")
        items.append(
            f'<li><time datetime="{html.escape(r.at)}">{local_time(r.at, "%Y-%m-%d %H:%M")}</time> <b>{html.escape(r.label)}</b>'
            f'<span class="trash-acts">{restore}{_confirm(action, csrf, "purge", r.key, "영구 삭제", r.label + " 영구 삭제", r.guard)}</span>'
            + (f'<small class="trash-sub">{html.escape(r.sub)}</small>' if r.sub else "") + "</li>")
    kept = kept_text(sum(1 for r in rows if r.guard and r.guard.kind == "project"),
                     sum(1 for r in rows if r.guard and r.guard.kind != "project"), done=False)
    head = (f'<div class="trash-head"><p class="trash-count">{len(rows)}개</p>'
            f'{_confirm(action, csrf, "empty", "1", "휴지통 비우기", "휴지통 비우기", note=kept)}</div>'
            f'<p class="muted trash-backup">{BACKUP_NOTE}</p>')
    return f'{head}<ol class="trash-list">{"".join(items)}</ol>{TRASH_SCRIPT}{NAME_SCRIPT if any(r.guard for r in rows) else ""}'
