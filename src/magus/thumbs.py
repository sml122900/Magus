"""사진 썸네일(2026-10-09 사용자 요청, #98-e 수정): 긴 변 400px JPEG, EXIF 회전 반영. 원본은 읽기만 하고 절대 바꾸지 않는다.

- 자리: 그 첨부의 id 폴더 안 `.thumb/thumb.jpg`(magus.store.attachments). 첨부 폴더에서 파일만 세는 옛 코드는 이 하위 폴더를 보지 않으므로
  되돌려도 첨부 목록이 그대로다. 글·첨부를 휴지통으로 옮기면 폴더째 함께 간다.
- 만드는 때: 사진을 올릴 때, 처음 열 때(없으면 그 자리에서), 운영자 명령 `magus thumbs`(배포 때 한 번에).
- 만들지 못하면(망가진 파일, 너무 큰 그림 등) None — 화면은 원본을 그대로 쓴다(원본 내려받기는 그대로).
- 그림 폭탄(2026-10-09 점검 7-a): 작은 파일이 풀면 수억 픽셀이 되어 서버(1GB)가 메모리 부족에 빠질 수 있었다(114KB WebP → 1,142MB).
  풀기 전에 머리의 크기로 픽셀 수를 보고 MAX_PIXELS를 넘으면 만들지 않는다. Pillow의 폭탄 경고도 오류로 본다.
  EXIF 회전은 줄인 뒤에 한다(큰 그림을 한 번 더 복사하지 않게). 만들지 못하면 같은 폴더에 실패 표시를 남겨 볼 때마다 다시 하지 않는다.
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
FAILED_NAME = "failed"  # 만들지 못했다는 표시(내용은 까닭 한 단어). 지워도 된다(다음에 다시 시도)
MAX_PIXELS = 30_000_000  # 3,000만 픽셀(예: 6000×5000). 휴대폰 사진(1,200~5,000만)… 5,000만 화소 사진은 원본만 보인다


def thumbnailable(name: str) -> bool:
    media, inline = media_type(name)
    return inline and media.startswith("image/")


def make_thumb(src: Path, dst: Path) -> bool:
    """src(원본, 읽기만)에서 dst에 썸네일을 쓴다. 실패하면 False(dst는 만들지 않고 옆에 실패 표시를 남긴다)."""
    import warnings  # noqa: PLC0415

    from PIL import Image, ImageOps  # noqa: PLC0415

    tmp = dst.with_name(f".{secrets.token_hex(4)}.part")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # 폭탄 경고(8,950만 픽셀부터)도 실패로
            with Image.open(src) as im:  # 여기까지는 머리만 읽는다(픽셀은 아직 풀지 않는다)
                im.draft("RGB", (THUMB_EDGE * 2, THUMB_EDGE * 2))  # JPEG는 읽을 때부터 1/2~1/8로 줄여 푼다(크기도 줄어든다)
                if im.width * im.height > MAX_PIXELS:  # 풀 크기(JPEG는 줄여 풀 크기)가 상한을 넘으면 풀지 않는다
                    raise ValueError("too_big")
                im.getexif()  # 방향 정보는 파일이 열려 있을 때 읽어 둔다(PNG는 여기서 풀리므로 크기 검사 뒤에)
                im.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
                shown = ImageOps.exif_transpose(im)  # 휴대폰 세로 사진: 줄인 뒤 EXIF 방향대로 돌린다
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
    except Exception as e:  # noqa: BLE001 — 그림 해석 실패는 종류가 많다(망가진 파일·폭탄 방지·모르는 형식). 원본을 쓰면 된다
        tmp.unlink(missing_ok=True)
        reason = "too_big" if str(e) == "too_big" or isinstance(e, (Image.DecompressionBombWarning, Image.DecompressionBombError)) else "failed"
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            (dst.parent / FAILED_NAME).write_text(reason, encoding="utf-8")
        except OSError:
            pass
        return False


def failed(dst: Path) -> bool:
    """전에 만들지 못한 썸네일인가(실패 표시가 있으면 다시 시도하지 않는다)."""
    return (dst.parent / FAILED_NAME).is_file()
