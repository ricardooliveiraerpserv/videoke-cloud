"""InProcessLibraryClient — implementação in-process do contrato LibraryClient
(ADR-1). Gerencia a Unit of Work por operação e publica os eventos coletados no
Event Bus após o commit. Trocar por IPC/HTTP no futuro não afeta as apps.
"""
from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

import os

from kk_shared.contracts.dtos import (
    ArtistCategoryView,
    ArtistView,
    EnqueueDTO,
    HistoryEntryView,
    LyricsView,
    MediaSourceDTO,
    Page,
    PageReq,
    PlaylistItemView,
    PlaylistView,
    PresetDTO,
    QueueItemView,
    RegisterMediaDTO,
    SearchFilters,
    SongRequestView,
    SongRowView,
    SongView,
)
from kk_shared.contracts.enums import QueueStatus
from kk_shared.events.bus import EventBus, Handler, Subscription

from ..infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from .ingest_service import IngestDownloadedMediaUseCase
from .mappers import to_song_row_view, to_song_view
from .queue_service import QueueService
from .search_service import SearchSongsUseCase


class InProcessLibraryClient:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        bus: EventBus | None = None,
        organizer=None,
    ):
        self._sf = session_factory
        self._bus = bus or EventBus()
        self._ingest = IngestDownloadedMediaUseCase(organizer)
        self._search = SearchSongsUseCase()
        self._queue = QueueService()

    def _uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._sf)

    # --- escrita ---
    def register_media(self, dto: RegisterMediaDTO) -> SongView | None:
        with self._uow() as uow:
            view = self._ingest.execute(uow, dto)   # None se estiver na lista negra
            uow.commit()
            events = list(uow.events)
        for ev in events:
            self._bus.publish(ev)
        return view

    def blacklist_songs(self, song_ids: list[str]) -> int:
        """Exclui VÁRIAS músicas de uma vez (soft-delete + bane arquivos). Retorna quantas."""
        with self._uow() as uow:
            n = 0
            for sid in (song_ids or []):
                song = uow.songs.get(sid)
                if not song:
                    continue
                artist = song.artists[0].name if song.artists else None
                url_by_sha = {mf.sha256: mf.source_url for mf in song.media_files}
                for h in uow.songs.soft_delete(sid):
                    uow.blacklist.add(h, title=song.title, artist=artist, reason="user",
                                      source_url=url_by_sha.get(h))
                uow.search.remove(sid)
                n += 1
            uow.artists.delete_orphans()
            uow.commit()
            return n

    def purge_songs(self, song_ids: list[str]) -> dict:
        """Exclusão DEFINITIVA: apaga o arquivo físico do disco (libera espaço) e
        mantém sha256 + URL na lista negra (nunca reimporta). Ao contrário do
        'Excluir' normal, NÃO dá pra restaurar. Só apaga arquivos dentro de media/;
        se o caminho aponta pra fora (import no lugar), preserva o arquivo e avisa."""
        import os
        from pathlib import Path

        from kk_shared.platform.paths import default_media_dir
        from ..infrastructure.db.models import MediaFileModel, SongModel

        # apaga só arquivos sob o media root REAL do organizador (imports "no lugar"
        # que apontam pra fora são preservados). Fallback: media dir padrão.
        _root = getattr(getattr(self._ingest, "_organizer", None), "root", None)
        media_root = Path(_root or default_media_dir()).resolve()
        purged = files_deleted = skipped_external = 0
        freed = 0
        with self._uow() as uow:
            for sid in (song_ids or []):
                # acesso DIRETO ao modelo: pega a música mesmo já na lixeira
                # (uow.songs.get filtra soft-deleted → não servia para 'Excluídas')
                song = uow.session.get(SongModel, sid)
                if not song:
                    continue
                title, artist = song.title, (song.artists[0].artist.name if song.artists else None)
                # TODAS as mídias, inclusive as já soft-deleted
                medias = uow.session.query(MediaFileModel).filter(
                    MediaFileModel.song_id == sid).all()
                paths = []
                for mf in medias:                                 # bane e coleta caminhos
                    uow.blacklist.add(mf.sha256, title=title, artist=artist,
                                      reason="purge", source_url=mf.source_url)
                    if mf.path:
                        paths.append(mf.path)
                uow.search.remove(sid)
                # remove DEFINITIVAMENTE do banco (some da Lixeira/Excluídas; segue
                # banido por hash+URL, então não reimporta). Cascata apaga mídias/vínculos.
                uow.session.query(SongModel).filter(SongModel.id == sid).delete(
                    synchronize_session=False)
                purged += 1
                for p in paths:                                   # apaga o arquivo físico
                    try:
                        rp = Path(p).resolve()
                        if not rp.is_file():
                            continue
                        if media_root not in rp.parents:          # fora do media/ → não apaga
                            skipped_external += 1
                            continue
                        sz = rp.stat().st_size
                        os.remove(rp)
                        files_deleted += 1
                        freed += sz
                        for d in (rp.parent, rp.parent.parent):   # limpa pastas vazias
                            try:
                                if d != media_root and d.is_dir() and not any(d.iterdir()):
                                    d.rmdir()
                            except OSError:
                                break
                    except OSError:
                        pass
            uow.artists.delete_orphans()
            uow.commit()
        return {"purged": purged, "files_deleted": files_deleted,
                "skipped_external": skipped_external,
                "freed_mb": round(freed / 1e6, 1)}

    def trash_songs(self, song_ids: list[str]) -> int:
        """Manda várias músicas para a LIXEIRA (soft-delete, restauráveis) SEM banir
        — usado pela varredura de duração. Diferente de blacklist_songs (que bane)."""
        with self._uow() as uow:
            n = 0
            for sid in (song_ids or []):
                if not uow.songs.get(sid):
                    continue
                uow.songs.soft_delete(sid)      # só lixeira; sem lista negra
                uow.search.remove(sid)
                n += 1
            uow.artists.delete_orphans()
            uow.commit()
            return n

    def blacklist_media(self, media_file_id: str) -> None:
        """Exclui UMA versão (arquivo) e a bane; se foi a última, exclui a música."""
        with self._uow() as uow:
            mf = uow.media.get(media_file_id)
            if not mf:
                return
            song = uow.songs.get(mf.song_id)
            artist = song.artists[0].name if song and song.artists else None
            title = song.title if song else None
            uow.blacklist.add(mf.sha256, title=title, artist=artist, reason="user",
                              source_url=mf.source_url)
            uow.media.soft_delete(media_file_id)
            song = uow.songs.get(mf.song_id)          # re-lê já sem a versão excluída
            if song and not song.media_files:          # música sem versões vivas → some
                uow.songs.soft_delete(song.id)
                uow.search.remove(song.id)
                uow.artists.delete_orphans()
            uow.commit()

    def list_trash(self) -> list[SongView]:
        """Músicas na lixeira (excluídas), p/ restaurar."""
        with self._uow() as uow:
            return [to_song_view(s) for s in uow.songs.list_deleted()]

    def restore_song(self, song_id: str) -> SongView | None:
        """Restaura uma música excluída e a tira da lista negra."""
        from kk_shared.platform.text import normalize
        with self._uow() as uow:
            hashes = uow.songs.restore(song_id)
            for h in hashes:
                uow.blacklist.remove(h)
            song = uow.songs.get(song_id)
            if song:
                for mf in song.media_files:       # tira também a URL da lista negra
                    uow.blacklist.remove_url(mf.source_url)
                uow.search.upsert(song_id, normalize(song.title),
                                  normalize(" ".join(a.name for a in song.artists)))
            uow.commit()
            return to_song_view(song) if song else None

    def blacklist_song(self, song_id: str) -> None:
        """Exclui a música do acervo e bane seus arquivos (não reimporta)."""
        with self._uow() as uow:
            song = uow.songs.get(song_id)
            if not song:
                return
            artist = song.artists[0].name if song.artists else None
            url_by_sha = {mf.sha256: mf.source_url for mf in song.media_files}
            hashes = uow.songs.soft_delete(song_id)
            for h in hashes:
                uow.blacklist.add(h, title=song.title, artist=artist, reason="user",
                                  source_url=url_by_sha.get(h))
            uow.search.remove(song_id)
            uow.artists.delete_orphans()
            uow.commit()

    # --- leitura ---
    def search_songs(
        self, query: str, filters: SearchFilters | None = None, page: PageReq | None = None
    ) -> Page[SongView]:
        with self._uow() as uow:
            return self._search.execute(uow, query, filters, page)

    def get_song(self, song_id: str) -> SongView | None:
        with self._uow() as uow:
            song = uow.songs.get(song_id)
            return to_song_view(song) if song else None

    def update_song(self, song_id: str, title: str, artists: list[str]) -> SongView | None:
        with self._uow() as uow:
            song = uow.songs.get(song_id)
            if not song:
                return None
            arts = [uow.artists.get_or_create(n) for n in artists if n.strip()]
            uow.songs.retitle(song_id, title, arts)
            from kk_shared.platform.text import normalize
            uow.search.upsert(song_id, normalize(title), normalize(" ".join(artists)))
            uow.artists.delete_orphans()
            uow.commit()
            song = uow.songs.get(song_id)
            return to_song_view(song) if song else None

    def list_artists(self) -> list[str]:
        with self._uow() as uow:
            return uow.artists.all_names()

    def has_media_url(self, source_url: str) -> bool:
        """Já existe no acervo uma mídia baixada desta URL? (evita re-baixar)."""
        with self._uow() as uow:
            return uow.media.url_exists(source_url)

    def existing_media_urls(self, urls: list[str]) -> list[str]:
        """Das URLs dadas, quais já estão no acervo (marcar na busca de download)."""
        with self._uow() as uow:
            return uow.media.existing_urls(urls)

    # --- cadastro de artistas (rotina de Ajustes) ---
    def list_artists_detail(self) -> list[ArtistView]:
        with self._uow() as uow:
            cats = uow.artist_categories.map_for_artists()   # artist_id → (cat_id, cat_name)
            out = []
            for i, n, c in uow.artists.list_with_counts():
                cat = cats.get(i)
                out.append(ArtistView(id=i, name=n, song_count=c,
                                      category_id=cat[0] if cat else None,
                                      category=cat[1] if cat else None))
            return out

    def artist_duplicate_clusters(self) -> list[list[ArtistView]]:
        """Grupos de artistas com nomes quase idênticos (acento/typo) — candidatos
        a mesclar. Cada grupo vem ordenado com o de MAIS músicas primeiro (canônico
        provável). Passa por confirmação humana → limiar mais solto que o do import."""
        from difflib import SequenceMatcher

        from kk_shared.platform.naming import _akey

        with self._uow() as uow:
            rows = uow.artists.list_with_counts()            # (id, name, count)
        items = [(i, n, c, _akey(n)) for i, n, c in rows]
        parent = {i: i for i, _n, _c, _k in items}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x

        for a in range(len(items)):
            i1, _n1, _c1, k1 = items[a]
            if not k1:
                continue
            for b in range(a + 1, len(items)):
                i2, _n2, _c2, k2 = items[b]
                if not k2 or abs(len(k1) - len(k2)) > 6:
                    continue
                if SequenceMatcher(None, k1, k2).ratio() >= 0.86:
                    parent[find(i1)] = find(i2)

        by_id = {i: (n, c) for i, n, c, _k in items}
        groups: dict[str, list[str]] = {}
        for i, _n, _c, _k in items:
            groups.setdefault(find(i), []).append(i)
        out: list[list[ArtistView]] = []
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda i: by_id[i][1], reverse=True)
            out.append([ArtistView(id=i, name=by_id[i][0], song_count=by_id[i][1])
                        for i in members])
        out.sort(key=lambda g: sum(a.song_count for a in g), reverse=True)
        return out

    def songs_without_artist(self) -> list[SongView]:
        """Músicas vivas sem nenhum artista vinculado (vínculo manual em massa)."""
        with self._uow() as uow:
            return [to_song_view(s) for s in uow.songs.without_artist()]

    # --- categorias de artista (estilo musical) ---
    def list_categories(self) -> list[ArtistCategoryView]:
        with self._uow() as uow:
            return [ArtistCategoryView(id=i, name=n, artist_count=na, song_count=ns)
                    for i, n, na, ns in uow.artist_categories.list_with_counts()]

    def add_category(self, name: str) -> ArtistCategoryView:
        with self._uow() as uow:
            cid = uow.artist_categories.get_or_create(name)
            uow.commit()
            return ArtistCategoryView(id=cid, name=name.strip())

    def rename_category(self, category_id: str, name: str) -> None:
        with self._uow() as uow:
            uow.artist_categories.rename(category_id, name)
            uow.commit()

    def delete_category(self, category_id: str) -> None:
        with self._uow() as uow:
            uow.artist_categories.delete(category_id)
            uow.commit()

    def set_artist_category(self, artist_id: str, category_id: str | None) -> None:
        with self._uow() as uow:
            uow.artist_categories.set_for_artist(artist_id, category_id)
            uow.commit()

    def set_artists_category(self, artist_ids: list[str], category_id: str | None) -> int:
        with self._uow() as uow:
            n = uow.artist_categories.set_for_artists(list(artist_ids or []), category_id)
            uow.commit()
            return n

    def browse_by_category(self, category_id: str, page: PageReq | None = None) -> Page[SongView]:
        return self.browse_by_categories([category_id], page)

    def browse_by_categories(self, category_ids: list[str], page: PageReq | None = None) -> Page[SongView]:
        page = page or PageReq(limit=500)
        offset = int(page.after) if page.after and page.after.isdigit() else 0
        limit = max(1, page.limit)
        with self._uow() as uow:
            songs = uow.songs.browse_by_categories(list(category_ids or []), limit + 1, offset)
        has_more = len(songs) > limit
        items = [to_song_view(s) for s in songs[:limit]]
        return Page(items=items, total_estimate=len(items),
                    next_cursor=str(offset + limit) if has_more else None)

    def browse_by_artist(self, artist_id: str, page: PageReq | None = None) -> Page[SongView]:
        page = page or PageReq(limit=500)
        offset = int(page.after) if page.after and page.after.isdigit() else 0
        limit = max(1, page.limit)
        with self._uow() as uow:
            songs = uow.songs.browse_by_artist(artist_id, limit + 1, offset)
        has_more = len(songs) > limit
        items = [to_song_view(s) for s in songs[:limit]]
        return Page(items=items, total_estimate=len(items),
                    next_cursor=str(offset + limit) if has_more else None)

    def add_artist(self, name: str) -> ArtistView:
        with self._uow() as uow:
            a = uow.artists.get_or_create(name)
            uow.commit()
            return ArtistView(id=a.id, name=a.name, song_count=0)

    def rename_artist(self, artist_id: str, name: str) -> None:
        with self._uow() as uow:
            sids = uow.artists.song_ids(artist_id)
            uow.artists.rename(artist_id, name)
            self._reindex_songs(uow, sids)
            uow.commit()

    def delete_artist(self, artist_id: str) -> None:
        with self._uow() as uow:
            sids = uow.artists.song_ids(artist_id)
            uow.artists.delete(artist_id)
            self._reindex_songs(uow, sids)     # músicas perderam esse artista
            uow.commit()

    def artist_songs(self, artist_id: str) -> list[SongView]:
        """Músicas vivas vinculadas a um artista (para confirmar antes de excluir)."""
        with self._uow() as uow:
            out = []
            for sid in uow.artists.song_ids(artist_id):
                s = uow.songs.get(sid)
                if s:
                    out.append(to_song_view(s))
            return out

    def delete_artist_with_songs(self, artist_id: str) -> int:
        """Exclui o artista E suas músicas. As músicas vão só para a LIXEIRA
        (soft-delete, restauráveis) — NÃO entram na lista negra, ao contrário do
        'Excluir' de música. Retorna quantas músicas saíram."""
        with self._uow() as uow:
            n = 0
            for sid in uow.artists.song_ids(artist_id):
                song = uow.songs.get(sid)
                if not song:
                    continue
                uow.songs.soft_delete(sid)     # só lixeira; sem banir hash/URL
                uow.search.remove(sid)
                n += 1
            uow.artists.delete(artist_id)
            uow.artists.delete_orphans()
            uow.commit()
            return n

    def merge_artists(self, from_id: str, into_id: str) -> None:
        with self._uow() as uow:
            sids = uow.artists.song_ids(from_id)
            uow.artists.merge(from_id, into_id)
            self._reindex_songs(uow, sids)
            uow.artists.delete_orphans()
            uow.commit()

    def _reindex_songs(self, uow, song_ids: list[str]) -> None:
        """Recalcula song_key + FTS das músicas após mudança de artista."""
        from kk_shared.platform.text import normalize
        for sid in song_ids:
            s = uow.songs.get(sid)
            if s:
                arts = [uow.artists.get_or_create(a.name) for a in s.artists]
                uow.songs.retitle(sid, s.title, arts)
                uow.search.upsert(sid, normalize(s.title),
                                  normalize(" ".join(a.name for a in s.artists)))

    def clean_titles(self) -> int:
        """Limpa TODOS os títulos do acervo (tira karaokê/videokê/artista/ano). Retorna quantos mudaram."""
        from kk_shared.platform.naming import clean_song_title
        from kk_shared.platform.text import normalize
        with self._uow() as uow:
            songs = uow.songs.browse(1_000_000, 0)
            changed = 0
            for song in songs:
                names = [a.name for a in song.artists]
                new = clean_song_title(song.title, names)
                if new and new != song.title:
                    uow.songs.retitle(song.id, new, song.artists)
                    uow.search.upsert(song.id, normalize(new), normalize(" ".join(names)))
                    changed += 1
            uow.commit()
            return changed

    def strip_emoji_titles(self) -> int:
        """Remove emojis dos TÍTULOS de todas as músicas. Retorna quantos mudaram."""
        from kk_shared.platform.naming import strip_emojis
        from kk_shared.platform.text import normalize
        with self._uow() as uow:
            changed = 0
            for song in uow.songs.browse(1_000_000, 0):
                new = strip_emojis(song.title)
                if new and new != song.title:
                    uow.songs.retitle(song.id, new, song.artists)
                    uow.search.upsert(song.id, normalize(new),
                                      normalize(" ".join(a.name for a in song.artists)))
                    changed += 1
            uow.commit()
            return changed

    def extract_artists_from_titles(self) -> int:
        """Quando o TÍTULO contém um artista conhecido (multi-palavra), move-o pra
        coluna Artista (grafia canônica) e limpa o título (tira karaokê etc).

        SEGURANÇA (evita inversão artista×música):
          - só casa artistas com espaço no nome (duplas/nomes completos);
          - candidatos = dicionário + artistas da tabela com >=3 músicas
            (ignora os de 1 música, que costumam ser título virado artista);
          - só grava se realmente mudar algo."""
        from kk_shared.platform.known_artists import KNOWN_ARTISTS, canonical_artist
        from kk_shared.platform.naming import clean_song_title, split
        from kk_shared.platform.text import normalize

        def _dedup(names):
            seen, out = set(), []
            for n in names:
                k = normalize(n)
                if k and k not in seen:
                    seen.add(k); out.append(n)
            return out

        with self._uow() as uow:
            trusted = [name for _id, name, count in uow.artists.list_with_counts()
                       if count >= 3 and " " in name]
            pool = [n for n in _dedup(sorted(trusted, key=len, reverse=True) + KNOWN_ARTISTS)
                    if " " in n]                        # só nomes com espaço
            songs = uow.songs.browse(1_000_000, 0)
            changed = 0
            for song in songs:
                arts, title = split(song.title, pool)
                if not arts:
                    continue
                arts = [canonical_artist(a) for a in arts]     # apelido → canônico
                clean = clean_song_title(title, arts) or song.title
                new_norm = {normalize(a) for a in arts}
                cur_norm = {normalize(a.name) for a in song.artists}
                if clean == song.title and new_norm == cur_norm:
                    continue                            # nada a fazer
                objs = [uow.artists.get_or_create(a) for a in arts]
                uow.songs.retitle(song.id, clean, objs)
                uow.search.upsert(song.id, normalize(clean), normalize(" ".join(arts)))
                changed += 1
            uow.commit()
            return changed

    def extract_artists_from_youtube(self) -> int:
        """Para músicas SEM artista, tenta descobri-lo no TÍTULO ORIGINAL do YouTube
        (source_title) — inclusive nos formatos de canal de karaokê que o parser
        normal descarta: 'Made Popular By X', 'No Estilo de X', 'Style X', '(Dupla)'.
        Só grava quando acha um artista. Retorna quantas músicas resolveu."""
        from kk_shared.platform.known_artists import KNOWN_ARTISTS, canonical_artist
        from kk_shared.platform.naming import (
            artist_from_context, clean_song_title, split, split_names,
        )
        from kk_shared.platform.text import normalize
        from ..infrastructure.db.models import MediaFileModel, SongModel

        pool = sorted({n for n in KNOWN_ARTISTS if " " in n}, key=len, reverse=True)
        with self._uow() as uow:
            rows = (uow.session.query(SongModel.id, MediaFileModel.source_title)
                    .join(MediaFileModel, MediaFileModel.song_id == SongModel.id)
                    .filter(SongModel.deleted_at.is_(None),
                            MediaFileModel.deleted_at.is_(None),
                            MediaFileModel.source_title.isnot(None),
                            MediaFileModel.source_title != "")
                    .all())
            yt_by_song: dict[str, str] = {}
            for sid, st in rows:
                yt_by_song.setdefault(sid, st)      # 1º título por música

            changed = 0
            for song in uow.songs.browse(1_000_000, 0):
                if song.artists:                    # só as que estão sem artista
                    continue
                yt = yt_by_song.get(song.id)
                if not yt:
                    continue
                arts, rest = split(yt, pool)        # 1) dicionário no título do YouTube
                if not arts:                        # 2) contexto de canal ('(Dupla)', 'Estilo de…')
                    ctx = artist_from_context(yt, pool)
                    if ctx:
                        arts = split_names(ctx)
                        rest = yt
                if not arts:
                    continue
                arts = [canonical_artist(a) for a in arts]
                clean = clean_song_title(rest, arts) or song.title
                objs = [uow.artists.get_or_create(a) for a in arts]
                uow.songs.retitle(song.id, clean, objs)
                uow.search.upsert(song.id, normalize(clean), normalize(" ".join(arts)))
                changed += 1
            uow.commit()
            return changed

    def set_artist_bulk(self, song_ids: list[str], artist: str) -> int:
        """Define o MESMO artista para várias músicas de uma vez (mantém títulos)."""
        from kk_shared.platform.text import normalize
        with self._uow() as uow:
            art = uow.artists.get_or_create(artist) if artist.strip() else None
            arts = [art] if art else []
            n = 0
            for sid in song_ids:
                s = uow.songs.get(sid)
                if not s:
                    continue
                uow.songs.retitle(sid, s.title, arts)
                uow.search.upsert(sid, normalize(s.title), normalize(artist))
                n += 1
            uow.artists.delete_orphans()
            uow.commit()
            return n

    def merge_songs(self, song_ids: list[str]) -> str:
        """Funde as músicas dadas numa só (mantém a 1ª, soma as versões). Retorna o id mantido."""
        from kk_shared.platform.text import normalize
        ids = [s for s in (song_ids or []) if s]
        if len(ids) < 2:
            return ids[0] if ids else ""
        with self._uow() as uow:
            keep = ids[0]
            uow.songs.merge_into(keep, ids[1:])
            for d in ids[1:]:
                uow.search.remove(d)
            uow.artists.delete_orphans()
            uow.commit()
            return keep

    def duplicate_groups(self) -> list[list[SongView]]:
        """Grupos de músicas duplicadas (mesmo título+artista), para curadoria."""
        with self._uow() as uow:
            out = []
            for ids in uow.songs.duplicate_groups():
                grp = [to_song_view(uow.songs.get(i)) for i in ids if uow.songs.get(i)]
                if grp:
                    out.append(grp)
            return out

    def suspect_originals(self) -> list[SongView]:
        """Músicas cujo título original do YouTube NÃO tem marca de videokê
        (karaokê/playback/instrumental…) — provavelmente são a gravação original,
        não a versão para cantar. Para revisão manual."""
        import unicodedata
        from ..infrastructure.db.models import MediaFileModel, SongModel

        def _norm(s: str) -> str:
            return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                           if unicodedata.category(c) != "Mn")
        MARKS = ("karaok", "videok", "playback", "play back", "instrumental",
                 "com letra", "sem vocal", "so a musica", "backing track",
                 "2a voz", "2 voz", "segunda voz", "faixa guia", "minus one",
                 "multiplayback", "multi playback", "trilha")
        with self._uow() as uow:
            rows = (uow.session.query(MediaFileModel.song_id, MediaFileModel.source_title)
                    .join(SongModel, SongModel.id == MediaFileModel.song_id)
                    .filter(MediaFileModel.deleted_at.is_(None),
                            SongModel.deleted_at.is_(None),
                            SongModel.karaoke_confirmed == 0,   # já confirmada não volta
                            MediaFileModel.source_title.isnot(None),
                            MediaFileModel.source_title != "")
                    .all())
            suspect_ids: list[str] = []
            seen: set[str] = set()
            for song_id, title in rows:
                n = _norm(title)
                if not any(m in n for m in MARKS) and song_id not in seen:
                    seen.add(song_id); suspect_ids.append(song_id)
            return [to_song_view(s) for i in suspect_ids
                    if (s := uow.songs.get(i)) is not None]

    def mark_karaoke(self, song_ids: list[str]) -> int:
        """Marca músicas como videokê confirmado → saem de 'Suspeita de original'."""
        from ..infrastructure.db.models import SongModel
        with self._uow() as uow:
            n = (uow.session.query(SongModel)
                 .filter(SongModel.id.in_(song_ids))
                 .update({SongModel.karaoke_confirmed: 1}, synchronize_session=False))
            uow.commit()
            return int(n or 0)

    def dedupe_library(self) -> int:
        """Funde músicas duplicadas (mesmo título+artista) em versões. Retorna quantas removeu."""
        with self._uow() as uow:
            removed = uow.songs.merge_duplicates()
            for sid in removed:
                uow.search.remove(sid)
            uow.commit()
            return len(removed)

    def merge_selected_duplicates(self, song_ids: list[str]) -> int:
        """Entre as músicas DADAS, funde só as que são duplicatas entre si (mesmo song_key =
        título+artista normalizados): mantém a MAIS ANTIGA de cada grupo e move as versões das
        demais pra ela (soft-delete). Não toca em músicas de título/artista diferentes.
        Retorna quantas cópias foram fundidas (removidas)."""
        from collections import defaultdict

        from sqlalchemy import select

        from ..infrastructure.db.models import SongModel
        ids = [s for s in (song_ids or []) if s]
        if len(ids) < 2:
            return 0
        with self._uow() as uow:
            rows = uow.session.scalars(
                select(SongModel).where(SongModel.id.in_(ids), SongModel.deleted_at.is_(None))
            ).all()
            groups: dict[str, list] = defaultdict(list)
            for m in rows:
                groups[m.song_key].append(m)
            removed: list[str] = []
            for members in groups.values():
                if len(members) < 2:
                    continue
                members.sort(key=lambda m: m.created_at)   # mais antiga fica
                keep, drops = members[0].id, [m.id for m in members[1:]]
                uow.songs.merge_into(keep, drops)
                removed.extend(drops)
            for sid in removed:
                uow.search.remove(sid)
            if removed:
                uow.artists.delete_orphans()
            uow.commit()
            return len(removed)

    def explode_versions(self) -> int:
        """Separa cada versão em uma música própria (curadoria manual). Retorna quantas criou."""
        from kk_shared.platform.text import normalize
        with self._uow() as uow:
            new_ids = uow.songs.explode_versions()
            for sid in new_ids:
                s = uow.songs.get(sid)
                if s:
                    uow.search.upsert(sid, normalize(s.title),
                                      normalize(" ".join(a.name for a in s.artists)))
            uow.commit()
            return len(new_ids)

    def browse_songs(self, page: PageReq | None = None) -> Page[SongView]:
        page = page or PageReq(limit=500)
        offset = int(page.after) if page.after and page.after.isdigit() else 0
        limit = max(1, page.limit)
        with self._uow() as uow:
            songs = uow.songs.browse(limit + 1, offset)
            total = uow.songs.count()
        has_more = len(songs) > limit
        items = [to_song_view(s) for s in songs[:limit]]
        return Page(items=items, total_estimate=total,
                    next_cursor=str(offset + limit) if has_more else None)

    def browse_rows(self, page: PageReq | None = None) -> Page[SongRowView]:
        """Como browse_songs, mas com a projeção LEVE (SongRowView) — para a lista
        do operador não travar carregando o grafo de versões de todo o acervo."""
        page = page or PageReq(limit=200)
        offset = int(page.after) if page.after and page.after.isdigit() else 0
        limit = max(1, page.limit)
        with self._uow() as uow:
            rows = uow.songs.browse_rows(limit + 1, offset)
            total = uow.songs.count()
        has_more = len(rows) > limit
        items = [to_song_row_view(r) for r in rows[:limit]]
        return Page(items=items, total_estimate=total,
                    next_cursor=str(offset + limit) if has_more else None)

    def resolve_media_source(self, media_file_id: str) -> MediaSourceDTO | None:
        with self._uow() as uow:
            path = uow.media.path_of(media_file_id)
            if not path:
                return None
            return MediaSourceDTO(media_file_id=media_file_id, uri=path, is_local=True)

    # --- presets ---
    def get_preset(self, song_id: str, user_id: str | None = None) -> PresetDTO | None:
        with self._uow() as uow:
            row = uow.presets.get(song_id, user_id)
            return PresetDTO(pitch=row[0], tempo=row[1]) if row else None

    def save_preset(self, song_id: str, preset: PresetDTO, user_id: str | None = None) -> None:
        with self._uow() as uow:
            uow.presets.save(song_id, preset.pitch, preset.tempo, user_id)
            uow.commit()

    # --- fila de cantores ---
    def _commit_publish(self, uow) -> None:
        uow.commit()
        for ev in list(uow.events):
            self._bus.publish(ev)

    def open_session(self, name: str = "Sessão") -> str:
        with self._uow() as uow:
            sid = self._queue.open_or_get_session(uow, name)
            uow.commit()
            return sid

    def enqueue(self, session_id: str, dto: EnqueueDTO) -> QueueItemView:
        with self._uow() as uow:
            view = self._queue.enqueue(uow, session_id, dto)
            self._commit_publish(uow)
            return view

    def queue_list(self, session_id: str) -> list[QueueItemView]:
        with self._uow() as uow:
            return self._queue.list(uow, session_id)

    def reorder_queue(self, session_id: str, item_id: str, new_index: int) -> None:
        with self._uow() as uow:
            self._queue.reorder(uow, session_id, item_id, new_index)
            self._commit_publish(uow)

    def set_queue_status(self, item_id: str, status: QueueStatus) -> None:
        with self._uow() as uow:
            self._queue.set_status(uow, item_id, status)
            uow.commit()

    def remove_queue_item(self, item_id: str) -> None:
        with self._uow() as uow:
            self._queue.remove(uow, item_id)
            uow.commit()

    def advance_queue(self, session_id: str) -> QueueItemView | None:
        with self._uow() as uow:
            view = self._queue.advance(uow, session_id)
            self._commit_publish(uow)
            return view

    def current_queue_item(self, session_id: str) -> QueueItemView | None:
        with self._uow() as uow:
            return uow.queue.current(session_id)

    # --- Fase D: sessão de convidado com código + pedidos com aprovação ---
    def open_guest_session(self, name: str = "Pedidos") -> dict:
        """Abre (ou reusa) a sessão ativa e garante um código de convidado.
        Retorna {session_id, code} — o code vai para o QR e para a tela."""
        with self._uow() as uow:
            sid = self._queue.open_or_get_session(uow, name)
            code = self._queue.ensure_code(uow, sid)
            uow.commit()
            return {"session_id": sid, "code": code}

    def session_by_code(self, code: str) -> str | None:
        with self._uow() as uow:
            return self._queue.session_by_code(uow, code)

    def request_song(self, session_id: str, song_id: str, singer: str,
                    note: str = "", device: str = "") -> SongRequestView:
        with self._uow() as uow:
            view = self._queue.request_song(uow, session_id, song_id, singer, note, device)
            self._commit_publish(uow)
            return view

    def list_requests(self, session_id: str,
                     status: str = "pending") -> list[SongRequestView]:
        with self._uow() as uow:
            return self._queue.list_requests(uow, session_id, status)

    def approve_request(self, request_id: str) -> QueueItemView:
        with self._uow() as uow:
            view = self._queue.approve_request(uow, request_id)
            self._commit_publish(uow)
            return view

    def reject_request(self, request_id: str) -> None:
        with self._uow() as uow:
            self._queue.reject_request(uow, request_id)
            self._commit_publish(uow)

    # --- playlists ---
    def create_playlist(self, name: str) -> str:
        with self._uow() as uow:
            pid = uow.playlists.create(name); uow.commit(); return pid

    def delete_playlist(self, playlist_id: str) -> None:
        with self._uow() as uow:
            uow.playlists.delete(playlist_id); uow.commit()

    def list_playlists(self) -> list[PlaylistView]:
        with self._uow() as uow:
            return uow.playlists.list()

    def playlist_items(self, playlist_id: str) -> list[PlaylistItemView]:
        with self._uow() as uow:
            return uow.playlists.items(playlist_id)

    def add_to_playlist(self, playlist_id: str, song_id: str) -> str:
        with self._uow() as uow:
            iid = uow.playlists.add_item(playlist_id, song_id); uow.commit(); return iid

    def remove_playlist_item(self, item_id: str) -> None:
        with self._uow() as uow:
            uow.playlists.remove_item(item_id); uow.commit()

    def enqueue_playlist(self, session_id: str, playlist_id: str, singer: str) -> int:
        with self._uow() as uow:
            items = uow.playlists.items(playlist_id)
            for it in items:
                self._queue.enqueue(uow, session_id, EnqueueDTO(song_id=it.song_id, singer=singer))
            self._commit_publish(uow)
            return len(items)

    # --- favoritos ---
    def add_favorite(self, song_id: str, user_id: str | None = None) -> None:
        with self._uow() as uow:
            uow.favorites.add(song_id, user_id); uow.commit()

    def remove_favorite(self, song_id: str, user_id: str | None = None) -> None:
        with self._uow() as uow:
            uow.favorites.remove(song_id, user_id); uow.commit()

    def is_favorite(self, song_id: str, user_id: str | None = None) -> bool:
        with self._uow() as uow:
            return uow.favorites.is_favorite(song_id, user_id)

    def list_favorites(self, user_id: str | None = None) -> list[SongView]:
        with self._uow() as uow:
            views = []
            for sid in uow.favorites.song_ids(user_id):
                song = uow.songs.get(sid)
                if song:
                    views.append(to_song_view(song))
            return views

    # --- letras ---
    def get_lyrics(self, song_id: str) -> LyricsView | None:
        with self._uow() as uow:
            return uow.lyrics.get(song_id)

    def set_lyrics(self, song_id: str, content: str, fmt: str = "text",
                   language: str | None = None, source: str = "manual") -> None:
        with self._uow() as uow:
            uow.lyrics.upsert(song_id, content, fmt, language, source)
            uow.commit()

    # --- histórico ---
    def list_history(self, limit: int = 100) -> list[HistoryEntryView]:
        with self._uow() as uow:
            return uow.history.recent(limit)

    # --- manutenção / offline ---
    def mark_missing_media(self) -> int:
        with self._uow() as uow:
            missing = [mid for mid, path in uow.media.all_paths() if not os.path.exists(path)]
            if missing:
                uow.media.mark_missing(missing)
                uow.commit()
            return len(missing)

    # --- eventos ---
    def subscribe(self, event_name: str, handler: Handler) -> Subscription:
        return self._bus.subscribe(event_name, handler)

    def subscribe_all(self, handler: Handler) -> Subscription:
        return self._bus.subscribe_all(handler)
