"""docx(zip)를 풀기 전 검사(2026-10-09 점검 7-c). 262KB docx 하나가 풀면 180MB XML이 되어 175초·8.9GB를 쓴 일이 있었다(압축 폭탄).

압축을 풀지 않고 목록만 보고 막는다: 항목 수, 풀린 크기의 합, 1MB 넘는 항목의 압축률. 실제 원고 docx는 항목 30여 개·4MB·압축률 3~8배였다
(합성 원고 32배). 쓰는 곳: 올린 문서 읽기(book.docx_reader — 문서 올리기·수정본·book_import·문헌 전문), 첨부 글자 뽑기(magus.extract).
"""

from __future__ import annotations

import zipfile

MAX_ENTRIES = 2_000
MAX_UNZIPPED = 200_000_000  # 풀린 합 200MB
MAX_RATIO = 100  # 압축률 100:1
RATIO_FROM = 1_000_000  # 이보다 작은 항목은 압축률을 보지 않는다(작은 XML은 압축률이 들쭉날쭉하고 폭탄이 될 수 없다)
REFUSED = "열 수 없는 문서입니다."


class UnsafeDocument(ValueError):
    """폭탄으로 보이는 문서. 메시지는 저자에게 그대로 보인다(까닭 한 문장, 값은 넣지 않는다)."""


def check(z: zipfile.ZipFile) -> None:
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES:
        raise UnsafeDocument(f"{REFUSED} 파일 안의 항목이 너무 많습니다.")
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise UnsafeDocument(f"{REFUSED} 압축을 풀면 너무 큽니다.")
    for i in infos:
        if i.file_size >= RATIO_FROM and i.file_size > MAX_RATIO * max(i.compress_size, 1):
            raise UnsafeDocument(f"{REFUSED} 압축률이 비정상적으로 큽니다.")
