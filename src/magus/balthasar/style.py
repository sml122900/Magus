"""문체 책장 — Balthasar · 유향. 글에 배는 것.

태그는 호출자(Claude)가 구절과 이유에서 추출해 넘긴다. 서버는 스키마를 검증만 한다.
검색 대상(FTS 색인·임베딩)은 reason + tags를 이은 문자열이다. passage는 넣지 않는다.
구절을 색인하면 문체가 아니라 주제(고래, 물가…)가 검색되기 때문이다.
"""

from __future__ import annotations

from typing import Any

TAG_KEYS = ("호흡", "시점", "열기", "장치", "어미", "톤")
LIST_KEYS = ("장치",)


def validate_tags(tags: dict[str, Any]) -> dict[str, Any]:
    """스키마 {호흡, 시점, 열기, 장치: [], 어미, 톤}. 정리한 dict를 돌려주고, 어긋나면 ValueError."""
    if not isinstance(tags, dict):
        raise ValueError("tags는 객체여야 한다: {호흡, 시점, 열기, 장치: [], 어미, 톤}")
    unknown = sorted(set(tags) - set(TAG_KEYS))
    missing = [k for k in TAG_KEYS if k not in tags]
    if unknown or missing:
        raise ValueError(f"tags 키가 스키마와 다르다. 없는 키: {missing or '-'}, 모르는 키: {unknown or '-'}")
    clean: dict[str, Any] = {}
    for key in TAG_KEYS:
        value = tags[key]
        if key in LIST_KEYS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"tags.{key}는 문자열 목록이어야 한다(없으면 [])")
            clean[key] = [" ".join(v.split()) for v in value if v.strip()]
        else:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"tags.{key}는 비어 있지 않은 문자열이어야 한다")
            clean[key] = " ".join(value.split())
    return clean


def tags_text(tags: dict[str, Any]) -> str:
    return " / ".join(f"{k}: {', '.join(tags[k]) if k in LIST_KEYS else tags[k]}" for k in TAG_KEYS if k in tags)


def search_text(reason: str, tags: dict[str, Any]) -> str:
    """색인·임베딩 대상: reason + tags. passage는 일부러 뺀다."""
    return f"{reason.strip()}\n{tags_text(tags)}"
