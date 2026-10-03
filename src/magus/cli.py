"""magus 명령. serve(Claude Desktop이 띄움), import, synth, seed-demo, reindex."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from magus.config import Settings
from magus.logsafe import setup_logging
from magus.store import LocalStore

DEFAULT_USER = "default"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="magus", description="Magus 집필 RAG MCP 서버")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="MCP 서버 실행")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1", help="http: 바인드 주소(인증 없이는 루프백만)")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000), help="http: 포트(기본 $PORT 또는 8000)")
    imp = sub.add_parser("import", help="원고(docx/pdf)를 새 프로젝트로 임포트하고 전체 리포트를 출력")
    imp.add_argument("path", type=Path)
    imp.add_argument("--project-id")
    imp.add_argument("--title")
    imp.add_argument("--replace", action="store_true", help="같은 project_id가 있으면 휴지통으로 옮기고 다시 만든다")
    imp.add_argument("--synthetic", action="store_true", help="리포트에 '합성 fixture'라고 표시")
    convo = sub.add_parser("conversation", help="대화 기록 md를 영감 책장(Casper)에 넣고 리포트를 출력")
    convo.add_argument("path", type=Path)
    convo.add_argument("--origin")
    cite = sub.add_parser("cite-report", help="책 전체 인용 집계(미확인 문헌 순위, 참고문헌 누락·미인용)")
    cite.add_argument("--project-id", required=True)
    cite.add_argument("--top", type=int, default=20)
    author = sub.add_parser("author-report", help="저자용 인용 점검 보고서(md + docx)")
    author.add_argument("--project-id", required=True)
    author.add_argument("--out", type=Path, required=True, help="md 경로. 같은 이름의 .docx도 만든다")
    author.add_argument("--date", default=None)
    alias = sub.add_parser("alias", help="사용자가 확정한 본문 표기를 문헌에 잇는다. 예: magus alias keynes1930b 케인스(1930)")
    alias.add_argument("key", help="참고문헌의 key(예: hayashi2016)")
    alias.add_argument("surface", help="본문 표기(예: 하야시(2016), 하야시)")
    terms = sub.add_parser("terms", help="프로젝트의 비인용 용어(지명·사건 등) 보기·추가·빼기")
    terms.add_argument("--project-id", required=True)
    terms.add_argument("--add", nargs="*", default=[])
    terms.add_argument("--remove", nargs="*", default=[])
    synth = sub.add_parser("synth", help="합성 fixture(원고 docx·pdf, 대화 기록 md)를 만든다")
    synth.add_argument("folder", type=Path)
    sub.add_parser("seed-demo", help="1단계 확인용 가짜 프로젝트 생성")
    sub.add_parser("reindex", help="원본 파일에서 index.sqlite 재생성")
    args = parser.parse_args(argv)

    # stdio 전송에서 stdout은 MCP 프로토콜 전용이다. 로그는 반드시 stderr로 보낸다. 내용은 로그에 남기지 않는다(logsafe).
    setup_logging()
    if args.cmd == "synth":
        from magus.synthetic import write_all

        for name, path in write_all(args.folder).items():
            print(f"{name}: {path}")
        return

    settings = Settings.from_env()
    if settings.user_id == DEFAULT_USER and (args.cmd == "seed-demo" or (args.cmd == "import" and args.synthetic)):
        # 합성·테스트 데이터는 default 사용자(실제 저자의 책장)에 넣지 않는다. 데모 책장이 저자의 취향으로 검색된다.
        parser.exit(2, "합성·데모 데이터는 default 사용자에 넣지 않습니다. USER_ID=demo 또는 USER_ID=synthetic로 실행하세요.\n")
    store = LocalStore(settings.data_dir)
    log = logging.getLogger("magus")
    log.info(
        "user_id=%s data_dir=%s files_root=%s embeddings=%s",
        settings.user_id, settings.data_dir, settings.files_root, settings.embeddings,
    )

    if args.cmd == "serve":
        from magus import transports
        from magus.embeddings import get_embedder
        from magus.server import build_server

        if args.transport == "http" and not transports.is_loopback(args.host):
            # 인증 없는 HTTP를 바깥에 열지 않는다. 원격 공개는 인증(2단계)이 켜진 뒤에만.
            parser.exit(2, f"인증 없이 {args.host}에 열 수 없습니다. 루프백(127.0.0.1)으로 실행하세요.\n")
        server = build_server(settings, store, get_embedder(settings))
        if args.transport == "stdio":
            transports.run_stdio(server)
        else:
            log.info("streamable-http: http://%s:%d%s (stateless, 인증 없음 — 로컬 전용)", args.host, args.port, transports.MCP_PATH)
            transports.run_http(server, args.host, args.port)
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
    elif args.cmd == "cite-report":
        from magus.melchior.report import build_cite_report

        print(build_cite_report(store, settings.user_id, args.project_id).render(args.top))
    elif args.cmd == "author-report":
        from datetime import date

        from magus.melchior.author_report import build_author_report, write_docx

        text = build_author_report(store, settings.user_id, args.project_id, args.date or date.today().isoformat())
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"{args.out}\n{write_docx(text, args.out.with_suffix('.docx'))}")
    elif args.cmd == "alias":
        from magus.melchior.check import after_refs_changed
        from magus.melchior.refs import add_alias

        try:
            ref, added = add_alias(store, settings.user_id, args.key, args.surface)
        except ValueError as e:
            parser.exit(2, f"{e}\n")
        linked = after_refs_changed(store, settings.user_id)  # 장별 집계와 이슈 연결을 새 alias로 다시 계산
        print(f"{ref.key} ← {added} · aliases: {', '.join(ref.aliases)} · citation 이슈 연결 변경 {linked}건")
    elif args.cmd == "terms":
        from magus.melchior.check import after_refs_changed

        current = store.get_non_citation_terms(settings.user_id, args.project_id)
        if args.add or args.remove:
            updated = [t for t in [*current, *args.add] if t not in set(args.remove)]
            store.set_non_citation_terms(settings.user_id, args.project_id, updated)
            after_refs_changed(store, settings.user_id)  # 장별 미확인 수·이슈 연결을 새 용어로 다시 계산
            current = store.get_non_citation_terms(settings.user_id, args.project_id)
        print("\n".join(current) or "(없음)")
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
