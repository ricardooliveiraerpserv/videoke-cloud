"""FASE 0 — POC Mobile (ISOLADA e REMOVÍVEL).

Prova "cantar pelo celular" com mudança estrutural ~zero: roda no daemon atual
na LAN, só ADICIONA endpoints read-only + uma página autocontida com <video> +
pitch-shifter granular (nó Web Audio, sem WASM/CDN) + instrumentação de latência.

NÃO toca em banco/contrato/player. Para remover a POC: apagar este arquivo e as
4 linhas de rota em server.py (marcadas com "# POC").

Endpoints (todos aditivos):
  GET  /m/poc              → a página da POC
  GET  /poc/shifter.js     → AudioWorkletProcessor (pitch granular)
  GET  /poc/catalog        → lista leve de músicas p/ escolher
  GET  /poc/resolve/<id>?mode=cold|hot → {kind, uri, duration_s, title, artist}
  GET  /proxy?url=...       → stream remoto c/ CORS+Range (testar se YouTube exige proxy)
  POST /poc/metric          → grava medição em ~/.karaoke_poc_metrics.jsonl
  GET  /poc/metrics         → devolve as medições gravadas (p/ análise)
"""
from __future__ import annotations

import json
from pathlib import Path

METRICS_PATH = Path.home() / ".karaoke_poc_metrics.jsonl"


# ---------------------------------------------------------------- dados (puros)
def _light_song(s) -> dict:
    """Projeta um SongView no formato leve da lista do celular."""
    v = s.versions[0] if s.versions else None
    fmt = ""
    if v:
        parts = [p for p in [(v.container or "").upper() or None, v.resolution] if p]
        fmt = " · ".join(parts)
    return {"id": s.id, "title": s.title,
            "artist": ", ".join(s.artists) if s.artists else "",
            "dur": (v.duration_s if v else 0), "fmt": fmt}


def catalog(client, limit: int = 300, category: str | None = None,
            after: str | None = None) -> dict:
    """Lista leve p/ o celular. Sem categoria → browse_rows paginado (cursor `after`
    → `next`). Com categoria → browse_by_category."""
    from kk_shared.contracts.dtos import PageReq
    if category:
        page = client.browse_by_category(category, PageReq(limit=2000))
        return {"items": [_light_song(s) for s in page.items]}
    page = client.browse_rows(PageReq(limit=limit, after=after))
    items = [{
        "id": r.id,
        "title": r.title,
        "artist": ", ".join(r.artists) if r.artists else "",
        "dur": r.duration_s,
        "fmt": r.format_label or "",
    } for r in page.items]
    return {"items": items, "next": page.next_cursor}


def search(client, query: str) -> dict:
    """Busca FTS no acervo INTEIRO (não só nas carregadas)."""
    from kk_shared.contracts.dtos import PageReq
    page = client.search_songs(query, None, PageReq(limit=300))
    return {"items": [_light_song(s) for s in page.items]}


def categories(client) -> dict:
    """Estilos (Sertanejo, Pagode, …) p/ os chips de filtro."""
    cats = client.list_categories()
    return {"items": [{"id": c.id, "name": c.name, "count": getattr(c, "song_count", 0)}
                      for c in cats]}


def resolve(client, song_id: str, mode: str) -> dict:
    """Resolve a fonte de reprodução.

    hot  → arquivo local servido por /media/<id> (nosso "cache" da POC).
    cold → URL progressiva do YouTube via yt-dlp (import em runtime do downloader).
    """
    song = client.get_song(song_id)
    if not song or not song.versions:
        return {"error": "música sem versão tocável"}
    v = song.versions[0]
    title = song.title
    artist = ", ".join(song.artists) if song.artists else ""

    def _local():
        return {"kind": "local", "uri": f"/media/{v.id}",
                "duration_s": v.duration_s, "title": title, "artist": artist}

    # auto (padrão) e hot preferem o arquivo local (instantâneo); cold força YouTube.
    if mode != "cold" and v.path:
        return _local()
    if v.source_url:
        try:
            from kk_downloader.infrastructure.ytdlp_adapter import YtDlpBackend
            url = YtDlpBackend().stream_url(v.source_url, max_height=720)
            return {"kind": "youtube", "uri": url, "source_url": v.source_url,
                    "duration_s": v.duration_s, "title": title, "artist": artist}
        except Exception as exc:  # noqa: BLE001
            if v.path:
                return _local()
            return {"error": f"resolução falhou: {type(exc).__name__}: {exc}"}
    if v.path:
        return _local()
    return {"error": "sem fonte tocável (sem arquivo local nem link)"}


def save_metric(obj: dict) -> int:
    with METRICS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return sum(1 for _ in METRICS_PATH.open(encoding="utf-8"))


