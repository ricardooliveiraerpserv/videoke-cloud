"""Palco rico servido PELA NUVEM (F4+): reusa a página do POC (tom/ritmo/letra/
intro/avatar + SoundTouch em AudioWorklet — a nuvem é HTTPS, contexto seguro) e
só adapta a resolução de fonte à nuvem:

- cloud_cache (MP4 no Supabase Storage, que já manda Access-Control-Allow-Origin:*)
  é tocado DIRETO (Web Audio/pitch-shift funciona), sem passar o vídeo pelo Render.
- esconde o painel de log de debug da POC (vira produto).

As rotas /poc/* e /resolve são servidas pelo asgi da nuvem.
"""
from __future__ import annotations

from . import poc

# G1 — injetado no player quando aberto como /m?session=<id> (a TV = receiver).
# Toca a fila em ordem, avança sozinho no fim e obedece a /pb/state (controle).
# Roda no mesmo escopo do script da POC → usa SEL/tom/rit/active/startSinging/etc.
_RECEIVER_JS = (
    "\n/* G1 receiver (TV) */\n(function(){\n"
    " var m=location.search.match(/[?&]session=([0-9a-fA-F-]{8,})/); if(!m) return;\n"
    " var SESSION=m[1], rxIdx=-1, rxQueue=[], rxSeek=0, rxEnded=-1;\n"
    " var w=document.createElement('div'); w.id='rxwait';\n"
    " w.style.cssText='position:fixed;inset:0;z-index:60;display:none;flex-direction:column;"
    "align-items:center;justify-content:center;gap:16px;background:#0B1120;color:#E8ECF6;"
    "text-align:center;padding:24px;font-family:-apple-system,system-ui,sans-serif';\n"
    " w.innerHTML='<div style=\"font-size:60px\">\\uD83C\\uDFA4</div>"
    "<div id=\"rxwT\" style=\"font-size:24px;font-weight:800\">Aguardando a fila\\u2026</div>"
    "<div style=\"color:#9AA6C0\">Pe\\u00e7a sua m\\u00fasica pelo celular</div>';\n"
    " document.body.appendChild(w);\n"
    " function showWait(t){ w.style.display='flex'; if(t) document.getElementById('rxwT').textContent=t; }\n"
    " function hideWait(){ w.style.display='none'; }\n"
    " showWait();\n"
    " function playIdx(i){ var it=rxQueue[i]; if(!it){ showWait('Aguardando a fila\\u2026'); return; }\n"
    "   rxIdx=i; rxEnded=-1;\n"
    "   SEL={id:it.song_id,title:it.song_title||'',artist:(it.artists&&it.artists.join)?it.artists.join(', '):''};\n"
    "   var sn=document.querySelector('#singer'); if(sn) sn.value=it.singer||'';\n"
    "   hideWait(); try{ startSinging(); }catch(e){} }\n"
    " function applyTomRit(st){\n"
    "   if(typeof st.tom==='number'&&st.tom!==tom){ tom=st.tom; try{syncTomRit();applyAudio();}catch(e){} }\n"
    "   if(typeof st.rit==='number'&&st.rit!==rit){ rit=st.rit; try{syncTomRit();applyAudio();}catch(e){} } }\n"
    " async function tick(){ try{\n"
    "   var d=await (await fetch('/pb/state?session='+SESSION)).json(); rxQueue=d.queue||[]; var st=d.state||{};\n"
    "   applyTomRit(st);\n"
    "   if(st.idx!==rxIdx){ playIdx(st.idx); }\n"
    "   if(active&&active.video){ var v=active.video;\n"
    "     if(st.paused && !v.paused){ v.pause(); try{document.querySelector('#pp').textContent='\\u25B6';}catch(e){} }\n"
    "     else if(!st.paused && v.paused && rxIdx>=0 && rxQueue[rxIdx]){ v.play().catch(function(){}); try{document.querySelector('#pp').textContent='\\u23F8';}catch(e){} }\n"
    "     if(st.seek_nonce && st.seek_nonce!==rxSeek){ rxSeek=st.seek_nonce; try{ v.currentTime=st.seek_to||0; }catch(e){} }\n"
    "   }\n"
    "   var vv=active&&active.video;\n"
    "   fetch('/pb/report',{method:'POST',headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({session:SESSION,idx:rxIdx,title:(SEL&&SEL.title)||'',"
    "singer:(rxQueue[rxIdx]&&rxQueue[rxIdx].singer)||'',t:vv?vv.currentTime:0,"
    "dur:vv?(vv.duration||0):0,paused:vv?vv.paused:true})}).catch(function(){});\n"
    "  }catch(e){} }\n"
    " document.addEventListener('ended', function(ev){\n"
    "   if(ev.target&&ev.target.tagName==='VIDEO'&&rxIdx>=0&&rxEnded!==rxIdx){ rxEnded=rxIdx;\n"
    "     showWait('Carregando pr\\u00f3xima\\u2026');\n"
    "     fetch('/pb/ended',{method:'POST',headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({session:SESSION,idx:rxIdx})}).catch(function(){}); } }, true);\n"
    " setInterval(tick,1500); tick();\n"
    "})();\n"
)


def _build() -> str:
    html = poc.POC_HTML
    # cloud_cache (Storage c/ CORS) toca DIRETO — não proxyar pelo Render
    html = html.replace(
        "if(info.kind==='local')return info.uri;",
        "if(info.kind==='local'||info.kind==='cloud_cache')return info.uri;",
    )
    # produto: esconde o log de debug do POC
    html = html.replace("</style>", "#log{display:none!important}\n</style>")
    # feedback visível no intro: carregando / indisponível (não cacheada)
    html = html.replace(
        "try{info=await resolveSrc(SEL.id,MODE);}catch(e){log('❌ resolve: '+e.message);return;}",
        "var _ih=document.querySelector('#iHint');"
        "if(_ih){_ih.textContent='⏳ Carregando…';_ih.style.color='#A78BFA';}"
        "try{info=await resolveSrc(SEL.id,MODE);}"
        "catch(e){if(_ih){_ih.textContent='⚠️ Indisponível na nuvem — música ainda não cacheada';"
        "_ih.style.color='#FBBF24';}log('resolve: '+e.message);return;}",
    )
    # produto: tira o marcador de versão do rodapé
    html = html.replace("Videokê Família Silva · v19", "Videokê Família Silva")
    # G1: modo RECEIVER — ?session=<id> → a TV toca a fila e obedece ao controle
    anchor = "document.addEventListener('pointerdown',arm);"
    html = html.replace(anchor, anchor + _RECEIVER_JS)
    # auto-play por ?song=<id> (operador toca a fila abrindo /m?song=…)
    html = html.replace(
        "loadCategories().then(loadCatalog);",
        "loadCategories().then(loadCatalog);"
        "(function(){var m=location.search.match(/[?&]song=([0-9a-fA-F-]{8,})/);if(!m)return;"
        "var id=m[1];fetch('/poc/resolve/'+id).then(r=>r.json()).then(d=>{"
        "SEL={id:id,title:(d&&d.title)||'',artist:(d&&d.artist)||''};startSinging();}).catch(()=>{});})();",
    )
    return html


CLOUD_STAGE_HTML = _build()
