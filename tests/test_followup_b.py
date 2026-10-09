"""코드 점검 후속 B(2026-10-09): 중간 항목별 시험. 항목 번호는 docs/audit/2026-10-09-code-audit.md."""

from __future__ import annotations

import httpx2
import pytest
from test_web import _csrf, server_proc  # noqa: F401 - 픽스처

from magus.store import CategoryItem, LocalStore

pytestmark = pytest.mark.anyio
BOUND = "----fbtest"


def _chunked(fields: dict[str, str], field: str, name: str, size: int):
    def gen():
        for k, v in fields.items():
            yield f"--{BOUND}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        yield f"--{BOUND}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{name}\"\r\nContent-Type: text/plain\r\n\r\n".encode()
        left = size
        while left > 0:
            n = min(left, 1_000_000)
            yield b"a" * n
            left -= n
        yield f"\r\n--{BOUND}--\r\n".encode()
    return gen()


# ---- 5-a 웹 본문 한도·업로드를 디스크로 바로 ----

def test_body_limit_and_streamed_uploads(server_proc):  # noqa: F811
    base, data_dir, log = server_proc({"MAX_ATTACH_MB": "2", "MAX_UPLOAD_MB": "3"})
    store = LocalStore(data_dir)
    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="bk1")
    store.close()
    headers = {"content-type": f"multipart/form-data; boundary={BOUND}"}
    with httpx2.Client(base_url=base, follow_redirects=False, timeout=120) as c:
        csrf = _csrf(c.get("/login?next=/shelf/write/bk1", follow_redirects=True).text)
        fields = {"csrf": csrf, "title": "시험", "content": "x", "project": "new"}
        # 첨부 주소: 2MB × 10 + 2MB를 넘는 청크 전송 → 받는 도중에 413(웹 오류 화면)
        big = c.post("/shelf/write/bk1", content=_chunked(fields, "files", "big.txt", 30_000_000), headers=headers)
        assert big.status_code == 413 and "보낸 내용이 너무 큽니다(한 번에 22.0 MB까지)." in big.text and "돌아가기" in big.text
        # 작은 폼 주소(지도 바꾸기)는 2MB
        small = c.post("/shelf/p/common/map", content=_chunked(fields, "files", "big.txt", 5_000_000), headers=headers)
        assert small.status_code == 413 and "2.0 MB까지" in small.text
        # 문서 올리기: 한 개 한도 + 1MB
        ms = c.post("/shelf/manuscript", content=_chunked(fields, "file", "원고.docx", 5_000_000), headers=headers)
        assert ms.status_code == 413
        # 정상 첨부는 그대로 저장된다(임시 파일에서 흘려 씀)
        ok = c.post("/shelf/write/bk1", data={"csrf": csrf, "title": "첨부", "content": "본문"},
                    files=[("files", ("a.txt", b"x" * 1_500_000, "text/plain")), ("files", ("b.txt", "가나다".encode(), "text/plain"))])
        assert ok.status_code == 303
        saved = sorted((data_dir / "users" / "alice" / "shelf" / "categories" / "bk1" / "files").glob("*/*/*.txt"))
        assert [p.read_bytes()[:3] for p in saved] == [b"xxx", "가".encode()] and saved[0].stat().st_size == 1_500_000
        # 첨부 한 개 한도(2MB)를 넘으면 저장하지 않는다(읽지 않고 받은 크기로)
        over = c.post("/shelf/write/bk1", data={"csrf": csrf, "title": "큼", "content": "본문"},
                      files=[("files", ("c.txt", b"x" * 2_500_000, "text/plain"))])
        assert over.status_code == 400 and "파일 한 개 2.0 MB까지입니다." in over.text
        # 올린 파일: 한도(3MB) 넘는 파일은 오류, 맞는 파일은 그대로
        up = c.post("/inbox/upload", data={"csrf": csrf},
                    files=[("files", ("큰.txt", b"x" * 3_500_000, "text/plain")), ("files", ("작은.txt", "내용".encode(), "text/plain"))],
                    follow_redirects=True)
        assert "큰.txt: 파일이 너무 크다" in up.text and "올림: 작은.txt" in up.text
        assert (data_dir / "users" / "alice" / "inbox" / "작은.txt").read_text(encoding="utf-8") == "내용"
    assert "Traceback" not in log.read_text(encoding="utf-8")


async def test_put_attachment_and_inbox_take_files(store: LocalStore, tmp_path):
    import io

    store.create_category("alice", "메모", "blank", "#1f2f5c", (), "common", category_id="bk1")
    store.put_category_item("alice", CategoryItem("20261009000000000-aaaaaa", "bk1", "글", "me"))
    stream = io.BytesIO(b"0123456789" * 1000)
    stream.seek(500)  # 처음부터 쓴다
    att = store.put_attachment("alice", "bk1/20261009000000000-aaaaaa", "a.txt", stream)
    path = store.attachment_path("alice", "bk1/20261009000000000-aaaaaa", att.id)[0]
    assert path.read_bytes() == b"0123456789" * 1000 and att.size == 10_000
    entry = store.put_inbox("alice", "b.txt", io.BytesIO("안녕".encode()))
    assert entry.size == len("안녕".encode())
