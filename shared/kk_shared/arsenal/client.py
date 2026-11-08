"""Cliente HTTP da Edge Function `arsenal` (só stdlib — sem novas deps no app).

- pull(): baixa o arsenal (manifesto) da nuvem — livre, sem senha.
- push(senha, songs): envia o arsenal e faz o MERGE no servidor — exige a senha
  master (validada no servidor; nunca fica salva no cliente).

Usa o mesmo projeto Supabase do licenciamento (SUPABASE_URL/ANON_KEY em
kk_shared.license.config). A anon key é pública por design.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..license.config import SUPABASE_ANON_KEY, SUPABASE_URL


def _post(payload: dict, *, base_url: str = "", anon_key: str = "", timeout: float = 30.0) -> dict:
    base = (base_url or SUPABASE_URL).rstrip("/")
    key = anon_key or SUPABASE_ANON_KEY
    if not base or not key:
        return {"ok": False, "reason": "config", "detail": "Supabase não configurado no app"}
    url = f"{base}/functions/v1/arsenal"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "apikey": key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return {"ok": False, "reason": "erro", "detail": f"http {e.code}"}
    except urllib.error.URLError as e:
        return {"ok": False, "reason": "offline", "detail": str(e.reason)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "erro", "detail": str(e)}


def pull(*, base_url: str = "", anon_key: str = "", timeout: float = 30.0) -> dict:
    """Baixa o arsenal atual: {ok, count, songs:[{url,artista,musica,categoria}], updated_at}."""
    return _post({"action": "pull"}, base_url=base_url, anon_key=anon_key, timeout=timeout)


def push(senha: str, songs: list[dict], *, base_url: str = "", anon_key: str = "",
         timeout: float = 60.0) -> dict:
    """Envia o arsenal e faz o merge no servidor.
    Retorna {ok, added, updated, total} | {ok:false, reason} — reason ∈
    {senha, vazio, config, offline, erro}."""
    return _post({"action": "push", "senha": senha, "songs": songs},
                 base_url=base_url, anon_key=anon_key, timeout=timeout)
