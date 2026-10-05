"""저자 확인 질문지(#84, `docs/decisions/author-questions.md`): 저자만 답할 수 있는 인용 질문을 책 단위로 모은다.

- 질문은 저장하지 않고 **매번 지금 원고와 문헌에서 계산한다.** 그래서 수정본을 올리면 저절로 새 판 기준이 된다.
- 판이 바뀌어도 이어지는 것은 답뿐이다(프로젝트의 `book/answers.md`, 사람이 읽는 파일). 질문 id는 종류 + key·표기로 만들어
  판이 바뀌어도 같은 질문이면 같은 id다.
- 판별은 기존 것을 그대로 쓴다: build_cite_report(연도 불일치 hint·참고문헌에만 있음·미연결), check_text의 matched_by·candidates
  (음역 추정·연도 a/b 모호), 같은 기본 key의 형제(같은 저자·연도 두 편), 참고문헌의 (연도, 제목) 겹침(중복 서지).
- 답의 반영: 표기를 문헌에 잇는 답은 alias(`refs.add_alias`, 결정 #28의 확정 경로), 사람 이름이 아니라는 답은 비인용 용어,
  Word에서 고칠 답은 결정(D번호)으로 남긴다. 어느 답이든 answers.md에 쌓인다.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from magus.ids import utcnow
from magus.melchior.author_report import chapters_text, cite_label, name_mentions, surnames
from magus.melchior.check import Resolver, after_refs_changed, check_text, terms_of
from magus.melchior.refs import add_alias
from magus.melchior.report import build_cite_report
from magus.melchior.translit import score
from magus.store import Ref, Store

TYPES = {
    "year": "연도 불일치", "bibonly": "참고문헌에만 있음", "translit": "한글 표기 추정", "ab": "연도 a/b 모호",
    "pair": "같은 저자·연도 두 편", "unlinked": "미연결 표기", "dup": "중복 서지",
}
# 답의 종류: apply = 서버가 바로 반영(alias·비인용 용어), wait = 저자가 Word에서 고칠 것(결정으로 남김), done = 그대로 둠
WAIT = {"fix_text", "add_ref", "cite", "drop", "change"}


@dataclass
class Question:
    id: str
    type: str
    chapters: list[str]
    text: str  # 저자에게 보일 질문 한 줄(key 없이 저자(연도) 『제목』)
    options: list[tuple[str, str]]  # (choice, 설명)
    surface: str = ""  # 원고 표기(표기를 문헌에 잇는 답에서 alias로 쓴다)
    state: str = "open"  # open | waiting(답함·원고 반영 대기) | answered(답함)
    answer: dict[str, str] = field(default_factory=dict)


def _surface_key(surface: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣一-鿿]", "", unicodedata.normalize("NFC", surface))


def _base(key: str) -> str:
    return re.sub(r"(-\d+)$", "", key)


def build_questions(store: Store, user_id: str, project_id: str) -> list[Question]:
    """지금 원고·문헌에서 질문을 계산하고, answers.md의 답으로 상태를 붙인다."""
    report = build_cite_report(store, user_id, project_id)
    refs = {r.key: r for r in store.list_refs(user_id)}
    resolver, terms = Resolver(store, user_id), terms_of(store, user_id, project_id)
    inferred: dict[tuple[str, str], list[str]] = defaultdict(list)  # (표기, key) → 장
    ambiguous: dict[str, tuple[list[str], list[str], set[str]]] = {}  # 모호 key → (후보, 장, 표기)
    linked: dict[str, list[str]] = defaultdict(list)  # 형제가 있는 key → 장
    texts: list[tuple[str, str]] = []
    for meta in store.list_chapters(user_id, project_id):
        chapter = store.read_chapter(user_id, project_id, meta.number)
        if chapter is None:
            continue
        texts.append((meta.display, chapter.content))
        for g in check_text(store, user_id, chapter.content, resolver, terms).groups:
            if g.candidates:
                cands, where, shown = ambiguous.setdefault(g.key, ([k for k, _ in g.candidates], [], set()))
                where.append(meta.display)
                shown.update(c for _, c in g.occurrences)
            elif "음역 추정" in g.matched_by:
                for _, surface in g.occurrences:
                    inferred[(surface, g.key)].append(meta.display)
            if g.status != "uncertain" and (re.search(r"-\d+$", g.key) or any(k.startswith(g.key + "-") for k in refs)):
                linked[g.key].append(meta.display)

    def label(key: str) -> str:
        return cite_label(refs.get(key), key)

    def where(chapters: list[str]) -> str:
        return chapters_text(dict.fromkeys(chapters)) or "장 밖"

    out: list[Question] = []
    for d in sorted(report.of("unknown"), key=lambda d: d.key):
        if not d.hint:  # 같은 저자의 다른 해 문헌이 없으면 질문이 아니라 미확인 문헌이다
            continue
        similar = " / ".join(label(k) for k in d.hint.split(", ") if k in refs)
        out.append(Question(
            f"year:{d.key}", "year", d.chapters,
            f"{where(d.chapters)} 본문 {', '.join(sorted(d.cited_as))} ↔ 참고문헌 {similar}. 연도가 다릅니다.",
            [("fix_text", "본문 연도를 고침(Word에서)"), ("add_ref", "참고문헌에 넣음(Word에서)"), ("other", "다른 문헌(그대로)")]))
    hinted = {k for d in report.of("unknown") for k in d.hint.split(", ") if k}  # 연도 불일치 질문이 이미 가리키는 문헌
    for key, _raw in report.uncited:
        if key in hinted:
            continue
        ref = refs.get(key)
        shown, at = name_mentions(texts, ref) if ref else ([], [])
        mention = f" 본문에는 이름만 나옵니다: '{', '.join(shown)}'({where(at)})." if at else " 본문에서 이름도 찾지 못했습니다."
        out.append(Question(
            f"bibonly:{key}", "bibonly", at, f"참고문헌에만 있는 {label(key)}.{mention}",
            [("cite", "인용을 넣음(Word에서)"), ("drop", "목록에서 뺌(Word에서)"), ("keep", "그대로 둠")]))
    for (surface, key), chapters in sorted(inferred.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        out.append(Question(
            f"translit:{_surface_key(surface)}>{key}", "translit", chapters,
            f"{where(chapters)} {surface} → {label(key)}로 추정해 이었습니다. 맞나요?",
            [("yes", "맞다"), ("ref:<key>", "다른 문헌(그 key)"), ("none", "참고문헌에 없음")], surface))
    for key, (cands, chapters, shown) in sorted(ambiguous.items()):
        out.append(Question(
            f"ab:{key}", "ab", chapters, f"{where(chapters)} {', '.join(sorted(shown))}: 어느 문헌인가요?",
            [(f"ref:{k}", label(k)) for k in cands], sorted(shown)[0]))
    for base in sorted({_base(k) for k in linked}):
        works = [k for k in refs if k == base or re.fullmatch(rf"{re.escape(base)}-\d+", k)]
        if len(works) < 2:
            continue
        first = refs[works[0]].bib
        pairs = ", ".join(f"{where(linked[k]) if k in linked else '인용 없음'}은 {cite_label(refs[k], k, all_authors=True)}"
                          for k in sorted(works, key=lambda k: linked.get(k, ["~"])[0]))
        chapters = [c for k in works for c in linked.get(k, [])]
        out.append(Question(
            f"pair:{base}", "pair", chapters,
            f"참고문헌에 {first.get('first_author')}({first.get('year')}) 문헌이 {len(works)}편 있습니다. 본문의 공저자 이름으로 {pairs}로 이었습니다. 맞나요?",
            [("yes", "맞다"), ("change", "바꿔야 함(Word에서)")]))
    for d in sorted(report.of("uncertain"), key=lambda d: d.key):
        year = m.group() if (m := re.search(r"\d{4}", d.key)) else ""
        name = re.sub(r"\d{4}[a-z]?", "", d.key)
        scored = sorted(((score(name, (surnames(str(r.bib.get("authors", ""))) or [str(r.bib.get("first_author", ""))])[0]), r.key)
                         for r in refs.values() if year and str(r.bib.get("year", ""))[:4] == year), reverse=True)
        cands = [k for s, k in scored if s >= 0.5][:3]
        out.append(Question(
            f"unlinked:{d.key}", "unlinked", d.chapters,
            f"{where(d.chapters)} {', '.join(sorted(d.cited_as))}: 참고문헌의 어느 문헌인가요?",
            [*((f"ref:{k}", label(k)) for k in cands), ("not_person", "사람 이름이 아님"), ("none", "참고문헌에 없음")],
            sorted(d.cited_as)[0] if d.cited_as else d.key))
    for keys in _duplicates(list(refs.values())):
        out.append(Question(
            f"dup:{'='.join(keys)}", "dup", [],
            f"참고문헌에 같은 문헌이 {len(keys)}번 있습니다: " + " / ".join(label(k) for k in keys) + ".",
            [*((f"drop:{k}", "이것을 뺌(Word에서)") for k in keys), ("keep", "둘 다 맞다(다른 문헌)")]))
    answers = latest_answers(store, user_id, project_id)
    for q in out:
        if q.id in answers:
            q.answer = answers[q.id]
            kind = q.answer.get("choice", "").split(":")[0]
            # 서버가 바로 반영하는 답(alias·비인용 용어)을 했는데도 질문이 남아 있으면 다시 연다(반영이 안 된 것)
            applied = q.type in ("translit", "ab", "unlinked") and kind in ("yes", "ref", "not_person")
            q.state = "waiting" if kind in WAIT else "open" if applied else "answered"
    return out


def _duplicates(refs: list[Ref]) -> list[list[str]]:
    """(첫 저자, 연도, 제목)이 같은 참고문헌 묶음. 올릴 때만 리포트하던 중복 서지를 언제든 다시 계산한다."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in refs:
        title = re.sub(r"[^0-9a-z가-힣]+", "", str(r.bib.get("title", "")).lower())
        if len(re.sub(r"[0-9]", "", title)) >= 4 and not r.key.startswith("raw-"):  # 제목을 못 읽은 줄('(2013')은 빼고
            groups[(str(r.bib.get("year", ""))[:4], title)].append(r.key)
    return [sorted(keys) for keys in groups.values() if len(keys) > 1]


