"""첨부 고르기(2026-10-09) 브라우저 시험: 헤드리스 Chrome으로 글쓰기·고치기 화면의 담은 파일 목록.

'파일 고르기'를 다시 눌러도 앞서 담은 파일이 남고(목록은 스크립트가 들고 있다), 파일마다 ✕로 뺀다.
10개 초과·20MB(여기서는 1MB) 초과·허용 안 되는 형식은 담는 순간 그 파일만 빼고 안내한다. 같은 이름·크기는 한 번만.
Chrome이나 node가 없으면 건너뛴다."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from conftest import needs_tools
from test_web import server_proc  # noqa: F401 - 픽스처

from magus.signing import sign
from magus.store import CategoryItem, LocalStore

NODE = shutil.which("node")
CHROME = next((c for c in (os.environ.get("CHROME"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           shutil.which("google-chrome"), shutil.which("chromium")) if c and Path(c).exists()), None)
SCRIPT = Path(__file__).parent / "e2e" / "attach_browser.mjs"
POST = "20261009000000000-aaaaaa"


@needs_tools("node 또는 Chrome이 없다", NODE, CHROME)
def test_pick_files_in_several_rounds_and_remove_one(server_proc, tmp_path):  # noqa: F811
    secret = "s" * 40
    base, data_dir, _ = server_proc({
        "PUBLIC_URL": "http://127.0.0.1:{port}", "AUTH_ISSUER": "http://127.0.0.1:9/never", "ALLOWED_USERS": "sub-a=alice",
        "SESSION_SECRET": secret, "WEB_CLIENT_ID": "web-client", "MAX_ATTACH_MB": "1",
    })
    store = LocalStore(data_dir)
    book = store.create_category("alice", "장날 메모", "blank", "#1f2f5c", (), "common").id
    store.put_category_item("alice", CategoryItem(POST, book, "고칠 글", "me"))
    store.put_attachment("alice", f"{book}/{POST}", "옛 사진.png", b"\x89PNG old")
    store.close()
    files = tmp_path / "files"
    files.mkdir()
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
    for name, data in [("a.png", png), ("b.pdf", b"%PDF-1.4 x"), ("c.txt", "글".encode()), ("bad.exe", b"MZ"),
                       ("big.pdf", b"%PDF" + b"0" * 1_100_000), *((f"e{n}.txt", f"e{n}".encode()) for n in range(1, 9))]:
        (files / name).write_bytes(data)
    cookie = sign({"uid": "alice", "sid": "a1"}, secret.encode(), "session", 3600)
    done = subprocess.run([NODE, str(SCRIPT), CHROME, base, cookie, str(tmp_path / "chrome"), str(files),
                           f"/shelf/write/{book}", f"/shelf/{book}/{POST}/edit"],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "FAIL" not in done.stdout and done.stdout.count("ok  ") == 17
    saved = next(line.split(" ", 1)[1] for line in done.stdout.splitlines() if line.startswith("SAVED "))
    store = LocalStore(data_dir)
    try:
        item = saved.rsplit("/", 1)[1]
        names = sorted(a.name for a in store.list_attachments("alice", f"{book}/{item}"))
        assert names == sorted(["a.png", "c.txt", "d.png", *(f"e{n}.txt" for n in range(1, 8))])  # e8은 11개째라 빠졌다
        assert sorted(a.name for a in store.list_attachments("alice", f"{book}/{POST}")) == ["a.png", "c.txt"]
        assert [t.preview for t in store.list_trash("alice") if t.kind == "attachment"] == ["옛 사진.png"]  # 뺀 첨부는 휴지통
    finally:
        store.close()
