"""원본 파일 형식: 사람이 읽고 고칠 수 있어야 하고, 파싱으로 인덱스를 다시 만들 수 있어야 한다."""

from __future__ import annotations

import re

from magus.store.base import Decision, Issue

# ---- ch-NN.md: front matter + 본문 -------------------------------------------------

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


def one_line(text: str) -> str:
    return " ".join(text.split())


def dump_chapter(meta: dict[str, object], body: str) -> str:
    lines = [f"{k}: {one_line(str(v))}" for k, v in meta.items() if v is not None and v != ""]
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body.strip() + "\n"


def strip_front_matter(text: str) -> tuple[str, bool]:
    """(본문, front matter가 있었는지). 도구 경계에서 호출자가 보낸 front matter를 벗겨 낼 때 쓴다."""
    m = _FM.match(text)
    return (text[m.end() :].strip(), True) if m else (text.strip(), False)


def parse_chapter(text: str) -> tuple[dict[str, str], str]:
    m = _FM.match(text)
    if not m:
        return {}, text.strip()
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, text[m.end() :].strip()


# ---- decisions.md -------------------------------------------------------------------

_DECISION = re.compile(r"^## D(\d+) · (\S+)[ \t]*$", re.M)


def dump_decisions(decisions: list[Decision]) -> str:
    out = ["# 결정\n"]
    for d in sorted(decisions, key=lambda d: d.id):
        out.append(f"## D{d.id} · {d.created_at}\n\n{d.text.strip()}\n")
    return "\n".join(out)


def parse_decisions(text: str) -> list[Decision]:
    heads = list(_DECISION.finditer(text))
    return [
        Decision(
            id=int(h.group(1)),
            created_at=h.group(2),
            text=text[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip(),
        )
        for i, h in enumerate(heads)
    ]


# ---- issues.md ----------------------------------------------------------------------

_ISSUE = re.compile(r"^## I(\d+) · (open|closed)[ \t]*$", re.M)
_META = re.compile(r"^- (\w+): (.*)$")


def dump_issues(issues: list[Issue]) -> str:
    out = ["# 미해결\n"]
    for i in sorted(issues, key=lambda i: i.id):
        meta = [f"- created_at: {i.created_at}", f"- origin: {i.origin}", f"- kind: {i.kind}"]
        if i.chapter_number is not None:
            meta.append(f"- chapter: {i.chapter_number}")
        if i.ref_key:
            meta.append(f"- ref_key: {i.ref_key}")
        if i.ref_id:
            meta.append(f"- ref_id: {i.ref_id}")
        if i.author:
            meta.append(f"- author: {one_line(i.author)}")
        if i.author_kind:
            meta.append(f"- author_kind: {i.author_kind}")
        if i.comment_date:
            meta.append(f"- comment_date: {i.comment_date}")
        if i.paragraph is not None:
            meta.append(f"- paragraph: {i.paragraph}")
        if i.anchor:
            meta.append(f"- anchor: {one_line(i.anchor)}")
        if i.closed_note:
            meta.append(f"- closed_note: {one_line(i.closed_note)}")
        out.append(f"## I{i.id} · {i.status}\n" + "\n".join(meta) + f"\n\n{i.text.strip()}\n")
    return "\n".join(out)


def parse_issues(text: str) -> list[Issue]:
    heads = list(_ISSUE.finditer(text))
    issues = []
    for n, h in enumerate(heads):
        section = text[h.end() : heads[n + 1].start() if n + 1 < len(heads) else len(text)].strip("\r\n")
        lines = section.splitlines()
        meta: dict[str, str] = {}
        while lines and (m := _META.match(lines[0])):
            meta[m.group(1)] = m.group(2).strip()
            lines.pop(0)
        chapter = meta.get("chapter")
        issues.append(
            Issue(
                id=int(h.group(1)),
                status=h.group(2),  # type: ignore[arg-type]
                origin=meta.get("origin", "user"),  # type: ignore[arg-type]
                chapter_number=int(chapter) if chapter and chapter.isdigit() else None,
                created_at=meta.get("created_at", ""),
                closed_note=meta.get("closed_note"),
                kind=meta.get("kind") if meta.get("kind") in ("citation", "fact") else "general",  # type: ignore[arg-type]
                ref_key=meta.get("ref_key") or None,
                ref_id=meta.get("ref_id") or None,
                author=meta.get("author") or None,
                author_kind=meta.get("author_kind") if meta.get("author_kind") in ("ai", "person") else None,  # type: ignore[arg-type]
                comment_date=meta.get("comment_date") or None,
                anchor=meta.get("anchor") or None,
                paragraph=int(meta["paragraph"]) if meta.get("paragraph", "").isdigit() else None,
                text="\n".join(lines).strip(),
            )
        )
    return issues
