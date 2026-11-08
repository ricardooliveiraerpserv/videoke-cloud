"""Entry e gerenciamento do Library Core Service (daemon).

  kk-libraryd                      # roda (127.0.0.1:8770)
  kk-libraryd run --host 0.0.0.0   # roda aceitando a LAN (celulares)
  kk-libraryd install              # autostart no login (macOS: launchd)
  kk-libraryd uninstall
"""
from __future__ import annotations

import argparse
import json
import plistlib
import subprocess
import sys
from pathlib import Path

from kk_shared.events.bus import EventBus
from kk_shared.platform.paths import data_dir, default_db_path, default_media_dir

from ..application.watch_service import WatchService
from ..bootstrap import build_in_process_client
from .server import LibraryCoreService

LABEL = "com.ricardo.karaoke.libraryd"


def _watch_config() -> Path:
    return data_dir() / "watch_dirs.json"


def _merge_watch_dirs(new: list[str]) -> list[str]:
    cfg = _watch_config()
    existing: list[str] = []
    if cfg.exists():
        try:
            existing = json.loads(cfg.read_text())
        except Exception:  # noqa: BLE001
            existing = []
    merged = list(dict.fromkeys([*existing, *new]))   # união preservando ordem
    cfg.write_text(json.dumps(merged, indent=2))
    return merged


def _run(args) -> int:
    client = build_in_process_client(
        db_path=str(default_db_path()), media_root=str(default_media_dir()), bus=EventBus()
    )
    tls_cert = tls_key = None
    scheme = "http"
    if getattr(args, "tls", False):
        from .tls import ensure_cert
        from .webapp import lan_ip
        tls_cert, tls_key = ensure_cert(data_dir(), extra_ips=[lan_ip()])
        scheme = "https"
    svc = LibraryCoreService(client, host=args.host, port=args.port,
                             tls_cert=tls_cert, tls_key=tls_key)

    watcher = None
    watch_dirs = _merge_watch_dirs(list(getattr(args, "watch", None) or []))
    if watch_dirs:
        watcher = WatchService(client, on_added=lambda t: print(f"[watch] catalogado: {t}"))
        active = watcher.start(watch_dirs)
        print(f"Vigiando pastas ({len(active)}): {', '.join(active) or '—'}")

    print(f"Library Core Service em {scheme}://{args.host}:{args.port}  (Ctrl+C para sair)")
    try:
        svc.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if watcher:
            watcher.stop()
        svc.stop()
    return 0


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _install(args) -> int:
    if not sys.platform == "darwin":
        print("Autostart automático implementado no macOS (launchd).")
        print("Windows: crie uma Tarefa Agendada 'Ao efetuar logon' executando:")
        print(f'  "{sys.executable}" -m kk_core.service.daemon run --host {args.host} --port {args.port}')
        return 0
    log = data_dir() / "daemon.log"
    plist = {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable, "-m", "kk_core.service.daemon", "run",
            "--host", args.host, "--port", str(args.port),
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    path = _plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(path)], check=False)
    print(f"Instalado e iniciado no login: {path}")
    print(f"Ouça na LAN: http://<ip-do-mac>:{args.port}  | log: {log}")
    return 0


def _uninstall(_args) -> int:
    path = _plist_path()
    if path.exists():
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        path.unlink()
        print("Autostart removido.")
    else:
        print("Nada instalado.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]

    p = argparse.ArgumentParser(prog="kk-libraryd")
    sub = p.add_subparsers(dest="cmd")
    for name, fn in (("run", _run), ("install", _install), ("uninstall", _uninstall)):
        sp = sub.add_parser(name)
        sp.add_argument("--host", default="127.0.0.1" if name == "run" else "0.0.0.0")
        sp.add_argument("--port", type=int, default=8770)
        if name == "run":
            sp.add_argument("--watch", action="append", metavar="PASTA",
                            help="pasta a monitorar e catalogar automaticamente (repetível)")
            sp.add_argument("--tls", action="store_true",
                            help="serve HTTPS (cert self-signed) p/ habilitar AudioWorklet no Safari")
        sp.set_defaults(func=fn)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
