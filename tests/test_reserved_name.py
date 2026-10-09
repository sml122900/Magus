"""정해진 이름 안내(2026-10-09, #99-8): 규칙은 그대로(대화의 '수정본 올렸어'가 책 이름과 헷갈리지 않게 막는다).
안내에 이유·다음 행동·쓸 수 없는 이름(코드의 RESERVED_SHOWN, 저자에게 보이는 이름만). 옛 이름·코어 이름은 막기만 하고 목록에 없다."""

from __future__ import annotations

import re

import httpx2
import pytest
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.category.rules import RESERVED, RESERVED_HIDDEN, RESERVED_SHOWN, check_name
from magus.instructions import CORE_NAMES, OLD_NAMES
from magus.store import LocalStore


def test_reserved_name_message_says_why_and_what_next():
    with pytest.raises(ValueError) as e:
        check_name("수정본", {})
    msg = str(e.value)
    assert msg.startswith("'수정본'은 Magus가 쓰는 말이라 책 이름으로는 쓸 수 없어요. 다른 이름을 붙여 주세요. (쓸 수 없는 이름: 전체, ")
    assert msg.endswith("게시판, 스크랩 등)") and all(n in msg for n in RESERVED_SHOWN)
    with pytest.raises(ValueError) as e:
        check_name("전체", {})
    assert str(e.value).startswith("'전체'는 Magus가 쓰는 말이라")
    # 옛 이름·코어 이름도 그대로 막지만 목록에는 보이지 않는다(용어집 규칙)
    with pytest.raises(ValueError) as e:
        check_name("Casper", {})
    listed = str(e.value).split("(쓸 수 없는 이름:")[1]
    assert not any(n in listed for n in (*OLD_NAMES, *CORE_NAMES))
    assert set(RESERVED) == set(RESERVED_SHOWN) | set(RESERVED_HIDDEN) and check_name("수정본 메모", {}) == "수정본 메모"


def test_scrap_is_reserved_but_existing_books_stay():
    with pytest.raises(ValueError) as e:
        check_name("스크랩", {})
    assert str(e.value).startswith("'스크랩'은 Magus가 쓰는 말이라") and "스크랩 등)" in str(e.value)
    assert check_name("스크랩 모음", {}) == "스크랩 모음"  # 정해진 이름 그대로일 때만 막는다


def test_existing_scrap_book_is_not_blocked(store):
    made = store.create_category("alice", "스크랩", "blank", "#1f2f5c", (), "common")  # 이전에 만든 책(저장소는 이름 규칙을 묻지 않는다)
    store.update_category("alice", made.id, color="#b3261e")  # 이름을 그대로 두고 색만 바꾸는 것은 된다
    assert store.get_category("alice", made.id).name == "스크랩"


def test_web_new_book_shows_reserved_message_and_picker(server_proc):  # noqa: F811
    base, data_dir, _ = server_proc({})
    LocalStore(data_dir).close()
    with httpx2.Client(base_url=base, follow_redirects=True, timeout=120) as c:
        page = c.get("/login?next=/shelf/new%3Fproject%3Dcommon").text
        csrf = _csrf(page)
        assert page.index('type="color" name="picker"') < page.index('<details class="palette">')
        bad = c.post("/shelf/new", data={"csrf": csrf, "name": "수정본", "color": "custom", "hex": "#123456"})
        assert bad.status_code == 400 and "Magus가 쓰는 말이라 책 이름으로는 쓸 수 없어요. 다른 이름을 붙여 주세요." in bad.text
        made = c.post("/shelf/new", data={"csrf": csrf, "name": "2026 답사", "color": "#b3261e", "was": "#b3261e", "picker": "#00ff88"})
        assert made.status_code == 200 and re.search(r"/shelf/[^/?]+\?done=made$", str(made.url))
    store = LocalStore(data_dir)
    [book] = [b for b in store.list_categories("alice") if b.name == "2026 답사"]
    assert book.color == "#00ff88"
    store.close()
