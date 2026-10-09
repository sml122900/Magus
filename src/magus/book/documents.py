"""문서 책 만들기(사용자 결정 #94). 첫 종류: 출처 확인 문서.

사실 부분(질문·불일치·사실 확인 요청·우선 문헌·장별 수·바뀐 점)은 서버가 원고·문헌·확인 요청 데이터에서 그대로 만든다.
Claude는 수치나 문헌 목록을 옮겨 쓰지 않는다. 저자가 원하면 머리말만 붙이고, 그 머리말은 누가 썼는지(AI·저자) 표시한다.
문서는 그 시점의 사진이다. 기준 원고에 새 수정본이 오면 '옛 판 기준'이 되고, 다시 만들면 새 판이 생긴다(이전 판은 이력).
"""

from __future__ import annotations

from magus.ids import local_time, utcnow
from magus.melchior.author_report import fact_lines, gather, mismatch_lines, per_chapter_lines, ranked_lines, summary_line
from magus.melchior.questions import TYPES as QUESTION_TYPES
from magus.melchior.questions import build_questions
from magus.store import DocVersion, Document, Store

DOC_TYPES = {"source_check": "출처 확인 문서"}  # 저자에게 보이는 이름 → 도구 인자도 이것
DOC_TYPE_BY_NAME = {name: key for key, name in DOC_TYPES.items()}
QUESTIONS_SHOWN = 40
DOCUMENT_COLOR = "#5b5f66"  # 문서 책의 처음 색(회청색). 저자가 바꿀 수 있다
STALE_WORDS = "옛 판 기준"
IN_MISMATCH = ("year", "bibonly")  # 원고 불일치(2절)에서 보이는 질문 종류


def latest_edition(store: Store, user_id: str, project_id: str) -> int | None:
    editions = store.list_editions(user_id, project_id)
    return editions[-1].number if editions else None


def is_stale(store: Store, user_id: str, doc: Document) -> bool:
    """기준 원고에 이 문서가 만든 뒤 새 수정본이 왔나."""
    made = doc.versions[-1].edition
    now = latest_edition(store, user_id, doc.project_id)
    return now is not None and (made is None or now > made)


