"""인용 계산 캐시(2026-10-09). 올린 문서의 인용 상태 탭·답해 주실 질문(book_questions)·출처 확인 문서(book_document)·
저자 보고서가 같은 계산을 매번 처음부터 했다(father 337편 기준 서버 7.5~8.4초). 시간의 약 9할은 '참고문헌에만 있는 문헌'마다
본문 전체에서 이름만 나오는 곳을 찾는 name_mentions였고, 나머지는 장마다 인용 대조(check_text)를 두세 번씩 한 것이다.

- 저장하는 것(파생값, 지워도 다시 계산한다): 장 본문마다 인용 대조 결과, 문헌 × 장 본문마다 이름 찾기 결과.
  자리는 프로젝트 폴더의 `.cache/cites.json`(Store.get_cache·put_cache). 옛 코드는 이 파일을 읽지 않는다.
- 장 본문은 내용 해시로 잇는다. 수정본·book_write_chapter로 바뀐 장만 다시 계산한다.
- 인용 대조는 그 원고가 보는 문헌(key·상태·한글 표기·서지)·문헌 범위·비인용 용어·이 계산 코드 가운데 하나라도 바뀌면 모두 다시 한다.
  이름 찾기는 그 문헌의 저자 칸과 장 본문이 바뀔 때만 다시 한다(답을 하나 해서 표기가 이어져도 이름 찾기는 그대로 쓴다).
- 확인 요청·답(answers.md)은 저장하지 않고 매번 읽는다(가볍다). 확인 요청을 닫거나 답해도 낡은 값이 보이지 않는다.
- 결과는 캐시가 없을 때와 글자까지 같아야 한다(시험: tests/test_cite_cache.py).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from magus.melchior.check import CheckResult, CiteGroup, Resolver, check_text, terms_of
from magus.store import ChapterMeta, Ref, Store

log = logging.getLogger("magus.cache")

NAME = "cites"
VERSION = 1
# 결과를 바꾸는 코드. 이 파일들이 바뀌면 캐시를 버린다(배포 뒤 낡은 계산이 남지 않게)
_SOURCES = ("cache.py", "check.py", "citations.py", "translit.py", "author_report.py")


@lru_cache(maxsize=1)
def code_stamp() -> str:
    here = Path(__file__).parent
    digest = hashlib.sha256(f"v{VERSION}".encode())
    for name in _SOURCES:
        digest.update(name.encode())
        digest.update((here / name).read_bytes())
    return digest.hexdigest()[:16]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _ref_stamp(refs: dict[str, Ref]) -> list[Any]:
    return [[r.key, r.status, list(r.aliases), r.bib] for r in sorted(refs.values(), key=lambda r: r.key)]


def _author_stamp(ref: Ref) -> str:
    return _digest([ref.bib.get("authors", ""), ref.bib.get("first_author", "")])


def _dump(result: CheckResult) -> dict[str, Any]:
    return {"n": result.needs_source,
            "g": [[g.key, g.status, g.title, g.matched_by, [list(o) for o in g.occurrences], [list(c) for c in g.candidates]]
                  for g in result.groups]}


def _load(data: dict[str, Any]) -> CheckResult:
    return CheckResult([CiteGroup(k, s, t, m, [(int(p), str(c)) for p, c in occ], tuple((str(a), str(b)) for a, b in cands))
                        for k, s, t, m, occ, cands in data["g"]], int(data["n"]))


@dataclass
class Chapter:
    meta: ChapterMeta
    text: str
    digest: str
    result: CheckResult


class CiteCache:
    """한 번의 계산(웹 화면 하나, 도구 호출 하나) 동안 쓴다: 읽고, 빠진 것만 계산하고, 끝에 save()."""

    def __init__(self, store: Store, user_id: str, project_id: str):
        self.store, self.user_id, self.project_id = store, user_id, project_id
        self.resolver = Resolver(store, user_id, project_id)
        self.terms = terms_of(store, user_id, project_id)
        # 그 프로젝트 + 연결 노드가 가리키는 문헌(#95). 목록 순서는 저장소 순서 그대로(집계의 '같은 저자' 순서가 이것을 따른다)
        self.refs = {r.key: r for r in store.list_refs(user_id, floors=self.resolver.floors)}
        self.scope = self._scope(self.refs)
        data = self._read()
        same_code = data.get("code") == code_stamp()
        self._checks: dict[str, Any] = data.get("checks", {}) if same_code and data.get("scope") == self.scope else {}
        self._mentions: dict[str, Any] = data.get("mentions", {}) if same_code else {}
        self._chapters: list[Chapter] | None = None
        self.dirty = False
        self.computed = 0  # 이번에 새로 계산한 장 수(시험·측정용)

    def _scope(self, refs: dict[str, Ref]) -> str:
        return _digest([code_stamp(), list(self.resolver.floors or ()), sorted(self.terms), _ref_stamp(refs)])

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.store.get_cache(self.user_id, self.project_id, NAME) or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) and data.get("version") == VERSION else {}

    def chapters(self) -> list[Chapter]:
        """읽는 순서의 장(본문이 있는 것)과 인용 대조 결과."""
        if self._chapters is None:
            out = []
            for meta in self.store.list_chapters(self.user_id, self.project_id):
                chapter = self.store.read_chapter(self.user_id, self.project_id, meta.number)
                if chapter is None:
                    continue
                digest = hashlib.sha256(chapter.content.encode()).hexdigest()[:16]
                if (cached := self._checks.get(digest)) is not None:
                    result = _load(cached)
                else:
                    result = check_text(self.store, self.user_id, chapter.content, self.resolver, self.terms)
                    self._checks[digest] = _dump(result)
                    self.dirty, self.computed = True, self.computed + 1
                out.append(Chapter(meta, chapter.content, digest, result))
            self._chapters = out
        return self._chapters

    def texts(self) -> list[tuple[str, str]]:
        return [(c.meta.display, c.text) for c in self.chapters()]

    def mentions(self, ref: Ref) -> tuple[list[str], list[str]]:
        """name_mentions(모든 장, ref)와 같은 값. 장마다 찾은 표기를 저장해 두고 모은다."""
        from magus.melchior.author_report import name_mentions  # author_report가 이 모듈을 쓴다(순환 import 피함)

        stamp = _author_stamp(ref)
        entry = self._mentions.get(ref.key)
        if not isinstance(entry, dict) or entry.get("authors") != stamp:
            entry = self._mentions[ref.key] = {"authors": stamp, "found": {}}
        found: dict[str, str] = entry["found"]
        shown: dict[str, None] = {}
        where: list[str] = []
        for chapter in self.chapters():
            if chapter.digest not in found:
                names, _ = name_mentions([(chapter.meta.display, chapter.text)], ref)
                found[chapter.digest] = names[0] if names else ""
                self.dirty = True
            if hit := found[chapter.digest]:
                shown[hit] = None
                where.append(chapter.meta.display)
        return list(shown)[:2], where

    def save(self) -> None:
        """새로 계산한 것이 있으면 쓴다. 계산하는 동안 문헌이 바뀌었으면 쓰지 않는다(다음 요청이 다시 계산)."""
        if not self.dirty:
            return
        refs = {r.key: r for r in self.store.list_refs(self.user_id, floors=self.resolver.floors)}
        if self._scope(refs) != self.scope:
            return
        current = {c.digest for c in self.chapters()}
        data = {
            "version": VERSION, "code": code_stamp(), "scope": self.scope,
            "checks": {d: v for d, v in self._checks.items() if d in current},
            "mentions": {k: {"authors": e["authors"], "found": {d: f for d, f in e["found"].items() if d in current}}
                         for k, e in self._mentions.items() if k in refs and isinstance(e, dict) and "found" in e},
        }
        self.store.put_cache(self.user_id, self.project_id, NAME, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        self.dirty = False


def warm(store: Store, user_id: str, project_id: str) -> None:
    """문서를 올린 직후 응답 뒤에 미리 계산해 둔다(첫 인용 상태 탭도 빠르게). 실패해도 다음 화면이 다시 계산하므로 남기기만 한다."""
    from magus.melchior.questions import build_questions  # questions가 이 모듈을 쓴다(순환 import 피함)

    try:
        build_questions(store, user_id, project_id)
    except Exception as e:  # noqa: BLE001 — 미리 계산은 덤이다
        log.warning("인용 계산 캐시 미리 만들기 실패: %s", type(e).__name__)
