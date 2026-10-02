from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from magus.store import LocalStore, Part


def _snapshot(store: LocalStore, user_id: str, project_id: str):
    return (
        store.get_project(user_id, project_id),
        store.list_parts(user_id, project_id),
        store.list_chapters(user_id, project_id),
        store.list_decisions(user_id, project_id),
        store.list_issues(user_id, project_id, None),
        store.recent_changes(user_id, project_id, 50),
    )


@pytest.fixture
def project(store: LocalStore):
    p = store.create_project("alice", "테스트 책", project_id="book1")
    store.set_parts("alice", p.id, [Part(1, "기원")])
    store.write_chapter("alice", p.id, 1, "첫 본문", "초안", title="첫 장", part_number=1)
    store.write_chapter("alice", p.id, 1, "고친 본문\n\n둘째 문단", "둘째 문단 추가")
    store.add_decision("alice", p.id, "장마다 장면으로 연다.")
    store.add_issue("alice", p.id, "여러 줄\n코멘트", origin="import_comment", chapter_number=1)
    store.add_issue("alice", p.id, "전체 이슈")
    return p


def test_files_are_the_source(store: LocalStore, project, data_dir: Path):
    pdir = data_dir / "users" / "alice" / "projects" / "book1"
    current = (pdir / "book" / "ch-01.md").read_text(encoding="utf-8")
    assert "version: 2" in current and "고친 본문" in current and "title: 첫 장" in current
    assert "part_number: 1" in current and "last_note: 둘째 문단 추가" in current
    archived = (pdir / "versions" / "ch-01.v1.md").read_text(encoding="utf-8")
    assert "첫 본문" in archived and "last_note: 초안" in archived
    assert "## D1 · " in (pdir / "decisions.md").read_text(encoding="utf-8")
    issues_md = (pdir / "issues.md").read_text(encoding="utf-8")
    assert "## I1 · open" in issues_md and "- origin: import_comment" in issues_md and "- chapter: 1" in issues_md


def test_write_keeps_meta_and_versions(store: LocalStore, project):
    [ch] = store.list_chapters("alice", project.id)
    assert (ch.number, ch.title, ch.part_number, ch.version, ch.last_note) == (1, "첫 장", 1, 2, "둘째 문단 추가")
    assert ch.char_count == len("고친 본문\n\n둘째 문단")
    changes = store.recent_changes("alice", project.id)
    assert [(c.chapter_number, c.version, c.note) for c in changes] == [(1, 2, "둘째 문단 추가"), (1, 1, "초안")]


def test_caller_front_matter_is_ignored(store: LocalStore, project, data_dir: Path):
    meta = store.write_chapter("alice", project.id, 1, "---\ntitle: 바꿔치기\nversion: 99\n---\n\n본문만", "메타 주입 시도")
    assert (meta.title, meta.version) == ("첫 장", 3)
    text = (data_dir / "users/alice/projects/book1/book/ch-01.md").read_text(encoding="utf-8")
    assert text.count("---") == 2 and "바꿔치기" not in text and text.endswith("본문만\n")


def test_issue_text_roundtrips_multiline(store: LocalStore, project):
    issues = store.list_issues("alice", project.id)
    assert [(i.id, i.text, i.chapter_number, i.origin) for i in issues] == [
        (1, "여러 줄\n코멘트", 1, "import_comment"),
        (2, "전체 이슈", None, "user"),
    ]


def test_reindex_rebuilds_same_index(store: LocalStore, project):
    before = _snapshot(store, "alice", project.id)
    store.reindex()
    assert _snapshot(store, "alice", project.id) == before


def test_index_recreated_when_schema_version_changes(store: LocalStore, project, data_dir: Path):
    before = _snapshot(store, "alice", project.id)
    store.close()
    db = sqlite3.connect(data_dir / "index.sqlite")
    db.execute("DELETE FROM chapters")
    db.execute("PRAGMA user_version = 0")
    db.commit()
    db.close()
    reopened = LocalStore(data_dir)
    assert _snapshot(reopened, "alice", project.id) == before
    reopened.close()


def test_other_user_sees_nothing(store: LocalStore, project):
    assert store.get_project("bob") is None
    assert store.get_project("bob", project.id) is None
    assert store.list_chapters("bob", project.id) == []
    assert store.list_decisions("bob", project.id) == []
    assert store.list_issues("bob", project.id, None) == []
    assert store.recent_changes("bob", project.id) == []
    with pytest.raises(ValueError):
        store.write_chapter("bob", project.id, 1, "x", "침입")


def test_default_project_is_most_recently_updated(store: LocalStore, project):
    other = store.create_project("alice", "두 번째 책", project_id="book2")
    assert store.get_project("alice").id == other.id
    store.write_chapter("alice", project.id, 2, "본문", "새 장")
    assert store.get_project("alice").id == project.id


def test_rejects_unsafe_project_id(store: LocalStore):
    with pytest.raises(ValueError):
        store.create_project("alice", "x", project_id="../evil")


def test_read_chapter_returns_body_only(store: LocalStore, project):
    chapter = store.read_chapter("alice", project.id, 1)
    assert chapter.content == "고친 본문\n\n둘째 문단"
    assert chapter.meta.version == 2
    assert store.read_chapter("alice", project.id, 9) is None
    assert store.read_chapter("bob", project.id, 1) is None


def test_numbers_are_never_reused(store: LocalStore, project, data_dir: Path):
    pdir = data_dir / "users/alice/projects/book1"
    store.add_issue("alice", project.id, "지울 이슈")  # I3
    issues_md = pdir / "issues.md"
    text = issues_md.read_text(encoding="utf-8")
    issues_md.write_text(text[: text.index("## I3")], encoding="utf-8")  # 사람이 마지막 항목을 지움
    assert store.add_issue("alice", project.id, "새 이슈").id == 4
    store.add_decision("alice", project.id, "지울 결정")  # D2
    decisions_md = pdir / "decisions.md"
    text = decisions_md.read_text(encoding="utf-8")
    decisions_md.write_text(text[: text.index("## D2")], encoding="utf-8")
    assert store.add_decision("alice", project.id, "새 결정").id == 3
    store.reindex()
    assert [i.id for i in store.list_issues("alice", project.id, None)] == [1, 2, 4]


def test_list_projects_recent_first(store: LocalStore, project):
    store.create_project("alice", "두 번째 책", project_id="book2")
    assert [p.id for p in store.list_projects("alice")] == ["book2", "book1"]
    assert store.list_projects("bob") == []
