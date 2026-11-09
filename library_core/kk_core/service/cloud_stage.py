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
