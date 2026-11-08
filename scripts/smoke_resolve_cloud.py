"""Smoke do /resolve na NUVEM — prova a arquitetura "só URLs" a partir do Render.

A nuvem NÃO guarda MP4: guarda a `source_url` e, na hora de cantar, o endpoint
`GET /resolve/{song_id}` resolve essa URL para um stream tocável via yt-dlp —
RODANDO NO SERVIDOR (IP de datacenter). O risco conhecido é o YouTube barrar
IPs de datacenter. Este script valida exatamente isso ANTES de sincronizar as
~9.800 músicas e construir o G2.

O que faz:
  1) GET /health              → a API está no ar?
  2) empurra 1 música (só catálogo + source_url, SEM MP4) via register_media
     admin — ou usa SONG_ID já existente, ou SOURCE_URL sintética.
  3) GET /resolve/{id}        → a RESOLUÇÃO acontece no Render. Veredito:
       • voltou "uri"            → ✅ YouTube responde ao Render; arquitetura OK.
       • "resolução falhou: ..." → ❌ YouTube barrou; o ERRO exato diz a mitigação
                                    (cookies / PO-token / proxy residencial).
  4) (informativo) tenta buscar alguns bytes da uri DESTA máquina. ⚠️ URLs do
     googlevideo costumam ser presas ao IP de quem resolveu (o Render), então um
     403 aqui NÃO reprova a resolução — é justamente por isso que o G2 precisa do
     PROXY de streaming na nuvem. Só reportamos.

Uso:
  CLOUD_URL=https://SEU-APP.onrender.com \
  VK_ADMIN_TOKEN=<token do Render> \
  uv run python scripts/smoke_resolve_cloud.py

  # resolver um id que já está na nuvem (pós-sync), sem empurrar nada:
  CLOUD_URL=... SONG_ID=<id> uv run python scripts/smoke_resolve_cloud.py

  # testar uma URL avulsa do YouTube (música sintética, idempotente):
  CLOUD_URL=... VK_ADMIN_TOKEN=... SOURCE_URL=https://youtu.be/XXXX \
    uv run python scripts/smoke_resolve_cloud.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

CLOUD_URL = (os.environ.get("CLOUD_URL") or "").rstrip("/")
TOKEN = os.environ.get("VK_ADMIN_TOKEN")
SONG_ID = os.environ.get("SONG_ID")
SOURCE_URL = os.environ.get("SOURCE_URL")

if not CLOUD_URL:
    sys.exit("defina CLOUD_URL (ex.: https://videoke-cloud-api.onrender.com)")


def _get(path: str, timeout: int = 90) -> dict:
    req = urllib.request.Request(CLOUD_URL + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _rpc(method: str, params: dict, timeout: int = 90) -> dict:
    body = json.dumps({"method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(CLOUD_URL + "/rpc", data=body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    if not out.get("ok"):
        raise RuntimeError(f"RPC {method} falhou: {out.get('error')}")
    return out.get("result")


def _local_song_with_source() -> dict | None:
    """Acha 1 música local com source_url do YouTube e monta o payload do push."""
    from collections import defaultdict

    from sqlalchemy import select

    from kk_core.bootstrap import build_in_process_client
    from kk_core.infrastructure.db.models import (
        ArtistModel, MediaFileModel, SongArtistModel,
    )
    from kk_shared.events.bus import EventBus
    from kk_shared.platform.paths import default_db_path, default_media_dir

    local = build_in_process_client(db_path=str(default_db_path()),
                                    media_root=str(default_media_dir()), bus=EventBus())
    with local._uow() as uow:
        s = uow.session
        q = (select(MediaFileModel)
             .where(MediaFileModel.deleted_at.is_(None))
             .where(MediaFileModel.source_url.isnot(None))
             .where(MediaFileModel.source_url.like("%youtu%"))
             .order_by(MediaFileModel.updated_at.desc())
             .limit(1))
        mf = s.execute(q).scalars().first()
        if mf is None or mf.song is None:
            return None
        names = [n for (n,) in s.execute(
            select(ArtistModel.name)
            .join(SongArtistModel, SongArtistModel.artist_id == ArtistModel.id)
            .where(SongArtistModel.song_id == mf.song.id)).all()]
        return {
            "title": mf.song.title, "artists": names,
            "duration_s": mf.duration_s, "sha256": mf.sha256,
            "source_url": mf.source_url, "source_title": mf.source_title,
            "container": mf.container, "resolution": mf.resolution,
            "source_path": mf.path or "/cloud/placeholder",
            "organize": False, "trust_artist": True,
        }


def _synthetic_payload(url: str) -> dict:
    return {
        "title": "SMOKE /resolve", "artists": ["Smoke"],
        "duration_s": 0, "source_url": url,
        "sha256": hashlib.sha256(("smoke:" + url).encode()).hexdigest(),
        "source_path": "/cloud/smoke", "organize": False, "trust_artist": True,
    }


def _push(payload: dict) -> str:
    """Empurra a música (register_media admin) e devolve o song_id da nuvem."""
    res = _rpc("register_media", {"dto": payload})
    if not res or "id" not in res:
        raise RuntimeError(f"register_media não devolveu id: {res!r}")
    return res["id"]


def _peek_stream(uri: str) -> str:
    """Informativo: tenta 1ª faixa de bytes da uri DESTA máquina (não do Render)."""
    try:
        req = urllib.request.Request(uri, method="GET", headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"HTTP {r.status} ({len(r.read())} bytes)"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} (esperado se a URL é presa ao IP do Render — G2 resolve com proxy)"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def main() -> int:
    print(f"== Smoke /resolve na nuvem: {CLOUD_URL} ==\n")

    # 1) health
    try:
        h = _get("/health", timeout=30)
        print(f"[1] /health → {h}")
    except Exception as e:  # noqa: BLE001
        print(f"[1] /health FALHOU: {type(e).__name__}: {e}")
        print("    A API não está no ar (ou a URL está errada). Pare aqui.")
        return 2

    # 2) obter um song_id resolvível na nuvem
    if SONG_ID:
        song_id = SONG_ID
        print(f"[2] usando SONG_ID existente: {song_id}")
    else:
        if not TOKEN:
            print("[2] sem VK_ADMIN_TOKEN: não dá pra empurrar música. "
                  "Passe SONG_ID de uma já sincronizada, ou o token.")
            return 2
        payload = _synthetic_payload(SOURCE_URL) if SOURCE_URL else _local_song_with_source()
        if payload is None:
            print("[2] nenhuma música local com source_url do YouTube encontrada. "
                  "Passe SOURCE_URL=https://youtu.be/... ou SONG_ID=...")
            return 2
        print(f"[2] empurrando: {payload['title']} — {', '.join(payload['artists']) or '(sem artista)'}")
        print(f"    source_url: {payload['source_url']}")
        song_id = _push(payload)
        print(f"    → song_id na nuvem: {song_id}")

    # 3) resolver NA NUVEM (yt-dlp roda no servidor da CLOUD_URL = o teste do risco)
    print("\n[3] GET /resolve/{id}  (resolução acontece no servidor da CLOUD_URL)…")
    try:
        res = _get(f"/resolve/{song_id}", timeout=120)
    except Exception as e:  # noqa: BLE001
        print(f"    chamada falhou: {type(e).__name__}: {e}")
        return 2

    if res.get("uri"):
        print(f"\n  ✅ RESOLUÇÃO OK NA NUVEM ({CLOUD_URL}) — o YouTube respondeu ao IP do servidor.")
        print(f"     título: {res.get('title')}  ·  duração: {res.get('duration_s')}s")
        print(f"     source: {res.get('source')}")
        print(f"     uri:    {res['uri'][:110]}…")
        print("\n  → A arquitetura 'só URLs, converte na hora' FUNCIONA na nuvem.")
        print("     Próximo: sync completo → F4 (mobile→nuvem) → G2 (proxy + hot-cache).")
        print(f"\n[4] (informativo) buscando bytes da uri desta máquina: {_peek_stream(res['uri'])}")
        return 0

    err = res.get("error", "(sem campo error)")
    if "resolução falhou" in err:
        print(f"\n  ❌ YOUTUBE BARROU O RENDER. Erro exato:\n     {err}")
        print("\n  → A aposta 'resolve on-demand na nuvem' precisa de mitigação. Pelo erro:")
        print("     • 'Sign in to confirm you're not a bot' / 403 → cookies ou PO-token no yt-dlp")
        print("     • bloqueio por IP → proxy residencial no resolve, OU subir o hot-cache")
        print("       (hospedar como MP4 as mais cantadas — mantém o modelo, só engorda o colchão).")
        return 1

    print(f"\n  ⚠️ Erro de setup (não é o risco do YouTube): {err}")
    print("     (música sem versão/sem fonte) — confira o SONG_ID/SOURCE_URL.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
