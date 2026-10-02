"""키워드 검색용 토큰화. FTS5(unicode61)에 넣기 전에 직접 토큰을 만든다.

한국어는 어절에 조사가 붙고 고유명사가 짧다("갤러", "헨릭"). trigram은 3글자 미만을 못 찾으므로,
한글·한자·가나 연속열은 2글자씩 겹쳐 자른 bigram으로, 라틴 문자와 숫자는 소문자 단어로 색인한다.
질의도 같은 방식으로 쪼개 OR로 묶는다. 일치하는 bigram이 많을수록 bm25 점수가 높아진다.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[가-힣]+|[぀-ヿ㐀-鿿]+|[A-Za-z0-9]+")


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN.finditer(text):
        word = m.group()
        if word[0].isascii():
            out.append(word.lower())
        elif len(word) == 1:
            out.append(word)
        else:
            out.extend(word[i : i + 2] for i in range(len(word) - 1))
    return out


def index_text(text: str) -> str:
    return " ".join(tokens(text))


def match_query(text: str) -> str | None:
    """FTS5 MATCH 식. 토큰이 없으면 None."""
    unique = list(dict.fromkeys(tokens(text)))
    return " OR ".join(f'"{t}"' for t in unique) if unique else None


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    """전문(full text)을 문단 경계 위주로 size 안팎의 조각으로 자른다. 긴 문단은 글자 수로 자른다."""
    pieces: list[str] = []
    current = ""
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        while len(para) > size:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(para[:size])
            para = para[size - overlap :]
        if current and len(current) + len(para) + 2 > size:
            pieces.append(current)
            current = current[-overlap:] + "\n\n" + para if overlap else para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        pieces.append(current)
    return pieces
