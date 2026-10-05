"""저자 확인 질문지 MCP 도구(#84): book_questions(조회) → book_answer(답 반영). 판별·반영은 magus.melchior.questions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool

from magus.book.outline import estimate_tokens
from magus.melchior.questions import TYPES, answer_question, build_questions
from magus.store import Project, Store

BUDGET = 3000  # 응답 토큰 상한(book_outline과 같은 보수적 추정). 넘치면 "외 N건"으로 접는다
STATES = {"open": "열림", "waiting": "답함·원고 반영 대기", "answered": "답함"}


def build_tools(store: Store, current_user: Callable[[], str]) -> list[Tool]:
    def project_of(project_id: str | None) -> Project:
        project = store.get_project(current_user(), project_id)
        if project is None:
            raise ToolError(f"프로젝트 {project_id!r}가 없습니다." if project_id else "프로젝트가 없습니다. book_import로 원고를 가져오세요.")
        return project

    def book_questions(
        status: Literal["open", "waiting", "all"] = "open",
        type: Literal["year", "bibonly", "translit", "ab", "pair", "unlinked", "dup"] | None = None,
        project_id: str | None = None,
    ) -> str:
        user, project = current_user(), project_of(project_id)
        questions = build_questions(store, user, project.id)
        counts = {s: sum(1 for q in questions if q.state == s) for s in STATES}
        chosen = [q for q in questions if (status == "all" or q.state == status) and (type is None or q.type == type)]
        lines = [
            f"프로젝트: {project.title} ({project.id}) · 저자에게 물을 것 {len(questions)}건"
            f"(열림 {counts['open']} · 원고 반영 대기 {counts['waiting']} · 답함 {counts['answered']})",
            f"보기: status={status}" + (f" · type={type}({TYPES[type]})" if type else "")
            + ". 저자가 답하면 book_answer(question_id, choice)로 남긴다. 저자 대신 짐작해서 답하지 않는다.",
        ]
        used = sum(estimate_tokens(line) for line in lines)
        for n, q in enumerate(chosen, 1):
            block = [f"{n}. [{q.id}] {TYPES[q.type]} — {q.text}",
                     "   선택: " + " / ".join(f"{code} {label}" for code, label in q.options)]
            if q.answer:
                block.append(f"   답: {q.answer.get('choice', '')}" + (f" · {q.answer['decision']}" if q.answer.get("decision") else "")
                             + f" · {STATES[q.state]}")
            size = sum(estimate_tokens(b) for b in block)
            if used + size > BUDGET:
                lines.append(f"외 {len(chosen) - n + 1}건 — type으로 좁혀 본다.")
                break
            lines += block
            used += size
        if not chosen:
            lines.append("없음")
        return "\n".join(lines)

    def book_answer(question_id: str, choice: str, note: str = "", project_id: str | None = None) -> str:
        user, project = current_user(), project_of(project_id)
        question = next((q for q in build_questions(store, user, project.id) if q.id == question_id.strip()), None)
        if question is None:
            raise ToolError(f"지금 원고에 없는 질문이다: {question_id}. 이미 해결됐거나 id가 다르다. book_questions로 확인한다.")
        try:
            record = answer_question(store, user, project.id, question, choice.strip(), note)
        except ValueError as e:
            raise ToolError(str(e)) from e
        label = dict(question.options).get(record["choice"], record["choice"])
        done = []
        if record["applied"].startswith("alias "):
            done.append(f"표기 「{question.surface}」를 그 문헌에 이음(수가 다시 계산됨)")
        elif record["applied"]:
            done.append(f"인용이 아닌 낱말로 둠: {record['applied'].split()[-1]}")
        if record["decision"]:
            done.append(f"결정 {record['decision']}로 남김(Word에서 고친 뒤 수정본을 올리면 질문이 사라진다)")
        left = sum(1 for q in build_questions(store, user, project.id) if q.state == "open")
        return f"답을 기록함: [{question.id}] {label}" + (" · " + " · ".join(done) if done else "") + f". 남은 열린 질문 {left}건."

    return [
        Tool.from_function(
            book_questions, name="book_questions",
            description=(
                "저자만 답할 수 있는 인용 질문 목록(조회 전용): 연도 불일치(year), 참고문헌에만 있음(bibonly), 한글 표기 추정(translit), "
                "연도 a/b 모호(ab), 같은 저자·연도 두 편(pair), 미연결 표기(unlinked), 중복 서지(dup). "
                "질문은 매번 지금 원고와 문헌에서 계산한다(수정본을 올리면 저절로 새 원고 기준). 본문은 싣지 않고 원고 표기와 장만 싣는다. "
                "status=open(기본, 아직 답 없음)|waiting(답했고 Word 수정 대기)|all. 질문마다 [id]와 선택지 코드가 있다."
            ),
            structured_output=False,
        ),
        Tool.from_function(
            book_answer, name="book_answer",
            description=(
                "저자가 그 질문에 분명히 답했을 때만 부른다. Claude가 짐작해서 답하지 않는다. "
                "question_id는 book_questions의 [ ] 안 id, choice는 그 질문의 선택지 코드다(ref:<key>는 다른 문헌을 고를 때 그 문헌의 key). "
                "원고 표기를 문헌에 잇는 답과 '사람 이름이 아니다'는 바로 반영되고 수가 다시 계산된다. "
                "'Word에서'라고 적힌 답은 결정으로 남는다(저자가 Word에서 고친 뒤 수정본을 올리면 질문이 사라진다). "
                "note에는 저자의 말을 짧게 적는다. 답은 원고와 함께 남아 다시 묻지 않는다."
            ),
            structured_output=False,
        ),
    ]
