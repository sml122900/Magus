"""층(작업물)과 공용 층의 규칙(사용자 결정 #93, 2026-10-07. #92-a "카테고리는 사람 소유"를 대신한다).

- 책장은 층으로 나뉜다. 맨 위는 공용 층(사용자마다 하나, 원고 없음)이고, 그 아래로 작업물(프로젝트)마다 한 층씩이다.
  층 번호(1층, 2층…)는 위에서 아래로 매긴다. 원고 없이 제목만 있는 빈 층도 만들 수 있다(원고는 나중에 그 층으로 가져온다).
- 카테고리(기본 카테고리 생각·문체·문헌 포함)는 공용 층이나 한 작업물 층에 꽂힌다. 새 작업물 층에는 생각·문헌이 생기고,
  문체는 처음부터 공용에 있다. 기본 카테고리는 한 층에 종류마다 하나까지이고, 여러 층에 같은 종류가 있을 수 있다.
- 카테고리를 옮기면 그 안의 항목이 모두 함께 간다(항목 id·작성자·시각·제목·태그는 그대로).
  받는 층에 같은 기본 카테고리가 있으면 합치고, 저자가 만든 같은 이름의 카테고리가 있으면 옮기지 않는다(이름을 바꾼 뒤 옮긴다).
  옮긴 직후에는 한 번 되돌릴 수 있다(마지막 옮기기만).
- 문헌 한 편은 사람마다 책장에 한 권이다(key가 사람마다 하나). 작업물 층의 원고는 그 층 문헌 + 공용 문헌과 대조한다.
  두 작업물이 같은 문헌을 쓰게 되면(다른 층에 있는 문헌을 가져오거나 등록하면) 그 문헌은 공용으로 옮겨진다.

원본 파일: data/users/<user_id>/shelf/floors.json(층 순서, 층마다 꽂힌 기본 카테고리, 마지막 옮기기).
항목의 층은 각 파일의 "floor"(생각·문체 json, 문헌 bib.json, 카테고리 category.json)다.
"""

from __future__ import annotations

COMMON = "common"  # 공용 층의 id. 프로젝트 id로 쓸 수 없다
COMMON_NAME = "공용"
FLOORS_SCHEMA = 1  # floors.json 형식
MAX_FLOORS = 20  # 작업물 층 수(공용 빼고). 책장 전체 보기가 한 화면 몇 번 넘김 안에 들어오게
NEW_FLOOR_BUILTINS = ("ideas", "refs")  # 새 작업물 층에 생기는 기본 카테고리
COMMON_BUILTINS = ("styles",)  # 공용 층에 처음부터 있는 기본 카테고리
BUILTIN_ORDER = ("ideas", "styles", "refs")


def floor_label(number: int) -> str:
    """0 → 공용, n → n층."""
    return COMMON_NAME if number == 0 else f"{number}층"


def has_batchim(word: str) -> bool | None:
    """마지막 글자에 받침이 있나. 한글이 아니면 None(숫자는 읽는 소리로)."""
    if not word:
        return None
    last = word.rstrip(" )」』\"'")[-1:] or word[-1]
    if "가" <= last <= "힣":
        return (ord(last) - 0xAC00) % 28 != 0
    if last.isdigit():
        return last in "013678"  # 영·일·삼·육·칠·팔은 받침, 이·사·오·구는 없음
    return None


def josa(word: str, pair: str) -> str:
    """word + 조사. pair는 '을/를'·'이/가'·'은/는'·'으로/로'·'과/와'. 받침을 모르면 '을(를)'처럼 둘 다."""
    first, second = pair.split("/")
    batchim = has_batchim(word)
    if pair == "으로/로":
        last = word.rstrip(" )」』\"'")[-1:]
        if batchim is None:
            return f"{word}(으)로"
        rieul = ("가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 8) or last in "178"  # ㄹ 받침은 '로'(일·칠·팔)
        return word + ("로" if (not batchim or rieul) else "으로")
    if batchim is None:
        return f"{word}{first}({second})"
    return word + (first if batchim else second)
