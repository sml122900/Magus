"""저자용 인용 점검 보고서(`magus author-report`). 독자는 개발자가 아니다.

- ref key 대신 "저자(연도) 『제목』"으로 쓴다. 설명은 한두 문장, 전체 3쪽 이내.
- 대상 사용자·프로젝트의 데이터만 쓴다(합성·데모 데이터는 다른 사용자에 있으므로 섞이지 않는다).
- markdown과, 같은 내용의 docx(pandoc, 본문 10pt 맑은 고딕)를 만든다.
"""

from __future__ import annotations

import re
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from magus.melchior.check import Resolver, check_text, terms_of
from magus.melchior.report import build_cite_report
from magus.melchior.translit import KOREAN_SURNAMES, korean_skeleton, latin_skeleton, score
from magus.store import Ref, Store
from magus.store.formats import one_line

MARKER_PREFIX = re.compile(r"^\s*(?:인용\s*)?확인\s*(?:할\s*)?필요\s*[:：]\s*")
_PARTICLE_TAIL = ("라는", "에게", "의", "가", "는", "은", "이", "와", "과", "을", "를", "도", "로")
# 이름(존, 리처드)이 아니라 문장 성분으로 끝나는 낱말: 조사·어미
_NOT_GIVEN_END = tuple("이가은는을를의에도로와과고며서다한된던할인적들게지면")


def surnames(authors: str) -> list[str]:
    """'Acemoglu, D., Johnson, S., & Robinson, J. A' → [Acemoglu, Johnson, Robinson]."""
    return re.findall(r"(?:^|&\s*|\.,\s*)([^,&]+?),\s*[A-Z]", authors)


def short_title(title: str, limit: int = 56) -> str:
    """부제와 서지 파싱 잔여물(', Vol' '(pp')을 덜어 낸 짧은 제목."""
    title = re.sub(r"(?<=[?!])\s+In\s.*$", "", one_line(title))
    title = re.sub(r",?\s*\(?(?:Vol|pp)\.?$", "", title).strip()
    if ":" in title and len(title.split(":")[0]) >= 12:
        title = title.split(":")[0]
    if len(title) > limit:
        title = title[: title.rfind(" ", 0, limit)] + "…"
    return title


def cite_label(ref: Ref | None, key: str = "", all_authors: bool = False) -> str:
    """저자(연도) 『제목』. 공저자가 있으면 '외'(all_authors면 성을 모두 '·'로)."""
    if ref is None:
        return key
    bib = ref.bib
    author = str(bib.get("first_author") or key)
    names = surnames(str(bib.get("authors", "")))
    if len(names) > 1:
        author = "·".join(names) if all_authors else f"{author} 외"
    title = short_title(str(bib.get("title", "")))
    return f"{author}({bib.get('year', '')}) 『{title}』" if title else f"{author}({bib.get('year', '')})"


def chapters_text(labels: Iterable[str]) -> str:
    """['15', '32'] → '제15·32장', ['15', '부록 2'] → '제15장, 부록 2', ['제35장'] → '제35장'. 같은 장이 여러 번 와도 한 번만."""
    nums, others = [], []
    for label in dict.fromkeys(labels):
        if m := re.fullmatch(r"제?(\d+)장?", label):
            nums.append(m.group(1))
        else:
            others.append(label)
    return ", ".join(([f"제{'·'.join(nums)}장"] if nums else []) + others)


@lru_cache(maxsize=65536)
def _score(word: str, surname: str) -> float:
    return score(word, surname)


