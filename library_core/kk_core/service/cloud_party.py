"""Fase D na NUVEM — festa com convidado + aprovação (polling; a nuvem não tem SSE).

- Operador (anfitrião): abre sessão → código + QR; vê pedidos pendentes e aprova/
  recusa; vê a fila; toca a próxima abrindo o palco (/m?song=<id>).
- Convidado: entra por código/QR, busca e PEDE (fica pendente); vê a fila.

Auth do operador SEM token admin: token POR SESSÃO = HMAC(VK_ADMIN_TOKEN, session_id).
O operador recebe no /op/open e manda nos /op/approve|reject. O convidado usa só
métodos de leitura/pedido (GUEST_METHODS) via /rpc.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def op_token(session_id: str) -> str:
    key = (os.environ.get("VK_ADMIN_TOKEN") or "vk").encode()
    return hmac.new(key, session_id.encode(), hashlib.sha256).hexdigest()[:24]


def check_op(session_id: str, token: str) -> bool:
    return bool(session_id) and hmac.compare_digest(op_token(session_id), token or "")


# ----------------------------------------------------------------- Operador
OPERATOR_HTML = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Videokê — Operador</title>
<style>
 :root{--bg:#0B1120;--card:#161E31;--fg:#E8ECF6;--muted:#9AA6C0;--accent:#8B5CF6;--cyan:#22D3EE;--ok:#34D399;--no:#F87171}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font-family:-apple-system,system-ui,sans-serif;padding:16px;max-width:760px;margin:0 auto}
 h1{font-size:20px;margin:4px 0} .muted{color:var(--muted)}
 .join{display:flex;gap:16px;align-items:center;background:var(--card);border-radius:16px;padding:14px;margin:10px 0;flex-wrap:wrap}
 .code{font-size:40px;font-weight:800;letter-spacing:6px;color:var(--cyan)}
 .qr{background:#fff;padding:8px;border-radius:12px;width:150px;height:150px}
 .sec{margin-top:18px;color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.06em}
 .req,.qi{display:flex;justify-content:space-between;align-items:center;gap:10px;
   background:var(--card);border-radius:12px;padding:12px 14px;margin:8px 0}
 .req b,.qi b{font-size:15px} .req small,.qi small{color:var(--muted);display:block;font-size:13px}
 button{font-size:15px;padding:10px 14px;border:0;border-radius:10px;font-weight:700;color:#fff}
 .ok{background:#123d1a;color:var(--ok)} .no{background:#3d1a12;color:var(--no)}
 .play{background:var(--accent)} a{color:var(--cyan)}
</style></head><body>
 <h1>🎛️ Operador — Videokê Família Silva</h1>
 <div class="join">
   <img class="qr" id="qr" alt="QR">
   <div><div class="muted">Convidados entram com o código:</div>
     <div class="code" id="code">······</div>
     <div class="muted" id="url" style="font-size:13px"></div></div>
 </div>
 <div class="sec">Pedidos pendentes</div>
 <div id="pend"><p class="muted">—</p></div>
 <div class="sec">Fila</div>
 <div id="queue"><p class="muted">—</p></div>
<script>
let SID=null, TOK=null;
const $=s=>document.querySelector(s);
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function jget(u){const r=await fetch(u);return r.json();}
async function jpost(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}
async function init(){
  const d=await jpost('/op/open',{}); SID=d.session_id; TOK=d.op_token;
  $('#code').textContent=d.code;
  const join=location.origin+'/festa?c='+d.code;
  $('#url').textContent=join;
  $('#qr').src='/op/qr?code='+encodeURIComponent(d.code);
  tick(); setInterval(tick, 3000);
}
async function tick(){
  try{
    const p=await jget('/op/requests?session='+SID+'&token='+TOK);
    $('#pend').innerHTML=(p.items||[]).map(r=>
      `<div class="req"><div><b>🎤 ${esc(r.singer)}</b><small>${esc(r.song_title)}${r.artists&&r.artists.length?' — '+esc(r.artists.join(', ')):''}</small></div>
       <div style="display:flex;gap:8px"><button class="ok" onclick="act('approve','${r.id}')">Aprovar</button>
       <button class="no" onclick="act('reject','${r.id}')">Recusar</button></div></div>`).join('')
      || '<p class="muted">Nenhum pedido pendente.</p>';
  }catch(e){}
  try{
    const q=await jget('/op/queue?session='+SID);
    $('#queue').innerHTML=(q.items||[]).map((it,i)=>
      `<div class="qi"><div><b>${i+1}. ${esc(it.singer)}</b><small>${esc(it.song_title)}</small></div>
       <button class="play" onclick="location.href='/m?song='+encodeURIComponent('${it.song_id}')">▶ Tocar</button></div>`).join('')
      || '<p class="muted">Fila vazia.</p>';
  }catch(e){}
}
async function act(kind,id){ await jpost('/op/'+kind,{session:SID,token:TOK,request:id}); tick(); }
init();
</script></body></html>"""


