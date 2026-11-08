"""CLI do Downloader — Fase 1 (prova a integração sem depender de GUI).

  kk-download search "Chitãozinho e Xororó" [--deep]
  kk-download get <url> [--artist "Chitãozinho e Xororó"] [--audio]
  kk-download library "evidencias"      # busca no acervo (Library Core)
"""
from __future__ import annotations

import argparse
import sys

from kk_shared.platform.paths import default_db_path, default_media_dir

from .bootstrap import build_downloader


def _fmt_dur(s: int) -> str:
    m, sec = divmod(int(s or 0), 60)
    return f"{m}:{sec:02d}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kk-download")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="pesquisa no YouTube")
    s.add_argument("query")
    s.add_argument("--deep", action="store_true")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--cookies", default="")

    g = sub.add_parser("get", help="baixa uma URL e cataloga no Library Core")
    g.add_argument("url")
    g.add_argument("--artist", default=None)
    g.add_argument("--title", default=None)
    g.add_argument("--audio", action="store_true")
    g.add_argument("--height", type=int, default=720)
    g.add_argument("--cookies", default="")

    lib = sub.add_parser("library", help="busca no acervo já catalogado")
    lib.add_argument("query")

    imp = sub.add_parser("import", help="cataloga uma pasta de mídia já baixada (não move)")
    imp.add_argument("folder")
    imp.add_argument("--artist", default=None, help="força o artista (senão detecta pela pasta)")
    imp.add_argument("--no-recursive", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "import":
        from kk_shared.client.factory import get_library_client
        from .application.import_service import ImportFolderUseCase
        # via daemon; organize=False no DTO referencia os arquivos no lugar
        library = get_library_client()
        uc = ImportFolderUseCase(library)

        def iprog(i, total, title):
            sys.stdout.write(f"\r  [{i}/{total}] {title[:48]:<48}")
            sys.stdout.flush()
        res = uc.execute(args.folder, recursive=not args.no_recursive,
                         artist_hint=args.artist, progress=iprog)
        print(f"\n✅ {res['added']} de {res['total']} catalogadas (falhas: {res['failed']}).")
        return 0

    app = build_downloader()

    if args.cmd == "search":
        hits = app.search.execute(args.query, deep=args.deep, limit=args.limit, cookies=args.cookies)
        print(f"{len(hits)} resultado(s):\n")
        for i, h in enumerate(hits, 1):
            print(f"{i:>3}. [{_fmt_dur(h.duration_s)}] {h.title[:60]}  · {h.channel}")
            print(f"     {h.url}")
        return 0

    if args.cmd == "get":
        print("baixando…")
        def prog(pct, spd):
            sys.stdout.write(f"\r  {pct:5.1f}%  {spd}   ")
            sys.stdout.flush()
        view = app.download.execute(
            args.url, audio_only=args.audio, max_height=args.height,
            artist_hint=args.artist, title_hint=args.title, cookies=args.cookies,
            progress=prog,
        )
        print(f"\n✅ catalogado: {view.title}  · {', '.join(view.artists)}")
        print(f"   versões: {view.version_count} | id: {view.id}")
        return 0

    if args.cmd == "library":
        page = app.library.search_songs(args.query)
        print(f"{page.total_estimate} no acervo:\n")
        for it in page.items:
            print(f"  • {it.title}  · {', '.join(it.artists)}  ({it.version_count} versão/ões)")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
