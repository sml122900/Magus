"""책 규칙(#92 카테고리 → #96 모든 책): 템플릿(칸), 이름 규칙, 책 색, 제목 기본값. 저장(store)과 화면(webshelf)·도구(category.tools)가 함께 쓴다.

- #96부터 기본 카테고리(생각·문체·문헌)가 없다. 옛 기본 카테고리는 이전으로 이름이 같은 여느 책이 됐고(이름·색·휴지통 모두 된다),
  무엇을 담는 책인지는 컨텍스트(magus.contexts)가 말한다. BUILTINS·DEFAULT_COLORS는 이전과 옛 데이터를 읽을 때만 쓴다.
- 책 색은 기본 색 이름(PALETTE) 또는 #RRGGBB만 받는다. 저장할 때 ^#[0-9a-fA-F]{6}$로 검사하고 소문자로 둔다.
  그 밖의 문자열은 스타일에 넣지 않는다. 색에 뜻을 붙이지 않는다(뜻은 저자가 정한다).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from magus.floors import josa

SCHEMA_VERSION = 1  # 책·글·책장 설정 파일 형식. 형식이 바뀌면 올리고 읽을 때 옮긴다
ITEM_SCHEMA = 2  # #96에서 더한 칸(이유·위치·쓸 부분·응답한 글 등)이 있는 글. 없는 글은 1 그대로
NAME_MAX = 12  # 책등에 세로로 들어가는 길이(한글 12자)
MAX_CATEGORIES = 60  # 사용자마다 만들 수 있는 책 수(올린 문서가 든 책·문서 책 빼고). #96: 옛 기본 책도 여기에 든다(30 → 60)
MAX_MY_COLORS = 12
TITLE_MAX = 80
CONTENT_MAX = 20_000
FIELD_MAX = 500
TAGS_MAX, TAG_MAX = 10, 30

# ---- 옛 기본 카테고리(#96 전). 이전이 이 이름·색으로 책을 만든다 ---------------------------------------------
BUILTINS: dict[str, str] = {"ideas": "생각", "styles": "문체", "refs": "문헌"}  # 옛 주소 이름 → 이름
DEFAULT_COLORS = {"ideas": "#1f2f5c", "styles": "#6e1f2f", "refs": "#1f4a3a"}  # 남색·자주·짙은 초록

# ---- 책 색(책장 전용) ----------------------------------------------------------------------------
PALETTE: tuple[tuple[str, str], ...] = (
    ("빨강", "#b3261e"), ("주황", "#d2691e"), ("노랑", "#e8c547"), ("초록", "#2e7d4f"), ("파랑", "#2f6db5"),
    ("남색", "#1f2f5c"), ("보라", "#6b3fa0"), ("분홍", "#e58fb0"), ("갈색", "#7a4e2d"), ("회색", "#8a8d91"),
    ("검정", "#1e1e1e"), ("미색", "#f1e9d2"), ("자주", "#6e1f2f"), ("짙은 초록", "#1f4a3a"), ("청록", "#2a7f86"),
    ("겨자", "#b8923a"), ("하늘", "#8db8de"), ("먹색", "#3b4652"),
)
PALETTE_BY_NAME = dict(PALETTE)
COLOR_NAMES = {hex_: name for name, hex_ in PALETTE}
# 새 카테고리에 차례로 주는 색(차분한 양장본 색부터)
NEW_COLOR_ORDER = ("겨자", "청록", "갈색", "파랑", "빨강", "보라", "먹색", "초록", "주황", "하늘", "분홍", "회색", "노랑",
                   "미색", "검정", "남색", "자주", "짙은 초록")
HEX = re.compile(r"#[0-9a-fA-F]{6}")
_COLOR_ALIASES = {
    "빨간": "빨강", "붉은": "빨강", "레드": "빨강", "red": "빨강", "주황빛": "주황", "오렌지": "주황", "orange": "주황",
    "노란": "노랑", "yellow": "노랑", "녹색": "초록", "green": "초록", "파란": "파랑", "푸른": "파랑", "blue": "파랑",
    "navy": "남색", "네이비": "남색", "보랏빛": "보라", "purple": "보라", "핑크": "분홍", "pink": "분홍", "brown": "갈색",
    "밤색": "갈색", "회": "회색", "gray": "회색", "grey": "회색", "검은": "검정", "까만": "검정", "black": "검정",
    "아이보리": "미색", "ivory": "미색", "크림": "미색", "cream": "미색", "버건디": "자주", "burgundy": "자주",
    "teal": "청록", "mustard": "겨자", "하늘빛": "하늘", "skyblue": "하늘", "진초록": "짙은 초록", "짙은초록": "짙은 초록",
    "먹": "먹색", "검정색": "검정",
}


def parse_color(value: str) -> str:
    """기본 색 이름(빨강·'빨간색'·red 등) 또는 #RRGGBB → 소문자 #rrggbb. 그 밖에는 ValueError(받는 값을 알려 준다)."""
    text = (value or "").strip()
    if HEX.fullmatch(text):
        return text.lower()
    key = " ".join(text.lower().split())
    for candidate in (key, key.removesuffix("색").strip(), key.replace(" ", "")):
        name = candidate if candidate in PALETTE_BY_NAME else _COLOR_ALIASES.get(candidate)
        if name:
            return PALETTE_BY_NAME[name]
    raise ValueError(f"색 {value!r}을 알 수 없다. 기본 색 이름({'·'.join(n for n, _ in PALETTE)}) 또는 #RRGGBB(예: #b22222)로 준다")


