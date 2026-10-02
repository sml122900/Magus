"""저장소 인터페이스.

P0 구현은 LocalStore(사람이 읽는 파일이 원본, SQLite는 인덱스)이고, P1 구현은 Postgres + 객체 스토리지다.
모든 메서드가 user_id를 인자로 받는다. 저장소는 "현재 사용자"를 모른다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

IssueStatus = Literal["open", "closed"]
IssueOrigin = Literal["import_comment", "user", "agent"]
IssueKind = Literal["citation", "general"]
ChapterStatus = Literal["draft", "revising", "done"]
CHAPTER_STATUSES: tuple[str, ...] = ("draft", "revising", "done")
RefStatus = Literal["unverified", "verified"]
Lane = Literal["ref_picked", "ref_full", "idea_me", "idea_ai", "style"]


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
class Passage:
    """사용자가 직접 골라 둔 발췌. reason은 왜 골랐는지."""

    text: str
    reason: str
    locator: str | None = None


@dataclass(frozen=True)
class Ref:
    """Melchior의 문헌 한 건. key = 첫 저자 성(소문자 영문) + 연도. 한글 표기 key는 aliases에 둔다."""

    key: str
    status: RefStatus
    bib: dict[str, Any] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    has_fulltext: bool = False
    file_path: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class Chunk:
    """검색 단위. owner_type/owner_id로 원본(ref·idea·style)을 가리킨다."""

    id: int
    owner_type: str
    owner_id: str
    lane: Lane
    text: str
    score: float = 0.0


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
    def archive_project(self, user_id: str, project_id: str) -> str:
        """프로젝트를 지우지 않고 휴지통(users/<id>/trash/)으로 옮기고 인덱스에서 뺀다. 옮긴 위치를 돌려준다."""
        ...
    def save_original(self, user_id: str, project_id: str, filename: str, data: bytes) -> str:
        """original/<filename>에 저장하고 데이터 루트 기준 상대 경로를 돌려준다(원본 사본·임포트 리포트용)."""
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

    # 문헌 (Melchior) — 사람 소유. 프로젝트와 무관하다.
    def get_ref(self, user_id: str, key: str) -> Ref | None: ...
    def resolve_ref(self, user_id: str, key: str) -> Ref | None:
        """key로 찾고, 없으면 aliases에서 찾는다."""
        ...
    def list_refs(self, user_id: str, status: RefStatus | None = None) -> list[Ref]: ...
    def get_passages(self, user_id: str, key: str) -> list[Passage]: ...
    def put_ref(
        self, user_id: str, ref: Ref, passages: list[Passage] | None = None, full_text: str | None = None
    ) -> Ref:
        """bib.json을 쓰고 인덱스·청크를 갱신한다. passages/full_text가 None이면 기존 것을 그대로 둔다."""
        ...

    # 검색 청크 (모든 책장 공용)
    def search_fts(self, user_id: str, lanes: list[Lane], match: str, limit: int) -> list[Chunk]: ...
    def search_vector(self, user_id: str, lanes: list[Lane], vector: list[float], limit: int) -> list[Chunk]: ...
    def chunks_missing_embedding(self, user_id: str, limit: int = 256) -> list[Chunk]: ...
    def set_embeddings(self, user_id: str, vectors: dict[int, list[float]]) -> None: ...

    # 인덱스
    def reindex(self) -> None:
        """원본 파일에서 인덱스 전체를 다시 만든다."""
        ...
