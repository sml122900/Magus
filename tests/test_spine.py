"""책등의 숫자·영문(2026-10-09, #99-7): 모두 세우고(upright) 2~4자 숫자·영문 묶음은 한 칸(text-combine-upright: all),
5자 이상 영문은 눕힘(side). 세움(up)과 둘 다 캡처해 눕힘이 더 읽기 쉬워 골랐다(private/screens/2026-10-09-edit-scrap/spine-compare-*)."""

from __future__ import annotations

import pytest

from magus.webshelf import SHELF_STYLE, SPINE_LONG, spine_html


@pytest.mark.parametrize(("name", "html"), [
    ("수정본2", "수정본2"),  # 한 글자 숫자는 그대로 선다
    ("3장 메모", "3장 메모"),
    ("2026 답사", '<span class="tcy">2026</span> 답사'),
    ("AI 메모", '<span class="tcy">AI</span> 메모'),
    ("Magus 구조", '<span class="side">Magus</span> 구조'),
    ("제1부 항온", "제1부 항온"),
    ("A<b>", "A&lt;b&gt;"),  # 이스케이프
])
def test_spine_letters(name, html):
    assert spine_html(name) == html
    assert spine_html("Magus 구조", "up") == "Magus 구조"


def test_spine_style_is_upright():
    assert "text-orientation:upright" in SHELF_STYLE and ".spine-title .tcy{text-combine-upright:all" in SHELF_STYLE
    assert SPINE_LONG == "side"
