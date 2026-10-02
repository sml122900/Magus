"""저장소 인터페이스.

P0 구현은 LocalStore(사람이 읽는 파일이 원본, SQLite는 인덱스)이고, P1 구현은 Postgres + 객체 스토리지다.
모든 메서드가 user_id를 인자로 받는다. 저장소는 "현재 사용자"를 모른다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

IssueStatus = Literal["open", "closed"]
IssueOrigin = Literal["import_comment", "user", "agent"]
IssueKind = Literal["citation", "general"]
ChapterStatus = Literal["draft", "revising", "done"]
CHAPTER_STATUSES: tuple[str, ...] = ("draft", "revising", "done")


@dataclass(frozen=True)
class Project:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Part:
    number: int
    title: str


@dataclass(frozen=True)
class ChapterMeta:
    number: int
    title: str
    status: str
    part_number: int | None
    char_count: int
    unverified_cite_count: int
    version: int
    last_note: str
    updated_at: str


@dataclass(frozen=True)
class Chapter:
    meta: ChapterMeta
    content: str  # 본문만. front matter는 담지 않는다.


@dataclass(frozen=True)
class Decision:
    id: int
    text: str
    created_at: str


@dataclass(frozen=True)
class Issue:
    id: int
    text: str
    status: IssueStatus
    origin: IssueOrigin
    chapter_number: int | None
    created_at: str
    closed_note: str | None = None
    kind: IssueKind = "general"
    ref_key: str | None = None  # kind=citation일 때 코멘트에서 뽑은 저자+연도 후보. 4단계에서 refs와 연결한다.


@dataclass(frozen=True)
class Change:
    """장 하나의 한 버전. 현재 본문과 versions/의 이전본을 모두 포함한다."""

    chapter_number: int
    version: int
    note: str
    created_at: str


class Store(Protocol):
    # 프로젝트
    def create_project(self, user_id: str, title: str, project_id: str | None = None) -> Project: ...
    def get_project(self, user_id: str, project_id: str | None = None) -> Project | None:
        """project_id가 None이면 그 사용자의 가장 최근에 갱신된 프로젝트를 돌려준다."""
        ...
    def list_projects(self, user_id: str) -> list[Project]:
        """최근 갱신순."""
        ...
    def set_parts(self, user_id: str, project_id: str, parts: list[Part]) -> None: ...
    def list_parts(self, user_id: str, project_id: str) -> list[Part]: ...

    # 장
    def list_chapters(self, user_id: str, project_id: str) -> list[ChapterMeta]: ...
    def read_chapter(self, user_id: str, project_id: str, number: int) -> Chapter | None: ...
    def write_chapter(
        self,
        user_id: str,
        project_id: str,
        number: int,
        content: str,
        note: str,
        *,
        title: str | None = None,
        status: ChapterStatus | None = None,
        part_number: int | None = None,
    ) -> ChapterMeta:
        """이전 본문을 versions/에 보관한 뒤 새 본문을 쓴다. 없는 번호면 새 장을 만든다.
        content는 본문만이다. front matter가 붙어 오면 벗겨 내고, 메타는 인자로만 바꾼다.
        status는 CHAPTER_STATUSES 중 하나여야 하고, 빈 본문은 거부한다(ValueError)."""
        ...
    def recent_changes(self, user_id: str, project_id: str, limit: int = 5) -> list[Change]: ...

    # 결정·미해결
    def add_decision(self, user_id: str, project_id: str, text: str) -> Decision:
        """번호(D{n})는 프로젝트별 일련번호이고, 한 번 준 번호는 다시 쓰지 않는다. add_issue도 같다."""
        ...
    def list_decisions(self, user_id: str, project_id: str, limit: int | None = None) -> list[Decision]:
        """최신순."""
        ...
    def add_issue(
        self,
        user_id: str,
        project_id: str,
        text: str,
        origin: IssueOrigin = "user",
        chapter_number: int | None = None,
        *,
        kind: IssueKind = "general",
        ref_key: str | None = None,
    ) -> Issue: ...
    def list_issues(
        self,
        user_id: str,
        project_id: str,
        status: IssueStatus | None = "open",
        *,
        chapter_number: int | None = None,
        origin: IssueOrigin | None = None,
        kind: IssueKind | None = None,
    ) -> list[Issue]:
        """번호순. status=None이면 전체."""
        ...

    # 인덱스
    def reindex(self) -> None:
        """원본 파일에서 인덱스 전체를 다시 만든다."""
        ...
