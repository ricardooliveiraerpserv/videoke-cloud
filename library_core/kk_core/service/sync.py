"""Fase F3 — sync Desktop→Cloud (empurra o catálogo leve, SEM a mídia).

Lê o catálogo LOCAL (SQLite) e, para cada arquivo, reconstrói um RegisterMediaDTO
(metadados + source_url, organize=False) e manda para a NUVEM via `register(dto)`.
A nuvem reusa seu próprio ingest: dedup por sha256/song_key, FTS, remote_sources.

Incremental por cursor `updated_at` (persistido pelo chamador). Idempotente: o
mesmo sha256 não duplica. NÃO envia MP4.
"""
from __future__ import annotations

import json
import urllib.request
from collections import defaultdict
from datetime import datetime

from kk_shared.contracts.dtos import RegisterMediaDTO


def make_http_register(cloud_url: str, admin_token: str):
    """Fábrica do `register` que posta register_media na API da nuvem (/rpc)."""
    endpoint = cloud_url.rstrip("/") + "/rpc"

    def register(dto: RegisterMediaDTO) -> bool:
        body = json.dumps({"method": "register_media",
                           "params": {"dto": dto.model_dump(mode="json")}}).encode()
        req = urllib.request.Request(
            endpoint, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {admin_token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return bool(json.loads(r.read()).get("ok"))

    return register


def push_catalog(local_client, register, *, since_iso: str | None = None,
                 limit: int | None = None) -> tuple[int, str | None]:
    """Empurra arquivos locais (updated_at > since) para a nuvem via `register`.
    Retorna (quantos enviados, novo_cursor_iso)."""
    from sqlalchemy import select

    from ..infrastructure.db.models import ArtistModel, MediaFileModel, SongArtistModel

    sent = 0
    cursor = since_iso
    with local_client._uow() as uow:
        s = uow.session
        # mapa song_id -> [nomes de artista]
        art_map: dict[str, list[str]] = defaultdict(list)
        for sid, name in s.execute(
            select(SongArtistModel.song_id, ArtistModel.name)
            .join(ArtistModel, ArtistModel.id == SongArtistModel.artist_id)
        ).all():
            art_map[sid].append(name)

        q = (select(MediaFileModel)
             .where(MediaFileModel.deleted_at.is_(None))
             .order_by(MediaFileModel.updated_at))
        if since_iso:
            q = q.where(MediaFileModel.updated_at > datetime.fromisoformat(since_iso))
        if limit:
            q = q.limit(limit)

        for mf in s.execute(q).scalars():
            song = mf.song
            if song is None:
                continue
            dto = RegisterMediaDTO(
                title=song.title, artists=art_map.get(song.id, []),
                album=song.album, year=song.year, language=song.language,
                container=mf.container, video_codec=mf.video_codec,
                audio_codec=mf.audio_codec, duration_s=mf.duration_s,
                resolution=mf.resolution, sha256=mf.sha256,
                source_url=mf.source_url, source_title=mf.source_title,
                source_path=mf.path or "/cloud/placeholder",
                organize=False, trust_artist=True,
            )
            if register(dto):
                sent += 1
            if mf.updated_at:
                cursor = mf.updated_at.isoformat()
    return sent, cursor
