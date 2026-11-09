"""Fase G1/G2 — resolver a RemoteSource para uma URL tocável.

A nuvem não hospeda o acervo: dado um song_id, procura primeiro um HOT-CACHE
(remote_source 'cloud_cache' = MP4 no Supabase Storage, URL estável e NÃO presa
a IP → à prova do bloqueio do YouTube em datacenter); se não houver, cai no
'youtube' (A4) e resolve pra uma URL progressiva via o backend (yt-dlp). Backend
injetável p/ testar sem tocar o YouTube.
"""
from __future__ import annotations


def _default_backend():
    from kk_downloader.infrastructure.ytdlp_adapter import YtDlpBackend
    return YtDlpBackend()


def resolve_source(client, song_id: str, backend=None, *, max_height: int = 720) -> dict:
    sv = client.get_song(song_id)
    if not sv or not sv.versions:
        return {"error": "música sem versão"}
    v = sv.versions[0]
    artist = ", ".join(sv.artists) if sv.artists else ""
    # fonte: HOT-CACHE 'cloud_cache' (G2, Storage) tem prioridade; senão 'youtube'/source_url
    cached = None
    youtube_src = None
    with client._uow() as uow:
        for r in uow.remote_sources.by_media(v.id):
            if r.kind == "cloud_cache" and r.uri and cached is None:
                cached = r.uri
            elif r.kind == "youtube" and r.uri and youtube_src is None:
                youtube_src = r.uri
    if cached:
        # já é uma URL tocável (Storage) — nada de yt-dlp
        return {"kind": "cloud_cache", "uri": cached, "source": cached,
                "duration_s": v.duration_s, "title": sv.title, "artist": artist}
    src = youtube_src or v.source_url
    if not src:
        return {"error": "sem fonte remota (sem URL)"}
    try:
        url = (backend or _default_backend()).stream_url(src, max_height=max_height)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"resolução falhou: {type(exc).__name__}: {exc}"}
    return {"kind": "youtube", "uri": url, "source": src,
            "duration_s": v.duration_s, "title": sv.title, "artist": artist}
