"""카테고리 옮기기·되돌리기(#93). 도구(category_edit)와 웹 책장이 함께 쓴다.

문헌을 옮기면 인용 점검이 보는 문헌(그 작업물 층 + 공용)이 바뀌므로 그 자리에서 장별 집계를 다시 계산한다.
문장은 둘: 도구 응답(Claude에게, '-다')과 웹 안내(저자에게, '-습니다'). 둘 다 용어집 이름만 쓴다.
"""

from __future__ import annotations

from magus.floors import COMMON, josa
from magus.melchior.check import after_refs_changed
from magus.store import FloorMove, Store
from magus.store.floors import KINDS, MoveError

BUILTIN_NAMES = {"ideas": "생각", "styles": "문체", "refs": "문헌"}


def move_book(store: Store, user: str, book: str, from_floor: str, to_floor: str) -> FloorMove:
    """book: 저자의 카테고리 id 또는 기본 카테고리 종류(ideas|styles|refs, from_floor에 꽂힌 것)."""
    if book in KINDS:
        move = store.move_builtin(user, book, from_floor, to_floor)
        if book == "refs":
            after_refs_changed(store, user)
        return move
    return store.move_category(user, book, to_floor)


def undo_move(store: Store, user: str, move_id: str) -> FloorMove:
    move = store.undo_move(user, move_id)
    if move.book == "refs":
        after_refs_changed(store, user)
    return move


def _labels(store: Store, user: str) -> dict[str, str]:
    return {f.id: f.label for f in store.list_floors(user)}


def refs_warning(store: Store, user: str, move: FloorMove) -> bool:
    """문헌을 원고가 있는 작업물 층에서 다른 작업물 층으로 옮겼나(그 원고의 인용 점검이 이 문헌을 더는 보지 않는다)."""
    if move.book != "refs" or move.to_floor == COMMON or move.from_floor == COMMON:
        return False
    source = store.get_floor(user, move.from_floor)
    return bool(source and source.has_manuscript)


def tool_message(store: Store, user: str, move: FloorMove, undone: bool = False) -> str:
    labels = _labels(store, user)
    src, dst = labels.get(move.from_floor, move.from_floor), labels.get(move.to_floor, move.to_floor)
    if undone:
        return f"되돌림: 「{move.name}」 {dst} → {src}(옮기기 전 자리)."
    merged = f"({dst}의 {move.name}과 합침, 항목 {len(move.items)}개)" if move.merged else (
        f"(항목 {len(move.items)}개 함께)" if move.book in KINDS else "(항목 모두 함께)")
    out = f"옮김: 「{move.name}」 {src} → {dst}{merged}. 되돌리려면 저자에게 확인하고 같은 카테고리로 category_edit(undo_move=true)."
    if refs_warning(store, user, move):
        out += f" 주의: {src} 원고의 인용 점검은 이제 이 문헌을 보지 않는다(그 층과 공용의 문헌만 본다)."
    return out


def web_message(store: Store, user: str, move: FloorMove, undone: bool = False) -> str:
    """저자에게 보이는 한 줄(이스케이프는 부르는 쪽에서)."""
    labels = _labels(store, user)
    src, dst = labels.get(move.from_floor, move.from_floor), labels.get(move.to_floor, move.to_floor)
    name = f"「{move.name}」"
    if undone:
        return f"{josa(name, '을/를')} 원래 자리({src})로 되돌렸습니다."
    if move.merged:
        out = f"{josa(name, '을/를')} {dst}의 {josa(move.name, '과/와')} 합쳤습니다(항목 {len(move.items)}개)."
    else:
        out = f"{josa(name, '을/를')} {josa(dst, '으로/로')} 옮겼습니다."
    if refs_warning(store, user, move):
        out += f" {src} 원고의 인용 점검은 이제 이 문헌을 보지 않습니다(그 층과 공용의 문헌만 봅니다)."
    return out


def error_message(e: MoveError, polite: bool) -> str:
    """옮기기·되돌리기를 하지 못한 까닭."""
    name, floor = e.info.get("name", ""), e.info.get("floor", "")
    texts = {
        "same": ("이미 그 층에 있습니다.", "이미 그 층에 있다."),
        "clash": (f"{floor}에 같은 이름 「{name}」이 있어 옮기지 못했습니다. 이름을 바꾼 뒤 옮겨 주세요.",
                  f"{floor}에 같은 이름 「{name}」이 있어 옮기지 않았다. 저자에게 알리고, 이름을 바꾼 뒤 옮긴다."),
        "undo_clash": (f"{floor}에 같은 이름 「{name}」이 생겨 되돌리지 못했습니다.",
                       f"{floor}에 같은 이름 「{name}」이 생겨 되돌리지 않았다."),
        "not_last": ("되돌릴 수 있는 것은 마지막으로 옮긴 것뿐입니다.", "되돌릴 수 있는 것은 마지막 옮기기뿐이다."),
        "unknown_floor": ("없는 층입니다.", "없는 층이다."),
        "no_builtin": ("그 층에 그 카테고리가 없습니다.", "그 층에 그 카테고리가 없다."),
        "unknown_category": ("없는 카테고리입니다.", "없는 카테고리다."),
    }
    polite_text, plain = texts.get(e.code, (str(e), str(e)))
    return polite_text if polite else plain