# ---- 답(book/answers.md) ----------------------------------------------------------------------

_HEAD = re.compile(r"^## Q (\S+) · (\S+)\s*$")


def parse_answers(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in text.splitlines():
        if m := _HEAD.match(line):
            out.append({"id": m.group(1), "at": m.group(2), "note": ""})
        elif out and (meta := re.match(r"^- (choice|applied|decision): (.*)$", line)) and not out[-1]["note"]:
            out[-1][meta.group(1)] = meta.group(2).strip()
        elif out and line.strip():
            out[-1]["note"] = (out[-1]["note"] + "\n" + line).strip()
    return out


def dump_answer(answer: dict[str, str]) -> str:
    lines = [f"## Q {answer['id']} · {answer['at']}"]
    lines += [f"- {k}: {answer[k]}" for k in ("choice", "applied", "decision") if answer.get(k)]
    return "\n".join(lines) + ("\n\n" + answer["note"] if answer.get("note") else "") + "\n\n"


def latest_answers(store: Store, user_id: str, project_id: str) -> dict[str, dict[str, str]]:
    return {a["id"]: a for a in parse_answers(store.get_answers(user_id, project_id))}


def answer_question(store: Store, user_id: str, project_id: str, question: Question, choice: str, note: str) -> dict[str, str]:
    """답을 반영하고 answers.md에 남긴다. 반영한 내용(applied·decision)을 돌려준다. 잘못된 선택은 ValueError."""
    codes = {c for c, _ in question.options}
    kind = choice.split(":")[0]
    if not (choice in codes or (kind == "ref" and "ref:<key>" in codes)):
        raise ValueError(f"선택지가 아니다: {choice!r}. 이 질문의 선택지: {', '.join(sorted(codes))}")
    applied, decision = "", ""
    if question.type in ("translit", "ab", "unlinked") and kind in ("yes", "ref"):
        key = choice[4:] if kind == "ref" else question.id.split(">")[1]
        if store.get_ref(user_id, key) is None:
            raise ValueError(f"문헌 {key}가 없다")
        ref, alias = add_alias(store, user_id, key, question.surface)
        after_refs_changed(store, user_id)
        applied = f"alias {ref.key} ← {alias}"
    elif kind == "not_person":
        term = re.sub(r"\d{4}[a-z]?$", "", question.id.split(":", 1)[1])
        terms = store.get_non_citation_terms(user_id, project_id)
        store.set_non_citation_terms(user_id, project_id, [*terms, term])
        after_refs_changed(store, user_id)
        applied = f"비인용 용어 {term}"
    if kind in WAIT:
        label = dict(question.options).get(choice, choice)
        made = store.add_decision(user_id, project_id, f"[질문 {question.id}] {question.text} → {label}" + (f" {note}" if note else ""))
        decision = f"D{made.id}"
    record = {"id": question.id, "at": utcnow(), "choice": choice, "applied": applied, "decision": decision, "note": note.strip()}
    store.add_answer(user_id, project_id, dump_answer(record))
    return record