def read_metrics() -> list[dict]:
    if not METRICS_PATH.exists():
        return []
    out = []
    for line in METRICS_PATH.open(encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


# ------------------------------------------------------------- PWA (B4)
# Ícone gerado em Python puro (sem Pillow): microfone branco sobre quadrado roxo
# arredondado. PNG RGBA via zlib. Cacheado por tamanho.
_ICON_CACHE: dict[int, bytes] = {}


def _png_rgba(width: int, height: int, raw_rgba: bytes) -> bytes:
    import struct
    import zlib
    stride = width * 4
    buf = bytearray()
    for y in range(height):
        buf.append(0)  # filtro "none"
        buf.extend(raw_rgba[y * stride:(y + 1) * stride])
    comp = zlib.compress(bytes(buf), 9)

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


def icon_png(size: int) -> bytes:
    if size in _ICON_CACHE:
        return _ICON_CACHE[size]
    S = size

    def rr(px, py, x0, y0, x1, y1, rad):
        qx = min(max(px, x0 + rad), x1 - rad)
        qy = min(max(py, y0 + rad), y1 - rad)
        return (px - qx) ** 2 + (py - qy) ** 2 <= rad * rad

    cx = S / 2
    body_r = S * 0.13
    buf = bytearray(S * S * 4)
    for y in range(S):
        t = y / S
        # gradiente roxo→índigo (#8B5CF6 → #6366F1)
        br = int(139 + (99 - 139) * t)
        bg = int(92 + (102 - 92) * t)
        bb = int(246 + (241 - 246) * t)
        for x in range(S):
            i = (y * S + x) * 4
            mic = (rr(x, y, cx - body_r, S * 0.20, cx + body_r, S * 0.56, body_r)
                   or rr(x, y, cx - S * 0.025, S * 0.56, cx + S * 0.025, S * 0.72, S * 0.025)
                   or rr(x, y, cx - S * 0.17, S * 0.745, cx + S * 0.17, S * 0.80, S * 0.027))
            if mic:
                buf[i:i + 4] = bytes((255, 255, 255, 255))
            elif rr(x, y, 0, 0, S, S, S * 0.22):
                buf[i:i + 4] = bytes((br, bg, bb, 255))
            # senão transparente (zeros)
    png = _png_rgba(S, S, bytes(buf))
    _ICON_CACHE[size] = png
    return png


MANIFEST = json.dumps({
    "name": "Videokê Família Silva",
    "short_name": "Videokê",
    "start_url": "/m/poc",
    "scope": "/",
    "display": "standalone",
    "orientation": "landscape",
    "background_color": "#0B1120",
    "theme_color": "#0B1120",
    "icons": [
        {"src": "/poc/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/poc/icon-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "any maskable"},
    ],
}, ensure_ascii=False)


SW_JS = r"""
// G2 — offline real. Casca + catálogo (navega offline) + mídia baixada (canta
// offline). A mídia (R2) é cache-first COM suporte a Range (o <video> pede faixas
// de bytes; sem isso o vídeo não toca do cache). O download em si é feito pela
// página (window.caches), aqui só servimos.
const SHELL='vk-shell-v2', MEDIA='vk-media-v1';
const SHELL_ASSETS=['/m','/poc/shifter.js','/manifest.webmanifest','/poc/icon-192.png','/poc/icon-512.png'];

self.addEventListener('install', e=>{ e.waitUntil((async()=>{
  const c=await caches.open(SHELL);
  await Promise.allSettled(SHELL_ASSETS.map(u=>c.add(u)));  // tolerante a 404 (desktop usa /m/poc)
  await self.skipWaiting();
})()); });

self.addEventListener('activate', e=>{ e.waitUntil((async()=>{
  const ks=await caches.keys();
  await Promise.all(ks.filter(k=>k.startsWith('vk-')&&k!==SHELL&&k!==MEDIA).map(k=>caches.delete(k)));
  await self.clients.claim();
})()); });

function isMedia(u){ return /r2\.dev|r2\.cloudflarestorage|\.mp4(\?|$)/i.test(u); }

async function serveMedia(req){
  const cache=await caches.open(MEDIA);
  const hit=await cache.match(req.url,{ignoreVary:true});
  if(!hit){ try{ return await fetch(req); }catch(_){ return new Response('',{status:504}); } }
  const range=req.headers.get('range');
  if(!range) return hit;                         // sem Range: devolve inteiro
  const buf=await hit.arrayBuffer();
  const m=/bytes=(\d+)-(\d*)/.exec(range)||[0,'0',''];
  let start=+m[1]||0, end=m[2]?+m[2]:buf.byteLength-1;
  if(end>=buf.byteLength) end=buf.byteLength-1;
  const chunk=buf.slice(start,end+1);
  return new Response(chunk,{status:206,headers:{
    'Content-Range':'bytes '+start+'-'+end+'/'+buf.byteLength,
    'Accept-Ranges':'bytes','Content-Length':String(chunk.byteLength),
    'Content-Type':hit.headers.get('Content-Type')||'video/mp4',
    'Access-Control-Allow-Origin':'*'}});
}

self.addEventListener('fetch', e=>{
  const req=e.request; if(req.method!=='GET') return;
  const url=req.url;
  if(isMedia(url)){ e.respondWith(serveMedia(req)); return; }        // mídia: cache-first (+Range)
  if(req.mode==='navigate'){                                         // abrir app: network, cai p/ casca
    e.respondWith((async()=>{ try{ return await fetch(req); }
      catch(_){ const c=await caches.open(SHELL); return (await c.match('/m'))||Response.error(); } })()); return; }
  const u=new URL(url); if(u.origin!==self.location.origin) return;  // outros cross-origin: rede
  if(/^\/poc\/(catalog|categories|search)/.test(u.pathname)){        // catálogo/busca: network+cache
    e.respondWith((async()=>{ try{ const r=await fetch(req); (await caches.open(SHELL)).put(req,r.clone()); return r; }
      catch(_){ const m=await caches.match(req,{ignoreVary:true}); return m||new Response('{"items":[]}',{headers:{'Content-Type':'application/json'}}); } })()); return; }
  if(/^\/(poc\/shifter\.js|manifest\.webmanifest|poc\/icon-)/.test(u.pathname)){  // casca: network+cache fallback
    e.respondWith((async()=>{ try{ const r=await fetch(req); (await caches.open(SHELL)).put(req,r.clone()); return r; }
      catch(_){ return (await caches.match(req))||Response.error(); } })()); return; }
  // resto: rede normal (passthrough)
});
"""


# --------------------------- AudioWorklet: pitch de ALTA QUALIDADE (SoundTouch)
# Núcleo SoundTouch (Olli Parviainen, LGPL 2.1) vendorizado em soundtouch_core.js
# + adaptador streaming abaixo. Pitch-only (duração preservada): st.pitch=ratio.
# Mantém o nome 'granular-pitch' p/ o resto do código não mudar.
_SOUNDTOUCH_CORE = (Path(__file__).parent / "soundtouch_core.js").read_text(encoding="utf-8")
_ST_ADAPTER = r"""
class STPitch extends AudioWorkletProcessor {
  static get parameterDescriptors() {
    return [{name:'ratio', defaultValue:1, minValue:0.25, maxValue:4, automationRate:'k-rate'}];
  }
  constructor() {
    super();
    this.st = new SoundTouch(); this.st.tempo = 1; this.st.rate = 1; this.st.pitch = 1; this.p = 1;
    this.inter = new Float32Array(256);
    const RB = 1 << 16; this.ring = new Float32Array(RB); this.mask = RB - 1;
    this.head = 0; this.tail = 0; this.count = 0;   // em amostras (interleaved)
    this.tmp = new Float32Array(1 << 14);
    this.underruns = 0; this.frames = 0;
  }
  _push(a, len) {
    for (let i = 0; i < len; i++) {
      this.ring[this.tail] = a[i]; this.tail = (this.tail + 1) & this.mask;
      if (this.count < this.ring.length) this.count++; else this.head = (this.head + 1) & this.mask;
    }
  }
  process(inputs, outputs, params) {
    const inp = inputs[0], out = outputs[0], n = out[0].length;
    const ratio = params.ratio[0];
    if ((ratio > this.p ? ratio - this.p : this.p - ratio) > 1e-4) { this.st.pitch = ratio; this.p = ratio; }
    if (inp && inp[0] && inp[0].length) {
      const L = inp[0], R = inp[1] || inp[0];
      if (this.inter.length < n * 2) this.inter = new Float32Array(n * 2);
      for (let i = 0; i < n; i++) { this.inter[2 * i] = L[i]; this.inter[2 * i + 1] = R[i]; }
      this.st.inputBuffer.putSamples(this.inter, 0, n);
      this.st.process();
      const avail = this.st.outputBuffer.frameCount;
      if (avail > 0) {
        if (this.tmp.length < avail * 2) this.tmp = new Float32Array(avail * 2);
        this.st.outputBuffer.receiveSamples(this.tmp, avail);
        this._push(this.tmp, avail * 2);
      }
    }
    const outL = out[0], outR = out[1] || out[0], need = n * 2;
    if (this.count >= need) {
      for (let i = 0; i < n; i++) {
        outL[i] = this.ring[this.head];
        const rr = this.ring[(this.head + 1) & this.mask];
        if (out[1]) outR[i] = rr;
        this.head = (this.head + 2) & this.mask;
      }
      this.count -= need;
    } else { for (let i = 0; i < n; i++) { outL[i] = 0; if (out[1]) outR[i] = 0; } this.underruns++; }
    this.frames++; if (this.frames % 200 === 0) this.port.postMessage({underruns: this.underruns});
    return true;
  }
}
registerProcessor('granular-pitch', STPitch);
"""
SHIFTER_JS = _SOUNDTOUCH_CORE + "\n" + _ST_ADAPTER


# ------------------------------------------------------------------ a página
POC_HTML = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0B1120">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Videokê">
<link rel="apple-touch-icon" href="/poc/icon-192.png">
<title>Videokê Família Silva</title>
<style>
 :root{--bg:#0B1120;--card:#161E31;--fg:#E8ECF6;--muted:#9AA6C0;--accent:#8B5CF6;--cyan:#22D3EE;--good:#34D399;--bad:#F87171;--warn:#FBBF24}
 *{box-sizing:border-box} html,body{margin:0;height:100%}
 body{background:var(--bg);color:var(--fg);font-family:-apple-system,system-ui,sans-serif;
   padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
 #home{padding:14px;max-width:720px;margin:0 auto}
 .brand{display:flex;align-items:center;gap:12px;margin:6px 0 14px}
 .brand .logo{font-size:34px}
 .brand .bt{font-size:22px;font-weight:800;line-height:1;background:linear-gradient(100deg,#A78BFA,#22D3EE);-webkit-background-clip:text;background-clip:text;color:transparent}
 .brand .bs{font-size:12px;color:var(--muted);letter-spacing:.16em;text-transform:uppercase;margin-top:3px}
 .chips{display:flex;gap:6px;overflow-x:auto;margin:8px 0 2px;padding-bottom:4px;-webkit-overflow-scrolling:touch}
 .chips button{flex:none;font-size:13px;padding:7px 13px;border-radius:999px;background:#161E31;border:1px solid #2A3550;color:var(--muted);font-weight:600;white-space:nowrap}
 .chips button.on{background:var(--accent);border-color:var(--accent);color:#fff}
 .chips button small{opacity:.7;font-weight:400}
 h1{font-size:20px;margin:6px 0 2px} .hint{color:var(--muted);font-size:13px;margin:0 0 10px}
 input,button,select{font-size:16px;padding:11px;border-radius:12px;border:1px solid #2A3550;background:#0D1424;color:var(--fg)}
 input{width:100%} button{background:var(--accent);border:0;color:#fff;font-weight:700}
 button.sec{background:#20283c;border:1px solid #2A3550;color:var(--fg);font-weight:600}
 .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
 .mode{display:flex;gap:6px;margin:10px 0}
 .mode button{flex:1} .mode button.on{outline:2px solid var(--cyan)}
 .list{margin-top:10px;max-height:46vh;overflow:auto;border:1px solid #223;border-radius:12px}
 .it{padding:11px 12px;border-bottom:1px solid #1b2436;display:flex;justify-content:space-between;gap:8px;cursor:pointer}
 .it:active{background:#1b2436} .it small{color:var(--muted);display:block;font-size:12px}
 .it .d{color:var(--cyan);font-size:12px;white-space:nowrap}
 .sel{outline:2px solid var(--accent)}
 #log{margin-top:12px;background:#0D1424;border:1px solid #223;border-radius:12px;padding:10px;font:12px ui-monospace,Menlo,monospace;white-space:pre-wrap;color:#cdd6ea;max-height:30vh;overflow:auto}

 /* PALCO */
 #stage{position:fixed;inset:0;background:#000;display:none;flex-direction:column;z-index:50}
 #stage.show{display:flex}
 .vwrap{position:relative;flex:1;min-height:0;background:#000}
 video{width:100%;height:100%;object-fit:contain;background:#000}
 #intro{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
   background:radial-gradient(60% 60% at 50% 40%,#2a1750,#07040f);color:#fff;text-align:center;gap:8px;transition:opacity .5s}
 #intro .t{font-size:30px;font-weight:800} #intro .a{color:#c9b6ff;font-size:18px}
 #intro .k{letter-spacing:.3em;color:#8B5CF6;font-size:13px}
 #prog{position:absolute;left:0;right:0;bottom:0;height:4px;background:#ffffff22}
 #prog > i{display:block;height:100%;width:0;background:linear-gradient(90deg,#8B5CF6,#22D3EE)}
 #novideo{position:absolute;inset:0;display:none;flex-direction:column;align-items:center;justify-content:center;
   background:radial-gradient(60% 60% at 50% 32%,#2a1750,#07040f);gap:12px}
 #novideo .av{width:116px;height:116px;border-radius:50%;display:grid;place-items:center;font-size:46px;font-weight:800;color:#fff}
 #novideo .t{font-size:26px;font-weight:800;text-align:center;padding:0 18px;text-wrap:balance}
 #novideo .a{color:#c9b6ff;font-size:18px}
 #lyrics{position:absolute;left:0;right:0;bottom:64px;display:none;text-align:center;padding:0 18px;pointer-events:none}
 #lyrics .cur{font-size:30px;font-weight:800;color:#fff;text-shadow:0 2px 10px #000;line-height:1.2}
 #lyrics .nxt{font-size:20px;color:#c9b6ff;margin-top:8px;text-shadow:0 2px 10px #000}
 #rotate{display:none;position:absolute;top:calc(8px + env(safe-area-inset-top));left:50%;transform:translateX(-50%);
   z-index:70;background:#000a;border:1px solid #39306b;border-radius:10px;padding:6px 12px;font-size:13px;color:#c9b6ff;pointer-events:none}
 @media (orientation:portrait){ #rotate{display:block} }
 #ctl{background:#0a0e18;border-top:1px solid #1b2436;padding:10px 12px 16px;transition:opacity .4s}
 #ctl.hide{opacity:0;pointer-events:none}
 .times{display:flex;justify-content:space-between;color:var(--muted);font:13px ui-monospace,monospace;margin-bottom:8px}
 .seek{width:100%;margin:0 0 10px} .grp{display:flex;align-items:center;gap:6px;justify-content:center;margin:7px 0;flex-wrap:wrap}
 .grp .lb{color:var(--muted);font-size:12px;min-width:48px;text-align:right}
 .pill{padding:9px 12px;border-radius:999px;background:#20283c;border:1px solid #2A3550;color:#fff;min-width:44px}
 .pill.on{background:var(--accent);border-color:var(--accent)}
 .trans{display:flex;gap:10px;justify-content:center;margin-top:8px}
 .trans button{width:64px;height:64px;border-radius:50%;font-size:22px}
 .small{font-size:12px;color:var(--muted);text-align:center;margin-top:6px}
 .back{position:absolute;top:calc(8px + env(safe-area-inset-top));left:8px;z-index:60;background:#0008;border:1px solid #333;border-radius:10px;padding:8px 12px}
 .warn{color:var(--warn)} .good{color:var(--good)} .bad{color:var(--bad)}
</style></head><body>

<div id="home">
  <div class="brand"><span class="logo">🎤</span><div><div class="bt">Videokê</div><div class="bs">Família Silva</div></div></div>
  <input id="q" placeholder="🔍 Buscar música ou artista…" autocomplete="off">
  <button id="newbtn" onclick="toggleNew()" style="width:100%;margin:6px 0;padding:10px;background:#162447;color:#A78BFA;border:1px solid #2A3550;border-radius:10px;font-weight:700">➕ Nova música</button>
  <div id="newsong" style="display:none;background:#161E31;border-radius:12px;padding:12px;margin-bottom:8px">
    <input id="nsq" placeholder="Link do YouTube ou: Música - Artista" autocomplete="off" style="width:100%;font-size:15px;padding:10px;border-radius:10px;border:1px solid #2A3550;background:#0D1424;color:#E8ECF6">
    <div style="display:flex;gap:8px;margin-top:8px">
      <button id="nsbtn" onclick="submitNew()" style="flex:1;padding:11px;background:#8B5CF6;color:#fff;border:0;border-radius:10px;font-weight:700">Baixar ⬇</button>
      <button onclick="toggleNew()" style="padding:11px 16px;background:#20304d;color:#cbd5e1;border:0;border-radius:10px;font-weight:700">Cancelar</button>
    </div>
    <div id="nsmsg" style="font-size:12px;color:#9AA6C0;min-height:16px;margin-top:6px"></div>
    <div id="nslist"></div>
  </div>
  <div class="chips" id="chips"></div>
  <div class="grp" style="justify-content:flex-start;margin-top:8px"><span class="lb">TOM</span>
    <button class="pill" data-tom="-2">-2</button><button class="pill" data-tom="-1">-1</button>
    <button class="pill on" data-tom="0">0</button><button class="pill" data-tom="1">+1</button>
    <button class="pill" data-tom="2">+2</button></div>
  <div class="grp" style="justify-content:flex-start"><span class="lb">RITMO</span>
    <button class="pill" data-rit="90">90</button><button class="pill" data-rit="95">95</button>
    <button class="pill on" data-rit="100">100</button><button class="pill" data-rit="105">105</button>
    <button class="pill" data-rit="110">110</button></div>
  <div id="offbar" style="display:none;align-items:center;justify-content:space-between;margin-top:10px;padding:9px 12px;background:#161E31;border-radius:10px;font-size:13px;color:#9AA6C0"></div>
  <div class="list" id="list"></div>
  <div id="more"></div>
  <div id="log" style="display:none"></div>
  <div class="hint" style="text-align:center;margin-top:12px;opacity:.45;font-size:11px">Videokê Família Silva · v19</div>
</div>

<div id="stage">
  <button class="back" onclick="closeStage()">✕ Voltar</button>
  <div class="vwrap">
    <video id="v0" playsinline webkit-playsinline></video>
    <video id="v1" playsinline webkit-playsinline style="display:none"></video>
    <div id="novideo"><div class="av" id="nvAv"></div><div class="t" id="nvT"></div><div class="a" id="nvA"></div></div>
    <div id="lyrics"></div>
    <div id="intro"><div class="k">TOCANDO AGORA</div><div class="t" id="iT">—</div><div class="a" id="iA"></div><div class="a" id="iC" style="color:#9AA6C0;margin-top:4px"></div><div class="a" id="iHint" style="margin-top:14px;color:#A78BFA;font-weight:700">👆 toque na tela para iniciar</div></div>
    <div id="rotate">📱 Gire o celular para a horizontal</div>
    <div id="prog"><i></i></div>
  </div>
  <div id="ctl">
    <div class="times"><span id="tcur">0:00</span><span id="tdur">0:00</span></div>
    <input type="range" id="seek" class="seek" min="0" max="1000" value="0">
    <div class="grp"><span class="lb">TOM</span>
      <button class="pill" data-tom="-2">-2</button><button class="pill" data-tom="-1">-1</button>
      <button class="pill on" data-tom="0">0</button><button class="pill" data-tom="1">+1</button>
      <button class="pill" data-tom="2">+2</button></div>
    <div class="grp"><span class="lb">RITMO</span>
      <button class="pill" data-rit="90">90</button><button class="pill" data-rit="95">95</button>
      <button class="pill on" data-rit="100">100</button><button class="pill" data-rit="105">105</button>
      <button class="pill" data-rit="110">110</button></div>
    <div class="grp"><span class="lb">VOL</span><input type="range" id="vol" min="0" max="100" value="100" style="flex:1"></div>
    <div class="trans">
      <button class="sec" id="back10">⏪</button>
      <button id="pp">⏸</button>
      <button class="sec" id="fwd10">⏩</button>
    </div>
    <div class="small" id="status">—</div>
  </div>
</div>

<script>
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let MODE='auto', ALL=[], SEL=null, ctx=null, worklet=false, players={}, active=null, prepared=null, prepInfo=null;
let tom=0, rit=100, vol=100, hideTimer=null, driftTimer=null, driftMax=0, underruns=0, t0=0;
function log(m){const l=$('#log'); l.textContent=(new Date().toLocaleTimeString()+'  '+m+'\n')+l.textContent;}
function fmt(s){s=Math.max(0,s|0);return (s/60|0)+':'+String(s%60).padStart(2,'0');}
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

async function rpc(method,params){const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({method,params})});const j=await r.json();if(!j.ok)throw new Error(j.error);return j.result;}

// catálogo
let CURCAT=null;   // categoria selecionada (null = todas)
async function loadCatalog(){
  CURCAT=null;
  $$('#chips button').forEach(b=>b.classList.toggle('on', b.dataset.cat===''));
  const r=await fetch('/poc/catalog');const j=await r.json();render(j.items||[], false);setMore(j.next);
}
async function loadCategories(){
  try{ const r=await fetch('/poc/categories'); const j=await r.json();
    const chips=['<button data-cat="" class="on">Todas</button>'].concat(
      (j.items||[]).map(c=>`<button data-cat="${c.id}">${esc(c.name)}${c.count?` <small>(${c.count})</small>`:''}</button>`));
    $('#chips').innerHTML=chips.join('');
    $$('#chips button').forEach(b=>b.onclick=()=>pickCat(b.dataset.cat));
  }catch(_){}
}
async function pickCat(id){
  $('#q').value=''; CURCAT=id||null;
  $$('#chips button').forEach(b=>b.classList.toggle('on',b.dataset.cat===(id||'')));
  if(!CURCAT){ return loadCatalog(); }
  const r=await fetch('/poc/catalog?category='+encodeURIComponent(CURCAT)); const j=await r.json(); render(j.items||[], false); setMore(null);
}
let ROWMAP={}, NEXT=null, LOADING=false;
function rowHTML(s){ return `<div class="it" data-id="${s.id}"><div><b>${esc(s.title)}</b><small>${esc(s.artist)}</small></div>`+
  `<div style="display:flex;align-items:center;gap:8px"><span class="d">${fmt(s.dur)} ${esc(s.fmt)}</span>`+
  `<button class="dlb" data-dl="${s.id}" title="Baixar p/ cantar offline" style="background:#20304d;color:#fff;border:0;border-radius:8px;padding:6px 10px;font-size:14px;line-height:1">${offHas(s.id)?'✓':'⬇'}</button></div></div>`; }
function wireRows(){
  $$('#list .it').forEach(el=>el.onclick=()=>{SEL=ROWMAP[el.dataset.id];$$('#list .it').forEach(e=>e.classList.remove('sel'));el.classList.add('sel');startSinging();});
  $$('#list .dlb').forEach(b=>b.onclick=ev=>{ev.stopPropagation();toggleOffline(ROWMAP[b.dataset.dl],b);});
}
function render(items, append){
  if(!append) ROWMAP={};
  items.forEach(s=>ROWMAP[s.id]=s);
  const html=items.map(rowHTML).join(''); const L=$('#list');
  if(append) L.insertAdjacentHTML('beforeend', html);
  else L.innerHTML = html || '<div class="it" style="color:#9AA6C0">Nada encontrado.</div>';
  wireRows(); updateOffbar();
}
function setMore(next){
  NEXT=next||null; const m=$('#more'); if(!m)return;
  if(NEXT){ m.innerHTML='<button id="moreb" style="width:100%;margin-top:10px;padding:12px;background:#20304d;color:#fff;border:0;border-radius:10px;font-weight:700">Carregar mais ↓</button>'; $('#moreb').onclick=loadMore; }
  else m.innerHTML='';
}
async function loadMore(){
  if(!NEXT||LOADING)return; LOADING=true;
  const b=$('#moreb'); if(b){b.textContent='Carregando…';b.disabled=true;}
  try{ const r=await fetch('/poc/catalog?after='+encodeURIComponent(NEXT)); const j=await r.json(); render(j.items||[], true); setMore(j.next); }
  catch(e){ if(b){b.textContent='Carregar mais ↓';b.disabled=false;} }
  finally{ LOADING=false; }
}
let _qt=null;
$('#q').oninput=e=>{
  const q=e.target.value.trim();
  clearTimeout(_qt);
  _qt=setTimeout(async()=>{
    if(!q){ return CURCAT?pickCat(CURCAT):loadCatalog(); }
    $$('#chips button').forEach(b=>b.classList.remove('on')); CURCAT=null;
    try{ const r=await fetch('/poc/search?q='+encodeURIComponent(q)); const j=await r.json(); render(j.items||[], false); setMore(null); }catch(_){}
  }, 250);
};

// ----- Nova música (pede p/ o desktop baixar do YouTube e publicar na nuvem)
function toggleNew(){ const n=$('#newsong'); const show=n.style.display==='none'; n.style.display=show?'block':'none'; if(show) loadReqs(); }
function isUrl(s){ return /youtube\.com|youtu\.be|^https?:\/\//i.test(s); }
async function submitNew(){
  const v=$('#nsq').value.trim(); if(!v){ $('#nsmsg').textContent='Digite um link ou "Música - Artista".'; return; }
  const sn=$('#singer'); const by=(sn&&sn.value.trim())||'';
  const body=isUrl(v)?{url:v,by}:{query:v,by};
  $('#nsbtn').disabled=true; $('#nsmsg').textContent='Enviando pedido…';
  try{ const r=await fetch('/dl/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const j=await r.json();
    if(j.error){ $('#nsmsg').textContent='⚠️ '+j.error; } else { $('#nsq').value=''; $('#nsmsg').textContent='✅ Enviado! O desktop baixa quando estiver online.'; }
  }catch(e){ $('#nsmsg').textContent='⚠️ Falha ao enviar o pedido.'; }
  finally{ $('#nsbtn').disabled=false; loadReqs(); }
}
async function loadReqs(){
  try{ const r=await fetch('/dl/list'); const j=await r.json();
    const badge={pending:'⏳ na fila',working:'⬇️ baixando',done:'✅ pronta',error:'⚠️ erro'};
    $('#nslist').innerHTML=(j.items||[]).slice(0,8).map(it=>{
      const name=esc(it.title||it.query||it.url||'—');
      const x=(it.status==='pending'||it.status==='error')?'<button onclick="cancelReq(\''+it.id+'\')" title="Cancelar" style="background:none;border:0;color:#F87171;font-size:16px;line-height:1;cursor:pointer;padding:0 2px">✕</button>':'';
      return '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:7px 0;border-top:1px solid #222c44;font-size:13px"><span>'+name+'</span><span style="display:flex;align-items:center;gap:10px"><span class="muted">'+(badge[it.status]||it.status)+'</span>'+x+'</span></div>';
    }).join('')||'<div class="muted" style="font-size:12px;padding-top:6px">Nenhum pedido ainda.</div>';
  }catch(e){}
}
async function cancelReq(id){ try{ await fetch('/dl/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})}); loadReqs(); }catch(e){} }

// ----- G2b: offline (baixar músicas p/ cantar sem internet)
const VK_MEDIA='vk-media-v1';
function offStore(){ try{return JSON.parse(localStorage.getItem('vk_offline')||'{}');}catch(_){return {};} }
function offSave(o){ try{localStorage.setItem('vk_offline',JSON.stringify(o));}catch(_){ } }
function offHas(id){ return !!offStore()[id]; }
function fmtMB(b){ return (b/1048576).toFixed(0)+' MB'; }
function updateOffbar(){
  const bar=$('#offbar'); if(!bar)return;
  const o=offStore(), ids=Object.keys(o);
  if(!ids.length){ bar.style.display='none'; return; }
  const tot=ids.reduce((a,k)=>a+(o[k].size||0),0);
  bar.style.display='flex';
  bar.innerHTML='<span>📥 '+ids.length+' offline · '+fmtMB(tot)+'</span>'+
    '<button onclick="clearOffline()" style="background:#3d1a12;color:#F87171;border:0;border-radius:8px;padding:6px 11px;font-size:12px;font-weight:700">Limpar offline</button>';
}
async function toggleOffline(s,btn){
  if(!s||!('caches'in window)){ setStatus('Offline não suportado neste navegador','warn'); return; }
  const o=offStore();
  if(o[s.id]){ await removeOffline(s.id); if(btn)btn.textContent='⬇'; updateOffbar(); return; }
  if(!navigator.onLine){ setStatus('Sem internet — baixe com conexão','warn'); return; }
  if(btn){btn.textContent='…';btn.disabled=true;}
  try{
    const info=await resolveSrc(s.id,'auto');
    const url=(info&&(info.kind==='cloud_cache'||info.kind==='local'))?info.uri:null;
    if(!url) throw new Error('não cacheada na nuvem');
    const resp=await fetch(url,{mode:'cors'}); if(!resp.ok) throw new Error('HTTP '+resp.status);
    await (await caches.open(VK_MEDIA)).put(url, resp.clone());
    const blob=await resp.blob();
    const st=offStore(); st[s.id]={title:s.title,artist:s.artist,url:url,size:blob.size}; offSave(st);
    if(btn)btn.textContent='✓';
  }catch(e){ if(btn)btn.textContent='⬇'; setStatus('Falha ao baixar: '+e.message,'bad'); }
  finally{ if(btn)btn.disabled=false; updateOffbar(); }
}
async function removeOffline(id){
  const o=offStore(), rec=o[id]; if(!rec)return;
  try{ await (await caches.open(VK_MEDIA)).delete(rec.url); }catch(_){}
  delete o[id]; offSave(o);
}
async function clearOffline(){
  try{ await caches.delete(VK_MEDIA); }catch(_){}
  localStorage.removeItem('vk_offline');
  $$('#list .dlb').forEach(b=>b.textContent='⬇'); updateOffbar();
}

// ----- áudio
let audioMode='—';   // worklet | scriptprocessor | nativo
let GRAPH_FX=null;   // estado do "efeito tom" com que o grafo foi montado
async function ensureCtx(){
  if(ctx){ try{await ctx.resume();}catch(_){} return; }
  ctx=new (window.AudioContext||window.webkitAudioContext)();
  // AudioWorklet SÓ existe em contexto seguro (https/localhost). Sobre http da LAN
  // cai no ScriptProcessor. Tenta carregar o worklet; se não der, segue sem ele.
  if(ctx.audioWorklet){
    try{ await ctx.audioWorklet.addModule('/poc/shifter.js'); worklet=true; }catch(e){ worklet=false; log('worklet indisponível: '+e.message); }
  }
  try{await ctx.resume();}catch(_){}
  log('AudioContext '+ctx.sampleRate+'Hz · worklet='+worklet);
}
// pitch granular em ScriptProcessor (funciona sobre http, sem contexto seguro)
function makeScriptShifter(){
  const N=32768,bs=4096,node=ctx.createScriptProcessor(bs,2,2);
  const ringL=new Float32Array(N),ringR=new Float32Array(N);
  let wp=0,phase=0;const grain=2048;let r=1;
  const read=(ring,delay)=>{let rp=wp-delay;while(rp<0)rp+=N;while(rp>=N)rp-=N;const i0=Math.floor(rp),fr=rp-i0,i1=(i0+1)%N;return ring[i0]*(1-fr)+ring[i1]*fr;};
  node.onaudioprocess=(e)=>{
    const inB=e.inputBuffer,outB=e.outputBuffer;
    const inL=inB.getChannelData(0),inR=inB.numberOfChannels>1?inB.getChannelData(1):inL;
    const outL=outB.getChannelData(0),outR=outB.getChannelData(1);
    const k=r-1,amp=Math.abs(k)*grain,up=k>=0;
    for(let i=0;i<inL.length;i++){
      ringL[wp]=inL[i];ringR[wp]=inR[i];
      const ph=phase,ph2=ph>=0.5?ph-0.5:ph+0.5;
      const d1=(up?(1-ph):ph)*amp,d2=(up?(1-ph2):ph2)*amp;
      const w1=0.5-0.5*Math.cos(2*Math.PI*ph),w2=0.5-0.5*Math.cos(2*Math.PI*ph2);
      outL[i]=read(ringL,d1)*w1+read(ringL,d2)*w2;
      outR[i]=read(ringR,d1)*w1+read(ringR,d2)*w2;
      wp++;if(wp>=N)wp=0;phase+=1/grain;if(phase>=1)phase-=1;
    }
  };
  return {node,setRatio:x=>{r=x;}};
}
function buildPlayer(video,fx){
  if(!ctx || !fx){ audioMode='nativo'; return {video,raw:true,connected:true}; }
  try{
    const src=ctx.createMediaElementSource(video);
    const gain=ctx.createGain(),an=ctx.createAnalyser();an.fftSize=512;
    let sh;
    if(worklet){
      const wn=new AudioWorkletNode(ctx,'granular-pitch',{outputChannelCount:[2]});
      wn.port.onmessage=e=>{if(e.data&&e.data.underruns!=null)underruns=e.data.underruns;};
      sh={node:wn,setRatio:x=>wn.parameters.get('ratio').value=x}; audioMode='worklet';
    }else{ sh=makeScriptShifter(); audioMode='scriptprocessor'; }
    src.connect(sh.node);sh.node.connect(gain);gain.connect(an);
    return {video,src,sh,gain,an,raw:false,connected:false};
  }catch(e){ log('grafo de áudio falhou ('+e.message+') → áudio nativo'); audioMode='nativo'; return {video,raw:true,connected:true}; }
}
function connect(p){if(p&&!p.raw&&!p.connected){p.an.connect(ctx.destination);p.connected=true;}}
function disconnect(p){if(p&&!p.raw&&p.connected){try{p.an.disconnect(ctx.destination);}catch(_){}p.connected=false;}}
function ratio(){return Math.pow(2,tom/12)/(rit/100);}
function applyAudio(){if(!active)return;active.video.playbackRate=rit/100;
  if(active.raw){active.video.volume=vol/100;return;}
  active.sh.setRatio(ratio());active.gain.gain.value=vol/100;}

function rms(p){if(!p||!p.an)return 1;const a=new Uint8Array(p.an.fftSize);p.an.getByteTimeDomainData(a);let s=0;for(const x of a){const d=(x-128)/128;s+=d*d;}return Math.sqrt(s/a.length);}
function setStatus(m,cls){const s=$('#status');if(s){s.textContent=m;s.className='small'+(cls?(' '+cls):'');}}

// pré-arma o áudio no 1º toque (iOS: AudioContext + worklet + players precisam de gesto)
let armed=false;
async function arm(){ if(armed)return; try{ await ensureCtx(); armed=true; log('🔊 áudio armado (ctx='+(ctx?ctx.state:'none')+')'); }catch(e){ log('arm: '+e.message);} }
document.addEventListener('pointerdown',arm);
// fallback universal iOS: se o autoplay for bloqueado, 1 toque na tela inicia
function tapToPlay(v){
  $('#iT').textContent='▶ Toque para iniciar'; $('#iA').textContent='';
  setStatus('iOS bloqueou o autoplay — toque na tela para iniciar','warn');
  const h=()=>{$('#intro').removeEventListener('pointerdown',h);v.play().catch(err=>setStatus('play falhou: '+err.message,'bad'));};
  $('#intro').addEventListener('pointerdown',h,{once:true});
}

// ----- fluxo CANTAR
async function startSinging(){
  if(!SEL){log('⚠️ escolha uma música');return;}
  curSongId=SEL.id;
  await arm();
  if(MODE==='prefetch'){
    if(prepared&&prepInfo&&prepInfo.id===SEL.id){return playPrepared();}
    log('⚠️ PREFETCH: toque "Preparar próxima" antes (mesma música).');return;
  }
  openStage(SEL.title,SEL.artist);
  t0=performance.now();
  if(!players.v0)players.v0=buildPlayer($('#v0'), !!(ctx&&ctx.audioWorklet));
  setActive(players.v0);
  log('['+MODE.toUpperCase()+'] áudio='+audioMode+' · resolvendo…');
  let info;
  try{info=await resolveSrc(SEL.id,MODE);}catch(e){log('❌ resolve: '+e.message);return;}
  const tResolve=performance.now()-t0;
  log('resolve='+Math.round(tResolve)+'ms ('+info.kind+')');
  await playInto(active,info,tResolve,MODE);
}
async function resolveSrc(id,mode){
  const r=await fetch('/poc/resolve/'+id+'?mode='+mode);const j=await r.json();
  if(j.error)throw new Error(j.error);return j;
}
function srcUrl(info){
  if(info.kind==='local')return info.uri;             // same-origin, ok p/ Web Audio
  // HTTPS + mídia http do YouTube = mixed content (bloqueado) → proxy same-origin sempre
  const needProxy=location.protocol==='https:';   // https: mídia http do YouTube = mixed content → proxy
  return needProxy ? ('/proxy?url='+encodeURIComponent(info.uri)) : info.uri;
}
function crossFor(url){ return (/^https?:\/\//.test(url) && !url.startsWith(location.origin)) ? 'anonymous' : null; }
async function playInto(p,info,tResolve,scenario){
  const v=p.video; v.playsInline=true;
  const _u=srcUrl(info); v.crossOrigin=crossFor(_u);
  v.onerror=()=>{const er=v.error;setStatus('erro de vídeo (code '+((er&&er.code)||'?')+')','bad');log('video error code '+((er&&er.code)||'?'));};
  log('ctx='+(ctx?ctx.state:'none')+' audio='+audioMode+' raw='+p.raw);
  ['loadedmetadata','canplay','waiting','stalled'].forEach(ev=>v.addEventListener(ev,()=>{if(!done)setStatus('vídeo: '+ev+' (rs'+v.readyState+'/ns'+v.networkState+') '+audioMode);},{once:true}));
  v.src=srcUrl(info); v.load();
  applyAudio();
  let done=false;
  const started=()=>{
    if(done)return; done=true;
    v.removeEventListener('playing',started);
    const total=performance.now()-t0;
    $('#intro').style.opacity='0';setTimeout(()=>{$('#intro').style.display='none';},500);
    log('▶ playing TOTAL='+Math.round(total)+'ms');
    setStatus('tocando — TOTAL '+Math.round(total)+'ms (resolve '+Math.round(tResolve)+'ms)','good');
    checkSignal(p,info);
    sendMetric(scenario,{resolve_ms:Math.round(tResolve),total_ms:Math.round(total),kind:info.kind,title:info.title});
    startDrift(p); checkNoVideo(p,info.title,info.artist); loadLyrics(curSongId);
  };
  v.addEventListener('playing',started);
  v.addEventListener('timeupdate',()=>{if(v.currentTime>0.05)started();});
  try{await v.play();}catch(e){log('⚠️ autoplay bloqueado: '+e.message);tapToPlay(v);}
  requestWakeLock(); lockLandscape();
}
function checkSignal(p,info){
  if(info.kind==='local'||p.raw)return;
  setTimeout(()=>{const r=rms(p);if(r<0.001&&!p.video.paused){
    log('🔇 SEM sinal de áudio no Web Audio → CORS do YouTube bloqueou. Marque "proxy" e tente de novo.');
    $('#status').innerHTML='<span class="bad">CORS bloqueou o áudio — use proxy</span>';
  }else{log('🔊 sinal ok (rms='+r.toFixed(3)+')');}},1500);
}

// PREFETCH
async function prepareNext(){
  if(!SEL){log('⚠️ escolha a música a preparar');return;}
  await ensureCtx();
  if(!players.v1)players.v1=buildPlayer($('#v1'),false);
  const p=players.v1;const tp=performance.now();
  log('⏳ preparando "'+SEL.title+'"…');
  let info;try{info=await resolveSrc(SEL.id, 'cold');}catch(e){log('❌ prep resolve: '+e.message);return;}
  const _pu=srcUrl(info);p.video.crossOrigin=crossFor(_pu);p.video.src=_pu;p.video.preload='auto';p.video.load();
  // buffering silencioso: play+pause
  p.video.muted=true;try{await p.video.play();p.video.pause();p.video.currentTime=0;}catch(_){}
  p.video.muted=false;
  prepared=p;prepInfo={id:SEL.id,title:SEL.title,artist:SEL.artist,info};
  log('✅ preparada em '+Math.round(performance.now()-tp)+'ms (resolve+buffer). Toque CANTAR no modo PREFETCH.');
}
async function playPrepared(){
  openStage(prepInfo.title,prepInfo.artist);
  curSongId=prepInfo.id;
  t0=performance.now();
  setActive(prepared);applyAudio();
  const v=active.video; let done=false;
  const started=()=>{if(done)return;done=true;v.removeEventListener('playing',started);const total=performance.now()-t0;
    $('#intro').style.opacity='0';setTimeout(()=>{$('#intro').style.display='none';},400);
    log('▶ PREFETCH TOTAL='+Math.round(total)+'ms (deve ser ~instantâneo)');
    setStatus('tocando (prefetch) — TOTAL '+Math.round(total)+'ms','good');
    sendMetric('prefetch',{total_ms:Math.round(total),kind:prepInfo.info.kind,title:prepInfo.title});
    checkSignal(active,prepInfo.info);startDrift(active);checkNoVideo(active,prepInfo.title,prepInfo.artist);loadLyrics(curSongId);};
  v.addEventListener('playing',started);
  v.addEventListener('timeupdate',()=>{if(v.currentTime>0.05)started();});
  try{await v.play();}catch(e){log('⚠️ autoplay bloqueado: '+e.message);tapToPlay(v);}
  requestWakeLock();lockLandscape();
  prepared=null;prepInfo=null;
}

function setActive(p){
  if(active&&active!==p){try{active.video.pause();}catch(_){}disconnect(active);active.video.style.display='none';}
  active=p;connect(p);p.video.style.display='block';bindTimes(p);
  // esconde o outro <video> (o efeito usa o 2º elemento, que nasce oculto)
  [players.v0,players.v1,players.vfx].forEach(q=>{if(q&&q!==p)q.video.style.display='none';});
}

// drift / underruns — amostra ao longo da música
function startDrift(p){
  stopDrift();driftMax=0;const t=p.video;
  driftTimer=setInterval(()=>{
    if(t.paused)return;
    // com Approach-2 áudio e vídeo compartilham o relógio do elemento:
    // reportamos latência de saída (const) + underruns do worklet (glitch=ruim)
    const lat=((ctx.outputLatency||ctx.baseLatency||0)*1000);
    $('#status').textContent='['+audioMode+'] t='+t.currentTime.toFixed(1)+'s · lat≈'+lat.toFixed(0)+'ms · underruns='+underruns+' · ratio='+ratio().toFixed(3);
  },1000);
}
function stopDrift(){if(driftTimer)clearInterval(driftTimer);driftTimer=null;}

// ----- fundo p/ vídeo ausente (arquivo só-áudio/tela preta) + letra sincronizada
let curSongId=null, LY=null;
const AV_COLORS=['#8B5CF6','#06B6D4','#EC4899','#F59E0B','#10B981','#6366F1','#EF4444','#14B8A6'];
function initials(s){const w=(s||'?').trim().split(/\s+/);return ((w[0]||'')[0]||'')+((w[1]||'')[0]||'');}
function avColor(s){let h=0;for(const c of (s||'')){h=(h*31+c.charCodeAt(0))>>>0;}return AV_COLORS[h%AV_COLORS.length];}
function checkNoVideo(p,title,artist){
  const show=()=>{const has=p.video.videoWidth>0;
    $('#novideo').style.display=has?'none':'flex';
    if(!has){$('#nvAv').textContent=initials(artist||title).toUpperCase();$('#nvAv').style.background=avColor(artist||title);
      $('#nvT').textContent=title;$('#nvA').textContent=artist||'';}};
  show(); setTimeout(show,900);   // videoWidth pode demorar 1 frame
}
async function loadLyrics(songId){
  LY=null; $('#lyrics').style.display='none'; $('#lyrics').innerHTML='';
  if(!songId)return;
  let ly; try{ly=await rpc('get_lyrics',{song_id:songId});}catch(_){return;}
  if(!ly||!ly.content)return;
  LY=parseLRC(ly.content);
  if(!LY){ $('#lyrics').style.display='block';
    $('#lyrics').innerHTML='<div class="cur">'+esc(ly.content.split(/\r?\n/)[0]||'')+'</div>'; }
}
function parseLRC(text){
  const out=[]; const re=/\[(\d+):(\d+(?:\.\d+)?)\]/g;
  for(const ln of text.split(/\r?\n/)){ let m; re.lastIndex=0; const ts=[];
    while((m=re.exec(ln))) ts.push(parseInt(m[1])*60+parseFloat(m[2]));
    const txt=ln.replace(/\[[^\]]*\]/g,'').trim();
    for(const t of ts) if(txt) out.push({t,txt}); }
  if(out.length<2)return null; out.sort((a,b)=>a.t-b.t); return out;
}
function updateLyric(time){
  if(!LY)return; let i=0; while(i<LY.length&&LY[i].t<=time)i++; i--;
  const cur=i>=0?LY[i].txt:''; const nxt=(i+1)<LY.length?LY[i+1].txt:'';
  $('#lyrics').style.display='block';
  $('#lyrics').innerHTML='<div class="cur">'+esc(cur)+'</div>'+(nxt?'<div class="nxt">'+esc(nxt)+'</div>':'');
}

// controles
function bindTimes(p){const v=p.video;
  v.ontimeupdate=()=>{$('#tcur').textContent=fmt(v.currentTime);if(v.duration){$('#seek').value=(v.currentTime/v.duration*1000)|0;$('#prog>i').style.width=(v.currentTime/v.duration*100)+'%';}updateLyric(v.currentTime);};
  v.ondurationchange=()=>$('#tdur').textContent=fmt(v.duration||0);
  v.onended=()=>{log('🏁 fim da música');stopDrift();};
}
$('#seek').oninput=e=>{if(active&&active.video.duration)active.video.currentTime=e.target.value/1000*active.video.duration;showCtl();};
$('#vol').oninput=e=>{vol=+e.target.value;applyAudio();};
$('#pp').onclick=()=>{if(!active)return;if(active.video.paused){active.video.play();$('#pp').textContent='⏸';}else{active.video.pause();$('#pp').textContent='▶';}showCtl();};
$('#back10').onclick=()=>{if(active)active.video.currentTime=Math.max(0,active.video.currentTime-10);showCtl();};
$('#fwd10').onclick=()=>{if(active)active.video.currentTime+=10;showCtl();};
function syncTomRit(){$$('[data-tom]').forEach(x=>x.classList.toggle('on',+x.dataset.tom===tom));$$('[data-rit]').forEach(x=>x.classList.toggle('on',+x.dataset.rit===rit));}
$$('[data-tom]').forEach(b=>b.onclick=()=>{tom=+b.dataset.tom;syncTomRit();applyAudio();showCtl();});
$$('[data-rit]').forEach(b=>b.onclick=()=>{rit=+b.dataset.rit;syncTomRit();applyAudio();showCtl();});

// auto-hide dos controles
function showCtl(){$('#ctl').classList.remove('hide');clearTimeout(hideTimer);hideTimer=setTimeout(()=>$('#ctl').classList.add('hide'),4000);}
$('#stage').addEventListener('pointerdown',()=>showCtl());

function openStage(title,artist){$('#iT').textContent=title;$('#iA').textContent=artist||'';$('#intro').style.display='flex';$('#intro').style.opacity='1';$('#stage').classList.add('show');showCtl();
  $('#novideo').style.display='none';$('#lyrics').style.display='none';
  const sn=$('#singer');$('#iC').textContent=(sn&&sn.value.trim())?('🎤 '+sn.value.trim()):'';
  // iOS: tocar na intro inicia a reprodução (gesto direto, à prova de bloqueio de autoplay)
  $('#intro').onclick=()=>{ if(active&&active.video&&active.video.currentSrc){ active.video.play().then(()=>setStatus('play ok','good')).catch(e=>setStatus('play falhou: '+e.message,'bad')); } };}
function closeStage(){$('#stage').classList.remove('show');if(active){try{active.video.pause();}catch(_){}}stopDrift();releaseWakeLock();$('#pp').textContent='⏸';$('#novideo').style.display='none';$('#lyrics').style.display='none';}

// wake lock / orientação
let wl=null;
async function requestWakeLock(){try{if('wakeLock'in navigator)wl=await navigator.wakeLock.request('screen');}catch(_){}}
function releaseWakeLock(){try{if(wl)wl.release();wl=null;}catch(_){}}
function lockLandscape(){try{if(screen.orientation&&screen.orientation.lock)screen.orientation.lock('landscape').catch(()=>{});}catch(_){}}

async function sendMetric(scenario,data){
  const body={scenario,audio:audioMode,fx:(audioMode!=='nativo'),ua:navigator.userAgent,ts:new Date().toISOString(),...data};
  try{await fetch('/poc/metric',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}catch(_){}
}
// teste dedicado do EFEITO DE TOM (usa o 2º <video>, grafo scriptprocessor; sem recarregar)
async function startFxTest(){
  if(!SEL){log('⚠️ escolha uma música');return;}
  curSongId=SEL.id;
  await arm();
  openStage(SEL.title+' 🎚️',SEL.artist);
  t0=performance.now();
  if(!players.vfx)players.vfx=buildPlayer($('#v1'),true);
  setActive(players.vfx);
  log('[FX] áudio='+audioMode+' · resolvendo…');
  if(audioMode==='nativo'){setStatus('efeito indisponível (áudio nativo) — veja o log','warn');}
  let info;try{info=await resolveSrc(SEL.id,'hot');}catch(e){log('❌ '+e.message);setStatus('erro: '+e.message,'bad');return;}
  await playInto(active,info,performance.now()-t0,'fx');
}
const _sn=$('#singer'); if(_sn){_sn.value=localStorage.getItem('vk_singer')||'';_sn.onchange=()=>localStorage.setItem('vk_singer',_sn.value);}
if('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{});}
loadCategories().then(loadCatalog);
</script></body></html>"""
