"""1단계 확인용 가짜 프로젝트. 실제 원고(fixtures)는 2단계 book_import로 들어온다."""

from __future__ import annotations

from magus.store import Part, Project, Store

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
        store.write_chapter(user_id, project.id, number, body, "데모 초안", title=title, part=part)
    store.write_chapter(
        user_id, project.id, 2, _CHAPTERS[1][3] + "\n\n목은 머리를 돌리는 자유였다.", "2장 끝에 한 문장 추가"
    )
    store.add_decision(user_id, project.id, "각 장은 하나의 생물 장면으로 연다.")
    store.add_decision(user_id, project.id, "학명은 처음 나올 때만 괄호 병기.")
    store.add_issue(user_id, project.id, "Daeschler 2006 원문 확인 필요", origin="import_comment", chapter_number=1)
    store.add_issue(user_id, project.id, "3장 폐의 기원 출처 찾기", chapter_number=3)
    store.add_issue(user_id, project.id, "2부 제목 후보 더 생각하기")
    return store.get_project(user_id, project.id) or project, True
