"""Fase A1 — autenticação/escopo do daemon HTTP.

Regra (simples e não-quebra-nada):
  • localhost (127.0.0.1/::1) → ADMIN. O desktop fala com o daemon por localhost,
    então continua com acesso total sem token.
  • rede (LAN/celular) → CONVIDADO por padrão: só pode chamar os métodos da
    whitelist (leitura + pedir música). Métodos destrutivos → 403.
  • token ADMIN (Bearer) → ADMIN mesmo pela rede (uso administrativo remoto futuro).

Assim, qualquer um na Wi-Fi NÃO consegue mais chamar purge_songs/blacklist/delete.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

# Métodos que um CONVIDADO (rede, sem token admin) pode chamar: leitura + pedir música.
GUEST_METHODS = frozenset({
    # busca / catálogo (leitura)
    "search_songs", "browse_songs", "browse_rows", "browse_by_category",
    "browse_by_categories", "browse_by_artist", "get_song", "list_artists",
    "list_artists_detail", "list_categories", "has_media_url", "existing_media_urls",
    # letras
    "get_lyrics",
    # sessão de convidado (Fase D): entrar por código e PEDIR (não enfileira
    # direto — o operador aprova). Acompanhar a fila é leitura.
    "session_by_code", "request_song", "queue_list", "current_queue_item",
    # favoritos / histórico (leitura)
    "is_favorite", "list_favorites", "list_history",
    # fonte de reprodução
    "resolve_media_source",
})

_LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


def is_local(ip: str | None) -> bool:
    return (ip or "").split("%")[0] in _LOCAL


def load_or_create_tokens(data_dir: Path) -> dict:
    """Carrega (ou gera) os tokens persistentes do daemon."""
    p = data_dir / "daemon_tokens.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("admin") and data.get("guest"):
                return data
        except Exception:  # noqa: BLE001
            pass
    toks = {"admin": secrets.token_urlsafe(24), "guest": secrets.token_urlsafe(16)}
    data_dir.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(toks), encoding="utf-8")
    return toks


def role_for(client_ip: str | None, auth_header: str | None, tokens: dict) -> str:
    """Papel do chamador: 'admin' ou 'guest' (rede sem token = guest)."""
    if is_local(client_ip):
        return "admin"
    tok = ""
    if auth_header and auth_header.lower().startswith("bearer "):
        tok = auth_header[7:].strip()
    if tok and tok == tokens.get("admin"):
        return "admin"
    return "guest"


def role_for_token(auth_header: str | None, tokens: dict) -> str:
    """Papel na NUVEM (sem exceção de localhost): token admin → admin; senão convidado."""
    tok = ""
    if auth_header and auth_header.lower().startswith("bearer "):
        tok = auth_header[7:].strip()
    if tok and tok == tokens.get("admin"):
        return "admin"
    return "guest"


def authorized(role: str, method: str) -> bool:
    if role == "admin":
        return True
    if role == "guest":
        return method in GUEST_METHODS
    return False
