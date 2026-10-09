"""책 색(2026-10-09, #99-6): 색 선택기가 먼저 보이고 기본 제공 색은 '기본 색 ▾'(접힌 details)를 눌러 펼친다. 저장 값·방식은 그대로.
스크립트 없이 색 선택기만 바꿔도 그 색으로 저장된다(was와 견줌)."""

from __future__ import annotations

import pytest

from magus.webshelf import chosen_color, color_fieldset


def test_color_picker_first_palette_folded():
    html = color_fieldset("#b3261e", ("#123456",))
    picker, mine, palette = html.index('type="color" name="picker"'), html.index('aria-label="내 색"'), html.index('<details class="palette">')
    assert picker < mine < palette and "<details class=\"palette\" open" not in html
    assert '<summary>기본 색 <span class="chev" aria-hidden="true">▾</span></summary>' in html
    assert 'name="color" value="#b3261e" checked' in html[palette:]  # 지금 색은 접힌 기본 색 안에서 골라져 있다
    assert '<input type="hidden" name="was" value="#b3261e">' in html


@pytest.mark.parametrize(("form", "expected"), [
    ({"color": "#2f6db5", "was": "#b3261e", "picker": "#b3261e"}, "#2f6db5"),  # 기본 색을 골랐다
    ({"color": "custom", "hex": "#ABCDEF", "was": "#b3261e"}, "#abcdef"),  # 직접 고르기
    ({"color": "#b3261e", "was": "#b3261e", "picker": "#00ff88"}, "#00ff88"),  # 스크립트 없이 색 선택기만 바꿨다
    ({"color": "#b3261e", "was": "#b3261e", "picker": "#b3261e"}, "#b3261e"),  # 그대로
])
def test_chosen_color_saves_as_before(form, expected):
    assert chosen_color(form) == expected
