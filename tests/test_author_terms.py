"""저자에게 보이는 글에 옛 이름·내부 이름이 남지 않았는지(#85·#87).

Claude는 도구 설명·도구 응답·서버 instructions에 있는 말을 저자에게 그대로 옮긴다. 그래서 이 세 곳 모두에서
코어 이름(Casper·Melchior·Balthasar)과 옛 이름('영감'·'책 지도'·'미해결'·'이슈'·'새 판')을 찾는다.
'책장'은 용어집 이름이 됐다(#92: 생각·문체·문헌과 카테고리를 모아 보는 화면).
예외는 instructions 규칙 7의 "이런 말은 쓰지 않는다" 문장(AVOID) 하나뿐이다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from mcp import Client

from magus.config import Settings
from magus.instructions import AVOID
from magus.server import build_server
from magus.store import LocalStore

pytestmark = pytest.mark.anyio

FORBIDDEN = re.compile(r"Casper|Melchior|Balthasar|영감|책 지도|미해결|이슈|새 판")
SYNTH = Path(__file__).parent / "fixtures" / "synthetic"
TAGS = {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": [], "어미": "-다", "톤": "건조"}


def _hits(text: str) -> list[str]:
    return [text[max(0, m.start() - 30): m.end() + 30] for m in FORBIDDEN.finditer(text)]


async def test_author_facing_text_has_no_old_or_core_names(settings: Settings, store: LocalStore):
    user = settings.user_id
    store.put_inbox(user, "원고.docx", (SYNTH / "닿으려는_종_합성.docx").read_bytes())
    store.put_inbox(user, "대화.md", (SYNTH / "대화_전체_기록.md").read_bytes())
    seen: dict[str, str] = {}
    async with Client(build_server(settings, store)) as c:
        assert not _hits(c.instructions.replace(AVOID, "")), _hits(c.instructions.replace(AVOID, ""))
        assert c.instructions.count(AVOID) == 1
        tools = (await c.list_tools()).tools
        assert len(tools) == 29  # #94: 문서 책 하나 더하고 지우기 둘을 category_trash로 합쳤다
        for tool in tools:
            seen[f"설명 {tool.name}"] = f"{tool.description}\n{json.dumps(tool.input_schema, ensure_ascii=False)}"

        async def call(name: str, args: dict, label: str = "") -> str:
            result = await c.call_tool(name, args)
            text = "\n".join(block.text for block in result.content)
            seen[f"응답 {label or name}"] = text
            return text

        await call("book_import", {"path": "원고.docx", "project_id": "synth"})
        await call("book_import", {"path": "원고.docx", "new_edition": True}, "book_import 오류(project_id 없음)")
        await call("book_import", {"path": "원고.docx", "project_id": "synth", "new_edition": True}, "book_import 수정본")
        await call("book_outline", {})
        await call("book_issues", {"status": "all", "limit": 200})
        await call("book_read_chapter", {"number": 1})
        await call("book_write_chapter", {"number": 1, "content": "물고기가 올라왔다(Clack, 2012).", "note": "시험"})
        await call("book_decide", {"text": "서장은 장면으로 연다"})
        added = await call("book_issue_add", {"text": "수치 확인", "chapter_number": 1})
        await call("book_issue_close", {"id": added.split()[0], "note": "확인함"})
        await call("book_issue_close", {"id": "x"}, "book_issue_close 오류")
        await call("book_export", {})
        await call("files_list", {})
        await call("ref_import_bibliography", {"text": "Clack, J. A. (2012). Gaining ground. Indiana University Press."})
        await call("ref_add", {"bib": {"key": "clack2012"}, "passages": [{"text": "tetrapods came ashore", "reason": "1장 근거"}]})
        await call("ref_search", {"query": "tetrapods"})
        await call("ref_check", {"chapter_number": 1})
        listed = await call("book_questions", {"status": "all"})
        await call("book_answer", {"question_id": "year:없는것", "choice": "fix_text"}, "book_answer 오류")
        if qid := re.search(r"\[(bibonly:[^\]]+)\]", listed):
            await call("book_answer", {"question_id": qid.group(1), "choice": "keep", "note": "시험"})
        await call("idea_add", {"text": "바다는 돌아가는 곳이다", "kind": "thought"}, "idea_add 오류(제목을 묻게 함)")
        idea = await call("idea_add", {"text": "바다는 돌아가는 곳이다", "kind": "thought", "title": "바다", "title_by": "ai"})
        await call("idea_add_conversation", {"path": "대화.md"})
        await call("idea_search", {"query": "바다", "author": "all"})
        await call("category_trash", {"category": "생각", "item_id": idea.split()[2], "note": "시험"}, "category_trash 생각")
        await call("category_trash", {"category": "생각", "item_id": "20260101000000000-ffffff", "note": "x"}, "category_trash 생각 오류")
        style = await call("style_add", {"passage": "짧다.", "reason": "(저자가 이유를 밝히지 않음)", "tags": TAGS})
        await call("style_search", {"query": "짧음"})
        await call("category_trash", {"category": "문체", "item_id": style.split()[2], "note": "시험"}, "category_trash 문체")
        await call("book_document", {"untitled": True}, "book_document 오류(제목을 묻게 함)")
        doc = await call("book_document", {"title": "출처 확인", "title_by": "author", "preface": "머리말"})
        await call("book_document", {"document_id": re.search(r"\((\d{17}-[0-9a-f]{6})\)", doc).group(1)}, "book_document 다시")
        await call("category_list", {})
        await call("category_create", {"name": "사례", "template": "사례", "color": "빨강"})
        await call("category_create", {"name": "생각"}, "category_create 오류(정해진 이름)")
        await call("category_edit", {"category": "생각", "color": "#b22222"})
        await call("category_edit", {"category": "사례", "new_name": "옛 사례"})
        await call("category_put", {"category": "옛 사례", "author": "me", "content": "1850년대 항구", "fields": {"시기": "1850년대"},
                                    "chapters": [1]}, "category_put 오류(제목을 묻게 함)")
        item = await call("category_put", {"category": "옛 사례", "author": "me", "content": "1850년대 항구", "untitled": True})
        await call("category_put", {"category": "생각", "author": "me", "content": "x"}, "category_put 오류(기본 카테고리)")
        await call("category_search", {"query": "항구"})
        await call("category_title_default", {"mode": "ai"})
        await call("category_put", {"category": "옛 사례", "author": "ai", "content": "요약"}, "category_put 오류(AI가 짓기)")
        await call("category_list", {}, "category_list 뒤")
        await call("category_trash", {"category": "옛 사례", "item_id": re.search(r"\d{17}-[0-9a-f]{6}", item).group(), "note": "시험"})
        await call("category_trash", {"category": "옛 사례", "note": "시험"}, "category_trash 통째")
    called = {k.split()[1] for k in seen if k.startswith("응답 ")}
    assert called == {t.name for t in tools}, {t.name for t in tools} - called  # 모든 도구의 응답을 봤다
    found = {where: _hits(text) for where, text in seen.items() if _hits(text)}
    assert not found, found
