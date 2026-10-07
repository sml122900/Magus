"""저장소 인터페이스.

P0 구현은 LocalStore(사람이 읽는 파일이 원본, SQLite는 인덱스)이고, P1 구현은 Postgres + 객체 스토리지다.
모든 메서드가 user_id를 인자로 받는다. 저장소는 "현재 사용자"를 모른다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol

IssueStatus = Literal["open", "closed"]
IssueOrigin = Literal["import_comment", "user", "agent"]
# citation: 출처 확인 코멘트 + 문헌이 지목됨 / fact: 출처 확인 코멘트지만 문헌 없음(사실·수치 확인) / general: 그 외
IssueKind = Literal["citation", "fact", "general"]
ISSUE_KINDS: tuple[str, ...] = ("citation", "fact", "general")
AuthorKind = Literal["ai", "person"]  # 원고 코멘트 작성자: AI인가 사람인가(#71)
ANCHOR_MAX = 1000  # 미해결에 남기는 걸린 문장의 최대 길이(#73)
IssueStale = Literal["comment_removed", "anchor_missing"]  # 다시 올린 뒤 "해결됐을 수 있음"(#76)
ChapterStatus = Literal["draft", "revising", "done"]
CHAPTER_STATUSES: tuple[str, ...] = ("draft", "revising", "done")
RefStatus = Literal["unverified", "verified"]
# style_passage·ref_bib는 웹 책장 검색 전용이다(문체 구절·문헌 서지). 도구 검색(style_search·ref_search)은 쓰지 않고 임베딩도 하지 않는다.
# category는 저자가 만든 카테고리의 항목(#92). owner_id는 "<카테고리 id>/<항목 id>"다.
# document는 문서 책의 지금 판 내용(#94). 웹 책장 검색 전용이다.
Lane = Literal["ref_picked", "ref_full", "idea_me", "idea_ai", "style", "style_passage", "ref_bib", "category", "document"]
WEB_ONLY_LANES: tuple[str, ...] = ("style_passage", "ref_bib", "document")
TagsBy = Literal["ai", "author"]  # 문체 태그를 누가 정했나: Claude가 뽑음(ai) / 저자가 말함(author). 기록 전 항목은 None
# 휴지통에 옮길 수 있는 책장 항목(#88). 카테고리는 통째(category, id = 카테고리 id)와 항목(category_item, id = "<카테고리 id>/<항목 id>")
TrashKind = Literal["idea", "style", "category", "category_item"]
TitleBy = Literal["ai", "author"]  # 항목 제목을 누가 지었나(#92). 태그의 tags_by와 같은 방식
TitleMode = Literal["ask", "ai", "none"]
EditedBy = Literal["author", "ai"]  # 항목을 나중에 고친 사람(웹에서 저자가 고치면 author). 처음 쓴 사람(author 필드)은 그대로 둔다  # 저자가 제목을 말하지 않았을 때: 매번 묻기 / AI가 짓기 / 비워 두기


@dataclass(frozen=True)
class Project:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str
    subtitle: str | None = None  # 책 제목과 부제를 따로 둔다(#77). 영문 제목·부제도 있으면 둔다
    title_en: str | None = None
    subtitle_en: str | None = None
    color: str | None = None  # 원고 책의 책 색(#94). 없으면 원고 책 기본 색


@dataclass(frozen=True)
class BookTitles:
    """원고에서 읽은 책 제목들(#77). 없으면 None."""

    title: str | None = None
    subtitle: str | None = None
    title_en: str | None = None
    subtitle_en: str | None = None


@dataclass(frozen=True)
class Part:
    number: int
    title: str


@dataclass(frozen=True)
class InboxFile:
    """받은함 파일. modified는 UTC ISO 8601."""

    name: str
    size: int
    modified: str


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
    # 본문이 어느 업로드 판(E1, E2…)과 같은가(#76). Magus에서 book_write_chapter로 고치면 비워진다(= Magus에서 고친 본문).
    edition: int | None = None

    @property
    def display(self) -> str:
        return self.label or f"제{self.number}장"


PART_INTRO_BASE = 100  # "제N부 들어가며"의 장 번호는 100 + N(#70). 서장 0, 본문 1~89, 맺음 90, 부록 N은 90+N


class _Numbered(Protocol):
    number: int
    part_number: int | None


def reading_order[T: _Numbered](chapters: Iterable[T]) -> list[T]:
    """책을 읽는 순서. 번호순이되, 부 들어가며(100+N)는 그 부의 첫 장 바로 앞에 둔다."""
    chapters = list(chapters)
    first: dict[int, int] = {}
    for c in chapters:
        if c.number < PART_INTRO_BASE and c.part_number is not None:
            first[c.part_number] = min(first.get(c.part_number, c.number), c.number)

    def key(c: T) -> tuple[int, int]:
        if c.number > PART_INTRO_BASE and c.part_number is not None:
            return (first.get(c.part_number, c.number), 0)
        return (c.number, 1)

    return sorted(chapters, key=key)


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
    # 원고 코멘트에서 온 미해결의 작성자(#71). 누가 말했는지 보존한다: AI가 단 코멘트는 저자에게도 "AI 확인 요청"으로 보인다.
    author: str | None = None  # Word의 작성자 이름 그대로. PDF·직접 남긴 미해결은 None
    author_kind: AuthorKind | None = None  # ai | person. 작성자 이름으로 판정해 파일에 적는다(사람이 고칠 수 있다)
    comment_date: str | None = None  # Word 코멘트의 작성 시각(w:date)
    # 코멘트가 걸린 문장 전문(한 줄로, ANCHOR_MAX자까지)과 그 장 본문의 문단 번호(ref_check의 paragraphs와 같은 번호, #73).
    # 본문의 "— 원문: “…”"은 표시용 120자다. 다시 올리기에서 걸린 문장이 남아 있는지 이것으로 본다.
    anchor: str | None = None
    paragraph: int | None = None
    # 다시 올리기(#76): 같은 코멘트를 두 번 넣지 않으려는 지문(작성자 + 날짜 + 본문)과 "해결됐을 수 있음" 표시.
    comment_fp: str | None = None
    stale: IssueStale | None = None  # 자동으로 닫지 않는다. 표시만 하고 닫는 것은 저자다
    stale_edition: int | None = None  # 몇 판에서 그렇게 됐나

    @property
    def by_ai(self) -> bool:
        return self.author_kind == "ai"


STALE_REASONS: dict[str, str] = {
    "comment_removed": "원고에서 코멘트가 지워짐",
    "anchor_missing": "걸린 문장이 원고에 없음",
}


@dataclass(frozen=True)
class Edition:
    """원고 업로드 한 번 = 판 하나(E1, E2…). project.json의 editions에 쌓인다(#76)."""

    number: int
    file: str  # 올린 원고 파일 이름. 사본은 original/에 있다
    uploaded_at: str
    sha256: str = ""
    changed: int = 0  # 본문이 바뀐 장(새 장 포함)
    added: int = 0
    removed: int = 0
    unchanged: int = 0
    legacy: bool = False  # 판 기록이 생기기 전에 임포트한 것을 E1로 본 기록


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
    floor: str | None = None  # 꽂힌 층(공용 "common" 또는 프로젝트 id, #93). None이면 저장소가 정한다
    updated_at: str = ""  # 마지막으로 고친 시각(층의 최근 수정에 쓴다). 기록 전 문헌은 created_at
    # 두 작업물이 함께 쓰게 되어 공용으로 옮겨졌을 때의 기록(#93-a 더함): {"at", "from", "to", "reason"}. 저자 모르게 배치가 바뀌지 않게
    moved: dict[str, str] | None = None


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
    title: str | None = None  # 선택 제목(#92). 없으면 목록에 내용 앞부분이 흐리게 보인다
    title_by: TitleBy | None = None
    edited_at: str | None = None  # 처음 쓴 뒤 고친 시각과 고친 사람(웹에서 저자가 고침). 고친 적이 없으면 None
    edited_by: EditedBy | None = None
    floor: str | None = None  # 꽂힌 층(#93). None이면 저장소가 정한다


@dataclass(frozen=True)
class StyleEntry:
    """Balthasar의 문체 표본. passage는 원문 구절, reason은 왜 좋은지, tags는 {호흡, 시점, 열기, 장치, 어미, 톤}."""

    id: str
    passage: str
    reason: str
    tags: dict[str, Any] = field(default_factory=dict)
    work: str | None = None
    created_at: str = ""
    tags_by: TagsBy | None = None  # 태그를 누가 정했나(#89). 웹 /styles에 보인다
    floor: str | None = None  # 꽂힌 층(#93). None이면 저장소가 정한다


@dataclass(frozen=True)
class Category:
    """저자가 만든 카테고리(#92). 칸 정의(fields)는 만들 때 템플릿에서 복사해 둔다(템플릿이 바뀌어도 그대로)."""

    id: str
    name: str
    template: str  # magus.category.rules.TEMPLATES의 key
    color: str  # #rrggbb
    fields: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    items: int = 0  # 항목 수(목록에서 채운다)
    floor: str = "common"  # 꽂힌 층(#93): 공용 "common" 또는 프로젝트 id


@dataclass(frozen=True)
class CategoryItem:
    """카테고리 항목 하나. author: 누가 말했나(me = 저자의 말, ai = Claude가 쓴 글). chapters: [(project_id, 장 번호)]."""

    id: str
    category_id: str
    content: str
    author: Author
    title: str | None = None
    title_by: TitleBy | None = None
    fields: dict[str, str] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    chapters: tuple[tuple[str, int], ...] = ()
    created_at: str = ""
    updated_at: str = ""
    edited_at: str | None = None  # 고친 시각과 고친 사람. AI가 쓴 항목을 저자가 고치면 author는 ai 그대로, edited_by는 author
    edited_by: EditedBy | None = None


@dataclass(frozen=True)
class ShelfSettings:
    """사용자의 책장 설정(shelf/settings.json): 기본 카테고리의 책 색, 내 색(최대 12), 제목 기본값."""

    colors: dict[str, str] = field(default_factory=dict)  # ideas|styles|refs → #rrggbb
    my_colors: tuple[str, ...] = ()
    title_default: TitleMode = "ask"


@dataclass(frozen=True)
class DocVersion:
    """문서 책의 한 판(#94). edition: 기준 원고의 수정본 번호(기록 없으면 None). method: server(사실 부분을 서버가 만듦) |
    server+preface(머리말을 더함). preface_by: 머리말을 누가 썼나(ai | author). stats: 다음 판과 견줄 수치(미확인 문헌 수 등)."""

    number: int
    at: str
    edition: int | None
    method: str = "server"
    preface_by: str | None = None
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Document:
    """문서 책(#94): 원고에서 만든 읽기용 문서. 그 시점의 사진이고, 다시 만들면 판이 하나 늘어난다."""

    id: str
    title: str
    title_by: TitleBy | None
    doc_type: str  # source_check(출처 확인 문서)
    floor: str
    project_id: str  # 기준 원고 책
    color: str
    created_at: str = ""
    updated_at: str = ""
    versions: tuple[DocVersion, ...] = ()


@dataclass(frozen=True)
class Floor:
    """책장의 한 층(#93). 공용(id "common", number 0) 또는 작업물(프로젝트) 하나. 번호는 위에서 아래로 1층, 2층…"""

    id: str
    number: int
    title: str
    builtins: tuple[str, ...] = ()  # 이 층에 꽂힌 기본 카테고리(ideas|styles|refs)
    has_manuscript: bool = False  # 장이 하나라도 있나(빈 층이면 False)
    updated_at: str = ""  # 최근 수정: 그 층 원고·카테고리·항목·옮기기 중 가장 최근

    @property
    def common(self) -> bool:
        return self.number == 0

    @property
    def label(self) -> str:
        return "공용" if self.number == 0 else f"{self.number}층"


@dataclass(frozen=True)
class FloorMove:
    """카테고리 옮기기 한 번(#93). 마지막 옮기기만 floors.json에 남아 한 번 되돌릴 수 있다.
    book: 저자의 카테고리 id 또는 기본 카테고리 종류(ideas|styles|refs). items: 기본 카테고리를 옮겼을 때 함께 간 항목 id(문헌은 key).
    merged: 받는 층에 같은 기본 카테고리가 있어 합쳤나. kept: 되돌릴 때 받은 층의 기본 카테고리를 남겨 둬야 하나(합쳤으면 True)."""

    id: str
    at: str
    book: str
    name: str
    from_floor: str
    to_floor: str
    merged: bool = False
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    """사용자 프로필(users/<id>/profile.json). 상단 바 이름 = 표시 이름, 없으면 메일, 없으면 내부 이름(user id).
    메일은 웹 로그인 때 인증 서버의 userinfo에서 받는다(저자가 바꾸지 않는다). 로그에는 남기지 않는다(#52)."""

    email: str | None = None
    display_name: str | None = None
    email_at: str | None = None  # 메일을 받아 적은 시각
    name_at: str | None = None  # 표시 이름을 바꾼 시각


@dataclass(frozen=True)
class TrashItem:
    """휴지통의 생각·문체 하나(trash/shelf/<casper|balthasar>/<id>.json). 지우지 않고 옮겨 둔 것이라 되살릴 수 있다(#88)."""

    kind: TrashKind
    id: str
    trashed_at: str
    note: str
    preview: str
    with_id: str | None = None  # 함께 옮겨진 AI 발화면 그 발화가 응답한 생각의 id


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

    # 받은함 — 사람 소유. 원격 모드에서 파일은 업로드로만 들어오고, 도구는 이름으로 가리킨다.
    def list_inbox(self, user_id: str) -> list[InboxFile]:
        """이름순."""
        ...
    def put_inbox(self, user_id: str, name: str, data: bytes) -> InboxFile:
        """같은 이름이면 덮어쓴다. name은 magus.inbox.safe_filename을 거친 것이어야 한다."""
        ...
    def delete_inbox(self, user_id: str, name: str) -> bool: ...
    def inbox_path(self, user_id: str, name: str) -> Path | None:
        """읽기용 로컬 경로(P1: 디스크 파일 그대로, P2: 객체 스토리지에서 받은 임시 파일). 없으면 None."""
        ...
    def usage_bytes(self, user_id: str) -> int:
        """사용자 폴더 전체(원고·책장·받은함·휴지통) 크기. 저장 용량 한도에 쓴다."""
        ...
    def get_profile(self, user_id: str) -> Profile:
        """없으면 빈 프로필. 읽기만 하면 사용자 폴더를 만들지 않는다."""
        ...
    def save_profile(self, user_id: str, profile: Profile) -> Profile: ...

    # 프로젝트
    def create_project(
        self, user_id: str, title: str, project_id: str | None = None, *, titles: BookTitles | None = None
    ) -> Project:
        """titles가 있으면 부제·영문 제목·영문 부제도 project.json에 둔다(title 인자가 제목이다)."""
        ...
    def set_titles(self, user_id: str, project_id: str, titles: BookTitles) -> Project:
        """제목·부제·영문 제목·영문 부제를 바꾼다(다시 올리기). title이 None이면 제목은 그대로 둔다."""
        ...
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
    def read_original(self, user_id: str, project_id: str, filename: str) -> str | None:
        """original/의 리포트 md(import-report.md, E2-reupload-report.md). 없으면 None."""
        ...
    def get_non_citation_terms(self, user_id: str, project_id: str) -> list[str]:
        """인용 추출에서 뺄 낱말(지명·사건 등). 프로젝트의 book/non_citation_terms.txt, 한 줄에 하나."""
        ...
    def set_non_citation_terms(self, user_id: str, project_id: str, terms: list[str]) -> None: ...
    def get_ai_authors(self, user_id: str, project_id: str) -> list[str]:
        """이 프로젝트에서 AI로 볼 코멘트 작성자 이름(기본 목록에 더한다). book/ai_authors.txt, 한 줄에 하나."""
        ...
    def set_ai_authors(self, user_id: str, project_id: str, names: list[str]) -> None: ...
    def get_answers(self, user_id: str, project_id: str) -> str:
        """저자 확인 질문지의 답(book/answers.md, #84). 없으면 ""."""
        ...
    def add_answer(self, user_id: str, project_id: str, block: str) -> None:
        """답 한 덩어리를 answers.md 끝에 더한다(파일이 없으면 머리말과 함께 만든다)."""
        ...
    def set_parts(self, user_id: str, project_id: str, parts: list[Part]) -> None: ...
    def list_parts(self, user_id: str, project_id: str) -> list[Part]: ...

    # 장
    def list_chapters(self, user_id: str, project_id: str) -> list[ChapterMeta]:
        """읽는 순서(reading_order): 번호순이되 부 들어가며는 그 부의 첫 장 앞."""
        ...
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
        edition: int | None = None,
    ) -> ChapterMeta:
        """이전 본문을 versions/에 보관한 뒤 새 본문을 쓴다. 없는 번호면 새 장을 만든다.
        edition은 업로드로 쓸 때만 준다(그 판의 본문). 주지 않으면(book_write_chapter) 앞머리의 edition이 비워진다.
        content는 본문만이다. front matter가 붙어 오면 벗겨 내고, 메타는 인자로만 바꾼다.
        status는 CHAPTER_STATUSES 중 하나여야 하고, 빈 본문은 거부한다(ValueError)."""
        ...
    def set_chapter_edition(self, user_id: str, project_id: str, number: int, edition: int) -> None:
        """본문이 그대로인 장에 '이 판과 같다'고만 적는다. 버전·갱신 시각은 그대로다(다시 올리기)."""
        ...
    def remove_chapter(self, user_id: str, project_id: str, number: int, edition: int) -> str:
        """새 판에 없는 장: 본문과 이전본을 removed/ch-NN-E{edition}/로 옮기고 인덱스에서 뺀다. 지우지 않는다."""
        ...
    def list_editions(self, user_id: str, project_id: str) -> list[Edition]:
        """판 기록(오래된 것부터). 판 기록 전에 임포트한 프로젝트는 빈 목록."""
        ...
    def add_edition(self, user_id: str, project_id: str, edition: Edition) -> None: ...
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
        author: str | None = None,
        author_kind: AuthorKind | None = None,
        comment_date: str | None = None,
        anchor: str | None = None,
        paragraph: int | None = None,
        comment_fp: str | None = None,
    ) -> Issue: ...
    def update_issues(self, user_id: str, project_id: str, issues: list[Issue]) -> None:
        """같은 번호의 미해결을 이 내용으로 바꾼다(issues.md를 한 번만 다시 쓴다). 다시 올리기에서 쓴다."""
        ...
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
        """exports/<filename>에 저장하고 위치(로컬 절대 경로)를 돌려준다. 원격 모드는 이것으로 다운로드 링크를 만든다."""
        ...
    def export_path(self, user_id: str, project_id: str, filename: str) -> Path | None:
        """다운로드용: 그 사용자·프로젝트의 exports/<filename>. 없거나 밖을 가리키면 None."""
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
    def get_ref(self, user_id: str, key: str, *, floors: Iterable[str] | None = None) -> Ref | None: ...
    def resolve_ref(self, user_id: str, key: str, *, floors: Iterable[str] | None = None) -> Ref | None:
        """key로 찾고, 없으면 aliases에서 찾는다. floors를 주면 그 층들 안에서만."""
        ...
    def list_refs(self, user_id: str, status: RefStatus | None = None, *, floors: Iterable[str] | None = None) -> list[Ref]:
        """floors를 주면 그 층들의 문헌만(인용 점검: 그 작업물 층 + 공용, #93)."""
        ...
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
    def list_ideas(self, user_id: str, author: Author | None = None, *, floors: Iterable[str] | None = None) -> list[Idea]: ...

    # 문체 (Balthasar) — 사람 소유
    def add_style(self, user_id: str, entry: StyleEntry) -> StyleEntry:
        """reason + tags만 색인·임베딩한다(balthasar.style.search_text). passage는 색인하지 않는다."""
        ...
    def get_styles(self, user_id: str, ids: list[str]) -> dict[str, StyleEntry]: ...
    def list_styles(self, user_id: str, *, floors: Iterable[str] | None = None) -> list[StyleEntry]: ...

    # 휴지통(생각·문체, #88) — 지우지 않고 trash/shelf/로 옮긴다. 검색·목록·웹에서 빠지고 되살릴 수 있다
    def trash_idea(self, user_id: str, idea_id: str, note: str) -> list[Idea]:
        """그 생각과, 그 생각에 응답한 AI 발화(parent_id)를 함께 옮긴다. 없으면 []."""
        ...
    def trash_style(self, user_id: str, style_id: str, note: str) -> StyleEntry | None: ...
    def list_trash(self, user_id: str) -> list[TrashItem]: ...
    def restore_trash(self, user_id: str, kind: TrashKind, item_id: str, *, name: str | None = None) -> list[str]:
        """되살린 id들(생각이면 함께 옮긴 AI 발화 포함). 휴지통에 없으면 ValueError.
        카테고리는 같은 이름이 이미 있으면 ValueError(name으로 새 이름을 주면 그 이름으로 되살린다)."""
        ...

    # 카테고리(#92) — 사람 소유. 원본은 shelf/categories/<id>/{category.json, items/<항목 id>.json}
    def list_categories(self, user_id: str, *, floors: Iterable[str] | None = None) -> list[Category]:
        """만든 순서. items에 항목 수를 채운다. floors를 주면 그 층들의 카테고리만."""
        ...
    def get_category(self, user_id: str, category_id: str) -> Category | None: ...
    def create_category(self, user_id: str, name: str, template: str, color: str, fields: tuple[str, ...],
                        floor: str | None = None) -> Category:
        """이름·템플릿·색은 호출자가 magus.category.rules로 검사한 값이다. id는 저장소가 짓는다.
        이름은 층마다 하나(같은 층에 같은 이름이 있으면 ValueError). floor가 None이면 공용."""
        ...
    def update_category(self, user_id: str, category_id: str, *, name: str | None = None, color: str | None = None) -> Category: ...
    def trash_category(self, user_id: str, category_id: str, note: str) -> Category | None:
        """카테고리 폴더를 통째로 trash/shelf/categories/로 옮긴다(항목 포함). 없으면 None."""
        ...
    def put_category_item(self, user_id: str, item: CategoryItem) -> CategoryItem:
        """같은 id가 있으면 바꾼다(created_at은 그대로, updated_at은 지금)."""
        ...
    def list_category_items(self, user_id: str, category_id: str | None = None) -> list[CategoryItem]:
        """category_id가 None이면 모든 카테고리. 항목 id 순(= 만든 순)."""
        ...
    def get_category_item(self, user_id: str, category_id: str, item_id: str) -> CategoryItem | None: ...
    def trash_category_item(self, user_id: str, category_id: str, item_id: str, note: str) -> CategoryItem | None: ...
    def get_shelf_settings(self, user_id: str) -> ShelfSettings: ...
    def save_shelf_settings(self, user_id: str, settings: ShelfSettings) -> ShelfSettings:
        """색은 #rrggbb만 남기고, 내 색은 최대 12개."""
        ...

    # 층(#93) — 공용 + 작업물(프로젝트)마다 한 층. 원본은 shelf/floors.json과 각 항목 파일의 "floor"
    def list_floors(self, user_id: str) -> list[Floor]:
        """공용이 먼저, 그다음 작업물 층(위에서 아래로). updated_at(최근 수정)을 채운다."""
        ...
    def get_floor(self, user_id: str, floor_id: str) -> Floor | None: ...
    def place(self, user_id: str, kind: str, floor: str | None) -> str:
        """새 항목이 들어갈 층: floor에 그 기본 카테고리(kind)가 있으면 floor, 없고 공용에 있으면 공용,
        둘 다 없으면 floor에 그 기본 카테고리를 다시 꽂고 floor. floor가 None이면 위에서부터 그 종류가 있는 첫 층."""
        ...
    def move_category(self, user_id: str, category_id: str, to_floor: str) -> FloorMove:
        """저자의 카테고리를 통째로 다른 층에. 받는 층에 같은 이름이 있으면 ValueError."""
        ...
    def move_builtin(self, user_id: str, kind: str, from_floor: str, to_floor: str) -> FloorMove:
        """기본 카테고리(생각·문체·문헌)를 그 항목과 함께 다른 층에. 받는 층에 같은 종류가 있으면 합친다."""
        ...
    def last_move(self, user_id: str) -> FloorMove | None: ...
    def last_undone(self, user_id: str) -> FloorMove | None:
        """마지막으로 되돌린 옮기기(웹의 '되돌렸습니다' 한 줄)."""
        ...
    def undo_move(self, user_id: str, move_id: str) -> FloorMove:
        """마지막 옮기기를 되돌린다. 마지막 옮기기가 아니거나 이미 되돌렸으면 ValueError."""
        ...
    def move_document(self, user_id: str, doc_id: str, to_floor: str) -> FloorMove:
        """문서 책을 다른 작업물 층으로(공용은 MoveError common_only)."""
        ...
    def trash_manuscript(self, user_id: str, project_id: str, note: str) -> str:
        """원고 책을 휴지통으로: 작업물 폴더를 통째로 trash/로 옮기고, 같은 id·제목의 빈 층을 남긴다(층의 다른 책은 그대로)."""
        ...
    def set_project_color(self, user_id: str, project_id: str, color: str | None) -> None: ...

    # 문서 책(#94) — shelf/documents/<id>/{document.json, v1.md…}
    def create_document(self, user_id: str, doc: Document, content: str) -> Document: ...
    def add_document_version(self, user_id: str, doc_id: str, version: DocVersion, content: str) -> Document: ...
    def get_document(self, user_id: str, doc_id: str) -> Document | None: ...
    def list_documents(self, user_id: str, *, floors: Iterable[str] | None = None, project_id: str | None = None) -> list[Document]: ...
    def read_document(self, user_id: str, doc_id: str, number: int | None = None) -> str | None: ...
    def update_document(self, user_id: str, doc_id: str, *, title: str | None = None, color: str | None = None,
                        title_by: str | None = None) -> Document: ...
    def trash_document(self, user_id: str, doc_id: str, note: str) -> Document | None: ...

    def set_ref_floor(self, user_id: str, key: str, floor: str, reason: str | None = None) -> Ref:
        """문헌 한 편의 층만 바꾼다(두 작업물이 함께 쓰게 된 문헌을 공용으로 옮길 때). reason을 주면 bib.json의 "moved"에
        옮긴 시각·원래 층·이유를 남긴다(웹 문헌 항목에 보인다)."""
        ...
    def category_updated(self, user_id: str, category_id: str) -> str:
        """카테고리의 최근 수정(카테고리·항목 중 가장 최근)."""
        ...
    def builtin_updated(self, user_id: str, kind: str, floor: str) -> str:
        """그 층 기본 카테고리의 최근 수정(항목 중 가장 최근)."""
        ...

    # 검색 청크 (모든 책장 공용)
    def search_fts(self, user_id: str, lanes: list[Lane], match: str, limit: int) -> list[Chunk]: ...
    def search_vector(self, user_id: str, lanes: list[Lane], vector: list[float], limit: int) -> list[Chunk]: ...
    def search_substring(self, user_id: str, lanes: list[Lane], needle: str, limit: int) -> list[Chunk]:
        """청크 글에 needle이 그대로 들어 있는 것(최근 청크부터). 2글자 조각 색인이 못 찾는 한 글자 검색어용(웹 책장)."""
        ...
    def chunks_missing_embedding(self, user_id: str, limit: int = 256) -> list[Chunk]:
        """임베딩이 빈 청크. 웹 검색 전용 레인(WEB_ONLY_LANES)은 벡터 검색을 하지 않으니 빼고 준다."""
        ...
    def set_embeddings(self, user_id: str, vectors: dict[int, list[float]]) -> None: ...

    # 인덱스
    def reindex(self) -> None:
        """원본 파일에서 인덱스 전체를 다시 만든다."""
        ...
