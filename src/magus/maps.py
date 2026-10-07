"""프로젝트와 마인드맵(지도)의 규칙(2026-10-08, 사용자 결정 #95. #93의 층을 대신한다).

- 구조: 프로젝트 → 지도(마인드맵) → 노드 → 책장(정면 2D) → 책 → 게시판(날짜·제목 목록).
- 프로젝트는 지금의 작업물(옛 '층')이다. 옛 공용 층은 프로젝트 「내 서재」가 됐다(원고 없음, 내부 id는 그대로 "common").
  항목 파일의 "floor"는 그 항목이 속한 프로젝트 id다(이름은 옛 형식과 맞추느라 그대로 둔다).
- 노드는 한 프로젝트에 속한다. 이름·위치(x, y)·색(선택)·책 목록. 가운데 노드는 프로젝트마다 하나이고(id "center",
  이름 = 프로젝트 제목), 원고 책을 둘 수 있는 유일한 노드다. 원고가 없어도 된다.
- 선은 같은 프로젝트의 두 노드를 잇는다(방향 없음). 새 노드는 가운데 노드와 이어서 만들고, 저자가 끊고 다시 이을 수 있다.
- 책은 노드에 꽂힌다(원고 책은 가운데에만, 문서 책은 원고가 있는 프로젝트의 아무 노드에). 기본 책(생각·문체·문헌)은
  한 프로젝트에 종류마다 하나까지다(항목의 "floor"만으로 어느 책인지 정해지게).
- 연결 노드는 다른 프로젝트의 노드를 가리킨다. 원본은 하나다: 연결 노드에서 보거나 넣으면 원본 노드에 들어간다.
  원본이 사라지면 연결 노드는 '원본 없음'으로 남는다. 연결 노드는 책을 갖지 않는다.
- 인용 점검 범위: 이 프로젝트의 문헌 책 + 연결 노드가 가리키는 노드에 꽂힌 문헌 책(store.cite_scope).
  문헌 key는 사람마다 하나라 같은 key가 두 곳에 있지 않다. 다른 프로젝트의 문헌을 이 프로젝트 원고도 쓰게 되면
  그 문헌을 「내 서재」의 문헌으로 옮기고, 두 프로젝트 지도에 그 노드로 가는 연결 노드를 붙인다(없을 때만).

원본 파일: data/users/<user_id>/shelf/maps/<프로젝트 id>.json(노드·선·책 배치). 지도 파일이 없는 프로젝트는
지금 배치에서 계산한 지도로 보인다(이전 전에도 같은 모습, store.maps).
"""

from __future__ import annotations

import re

from magus.floors import COMMON

LIBRARY = COMMON  # 「내 서재」 프로젝트의 내부 id(옛 공용 층)
LIBRARY_NAME = "내 서재"
CENTER = "center"
MAP_SCHEMA = 1
MAX_NODES = 40  # 프로젝트 하나의 노드 수(가운데·연결 노드 포함). 카테고리 30 + 기본 셋 + 가운데가 이전 때 들어가고 남게
MAX_BOOKS_PER_NODE = 12  # 노드 하나의 책 수. 옆 패널의 정면 책장 두 줄
NODE_NAME_MAX = 20
RING = 240  # 계산한 배치: 가운데에서 첫 고리까지(지도 좌표, 확대 1에서 px)
NODE_GAP = 170  # 계산한 배치: 노드 사이 최소 거리(가로로 긴 노드라 가로는 1.6배로 본다)
BOOK_NAMES = {"ideas": "생각", "styles": "문체", "refs": "문헌"}
_NODE_ID = re.compile(r"[A-Za-z0-9_\-]{1,64}")


def clean_node_name(name: str | None) -> str:
    """노드 이름: 한 줄, 앞뒤 공백 없이, NODE_NAME_MAX자까지. 비면 ValueError."""
    clean = " ".join(str(name or "").split())
    if not clean:
        raise ValueError("노드 이름을 적는다.")
    if len(clean) > NODE_NAME_MAX:
        raise ValueError(f"노드 이름은 {NODE_NAME_MAX}자까지다.")
    return clean


def name_key(name: str) -> str:
    return "".join(name.split()).lower()


def valid_node_id(node_id: str) -> bool:
    return bool(_NODE_ID.fullmatch(node_id or ""))


def global_key(floor: str, local: str) -> str:
    """지도 파일의 책 이름(ms·ideas·<카테고리 id>·doc.<id>) → 화면·옮기기에서 쓰는 책 주소 이름(ms.<프로젝트>·ideas.<프로젝트>…)."""
    if local == "ms" or local in BOOK_NAMES:
        return f"{local}.{floor}"
    return local


def local_key(key: str) -> tuple[str | None, str]:
    """책 주소 이름 → (그 이름에 들어 있는 프로젝트 id 또는 None, 지도 파일의 책 이름)."""
    base, dot, rest = key.partition(".")
    if dot and (base == "ms" or base in BOOK_NAMES):
        return rest, base
    return None, key