def _lead(word: str) -> str:
    """첫 음절의 첫소리 골격(받침 제외). 존 → S, 리처드 → R, 훨씬 → ''."""
    code = ord(word[0]) - 0xAC00
    return korean_skeleton(chr(0xAC00 + code // 588 * 588)) if 0 <= code < 11172 else ""


def _stems(word: str) -> list[str]:
    return [word, *(word[: -len(p)] for p in _PARTICLE_TAIL if word.endswith(p) and len(word) > len(p))]


def name_mentions(chapters: list[tuple[str, str]], ref: Ref) -> tuple[list[str], list[str]]:
    """연도 없이 이름만 나오는 곳 → (표기들, 장들). 음역은 낱말만으로는 오탐이 많아('그런데' ≈ Graunt)
    확실한 자리만 본다: 이니셜이 맞는 이름 뒤(존 그랜트), 괄호 속(래티모어, …), 공저자와 가운뎃점(노드하우스·토빈),
    연도가 따라오지 않는 영문 성."""
    authors = str(ref.bib.get("authors", ""))
    names = surnames(authors) or [str(ref.bib.get("first_author", ""))]
    surname, partner = names[0], (names[1] if len(names) > 1 else "")
    initial = re.search(r",\s*([A-Z])", authors)
    given = latin_skeleton(initial.group(1))[:1] if initial else ""
    sound, lead = latin_skeleton(surname), latin_skeleton(surname)[:1]
    # 한국인 성명(성씨표의 첫 글자 + 두세 글자)은 성씨 표기만 맞아도 점수가 1이 된다(이상호 ≈ Lee). 저자가 한국 이름처럼
    # 보이지 않으면(이름 머리글자에 하이픈이 없으면) 그런 낱말은 이름 언급으로 보지 않는다.
    korean_author = bool(re.search(r",\s*[A-Z][a-z]*\.?-[A-Za-z]", authors))
    shown: dict[str, None] = {}
    where: list[str] = []
    for label, text in chapters:
        found = ""
        if m := re.search(rf"\b{re.escape(surname)}\b(?![^()]{{0,15}}\d{{4}})", text):
            found = m.group()
        words = list(re.finditer(r"[가-힣]+", text))
        for i, m in enumerate(words):
            if found:
                break
            prev = words[i - 1] if i else None
            named = (  # 앞 낱말이 이니셜이 맞는 이름처럼 보인다(존 그랜트, 리처드 리)
                prev is not None and text[prev.end() : m.start()] == " " and len(prev.group()) <= 3
                and not prev.group().endswith(_NOT_GIVEN_END) and bool(given) and _lead(prev.group()) == given
            )
            nxt = words[i + 1].group() if i + 1 < len(words) else ""
            for stem in _stems(m.group()):
                if not korean_author and len(stem) == 3 and stem[0] in KOREAN_SURNAMES:
                    continue
                before = text[m.start() - 1 : m.start()]
                after = text[m.start() + len(stem) : m.start() + len(stem) + 1]
                s = _score(stem, surname)
                if named and korean_skeleton(stem) == sound and _lead(stem) == lead and not stem.endswith("다"):
                    found = f"{prev.group()} {stem}"
                elif s >= 0.85 and before == "(" and after in (",", ")"):
                    found = stem
                elif s >= 0.85 and after == "·" and partner and any(_score(t, partner) >= 0.85 for t in _stems(nxt)):
                    found = f"{stem}·{_stems(nxt)[-1]}"
                if found:
                    break
        if found:
            shown[found] = None
            where.append(label)
    return list(shown)[:2], where


def build_author_report(store: Store, user_id: str, project_id: str, date: str) -> str:
    project = store.get_project(user_id, project_id)
    if project is None:
        raise ValueError(f"프로젝트 {project_id!r}가 없다")
    report = build_cite_report(store, user_id, project_id)
    refs = {r.key: r for r in store.list_refs(user_id)}
    unchecked = report.of("unverified", "unknown")
    occurrences = sum(d.count for d in report.docs.values() if d.status in ("unverified", "unknown", "verified"))
    verified = len(report.of("verified"))

    # 추정 연결과 동명 판별을 장 단위로 다시 모은다(어느 장의 어떤 표기인지 보여 주려고)
    resolver, terms = Resolver(store, user_id), terms_of(store, user_id, project_id)
    inferred: dict[tuple[str, str], list[str]] = defaultdict(list)  # (표기, ref key) → 장
    same_author: dict[str, list[str]] = defaultdict(list)  # ref key → 장
    ambiguous: dict[str, list[str]] = {}  # 연도 a/b 모호로 잇지 않은 것 → 후보 key
    texts: list[tuple[str, str]] = []
    for meta in store.list_chapters(user_id, project_id):
        chapter = store.read_chapter(user_id, project_id, meta.number)
        if chapter is None:
            continue
        texts.append((meta.display, chapter.content))
        for g in check_text(store, user_id, chapter.content, resolver, terms).groups:
            for _, surface in g.occurrences:
                if g.matched_by not in ("", "alias"):
                    inferred[(surface, g.key)].append(meta.display)
            if g.candidates:
                ambiguous[g.key] = [k for k, _ in g.candidates]
            if re.search(r"-\d+$", g.key) or any(k.startswith(g.key + "-") for k in refs):
                same_author[g.key].append(meta.display)

    lines = [
        f"# 『{project.title}』 인용 점검 보고서",
        f"{date} · Magus가 원고 전체를 읽고 정리했습니다.",
        "",
        "## 1. 한 줄 요약",
        f"원고 전체 인용 **{occurrences}곳**, 문헌 **{len(report.docs) - len(report.of('uncertain'))}편**, "
        f"원문 대조 완료 **{verified}편**입니다.",
        "",
        "## 2. 바로 확인할 것",
        f"**연도가 맞지 않는 {len(report.of('unknown'))}건.** 본문 연도의 문헌이 참고문헌에 없고, 같은 저자의 다른 해 문헌만 있습니다. "
        "연도를 잘못 적었는지, 참고문헌에서 빠졌는지 확인해 주세요.",
    ]
    for d in sorted(report.of("unknown"), key=lambda d: d.key):
        similar = [refs[k] for k in d.hint.split(", ") if k in refs]
        listed = " / ".join(cite_label(r) for r in similar) or "같은 저자 없음"
        lines.append(f"- {chapters_text(d.chapters)} 본문 {', '.join(sorted(d.cited_as))} ↔ 참고문헌 {listed}")
    lines += [
        "",
        f"**참고문헌에만 있는 {len(report.uncited)}건.** 본문에 연도와 함께 인용된 곳이 없습니다. "
        "인용을 넣을지, 목록에서 뺄지 정해 주세요.",
    ]
    for key, _ in report.uncited:
        ref = refs.get(key)
        shown, where = name_mentions(texts, ref) if ref else ([], [])
        note = f" — 본문에는 이름만 나옵니다: '{', '.join(shown)}'({chapters_text(where)})" if where else " — 본문에서 이름도 찾지 못했습니다"
        lines.append(f"- {cite_label(ref, key)}{note}")

    lines += ["", "## 3. 답해 주실 질문", "본문의 한글 표기를 참고문헌의 영문 문헌으로 추정해 이었습니다. 맞는지 알려 주세요."]
    for (surface, key), chapters in sorted(inferred.items(), key=lambda kv: kv[0][1]):
        ref = refs.get(key)
        if key in ambiguous:
            options = ", ".join(cite_label(refs.get(k), k) for k in ambiguous[key])
            lines.append(f"- {chapters_text(chapters)} {surface}: {options} 중 어느 것인가요?")
        else:
            lines.append(f"- {chapters_text(chapters)} {surface} → {cite_label(ref, key)} 맞나요?")
    for base in sorted({re.sub(r"-\d+$", "", k) for k in same_author}):
        works = [k for k in refs if k == base or re.fullmatch(rf"{re.escape(base)}-\d+", k)]
        if len(works) > 1:
            first = refs[works[0]].bib
            pairs = ", ".join(
                f"{chapters_text(same_author[k]) if k in same_author else '인용 없음'}은 {cite_label(refs[k], k, all_authors=True)}"
                for k in sorted(works, key=lambda k: same_author.get(k, ["~"])[0])
            )
            lines.append(
                f"- 참고문헌에 {first.get('first_author')}({first.get('year')}) 문헌이 {len(works)}편 있습니다. "
                f"본문의 공저자 이름으로 {pairs}로 이었습니다. 맞나요?"
            )

    lines += ["", "## 4. 확인을 시작할 순서", "가장 많이 인용된 문헌부터 원문을 확인하시면 한 번에 여러 곳이 해결됩니다.", ""]
    ranked = sorted(unchecked, key=lambda d: (-d.count, -len(d.chapters), d.key))[:20]
    lines += [
        f"{n}. {cite_label(refs.get(d.key), d.key)} — {d.count}곳({chapters_text(d.chapters)})"
        for n, d in enumerate(ranked, 1)
    ]

    facts: dict[str, list[str]] = defaultdict(list)
    chapter_names = {m.number: m.display for m in store.list_chapters(user_id, project_id)}
    fact_issues = store.list_issues(user_id, project_id, "open", kind="fact")
    for issue in fact_issues:
        comment = issue.text.split("\n— 원문:")[0]
        head = one_line(MARKER_PREFIX.sub("", comment))
        head = head if len(head) <= 40 else head[:40] + "…"
        facts[chapter_names.get(issue.chapter_number, "장 밖")].append(f"{head} (I{issue.id}{', AI' if issue.by_ai else ''})")
    by_ai = [i for i in fact_issues if i.by_ai]
    ai_names = "·".join(sorted({i.author for i in by_ai if i.author})) or "AI"
    lines += [
        "",
        f"## 5. 사실·수치 확인 요청 {len(fact_issues)}건",
        "특정 문헌이 아니라 사실이나 수치를 확인해 달라는 원고 메모입니다. 장별로 모아 앞 40자만 옮겼습니다. "
        "괄호 속 번호(I3 등)로 말씀하시면 해당 메모를 바로 찾습니다.",
        *([f"이 중 {len(by_ai)}건은 {ai_names}(AI)가 원고에 단 확인 요청입니다(괄호 속 'AI')."] if by_ai else []),
        "",
    ]
    order = {m.display: n for n, m in enumerate(store.list_chapters(user_id, project_id))}  # 읽는 순서
    for name in sorted(facts, key=lambda n: order.get(n, 999)):
        lines.append(f"- **{name}**: " + " / ".join(facts[name]))

    lines += ["", "## 6. 장별 미확인 문헌 수", "", "| 장 | 편 | 장 | 편 | 장 | 편 | 장 | 편 |", "|---|---:|---|---:|---|---:|---|---:|"]
    cells = [(d, u) for d, _, u, _, _ in report.per_chapter]
    for i in range(0, len(cells), 4):
        row = cells[i : i + 4] + [("", "")] * (4 - len(cells[i : i + 4]))
        lines.append("| " + " | ".join(f"{d} | {u}" for d, u in row) + " |")

    lines += [
        "",
        "## 7. 앞으로의 방식",
        "- 논문 원문을 올리고 쓸 부분과 그 이유를 말씀하시면 '확인 완료'로 바뀝니다.",
        "- 확인된 문헌만 글에 인용됩니다. 확인 전인 문헌은 [출처 필요]로 표시됩니다.",
        "- 새 대화를 열어도 목차와 결정이 그대로 유지됩니다.",
    ]
    return "\n".join(lines) + "\n"


def write_docx(markdown: str, out: Path) -> Path:
    """같은 내용의 docx. 본문 10pt 맑은 고딕, 여백 2cm(3쪽 이내를 위해)."""
    import subprocess

    import docx
    import pypandoc
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    with tempfile.TemporaryDirectory() as tmp:
        reference = Path(tmp) / "reference.docx"
        data = subprocess.run(
            [pypandoc.get_pandoc_path(), "--print-default-data-file", "reference.docx"], capture_output=True, check=True
        ).stdout
        reference.write_bytes(data)
        doc = docx.Document(str(reference))
        sizes = [("Normal", 10), ("Body Text", 10), ("First Paragraph", 10), ("Compact", 10),
                 ("Title", 18), ("Heading 1", 15), ("Heading 2", 12.5)]
        for name, size in sizes:
            try:
                style = doc.styles[name]
            except KeyError:
                continue
            style.font.size = Pt(size)
            style.font.name = "맑은 고딕"
            style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "맑은 고딕")
            if name not in ("Title", "Heading 1", "Heading 2"):
                style.paragraph_format.space_after = Pt(3)
        for section in doc.sections:
            section.left_margin = section.right_margin = Cm(2)
            section.top_margin = section.bottom_margin = Cm(1.8)
        doc.save(str(reference))
        out.parent.mkdir(parents=True, exist_ok=True)
        pypandoc.convert_text(markdown, "docx", format="markdown", outputfile=str(out), extra_args=[f"--reference-doc={reference}"])
    return out
