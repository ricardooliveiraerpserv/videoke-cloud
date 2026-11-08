"""Caso de uso: registrar mídia baixada (o Downloader chama isto).

Faz dedup físico (hash) e lógico (song_key), anexa versão a música existente
ou cria nova, mantém o índice FTS e publica MediaFileAdded.
"""
from __future__ import annotations

import re

from kk_shared.contracts.dtos import RegisterMediaDTO, SongView
from kk_shared.events.catalog import MediaFileAdded
from kk_shared.platform.known_artists import KNOWN_ARTISTS
from kk_shared.platform.text import normalize

from pathlib import Path

from ..domain.catalog.entities import MediaFile, Song
from ..domain.services import IFileOrganizer
from ..domain.value_objects import Duration, Resolution
from ..infrastructure.fs.organizer import NullOrganizer
from .mappers import to_song_view

# "cara de música" (não de artista): usado no guard de importação — nome com artigo/preposição
# no início, frase longa, número, ou curto demais. Artista NOVO assim vai pra quarentena (Lixeira).
_JUNK_START = re.compile(
    r"^(a|o|as|os|um|uma|ao|aos|da|de|do|das|dos|na|no|nas|nos|e|é|ó|ai|que|se|pra|por|com|sem|meu|minha|mas|mar|me)\s",
    re.IGNORECASE)


def _looks_like_junk_artist(name: str) -> bool:
    n = (name or "").strip()
    if sum(c.isalnum() for c in n) < 3:
        return True
    if _JUNK_START.match(n):
        return True
    if len(n.split()) > 5:
        return True
    if n[:1].isdigit() and len(n.split()) > 2:
        return True
    return False


class IngestDownloadedMediaUseCase:
    def __init__(self, organizer: IFileOrganizer | None = None):
        self._organizer = organizer or NullOrganizer()

    def execute(self, uow, dto: RegisterMediaDTO) -> SongView | None:
        # 0) lista negra: arquivo banido não volta ao acervo (por hash OU por URL).
        #    EXCEÇÃO: download explícito por URL (ignore_blacklist) DESTRAVA — o
        #    usuário pediu de volta aquele vídeo, então removemos o banimento e segue.
        if dto.ignore_blacklist:
            if dto.sha256:
                uow.blacklist.remove(dto.sha256)
            if dto.source_url:
                uow.blacklist.remove_url(dto.source_url)
        else:
            if dto.sha256 and uow.blacklist.contains(dto.sha256):
                return None
            if dto.source_url and uow.blacklist.contains_url(dto.source_url):
                return None
        # 1) dedup físico: já temos este arquivo exato?
        if dto.sha256:
            existing = uow.media.by_hash(dto.sha256)
            if existing:
                song = uow.songs.get(existing.song_id)
                if song:
                    # re-catalogação: se a detecção de artista mudou (acervo antigo
                    # sem artista, ou artista corrigido), atualiza título/artista.
                    new_norm = {normalize(n) for n in dto.artists if n.strip()}
                    cur_norm = {normalize(a.name) for a in song.artists}
                    if new_norm and new_norm != cur_norm:
                        arts = [uow.artists.resolve_or_create(n, KNOWN_ARTISTS)
                                for n in dto.artists if n.strip()]
                        uow.songs.retitle(song.id, dto.title, arts)
                        uow.search.upsert(song.id, normalize(dto.title),
                                          normalize(" ".join(dto.artists)))
                        song = uow.songs.get(song.id)
                    return to_song_view(song)

        # 2) resolve artistas e canal — resolve_or_create colapsa variantes quase
        # idênticas no cadastro (evita poluir com 'Allan e Aladim' vs 'Alan e Aladim')
        artists = [uow.artists.resolve_or_create(n, KNOWN_ARTISTS)
                   for n in dto.artists if n.strip()]
        channel = None
        if dto.channel_name:
            channel = uow.channels.get_or_create(dto.channel_name, dto.channel_external_id)

        media = MediaFile(
            channel=channel, container=dto.container,
            video_codec=dto.video_codec, audio_codec=dto.audio_codec,
            duration=Duration(dto.duration_s or 0),
            resolution=Resolution.parse(dto.resolution),
            sha256=dto.sha256, source_url=dto.source_url, source_title=dto.source_title,
        )
        # o Core assume a organização física (salvo import que referencia no lugar)
        if dto.organize:
            ext = Path(dto.source_path).suffix
            media.path = self._organizer.organize(
                dto.source_path, media_id=media.id, title=dto.title,
                artists=[a.name for a in artists], ext=ext,
            )
        else:
            media.path = dto.source_path

        # 3) dedup lógico: a música já existe? então só anexa a versão.
        tmp = Song(title=dto.title, artists=artists)
        existing_song = uow.songs.by_song_key(tmp.song_key())
        if existing_song:
            media.song_id = existing_song.id
            uow.media.add(media)
            existing_song.media_files.append(media)
            song = existing_song
        else:
            song = Song(
                title=dto.title, artists=artists, album=dto.album,
                year=dto.year, language=dto.language,
                genres=dto.genres, categories=dto.categories,
            )
            song.add_version(media)
            uow.songs.add(song)
            artist_norm = normalize(" ".join(a.name for a in artists))
            uow.search.upsert(song.id, normalize(song.title), artist_norm)
            # taxonomia (nível música — só na criação)
            if dto.album:
                uow.songs.set_album(song.id, uow.albums.get_or_create(dto.album, dto.year))
            uow.tags.link_genres(song.id, dto.genres)
            uow.tags.link_categories(song.id, dto.categories)
            # QUARENTENA (guard de importação): se o ÚNICO artista é NOVO (só esta música) e o
            # nome tem cara de MÚSICA (não de artista), a faixa vai pra Lixeira p/ o usuário revisar —
            # evita entrar lixo. Artista já aprovado (com outras músicas) ou nome normal passa direto.
            if not dto.trust_artist and len(artists) == 1 and _looks_like_junk_artist(artists[0].name) \
                    and len(uow.artists.song_ids(artists[0].id)) <= 1:
                uow.songs.soft_delete(song.id)
                uow.search.remove(song.id)

        # nível arquivo (ambos os caminhos)
        kind = "audio" if not dto.video_codec and dto.audio_codec else "video"
        if dto.source_url:
            uow.downloads.record(url=dto.source_url, title=song.title,
                                 kind=kind, media_file_id=media.id)
            # A4: materializa a fonte remota (o que a nuvem sincroniza)
            uow.remote_sources.upsert(media.id, dto.source_url, kind="youtube",
                                      song_id=song.id, status="unknown")
        if dto.thumbnail_path and Path(dto.thumbnail_path).exists():
            uow.thumbnails.add(media.id, dto.thumbnail_path)

        uow.add_event(MediaFileAdded(song_id=song.id, media_file_id=media.id, title=song.title))
        return to_song_view(song)
