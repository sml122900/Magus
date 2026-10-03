"""한글 음역 표기(케인스, 넌, 마셜) ↔ 영문 참고문헌의 성(Keynes, Nunn, Marshall) 추정 연결.

참고문헌은 영문인데 본문은 "케인스(1930)"처럼 한글로 인용하는 경우가 많고, 국역 꼬리에 한글 저자명이 없으면
aliases로 이을 수 없다. 그래서 **같은 연도의 문헌 안에서만**, 자음 골격(소리 갈래)을 비교해 가장 가까운 하나를 고른다.
한국인 저자(김성은 → Kim)는 흔한 성씨 로마자 표기표로 맞춘다. 결과는 '음역 추정'으로 표시해 사람이 확인하게 한다.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# 초성 19: ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ
_INITIAL = ["K", "K", "N", "T", "T", "R", "M", "P", "P", "S", "S", "", "S", "S", "S", "K", "T", "P", ""]
# 종성 28: 없음 ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ (외래어 받침 ㅅ은 t 소리)
_FINAL = ["", "K", "K", "K", "N", "N", "N", "T", "R", "K", "M", "R", "R", "R", "P", "R", "M", "P", "P", "T", "T", "N", "T", "T", "K", "T", "P", ""]

KOREAN_SURNAMES = {
    "김": ("kim", "gim"), "이": ("lee", "yi", "rhee", "i", "ri"), "박": ("park", "pak", "bak"), "최": ("choi", "choe"),
    "정": ("jung", "jeong", "chung", "jong"), "강": ("kang", "gang"), "조": ("cho", "jo", "joe"), "윤": ("yoon", "yun"),
    "장": ("jang", "chang"), "임": ("lim", "im", "yim", "rim"), "한": ("han",), "오": ("oh", "o"), "서": ("seo", "suh"),
    "신": ("shin", "sin"), "권": ("kwon", "gwon"), "황": ("hwang",), "안": ("ahn", "an"), "송": ("song",),
    "류": ("ryu", "yoo", "yu"), "유": ("yoo", "yu", "you"), "홍": ("hong",), "전": ("jeon", "chun", "jun"),
    "고": ("ko", "go"), "문": ("moon", "mun"), "손": ("son", "sohn"), "양": ("yang",), "배": ("bae",),
    "백": ("baek", "paik", "baik"), "허": ("heo", "hur", "huh"), "남": ("nam",), "염": ("yum", "yeom"),
    "노": ("noh", "roh", "no"), "하": ("ha",), "곽": ("kwak",), "성": ("sung", "seong"), "차": ("cha",),
    "주": ("joo", "ju", "chu"), "우": ("woo", "u"), "구": ("koo", "ku", "gu"), "민": ("min",), "진": ("jin", "chin"),
}


def korean_skeleton(name: str) -> str:
    out = []
    for ch in name:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out += [_INITIAL[code // 588], _FINAL[code % 28]]
    return _collapse("".join(out))


def latin_skeleton(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z]", "", s)
    for a, b in (("sch", "s"), ("ph", "f"), ("th", "t"), ("sh", "s"), ("ch", "s"), ("ck", "k"), ("qu", "k"), ("tz", "s")):
        s = s.replace(a, b)
    s = re.sub(r"ng(?=[^aeiouy]|$)", "n", s)
    out = []
    for i, ch in enumerate(s):
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if ch in "bpfv":
            out.append("P")
        elif ch == "c":
            out.append("S" if nxt in "eiy" else "K")
        elif ch == "q":
            out.append("S" if nxt == "i" else "K")  # 병음 Qian → 첸
        elif ch in "gk":
            out.append("K")
        elif ch in "dt":
            out.append("T")
        elif ch in "szxj":
            out.append("S")
        elif ch in "lr":
            out.append("R")
        elif ch in "mn":
            out.append(ch.upper())
    return _collapse("".join(out))


def _collapse(skeleton: str) -> str:
    return re.sub(r"(.)\1+", r"\1", skeleton)


def score(hangul: str, latin_surname: str) -> float:
    """0~1. 한국인 이름(성씨표에 있는 첫 글자 + 2~3글자)은 성씨 표기가 맞으면 1."""
    latin = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", latin_surname).encode("ascii", "ignore").decode().lower())
    if 2 <= len(hangul) <= 3 and hangul[0] in KOREAN_SURNAMES and latin in KOREAN_SURNAMES[hangul[0]]:
        return 1.0
    a = korean_skeleton(hangul)
    best = 0.0
    # 독일식 W(Wolf → 볼프)는 v 소리다. w를 모음으로 본 골격과 P로 본 골격 중 나은 쪽을 쓴다.
    for variant in {latin_surname, re.sub(r"[Ww]", "v", latin_surname)}:
        b = latin_skeleton(variant)
        if a and b and a[0] == b[0]:
            best = max(best, SequenceMatcher(None, a, b).ratio())
    return best


def best_match(hangul: str, candidates: list[tuple[str, str]], threshold: float = 0.75) -> str | None:
    """candidates: (ref key, 영문 성). 점수가 문턱 이상인 가장 높은 하나. 동점이면 고르지 않는다(잘못 잇는 것보다 낫다)."""
    scored = sorted(((score(hangul, surname), key) for key, surname in candidates), reverse=True)
    if not scored or scored[0][0] < threshold:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]