def build_source_check(store: Store, user_id: str, project_id: str, title: str, *, preface: str | None = None,
                       preface_by: str | None = None, previous: DocVersion | None = None) -> tuple[str, DocVersion]:
    """(markdown, 판 정보). 판 번호·시각은 저장소가 붙인다."""
    p = gather(store, user_id, project_id)
    project = p.project
    editions = store.list_editions(user_id, project_id)
    edition = editions[-1] if editions else None
    questions = [q for q in build_questions(store, user_id, project_id, p.cache) if q.state in ("open", "waiting")]
    asked = [q for q in questions if q.type not in IN_MISMATCH]  # 연도 불일치·참고문헌에만 있음은 2절(원고 불일치)에서 보인다
    open_issues = store.list_issues(user_id, project_id, "open")
    fact_count, facts = fact_lines(store, user_id, project_id)
    stats = {"occurrences": p.occurrences, "documents": p.documents, "verified": p.verified, "unverified": len(p.unchecked),
             "open_issues": len(open_issues), "questions": len(questions), "facts": fact_count}
    made = utcnow()
    basis = (f"수정본 E{edition.number}({local_time(edition.uploaded_at, '%Y-%m-%d %H:%M')}에 올린 {edition.file})" if edition
             else "수정본 기록 없음")
    lines = [
        f"# {title}",
        "",
        f"기준 문서: 『{project.title}』 {basis} · 만든 시각: {local_time(made, '%Y-%m-%d %H:%M')}",
        "",
        "만든 방법: 이 문서의 질문·수치·문헌 목록은 Magus가 올린 문서·문헌·확인 요청 데이터에서 그대로 만들었습니다(Claude가 옮겨 쓴 것이 아닙니다).",
    ]
    if preface and preface.strip():
        who = "Claude(AI)가 쓴 머리말입니다." if preface_by != "author" else "저자가 말한 머리말입니다."
        lines += ["", "## 머리말", f"*{who}*", "", preface.strip()]
    lines += [
        "", "## 한눈에",
        f"- {summary_line(p)}",
        f"- 열린 확인 요청 **{len(open_issues)}건**, 답해 주실 질문 **{len(questions)}건**"
        + (f"(1절 {len(asked)}건 · 2절 본문 불일치 {len(questions) - len(asked)}건)" if len(questions) > len(asked) else "")
        + f", 사실·수치 확인 요청 **{fact_count}건**",
        "", f"## 1. 답해 주실 질문 {len(asked)}건",
        "답은 올린 문서의 확인 요청이나 Claude와의 대화에서 해 주세요. 이 문서는 읽기용입니다. "
        "연도가 맞지 않는 것과 참고문헌에만 있는 것은 2절에 있습니다.",
        "",
    ]
    for q in asked[:QUESTIONS_SHOWN]:
        choices = " / ".join(label.replace("(그 key)", "") for _, label in q.options)
        waiting = " (답함 · 원본 반영 대기)" if q.state == "waiting" else ""
        lines.append(f"- **{QUESTION_TYPES.get(q.type, q.type)}**{waiting} — {q.text}" + (f" 고를 수 있는 답: {choices}" if choices else ""))
    if len(asked) > QUESTIONS_SHOWN:
        lines.append(f"- … 외 {len(asked) - QUESTIONS_SHOWN}건(올린 문서의 인용 상태에서 모두 볼 수 있습니다)")
    if not asked:
        lines.append("- 없습니다.")
    lines += ["", "## 2. 본문 불일치", *mismatch_lines(p),
              "", f"## 3. 사실·수치 확인 요청 {fact_count}건", *facts,
              "", "## 4. 원문 확인 우선 문헌", "가장 많이 인용된 문헌부터 원문을 확인하시면 한 번에 여러 곳이 해결됩니다.", "",
              *(ranked_lines(p) or ["없습니다."]),
              "", "## 5. 장별 미확인 문헌 수", "", *per_chapter_lines(p),
              "", "## 6. 이전 수정본 대비 바뀐 점", *changes_lines(editions, previous, stats),
              "", "---",
              f"이 문서는 {local_time(made, '%Y-%m-%d %H:%M')}의 사진입니다. 올린 문서에 새 수정본이 오면 책장에서 '{STALE_WORDS}'으로 표시되고, "
              "문서 화면에서 다시 만들 수 있습니다(이전 판은 이력으로 남습니다)."]
    version = DocVersion(0, made, edition.number if edition else None, "server+preface" if preface and preface.strip() else "server",
                         (preface_by or "ai") if preface and preface.strip() else None, stats)
    p.cache.save()
    return "\n".join(lines) + "\n", version


def changes_lines(editions: list, previous: DocVersion | None, stats: dict[str, int]) -> list[str]:
    out = []
    if len(editions) >= 2:
        last, before = editions[-1], editions[-2]
        out.append(f"- 수정본 E{before.number} → E{last.number}({local_time(last.uploaded_at, '%Y-%m-%d')}): "
                   f"본문이 바뀐 장 {last.changed}(새 장 {last.added} 포함) · 빠진 장 {last.removed} · 그대로 {last.unchanged}")
    if previous is not None:
        old = previous.stats
        pairs = [("미확인 문헌", "unverified", "편"), ("원문 대조 완료", "verified", "편"), ("열린 확인 요청", "open_issues", "건"),
                 ("답해 주실 질문", "questions", "건"), ("사실·수치 확인 요청", "facts", "건")]
        moved = " · ".join(f"{name} {old.get(key, 0)} → {stats.get(key, 0)}{unit}" for name, key, unit in pairs)
        base = f"E{previous.edition} 기준" if previous.edition else "수정본 기록 없음"
        out.append(f"- 이 문서의 이전 판(v{previous.number}, {base}, {local_time(previous.at, '%Y-%m-%d')}) 대비: {moved}")
    return out or ["- 견줄 이전 수정본이 없습니다(처음 올린 문서)."]


def default_title(store: Store, user_id: str, project_id: str, doc_type: str) -> str:
    project = store.get_project(user_id, project_id)
    name = project.title.split(" — ")[0].split(":")[0].strip() if project else project_id
    return f"{name} {DOC_TYPES[doc_type]}"

