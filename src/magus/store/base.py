"""저장소 인터페이스.

P0 구현은 LocalStore(사람이 읽는 파일이 원본, SQLite는 인덱스)이고, P1 구현은 Postgres + 객체 스토리지다.
모든 메서드가 user_id를 인자로 받는다. 저장소는 "현재 사용자"를 모른다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal, NamedTuple, Protocol

from magus.contexts import Context, SavedContext  # 컨텍스트(#96). 규칙과 함께 magus.contexts에 둔다(순환 import를 피해)

IssueStatus = Literal["open", "closed"]
IssueOrigin = Literal["import_comment", "user", "agent"]
# citation: 출처 확인 코멘트 + 문헌이 지목됨 / fact: 출처 확인 코멘트지만 문헌 없음(사실·수치 확인) / general: 그 외
IssueKind = Literal["citation", "fact", "general"]
AuthorKind = Literal["ai", "person"]  # 원고 코멘트 작성자: AI인가 사람인가(#71)
ANCHOR_MAX = 1000  # 미해결에 남기는 걸린 문장의 최대 길이(#73)
IssueStale = Literal["comment_removed", "anchor_missing"]  # 다시 올린 뒤 "해결됐을 수 있음"(#76)
ChapterStatus = Literal["draft", "revising", "done"]
CHAPTER_STATUSES: tuple[str, ...] = ("draft", "revising", "done")
# 장 번호 범위(2026-10-09 점검 15-1): 0(서장)~9,999. 너무 큰 번호(2^63 이상)는 색인(SQLite 정수)에 들어가지 않아 다시 만들기를 막았다
CHAPTER_NUMBER_MAX = 9_999
CHAPTER_RANGE = f"장 번호는 0~{CHAPTER_NUMBER_MAX:,}입니다(0은 서장)."  # 범위 밖 장 번호 안내(쓰기·읽기 도구 공통)


def chapter_number_ok(number: int) -> bool:
    return 0 <= number <= CHAPTER_NUMBER_MAX
# 저자에게 보이는 장 상태 이름(웹·내려받기, 2026-10-09). 도구 인자·파일 값은 영문 그대로
CHAPTER_STATUS_NAMES: dict[str, str] = {"draft": "초안", "revising": "고치는 중", "done": "완성"}
RefStatus = Literal["unverified", "verified"]
# style_passage·ref_bib는 웹 책장 검색 전용이다(문체 구절·문헌 서지). 도구 검색(style_search·ref_search)은 쓰지 않고 임베딩도 하지 않는다.
# category는 저자가 만든 카테고리의 항목(#92). owner_id는 "<카테고리 id>/<항목 id>"다.
# document는 문서 책의 지금 판 내용(#94). 웹 책장 검색 전용이다.
# #96: 생각·문체는 글(category 레인)이 됐다. idea_*·style* 레인은 쓰지 않는다(옛 인덱스를 읽을 일이 없어 이름만 남긴다).
Lane = Literal["ref_picked", "ref_full", "idea_me", "idea_ai", "style", "style_passage", "ref_bib", "category", "document",
               "attach_text"]  # attach_text: 첨부에서 뽑은 글자(2026-10-09 #100, chunks.part = 첨부 id)
# 임베딩(벡터 검색)하지 않는 레인. 옛 이름 그대로(처음에는 웹 찾기 전용 레인이었다). #100: ref_bib은 대화 찾기도 보고, 첨부 글자는 길어서 임베딩하지 않는다
WEB_ONLY_LANES: tuple[str, ...] = ("style_passage", "ref_bib", "document", "attach_text")
TagsBy = Literal["ai", "author"]  # 문체 태그를 누가 정했나: Claude가 뽑음(ai) / 저자가 말함(author). 기록 전 항목은 None
# 휴지통에 옮길 수 있는 책장 항목(#88). 카테고리는 통째(category, id = 카테고리 id)와 항목(category_item, id = "<카테고리 id>/<항목 id>")
TrashKind = Literal["category", "category_item", "node", "attachment"]  # #96: 생각·문체 휴지통은 책의 글 휴지통(category_item)이 됐다. attachment: 글에서 뺀 첨부 하나(2026-10-09)
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
    contexts: tuple[Context, ...] = ()  # 올린 문서가 든 책(가운데 노드)의 컨텍스트(#96, project.json "contexts")


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


@dataclass(frozen=True)
class Attachment:
    """글에 붙인 파일 하나(#97). id는 서버가 만든 시간순 id(new_id), name은 다듬은 원래 이름, at은 올린 시각(UTC ISO).
    owner: 글이면 "<책 id>/<글 id>", 문헌 글이면 "ref:<key>"."""

    id: str
    name: str
    size: int
    at: str


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
    "comment_removed": "올린 문서에서 코멘트가 지워짐",
    "anchor_missing": "걸린 문장이 올린 문서에 없음",
}


@dataclass(frozen=True)
class Edition:
    """원고 업로드 한 번 = 판 하나(E1, E2…). project.json의 editions에 쌓인다(#76)."""

    number: int
    file: str  # 올린 문서 파일 이름. 사본은 original/에 있다
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
    floor: str | None = None  # 그 글이 있는 프로젝트(#93 층 → #95). None이면 저장소가 정한다(book의 프로젝트)
    updated_at: str = ""  # 마지막으로 고친 시각(층의 최근 수정에 쓴다). 기록 전 문헌은 created_at
    # 두 작업물이 함께 쓰게 되어 공용으로 옮겨졌을 때의 기록(#93-a 더함): {"at", "from", "to", "reason"}. 저자 모르게 배치가 바뀌지 않게
    moved: dict[str, str] | None = None
    # 그 글이 꽂힌 책(카테고리 id, #96). 문헌·참고문헌 항목도 여느 글처럼 어떤 책에든 들어간다. None이면 저장소가 정한다
    book: str | None = None
    scrap: bool = False  # 스크랩(별표, 2026-10-09). bib.json에 켰을 때만 "scrap": true. put_ref는 바꾸지 않는다(set_scrap만)


Author = Literal["me", "ai"]


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
    items: int = 0  # 글 수(목록에서 채운다). 문헌·참고문헌 항목(sources)은 따로 센다
    floor: str = "common"  # 그 책이 있는 프로젝트(#93 층 → #95)
    contexts: tuple[Context, ...] = ()  # 컨텍스트(#96). 읽을 때는 꽂힌 노드의 것 다음에 이것(#96-d)
    sources: int = 0  # 이 책에 든 문헌·참고문헌 항목 수(#96, refs.book). 목록에서 채운다
    verified: int = 0  # 그중 원문 확인 수


@dataclass(frozen=True)
class CategoryItem:
    """책의 글 하나(#96. 옛 '카테고리 항목', 옛 생각·문체도 이것이 됐다). author: 누가 말했나(me = 저자의 말, ai = Claude가 쓴 글).
    chapters: [(project_id, 장 번호)]. 문헌(서지·원문 확인)은 이것이 아니라 Ref로 저장되고 같은 책에 함께 보인다."""

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
    # #96에서 더한 칸(모두 선택). 어느 책에든 쓸 수 있고, 무엇을 묻고 채울지는 그 책의 컨텍스트가 AI에게 알려 준다
    reason: str | None = None  # 이유(왜 골랐나·왜 좋은가). 저자가 말한 것만
    where: str | None = None  # 위치(출전·쪽·장소)
    passages: tuple[Passage, ...] = ()  # 쓸 부분(원문에서 고른 대목과 그 이유·위치)
    parent_id: str | None = None  # 이 글이 응답한 글(대화 기록의 AI 발화)
    origin: str | None = None  # 어디서 왔나(대화 기록 이름 등)
    kind: str | None = None  # 옛 생각의 갈래(thought·ai·article·conversation·tv·other). 화면에 보이지 않고 되돌리기에 쓴다
    tags_by: TagsBy | None = None  # 태그를 누가 정했나(옛 문체 #89)
    scrap: bool = False  # 스크랩(저자가 별표로 표시해 둔 글, 2026-10-09). 파일에는 켰을 때만 "scrap": true


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
    contexts: tuple[Context, ...] = ()  # 컨텍스트(#96). 출처 확인 문서는 만들 때 그 설명을 붙인다


@dataclass(frozen=True)
class Floor:
    """프로젝트 하나(#95. 옛 '층', #93). 「내 서재」(id "common", number 0, 옛 공용 층) 또는 작업물 하나.
    number는 만든 순서(1, 2…)이고 저자에게 보이지 않는다. 이름(label)은 「내 서재」 또는 작업물 제목이다."""

    id: str
    number: int
    title: str
    builtins: tuple[str, ...] = ()  # 이 프로젝트에 있는 기본 책(ideas|styles|refs)
    has_manuscript: bool = False  # 장이 하나라도 있나(원고 없는 프로젝트면 False)
    updated_at: str = ""  # 최근 수정: 그 프로젝트의 원고·책·항목·지도·옮기기 중 가장 최근

    @property
    def common(self) -> bool:
        """「내 서재」인가(옛 공용 층)."""
        return self.number == 0

    @property
    def label(self) -> str:
        return self.title


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
    from_node: str | None = None  # 지도(#95): 옮기기 전 노드와 옮긴 노드(되돌릴 때 그 노드로)
    to_node: str | None = None
    made_node: bool = False  # 옮기며 받는 지도에 새로 생긴 노드(이름이 같은 새 노드). 되돌릴 때 비면 치운다


@dataclass(frozen=True)
class MapNode:
    """지도의 노드 하나(#95). books는 책 주소 이름(ms.<프로젝트>·ideas.<프로젝트>·<카테고리 id>·doc.<id>).
    연결 노드(link)는 책을 갖지 않고 원본(프로젝트, 노드)을 가리킨다. 이름은 원본 노드 이름이고, 원본이 없으면 missing."""

    id: str
    name: str
    x: float
    y: float
    color: str | None = None
    books: tuple[str, ...] = ()
    center: bool = False
    link: tuple[str, str] | None = None  # (원본 프로젝트 id, 원본 노드 id)
    link_title: str = ""  # 원본 프로젝트 이름
    missing: bool = False  # 연결 노드의 원본이 없다
    contexts: tuple[Context, ...] = ()  # 노드의 컨텍스트(#96). 연결 노드는 원본 노드의 것


class EditConflict(ValueError):
    """고치는 동안 다른 곳(웹의 다른 창·대화)에서 그 글이 저장됐다(2026-10-09). 덮어쓰지 않고 거절한다."""


def edit_stamp(record: dict[str, Any]) -> str:
    """글·문헌 글 파일의 '마지막으로 저장한 시각'(고친 시각, 기록 전이면 만든 시각). 동시 고치기 검사에 쓴다."""
    return str(record.get("updated_at") or record.get("created_at") or "")


@dataclass(frozen=True)
class NodeTrashInfo:
    """웹의 노드 삭제 확인 창에 보일 것(#97). blocked: 옮길 수 없는 까닭 코드(center | linked | has_refs | unknown_book), 없으면 None."""

    node: MapNode
    books: int
    items: int
    blocked: str | None = None
    linked_from: tuple[str, ...] = ()  # 이 노드를 가리키는 연결 노드가 있는 프로젝트 이름
    refs_book: str = ""  # 문헌 글이 든 책 이름


@dataclass(frozen=True)
class ProjectTrashInfo:
    """웹의 확인 창에 보일 것. blocked: library(「내 서재」) | linked(다른 프로젝트가 연결 중), 없으면 None."""

    project_id: str
    title: str
    nodes: int
    books: int
    items: int
    refs: int
    chapters: int
    revisions: int  # 수정본 수(E2부터. 처음 올린 문서 E1은 세지 않는다)
    blocked: str | None = None
    linked_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrashedProject:
    trash_id: str  # trash/projects/ 아래 폴더 이름(<프로젝트>-<시각>)
    project_id: str
    title: str
    trashed_at: str
    chapters: int
    revisions: int
    books: int
    items: int


@dataclass(frozen=True)
class TrashedExtra:
    """휴지통의 만든 문서(document)·올린 문서(manuscript)(2026-10-11 휴지통 비우기에서 화면에 보이게 됐다). id는 휴지통 폴더 이름."""

    kind: str
    id: str
    project_id: str
    title: str
    trashed_at: str
    detail: str = ""


@dataclass(frozen=True)
class ProjectMap:
    """프로젝트 하나의 지도(#95): 노드와 선. stored: 지도 파일이 있나(없으면 지금 배치에서 계산한 지도)."""

    floor: str
    title: str
    nodes: tuple[MapNode, ...]
    edges: tuple[tuple[str, str], ...]
    stored: bool = False
    updated_at: str = ""

    def node(self, node_id: str) -> MapNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def node_of(self, book: str) -> MapNode | None:
        return next((n for n in self.nodes if book in n.books), None)


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
    """휴지통의 책·글·노드 하나. 지우지 않고 옮겨 둔 것이라 되살릴 수 있다(#88·#92·#95)."""

    kind: TrashKind
    id: str
    trashed_at: str
    note: str
    preview: str
    with_id: str | None = None  # 함께 옮겨진 AI 발화면 그 발화가 응답한 생각의 id
    owner: str | None = None  # 첨부(attachment)면 그 글("<책 id>/<글 id>" 또는 "ref:<key>"). id는 "<owner>/<첨부 id>"
    title: bool = False  # 글이면 제목이 있었나(preview가 제목인지 본문 앞부분인지)
    detail: str = ""  # 노드면 그 안에 있던 것 한 줄(책 N권·글 N개·먼저 버린 글 N개, 2026-10-09)


@dataclass(frozen=True)
class Chunk:
    """검색 단위. owner_type/owner_id로 원본(ref·idea·style)을 가리킨다."""

    id: int
    owner_type: str
    owner_id: str
    lane: Lane
    text: str
    score: float = 0.0
    part: str | None = None  # attach_text 레인이면 그 첨부 id(어느 첨부의 글자인지)
    partial: int = 0  # 찾기에서 모두 맞는 글이 없어 일부 낱말만 맞은 조각이면 맞은 낱말 수(후속 C). 0이면 보통 결과


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
    def put_inbox(self, user_id: str, name: str, data: bytes | IO[bytes]) -> InboxFile:
        """같은 이름이면 덮어쓴다. name은 magus.inbox.safe_filename을 거친 것이어야 한다."""
        ...
    def delete_inbox(self, user_id: str, name: str) -> bool: ...
    def inbox_path(self, user_id: str, name: str) -> Path | None:
        """읽기용 로컬 경로(P1: 디스크 파일 그대로, P2: 객체 스토리지에서 받은 임시 파일). 없으면 None."""
        ...
    def trash_inbox(self, user_id: str, name: str, note: str) -> str:
        """예전 올린 파일을 지우지 않고 휴지통(trash/inbox/)으로 옮긴다(문서 업데이트, 2026-10-10). 휴지통 id. 없으면 ValueError."""
        ...
    def list_trashed_inbox(self, user_id: str) -> list[tuple[str, InboxFile, dict]]:
        """휴지통의 예전 올린 파일 (휴지통 id, 파일, 기록{at, note, name}). 새것부터."""
        ...
    def restore_inbox(self, user_id: str, trash_id: str) -> str:
        """되살린 이름. 막히면 ValueError(code: missing·taken, 이름)."""
        ...
    def usage_bytes(self, user_id: str) -> int:
        """사용자 폴더 전체(원고·책장·받은함·휴지통) 크기. 저장 용량 한도에 쓴다."""
        ...

    # 글의 첨부(#97) — 사용자 폴더 안(글 폴더 옆, 백업 대상). owner는 "<책 id>/<글 id>" 또는 "ref:<key>"
    def list_attachments(self, user_id: str, owner: str) -> list[Attachment]:
        """올린 순서. 글이 없거나 첨부가 없으면 []."""
        ...
    def put_attachment(self, user_id: str, owner: str, name: str, data: bytes | IO[bytes]) -> Attachment:
        """name은 magus.attachments.clean_name을 거친 것. 글이 없으면 ValueError."""
        ...
    def attachment_path(self, user_id: str, owner: str, attachment_id: str) -> tuple[Path, Attachment] | None:
        """읽기용 로컬 경로와 정보. 없으면 None."""
        ...
    def trash_attachment(self, user_id: str, owner: str, attachment_id: str, note: str) -> bool:
        """지우지 않고 trash/shelf/attachments/로 옮긴다. 없으면 False."""
        ...
    def replace_attachment(self, user_id: str, owner: str, attachment_id: str, name: str, data: bytes | IO[bytes],
                           note: str) -> tuple[Attachment, str]:
        """같은 첨부 id 자리에 새 파일(문서 업데이트). 이전 파일은 새 휴지통 id로 첨부 휴지통에. (새 첨부, 휴지통 id). 없으면 ValueError."""
        ...
    def attachment_thumb(self, user_id: str, owner: str, attachment_id: str) -> Path | None:
        """사진 첨부의 썸네일(긴 변 400px JPEG, 첨부 폴더 안 .thumb/, 없으면 만든다). 사진이 아니거나 만들지 못하면 None. 원본은 바꾸지 않는다."""
        ...
    def trashed_item_attachments(self, user_id: str, book: str, item: str) -> list[str]:
        """휴지통에 있는 글의 첨부 이름(올린 순서)."""
        ...
    def attachment_text(self, user_id: str, owner: str, attachment_id: str, *, make: bool = True,
                        deadline: float | None = None) -> tuple[dict | None, str | None]:
        """첨부에서 뽑은 글자(#100): (상태 {status, chars, ms, at, reason?}, 글자). 상태가 없거나(그 형식을 뽑기 전 VERSION의 상태 포함) '나중에'면 make일 때 지금 뽑아
        첨부 폴더 안 .text/에 적고 그 글의 색인을 다시 만든다. 뽑지 않는 형식이면 (None, None). 원본은 읽기만."""
        ...
    def find_attachment(self, user_id: str, attachment_id: str) -> tuple[str, Attachment] | None:
        """첨부 id → (owner, 첨부). 휴지통에 있는 것과 다른 사용자의 것은 찾지 않는다."""
        ...
    def file_attachments(self, user_id: str, suffixes: tuple[str, ...]) -> list[tuple[str, Attachment]]:
        """모든 글·문헌 글의 첨부 중 이름이 suffixes(소문자 확장자)로 끝나는 것 (owner, 첨부). 새것부터.
        게시판에 첨부한 문서를 files_list가 보이고 도구의 파일 인자('첨부:<id>')로 읽게 한다(2026-10-09)."""
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
    def original_bytes(self, user_id: str, project_id: str, filename: str | None = None) -> tuple[str, bytes] | None:
        """(파일 이름, 내용): original/의 원고 파일. filename이 없으면 마지막 수정본의 원고(내려받기용, #95)."""
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
    def get_cache(self, user_id: str, project_id: str, name: str) -> str:
        """프로젝트의 계산 캐시(지워도 다시 계산하는 파생값, 2026-10-09 인용 계산). 없으면 ""."""
        ...
    def put_cache(self, user_id: str, project_id: str, name: str, text: str) -> None:
        """계산 캐시를 쓴다. 프로젝트의 최근 수정 시각은 바꾸지 않는다."""
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

    # 문헌 (Melchior) — 사람마다 key 하나. 어느 책의 글로 보인다(#96: refs.book)
    def get_ref(self, user_id: str, key: str, *, floors: Iterable[str] | None = None) -> Ref | None: ...
    def resolve_ref(self, user_id: str, key: str, *, floors: Iterable[str] | None = None) -> Ref | None:
        """key로 찾고, 없으면 aliases에서 찾는다. floors를 주면 그 층들 안에서만."""
        ...
    def list_refs(self, user_id: str, status: RefStatus | None = None, *, floors: Iterable[str] | None = None,
                  book: str | None = None) -> list[Ref]:
        """floors를 주면 그 프로젝트들의 문헌만(인용 점검 범위), book을 주면 그 책의 것만(#96)."""
        ...
    def get_passages(self, user_id: str, key: str) -> list[Passage]: ...
    def put_ref(
        self, user_id: str, ref: Ref, passages: list[Passage] | None = None, full_text: str | None = None
    ) -> Ref:
        """bib.json을 쓰고 인덱스·청크를 갱신한다. passages/full_text가 None이면 기존 것을 그대로 둔다.
        ref.book이 없으면 지금 책, 새 문헌이면 그 프로젝트의 문헌 책(source_book, 없으면 만든다, #96)."""
        ...
    def source_book(self, user_id: str, floor: str, *, create: bool = False) -> str | None:
        """그 프로젝트에서 문헌·참고문헌 항목이 든 책(가장 많이 든 책). 없으면 create일 때 「참고문헌」 책을 만든다(#96)."""
        ...
    def default_project(self, user_id: str) -> str:
        """프로젝트를 말하지 않았을 때 문헌이 갈 프로젝트: 프로젝트가 하나면 그것, 아니면 「내 서재」."""
        ...
    def set_ref_book(self, user_id: str, key: str, book: str, reason: str | None = None) -> Ref:
        """문헌 한 편을 다른 책으로(프로젝트도 그 책의 것). reason을 주면 bib.json "moved"에 옮긴 기록을 남긴다(#93-a)."""
        ...
    def node_trash_info(self, user_id: str, floor: str, node_id: str) -> NodeTrashInfo | None:
        """웹의 노드 삭제 확인 창(#97): 책·글 수와 막는 까닭(가운데·다른 프로젝트가 연결 중·문헌 글이 든 책)."""
        ...
    def trash_node_with_books(self, user_id: str, floor: str, node_id: str, note: str) -> MapNode:
        """노드를 책·글·첨부·문서째 휴지통으로(#97, 웹). 되살리기는 restore_trash("node", …)."""
        ...
    def set_scrap(self, user_id: str, owner: str, on: bool) -> bool:
        """글("<책 id>/<글 id>") 또는 문헌 글("ref:<key>")의 스크랩(별표)을 켜고 끈다. 파일의 표시 하나만 바꾸고(고친 시각은 그대로)
        색인도 바꾼다. 없는 글이면 ValueError. 바꾼 뒤의 값을 돌려준다."""
        ...
    def add_passages(self, user_id: str, key: str, passages: list[Passage]) -> tuple[int, int]:
        """문헌 글에 쓸 부분을 더한다(passages.json만, 같은 대목은 한 번). (더한 수, 모두). 없으면 ValueError."""
        ...
    def set_ref_memo(self, user_id: str, key: str, memo: str) -> Ref:
        """문헌 글의 본문(bib.memo)만 바꾼다(웹의 글 고치기). 서지·쓸 부분·원문 확인 표시와 그 기록은 그대로."""
        ...
    def set_ref_status(self, user_id: str, key: str, status: str, via: str = "chat") -> Ref:
        """원문 확인 표시만 바꾼다(#97, 웹의 '원문 확인' 체크). 쓸 부분·전문·서지는 그대로. bib.json "status_by"에 누가·언제."""
        ...

    # 휴지통 — 지우지 않고 trash/shelf/로 옮긴다. 검색·목록·웹에서 빠지고 되살릴 수 있다
    def list_trash(self, user_id: str) -> list[TrashItem]: ...
    def restore_trash(self, user_id: str, kind: TrashKind, item_id: str, *, name: str | None = None) -> list[str]:
        """되살린 id들(글이면 함께 옮긴 응답 글 포함). 휴지통에 없으면 ValueError.
        책은 같은 이름이 이미 있으면 ValueError(name으로 새 이름을 주면 그 이름으로 되살린다)."""
        ...

    # 자주 쓰는 컨텍스트(#96) — shelf/contexts.json. 파일이 없으면 처음 제공하는 넷
    def list_saved_contexts(self, user_id: str) -> list[SavedContext]: ...
    def save_saved_context(self, user_id: str, context: SavedContext) -> SavedContext:
        """같은 id면 고치고, 없으면 더한다(이름이 같은 것이 있으면 ValueError). 처음 쓸 때 기본 넷도 함께 파일에 적는다."""
        ...
    def delete_saved_context(self, user_id: str, context_id: str) -> bool: ...
    def set_book_contexts(self, user_id: str, key: str, contexts: tuple[Context, ...]) -> None:
        """책(카테고리 id · ms.<프로젝트> · doc.<id>)의 컨텍스트를 바꾼다(빈 것이면 뗀다)."""
        ...
    def set_node_contexts(self, user_id: str, floor: str, node_id: str, contexts: tuple[Context, ...]) -> MapNode: ...

    # 카테고리(#92) — 사람 소유. 원본은 shelf/categories/<id>/{category.json, items/<항목 id>.json}
    def list_categories(self, user_id: str, *, floors: Iterable[str] | None = None) -> list[Category]:
        """만든 순서. items에 항목 수를 채운다. floors를 주면 그 층들의 카테고리만."""
        ...
    def get_category(self, user_id: str, category_id: str) -> Category | None: ...
    def create_category(self, user_id: str, name: str, template: str, color: str, fields: tuple[str, ...],
                        floor: str | None = None, node: str | None = None, *, contexts: tuple[Context, ...] = (),
                        category_id: str | None = None) -> Category:
        """책 만들기(#96: 모든 책). 이름·템플릿·색은 호출자가 magus.category.rules로 검사한 값이다. id는 저장소가 짓는다
        (category_id는 이전만 준다). 이름은 프로젝트마다 하나(같은 프로젝트에 같은 이름이 있으면 ValueError).
        floor가 None이면 「내 서재」. node: 꽂을 노드(#95). 없으면 이름이 같은 노드, 그것도 없으면 이름이 같은 새 노드."""
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
    def patch_category_item(self, user_id: str, category_id: str, item_id: str, changes: dict[str, Any]) -> CategoryItem:
        """글 파일에서 준 칸만 바꾼다(웹의 글 고치기·스크랩). 나머지 칸은 파일에서 그대로. 값이 None이면 그 칸을 뺀다. 없으면 ValueError."""
        ...
    # 프로젝트 휴지통(2026-10-09) — trash/projects/<프로젝트>-<시각>/(manifest.json + files/). 지우지 않는다
    def project_trash_info(self, user_id: str, project_id: str) -> ProjectTrashInfo | None:
        """웹 확인 창: 노드·책·글·문헌·장·수정본 수와 막는 까닭(「내 서재」, 다른 프로젝트가 연결 중). 없는 프로젝트면 None."""
        ...
    def trash_project(self, user_id: str, project_id: str, note: str) -> str:
        """프로젝트를 통째로 휴지통으로(휴지통 id). 막히면 ValueError(code, 보일 이름)."""
        ...
    def list_trashed_projects(self, user_id: str) -> list[TrashedProject]: ...
    def restore_project(self, user_id: str, trash_id: str) -> str:
        """되살린 프로젝트 id. 막히면 아무것도 옮기지 않고 ValueError(code: missing·taken·full·clash, 보일 이름)."""
        ...
    # 휴지통 비우기(2026-10-11) — 영구 삭제. 되살릴 수 없다(백업에는 남는다)
    def list_trashed_documents(self, user_id: str) -> list[TrashedExtra]: ...
    def list_trashed_manuscripts(self, user_id: str) -> list[TrashedExtra]: ...
    def trashed_books(self, user_id: str) -> dict[str, tuple[str, str, int]]:
        """책째 휴지통으로 옮긴 책: 휴지통 폴더 이름 → (프로젝트, 책 이름, 글 수)."""
        ...
    def purge_trash(self, user_id: str, kind: str, item_id: str) -> int:
        """kind: node·category_item·attachment·category·document·manuscript·project·inbox. 지운 바이트 수. 없으면 ValueError("missing")."""
        ...
    def trashed_node_books(self, user_id: str, floor: str) -> dict[str, tuple[str, str]]:
        """이 프로젝트에서 책째 휴지통으로 옮긴 노드의 책: 책 id → (책 이름, 노드 이름)."""
        ...
    def trashed_item_project(self, user_id: str, category_id: str, item_id: str) -> str | None:
        """휴지통에 있는 글이면 그 책의 프로젝트(웹의 '이 글은 휴지통에 있습니다.'). 없으면 None."""
        ...
    def get_shelf_settings(self, user_id: str) -> ShelfSettings: ...
    def save_shelf_settings(self, user_id: str, settings: ShelfSettings) -> ShelfSettings:
        """색은 #rrggbb만 남기고, 내 색은 최대 12개."""
        ...

    # 프로젝트(#95, 옛 층 #93) — 「내 서재」(id common) + 작업물마다 하나. 원본은 shelf/floors.json과 각 항목 파일의 "floor"
    def list_floors(self, user_id: str) -> list[Floor]:
        """「내 서재」가 먼저, 그다음 프로젝트(만든 순서). updated_at(최근 수정)을 채운다."""
        ...
    def get_floor(self, user_id: str, floor_id: str) -> Floor | None: ...

    # 지도(#95) — shelf/maps/<프로젝트>.json(노드·선·책 배치). 파일이 없으면 지금 배치에서 계산한 지도
    def get_map(self, user_id: str, floor: str) -> ProjectMap | None: ...
    def ensure_maps(self, user_id: str) -> list[str]:
        """모든 프로젝트의 지도를 파일로 적는다(이미 적힌 것은 그대로). 적은 프로젝트 id."""
        ...
    def map_updated(self, user_id: str, floor: str) -> str: ...
    def book_floor(self, user_id: str, key: str) -> str | None: ...
    def node_of_book(self, user_id: str, key: str) -> tuple[str, str] | None: ...
    def cite_scope(self, user_id: str, floor: str) -> tuple[str, ...]:
        """그 프로젝트 원고의 인용 점검이 보는 문헌의 프로젝트: 자기 + 연결 노드가 가리키는 노드에 꽂힌 문헌."""
        ...
    def add_node(self, user_id: str, floor: str, name: str, *, x: float | None = None, y: float | None = None,
                 color: str | None = None) -> MapNode: ...
    def add_link_node(self, user_id: str, floor: str, target_floor: str, target_node: str, *, x: float | None = None,
                      y: float | None = None) -> MapNode: ...
    def ensure_link(self, user_id: str, floor: str, target_floor: str, book: str) -> MapNode | None:
        """floor의 지도에 target_floor의 그 책(카테고리 id)이 꽂힌 노드로 가는 연결 노드가 없으면 붙인다."""
        ...
    def update_node(self, user_id: str, floor: str, node_id: str, *, name: str | None = None, color: str | None = None,
                    x: float | None = None, y: float | None = None) -> MapNode: ...
    def connect_nodes(self, user_id: str, floor: str, a: str, b: str) -> bool: ...
    def disconnect_nodes(self, user_id: str, floor: str, a: str, b: str) -> bool: ...
    def trash_node(self, user_id: str, floor: str, node_id: str, note: str) -> MapNode: ...
    def place_book(self, user_id: str, floor: str, key: str, node_id: str) -> tuple[str | None, str]: ...
    def move_category(self, user_id: str, category_id: str, to_floor: str, to_node: str | None = None) -> FloorMove:
        """저자의 카테고리를 통째로 다른 층에. 받는 층에 같은 이름이 있으면 ValueError."""
        ...
    def last_move(self, user_id: str) -> FloorMove | None: ...
    def record_move(self, user_id: str, move: FloorMove) -> FloorMove: ...
    def last_undone(self, user_id: str) -> FloorMove | None:
        """마지막으로 되돌린 옮기기(웹의 '되돌렸습니다' 한 줄)."""
        ...
    def undo_move(self, user_id: str, move_id: str) -> FloorMove:
        """마지막 옮기기를 되돌린다. 마지막 옮기기가 아니거나 이미 되돌렸으면 ValueError."""
        ...
    def move_document(self, user_id: str, doc_id: str, to_floor: str, to_node: str | None = None) -> FloorMove:
        """문서 책을 다른 작업물 층으로(공용은 MoveError common_only)."""
        ...
    def trash_manuscript(self, user_id: str, project_id: str, note: str) -> str:
        """원고 책을 휴지통으로: 작업물 폴더를 통째로 trash/로 옮기고, 같은 id·제목의 빈 층을 남긴다(층의 다른 책은 그대로)."""
        ...
    def set_project_color(self, user_id: str, project_id: str, color: str | None) -> None: ...

    # 문서 책(#94) — shelf/documents/<id>/{document.json, v1.md…}
    def create_document(self, user_id: str, doc: Document, content: str, node: str | None = None) -> Document: ...
    def add_document_version(self, user_id: str, doc_id: str, version: DocVersion, content: str) -> Document: ...
    def get_document(self, user_id: str, doc_id: str) -> Document | None: ...
    def list_documents(self, user_id: str, *, floors: Iterable[str] | None = None, project_id: str | None = None) -> list[Document]: ...
    def read_document(self, user_id: str, doc_id: str, number: int | None = None) -> str | None: ...
    def update_document(self, user_id: str, doc_id: str, *, title: str | None = None, color: str | None = None,
                        title_by: str | None = None) -> Document: ...
    def trash_document(self, user_id: str, doc_id: str, note: str) -> Document | None: ...

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
