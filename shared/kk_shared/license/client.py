"""Cliente HTTP da Edge Function `ativar` (só stdlib — sem novas deps no app)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def activate(base_url: str, anon_key: str, chave: str, fingerprint: str,
             maquina: str, mac: str = "", so: str = "", timeout: float = 15.0) -> dict:
    """POST /functions/v1/ativar → {ok, token?} | {ok:false, reason}.
    reason ∈ {invalid, blocked, other_machine, offline, erro}."""
    if not base_url or not anon_key:
        return {"ok": False, "reason": "erro", "detail": "Supabase não configurado no app"}
    url = base_url.rstrip("/") + "/functions/v1/ativar"
    # mac/so alimentam a Central (painel mostra nome + MAC + SO). Vazios são ignorados lá.
    body = json.dumps({"chave": chave, "fingerprint": fingerprint,
                       "maquina": maquina, "mac": mac, "so": so}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {anon_key}",
        "apikey": anon_key,
    })
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
