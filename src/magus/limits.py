"""도구 입력 칸의 길이 상한(2026-10-09 점검 15-6). 한 곳에 두고 도구 인자 형에 실어, 입력 스키마(maxLength)에도 보이고
SDK가 입구에서 거절한다(자르지 않는다 — 웹과 같다). 전에는 부제·장 제목·한글 표기·쓸 부분·결정·확인 요청·note·origin이
20만 자도 저장돼 book_outline(3,000토큰 원칙)·수정본 리포트·찾기 응답이 수십만 자가 됐다.
장 번호 범위(점검 15-2)도 여기 둔다(스키마 minimum·maximum)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from magus.category.rules import FIELD_MAX
from magus.store.base import CHAPTER_NUMBER_MAX

TITLE_MAX = 120  # 프로젝트 제목·부제, 장 제목
TEXT_MAX = 4_000  # 결정·확인 요청 본문
NOTE_MAX = 500  # 확인 요청 닫는 note·답 note·장 저장 note
ALIAS_MAX = 40  # 한글 표기 하나
PART_MAX = FIELD_MAX * 4  # 쓸 부분(원문에서 고른 대목) 하나
ORIGIN_MAX = 100  # 대화 기록의 출처 이름

Title = Annotated[str, Field(max_length=TITLE_MAX)]
Text = Annotated[str, Field(max_length=TEXT_MAX)]
Note = Annotated[str, Field(max_length=NOTE_MAX)]
Alias = Annotated[str, Field(max_length=ALIAS_MAX)]
Origin = Annotated[str, Field(max_length=ORIGIN_MAX)]
ChapterNumber = Annotated[int, Field(ge=0, le=CHAPTER_NUMBER_MAX)]  # 0(서장)~9,999
