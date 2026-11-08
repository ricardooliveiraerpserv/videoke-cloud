"""Sincroniza o catálogo local (SQLite) para a API da nuvem, em lotes, com cursor.

Uso:
  CLOUD_URL=https://videoke-cloud-api.onrender.com \
  VK_ADMIN_TOKEN=<token do Render> \
  uv run python scripts/sync_to_cloud.py

Reexecutável: retoma do cursor salvo em ~/.videoke_sync_cursor. NÃO envia MP4.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from kk_core.bootstrap import build_in_process_client
from kk_core.service.sync import make_http_register, push_catalog
from kk_shared.events.bus import EventBus
from kk_shared.platform.paths import default_db_path, default_media_dir

CLOUD_URL = os.environ.get("CLOUD_URL")
TOKEN = os.environ.get("VK_ADMIN_TOKEN")
if not CLOUD_URL or not TOKEN:
    sys.exit("defina CLOUD_URL e VK_ADMIN_TOKEN")

CURSOR_FILE = Path.home() / ".videoke_sync_cursor"


def main() -> int:
    local = build_in_process_client(db_path=str(default_db_path()),
                                    media_root=str(default_media_dir()), bus=EventBus())
    register = make_http_register(CLOUD_URL, TOKEN)
    cursor = CURSOR_FILE.read_text(encoding="utf-8").strip() if CURSOR_FILE.exists() else None
    total = 0
    while True:
        sent, cursor = push_catalog(local, register, since_iso=cursor, limit=200)
        if not sent:
            break
        total += sent
        if cursor:
            CURSOR_FILE.write_text(cursor, encoding="utf-8")
        print(f"... {total} enviadas (cursor {cursor[:19] if cursor else '-'})", flush=True)
    print(f"OK: {total} músicas sincronizadas para {CLOUD_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
