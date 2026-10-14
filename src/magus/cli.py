"""magus 명령. serve(Claude Desktop이 띄움), import, synth, seed-demo, reindex."""

from __future__ import annotations

import argparse
import dataclasses
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
    imp = sub.add_parser("import", help="원고(docx/hwpx/hwp/pdf)를 새 프로젝트로 임포트하고 전체 리포트를 출력")
    imp.add_argument("path", type=Path)
    imp.add_argument("--project-id")
    imp.add_argument("--title")
    imp.add_argument("--subtitle", help="부제. 비우면 원고에서 읽는다")
    imp.add_argument("--replace", action="store_true", help="같은 project_id가 있으면 휴지통으로 옮기고 다시 만든다(결정·미해결도)")
    imp.add_argument("--new-edition", action="store_true", help="같은 책의 새 판으로 올린다(바뀐 장만, 결정·미해결 유지)")
    imp.add_argument("--force", action="store_true", help="--new-edition: 장 제목 겹침이 30%% 미만이어도 올린다")
    imp.add_argument("--synthetic", action="store_true", help="리포트에 '합성 fixture'라고 표시")
    convo = sub.add_parser("conversation", help="대화 기록 md를 책(--book, 이름 또는 id)의 글로 넣고 리포트를 출력")
    convo.add_argument("path", type=Path)
    convo.add_argument("--origin")
    convo.add_argument("--book", required=True, help="넣을 책 이름 또는 id")
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
    inbox = sub.add_parser("inbox", help="받은함 보기·넣기·지우기(로컬 개발용. 원격에서는 웹 업로드)")
    inbox.add_argument("--add", nargs="*", type=Path, default=[])
    inbox.add_argument("--remove", nargs="*", default=[])
    terms = sub.add_parser("terms", help="프로젝트의 비인용 용어(지명·사건 등) 보기·추가·빼기")
    terms.add_argument("--project-id", required=True)
    terms.add_argument("--add", nargs="*", default=[])
    terms.add_argument("--remove", nargs="*", default=[])
    trash = sub.add_parser("trash", help="책장 휴지통(운영자용, USER_ID 사용자): list | put category|category-item <id> --note … | "
                                         "restore category|category-item|node|attachment <id> [--name 새 이름]")
    trash.add_argument("action", choices=["list", "put", "restore"])
    trash.add_argument("kind", nargs="?", choices=["category", "category-item", "node", "attachment"])
    trash.add_argument("id", nargs="?", help="category-item은 <책 id>/<글 id>, node는 <프로젝트 id>/<노드 id>, "
                                            "attachment는 <책 id>/<글 id>/<첨부 id>(문헌 글은 ref:<key>/<첨부 id>)")
    trash.add_argument("--note", default="", help="put: 휴지통으로 옮기는 이유")
    trash.add_argument("--name", default=None, help="restore category: 같은 이름이 이미 있으면 이 이름으로 되살린다")
    for name, about in (("maps", "프로젝트·지도 이전(#95, 운영자용): plan(미리보기) | apply --backup 폴더 | revert(옛 코드로 되돌리기 전)"),
                        ("floors", "옛 이름(#93). maps와 같다")):
        migrate = sub.add_parser(name, help=about)
        migrate.add_argument("action", choices=["plan", "apply", "revert"])
        migrate.add_argument("--user", action="append", default=None, help="사용자(여러 번 줄 수 있다). 없으면 USER_ID")
        migrate.add_argument("--all-users", action="store_true", help="데이터 폴더의 모든 사용자")
        migrate.add_argument("--backup", type=Path, help="apply: 사용자 책장 폴더를 복사해 둘 곳(필수)")
    synth = sub.add_parser("synth", help="합성 fixture(원고 docx·pdf, 대화 기록 md)를 만든다")
    synth.add_argument("folder", type=Path)
    sub.add_parser("seed-demo", help="1단계 확인용 가짜 프로젝트 생성")
    sub.add_parser("reindex", help="원본 파일에서 index.sqlite 재생성")
    outline = sub.add_parser("outline", help="book_outline과 같은 출력(USER_ID 사용자). 복구 확인에 쓴다")
    outline.add_argument("--project-id")
    sub.add_parser("alert-test", help="운영자 알림 채널로 시험 메시지를 보낸다")
    thumbs = sub.add_parser("thumbs", help="이미 올라간 사진 첨부의 썸네일을 한 번에 만든다(배포 때, 원본은 읽기만)")
    thumbs.add_argument("--user", action="append", default=None, help="사용자(여러 번 줄 수 있다). 없으면 USER_ID")
    thumbs.add_argument("--all-users", action="store_true", help="데이터 폴더의 모든 사용자")
    extract = sub.add_parser("extract", help="이미 올라간 첨부(문서·표·발표 자료)의 글자를 한 번에 뽑는다(배포 때, 원본은 읽기만, 첨부 폴더 안 .text/)")
    extract.add_argument("--user", action="append", default=None, help="사용자(여러 번 줄 수 있다). 없으면 USER_ID")
    extract.add_argument("--all-users", action="store_true", help="데이터 폴더의 모든 사용자")
    extract.add_argument("--force", action="store_true", help="이미 뽑은 것도 다시")
    check = sub.add_parser("extract-check", help="로컬 파일 하나(또는 여럿)에서 첨부 글자를 뽑아 보기만 한다(실제 hwp·hwpx·xlsx 확인용, "
                                                 "private/samples/). 형식·상태·쪽 수·글자 수·앞 300자만 보인다(파일 이름·본문 전체는 보이지 않는다)")
    check.add_argument("files", nargs="+", help="확인할 파일(저장소 밖이면 사용자가 경로를 준 것만)")
    warm = sub.add_parser("warm-cache", help="인용 계산 캐시를 미리 만들고(배포 때, 프로젝트 폴더 .cache/, 결정 f), "
                                             "아직 글자를 뽑지 않은 첨부(새로 뽑게 된 hwp 등)도 뽑는다. 원본은 읽기만")
    warm.add_argument("--user", action="append", default=None, help="사용자(여러 번 줄 수 있다). 없으면 USER_ID")
    warm.add_argument("--all-users", action="store_true", help="데이터 폴더의 모든 사용자")
    args = parser.parse_args(argv)
    from magus.melchior import warmer

    warmer.ENABLED = args.cmd == "serve"  # 뒤에서 데우기는 서버에서만(다른 명령은 곧 끝나 계산이 잘린다)

    # stdio 전송에서 stdout은 MCP 프로토콜 전용이다. 로그는 반드시 stderr로 보낸다. 내용은 로그에 남기지 않는다(logsafe).
    # ERROR는 운영자 알림(ALERT_*)으로도 간다. 설정이 없으면 알림은 꺼져 있다.
    from magus.alerts import sender

    alert = sender(os.environ)
    setup_logging(alert)
    if args.cmd == "alert-test":
        if alert is None:
            parser.exit(2, "알림 설정이 없습니다(ALERT_TELEGRAM_BOT_TOKEN+ALERT_TELEGRAM_CHAT_ID 또는 ALERT_WEBHOOK_URL).\n")
        alert.deliver("[Magus] 알림 시험: 이 메시지가 보이면 오류 알림이 동작합니다.")  # type: ignore[attr-defined]
        print("보냈습니다(전송 실패는 조용히 버리므로, 메신저에서 도착했는지 확인하세요).")
        return
    if args.cmd == "extract-check":  # 데이터 폴더·저장소를 열지 않는다. 파일 이름은 찍지 않는다(몇 번째 파일인지만)
        from magus.extract import check_report

        for n, name in enumerate(args.files, 1):
            print(f"[{n}/{len(args.files)}]")
            print(check_report(Path(name)))
        return
    if args.cmd == "synth":
        from magus.synthetic import write_all

        for name, path in write_all(args.folder).items():
            print(f"{name}: {path}")
        return

    try:
        settings = Settings.from_env()
    except ValueError as e:
        # 설정이 틀리면 시작하지 않는다. 이유는 stderr(운영에서는 docker compose logs)에 한국어로 남는다
        parser.exit(2, f"설정 오류로 시작하지 않습니다: {e}\n")
    if settings.user_id == DEFAULT_USER and (args.cmd == "seed-demo" or (args.cmd == "import" and args.synthetic)):
        # 합성·테스트 데이터는 default 사용자(실제 저자의 책장)에 넣지 않는다. 데모 책장이 저자의 취향으로 검색된다.
        parser.exit(2, "합성·데모 데이터는 default 사용자에 넣지 않습니다. USER_ID=demo 또는 USER_ID=synthetic로 실행하세요.\n")
    store = LocalStore(settings.data_dir)
    log = logging.getLogger("magus")
    log.info(
        "user_id=%s data_dir=%s files_root=%s embeddings=%s",
        settings.user_id if settings.auth is None else "(토큰)", settings.data_dir, settings.files_root, settings.embeddings,
    )

    if args.cmd == "serve":
        from magus import transports
        from magus.embeddings import get_embedder
        from magus.server import build_server

        from magus.auth import JwtVerifier

        if args.transport == "stdio":
            settings = dataclasses.replace(settings, auth=None)  # 로컬 모드는 USER_ID 하나. 인증 설정은 쓰지 않는다
        if args.transport == "http" and settings.auth is None and not transports.is_loopback(args.host):
            # 인증 없는 HTTP를 바깥에 열지 않는다. 원격 공개는 인증(AUTH_ISSUER 등)이 켜졌을 때만.
            parser.exit(2, f"인증 없이 {args.host}에 열 수 없습니다. 루프백(127.0.0.1)으로 실행하거나 AUTH_ISSUER를 설정하세요.\n")
        verifier = JwtVerifier(settings.auth) if settings.auth else None
        from magus import book_migrate

        # 옛 형식(#96 전: 기본 카테고리·생각·문체 파일)이 남은 사용자가 있으면 띄우지 않는다. 새 코드는 그 형식을 읽지 않는다
        serving = sorted(set(settings.auth.allowed.values())) if settings.auth else [settings.user_id]
        if stale := [u for u in serving if (store.root / "users" / u).exists() and book_migrate.needs(store, u)]:
            parser.exit(2, f"옛 형식(#96 전) 책장이 있는 사용자 {len(stale)}명: {', '.join(stale)}. 먼저 "
                           "`magus maps apply --backup <폴더> --user <id>`로 이전합니다(docs/deploy.md 2-2절).\n")
        from magus.activity import prune_all

        prune_all(store.root / "users")  # 활동 기록의 90일 지난 줄(쓸 때도 지운다)
        if args.transport == "stdio":
            transports.run_stdio(build_server(settings, store, get_embedder(settings), local_files=True))
        else:
            from magus.web import Web

            base_url = settings.auth.public_url if settings.auth else f"http://{args.host}:{args.port}"
            try:
                web = Web.create(store, settings, base_url, verifier)
            except ValueError as e:
                parser.exit(2, f"{e}\n")
            server = build_server(settings, store, get_embedder(settings), verifier, export_link=web.export_link)
            web.register(server)  # 웹 페이지 4개 + 내려받기(같은 프로세스)
            mode = f"인증: {settings.auth.issuer}, 허용 {len(settings.auth.allowed)}명" if settings.auth else "인증 없음 — 로컬 전용"
            log.info("streamable-http: http://%s:%d%s (stateless, %s)", args.host, args.port, transports.MCP_PATH, mode)
            transports.run_http(server, args.host, args.port, verifier, settings.max_request_bytes, web.http_error, web.body_limit)
    elif args.cmd == "import" and args.new_edition:
        from magus.book.reupload import reupload_manuscript

        if not args.project_id:
            parser.exit(2, "--new-edition에는 --project-id가 필요합니다.\n")
        try:
            again = reupload_manuscript(
                store, settings.user_id, args.path, args.project_id, title=args.title, subtitle=args.subtitle, force=args.force
            )
        except ValueError as e:
            parser.exit(2, f"{e}\n")
        print(again.full())
    elif args.cmd == "import":
        from magus.book.importer import import_manuscript

        report = import_manuscript(
            store,
            settings.user_id,
            args.path,
            project_id=args.project_id,
            title=args.title,
            subtitle=args.subtitle,
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
    elif args.cmd == "inbox":
        from magus.inbox import describe, save_upload

        try:
            for path in args.add:
                save_upload(store, settings.user_id, path.name, path.read_bytes(), settings.max_upload_bytes, settings.max_user_bytes)
            for name in args.remove:
                if not store.delete_inbox(settings.user_id, name):
                    print(f"없음: {name}")
        except (ValueError, OSError) as e:
            parser.exit(2, f"{e}\n")
        print(describe(store.list_inbox(settings.user_id), store.usage_bytes(settings.user_id), settings.max_user_bytes))
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
    elif args.cmd == "trash":  # 지우지 않고 옮긴다. 되살리기는 이 CLI로만 한다(#88)
        user = settings.user_id
        if args.action != "list" and not (args.kind and args.id):
            parser.exit(2, "put·restore에는 category|category-item|node와 id가 필요합니다\n")
        try:
            if args.action == "put":
                if args.kind in ("node", "attachment"):
                    parser.exit(2, "노드·첨부는 웹(지도·글 고치기)에서 휴지통으로 옮깁니다\n")
                if args.kind == "category":  # 책 통째(글 포함)
                    moved = [c.id for c in [store.trash_category(user, args.id, args.note)] if c]
                else:  # 글 하나(응답한 글도 함께, #96: 옛 생각·문체도 글)
                    book_id, _, item_id = args.id.partition("/")
                    moved = [f"{book_id}/{i.id}" for i in store.trash_item_with_replies(user, book_id, item_id, args.note)]
                if not moved:
                    parser.exit(2, f"없음: {args.kind} {args.id}\n")
                print(f"휴지통으로 옮김({user}): {args.kind} {', '.join(moved)}")
            elif args.action == "restore":
                kind = args.kind.replace("-", "_")
                name = None
                if kind == "category" and args.name:
                    from magus.category.rules import check_name, name_key

                    name = check_name(args.name, {name_key(c.name): c.name for c in store.list_categories(user)})
                if kind == "node":  # 연결 노드면 인용 점검 범위가 바뀐다(점검 13-b)
                    from magus.category.moves import restore_node

                    restored = restore_node(store, user, args.id)
                else:
                    restored = store.restore_trash(user, kind, args.id, name=name)
                print(f"되살림({user}): {args.kind} {', '.join(restored)}")
        except ValueError as e:
            parser.exit(2, f"{e}\n")
        items = store.list_trash(user)
        print(f"휴지통({user}) {len(items)}개")
        for t in items:
            print(f"- {t.kind} {t.id} · {t.trashed_at} · {t.note or '-'}" + (f" · 함께 옮긴 글 {t.with_id}" if t.with_id else "")
                  + f" · “{t.preview[:40]}”" + (f" · {t.detail}" if t.detail else ""))
    elif args.cmd == "thumbs":  # 사진 썸네일(2026-10-09). 첨부 폴더 안 .thumb/에 쓰고 원본은 건드리지 않는다
        from magus.thumbs import THUMB_DIR, THUMB_NAME, thumbnailable

        folders = store.root / "users"  # 첨부는 파일에만 있으므로 사용자도 폴더에서 찾는다(색인의 users는 프로젝트가 있는 사람만)
        everyone = sorted(p.name for p in folders.iterdir() if p.is_dir()) if folders.is_dir() else []
        for user in everyone if args.all_users else (args.user or [settings.user_id]):
            made = have = failed = 0
            for owner, att in store.file_attachments(user, (".png", ".jpg", ".jpeg", ".gif", ".webp")):
                if not thumbnailable(att.name):
                    continue
                hit = store.attachment_path(user, owner, att.id)
                if hit and (hit[0].parent / THUMB_DIR / THUMB_NAME).is_file():
                    have += 1
                elif store.attachment_thumb(user, owner, att.id):
                    made += 1
                else:
                    failed += 1  # 화면은 원본을 쓴다
            print(f"{user}: 만듦 {made} · 이미 있음 {have} · 못 만듦(원본으로 보임) {failed}")
    elif args.cmd == "extract":  # 첨부 글자(#100). 개수만 보인다(파일 이름·글자는 보이지 않는다)
        folders = store.root / "users"
        everyone = sorted(p.name for p in folders.iterdir() if p.is_dir()) if folders.is_dir() else []
        for user in everyone if args.all_users else (args.user or [settings.user_id]):
            counts = store.extract_all(user, force=args.force)
            print(f"{user}: " + " · ".join(f"{k} {v}" for k, v in counts.items()))
    elif args.cmd == "warm-cache":  # 인용 계산 캐시(결정 f) + 아직 뽑지 않은 첨부 글자(2026-10-11). 프로젝트 id·개수·시간만 보인다
        import time

        from magus.melchior.cache import warm as warm_cites

        folders = store.root / "users"
        everyone = sorted(p.name for p in folders.iterdir() if p.is_dir()) if folders.is_dir() else []
        for user in everyone if args.all_users else (args.user or [settings.user_id]):
            for project_id in warmer.projects_with_manuscript(store, user):
                started = time.monotonic()
                warm_cites(store, user, project_id)
                print(f"{user}/{project_id}: {time.monotonic() - started:.1f}초")
            started = time.monotonic()
            counts = store.extract_all(user)  # 상태가 없는 것(형식을 늘리기 전에 올라간 hwp 등)만 뽑는다. 이미 뽑은 것은 그대로
            print(f"{user}: 첨부 글자 " + " · ".join(f"{k} {v}" for k, v in counts.items()) + f" · {time.monotonic() - started:.1f}초")
    elif args.cmd in ("maps", "floors"):  # 프로젝트·지도 이전(#95, 층 이전 #93을 포함). 실행은 백업 뒤에, 전후 비교를 보인다
        from magus import map_migrate as floor_migrate

        users = store.list_users() if args.all_users else (args.user or [settings.user_id])
        if args.action == "apply" and args.backup is None:
            parser.exit(2, "apply에는 --backup 폴더가 필요합니다(사용자 책장 폴더를 먼저 복사해 둡니다).\n")
        failed = False
        for user in users:
            if args.action == "plan":
                lines = floor_migrate.plan(store, user)
            elif args.action == "apply":
                args.backup.mkdir(parents=True, exist_ok=True)
                lines, same = floor_migrate.apply(store, user, args.backup)
                failed |= not same
            else:
                lines = floor_migrate.revert(store, user)
            print("\n".join(lines) + "\n")
        if failed:
            parser.exit(1, "전후가 다른 사용자가 있습니다. 위 보고를 확인하세요(백업에서 되살릴 수 있습니다).\n")
    elif args.cmd == "conversation":
        from magus.casper.tools import add_conversation
        from magus.category.books import writable_book
        from mcp.server.mcpserver.exceptions import ToolError

        try:
            book = writable_book(store, settings.user_id, args.book)
        except ToolError as e:
            parser.exit(2, f"{e}\n")
        report, ideas = add_conversation(
            store, settings.user_id, args.path.read_text(encoding="utf-8"), args.origin or args.path.stem, book.key
        )
        print(f"{args.path.name}: {report}\n「{book.name}」에 저장 {len(ideas)}건")
    elif args.cmd == "seed-demo":
        from magus.book.demo import seed_demo, seed_demo_shelf
        from magus.book.outline import build_outline

        project, created = seed_demo(store, settings.user_id)
        if created:
            seed_demo_shelf(store, settings.user_id)
        print(f"{'생성' if created else '이미 있음'}: {project.id} ({project.title})\n")
        print(build_outline(store, settings.user_id, project.id))
    elif args.cmd == "outline":
        from magus.book.outline import build_outline
        from magus.melchior.check import refresh_cite_counts

        refresh_cite_counts(store, settings.user_id)  # 파생값(장별 미확인)을 맞춘 뒤 서버와 같은 출력
        print(build_outline(store, settings.user_id, args.project_id))
    elif args.cmd == "reindex":
        from magus.melchior.check import after_refs_changed

        store.reindex()
        for user_id in store.list_users():
            after_refs_changed(store, user_id)  # 파생값(장별 미확인 인용 수, citation 이슈 연결) 다시 계산
        print(f"재생성 완료: {settings.data_dir / 'index.sqlite'}")
