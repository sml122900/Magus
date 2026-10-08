"""사진 썸네일(2026-10-09 사용자 요청, #98-e 수정): 긴 변 400px JPEG, EXIF 회전 반영. 원본은 읽기만 하고 절대 바꾸지 않는다.

- 자리: 그 첨부의 id 폴더 안 `.thumb/thumb.jpg`(magus.store.attachments). 첨부 폴더에서 파일만 세는 옛 코드는 이 하위 폴더를 보지 않으므로
  되돌려도 첨부 목록이 그대로다. 글·첨부를 휴지통으로 옮기면 폴더째 함께 간다.
- 만드는 때: 사진을 올릴 때, 처음 열 때(없으면 그 자리에서), 운영자 명령 `magus thumbs`(배포 때 한 번에).
- 만들지 못하면(망가진 파일, 너무 큰 그림 등) None — 화면은 원본을 그대로 쓴다.
- 대상은 브라우저가 바로 그리는 그림(png·jpg·jpeg·gif·webp)만. heic·tif는 원래 내려받기로만 준다.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from magus.attachments import media_type

THUMB_EDGE = 400  # 긴 변
THUMB_DIR = ".thumb"
THUMB_NAME = "thumb.jpg"


def thumbnailable(name: str) -> bool:
    media, inline = media_type(name)
    return inline and media.startswith("image/")


def make_thumb(src: Path, dst: Path) -> bool:
    """src(원본, 읽기만)에서 dst에 썸네일을 쓴다. 실패하면 False(dst는 만들지 않는다)."""
    from PIL import Image, ImageOps  # noqa: PLC0415

    tmp = dst.with_name(f".{secrets.token_hex(4)}.part")
    try:
        with Image.open(src) as im:
            im.draft("RGB", (THUMB_EDGE * 2, THUMB_EDGE * 2))  # JPEG는 읽을 때부터 줄여 빠르다
            shown = ImageOps.exif_transpose(im)  # 휴대폰 세로 사진: EXIF 방향대로 돌린다
            shown.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
            if shown.mode in ("RGBA", "LA", "P"):  # 투명한 부분은 흰 바탕으로(JPEG에는 투명이 없다)
                rgba = shown.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                shown = flat
            else:
                shown = shown.convert("RGB")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shown.save(tmp, "JPEG", quality=82, optimize=True)
        os.replace(tmp, dst)  # 다 쓴 뒤에 이름을 바꾼다(반쪽 썸네일이 보이지 않게)
        return True
    except Exception:  # noqa: BLE001 — 그림 해석 실패는 종류가 많다(망가진 파일·폭탄 방지·모르는 형식). 원본을 쓰면 된다
        tmp.unlink(missing_ok=True)
        return False