def color_label(hex_: str) -> str:
    """'빨강(#b3261e)' 또는 '#123456'."""
    return f"{COLOR_NAMES[hex_]}({hex_})" if hex_ in COLOR_NAMES else hex_


# ---- 템플릿 ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Template:
    key: str  # 파일에 적는 이름
    name: str  # 저자에게 보이는 이름(도구 인자도 이것)
    band: str  # 책등 위쪽 띠
    fields: tuple[tuple[str, str], ...]  # (칸 이름, 예시). 칸은 작게 잡는다. 제목·내용은 모든 항목에 있다
    about: str


TEMPLATES: tuple[Template, ...] = (
    Template("blank", "빈 책", "일반", (), "제목과 내용만 적습니다."),
    Template("person", "인물", "인물", (("원어 표기", "예: Adam Smith"), ("생몰", "예: 1723–1790"), ("소속·국적", "")),
             "책에 나오는 사람"),
    Template("case", "사례", "사례", (("시기", "예: 1850년대"), ("장소", ""), ("출처", "책·기사·기관 이름")), "이야기로 쓸 사례"),
    Template("number", "수치", "수치", (("값", "예: 1,200"), ("단위", "예: 톤"), ("기준 시점", "예: 2020년"), ("출처", "자료·기관 이름")),
             "확인한 숫자와 그 출처"),
    Template("term", "용어", "용어", (("원어", ""), ("출처", "")), "책에서 쓰는 낱말과 뜻"),
)
TEMPLATE_BY_KEY = {t.key: t for t in TEMPLATES}
TEMPLATE_BY_NAME = {t.name: t for t in TEMPLATES}
TEMPLATE_NAMES = tuple(t.name for t in TEMPLATES)


def template_of(value: str) -> Template:
    """템플릿 이름(빈 책·인물·사례·수치·용어) 또는 파일의 key. 옛 이름 '빈 카테고리'도 받는다."""
    raw = (value or "").strip()
    raw = "빈 책" if raw in ("빈 카테고리", "") else raw
    t = TEMPLATE_BY_NAME.get(raw) or TEMPLATE_BY_KEY.get(raw)
    if t is None:
        raise ValueError(f"템플릿 {value!r}이 없다. {'·'.join(TEMPLATE_NAMES)} 중 하나")
    return t


