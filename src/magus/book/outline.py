"""book_outline: 모든 원고 작업의 첫 호출. 책 전체가 아니라 책의 지도만 준다. 3,000 토큰 이하."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable

from magus.ids import local_time
from magus.store import Store

TOKEN_BUDGET = 3000
_MARGIN = 100  # 섹션 구분자와 추정 오차를 위한 여유분


def estimate_tokens(text: str) -> int:
    """보수적으로 추정한다. 한글 등 비ASCII 문자는 1자를 1토큰, ASCII는 3자를 1토큰으로 센다(실제 토큰 수는 이보다 적다)."""
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return non_ascii + math.ceil((len(text) - non_ascii) / 3)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fit(head: str, items: list[str], budget: int, more: Callable[[int], str]) -> tuple[str, int]:
    """head와 items를 예산 안에서 최대한 싣는다. 잘리면 more(남은 건수) 줄을 붙인다."""
    lines, used = [head], estimate_tokens(head) + 1
    reserve = estimate_tokens(more(len(items))) + 1
    for n, item in enumerate(items):
        cost = estimate_tokens(item) + 1
        is_last = n == len(items) - 1
        if used + cost + (0 if is_last else reserve) > budget:
            lines.append(more(len(items) - n))
            break
        lines.append(item)
        used += cost
    text = "\n".join(lines)
    return text, estimate_tokens(text)


def build_outline(store: Store, user_id: str, project_id: str | None = None, budget: int = TOKEN_BUDGET) -> str:
    project = store.get_project(user_id, project_id)
    if project is None:
        if project_id:
            return f"프로젝트 {project_id!r}가 없습니다."
        return "프로젝트가 없습니다. book_import(path)로 원고를 가져오세요."

    parts = {p.number: p.title for p in store.list_parts(user_id, project.id)}
    chapters = store.list_chapters(user_id, project.id)
    decisions = store.list_decisions(user_id, project.id, limit=10)
    issues = store.list_issues(user_id, project.id, "open")
    changes = store.recent_changes(user_id, project.id, limit=5)
    issues_per_chapter = Counter(i.chapter_number for i in issues if i.chapter_number is not None)

    header = (
        f"# {project.title}\n"
        f"project_id: {project.id} · {len(chapters)}장 · {len(parts)}부 · "
        f"{sum(c.char_count for c in chapters):,}자 · "
        f"미확인 인용 {sum(c.unverified_cite_count for c in chapters)} · 열린 미해결 {len(issues)}"
    )

    toc_items: list[str] = []
    current_part: int | None = None
    for c in chapters:
        if c.part is not None and c.part != current_part:
            toc_items.append(f"### 제{c.part}부 {parts.get(c.part, '')}".rstrip())
        current_part = c.part
        line = f"- {c.number}. {_clip(c.title, 40)} · {c.status} · {c.char_count:,}자 · 미확인 {c.unverified_cite_count}"
        if issues_per_chapter[c.number]:
            line += f" · 미해결 {issues_per_chapter[c.number]}"
        toc_items.append(line)

    change_items = [
        f"- {ch.chapter_number}장 v{ch.version} · {local_time(ch.created_at)} · {_clip(ch.note, 60) or '(메모 없음)'}"
        for ch in changes
    ]
    decision_items = [f"- D{d.id} ({local_time(d.created_at, '%m-%d')}) {_clip(d.text, 100)}" for d in decisions]
    issue_items = [
        f"- I{i.id}"
        + (f" · {i.chapter_number}장" if i.chapter_number is not None else "")
        + (" · 코멘트" if i.origin == "import_comment" else "")
        + f" · {_clip(i.text, 80)}"
        for i in issues
    ]

    # 예산 배분 순서: 머리 → 목차 → 최근 변경 → 결정 → 미해결(남는 만큼). 출력 순서는 따로 정한다.
    remaining = budget - _MARGIN - estimate_tokens(header)
    toc, used = _fit("## 목차", toc_items or ["- (장 없음)"], remaining, lambda n: f"- … 외 {n}줄")
    remaining -= used
    recent, used = _fit("## 최근 변경", change_items or ["- (없음)"], remaining, lambda n: f"- … 외 {n}건")
    remaining -= used
    decided, used = _fit("## 최근 결정", decision_items or ["- (없음)"], remaining, lambda n: f"- … 외 {n}건")
    remaining -= used
    open_issues, _ = _fit(
        f"## 열린 미해결 ({len(issues)})",
        issue_items or ["- (없음)"],
        remaining,
        lambda n: f"- … 외 {n}건 생략 (장별 미해결은 book_read_chapter 메타에 있음)",
    )
    return "\n\n".join([header, toc, decided, open_issues, recent])
