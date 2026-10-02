"""book_export: 장 md를 차례대로 합쳐 docx로 만든다(pandoc, pypandoc_binary에 내장).

부가 있으면 "# 제N부 제목" 아래 "## 제N장 제목"으로, 부가 없으면 "# 제N장 제목"으로 쓴다.
장 안의 소제목은 장 제목 아래 단계로 한 칸씩 내린다. P0에서는 코멘트·그림을 복원하지 않는다(자리표시자 그대로).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pypandoc

from magus.ids import utcnow
from magus.store import Project, Store

_HEADING = re.compile(r"^(#{1,5}) ", re.M)


def assemble_markdown(store: Store, user_id: str, project: Project) -> str:
    parts = {p.number: p.title for p in store.list_parts(user_id, project.id)}
    chapters = store.list_chapters(user_id, project.id)
    level = 2 if any(c.part_number is not None for c in chapters) else 1
    out: list[str] = []
    current_part: int | None = None
    for c in chapters:
        if c.part_number is not None and c.part_number != current_part:
            out.append(f"# 제{c.part_number}부 {parts.get(c.part_number, '')}".rstrip())
            current_part = c.part_number
        chapter = store.read_chapter(user_id, project.id, c.number)
        body = chapter.content if chapter else ""
        body = _HEADING.sub(lambda m: "#" * (len(m.group(1)) + level - 1) + " ", body)
        out += [f"{'#' * level} 제{c.number}장 {c.title}", body]
    return "\n\n".join(out) + "\n"


def export_docx(store: Store, user_id: str, project: Project, filename: str | None = None) -> str:
    markdown = assemble_markdown(store, user_id, project)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "book.docx"
        pypandoc.convert_text(
            markdown, "docx", format="markdown", outputfile=str(out), extra_args=["--metadata", f"title={project.title}"]
        )
        data = out.read_bytes()
    name = Path(filename).name if filename else f"{project.id}-{re.sub(r'[^0-9]', '', utcnow())[:14]}.docx"
    if not name.lower().endswith(".docx"):
        name += ".docx"
    return store.save_export(user_id, project.id, name, data)