# ----------------------------------------------------------------- Convidado
FESTA_HTML = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Videokê — Pedir música</title>
<style>
 :root{--bg:#0B1120;--card:#161E31;--fg:#E8ECF6;--muted:#9AA6C0;--accent:#8B5CF6;--cyan:#22D3EE;--ok:#34D399;--no:#FBBF24}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font-family:-apple-system,system-ui,sans-serif;padding:14px;max-width:720px;margin:0 auto;padding-bottom:40px}
 h1{font-size:20px;margin:4px 0 10px} .muted{color:var(--muted)}
 input{width:100%;font-size:16px;padding:12px;border-radius:12px;border:1px solid #2A3550;background:#0D1424;color:var(--fg);margin:4px 0}
 .it{display:flex;justify-content:space-between;align-items:center;gap:8px;background:var(--card);border-radius:12px;padding:11px 13px;margin:7px 0}
 .it small{color:var(--muted);display:block;font-size:12px}
 button{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:9px 15px;font-weight:700}
 .sec{margin-top:16px;color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.05em}
 .tag{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px}
 .tag.pend{background:#2a2f3a;color:#cbd} .tag.ok{background:#123d1a;color:var(--ok)}
 #gate{position:fixed;inset:0;background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:24px;text-align:center}
 #gate.hide{display:none} #gate input{max-width:220px;text-align:center;font-size:28px;letter-spacing:4px}
 #toast{position:fixed;left:16px;right:16px;bottom:18px;background:#123d1a;border:1px solid #2a7;color:#dfe;padding:14px;border-radius:12px;text-align:center;opacity:0;transition:.3s;pointer-events:none}
 #toast.show{opacity:1}
</style></head><body>
 <div id="gate"><h1>🎤 Entrar na festa</h1><p class="muted">Digite o código da TV / do painel.</p>
   <input id="code" inputmode="numeric" maxlength="6" placeholder="000000">
   <button onclick="joinInput()">Entrar</button><p id="gerr" style="color:#FBBF24;min-height:20px"></p></div>
 <h1>🎤 Peça sua música</h1>
 <input id="singer" placeholder="Seu nome" autocomplete="name">
 <input id="q" placeholder="🔍 Música ou artista…" autocomplete="off">
 <div id="list"></div>
 <div class="sec">Meus pedidos</div><div id="mine"></div>
 <div class="sec">Na fila</div><div id="queue"></div>
 <div id="toast"></div>
<script>
let SID=null;
const $=s=>document.querySelector(s);
let MINE=JSON.parse(localStorage.getItem('vk_mine')||'[]');
const saveMine=()=>localStorage.setItem('vk_mine',JSON.stringify(MINE.slice(-30)));
const singer=$('#singer'); singer.value=localStorage.getItem('vk_singer')||'';
singer.addEventListener('change',()=>localStorage.setItem('vk_singer',singer.value));
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2200);}
async function rpc(method,params){const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({method,params})});const j=await r.json();if(!j.ok)throw new Error(j.error);return j.result;}
function codeFromUrl(){const m=location.search.match(/[?&]c=(\\d{4,8})/);return m?m[1]:'';}
async function tryJoin(code){ if(!code)return false; try{const sid=await rpc('session_by_code',{code});if(sid){SID=sid;localStorage.setItem('vk_code',code);return true;}}catch(_){} return false;}
async function joinInput(){const c=$('#code').value.trim(); if(await tryJoin(c)){$('#gate').classList.add('hide');start();} else $('#gerr').textContent='Código não encontrado.';}
async function boot(){const c=codeFromUrl()||localStorage.getItem('vk_code')||''; if(await tryJoin(c)){$('#gate').classList.add('hide');start();}}
function start(){browseAll();renderMine();pollQueue();setInterval(pollQueue,4000);}
function render(items){
  $('#list').innerHTML=items.slice(0,400).map(s=>
    `<div class="it"><div><b>${esc(s.title)}</b><small>${esc((s.artists||[]).join(', '))}</small></div>
     <button onclick="req('${s.id}','${esc(s.title)}')">Pedir</button></div>`).join('')||'<p class="muted">Nada.</p>';
}
async function browseAll(){const p=await rpc('browse_songs',{page:{limit:500}});render(p.items||[]);}
async function doSearch(){const q=$('#q').value.trim();if(!q)return browseAll();const p=await rpc('search_songs',{query:q});render(p.items||[]);}
async function req(id,title){const nome=singer.value.trim()||'Convidado';
  const r=await rpc('request_song',{session_id:SID,song_id:id,singer:nome,device:'celular'});
  MINE.push({id:r.id,song_id:id,title,singer:nome,status:'pend'});saveMine();renderMine();
  toast('⏳ '+title+' — pedida (aguardando aprovação)');}
function renderMine(){$('#mine').innerHTML=MINE.slice().reverse().map(m=>{
  const lbl=m.status==='ok'?'aprovada ✓':'aguardando';const cls=m.status==='ok'?'ok':'pend';
  return `<div class="it"><span>${esc(m.title)}</span><span class="tag ${cls}">${lbl}</span></div>`;}).join('')||'<p class="muted">Nada ainda.</p>';}
async function pollQueue(){ if(!SID)return;
  let q; try{q=await rpc('queue_list',{session_id:SID});}catch(_){return;}
  $('#queue').innerHTML=(q||[]).map((it,i)=>`<div class="it"><span>${i+1}. <b>${esc(it.singer)}</b> — ${esc(it.song_title)}</span></div>`).join('')||'<p class="muted">Fila vazia.</p>';
  // marca meus pedidos que já entraram na fila como aprovados
  const insong=new Set((q||[]).map(it=>it.song_id));
  let ch=false; MINE.forEach(m=>{if(m.status!=='ok'&&insong.has(m.song_id)){m.status='ok';ch=true;}});
  if(ch){saveMine();renderMine();}
}
$('#q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
$('#q').addEventListener('input',e=>{if(!e.target.value.trim())browseAll();});
$('#code').addEventListener('keydown',e=>{if(e.key==='Enter')joinInput();});
boot();
</script></body></html>"""
