"""대화 기록 markdown → 발화 단위. 누가 말했는지(me/ai)를 보존한다.

지원 마커(한 파일 안에서 섞여 있어도 된다):
- `**사용자:**` / `**Claude:**` (콜론이 굵은 글씨 밖에 있어도 됨. 나/User, ChatGPT/AI/Assistant도 인정)
- `질문:` / `답변:` (앞에 `#`나 `**`가 붙어도 됨)
- `> 인용 블록` 바로 뒤의 `**Claude 요지**` — 인용 블록이 사용자 발화, 요지 이후가 AI 발화

사용자 발화 하나 → me, 그 뒤의 AI 발화 → ai(parent = 그 사용자 발화).
첫 마커 앞의 본문, 내용 없는 마커, 앞선 사용자 발화가 없는 AI 발화는 '분리 실패 구간'으로 리포트한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

_USER = re.compile(r"^\s*\*\*\s*(?:사용자|나|User|Me|Human)\s*[:：]?\s*\*\*\s*[:：]?\s*", re.I)
_AI = re.compile(r"^\s*\*\*\s*(?:Claude|ChatGPT|GPT|AI|Assistant|어시스턴트)\s*[:：]?\s*\*\*\s*[:：]?\s*", re.I)
# "답변(수정된 평가):"처럼 마커 뒤에 괄호 설명이 붙기도 한다(실대화 기록에서 확인)
_QUESTION = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*질문\s*(?:\([^)]{0,30}\))?\s*[:：]\s*(?:\*\*)?\s*")
_ANSWER = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*답변\s*(?:\([^)]{0,30}\))?\s*[:：]\s*(?:\*\*)?\s*")
_SUMMARY = re.compile(r"^\s*\*\*\s*Claude\s*요지\s*[:：]?\s*\*\*\s*[:：]?\s*")
# 제목 줄 자체가 마커인 형식: "## 질문 1" 다음 줄부터 질문(흔히 > 인용), "### 답변" 다음 줄부터 답변
_QUESTION_HEADING = re.compile(r"^\s*#{1,6}\s*질문(?:\s*\d+)?\s*[:：]?\s*$")
_ANSWER_HEADING = re.compile(r"^\s*#{1,6}\s*답변(?:\s*\d+)?\s*[:：]?\s*$")
_QUOTE = re.compile(r"^\s*>\s?")
_SEPARATOR = re.compile(r"^\s*(?:#{1,6}\s.*|-{3,}|\*{3,}|_{3,})\s*$")

Speaker = Literal["me", "ai"]


@dataclass
class Utterance:
    speaker: Speaker
    text: str
    line: int  # 1부터
    parent: int | None = None  # 이 AI 발화가 응답한 사용자 발화의 목록 인덱스


@dataclass
class ConversationSplit:
    utterances: list[Utterance]
    failures: list[tuple[int, str]] = field(default_factory=list)  # (줄 번호, 앞 40자)
    notes: list[str] = field(default_factory=list)

    @property
    def me(self) -> int:
        return sum(u.speaker == "me" for u in self.utterances)

    @property
    def ai(self) -> int:
        return sum(u.speaker == "ai" for u in self.utterances)

    def render(self) -> str:
        lines = [f"me {self.me}건, ai {self.ai}건, 분리 실패 구간 {len(self.failures)}개"]
        lines += [f"- {line}행: {head}" for line, head in self.failures]
        lines += [f"- 참고: {note}" for note in self.notes]
        return "\n".join(lines)


def _clean(lines: list[str]) -> str:
    """앞뒤의 빈 줄·구분선·제목 줄(대화 사이 구분용)을 떼어 낸다."""
    while lines and (not lines[0].strip() or _SEPARATOR.match(lines[0])):
        lines = lines[1:]
    while lines and (not lines[-1].strip() or _SEPARATOR.match(lines[-1])):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _all_quoted(lines: list[str]) -> bool:
    """사용자 발화 전체가 > 인용 블록이면(제목형 '## 질문' 아래) 인용 표시를 뗀다."""
    content = [line for line in lines if line.strip() and not _SEPARATOR.match(line)]
    return bool(content) and all(_QUOTE.match(line) for line in content)


def split_conversation(markdown: str) -> ConversationSplit:
    lines = markdown.splitlines()
    marks: list[tuple[int, str, int]] = []  # (줄, 화자 또는 'quote', 마커 뒤 시작 열)
    for i, line in enumerate(lines):
        for pattern, speaker in (
            (_SUMMARY, "ai"),
            (_USER, "me"),
            (_AI, "ai"),
            (_QUESTION_HEADING, "me"),
            (_ANSWER_HEADING, "ai"),
            (_QUESTION, "me"),
            (_ANSWER, "ai"),
        ):
            if m := pattern.match(line):
                marks.append((i, speaker, m.end()))
                if pattern is _SUMMARY:
                    # 요지 바로 앞(빈 줄 건너뜀)의 인용 블록이 사용자 발화다
                    j = i - 1
                    while j >= 0 and not lines[j].strip():
                        j -= 1
                    end = j
                    while j >= 0 and _QUOTE.match(lines[j]):
                        j -= 1
                    if j + 1 <= end:
                        marks.append((j + 1, "quote", 0))
                break
    marks.sort()

    split = ConversationSplit([])
    first = marks[0][0] if marks else len(lines)
    if preamble := _clean(lines[:first]):
        split.failures.append((1, preamble.replace("\n", " ")[:40]))
    last_me: int | None = None
    for n, (start, kind, col) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
        body = [lines[start][col:], *lines[start + 1 : end]]
        if kind == "quote" or (kind == "me" and _all_quoted(body)):
            body = [_QUOTE.sub("", line) for line in body]
        text = _clean(body)
        if not text:
            split.failures.append((start + 1, f"(빈 {'사용자' if kind != 'ai' else 'AI'} 발화)"))
            continue
        if kind == "ai":
            if last_me is None:
                split.failures.append((start + 1, "앞선 사용자 발화가 없는 AI 발화: " + text.replace("\n", " ")[:30]))
                continue
            if split.utterances[-1].speaker == "ai":
                split.notes.append(f"{start + 1}행: 같은 사용자 발화에 AI 발화가 이어서 하나 더 붙었다")
            split.utterances.append(Utterance("ai", text, start + 1, last_me))
        else:
            split.utterances.append(Utterance("me", text, start + 1))
            last_me = len(split.utterances) - 1
    return split
