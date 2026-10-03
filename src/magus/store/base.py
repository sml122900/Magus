"""저장소 인터페이스.

P0 구현은 LocalStore(사람이 읽는 파일이 원본, SQLite는 인덱스)이고, P1 구현은 Postgres + 객체 스토리지다.
모든 메서드가 user_id를 인자로 받는다. 저장소는 "현재 사용자"를 모른다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple, Protocol

IssueStatus = Literal["open", "closed"]
IssueOrigin = Literal["import_comment", "user", "agent"]
# citation: 출처 확인 코멘트 + 문헌이 지목됨 / fact: 출처 확인 코멘트지만 문헌 없음(사실·수치 확인) / general: 그 외
IssueKind = Literal["citation", "fact", "general"]
ISSUE_KINDS: tuple[str, ...] = ("citation", "fact", "general")
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


class CiteKeys(NamedTuple):
    """장 하나의 인용 집계 파생값: 미확인 문헌 key(unverified + unknown)와 미연결 한글 표기 key(uncertain)."""

    unverified: list[str]
    uncertain: list[str]


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
    label: str | None = None  # 번호 없는 장의 표시 이름(서장·맺음·부록 N). 없으면 "제N장"
    unverified_cite_keys: tuple[str, ...] = ()  # 파생값. 장 사이 합집합이 책 전체 고유 미확인 문헌이다
    uncertain_cite_keys: tuple[str, ...] = ()  # 파생값. 한글 표기인데 refs와 잇지 못한 것(미확인 수에는 넣지 않음)

    @property
    def display(self) -> str:
        return self.label or f"제{self.number}장"


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
    ref_key: str | None = None  # kind=citation일 때 코멘트에서 뽑은 저자+연도 후보(조사 뗀 한글 key일 수도 있다)
    ref_id: str | None = None  # ref_key가 refs에서 해석된 정식 key. refs 행 id는 재생성되므로 key를 식별자로 쓴다.


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


IdeaKind = Literal["thought", "ai", "article", "conversation", "tv", "other"]
Author = Literal["me", "ai"]


@dataclass(frozen=True)
class Idea:
    """Casper의 생각 한 조각. author=me가 사용자의 말, ai가 AI의 말이다."""

    id: str
    text: str
    kind: IdeaKind
    author: Author
    origin: str | None = None
    parent_id: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class StyleEntry:
    """Balthasar의 문체 표본. passage는 원문 구절, reason은 왜 좋은지, tags는 {호흡, 시점, 열기, 장치, 어미, 톤}."""

    id: str
    passage: str
    reason: str
    tags: dict[str, Any] = field(default_factory=dict)
    work: str | None = None
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
    def list_users(self) -> list[str]:
        """운영용(재생성 뒤 파생값 재계산). 도구에서는 쓰지 않는다."""
        ...

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
    def get_non_citation_terms(self, user_id: str, project_id: str) -> list[str]:
        """인용 추출에서 뺄 낱말(지명·사건 등). 프로젝트의 book/non_citation_terms.txt, 한 줄에 하나."""
        ...
    def set_non_citation_terms(self, user_id: str, project_id: str, terms: list[str]) -> None: ...
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
        label: str | None = None,
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
    def close_issue(self, user_id: str, project_id: str, issue_id: int, note: str | None = None) -> Issue | None:
        """없는 번호면 None. 이미 닫힌 이슈는 note만 갱신한다."""
        ...
    def set_issue_refs(self, user_id: str, project_id: str, ref_ids: dict[int, str | None]) -> None:
        """citation 이슈의 ref_id를 한 번에 기록한다(issues.md를 한 번만 다시 쓴다)."""
        ...
    def set_cite_keys(self, user_id: str, project_id: str, cites: dict[int, CiteKeys]) -> None:
        """장별 미확인 문헌 key(수는 그 길이)와 미연결 key. 본문과 refs로 계산되는 파생값이라 인덱스에만 둔다."""
        ...
    def save_export(self, user_id: str, project_id: str, filename: str, data: bytes) -> str:
        """exports/<filename>에 저장하고 위치를 돌려준다(P0: 절대 경로, P1: 내려받기 URL)."""
        ...
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

    # 영감 (Casper) — 사람 소유
    def add_ideas(self, user_id: str, ideas: list[Idea]) -> list[Idea]:
        """한 번에 여러 개를 쓴다(대화 기록 한 편). 각자 shelf/casper/<id>.json이 된다."""
        ...
    def get_ideas(self, user_id: str, ids: list[str]) -> dict[str, Idea]: ...
    def list_ideas(self, user_id: str, author: Author | None = None) -> list[Idea]: ...

    # 문체 (Balthasar) — 사람 소유
    def add_style(self, user_id: str, entry: StyleEntry) -> StyleEntry:
        """reason + tags만 색인·임베딩한다(balthasar.style.search_text). passage는 색인하지 않는다."""
        ...
    def get_styles(self, user_id: str, ids: list[str]) -> dict[str, StyleEntry]: ...
    def list_styles(self, user_id: str) -> list[StyleEntry]: ...

    # 검색 청크 (모든 책장 공용)
    def search_fts(self, user_id: str, lanes: list[Lane], match: str, limit: int) -> list[Chunk]: ...
    def search_vector(self, user_id: str, lanes: list[Lane], vector: list[float], limit: int) -> list[Chunk]: ...
    def chunks_missing_embedding(self, user_id: str, limit: int = 256) -> list[Chunk]: ...
    def set_embeddings(self, user_id: str, vectors: dict[int, list[float]]) -> None: ...

    # 인덱스
    def reindex(self) -> None:
        """원본 파일에서 인덱스 전체를 다시 만든다."""
        ...
