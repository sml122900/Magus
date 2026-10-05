"""Claude Desktop과 같은 경로: 하위 프로세스 + stdio + 한글. 단계마다 새 도구를 여기서 한 번씩 부른다."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from magus.book.demo import seed_demo
from magus.store import LocalStore
from magus.synthetic import build_manuscript_docx

pytestmark = pytest.mark.anyio


def _text(result) -> str:
    assert not result.is_error, result.content[0].text if result.content else result
    return "".join(block.text for block in result.content)


async def test_stdio_subprocess(data_dir: Path, tmp_path: Path):
    manuscript = build_manuscript_docx(tmp_path / "닿으려는_종_합성.docx")
    store = LocalStore(data_dir)
    seed_demo(store, "alice")
    store.put_inbox("alice", manuscript.name, manuscript.read_bytes())  # 원고는 받은함 이름으로 가리킨다
    store.close()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "magus", "serve"],
        env={**os.environ, "USER_ID": "alice", "DATA_DIR": str(data_dir), "EMBEDDINGS": "none"},
    )
    async with Client(params) as client:
        assert client.server_info.name == "Magus"
        outline = _text(await client.call_tool("book_outline", {}))
        assert outline.startswith("프로젝트: 데모: 물에서 뭍으로 (demo)")
        assert "물가의 망설임" in outline

        # 2단계
        imported = _text(await client.call_tool("book_import", {"path": manuscript.name, "project_id": "synth"}))
        assert "장 7개(" in imported and "· 부 3개" in imported and "| ch-04.md | 제4장 | 닿으려는 손 | 2 |" in imported
        bib = _text(await client.call_tool("ref_import_bibliography", {"text": "Zimmer, C. (1998). At the water's edge. Free Press."}))
        assert "이미 있음 1건" in bib

        # 1단계 검토 반영(미리 구현된 도구)
        ch1 = _text(await client.call_tool("book_read_chapter", {"number": 1, "project_id": "synth"}))
        assert '"title": "물가의 망설임"' in ch1
        written = _text(await client.call_tool("book_write_chapter", {"number": 7, "content": "닿으려는 것.", "note": "고침", "project_id": "synth"}))
        assert '"version": 2' in written
        assert _text(await client.call_tool("book_issues", {"project_id": "synth"})).startswith("확인 요청 13건")

        # 3단계
        assert _text(await client.call_tool("book_decide", {"text": "결정", "project_id": "synth"})).startswith("D1")
        assert _text(await client.call_tool("book_issue_add", {"text": "열린 문제", "project_id": "synth"})).startswith("I14")
        assert _text(await client.call_tool("book_issue_close", {"id": "I14", "project_id": "synth"})) == "I14 닫음"
        exported = _text(await client.call_tool("book_export", {"project_id": "synth"}))
        assert Path(exported.splitlines()[0].removeprefix("docx를 만들었다: ")).exists()

        # 4단계
        checked = _text(await client.call_tool("ref_check", {"chapter_number": 1, "project_id": "synth"}))
        assert '"daeschler2006"' in checked
        added = _text(await client.call_tool("ref_add", {"bib": {"key": "clack2012"}, "passages": [{"text": "네발동물의 기원", "reason": "1장"}]}))
        assert added.startswith("clack2012: unverified → verified")
        assert "clack2012 (verified)" in _text(await client.call_tool("ref_search", {"query": "네발동물"}))

        # 5단계
        convo = _text(await client.call_tool("idea_add_conversation", {"markdown": "**사용자:** 고래는 돌아갔다\n**Claude:** 맞습니다"}))
        assert convo.startswith("me 1건, ai 1건")
        assert _text(await client.call_tool("idea_add", {"text": "물가의 망설임", "kind": "thought"})).startswith("기록함 [me]")
        assert "[me]" in _text(await client.call_tool("idea_search", {"query": "고래"}))

        # 6단계
        tags = {"호흡": "짧음", "시점": "1인칭", "열기": "장면", "장치": ["반복"], "어미": "-다", "톤": "건조"}
        styled = _text(await client.call_tool("style_add", {"passage": "고래는 돌아갔다.", "reason": "짧은 문장의 리듬", "tags": tags}))
        assert styled.startswith("문체에 기록함 ")
        assert "구절: “고래는 돌아갔다.”" in _text(await client.call_tool("style_search", {"query": "짧은 리듬"}))



async def test_relative_file_path_from_other_cwd(data_dir: Path, tmp_path: Path):
    """로컬(stdio) 개발용 대체 경로: 받은함에 없으면 로컬 경로도 받는다. 원격(HTTP)에서는 받지 않는다(test_http, test_inbox).
    Desktop은 서버를 어느 작업 폴더에서 띄울지 정하지 않는다. 상대 경로는 DATA_DIR의 부모(프로젝트 폴더) 기준이어야 한다.
    README '첫 실행 확인'의 시연: "fixtures/papers/<파일>.pdf를 문헌으로 등록해 줘. 쓸 부분은 ~, 이유는 ~"."""
    import pymupdf

    papers = tmp_path / "fixtures" / "papers"
    papers.mkdir(parents=True)
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Population Growth and Technological Change:")
        page.insert_text((72, 90), "One Million B.C. to 1990")
        page.insert_text((72, 120), "Michael Kremer. Quarterly Journal of Economics")
        doc.save(papers / "kremer.pdf")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "magus", "serve"],
        env={**os.environ, "USER_ID": "alice", "DATA_DIR": str(data_dir), "EMBEDDINGS": "none"},
        cwd=str(elsewhere),
    )
    bib_line = "Kremer, M. (1993). Population growth and technological change: One million B.C. to 1990. Quarterly Journal of Economics, 108(3), 681–716."
    async with Client(params) as client:
        assert "새 refs 1건" in _text(await client.call_tool("ref_import_bibliography", {"text": bib_line}))
        passage = {"text": "인구가 많을수록 기술 진보가 빠르다", "reason": "35장 크레머 문단의 근거"}
        # 저자·연도 없이 파일만: 전문 첫머리의 제목으로 참고문헌을 찾는다
        added = _text(
            await client.call_tool("ref_add", {"bib": {}, "passages": [passage], "file_path": "fixtures/papers/kremer.pdf"})
        )
        assert added.startswith("kremer1993: unverified → verified") and "전문 있음" in added
        missing = await client.call_tool("ref_add", {"bib": {"key": "x2000"}, "passages": [passage], "file_path": "fixtures/papers/없음.pdf"})
        assert missing.is_error and f"{tmp_path} 기준으로 푼다" in missing.content[0].text
    stored = LocalStore(data_dir)
    assert stored.get_ref("alice", "kremer1993").file_path == str((papers / "kremer.pdf").resolve())
    stored.close()
