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
from fastapi.responses import HTMLResponse, JSONResponse, Response

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

    # ---- F4+: PALCO RICO servido pela nuvem (tom/ritmo/letra; PC desligado) ----
    @app.get("/", response_class=HTMLResponse)
    @app.get("/m", response_class=HTMLResponse)
    def mobile() -> str:
        from .cloud_stage import CLOUD_STAGE_HTML
        return CLOUD_STAGE_HTML

    @app.get("/poc/shifter.js")
    def shifter_js() -> Response:   # SoundTouch (worklet) — pitch de alta qualidade
        from .poc import SHIFTER_JS
        return Response(SHIFTER_JS, media_type="application/javascript")

    @app.get("/manifest.webmanifest")
    def manifest() -> Response:
        from .poc import MANIFEST
        # na nuvem a página é /m (no desktop é /m/poc) → start_url correto p/ o PWA
        return Response(MANIFEST.replace('"/m/poc"', '"/m"'),
                        media_type="application/manifest+json")

    @app.get("/sw.js")
    def sw_js() -> Response:
        from .poc import SW_JS
        return Response(SW_JS, media_type="application/javascript")

    @app.get("/poc/icon-192.png")
    def icon192() -> Response:
        from .poc import icon_png
        return Response(icon_png(192), media_type="image/png")

    @app.get("/poc/icon-512.png")
    def icon512() -> Response:
        from .poc import icon_png
        return Response(icon_png(512), media_type="image/png")

    @app.get("/poc/catalog")
    def poc_catalog(category: str | None = None, after: str | None = None) -> dict:
        from .poc import catalog
        return catalog(_client(), category=category, after=after)

    @app.get("/poc/categories")
    def poc_categories() -> dict:
        from .poc import categories
        return categories(_client())

    @app.get("/poc/search")
    def poc_search(q: str = "") -> dict:
        from .poc import search
        return search(_client(), q)

    @app.get("/poc/resolve/{song_id}")
    def poc_resolve(song_id: str, mode: str = "") -> dict:   # cloud-aware (hot-cache→Storage)
        from .resolve import resolve_source
        return resolve_source(_client(), song_id)

    @app.post("/poc/metric")
    async def poc_metric() -> dict:   # no-op na nuvem
        return {"ok": True}

    # ---- Fase D na nuvem: festa com convidado + aprovação (operador por sessão) ----
    @app.get("/operador", response_class=HTMLResponse)
    def operador_page() -> str:
        from .cloud_party import OPERATOR_HTML
        return OPERATOR_HTML

    @app.get("/festa", response_class=HTMLResponse)
    def festa_page() -> str:
        from .cloud_party import FESTA_HTML
        return FESTA_HTML

    @app.post("/op/open")
    def op_open() -> dict:
        from .cloud_party import op_token
        gs = _client().open_guest_session()
        sid = gs["session_id"]
        return {"session_id": sid, "code": gs["code"], "op_token": op_token(sid)}

    @app.get("/op/requests")
    def op_requests(session: str, token: str) -> dict:
        from .cloud_party import check_op
        if not check_op(session, token):
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        reqs = _client().list_requests(session, "pending")
        return {"items": [_encode(r) for r in reqs]}

    @app.post("/op/approve")
    async def op_approve(req: Request) -> dict:
        from .cloud_party import check_op
        b = await req.json()
        if not check_op(b.get("session", ""), b.get("token", "")):
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        _client().approve_request(b["request"])
        return {"ok": True}

    @app.post("/op/reject")
    async def op_reject(req: Request) -> dict:
        from .cloud_party import check_op
        b = await req.json()
        if not check_op(b.get("session", ""), b.get("token", "")):
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        _client().reject_request(b["request"])
        return {"ok": True}

    @app.get("/op/queue")
    def op_queue(session: str) -> dict:
        return {"items": [_encode(it) for it in _client().queue_list(session)]}

    @app.post("/op/clear")
    async def op_clear(req: Request) -> dict:   # operador esvazia a fila
        from . import playback
        from .cloud_party import check_op
        b = await req.json()
        if not check_op(b.get("session", ""), b.get("token", "")):
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        cli = _client()
        removed = 0
        for it in cli.queue_list(b.get("session", "")):
            try:
                cli.remove_queue_item(it.id)
                removed += 1
            except Exception:  # noqa: BLE001
                pass
        playback.cmd(b.get("session", ""), "goto", 0)  # cursor volta ao início
        return {"ok": True, "removed": removed}

    @app.get("/op/qr")
    def op_qr(code: str, request: Request) -> Response:
        import io
        base = str(request.base_url).rstrip("/")
        url = f"{base}/festa?c={code}"
        try:
            import segno
            buf = io.BytesIO()
            segno.make(url, error="m").save(buf, kind="png", scale=5, border=2)
            return Response(buf.getvalue(), media_type="image/png")
        except Exception:  # noqa: BLE001
            return Response(b"", media_type="image/png")

    # ---- G1: controle remoto + fila automática (cast por polling) ----
    @app.get("/pb/state")
    def pb_state(session: str) -> dict:   # player (TV) e controle leem daqui
        from . import playback
        st = playback.get_state(session)
        try:
            q = [_encode(it) for it in _client().queue_list(session)]
        except Exception:  # noqa: BLE001
            q = []
        return {"state": st, "queue": q}

    @app.post("/pb/cmd")
    async def pb_cmd(req: Request):   # controle (operador) manda — autenticado
        from . import playback
        from .cloud_party import check_op
        b = await req.json()
        if not check_op(b.get("session", ""), b.get("token", "")):
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        st = playback.cmd(b.get("session", ""), b.get("type", ""), b.get("arg"))
        return {"ok": True, "state": st}

    @app.post("/pb/ended")
    async def pb_ended(req: Request) -> dict:   # player avisa fim → avança a fila
        from . import playback
        b = await req.json()
        playback.ended(b.get("session", ""), b.get("idx", -1))
        return {"ok": True}

    @app.post("/pb/report")
    async def pb_report(req: Request) -> dict:   # player reporta o que toca (display)
        from . import playback
        b = await req.json()
        now = {k: b.get(k) for k in ("idx", "title", "singer", "t", "dur", "paused")}
        playback.report(b.get("session", ""), now)
        return {"ok": True}

    # ---- Nova música: fila de pedidos (mobile enfileira; agente do desktop baixa) ----
    @app.post("/dl/request")
    async def dl_request(req: Request) -> dict:
        from . import download_queue
        b = await req.json()
        url = (b.get("url") or "").strip()
        query = (b.get("query") or "").strip()
        if not url and not query:
            return JSONResponse({"error": "informe um link ou nome da música"}, status_code=400)
        return download_queue.enqueue(
            url=url, query=query, title=(b.get("title") or "").strip(),
            artist=(b.get("artist") or "").strip(), requested_by=(b.get("by") or "").strip())

    @app.get("/dl/list")
    def dl_list(status: str | None = None) -> dict:
        from . import download_queue
        return {"items": download_queue.list_status(status)}

    @app.post("/dl/cancel")
    async def dl_cancel(req: Request) -> dict:
        from . import download_queue
        b = await req.json()
        return download_queue.cancel(b.get("id", ""))

    @app.get("/dl/claim")
    def dl_claim(token: str, limit: int = 5):
        from . import auth as _auth, download_queue
        if _auth.role_for_token(f"Bearer {token}", tokens) != "admin":
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        return {"items": download_queue.claim(limit)}

    @app.post("/dl/cloudcache")
    async def dl_cloudcache(req: Request):
        from . import auth as _auth, download_queue
        b = await req.json()
        if _auth.role_for_token(f"Bearer {b.get('token','')}", tokens) != "admin":
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        return download_queue.register_cloud_cache(b.get("sha256", ""), b.get("url", ""))

    @app.post("/dl/complete")
    async def dl_complete(req: Request):
        from . import auth as _auth, download_queue
        b = await req.json()
        if _auth.role_for_token(f"Bearer {b.get('token','')}", tokens) != "admin":
            return JSONResponse({"error": "não autorizado"}, status_code=403)
        return download_queue.complete(b.get("id", ""), b.get("status", "done"),
                                       b.get("song_id", ""), b.get("detail", ""))

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
