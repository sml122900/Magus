"""원고 PDF 폴백. docx가 없을 때 쓴다. 코멘트는 Word가 PDF로 내보낸 말풍선 글("메모 포함[C1]: …")에서 뽑는다.

앵커 위치는 알 수 없으므로, 말풍선 바로 앞의 본문 블록을 앵커로 본다. 그림·표·수식은 구분하지 못한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from magus.book.docx_reader import Block, Comment, Manuscript

_COMMENT = re.compile(r"메모\s*포함\s*\[\s*C\s*(\d+)\s*\]\s*[:：]?\s*(.*)", re.S)


def read_pdf(path: Path) -> Manuscript:
    blocks: list[Block] = []
    comments: list[Comment] = []
    with pymupdf.open(path) as doc:
        title = (doc.metadata or {}).get("title") or None
        for page in doc:
            for block in page.get_text("blocks", sort=True):
                if block[6] != 0:  # 이미지 블록
                    continue
                text = " ".join(line.strip() for line in block[4].splitlines() if line.strip())
                if not text:
                    continue
                if m := _COMMENT.search(text):
                    before = text[: m.start()].strip()
                    if before:
                        blocks.append(Block(len(blocks), "para", before))
                    anchor_index = len(blocks) - 1 if blocks else None
                    comments.append(
                        Comment(
                            id=m.group(1),
                            author="",
                            text=m.group(2).strip(),
                            block_index=anchor_index,
                            anchor=blocks[anchor_index].text if anchor_index is not None else "",
                        )
                    )
                    continue
                blocks.append(Block(len(blocks), "para", text))
    return Manuscript(blocks, comments, title, source="pdf", notes=["코멘트는 PDF 텍스트에서 추출"])
