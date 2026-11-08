"""Orquestra o licenciamento (sem UI). Offline-first: usa o token local; só chama
o servidor pra ativar ou renovar."""
from __future__ import annotations

import platform
import time

from . import client, store
from .config import (
    GRACE_DAYS,
    PUBLIC_KEY_B64,
    RENEW_BEFORE_DAYS,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
)
from .fingerprint import machine_fingerprint, mac_address, os_name
from .token import token_status, verify_token

_REASONS = {
    "invalid": "Chave inválida.",
    "blocked": "Licença bloqueada.",
    "other_machine": "Esta licença já está ativa em OUTRA máquina. "
                     "Peça a liberação (envie o código da máquina abaixo).",
    "offline": "Sem internet — conecte para ativar.",
    "erro": "Não foi possível ativar.",
}


def _machine_name() -> str:
    return platform.node() or "PC"


def check_license() -> tuple[str, str]:
    """Verifica a licença A CADA ABERTURA. Online: consulta o servidor (bloqueio quase
    imediato) e renova o token. Offline/erro de rede: cai na tolerância do token local
    (até vencer). Retorna (status, msg); status ∈ {'ok', 'need_activation'}."""
    fp = machine_fingerprint()
    tok = store.load_token()
    if not tok:
        return "need_activation", "Ative a licença para usar o Karaokê."
    p = verify_token(tok, PUBLIC_KEY_B64)
    if not p or p.get("fp") != fp:
        return "need_activation", "Licença não é desta máquina — ative novamente."

    # consulta o servidor (revalida status + renova). timeout curto p/ não travar offline.
    res = client.activate(SUPABASE_URL, SUPABASE_ANON_KEY, p.get("chave", ""), fp,
                          _machine_name(), mac=mac_address(), so=os_name(), timeout=8.0)
    if res.get("ok") and res.get("token"):
        ok, _ = token_status(res["token"], PUBLIC_KEY_B64, fp)
        if ok:
            store.save_token(res["token"])
            return "ok", "Licenciado."
    if res.get("reason") in ("blocked", "invalid", "other_machine"):
        store.clear_token()                       # servidor negou → trava já
        return "need_activation", _REASONS.get(res["reason"], "Licença inválida.")

    # sem internet (ou erro transitório): usa o token local enquanto for válido
    ok, _why = token_status(tok, PUBLIC_KEY_B64, fp)
    if ok:
        return "ok", "Licenciado (offline)."
    return "need_activation", "Token vencido — conecte à internet para reativar."


def activate_with_key(chave: str) -> tuple[bool, str]:
    """Ativa nesta máquina. (sucesso?, mensagem)."""
    fp = machine_fingerprint()
    res = client.activate(SUPABASE_URL, SUPABASE_ANON_KEY, chave.strip(), fp,
                          _machine_name(), mac=mac_address(), so=os_name())
    if res.get("ok") and res.get("token"):
        ok, why = token_status(res["token"], PUBLIC_KEY_B64, fp)
        if not ok:
            return False, f"Token recebido é inválido ({why})."
        store.save_token(res["token"])
        return True, "Ativado com sucesso."
    return False, _REASONS.get(res.get("reason", "erro"), "Não foi possível ativar.")


def renew_if_needed() -> None:
    """Renova o token em silêncio quando online e perto de vencer. Nunca lança."""
    try:
        fp = machine_fingerprint()
        tok = store.load_token()
        if not tok:
            return
        p = verify_token(tok, PUBLIC_KEY_B64)
        if not p or p.get("fp") != fp:
            return
        if int(p.get("exp", 0)) - time.time() > RENEW_BEFORE_DAYS * 86400:
            return
        res = client.activate(SUPABASE_URL, SUPABASE_ANON_KEY, p.get("chave", ""), fp,
                              _machine_name(), mac=mac_address(), so=os_name())
        if res.get("ok") and res.get("token"):
            ok, _ = token_status(res["token"], PUBLIC_KEY_B64, fp)
            if ok:
                store.save_token(res["token"])
    except Exception:  # noqa: BLE001 — renovação é best-effort
        pass


__all__ = ["check_license", "activate_with_key", "renew_if_needed",
           "machine_fingerprint", "GRACE_DAYS"]
