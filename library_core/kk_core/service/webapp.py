"""Páginas servidas pelo próprio daemon, self-contained (sem CDN, offline na LAN):

- MOBILE_HTML   → celular do CONVIDADO: entra por código, busca e PEDE música
                  (fica pendente); acompanha o status do pedido e a fila.
- OPERATOR_HTML → painel do OPERADOR (localhost=admin): mostra código + QR,
                  lista pedidos pendentes e aprova/recusa em tempo real.
- qr_html       → tela de QR para projetar.

Fase D: o convidado NÃO enfileira direto — ele pede, e o operador aceita/recusa.
"""
from __future__ import annotations

import io
import socket


def lan_ip() -> str:
    """Melhor IP da LAN, funciona offline (não envia pacote de fato)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def guest_url_from_host(host_header: str, port_fallback: int) -> str:
    host = host_header or ""
    ip, _, port = host.partition(":")
    if not ip or ip in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        ip = lan_ip()
    port = port or str(port_fallback)
    return f"http://{ip}:{port}/"


def qr_html(url: str) -> str:
    try:
        import segno
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=9, border=2)
        svg = buf.getvalue().decode()
    except Exception:  # noqa: BLE001
        svg = "<p>(instale 'segno' para o QR)</p>"
    return f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QR — Peça sua música</title>
<style>
 body{{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;
   justify-content:center;background:#0d0f16;color:#fff;font-family:-apple-system,system-ui,sans-serif;gap:18px}}
 h1{{font-size:28px;margin:0}} .qr{{background:#fff;padding:16px;border-radius:16px}}
 .url{{font-size:20px;color:#e5352b;font-weight:700}} p{{color:#9aa}}
</style></head><body>
 <h1>🎤 Escaneie para pedir música</h1>
 <div class="qr">{svg}</div>
 <div class="url">{url}</div>
 <p>Conecte o celular na mesma Wi-Fi e aponte a câmera.</p>
</body></html>"""


