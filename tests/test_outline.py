from __future__ import annotations

from magus.book.demo import seed_demo
from magus.book.outline import TOKEN_BUDGET, build_outline, estimate_tokens
from magus.store import LocalStore, Part

USER_ISSUES = 12
AGENT_ISSUES = 4


def _big_book(store: LocalStore) -> str:
    """완료 기준 규모: 35장 8부, 코멘트 유래 미해결 86건, 결정 15건. 여기에 직접 남긴 미해결 16건을 더한다."""
    p = store.create_project("alice", "닿으려는 종", project_id="big")
    store.set_parts("alice", p.id, [Part(n, f"{n}부의 제목입니다") for n in range(1, 9)])
    for n in range(1, 36):
        store.write_chapter(
            "alice", p.id, n, "가" * 9700, "임포트",
            title=f"제{n}장의 꽤 긴 제목 — 부제까지 붙어 있는 경우", part_number=(n - 1) * 8 // 35 + 1,
        )
    for n in range(15):
        store.add_decision("alice", p.id, f"결정 {n}: " + "문장은 짧게 끊고 각 장은 장면으로 연다. " * 3)
    for n in range(86):
        store.add_issue(
            "alice", p.id, f"확인 필요: 이 인용의 원문 쪽수와 연도를 대조할 것 ({n}) " * 3,
            origin="import_comment", chapter_number=n % 35 + 1, kind="citation",
        )
    for n in range(USER_ISSUES):
        store.add_issue(
            "alice", p.id, f"사용자 미해결 {n}: 이 장의 논지가 앞 장과 겹치는지 다시 읽고 판단해야 한다. " * 2,
            chapter_number=n + 1,
        )
    for n in range(AGENT_ISSUES):
        store.add_issue(
            "alice", p.id, f"에이전트 미해결 {n}: 4부와 5부 사이 연결 문단이 비어 있어 초안이 필요하다. " * 2,
            origin="agent",
        )
    return p.id


def test_outline_fits_budget_and_lists_every_direct_issue(store: LocalStore):
    project_id = _big_book(store)
    text = build_outline(store, "alice", project_id)
    assert estimate_tokens(text) <= TOKEN_BUDGET
    # 목차: 35장 모두, 집계만 담은 줄. 장별 미해결 수에는 코멘트 유래도 들어간다(1장: 코멘트 3 + 사용자 1).
    first = next(line for line in text.splitlines() if line.startswith("- 제1장 "))
    assert first.endswith("… · 초안 · 9,700자 · 확인 요청 4 · 미확인인용 0")  # 제목은 24자로 자른다
    for n in range(1, 36):
        assert f"\n- 제{n}장 " in text
    assert text.count("### 제") == 8
    # 직접 남긴 미해결은 전부, 코멘트 유래는 건수 한 줄만.
    for n in range(USER_ISSUES):
        assert f"사용자 미해결 {n}:" in text
    for n in range(AGENT_ISSUES):
        assert f"에이전트 미해결 {n}:" in text
    assert "- 코멘트 유래 확인 요청 86건(citation " in text
    assert "원문 쪽수와 연도를 대조할 것" not in text
    assert "외 " not in text.split("## 열린 확인 요청")[1].split("## 최근 변경")[0]
    # 남는 예산은 결정과 변경에 간다. 가장 최근 것은 반드시 실린다.
    assert "- D15 " in text and "- 35장 v1 " in text


def test_outline_demo(store: LocalStore):
    project, created = seed_demo(store, "alice")
    assert created and not seed_demo(store, "alice")[1]
    text = build_outline(store, "alice")
    assert text.splitlines()[0] == "프로젝트: 데모: 물에서 뭍으로 (demo)"
    assert "프로젝트는" not in text  # 프로젝트가 하나면 안내 줄 없음
    assert "### 제1부 물가" in text and "### 제2부 뭍" in text
    assert "- 제1장 물가의 망설임 · 초안 · 68자 · 확인 요청 1 · 미확인인용 0" in text
    assert "2장 v2" in text and "2장 끝에 한 문장 추가" in text
    assert "- 코멘트 유래 확인 요청 1건(citation 1) — book_issues(kind)로 조회" in text
    assert "Daeschler 2006 원문 확인 필요" not in text
    assert "I2 · 3장 · 3장 폐의 기원 출처 찾기" in text and "I3 · 2부 제목 후보 더 생각하기" in text
    assert "D2" in text


