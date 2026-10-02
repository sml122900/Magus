"""magus 명령. serve(Claude Desktop이 띄움), seed-demo, reindex."""

from __future__ import annotations

import argparse
import logging
import sys

from magus.config import Settings
from magus.store import LocalStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="magus", description="Magus 집필 RAG MCP 서버")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="MCP 서버 실행")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    sub.add_parser("seed-demo", help="1단계 확인용 가짜 프로젝트 생성")
    sub.add_parser("reindex", help="원본 파일에서 index.sqlite 재생성")
    args = parser.parse_args(argv)

    # stdio 전송에서 stdout은 MCP 프로토콜 전용이다. 로그는 반드시 stderr로 보낸다.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    store = LocalStore(settings.data_dir)
    log = logging.getLogger("magus")
    log.info("user_id=%s data_dir=%s embeddings=%s", settings.user_id, settings.data_dir, settings.embeddings)

    if args.cmd == "serve":
        from magus import transports
        from magus.server import build_server

        server = build_server(settings, store)
        if args.transport == "stdio":
            transports.run_stdio(server)
        else:
            transports.run_http(server)
    elif args.cmd == "seed-demo":
        from magus.book.demo import seed_demo
        from magus.book.outline import build_outline

        project, created = seed_demo(store, settings.user_id)
        print(f"{'생성' if created else '이미 있음'}: {project.id} ({project.title})\n")
        print(build_outline(store, settings.user_id, project.id))
    elif args.cmd == "reindex":
        store.reindex()
        print(f"재생성 완료: {settings.data_dir / 'index.sqlite'}")
