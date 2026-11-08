"""Fase G1 — resolver a RemoteSource para uma URL tocável.

A nuvem não hospeda o MP4: dado um song_id, acha a fonte remota (youtube, da
tabela remote_sources/A4) e resolve para uma URL progressiva via o backend
(yt-dlp). Backend injetável p/ testar sem tocar o YouTube.
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
    # fonte: remote_source 'youtube' (A4) ou o source_url do próprio arquivo
    src = None
    with client._uow() as uow:
        for r in uow.remote_sources.by_media(v.id):
            if r.kind == "youtube" and r.uri:
                src = r.uri
                break
    src = src or v.source_url
    if not src:
        return {"error": "sem fonte remota (sem URL)"}
    try:
        url = (backend or _default_backend()).stream_url(src, max_height=max_height)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"resolução falhou: {type(exc).__name__}: {exc}"}
    return {"kind": "youtube", "uri": url, "source": src,
            "duration_s": v.duration_s, "title": sv.title,
            "artist": ", ".join(sv.artists) if sv.artists else ""}
