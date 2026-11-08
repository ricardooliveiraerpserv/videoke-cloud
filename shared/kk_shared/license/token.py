"""Verificação do token de licença (assinado pelo servidor com Ed25519).

Formato do token:  <payload_b64url>.<sig_b64url>
- payload_b64url = base64url( JSON {chave, fp, exp, maquina} )
- sig            = Ed25519_sign(chave_privada, payload_b64url.encode())
O app NUNCA assina; só verifica com a chave pública. Assim, sem a privada (que fica
só no servidor), não dá pra forjar um token "válido" localmente."""
from __future__ import annotations

import base64
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_token(token: str, public_key_b64: str) -> dict | None:
    """Confere a assinatura e devolve o payload, ou None se inválido/adulterado."""
    try:
        payload_b64, sig_b64 = token.strip().split(".", 1)
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pub.verify(_b64url_decode(sig_b64), payload_b64.encode())
        return json.loads(_b64url_decode(payload_b64))
    except (InvalidSignature, ValueError, KeyError, json.JSONDecodeError):
        return None
    except Exception:  # noqa: BLE001
        return None


def token_status(token: str, public_key_b64: str, fingerprint: str,
                 now: float | None = None) -> tuple[bool, str]:
    """(válido?, motivo). Checa assinatura + máquina + validade."""
    now = int(now if now is not None else time.time())
    p = verify_token(token, public_key_b64)
    if not p:
        return False, "assinatura inválida"
    if p.get("fp") != fingerprint:
        return False, "outra máquina"
    if int(p.get("exp", 0)) < now:
        return False, "token vencido"
    return True, "ok"
