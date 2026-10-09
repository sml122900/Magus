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


_QUOTED = re.compile(r'"([^"]*)"')


def query_parts(q: str) -> tuple[list[str], list[str]]:
    """검색어 → (따옴표로 묶은 구절들, 나머지 낱말들). 짝이 맞지 않는 따옴표는 버린다."""
    phrases = [" ".join(p.split()) for p in _QUOTED.findall(q) if p.strip()]
    return phrases, _QUOTED.sub(" ", q).replace('"', " ").split()


def search_match(q: str) -> str | None:
    """찾기용 FTS5 MATCH 식(2026-10-09). 따옴표로 묶은 구절은 그 토큰이 이어진 구절("raw 3fb7a700"), 나머지 라틴·숫자 낱말과
    한 글자 토큰은 앞부분 일치("ra"*), 한글·한자 2글자 조각은 그대로("도시"). OR로 묶어 많이 맞을수록 위(bm25).
    식에는 토큰(글자·숫자)만 큰따옴표로 묶어 넣으므로 검색어의 ( ) " * : - 같은 글자가 FTS 문법이 되지 않는다. 토큰이 없으면 None."""
    phrases, words = query_parts(q)
    parts = []
    for phrase in phrases:
        if toks := tokens(phrase):
            parts.append('"' + " ".join(toks) + '"')
    for tok in dict.fromkeys(tokens(" ".join(words))):
        parts.append(f'"{tok}"*' if tok.isascii() or len(tok) == 1 else f'"{tok}"')
    return " OR ".join(dict.fromkeys(parts)) or None


def needle_of(q: str) -> str:
    """2단계(글자 그대로 포함)에 쓸 글: 따옴표를 뗀 검색어(공백은 하나로)."""
    return " ".join(q.replace('"', " ").split())


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