# ---- 이름 규칙 --------------------------------------------------------------------------------
# #96: 생각·문체·문헌·원고는 여느 책 이름으로 쓸 수 있다(옛 기본 책도 그 이름의 책이 됐다)
# 책 이름으로 쓸 수 없는 이름. 대화에서 '수정본 올렸어'·'전체 보여 줘' 같은 말이 책 이름과 헷갈리지 않게 막는다.
# 안내에 보이는 것은 저자에게 보이는 이름(RESERVED_SHOWN)만이다. 옛 이름·코어 이름(RESERVED_HIDDEN)은 막기만 한다(용어집 규칙 #85·#87)
RESERVED_SHOWN = (
    "전체", "확인 요청", "AI 확인 요청", "결정", "수정본", "책장", "컨텍스트", "휴지통", "책",
    "프로젝트", "지도", "노드", "연결 노드", "내 서재", "게시판",
    "스크랩",  # 2026-10-09 #100-2: "스크랩 보여 줘"가 책 이름과 헷갈리지 않게. 이미 그 이름의 책은 그대로 둔다(새로 짓거나 바꿀 때만 막는다)
)
RESERVED_HIDDEN = (
    "카테고리", "받은함", "인용 체크리스트", "영감", "미해결", "이슈", "책 지도", "새 판", "서랍", "공용", "층",
    "Casper", "Melchior", "Balthasar", "idea", "style", "ref", "book",
)
RESERVED = RESERVED_SHOWN + RESERVED_HIDDEN
_NAME_CHARS = set(" ·-()&")


def name_key(name: str) -> str:
    """같은 이름인지 볼 때 쓰는 열쇠: NFC, 공백 무시, 라틴 소문자, 끝의 '카테고리'를 뗀다('사례 카테고리' = '사례')."""
    text = unicodedata.normalize("NFC", name or "").lower().replace(" ", "")
    return text.removesuffix("카테고리") or text


RESERVED_KEYS = {name_key(n) for n in RESERVED} | {"카테고리"}


def clean_name(name: str) -> str:
    """NFC, 앞뒤 공백 제거, 공백 하나로. 끝의 ' 카테고리'는 뗀다."""
    text = " ".join(unicodedata.normalize("NFC", name or "").split())
    stripped = text.removesuffix("카테고리").strip()
    return stripped or text


def check_name(name: str, taken: dict[str, str]) -> str:
    """새 이름 검사. taken: 이미 쓰는 이름의 열쇠 → 이름. 통과하면 정리한 이름, 아니면 ValueError(이유를 한국어로)."""
    clean = clean_name(name)
    if not clean:
        raise ValueError("책 이름이 비어 있습니다")
    if len(clean) > NAME_MAX:
        raise ValueError(f"책 이름은 {NAME_MAX}자까지입니다(책등에 들어가는 길이). 지금 {len(clean)}자")
    if bad := sorted({c for c in clean if not (c.isalnum() or c in _NAME_CHARS)}):
        raise ValueError(f"책 이름에 쓸 수 없는 글자가 있습니다: {' '.join(bad)} (글자·숫자·띄어쓰기·가운뎃점·하이픈·괄호만)")
    if clean.replace(" ", "").isdigit():
        raise ValueError("숫자만으로는 책 이름을 지을 수 없습니다")
    key = name_key(clean)
    if key in RESERVED_KEYS:  # 이유와 다음 행동, 쓸 수 없는 이름(2026-10-09)
        said = josa(f"'{clean}'", "은/는")
        raise ValueError(f"{said} Magus가 쓰는 말이라 책 이름으로는 쓸 수 없어요. 다른 이름을 붙여 주세요. "
                         f"(쓸 수 없는 이름: {', '.join(RESERVED_SHOWN)} 등)")
    if key in taken:
        raise ValueError(f"'{taken[key]}' 책이 이미 있습니다. 다른 이름을 지어 주세요")
    return clean


# ---- 제목 기본값 -------------------------------------------------------------------------------
TITLE_MODES = {"ask": "매번 묻기", "ai": "AI가 짓기", "none": "비워 두기"}


def clean_tags(tags: list[str] | None) -> list[str]:
    out = list(dict.fromkeys(" ".join(str(t).split())[:TAG_MAX] for t in (tags or []) if str(t).strip()))
    if len(out) > TAGS_MAX:
        raise ValueError(f"태그는 {TAGS_MAX}개까지")
    return out
