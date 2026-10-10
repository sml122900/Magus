"""휴지통 목록 그리기(2026-10-11 묶음 3: 영구 삭제·휴지통 비우기). 프로젝트 휴지통과 프로젝트 목록의 휴지통이 함께 쓴다.

- 줄마다 [되살리기](되살릴 수 있을 때)와 [영구 삭제], 맨 위에 [휴지통 비우기](그 화면의 전부).
- 누르면 같은 자리에서 확인 창: "되살릴 수 없습니다. 영구 삭제할까요?" [영구 삭제][취소]. 브라우저 alert·confirm은 쓰지 않는다.
  Esc로 닫고, 열면 첫 단추에 초점(지도 화면의 노드 삭제 확인 창과 같은 모양 `.node-del`·`.del-box`).
- 안내 한 줄: "백업에는 최대 1년까지 남을 수 있습니다."
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from magus.ids import local_time

CONFIRM = "되살릴 수 없습니다. 영구 삭제할까요?"
BACKUP_NOTE = "백업에는 최대 1년까지 남을 수 있습니다."
EMPTY = '<p class="empty">휴지통이 비었습니다.</p>'
PURGED = {"purged": "영구 삭제했습니다.", "emptied": "휴지통을 비웠습니다."}

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

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"


def _confirm(action: str, csrf: str, name: str, value: str, summary: str, label: str) -> str:
    close = '<button type="button" class="del-cancel" onclick="this.closest(\'details\').open=false">취소</button>'
    return (f'<details class="node-del purge"><summary class="btn quiet">{summary}</summary>'
            f'<div class="del-box" role="dialog" aria-label="{html.escape(label)}"><p>{CONFIRM}</p>'
            f'<form method="post" action="{html.escape(action)}">{csrf}<input type="hidden" name="{name}" value="{html.escape(value)}">'
            f'<p><button class="primary">영구 삭제</button> {close}</p></form></div></details>')


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
            f'<span class="trash-acts">{restore}{_confirm(action, csrf, "purge", r.key, "영구 삭제", r.label + " 영구 삭제")}</span>'
            + (f'<small class="trash-sub">{html.escape(r.sub)}</small>' if r.sub else "") + "</li>")
    head = (f'<div class="trash-head"><p class="trash-count">{len(rows)}개</p>'
            f'{_confirm(action, csrf, "empty", "1", "휴지통 비우기", "휴지통 비우기")}</div>'
            f'<p class="muted trash-backup">{BACKUP_NOTE}</p>')
    return f'{head}<ol class="trash-list">{"".join(items)}</ol>{TRASH_SCRIPT}'
