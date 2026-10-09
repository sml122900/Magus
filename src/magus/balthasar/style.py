"""문체 책장 — Balthasar · 유향. 글에 배는 것.

#96부터 문체도 여느 책의 글이다(컨텍스트 「문체」). 이 모듈은 옛 문체 표본의 태그 키만 둔다(이전 book_migrate가 옛 파일을 읽을 때 쓴다).
옛 태그 검증·색인 문자열(validate_tags·search_text)은 시험에서만 쓰여 지웠다(2026-10-09 점검 21-b).
"""

from __future__ import annotations


TAG_KEYS = ("호흡", "시점", "열기", "장치", "어미", "톤")
LIST_KEYS = ("장치",)
