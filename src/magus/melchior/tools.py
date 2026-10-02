"""문헌(ref_*) MCP 도구 — Melchior · 황금. 검증된 근거만."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver.tools import Tool

from magus.melchior.bibliography import import_bibliography
from magus.store import Store


def build_tools(store: Store, current_user: Callable[[], str]) -> list[Tool]:
    def ref_import_bibliography(text: str) -> str:
        report = import_bibliography(store, current_user(), text)
        return report.render() + "\n모두 status=unverified다. 실제로 읽고 발췌한 문헌만 ref_add로 verified가 된다."

    return [
        Tool.from_function(
            ref_import_bibliography,
            name="ref_import_bibliography",
            description=(
                "참고문헌 목록 텍스트(한 줄에 한 문헌)를 refs에 status=unverified로 넣는다. "
                "key는 첫 저자 성(소문자 영문)+연도(예: daeschler2006)이고, '[국역: …]'이 있으면 한글 성+연도를 aliases에 넣는다. "
                "이미 있는 key는 건드리지 않는다. 파싱 실패 줄은 raw로 보관하고 리포트한다."
            ),
            structured_output=False,
        ),
    ]
