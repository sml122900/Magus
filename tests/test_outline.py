from __future__ import annotations

from magus.book.demo import seed_demo
from magus.book.outline import TOKEN_BUDGET, build_outline, estimate_tokens
from magus.store import LocalStore, Part


def _big_book(store: LocalStore) -> str:
    """완료 기준 규모: 35장 8부, 코멘트 이슈 86개, 결정 15개."""
    p = store.create_project("alice", "닿으려는 종", project_id="big")
    store.set_parts("alice", p.id, [Part(n, f"{n}부의 제목입니다") for n in range(1, 9)])
    for n in range(1, 36):
        store.write_chapter(
            "alice", p.id, n, "가" * 9700, "임포트", title=f"제{n}장의 꽤 긴 제목 — 부제까지 붙어 있는 경우", part_number=(n - 1) * 8 // 35 + 1
        )
    for n in range(15):
        store.add_decision("alice", p.id, f"결정 {n}: " + "문장은 짧게 끊고 각 장은 장면으로 연다. " * 3)
    for n in range(86):
        store.add_issue(
            "alice", p.id, f"확인 필요: 이 인용의 원문 쪽수와 연도를 대조할 것 ({n}) " * 3,
            origin="import_comment", chapter_number=n % 35 + 1,
        )
    return p.id


def test_outline_fits_budget_at_full_book_scale(store: LocalStore):
    project_id = _big_book(store)
    text = build_outline(store, "alice", project_id)
    assert estimate_tokens(text) <= TOKEN_BUDGET
    for n in range(1, 36):
        assert f"\n- {n}. " in text  # 목차는 자르지 않는다
    assert text.count("### 제") == 8
    assert "D15" in text and "D5 " not in text  # 최근 결정 10개 (D6~D15)
    assert "## 열린 미해결 (86)" in text and "외 " in text
    assert "## 최근 변경" in text


def test_outline_demo(store: LocalStore):
    project, created = seed_demo(store, "alice")
    assert created and not seed_demo(store, "alice")[1]
    text = build_outline(store, "alice")
    assert text.splitlines()[0] == "프로젝트: 데모: 물에서 뭍으로 (demo)"
    assert "프로젝트는" not in text  # 프로젝트가 하나면 안내 줄 없음
    assert "### 제1부 물가" in text and "### 제2부 뭍" in text
    assert "2장 v2" in text and "2장 끝에 한 문장 추가" in text
    assert "I1 · 1장 · 코멘트 · Daeschler 2006 원문 확인 필요" in text
    assert "D2" in text


def test_outline_without_project(store: LocalStore):
    assert "book_import" in build_outline(store, "alice")
    assert "없습니다" in build_outline(store, "alice", "nope")


def test_estimate_is_conservative_for_korean():
    assert estimate_tokens("가나다") == 3
    assert estimate_tokens("abcdef") == 2


def test_outline_mentions_other_projects(store: LocalStore):
    seed_demo(store, "alice")
    store.create_project("alice", "두 번째 책", project_id="book2")
    lines = build_outline(store, "alice").splitlines()
    assert lines[0] == "프로젝트: 두 번째 책 (book2)"  # 최근 갱신 프로젝트
    assert lines[1] == "이 사용자의 프로젝트는 2개다. 다른 프로젝트: 데모: 물에서 뭍으로(demo) (project_id로 지정)"
    assert build_outline(store, "alice", "demo").splitlines()[0] == "프로젝트: 데모: 물에서 뭍으로 (demo)"
