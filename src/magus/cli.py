"""magus 명령. serve(Claude Desktop이 띄움), import, synth, seed-demo, reindex."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from magus.config import Settings
from magus.store import LocalStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="magus", description="Magus 집필 RAG MCP 서버")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="MCP 서버 실행")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    imp = sub.add_parser("import", help="원고(docx/pdf)를 새 프로젝트로 임포트하고 전체 리포트를 출력")
    imp.add_argument("path", type=Path)
    imp.add_argument("--project-id")
    imp.add_argument("--title")
    imp.add_argument("--replace", action="store_true", help="같은 project_id가 있으면 휴지통으로 옮기고 다시 만든다")
    imp.add_argument("--synthetic", action="store_true", help="리포트에 '합성 fixture'라고 표시")
    convo = sub.add_parser("conversation", help="대화 기록 md를 영감 책장(Casper)에 넣고 리포트를 출력")
    convo.add_argument("path", type=Path)
    convo.add_argument("--origin")
    synth = sub.add_parser("synth", help="합성 fixture(원고 docx·pdf, 대화 기록 md)를 만든다")
    synth.add_argument("folder", type=Path)
    sub.add_parser("seed-demo", help="1단계 확인용 가짜 프로젝트 생성")
    sub.add_parser("reindex", help="원본 파일에서 index.sqlite 재생성")
    args = parser.parse_args(argv)

    # stdio 전송에서 stdout은 MCP 프로토콜 전용이다. 로그는 반드시 stderr로 보낸다.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "synth":
        from magus.synthetic import write_all

        for name, path in write_all(args.folder).items():
            print(f"{name}: {path}")
        return

    settings = Settings.from_env()
    store = LocalStore(settings.data_dir)
    log = logging.getLogger("magus")
    log.info("user_id=%s data_dir=%s embeddings=%s", settings.user_id, settings.data_dir, settings.embeddings)

    if args.cmd == "serve":
        from magus import transports
        from magus.embeddings import get_embedder
        from magus.server import build_server

        server = build_server(settings, store, get_embedder(settings))
        if args.transport == "stdio":
            transports.run_stdio(server)
        else:
            transports.run_http(server)
    elif args.cmd == "import":
        from magus.book.importer import import_manuscript

        report = import_manuscript(
            store,
            settings.user_id,
            args.path,
            project_id=args.project_id,
            title=args.title,
            replace=args.replace,
            synthetic=args.synthetic,
        )
        print(report.full())
    elif args.cmd == "conversation":
        from magus.casper.tools import add_conversation

        report, ideas = add_conversation(
            store, settings.user_id, args.path.read_text(encoding="utf-8"), args.origin or args.path.stem
        )
        print(f"{args.path.name}: {report}\n저장 {len(ideas)}건")
    elif args.cmd == "seed-demo":
        from magus.book.demo import seed_demo, seed_demo_shelf
        from magus.book.outline import build_outline

        project, created = seed_demo(store, settings.user_id)
        if created:
            seed_demo_shelf(store, settings.user_id)
        print(f"{'생성' if created else '이미 있음'}: {project.id} ({project.title})\n")
        print(build_outline(store, settings.user_id, project.id))
    elif args.cmd == "reindex":
        from magus.melchior.check import after_refs_changed

        store.reindex()
        for user_id in store.list_users():
            after_refs_changed(store, user_id)  # 파생값(장별 미확인 인용 수, citation 이슈 연결) 다시 계산
        print(f"재생성 완료: {settings.data_dir / 'index.sqlite'}")
