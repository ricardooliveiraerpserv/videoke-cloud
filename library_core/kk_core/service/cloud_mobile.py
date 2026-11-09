"""Fase F4 — página do celular servida PELA NUVEM (PC desligado).

Self-contained (sem CDN). Busca/navega o catálogo via POST /rpc (métodos de
convidado) e toca via GET /resolve/{song_id} — que devolve o hot-cache (Storage)
ou a fonte YouTube. Versão enxuta de produto: buscar → tocar. O palco rico
(tom/ritmo/letra do POC local) entra depois sobre esta base.
"""
from __future__ import annotations

CLOUD_MOBILE_HTML = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Videokê Família Silva</title>
<style>
 :root{--bg:#0d0f16;--card:#171a22;--fg:#fff;--muted:#9aa3b2;--accent:#8B5CF6;--ok:#2ecc71;--no:#e67e22}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font-family:-apple-system,system-ui,sans-serif;padding:14px;padding-bottom:40px}
 h1{font-size:20px;margin:4px 0 12px} .row{display:flex;gap:8px}
 input{flex:1;padding:12px 14px;border-radius:12px;border:1px solid #2a2f3a;background:#0f1420;color:#fff;font-size:16px}
 button{background:var(--accent);color:#fff;border:0;border-radius:12px;padding:12px 14px;font-size:15px;font-weight:700}
 #video{width:100%;aspect-ratio:16/9;background:#000;border-radius:12px;margin:12px 0;display:none}
 #now{color:var(--muted);font-size:14px;min-height:20px;margin:4px 2px}
 .item{display:flex;justify-content:space-between;align-items:center;gap:8px;
   background:var(--card);border-radius:12px;padding:12px 14px;margin:8px 0}
 .item b{font-size:15px} .item small{color:var(--muted);display:block;font-size:13px}
 .item button{padding:9px 16px}
 .tag{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:#123d1a;color:var(--ok)}
 .tag.no{background:#3d1a12;color:var(--no)}
</style></head><body>
 <h1>🎤 Videokê Família Silva</h1>
 <video id="video" controls playsinline></video>
 <div id="now"></div>
 <div class="row"><input id="q" placeholder="Música ou artista…" autocomplete="off">
   <button onclick="doSearch()">Buscar</button></div>
 <div id="list"></div>
<script>
const $=s=>document.querySelector(s);
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function rpc(method,params){
  const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({method,params})});
  const j=await r.json(); if(!j.ok) throw new Error(j.error); return j.result;
}
function render(items){
  $('#list').innerHTML = items.map(s=>
    `<div class="item"><div><b>${esc(s.title)}</b><small>${esc((s.artists||[]).join(', '))}</small></div>
     <button onclick="play('${s.id}','${esc(s.title)}')">▶</button></div>`).join('')
    || '<p style="color:#9aa">Nada encontrado.</p>';
}
async function browseAll(){ try{ const p=await rpc('browse_songs',{page:{limit:500}}); render(p.items);}catch(e){ $('#list').innerHTML='<p style="color:#e67e22">'+esc(e.message)+'</p>'; } }
async function doSearch(){ const q=$('#q').value.trim(); if(!q) return browseAll();
  const p=await rpc('search_songs',{query:q}); render(p.items); }
async function play(id,title){
  const v=$('#video'); $('#now').textContent='⏳ Resolvendo '+title+'…';
  try{
    const r=await fetch('/resolve/'+id); const d=await r.json();
    if(!d.uri){ $('#now').innerHTML='<span class="tag no">indisponível</span> '+esc(title)+' — '+esc(d.error||'sem fonte'); return; }
    const kind=d.kind==='cloud_cache'?'<span class="tag">cache</span>':'<span class="tag">youtube</span>';
    $('#now').innerHTML=kind+' '+esc(title)+(d.artist?' — '+esc(d.artist):'');
    v.src=d.uri; v.style.display='block'; v.play().catch(()=>{});
  }catch(e){ $('#now').innerHTML='<span class="tag no">erro</span> '+esc(e.message); }
}
$('#q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
$('#q').addEventListener('input',e=>{if(!e.target.value.trim())browseAll();});
browseAll();
</script></body></html>"""
