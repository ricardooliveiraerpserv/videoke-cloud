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
    return html


CLOUD_STAGE_HTML = _build()