def test_outline_without_project(store: LocalStore):
    assert "'+ 프로젝트'로 먼저 만들어 주세요" in build_outline(store, "alice")  # 새 사용자는 프로젝트 0개(2026-10-11)
    assert "없습니다" in build_outline(store, "alice", "nope")
    store.create_project("alice", "제목만", project_id="t")
    assert build_outline(store, "alice", "t").startswith("프로젝트: 제목만 (t)")


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


def test_outline_names_special_chapters_and_comment_kinds(store: LocalStore):
    # 실원고: 최근 변경에 '93장 v1'이 아니라 '부록 3 v1'으로 나와야 한다. 코멘트 유래는 kind별로 센다.
    p = store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", p.id, 1, "본문", "x")
    store.write_chapter("alice", p.id, 93, "부록 본문", "임포트", label="부록 3")
    for kind in ("citation", "fact", "fact"):
        store.add_issue("alice", p.id, "확인 필요", origin="import_comment", chapter_number=93, kind=kind)
    text = build_outline(store, "alice", p.id)
    assert "- 부록 3 v1 " in text and "- 93장 v1" not in text
    assert "- 코멘트 유래 확인 요청 3건(citation 1 · fact 2) — book_issues(kind)로 조회" in text


def test_outline_header_counts_unique_docs_across_book(store: LocalStore):
    # 머리줄은 책 전체 고유 미확인 문헌 수다(장별 합이 아님). 저자 보고서 1절의 문헌 수와 같아야 한다.
    from magus.melchior.bibliography import import_bibliography
    from magus.melchior.check import refresh_cite_counts
    from magus.melchior.report import build_cite_report

    p = store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", p.id, 0, "(Clack, 2012) 서장", "x", label="서장")
    store.write_chapter("alice", p.id, 1, "Clack(2012)와 (Hu et al., 2023)", "x")
    store.write_chapter("alice", p.id, 2, "Clack(2012) 다시, 그리고 Nobody(2001).", "x")
    for n in (91, 92, 93):
        store.write_chapter("alice", p.id, n, "부록", "x", label=f"부록 {n - 90}")
    store.write_chapter("alice", p.id, 90, "맺음", "x", label="맺음")
    import_bibliography(store, "alice", "Clack, J. A. (2012). Gaining ground. Press.\nHu, W. et al. (2023). Bottleneck. Science.")
    refresh_cite_counts(store, "alice")
    text = build_outline(store, "alice", p.id)
    header = text.splitlines()[1]
    assert header.startswith("2장 + 서장·맺음·부록 1~3 · 0부 · ")
    assert "미확인 문헌 3편" in header  # clack2012(세 장) · hu2023 · nobody2001. 장별 합이면 5
    report = build_cite_report(store, "alice", p.id)
    assert len(report.of("unverified", "unknown")) == 3


def test_outline_shows_unlinked_hangul_names(store: LocalStore):
    # 미연결(한글 표기인데 refs와 못 이음)은 미확인 수에서 빼지만 머리줄에 따로 보인다(사용자 결정 #29)
    from magus.melchior.check import check_chapter

    p = store.create_project("alice", "책", project_id="b")
    store.write_chapter("alice", p.id, 1, "아무개(2001)와 누군가(2002), Clack(2012)", "x")
    result = check_chapter(store, "alice", p.id, 1)
    assert result.as_dict()["unique_uncertain"] == 2 and len(result.as_dict()["uncertain"]) == 2
    header = build_outline(store, "alice", p.id).splitlines()[1]
    assert "미확인 문헌 1편 · 미연결 2 · " in header
