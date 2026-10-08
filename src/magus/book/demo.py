"""1단계 확인용 가짜 프로젝트. 실제 원고(fixtures)는 2단계 book_import로 들어온다."""

from __future__ import annotations

from magus.book.comments import classify_comment
from magus.ids import new_id
from magus.store import CategoryItem, Context, Part, Project, Store

DEMO_PROJECT_ID = "demo"

_CHAPTERS = [
    (1, 1, "물가의 망설임", "데본기 얕은 물가. 지느러미로 바닥을 짚는 물고기가 있었다(Daeschler, Shubin & Jenkins, 2006)."),
    (2, 1, "목이 생긴 날", "아가미덮개가 사라지고 목이 생겼다. Clack(2012)은 이 변화를 길게 다룬다."),
    (3, 1, "숨의 경제학", "폐는 처음부터 육지를 위해 생긴 기관이 아니었다. [출처 필요: 초기 폐의 기능]"),
    (4, 2, "닿으려는 손", "손가락은 걷기보다 먼저 물풀을 헤치기 위해 생겼을지도 모른다."),
    (5, 2, "뭍의 첫 밤", "갤러(2022)의 말처럼, 이동은 언제나 비용과 기회의 계산이었다."),
]


def seed_demo(store: Store, user_id: str) -> tuple[Project, bool]:
    """(프로젝트, 새로 만들었는지). 이미 있으면 건드리지 않는다."""
    existing = store.get_project(user_id, DEMO_PROJECT_ID)
    if existing:
        return existing, False
    project = store.create_project(user_id, "데모: 물에서 뭍으로", project_id=DEMO_PROJECT_ID)
    store.set_parts(user_id, project.id, [Part(1, "물가"), Part(2, "뭍")])
    for number, part, title, body in _CHAPTERS:
        store.write_chapter(user_id, project.id, number, body, "데모 초안", title=title, part_number=part)
    store.write_chapter(
        user_id, project.id, 2, _CHAPTERS[1][3] + "\n\n목은 머리를 돌리는 자유였다.", "2장 끝에 한 문장 추가"
    )
    store.add_decision(user_id, project.id, "각 장은 하나의 생물 장면으로 연다.")
    store.add_decision(user_id, project.id, "학명은 처음 나올 때만 괄호 병기.")
    comment = "Daeschler 2006 원문 확인 필요"
    kind, ref_key = classify_comment(comment)
    store.add_issue(
        user_id, project.id, comment, origin="import_comment", chapter_number=1, kind=kind, ref_key=ref_key
    )
    store.add_issue(user_id, project.id, "3장 폐의 기원 출처 찾기", chapter_number=3)
    store.add_issue(user_id, project.id, "2부 제목 후보 더 생각하기")
    return store.get_project(user_id, project.id) or project, True


def seed_demo_shelf(store: Store, user_id: str) -> None:
    """Desktop에서 글 넣기·찾기를 바로 써 볼 수 있게 책 둘(컨텍스트 「생각 메모」·「문체」)에 글을 몇 개 넣는다(CLI seed-demo 전용, #96)."""
    saved = {c.name: c for c in store.list_saved_contexts(user_id)}

    def book(name: str, context: str, color: str) -> str:
        found = next((c for c in store.list_categories(user_id, floors=[DEMO_PROJECT_ID]) if c.name == name), None)
        if found:
            return found.id
        ctx = saved.get(context)
        return store.create_category(user_id, name, "blank", color, (), DEMO_PROJECT_ID,
                                     contexts=(Context(ctx.name, ctx.text),) if ctx else ()).id

    ideas = book("생각", "생각 메모", "#1f2f5c")
    for text in ("물고기가 뭍으로 올라온 건 용기가 아니라 궁지였다.", "이 책의 축은 닿으려는 몸짓이다."):
        store.put_category_item(user_id, CategoryItem(new_id(), ideas, text, "me", origin="데모", kind="thought"))
    question = store.put_category_item(user_id, CategoryItem(new_id(), ideas, "고래는 왜 다시 물로 돌아갔을까?", "me",
                                                             origin="데모 대화", kind="conversation"))
    store.put_category_item(user_id, CategoryItem(new_id(), ideas, "먹이와 경쟁의 조건이 바뀌면 이전 환경이 다시 유리해질 수 있습니다.",
                                                  "ai", origin="데모 대화", kind="conversation", parent_id=question.id))
    styles = book("문체", "문체", "#6e1f2f")
    for passage, reason, tags, work in [
        ("고래는 돌아갔다. 물이 고래를 불렀다. 고래는 대답했다.", "짧은 문장과 같은 주어의 반복이 숨 가쁜 리듬을 만든다",
         ["호흡: 짧고 끊김", "장치: 반복", "톤: 건조함"], "데모 산문"),
        ("그 여름의 물가에는 아무도 없었고, 나는 오래도록 바람이 지나간 자리를 바라보았다.", "길게 이어지는 회상이 느린 호흡과 여운을 만든다",
         ["호흡: 길고 느림", "장치: 열거", "톤: 서정적"], "데모 산문"),
    ]:
        store.put_category_item(user_id, CategoryItem(new_id(), styles, passage, "me", tags=tuple(tags), reason=reason, where=work,
                                                      tags_by="ai"))
