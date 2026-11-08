"""Fase F2 — API ASGI (FastAPI) da NUVEM.

Expõe o MESMO contrato LibraryClient por HTTP, sobre Postgres (via DATABASE_URL),
reusando o dispatch RPC (_decode/_encode) e o escopo por papel (auth).

Rodar local (contra o Postgres do Docker):
  DATABASE_URL=postgresql+psycopg://postgres:vk@localhost:5434/videoke \
    uv run uvicorn kk_core.service.asgi:app --port 8900

Auth: token admin via env VK_ADMIN_TOKEN (no deploy). Sem token = convidado
(whitelist de leitura/pedido). A amarração com a licença Ed25519 entra no deploy.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kk_shared.events.bus import EventBus
from kk_shared.platform.paths import data_dir

from . import auth
from .server import _decode, _encode


def create_app(client=None) -> FastAPI:
    app = FastAPI(title="Videokê Família Silva — Cloud API")
    tokens = auth.load_or_create_tokens(data_dir())
    if os.environ.get("VK_ADMIN_TOKEN"):
        tokens["admin"] = os.environ["VK_ADMIN_TOKEN"]
    holder = {"client": client}

    def _client():
        if holder["client"] is None:   # lazy: só conecta no 1º uso (DATABASE_URL→Postgres)
            from kk_core.bootstrap import build_in_process_client
            holder["client"] = build_in_process_client(bus=EventBus())
        return holder["client"]

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "videoke-cloud"}

    @app.get("/resolve/{song_id}")
    def resolve_ep(song_id: str):   # G1: fonte tocável (sync → threadpool do FastAPI)
        from .resolve import resolve_source
        return resolve_source(_client(), song_id)

    @app.post("/rpc")
    async def rpc(req: Request):
        try:
            payload = await req.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": "json inválido"}, status_code=400)
        method = payload.get("method", "")
        role = auth.role_for_token(req.headers.get("authorization"), tokens)
        if not auth.authorized(role, method):
            return JSONResponse(
                {"ok": False, "error": f"método '{method}' não permitido para {role}"},
                status_code=403,
            )
        try:
            params = _decode(method, payload.get("params", {}))
            fn = getattr(_client(), method)
            return {"ok": True, "result": _encode(fn(**params))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return app


app = create_app()