# ---------------------------------------------------------------------------
# Celular do convidado — pedir música (fica pendente de aprovação do operador).
MOBILE_HTML = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Peça sua música</title>
<style>
 :root{--bg:#0d0f16;--card:#171a22;--fg:#fff;--muted:#9aa3b2;--accent:#e5352b;--ok:#2ecc71;--no:#e67e22}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font-family:-apple-system,system-ui,sans-serif;padding:16px;padding-bottom:120px}
 h1{font-size:22px;margin:4px 0 12px} .row{display:flex;gap:8px}
 input,button{font-size:17px;padding:12px;border-radius:12px;border:0}
 input{flex:1;background:#0a0c12;color:#fff;border:1px solid #2a2f3a}
 button{background:var(--accent);color:#fff;font-weight:700}
 .singer{margin:10px 0} .item{background:var(--card);border-radius:14px;padding:14px;margin:10px 0;
   display:flex;justify-content:space-between;align-items:center;gap:10px}
 .item small{color:var(--muted);display:block} .add{background:#233; padding:10px 14px}
 .sec{margin-top:22px;color:var(--muted);font-size:14px;text-transform:uppercase;letter-spacing:.05em}
 .q{background:#101828;border-left:3px solid var(--accent);padding:10px 12px;border-radius:8px;margin:8px 0}
 .r{background:#101828;padding:10px 12px;border-radius:8px;margin:8px 0;display:flex;justify-content:space-between;gap:8px}
 .tag{font-size:12px;font-weight:700;padding:3px 8px;border-radius:999px;white-space:nowrap}
 .tag.pending{background:#2a2f3a;color:#cbd} .tag.approved{background:#123d1a;color:var(--ok)}
 .tag.rejected{background:#3d1a12;color:var(--no)}
 #gate{position:fixed;inset:0;background:var(--bg);display:flex;flex-direction:column;
   align-items:center;justify-content:center;gap:16px;padding:24px;text-align:center}
 #gate.hide{display:none} #gate input{max-width:220px;text-align:center;font-size:28px;letter-spacing:4px}
 #toast{position:fixed;left:16px;right:16px;bottom:20px;background:#123d1a;border:1px solid #2a7;
   color:#dfe;padding:14px;border-radius:12px;text-align:center;opacity:0;transition:.3s;pointer-events:none}
 #toast.show{opacity:1}
</style></head><body>
 <div id="gate">
   <h1>🎤 Entrar na sessão</h1>
   <p style="color:#9aa">Digite o código que aparece na TV / no painel.</p>
   <input id="code" inputmode="numeric" maxlength="6" placeholder="000000">
   <button onclick="joinByInput()">Entrar</button>
   <p id="gateErr" style="color:#e67e22;min-height:20px"></p>
 </div>

 <h1>🎤 Peça sua música</h1>
 <div class="singer"><input id="singer" placeholder="Seu nome" autocomplete="name"></div>
 <div class="row"><input id="q" placeholder="Música ou artista…" autocomplete="off">
   <button onclick="doSearch()">Buscar</button></div>
 <div id="results"></div>

 <div class="sec">Meus pedidos</div>
 <div id="mine"></div>
 <div class="sec">Na fila</div>
 <div id="queue"></div>
 <div id="toast"></div>
<script>
let SID=null;
const $=s=>document.querySelector(s);
const singer=$('#singer'); singer.value=localStorage.getItem('singer')||'';
singer.addEventListener('change',()=>localStorage.setItem('singer',singer.value));
// pedidos deste celular: {id,title,status}
let MINE=JSON.parse(localStorage.getItem('mine')||'[]');
const saveMine=()=>localStorage.setItem('mine',JSON.stringify(MINE.slice(-30)));

async function rpc(method,params){
  const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({method,params})});
  const j=await r.json(); if(!j.ok) throw new Error(j.error); return j.result;
}
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2200);}
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function codeFromUrl(){const m=location.search.match(/[?&]c=(\\d{4,8})/);return m?m[1]:'';}
async function tryJoin(code){
  if(!code) return false;
  try{ const sid=await rpc('session_by_code',{code}); if(sid){SID=sid;localStorage.setItem('code',code);return true;} }
  catch(_){}
  return false;
}
async function joinByInput(){
  const code=$('#code').value.trim();
  if(await tryJoin(code)){ $('#gate').classList.add('hide'); start(); }
  else $('#gateErr').textContent='Código não encontrado. Confira na TV.';
}
async function boot(){
  const code=codeFromUrl()||localStorage.getItem('code')||'';
  if(await tryJoin(code)){ $('#gate').classList.add('hide'); start(); }
  // senão, o #gate fica visível pedindo o código
}
function start(){ browseAll(); loadQueue(); renderMine(); }

function render(items){
  $('#results').innerHTML = items.map(s=>
    `<div class="item"><div><b>${esc(s.title)}</b><small>${esc(s.artists.join(', '))}</small></div>
     <button class="add" onclick="req('${s.id}','${esc(s.title)}')">Pedir</button></div>`).join('')
    || '<p style="color:#9aa">Nada encontrado.</p>';
}
async function browseAll(){ const page=await rpc('browse_songs',{page:{limit:10000}}); render(page.items); }
async function doSearch(){
  const q=$('#q').value.trim(); if(!q) return browseAll();
  const page=await rpc('search_songs',{query:q}); render(page.items);
}
async function req(songId,title){
  const nome=singer.value.trim()||'Convidado';
  const r=await rpc('request_song',{session_id:SID,song_id:songId,singer:nome,device:'celular'});
  MINE.push({id:r.id,title,status:'pending'}); saveMine(); renderMine();
  toast('⏳ '+title+' — pedida para '+nome+' (aguardando aprovação)');
}
function renderMine(){
  $('#mine').innerHTML = MINE.slice().reverse().map(m=>{
    const lbl={pending:'aguardando',approved:'aprovada ✓',rejected:'recusada'}[m.status]||m.status;
    return `<div class="r"><span>${esc(m.title)}</span><span class="tag ${m.status}">${lbl}</span></div>`;
  }).join('') || '<p style="color:#9aa">Você ainda não pediu nada.</p>';
}
async function loadQueue(){
  if(!SID)return; const q=await rpc('queue_list',{session_id:SID});
  $('#queue').innerHTML=q.map((it,i)=>`<div class="q">${i+1}. <b>${esc(it.singer)}</b> — ${esc(it.song_title)}</div>`).join('')
    || '<p style="color:#9aa">Fila vazia.</p>';
}
function markMine(id,status){ const m=MINE.find(x=>x.id===id); if(m){m.status=status;saveMine();renderMine();} }

try{ const ev=new EventSource('/events');
  ev.onmessage=e=>{ try{const d=JSON.parse(e.data);
    if(d.name==='RequestApproved'){ markMine(d.request_id,'approved'); loadQueue();
      const m=MINE.find(x=>x.id===d.request_id); if(m) toast('✅ '+m.title+' foi aprovada!'); }
    else if(d.name==='RequestRejected'){ markMine(d.request_id,'rejected'); }
    else if(['QueueItemAdded','NowSinging','QueueItemDone','QueueReordered'].includes(d.name)) loadQueue();
  }catch(_){}};}catch(_){}
$('#q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
$('#q').addEventListener('input',e=>{if(!e.target.value.trim())browseAll();});
$('#code').addEventListener('keydown',e=>{if(e.key==='Enter')joinByInput();});
boot();
</script></body></html>"""


# ---------------------------------------------------------------------------
# Painel do operador — aprovar/recusar pedidos. AÇÕES são admin (localhost/token);
# a página é inócua (o /rpc barra convidado nas ações).
OPERATOR_HTML = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Operador — pedidos</title>
<style>
 :root{--bg:#0d0f16;--card:#171a22;--fg:#fff;--muted:#9aa3b2;--accent:#e5352b;--ok:#2ecc71;--no:#e67e22}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font-family:-apple-system,system-ui,sans-serif;padding:16px}
 h1{font-size:22px;margin:4px 0} .muted{color:var(--muted)}
 .code{font-size:40px;font-weight:800;letter-spacing:6px;color:var(--accent);margin:4px 0}
 .req{background:var(--card);border-radius:14px;padding:14px;margin:10px 0;display:flex;
   justify-content:space-between;align-items:center;gap:10px}
 .req small{color:var(--muted);display:block}
 .acts{display:flex;gap:8px} button{font-size:16px;padding:10px 14px;border:0;border-radius:10px;font-weight:700}
 .ok{background:#123d1a;color:var(--ok)} .no{background:#3d1a12;color:var(--no)}
 a{color:var(--accent)}
</style></head><body>
 <h1>🎛️ Pedidos dos convidados</h1>
 <div>Código da sessão: <span class="code" id="code">······</span></div>
 <p class="muted">Convidados entram em <b id="guesturl"></b> ou pelo <a href="/qr" target="_blank">QR</a>.</p>
 <h1 style="font-size:18px;margin-top:20px">Pendentes</h1>
 <div id="list"><p class="muted">Carregando…</p></div>
<script>
let SID=null;
const $=s=>document.querySelector(s);
async function rpc(method,params){
  const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({method,params})});
  const j=await r.json(); if(!j.ok) throw new Error(j.error); return j.result;
}
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function init(){
  const gs=await rpc('open_guest_session',{}); SID=gs.session_id;
  $('#code').textContent=gs.code;
  $('#guesturl').textContent=location.origin+'/?c='+gs.code;
  load();
}
async function load(){
  if(!SID)return;
  const reqs=await rpc('list_requests',{session_id:SID,status:'pending'});
  $('#list').innerHTML = reqs.map(r=>
    `<div class="req"><div><b>${esc(r.singer)}</b><small>${esc(r.song_title)}</small></div>
     <div class="acts">
       <button class="ok" onclick="act('approve','${r.id}')">Aprovar</button>
       <button class="no" onclick="act('reject','${r.id}')">Recusar</button>
     </div></div>`).join('') || '<p class="muted">Nenhum pedido pendente.</p>';
}
async function act(kind,id){
  try{ await rpc(kind==='approve'?'approve_request':'reject_request',{request_id:id}); load(); }
  catch(e){ alert(e.message); }
}
try{ const ev=new EventSource('/events');
  ev.onmessage=e=>{ try{const d=JSON.parse(e.data);
    if(['SongRequested','RequestApproved','RequestRejected'].includes(d.name)) load();
  }catch(_){}};}catch(_){}
init();
</script></body></html>"""
