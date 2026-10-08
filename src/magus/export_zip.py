"""프로젝트를 마크다운 폴더(zip)로 내려받기(#95). Magus 서버에 묶이지 않는다는 것을 저자에게 보이려고 만든다.

zip 안:
  README.md                         이 구조 설명
  <프로젝트 이름>/지도.json           노드(이름·위치·색·책·연결)와 선
  <프로젝트 이름>/<노드 이름>/         노드 = 폴더(가운데 노드는 '가운데 노드')
      <모음 책 이름>/<날짜 시각 제목>.md   게시판 항목 하나 = 마크다운 파일(머리에 날짜·제목·작성자)
      문헌/<key 저자 연도>.md            문헌 하나 = 파일(서지·상태·발췌)
      올린 문서/<원본 파일>, 올린 문서/장/<NN 제목>.md, 올린 문서/확인 요청.md, 올린 문서/결정.md
      <문서 책 제목>.md                  문서 책 = 파일(지금 판)
      연결.md                          연결 노드면 원본을 가리키는 메모(내용은 원본 폴더에 한 번만 담는다)
시각은 한국 시간(KST)이다.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

from magus.ids import local_time, utcnow
from magus.contexts import book_contexts
from magus.maps import BOOK_NAMES, LIBRARY_NAME, local_key
from magus.store import MapNode, Store

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
WHEN = "%Y-%m-%d %H%M"


def safe_name(text: str, width: int = 60) -> str:
    clean = _BAD.sub("_", " ".join(str(text).split())).strip(" .") or "이름 없음"
    return clean[:width].rstrip(" .")


def zip_name(title: str) -> str:
    return f"{safe_name(title, 40)} {local_time(utcnow(), '%Y-%m-%d')}.zip"


def _front(fields: list[tuple[str, Any]]) -> str:
    lines = ["---"]
    for key, value in fields:
        if value in (None, "", [], ()):
            continue
        if isinstance(value, list | tuple):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{key}: {' '.join(str(value).split())}")
    return "\n".join([*lines, "---", ""]) + "\n"


class _Zip:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()
        self.zip = zipfile.ZipFile(self.buffer, "w", zipfile.ZIP_DEFLATED)
        self.used: set[str] = set()

    def path(self, folder: str, name: str) -> str:
        """같은 폴더에 같은 이름이 있으면 ' (2)'를 붙인다."""
        stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
        prefix = f"{folder}/" if folder else ""
        candidate, n = f"{prefix}{name}", 2
        while candidate.lower() in self.used:
            candidate, n = f"{prefix}{stem} ({n}){dot}{ext}", n + 1
        self.used.add(candidate.lower())
        return candidate

    def text(self, folder: str, name: str, content: str) -> str:
        where = self.path(folder, name)
        self.zip.writestr(where, content.encode("utf-8"))
        return where

    def raw(self, folder: str, name: str, data: bytes) -> str:
        where = self.path(folder, name)
        self.zip.writestr(where, data)
        return where

    def close(self) -> bytes:
        self.zip.close()
        return self.buffer.getvalue()


def _item_file(when: str, title: str | None, preview: str) -> str:
    head = title or " ".join(preview.split())[:30] or "제목 없음"
    return f"{local_time(when, WHEN) if when else '날짜 없음'} {safe_name(head, 40)}.md"


def _who(author: str) -> str:
    return "저자" if author == "me" else "Claude(AI)"


def _contexts_md(contexts: tuple) -> str:
    return "# 컨텍스트\n\nAI가 이 책의 글을 읽는 방법(저자가 적어 둔 것)입니다.\n\n" + "\n\n".join(
        (f"## {c.name}\n\n" if c.name else "") + c.text.strip() for c in contexts) + "\n"


def _ref_file(store: Store, user: str, z: _Zip, where: str, ref: Any) -> None:
    bib = ref.bib
    name = safe_name(f"{ref.key} {bib.get('first_author') or ''} {bib.get('year') or ''}", 50) + ".md"
    passages = store.get_passages(user, ref.key)
    body = [f"# {bib.get('title') or bib.get('raw') or ref.key}", ""]
    body += [f"{bib['memo']}\n"] if bib.get("memo") else []
    body += [f"> {p.text.strip()}\n\n이유: {p.reason}" + (f" ({p.locator})" if p.locator else "") + "\n" for p in passages]
    z.text(where, name, _front([
        ("key", ref.key), ("상태", "원문 확인(저자가 원문을 읽고 확인)" if ref.status == "verified" else "원문 확인 전(참고문헌 목록 등)"),
        ("저자", bib.get("authors") or bib.get("author")), ("연도", bib.get("year")), ("제목", bib.get("title")),
        ("원문 줄", bib.get("raw")), ("다른 표기", list(ref.aliases)), ("파일", ref.file_path),
        ("옮긴 기록", (ref.moved or {}).get("reason") if ref.moved else ""),
        ("등록한 때", local_time(ref.created_at, "%Y-%m-%d %H:%M") if ref.created_at else "")]) + "\n".join(body) + "\n")


def _book_folder(store: Store, user: str, z: _Zip, folder: str, key: str) -> str | None:
    """책 하나를 zip에 넣고 그 책의 폴더(또는 파일) 이름을 돌려준다(#96: 책의 글 + 문헌 글 + 컨텍스트.md)."""
    floor, local = local_key(key)
    if local == "ms" and floor:
        project = store.get_project(user, floor)
        if project and project.contexts:
            z.text(f"{folder}/올린 문서", "컨텍스트.md", _contexts_md(project.contexts))
        return _manuscript(store, user, z, f"{folder}/올린 문서", floor)
    if local.startswith("doc."):
        doc = store.get_document(user, local[4:])
        if doc is None:
            return None
        content = store.read_document(user, doc.id) or ""
        v = doc.versions[-1] if doc.versions else None
        where = z.text(folder, safe_name(doc.title) + ".md", _front([
            ("제목", doc.title), ("컨텍스트", [c.name or c.text[:30] for c in doc.contexts]),
            ("만든 때", local_time(v.at, "%Y-%m-%d %H:%M") if v else ""), ("기준 수정본", f"E{v.edition}" if v and v.edition else ""),
            ("판", v.number if v else "")]) + content)
        return where.rsplit("/", 1)[-1]
    try:
        category = store.get_category(user, local)
    except ValueError:
        category = None
    if category is None:
        return None
    where = f"{folder}/{safe_name(category.name)}"
    if category.contexts:
        z.text(where, "컨텍스트.md", _contexts_md(category.contexts))
    for item in sorted(store.list_category_items(user, category.id), key=lambda i: i.created_at):
        fields = [f"{k}: {v}" for k, v in item.fields.items() if v]
        parts = "".join(f"\n> {p.text.strip()}\n" + (f"\n이유: {p.reason}" if p.reason else "") + (f" ({p.locator})" if p.locator else "") + "\n"
                        for p in item.passages)
        z.text(where, _item_file(item.created_at, item.title, item.content or " ".join(fields)), _front([
            ("날짜", local_time(item.created_at, "%Y-%m-%d %H:%M")), ("제목", item.title), ("작성자", _who(item.author)),
            ("제목을 지은 이", {"ai": "Claude(AI)", "author": "저자"}.get(item.title_by or "")), ("이유", item.reason), ("위치", item.where),
            ("칸", fields), ("태그", list(item.tags)), ("태그를 정한 이", {"ai": "Claude(AI)", "author": "저자"}.get(item.tags_by or "")),
            ("연결된 장", [f"{p} {n}장" for p, n in item.chapters]), ("출처", item.origin), ("응답한 글", item.parent_id),
            ("고친 때", local_time(item.edited_at, "%Y-%m-%d %H:%M") if item.edited_at else ""), ("id", item.id)])
            + (item.content or "").strip() + "\n" + parts)
    for ref in store.list_refs(user, book=category.id):
        _ref_file(store, user, z, f"{where}/문헌 글", ref)
    return f"{safe_name(category.name)}/"


def _manuscript(store: Store, user: str, z: _Zip, folder: str, project_id: str) -> str:
    original = store.original_bytes(user, project_id)
    if original:
        z.raw(folder, original[0], original[1])
    for meta in store.list_chapters(user, project_id):
        chapter = store.read_chapter(user, project_id, meta.number)
        if chapter is None:
            continue
        z.text(f"{folder}/장", f"{meta.number:03d} {safe_name(meta.title, 40)}.md",
               _front([("장", meta.display), ("제목", meta.title), ("상태", meta.status), ("버전", meta.version)])
               + f"# {meta.display} {meta.title}\n\n{chapter.content.strip()}\n")
    issues = store.list_issues(user, project_id, None)
    if issues:
        z.text(folder, "확인 요청.md", "# 확인 요청\n\n" + "\n".join(
            f"- I{i.id} · {'열림' if i.status == 'open' else '닫힘'}" + (f" · {i.chapter_number}장" if i.chapter_number is not None else "")
            + f" · {' '.join(i.text.split())}" for i in issues) + "\n")
    decisions = store.list_decisions(user, project_id)
    if decisions:
        z.text(folder, "결정.md", "# 결정\n\n" + "\n".join(
            f"- D{d.id} · {local_time(d.created_at, '%Y-%m-%d')} · {' '.join(d.text.split())}" for d in decisions) + "\n")
    return "올린 문서/"


def _node_folder(node: MapNode, title: str) -> str:
    if node.center:
        return "가운데 노드"
    return safe_name(f"연결 · {node.name}" if node.link else node.name, 40)


def build_zip(store: Store, user: str, floors: list[str]) -> bytes:
    z = _Zip()
    projects = []
    for floor_id in floors:
        floor = store.get_floor(user, floor_id)
        found = store.get_map(user, floor_id)
        if floor is None or found is None:
            continue
        title = LIBRARY_NAME if floor.common else floor.title
        root = z.path("", safe_name(title, 50))
        projects.append(root)
        names = {n.id: ("가운데" if n.center else f"연결 · {n.name}" if n.link else n.name) for n in found.nodes}
        nodes = []
        for node in found.nodes:
            folder = f"{root}/{_node_folder(node, title)}"
            books = []
            if node.link:
                where = store.get_floor(user, node.link[0])
                z.text(folder, "연결.md", "# 연결 노드\n\n" + (
                    "원본 노드가 없습니다.\n" if node.missing else
                    f"이 노드는 「{node.link_title}」의 「{node.name}」 노드를 가리킵니다. 내용은 그 프로젝트 폴더에 있습니다"
                    + ("(이 zip에 함께 들었습니다).\n" if where and where.id in floors else "(이 zip에는 없습니다).\n")))
            else:
                for key in node.books:
                    shown = _book_folder(store, user, z, folder, key)
                    if shown:
                        books.append({"책": _book_title(store, user, key), "컨텍스트": _book_contexts(store, user, key), "자리": shown})
                if not node.books:
                    z.text(folder, "빈 노드.md", f"# {node.name}\n\n책이 없는 노드입니다.\n")
            nodes.append({"id": node.id, "이름": names[node.id], "x": node.x, "y": node.y, "색": node.color, "가운데": node.center,
                          "연결": {"프로젝트": node.link_title, "노드": node.name, "원본 없음": node.missing} if node.link else None,
                          "책": books, "폴더": _node_folder(node, title)})
        z.text(root, "지도.json", json.dumps({
            "프로젝트": title, "id": floor_id, "내려받은 때": local_time(utcnow(), "%Y-%m-%d %H:%M"),
            "노드": nodes, "선": [{"이음": [names.get(a, a), names.get(b, b)], "id": [a, b]} for a, b in found.edges],
        }, ensure_ascii=False, indent=2) + "\n")
    z.text("", "README.md", README.format(when=datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M"),
                                         projects="\n".join(f"- {p}/" for p in projects)))
    return z.close()


def _book_title(store: Store, user: str, key: str) -> str:
    floor, local = local_key(key)
    if local in BOOK_NAMES:
        return BOOK_NAMES[local]
    if local == "ms" and floor:
        project = store.get_project(user, floor)
        return project.title if project else "올린 문서"
    if local.startswith("doc."):
        doc = store.get_document(user, local[4:])
        return doc.title if doc else ""
    try:
        category = store.get_category(user, local)
    except ValueError:
        category = None
    return category.name if category else ""


def _book_contexts(store: Store, user: str, key: str) -> list[str]:
    contexts, _ = book_contexts(store, user, key)
    return [c.name or c.text[:30] for c in contexts]


README = """# Magus에서 내려받은 자료

내려받은 때: {when}

Magus 서버 없이도 읽을 수 있는 마크다운 파일입니다. 아무 글 편집기(메모장, Word, Obsidian 등)로 열 수 있습니다.

## 들어 있는 프로젝트

{projects}

## 구조

- 프로젝트 하나 = 폴더 하나. 그 안의 `지도.json`에 노드(이름·위치·색·꽂힌 책·연결)와 선이 있습니다.
- 노드 하나 = 폴더 하나(가운데 노드는 `가운데 노드`).
- 책 = 노드 폴더 안의 폴더. 게시판의 글 하나가 마크다운 파일 하나이고, 파일 머리에 날짜·제목·작성자가 있습니다.
  책에 컨텍스트(AI가 그 책을 읽는 방법)가 있으면 `컨텍스트.md`에, 서지가 있는 문헌 글은 `문헌 글` 폴더에 파일 하나씩(서지·원문 확인·쓸 부분) 있습니다.
- 올린 문서 = `올린 문서` 폴더. 올린 파일(docx·pdf) 원본, 장마다 마크다운, 확인 요청·결정 목록.
- 올린 문서에서 만든 문서 = 마크다운 파일 하나(지금 판).
- 연결 노드 = `연결.md`(원본을 가리키는 메모). 내용은 원본 프로젝트 폴더에 한 번만 들어 있습니다.

시각은 한국 시간입니다.
"""
