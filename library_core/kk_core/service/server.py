"""Library Core Service (daemon) — expõe o LibraryClient via HTTP (stdlib).

- POST /rpc     {method, params}  → {ok, result|error}   (chama o client in-process)
- GET  /events  Server-Sent Events com os eventos de domínio (fila etc.)
- GET  /health  → {ok:true}

Só stdlib (http.server). Escala de bar/festa; para nuvem/internet, trocar por
um servidor ASGI mantendo o MESMO contrato do cliente.
"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic import BaseModel

from kk_shared.contracts.dtos import (
    EnqueueDTO,
    PageReq,
    PresetDTO,
    RegisterMediaDTO,
    SearchFilters,
)

# quais parâmetros de cada método são DTOs (para reconstruir a partir do JSON)
_DTO_PARAMS: dict[str, dict[str, type[BaseModel]]] = {
    "register_media": {"dto": RegisterMediaDTO},
    "enqueue": {"dto": EnqueueDTO},
    "save_preset": {"preset": PresetDTO},
    "search_songs": {"filters": SearchFilters, "page": PageReq},
    "browse_songs": {"page": PageReq},
    "browse_rows": {"page": PageReq},
    "browse_by_category": {"page": PageReq},
    "browse_by_categories": {"page": PageReq},
    "browse_by_artist": {"page": PageReq},
}


def _decode(method: str, params: dict) -> dict:
    params = dict(params or {})
    for pname, cls in _DTO_PARAMS.get(method, {}).items():
        if params.get(pname) is not None:
            params[pname] = cls.model_validate(params[pname])
    if method == "set_queue_status" and "status" in params:
        from kk_shared.contracts.enums import QueueStatus
        params["status"] = QueueStatus(params["status"])
    return params


def _encode(result):
    if result is None:
        return None
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return [_encode(x) for x in result]
    return result


class _CoreHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, client):
        super().__init__(addr, _Handler)
        self.client = client
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()
        from kk_shared.platform.paths import data_dir
        from . import auth
        self.tokens = auth.load_or_create_tokens(data_dir())  # A1: auth/escopo
        client.subscribe_all(self._broadcast)

    def _broadcast(self, ev) -> None:
        data = json.dumps({k: v for k, v in ev.__dict__.items()}, default=str)
        with self._lock:
            for q in list(self._subs):
                q.put(data)

    def add_sub(self, q) -> None:
        with self._lock:
            self._subs.add(q)

    def remove_sub(self, q) -> None:
        with self._lock:
            self._subs.discard(q)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):  # silêncio
        pass

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, html: str) -> None:
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")  # POC: evita página órfã no Safari
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        from .webapp import (
            MOBILE_HTML,
            OPERATOR_HTML,
            guest_url_from_host,
            qr_html,
        )

        if self.path in ("/", "/index.html"):
            return self._html(200, MOBILE_HTML)
        if self.path.startswith("/operador"):
            # Painel do operador (aprovar/recusar). As AÇÕES são admin: só passam
            # por localhost ou token (o /rpc barra convidado). A página é inócua.
            return self._html(200, OPERATOR_HTML)
        if self.path.startswith("/qr"):
            url = guest_url_from_host(self.headers.get("Host", ""), self.server.server_address[1])
            try:   # embute o código da sessão ativa no link do QR (Fase D)
                code = self.server.client.open_guest_session().get("code")
                if code:
                    url = f"{url}?c={code}"
            except Exception:  # noqa: BLE001
                pass
            return self._html(200, qr_html(url))
        if self.path.startswith("/health"):
            return self._json(200, {"ok": True})
        if self.path.startswith("/media/"):
            return self._serve_media(self.path[len("/media/"):].split("?")[0])
        if self.path.startswith("/events"):
            return self._sse()
        if (self.path.startswith("/m/poc") or self.path.startswith("/poc")
                or self.path.startswith("/proxy") or self.path.startswith("/manifest")
                or self.path.startswith("/sw.js") or self.path.startswith("/cert")):
            return self._poc_get()  # POC
        self._json(404, {"ok": False, "error": "not found"})

    def _poc_get(self) -> None:  # POC — Fase 0 (isolada; remover junto com poc.py)
        from urllib.parse import parse_qs, unquote, urlparse
        from . import poc
        parsed = urlparse(self.path)
        path = parsed.path
        print(f"[POC] GET {self.path}", flush=True)  # POC
        if path == "/m/poc":
            return self._html(200, poc.POC_HTML)
        if path in ("/poc/shifter.js", "/sw.js"):
            body = (poc.SHIFTER_JS if path == "/poc/shifter.js" else poc.SW_JS).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == "/manifest.webmanifest":
            body = poc.MANIFEST.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path in ("/poc/icon-192.png", "/poc/icon-512.png"):
            body = poc.icon_png(192 if "192" in path else 512)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "max-age=86400")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == "/cert":
            import os
            from kk_shared.platform.paths import data_dir
            cp = data_dir() / "daemon_cert.pem"
            if not os.path.isfile(cp):
                return self._json(404, {"ok": False, "error": "sem cert (rode com --tls)"})
            body = cp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", "attachment; filename=videoke.cer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == "/poc/catalog":
            cat = parse_qs(parsed.query).get("category", [None])[0]
            return self._json(200, poc.catalog(self.server.client, category=cat))
        if path == "/poc/categories":
            return self._json(200, poc.categories(self.server.client))
        if path == "/poc/search":
            q = parse_qs(parsed.query).get("q", [""])[0]
            return self._json(200, poc.search(self.server.client, q))
        if path.startswith("/poc/resolve/"):
            song_id = unquote(path[len("/poc/resolve/"):])
            mode = (parse_qs(parsed.query).get("mode", ["cold"])[0])
            return self._json(200, poc.resolve(self.server.client, song_id, mode))
        if path == "/poc/metrics":
            return self._json(200, {"items": poc.read_metrics()})
        if path == "/proxy":
            url = parse_qs(parsed.query).get("url", [""])[0]
            return self._serve_proxy(url)
        self._json(404, {"ok": False, "error": "not found"})

    def _serve_proxy(self, url: str) -> None:  # POC — testa se o YouTube exige proxy p/ Web Audio (CORS)
        import urllib.request
        if not url.startswith("http"):
            return self._json(400, {"ok": False, "error": "url inválida"})
        headers = {"User-Agent": "Mozilla/5.0"}
        rng = self.headers.get("Range")
        if rng:
            headers["Range"] = rng
        try:
            up = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20)
        except Exception as exc:  # noqa: BLE001
            return self._json(502, {"ok": False, "error": f"proxy: {exc}"})
        try:
            self.send_response(up.status)
            for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                v = up.headers.get(h)
                if v:
                    self.send_header(h, v)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            while True:
                chunk = up.read(1 << 20)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        finally:
            up.close()

    def do_HEAD(self) -> None:
        if self.path.startswith("/media/"):
            return self._serve_media(self.path[len("/media/"):].split("?")[0])
        self.send_response(404); self.end_headers()

    def _serve_media(self, media_file_id: str) -> None:
        """Streaming do arquivo de mídia (com Range) → o player de outra máquina toca pela LAN."""
        import mimetypes
        import os
        print(f"[POC] MEDIA {media_file_id[:12]} range={self.headers.get('Range')}", flush=True)  # POC
        from urllib.parse import unquote
        src = self.server.client.resolve_media_source(unquote(media_file_id))
        path = src.uri if src else None
        if not path or not os.path.isfile(path):
            return self._json(404, {"ok": False, "error": "media not found"})
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            try:
                s, e = rng[6:].split("-", 1)
                start = int(s) if s else 0
                end = min(int(e), size - 1) if e else size - 1
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers(); return
                status = 206
            except ValueError:
                start, end, status = 0, size - 1, 200
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")  # POC: permite Web Audio
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                remaining -= len(chunk)

    def do_POST(self) -> None:
        if self.path.startswith("/poc/metric"):  # POC
            from . import poc
            length = int(self.headers.get("Content-Length", 0))
            try:
                obj = json.loads(self.rfile.read(length).decode() or "{}")
                return self._json(200, {"ok": True, "count": poc.save_metric(obj)})
            except Exception as exc:  # noqa: BLE001
                return self._json(200, {"ok": False, "error": str(exc)})
        if not self.path.startswith("/rpc"):
            return self._json(404, {"ok": False, "error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length).decode() or "{}")
            method = payload["method"]
            from . import auth  # A1: escopo por papel (localhost=admin; rede=convidado)
            role = auth.role_for(self.client_address[0], self.headers.get("Authorization"),
                                 self.server.tokens)
            if not auth.authorized(role, method):
                return self._json(403, {"ok": False,
                                        "error": f"método '{method}' não permitido para {role}"})
            params = _decode(method, payload.get("params", {}))
            fn = getattr(self.server.client, method)
            result = _encode(fn(**params))
            self._json(200, {"ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q: queue.Queue = queue.Queue()
        self.server.add_sub(q)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=15)
                    self.wfile.write(f"data: {data}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")   # detecta desconexão
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.remove_sub(q)


class LibraryCoreService:
    def __init__(self, client, host: str = "127.0.0.1", port: int = 8770,
                 tls_cert: str | None = None, tls_key: str | None = None):
        self._httpd = _CoreHTTPServer((host, port), client)
        if tls_cert and tls_key:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(tls_cert, tls_key)
            self._httpd.socket = ctx.wrap_socket(self._httpd.socket, server_side=True)

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def start_background(self) -> "LibraryCoreService":
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
