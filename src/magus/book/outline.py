"""book_outline: 모든 원고 작업의 첫 호출. 책 전체가 아니라 책의 지도만 준다. 3,000 토큰 이하."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from magus.limits import TITLE_MAX
from magus.category.maptext import outline_lines
from magus.ids import STAMP, local_time
from magus.store import ChapterMeta, Project, Store

TOKEN_BUDGET = 3000
STALE_UPLOAD_DAYS = 7  # 마지막 업로드 뒤 이만큼 지나면 최신본을 올렸는지 묻게 한다(#76, 아버지 작업 주기를 보고 바꾼다)
_MARGIN = 100  # 섹션 구분자와 추정 오차를 위한 여유분
_OTHER_PROJECTS_SHOWN = 5


def estimate_tokens(text: str) -> int:
    """보수적으로 추정한다. 한글 등 비ASCII 문자는 1자를 1토큰, ASCII는 3자를 1토큰으로 센다(실제 토큰 수는 이보다 적다)."""
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return non_ascii + math.ceil((len(text) - non_ascii) / 3)


def chapter_count(chapters: list[ChapterMeta]) -> str:
    return count_by_labels([c.label for c in chapters])


def count_by_labels(labels: list[str | None]) -> str:
    """'35장 + 서장·부 들어가며 2·맺음·부록 1~3'. 번호 없는 장은 이름으로 적고, 부록은 이어지면 범위로 묶는다."""
    named = [label for label in labels if label]
    appendix = sorted(int(m.group(1)) for label in named if (m := re.fullmatch(r"부록\s*(\d+)", label)))
    intros = [label for label in named if label.endswith("부 들어가며")]
    others = [label for label in named if not re.fullmatch(r"부록\s*\d+", label) and label not in intros]
    if intros:
        others.insert(1 if others[:1] == ["서장"] else 0, f"부 들어가며 {len(intros)}")
    if appendix:
        contiguous = len(appendix) > 1 and appendix == list(range(appendix[0], appendix[-1] + 1))
        others.append(f"부록 {appendix[0]}~{appendix[-1]}" if contiguous else "부록 " + "·".join(map(str, appendix)))
    numbered = f"{len(labels) - len(named)}장"
    return f"{numbered} + {'·'.join(others)}" if others else numbered


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


def edition_line(store: Store, user_id: str, project: Project, chapters: list[ChapterMeta], now: datetime | None = None) -> str:
    """'수정본 E2 · 마지막 업로드 10-06 14:20(원고.docx) · 그 뒤 Magus에서 고친 장 0'(#76). 첫 업로드는 '처음 올린 문서 E1'.
    원고 본문의 원본은 저자 파일이다(#68). 마지막 업로드가 STALE_UPLOAD_DAYS보다 오래되면 최신본을 올렸는지 묻게 한다.
    서버는 Word 파일이 바뀌었는지 알 수 없어 시각만 알리고 판단은 저자에게 묻는다."""
    editions = store.list_editions(user_id, project.id)
    edited = sum(1 for c in chapters if (c.edition is None if editions else c.version > 1))
    if editions:
        last = editions[-1]
        name = f"수정본 E{last.number}" if last.number > 1 else "처음 올린 문서 E1"  # 저자에게 보이는 이름(용어집)
        line = f"{name} · 마지막 업로드 {local_time(last.uploaded_at, STAMP)}({_clip(last.file, 40)})"
        at = last.uploaded_at
    elif not chapters:  # 올린 문서 없이 만든 프로젝트(전에는 가져온 적 없는데 '임포트 시각'처럼 보였다, 점검 16-1)
        return "올린 문서 없음"
    else:
        line = f"수정본 기록 없음(수정본 기능 전 임포트) · 임포트 {local_time(project.created_at, STAMP)}"
        at = project.created_at
    line += f" · 그 뒤 Magus에서 고친 장 {edited}"
    try:
        days = ((now or datetime.now(UTC)) - datetime.fromisoformat(at.replace("Z", "+00:00"))).days
    except ValueError:
        return line
    if days >= STALE_UPLOAD_DAYS:
        line += (f" — 업로드 뒤 {days}일 지남. 그사이 저자가 Word에서 고쳤다면, 최신본을 책장(가운데 노드)에서 "
                 "수정본으로 올리도록(book_import new_edition) 저자에게 먼저 묻는다")
    return line


def build_outline(
    store: Store, user_id: str, project_id: str | None = None, budget: int = TOKEN_BUDGET, now: datetime | None = None
) -> str:
    project = store.get_project(user_id, project_id)
    if project is None:
        if project_id:
            return f"프로젝트 {project_id!r}가 없습니다."
        return "프로젝트가 없습니다. book_import(path)로 문서를 가져오세요."

    parts = {p.number: p.title for p in store.list_parts(user_id, project.id)}
    chapters = store.list_chapters(user_id, project.id)
    decisions = store.list_decisions(user_id, project.id, limit=10)
    issues = store.list_issues(user_id, project.id, "open")
    changes = store.recent_changes(user_id, project.id, limit=5)
    issues_per_chapter = Counter(i.chapter_number for i in issues if i.chapter_number is not None)
    labels = {c.number: c.label for c in chapters if c.label}  # 90번대 특수 장은 번호 대신 '맺음'·'부록 N'

    def name(number: int) -> str:
        return labels.get(number) or f"{number}장"

    # 첫 줄은 항상 어느 프로젝트인지 밝힌다. project_id를 생략하면 최근 프로젝트가 골라지기 때문이다.
    header_lines = [f"프로젝트: {project.title} ({project.id})"]
    if project.subtitle or project.title_en:  # 제목과 부제를 따로 둔다(#77)
        english = _clip(" — ".join(x for x in (project.title_en, project.subtitle_en) if x), TITLE_MAX)  # 옛 긴 값도 줄 하나로(점검 15-6)
        header_lines.append(" · ".join(x for x in (f"부제: {_clip(project.subtitle, TITLE_MAX)}" if project.subtitle else "",
                                                   f"영문: {english}" if english else "") if x))
    others = [p for p in store.list_projects(user_id) if p.id != project.id]
    if others:
        listed = ", ".join(f"{_clip(p.title, 20)}({p.id})" for p in others[:_OTHER_PROJECTS_SHOWN])
        more = f" 외 {len(others) - _OTHER_PROJECTS_SHOWN}개" if len(others) > _OTHER_PROJECTS_SHOWN else ""
        header_lines.append(
            f"이 사용자의 프로젝트는 {len(others) + 1}개다. 다른 프로젝트: {listed}{more} (project_id로 지정)"
        )
    # 미확인 문헌은 책 전체 고유 수다(여러 장에 나오는 문헌은 한 번). 장별 수는 각 장 줄에만 싣는다.
    # 미연결(한글 표기인데 refs와 잇지 못한 것)은 미확인 수에 넣지 않지만 숨기지 않는다(ref_check의 uncertain 목록).
    unique_unverified = len({key for c in chapters for key in c.unverified_cite_keys})
    unlinked = len({key for c in chapters for key in c.uncertain_cite_keys})
    header_lines.append(
        f"{chapter_count(chapters)} · {len(parts)}부 · {sum(c.char_count for c in chapters):,}자 · "
        f"미확인 문헌 {unique_unverified}편 · 미연결 {unlinked} · 열린 확인 요청 {len(issues)}"
    )
    header_lines.append(edition_line(store, user_id, project, chapters, now))
    header_lines += outline_lines(store, user_id, project.id)  # 이 프로젝트의 지도: 노드·책·연결과 선(#95)
    header = "\n".join(header_lines)

    # 목차 줄에는 집계만 싣는다. 장별 미해결 수에는 코멘트 유래까지 모두 센다.
    toc_items: list[str] = []
    current_part: int | None = None
    for c in chapters:
        if c.part_number is not None and c.part_number != current_part:
            toc_items.append(f"### 제{c.part_number}부 {parts.get(c.part_number, '')}".rstrip())
        elif c.part_number is None and current_part is not None:
            toc_items.append("### (부 밖)")  # 부가 끝난 뒤의 맺음·부록
        current_part = c.part_number
        # 번호 없는 장은 도구에 줄 번호를 괄호로 밝힌다(서장(0), 제2부 들어가며(102), 부록 1(91))
        toc_items.append(
            f"- {c.display}{f'({c.number})' if c.label else ''} {_clip(c.title, 24)} · {c.status} · {c.char_count:,}자 · "
            f"확인 요청 {issues_per_chapter[c.number]} · 미확인인용 {c.unverified_cite_count}"
        )

    # 전문을 싣는 미해결은 사람(user)과 에이전트(agent)가 남긴 것만이다. 코멘트 유래는 건수만 싣는다.
    direct = [i for i in issues if i.origin != "import_comment"]
    from_comments = len(issues) - len(direct)
    issue_head = f"## 열린 확인 요청 (직접 남긴 것 {len(direct)}건)"
    if from_comments:
        kinds = Counter(i.kind for i in issues if i.origin == "import_comment")
        split = " · ".join(f"{k} {kinds[k]}" for k in ("citation", "fact", "general") if kinds[k])
        by_ai = sum(1 for i in issues if i.origin == "import_comment" and i.by_ai)  # 누가 말했는지 보존한다(#71)
        ai = f" · 그중 AI 확인 요청 {by_ai}건(AI가 문서에 단 코멘트)" if by_ai else ""
        issue_head += f"\n- 코멘트 유래 확인 요청 {from_comments}건({split}){ai} — book_issues(kind)로 조회"
        if stale := sum(1 for i in issues if i.stale):  # 다시 올린 뒤 원고에서 코멘트·걸린 문장이 사라진 것(#76). 닫지 않았다
            issue_head += f"\n- 그중 해결됐을 수 있음 {stale}건(수정본에서 코멘트나 걸린 문장이 사라짐) — book_issues(possibly_resolved=true)로 확인"
    issue_items = [
        f"- I{i.id}"
        + (f" · {name(i.chapter_number)}" if i.chapter_number is not None else "")
        + (" · agent" if i.origin == "agent" else "")
        + f" · {_clip(i.text, 60)}"
        for i in direct
    ]
    decision_items = [f"- D{d.id} ({local_time(d.created_at, '%m-%d')}) {_clip(d.text, 60)}" for d in decisions]
    change_items = [
        f"- {name(ch.chapter_number)} v{ch.version} · {local_time(ch.created_at)} · {_clip(ch.note, 50) or '(메모 없음)'}"
        for ch in changes
    ]

    # 예산 배분 순서: 머리 → 목차 → 직접 남긴 미해결 → 결정 → 최근 변경. 출력 순서는 따로 정한다.
    remaining = budget - _MARGIN - estimate_tokens(header)
    toc, used = _fit("## 목차", toc_items or ["- (장 없음)"], remaining, lambda n: f"- … 외 {n}줄")
    remaining -= used
    open_issues, used = _fit(
        issue_head,
        issue_items or ([] if from_comments else ["- (없음)"]),
        remaining,
        lambda n: f"- … 외 {n}건 — book_issues로 조회",
    )
    remaining -= used
    # 가장 최근 변경 한 줄은 결정보다 먼저 자리를 잡아 둔다(지도 줄이 머리에 더해진 뒤로 큰 책에서 변경이 통째로 빠지지 않게, #93·#95)
    keep = estimate_tokens("## 최근 변경\n" + change_items[0]) + 2 if change_items else 0
    decided, used = _fit("## 최근 결정", decision_items or ["- (없음)"], remaining - keep, lambda n: f"- … 외 {n}건")
    remaining -= used
    recent, _ = _fit("## 최근 변경", change_items or ["- (없음)"], remaining, lambda n: f"- … 외 {n}건")
    return "\n\n".join([header, toc, decided, open_issues, recent])
