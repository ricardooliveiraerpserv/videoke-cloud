"""Implementações SQLAlchemy dos ports de repositório (mapeiam ORM ↔ domínio)."""
from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from kk_shared.contracts.enums import MediaStatus
from kk_shared.platform.text import normalize, song_key as _song_key

from ...domain.catalog.entities import Artist, Channel, MediaFile, Song, SongRow


def _display(text: str) -> str:
    """Grafia de exibição do acervo: CAIXA ALTA e '&' vira 'E'. Aplicado em TODA
    escrita de título/artista (import, edição, extração) — o acervo fica sempre
    padronizado, inclusive downloads futuros."""
    import re
    t = re.sub(r"\s*&\s*", " E ", text or "")
    return re.sub(r"\s+", " ", t).strip().upper()
from ...domain.value_objects import Duration, Resolution
from ..db.models import (
    ArtistCategoryLinkModel,
    ArtistCategoryModel,
    ArtistModel,
    BlacklistModel,
    ChannelModel,
    MediaFileModel,
    PresetModel,
    SongArtistModel,
    SongModel,
)


# ---- mappers ORM -> domínio ----
def _media_to_domain(m: MediaFileModel) -> MediaFile:
    ch = Channel(id=m.channel.id, name=m.channel.name, external_id=m.channel.external_id) if m.channel else None
    return MediaFile(
        id=m.id, song_id=m.song_id, channel=ch, path=m.path,
        container=m.container, video_codec=m.video_codec, audio_codec=m.audio_codec,
        duration=Duration(m.duration_s or 0), resolution=Resolution.parse(m.resolution),
        sha256=m.sha256, status=MediaStatus(m.status), source_url=m.source_url,
        source_title=m.source_title,
    )


def _song_to_domain(s: SongModel) -> Song:
    return Song(
        id=s.id, title=s.title, album=s.album, year=s.year, language=s.language,
        artists=[Artist(id=sa.artist.id, name=sa.artist.name) for sa in s.artists],
        media_files=[_media_to_domain(m) for m in s.media_files if m.deleted_at is None],
    )


class SqlSongRepository:
    def __init__(self, session: Session):
        self.s = session

    def get(self, song_id: str) -> Song | None:
        m = self.s.get(SongModel, song_id)
        return _song_to_domain(m) if m and m.deleted_at is None else None

    def get_many(self, ids: list[str]) -> list[Song]:
        """Carrega VÁRIAS músicas vivas de uma vez (mesmos loads do get), sem N+1.
        A ordem do retorno NÃO é garantida — quem chama reordena se precisar."""
        if not ids:
            return []
        rows = self.s.scalars(
            select(SongModel).where(SongModel.id.in_(list(ids)), SongModel.deleted_at.is_(None))
        ).all()
        return [_song_to_domain(m) for m in rows]

    def by_song_key(self, key: str) -> Song | None:
        m = self.s.scalars(
            select(SongModel).where(SongModel.song_key == key, SongModel.deleted_at.is_(None))
        ).first()
        return _song_to_domain(m) if m else None

    def add(self, song: Song) -> None:
        model = SongModel(
            id=song.id, title=_display(song.title), title_norm=normalize(song.title),
            song_key=song.song_key(), album=song.album, year=song.year, language=song.language,
        )
        self.s.add(model)
        self.s.flush()  # garante songs.id antes das FKs de song_artists/media_files
        for art in song.artists:
            self.s.add(SongArtistModel(song_id=song.id, artist_id=art.id, role="main"))
        for mf in song.media_files:
            self.s.add(_media_to_model(mf))

    def update(self, song: Song) -> None:
        # Fase 0: usado só para anexar versões novas (via media repo). Sem-op aqui.
        pass

    def set_album(self, song_id: str, album_id: str) -> None:
        m = self.s.get(SongModel, song_id)
        if m:
            m.album_id = album_id

    def retitle(self, song_id: str, title: str, artists: list[Artist]) -> None:
        """Atualiza título + artistas de uma música existente (re-catalogação)."""
        m = self.s.get(SongModel, song_id)
        if not m:
            return
        m.title = _display(title)
        m.title_norm = normalize(title)
        m.song_key = _song_key(title, [a.name for a in artists])
        self.s.execute(delete(SongArtistModel).where(SongArtistModel.song_id == song_id))
        for a in artists:
            self.s.add(SongArtistModel(song_id=song_id, artist_id=a.id, role="main"))

    def list_deleted(self, limit: int = 500) -> list[Song]:
        """Músicas na lixeira (soft-deleted), mais recentes primeiro."""
        stmt = (select(SongModel).where(SongModel.deleted_at.is_not(None))
                .order_by(SongModel.deleted_at.desc()).limit(limit))
        return [_song_to_domain(m) for m in self.s.scalars(stmt).all()]

    def restore(self, song_id: str) -> list[str]:
        """Desfaz o soft-delete da música e de suas versões; retorna os sha256 restaurados."""
        m = self.s.get(SongModel, song_id)
        if not m:
            return []
        m.deleted_at = None
        hashes: list[str] = []
        for mf in m.media_files:
            if mf.deleted_at is not None:
                mf.deleted_at = None
            if mf.sha256:
                hashes.append(mf.sha256)
        return hashes

    def soft_delete(self, song_id: str) -> list[str]:
        """Marca a música e seus arquivos como excluídos; retorna os sha256 dos arquivos."""
        m = self.s.get(SongModel, song_id)
        if not m:
            return []
        hashes: list[str] = []
        for mf in m.media_files:
            if mf.deleted_at is None:
                mf.deleted_at = func.now()
            if mf.sha256:
                hashes.append(mf.sha256)
        m.deleted_at = func.now()
        return hashes

    def explode_versions(self) -> list[str]:
        """Desfaz o merge: cada versão extra de uma música vira uma MÚSICA própria
        (curadoria manual). Retorna os ids das novas músicas (p/ indexar no FTS)."""
        rows = self.s.execute(
            select(MediaFileModel.song_id)
            .where(MediaFileModel.deleted_at.is_(None))
            .group_by(MediaFileModel.song_id)
            .having(func.count(MediaFileModel.id) > 1)
        ).all()
        created: list[str] = []
        for (song_id,) in rows:
            song = self.s.get(SongModel, song_id)
            if not song or song.deleted_at is not None:
                continue
            media = [m for m in song.media_files if m.deleted_at is None]
            for extra in media[1:]:      # a 1ª versão fica; as demais viram músicas próprias
                new = SongModel(
                    title=song.title, title_norm=song.title_norm, song_key=song.song_key,
                    album=song.album, year=song.year, language=song.language,
                )
                self.s.add(new); self.s.flush()
                for sa in song.artists:
                    self.s.add(SongArtistModel(song_id=new.id, artist_id=sa.artist_id, role=sa.role))
                extra.song_id = new.id
                created.append(new.id)
        return created

    def count(self) -> int:
        return int(self.s.scalar(
            select(func.count()).select_from(SongModel).where(SongModel.deleted_at.is_(None))
        ) or 0)

    def duplicate_groups(self) -> list[list[str]]:
        """Grupos de músicas com o MESMO song_key (título+artista), tamanho > 1."""
        keys = self.s.execute(
            select(SongModel.song_key).where(SongModel.deleted_at.is_(None))
            .group_by(SongModel.song_key).having(func.count(SongModel.id) > 1)
        ).all()
        groups: list[list[str]] = []
        for (k,) in keys:
            ids = [r[0] for r in self.s.execute(
                select(SongModel.id).where(SongModel.song_key == k, SongModel.deleted_at.is_(None))
                .order_by(SongModel.created_at.asc())
            ).all()]
            groups.append(ids)
        return groups

    def merge_into(self, keep_id: str, drop_ids: list[str]) -> None:
        """Move as versões das músicas `drop_ids` para `keep_id` e soft-deleta as drops."""
        drop_ids = [d for d in drop_ids if d and d != keep_id]
        if not drop_ids:
            return
        self.s.execute(update(MediaFileModel).where(MediaFileModel.song_id.in_(drop_ids)).values(song_id=keep_id))
        for d in drop_ids:
            m = self.s.get(SongModel, d)
            if m:
                m.deleted_at = func.now()
        self.s.flush()

    def merge_duplicates(self) -> list[str]:
        """Funde músicas com o MESMO song_key: move as versões p/ uma só e
        soft-deleta as demais. Retorna os ids removidos (p/ tirar do FTS)."""
        groups = self.s.execute(
            select(SongModel.song_key)
            .where(SongModel.deleted_at.is_(None))
            .group_by(SongModel.song_key)
            .having(func.count(SongModel.id) > 1)
        ).all()
        removed: list[str] = []
        for (key,) in groups:
            ids = [r[0] for r in self.s.execute(
                select(SongModel.id)
                .where(SongModel.song_key == key, SongModel.deleted_at.is_(None))
                .order_by(SongModel.created_at.asc())
            ).all()]
            keep, drops = ids[0], ids[1:]
            # move todas as versões (arquivos) das duplicatas para a música mantida
            self.s.execute(
                update(MediaFileModel).where(MediaFileModel.song_id.in_(drops)).values(song_id=keep)
            )
            for d in drops:
                m = self.s.get(SongModel, d)
                if m:
                    m.deleted_at = func.now()
            removed.extend(drops)
        return removed

    @staticmethod
    def _artist_order_subquery():
        """Menor name_norm dos artistas da música — para ordenar por artista."""
        return (
            select(func.min(ArtistModel.name_norm))
            .select_from(SongArtistModel)
            .join(ArtistModel, ArtistModel.id == SongArtistModel.artist_id)
            .where(SongArtistModel.song_id == SongModel.id)
            .correlate(SongModel).scalar_subquery()
        )

    def browse(self, limit: int, offset: int) -> list[Song]:
        """Todas as músicas ordenadas por ARTISTA e depois pelo TÍTULO."""
        art_sub = self._artist_order_subquery()
        stmt = (
            select(SongModel)
            .where(SongModel.deleted_at.is_(None))
            .order_by(func.coalesce(art_sub, "~").asc(), SongModel.title_norm.asc())
            .limit(limit).offset(offset)
        )
        return [_song_to_domain(m) for m in self.s.scalars(stmt).all()]

    def browse_rows(self, limit: int, offset: int) -> list[SongRow]:
        """Projeção LEVE da página: um SELECT ordenado/paginado pega id/título/idioma
        (+ ordem por artista) e, em seguida, três consultas EM LOTE (chaveadas pelos
        ids da página) trazem artistas, categoria e mídia viva. Custo constante por
        página (4 queries), sem carregar o grafo `selectin` de versões — que é o que
        deixava a lista pesada."""
        art_sub = self._artist_order_subquery()
        base = self.s.execute(
            select(SongModel.id, SongModel.title, SongModel.language)
            .where(SongModel.deleted_at.is_(None))
            .order_by(func.coalesce(art_sub, "~").asc(), SongModel.title_norm.asc())
            .limit(limit).offset(offset)
        ).all()
        ids = [r[0] for r in base]
        if not ids:
            return []

        # artistas (nome + name_norm p/ ordenação estável) por música — em lote
        artists_by_song: dict[str, list[tuple[str, str]]] = {}
        for sid, name, norm in self.s.execute(
            select(SongArtistModel.song_id, ArtistModel.name, ArtistModel.name_norm)
            .join(ArtistModel, ArtistModel.id == SongArtistModel.artist_id)
            .where(SongArtistModel.song_id.in_(ids))
        ).all():
            artists_by_song.setdefault(sid, []).append((name, norm or ""))

        # categoria (uma por artista → a 1ª encontrada da música) — em lote
        cat_by_song: dict[str, str] = {}
        for sid, cname in self.s.execute(
            select(SongArtistModel.song_id, ArtistCategoryModel.name)
            .join(ArtistCategoryLinkModel,
                  ArtistCategoryLinkModel.artist_id == SongArtistModel.artist_id)
            .join(ArtistCategoryModel,
                  ArtistCategoryModel.id == ArtistCategoryLinkModel.category_id)
            .where(SongArtistModel.song_id.in_(ids))
        ).all():
            cat_by_song.setdefault(sid, cname)

        # mídia VIVA por música (ordem de criação = ordem das versões) — em lote
        media_by_song: dict[str, list[tuple[str | None, str | None, int]]] = {}
        for sid, container, resolution, dur in self.s.execute(
            select(MediaFileModel.song_id, MediaFileModel.container,
                   MediaFileModel.resolution, MediaFileModel.duration_s)
            .where(MediaFileModel.song_id.in_(ids), MediaFileModel.deleted_at.is_(None))
            .order_by(MediaFileModel.song_id, MediaFileModel.created_at.asc(),
                      MediaFileModel.id.asc())
        ).all():
            media_by_song.setdefault(sid, []).append((container, resolution, int(dur or 0)))

        rows: list[SongRow] = []
        for sid, title, language in base:
            arts = [n for n, _norm in sorted(artists_by_song.get(sid, []), key=lambda x: x[1])]
            media = media_by_song.get(sid, [])
            # formato = 1ª versão com container/resolução; duração = 1ª com duração > 0
            fmt = next(((c, r) for (c, r, _d) in media if c or r), (None, None))
            secs = next((d for (_c, _r, d) in media if d), 0)
            rows.append(SongRow(
                id=sid, title=title, language=language,
                artists=arts, category=cat_by_song.get(sid),
                container=fmt[0], resolution=fmt[1],
                duration_s=secs, version_count=len(media),
            ))
        return rows

    def browse_by_category(self, category_id: str, limit: int, offset: int) -> list[Song]:
        return self.browse_by_categories([category_id], limit, offset)

    def browse_by_categories(self, category_ids: list[str], limit: int, offset: int) -> list[Song]:
        """Músicas cujo artista pertence a QUALQUER das categorias dadas (união),
        ordenado por artista e depois título."""
        if not category_ids:
            return []
        art_ids = select(ArtistCategoryLinkModel.artist_id).where(
            ArtistCategoryLinkModel.category_id.in_(list(category_ids)))
        song_ids = select(SongArtistModel.song_id).where(
            SongArtistModel.artist_id.in_(art_ids))
        art_sub = self._artist_order_subquery()
        stmt = (
            select(SongModel)
            .where(SongModel.deleted_at.is_(None), SongModel.id.in_(song_ids))
            .order_by(func.coalesce(art_sub, "~").asc(), SongModel.title_norm.asc())
            .limit(limit).offset(offset)
        )
        return [_song_to_domain(m) for m in self.s.scalars(stmt).all()]

    def browse_by_artist(self, artist_id: str, limit: int, offset: int) -> list[Song]:
        """Músicas vinculadas a UM artista (filtro por cantor), ordenado por título."""
        if not artist_id:
            return []
        song_ids = select(SongArtistModel.song_id).where(
            SongArtistModel.artist_id == artist_id)
        stmt = (
            select(SongModel)
            .where(SongModel.deleted_at.is_(None), SongModel.id.in_(song_ids))
            .order_by(SongModel.title_norm.asc())
            .limit(limit).offset(offset)
        )
        return [_song_to_domain(m) for m in self.s.scalars(stmt).all()]

    def without_artist(self, limit: int = 5000) -> list[Song]:
        """Músicas vivas SEM nenhum artista vinculado (para vínculo em massa)."""
        with_artist = select(SongArtistModel.song_id).distinct()
        stmt = (
            select(SongModel)
            .where(SongModel.deleted_at.is_(None), SongModel.id.not_in(with_artist))
            .order_by(SongModel.title_norm.asc()).limit(limit)
        )
        return [_song_to_domain(m) for m in self.s.scalars(stmt).all()]


def _media_to_model(mf: MediaFile) -> MediaFileModel:
    return MediaFileModel(
        id=mf.id, song_id=mf.song_id,
        channel_id=mf.channel.id if mf.channel else None,
        path=mf.path, container=mf.container, video_codec=mf.video_codec,
        audio_codec=mf.audio_codec, duration_s=mf.duration.seconds,
        resolution=str(mf.resolution) or None, sha256=mf.sha256,
        status=mf.status.value, source_url=mf.source_url, source_title=mf.source_title,
    )


class SqlMediaRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, media: MediaFile) -> None:
        self.s.add(_media_to_model(media))

    def url_exists(self, source_url: str) -> bool:
        if not source_url:
            return False
        return self.s.scalar(
            select(func.count()).select_from(MediaFileModel).where(
                MediaFileModel.source_url == source_url, MediaFileModel.deleted_at.is_(None))
        ) > 0

    def existing_urls(self, urls: list[str]) -> list[str]:
        """Quais das URLs dadas já existem no acervo (mídia viva)."""
        if not urls:
            return []
        rows = self.s.execute(
            select(MediaFileModel.source_url).where(
                MediaFileModel.source_url.in_(urls), MediaFileModel.deleted_at.is_(None))
        ).all()
        return [r[0] for r in rows]

    def by_hash(self, sha256: str) -> MediaFile | None:
        if not sha256:
            return None
        m = self.s.scalars(
            select(MediaFileModel).where(MediaFileModel.sha256 == sha256, MediaFileModel.deleted_at.is_(None))
        ).first()
        return _media_to_domain(m) if m else None

    def mark_missing(self, ids: list[str]) -> None:
        for mid in ids:
            m = self.s.get(MediaFileModel, mid)
            if m:
                m.status = MediaStatus.MISSING.value

    def path_of(self, media_file_id: str) -> str | None:
        m = self.s.get(MediaFileModel, media_file_id)
        return m.path if m and m.deleted_at is None else None

    def get(self, media_file_id: str) -> MediaFile | None:
        m = self.s.get(MediaFileModel, media_file_id)
        return _media_to_domain(m) if m and m.deleted_at is None else None

    def soft_delete(self, media_file_id: str) -> None:
        m = self.s.get(MediaFileModel, media_file_id)
        if m and m.deleted_at is None:
            m.deleted_at = func.now()
        self.s.flush()

    def all_paths(self) -> list[tuple[str, str]]:
        rows = self.s.execute(
            select(MediaFileModel.id, MediaFileModel.path)
            .where(MediaFileModel.status == MediaStatus.OK.value, MediaFileModel.deleted_at.is_(None))
        ).all()
        return [(r[0], r[1]) for r in rows]


class SqlBlacklistRepository:
    """Lista negra de arquivos (por sha256): não voltam na importação."""
    def __init__(self, session: Session):
        self.s = session

    def add(self, sha256: str, title: str | None = None, artist: str | None = None,
            reason: str = "user", source_url: str | None = None) -> None:
        if not sha256:
            return
        exists = self.s.scalars(
            select(BlacklistModel).where(BlacklistModel.sha256 == sha256)
        ).first()
        if exists:
            if source_url and not exists.source_url:
                exists.source_url = source_url
        else:
            self.s.add(BlacklistModel(sha256=sha256, title=title, artist=artist,
                                      reason=reason, source_url=source_url or None))

    def contains(self, sha256: str | None) -> bool:
        if not sha256:
            return False
        return self.s.scalar(
            select(func.count()).select_from(BlacklistModel).where(BlacklistModel.sha256 == sha256)
        ) > 0

    def contains_url(self, source_url: str | None) -> bool:
        if not source_url:
            return False
        return self.s.scalar(
            select(func.count()).select_from(BlacklistModel).where(BlacklistModel.source_url == source_url)
        ) > 0

    def remove_url(self, source_url: str) -> None:
        if source_url:
            self.s.execute(delete(BlacklistModel).where(BlacklistModel.source_url == source_url))

    def remove(self, sha256: str) -> None:
        if sha256:
            self.s.execute(delete(BlacklistModel).where(BlacklistModel.sha256 == sha256))

    def count(self) -> int:
        return int(self.s.scalar(select(func.count()).select_from(BlacklistModel)) or 0)


class SqlArtistRepository:
    def __init__(self, session: Session):
        self.s = session

    def get_or_create(self, name: str) -> Artist:
        norm = normalize(name)
        m = self.s.scalars(select(ArtistModel).where(ArtistModel.name_norm == norm)).first()
        if not m:
            m = ArtistModel(name=_display(name), name_norm=norm)
            self.s.add(m)
            self.s.flush()
        return Artist(id=m.id, name=m.name)

    def _by_norm(self, norm: str) -> ArtistModel | None:
        return self.s.scalars(select(ArtistModel).where(ArtistModel.name_norm == norm)).first()

    def resolve_or_create(self, name: str, extra_pool: list[str] | None = None) -> Artist:
        """Como get_or_create, mas ANTES de criar um artista novo tenta casá-lo
        com um já existente quase idêntico (acento/typo) — evita poluir o cadastro
        com variantes ('Allan e Aladim' vs 'Alan e Aladim'). Conservador: só funde
        nomes com o MESMO número de palavras (nunca 'Daniel' → 'João Paulo e Daniel').

        `extra_pool` (dicionário de conhecidos) fornece a grafia canônica quando o
        nome novo é uma variante de um artista famoso ainda não cadastrado."""
        from kk_shared.platform.known_artists import canonical_artist
        from kk_shared.platform.naming import best_match

        name = canonical_artist(name)                     # apelido conhecido → oficial
        norm = normalize(name)
        m = self._by_norm(norm)
        if m:
            return Artist(id=m.id, name=m.name)

        reg_names = [r[0] for r in self.s.execute(select(ArtistModel.name)).all()]
        hit = best_match(name, reg_names)                 # variante de um já cadastrado?
        if hit:
            m = self._by_norm(normalize(hit))
            if m:
                return Artist(id=m.id, name=m.name)

        if extra_pool:                                    # variante de um conhecido → grafia oficial
            pool_hit = best_match(name, extra_pool)
            if pool_hit and normalize(pool_hit) != norm:
                name, norm = pool_hit, normalize(pool_hit)
                m = self._by_norm(norm)
                if m:
                    return Artist(id=m.id, name=m.name)

        m = ArtistModel(name=_display(name), name_norm=norm)
        self.s.add(m); self.s.flush()
        return Artist(id=m.id, name=m.name)

    def all_names(self) -> list[str]:
        return [r[0] for r in self.s.execute(select(ArtistModel.name)).all()]

    def list_with_counts(self) -> list[tuple[str, str, int]]:
        """(id, nome, nº de músicas vivas) — ordenado por nome."""
        cnt = (
            select(SongArtistModel.artist_id, func.count(SongModel.id).label("n"))
            .join(SongModel, (SongModel.id == SongArtistModel.song_id) & SongModel.deleted_at.is_(None))
            .group_by(SongArtistModel.artist_id).subquery()
        )
        rows = self.s.execute(
            select(ArtistModel.id, ArtistModel.name, func.coalesce(cnt.c.n, 0))
            .outerjoin(cnt, cnt.c.artist_id == ArtistModel.id)
            .order_by(ArtistModel.name_norm)
        ).all()
        return [(r[0], r[1], int(r[2])) for r in rows]

    def song_ids(self, artist_id: str) -> list[str]:
        return [r[0] for r in self.s.execute(
            select(SongArtistModel.song_id).where(SongArtistModel.artist_id == artist_id)
        ).all()]

    def rename(self, artist_id: str, name: str) -> None:
        m = self.s.get(ArtistModel, artist_id)
        if m:
            m.name = _display(name)
            m.name_norm = normalize(name)
            self.s.flush()

    def delete(self, artist_id: str) -> None:
        self.s.execute(delete(SongArtistModel).where(SongArtistModel.artist_id == artist_id))
        self.s.execute(delete(ArtistModel).where(ArtistModel.id == artist_id))
        self.s.flush()

    def delete_orphans(self) -> int:
        """Apaga artistas sem NENHUMA música viva (limpeza automática)."""
        with_songs = (
            select(SongArtistModel.artist_id)
            .join(SongModel, (SongModel.id == SongArtistModel.song_id) & SongModel.deleted_at.is_(None))
            .distinct()
        )
        orphan_ids = [r[0] for r in self.s.execute(
            select(ArtistModel.id).where(ArtistModel.id.not_in(with_songs))
        ).all()]
        if orphan_ids:
            self.s.execute(delete(SongArtistModel).where(SongArtistModel.artist_id.in_(orphan_ids)))
            self.s.execute(delete(ArtistModel).where(ArtistModel.id.in_(orphan_ids)))
            self.s.flush()
        return len(orphan_ids)

    def merge(self, from_id: str, into_id: str) -> None:
        """Move as músicas do artista `from` para `into` e remove o `from`."""
        if from_id == into_id:
            return
        links = self.s.scalars(
            select(SongArtistModel).where(SongArtistModel.artist_id == from_id)
        ).all()
        for link in links:
            dup = self.s.scalar(
                select(func.count()).select_from(SongArtistModel).where(
                    SongArtistModel.song_id == link.song_id, SongArtistModel.artist_id == into_id)
            )
            if dup:
                self.s.delete(link)          # já tem o destino → descarta o link duplicado
            else:
                link.artist_id = into_id
        self.s.flush()
        self.s.execute(delete(ArtistModel).where(ArtistModel.id == from_id))
        self.s.flush()


class SqlChannelRepository:
    def __init__(self, session: Session):
        self.s = session

    def get_or_create(self, name: str, external_id: str | None = None) -> Channel:
        stmt = select(ChannelModel)
        if external_id:
            stmt = stmt.where(ChannelModel.external_id == external_id)
        else:
            stmt = stmt.where(ChannelModel.name == name)
        m = self.s.scalars(stmt).first()
        if not m:
            m = ChannelModel(name=name, external_id=external_id)
            self.s.add(m)
            self.s.flush()
        return Channel(id=m.id, name=m.name, external_id=m.external_id)


class SqlPresetRepository:
    def __init__(self, session: Session):
        self.s = session

    def get(self, song_id: str, user_id: str | None) -> tuple[int, int] | None:
        m = self.s.scalars(
            select(PresetModel).where(PresetModel.song_id == song_id, PresetModel.user_id.is_(user_id))
        ).first()
        return (m.pitch, m.tempo) if m else None

    def save(self, song_id: str, pitch: int, tempo: int, user_id: str | None) -> None:
        m = self.s.scalars(
            select(PresetModel).where(PresetModel.song_id == song_id, PresetModel.user_id.is_(user_id))
        ).first()
        if m:
            m.pitch, m.tempo = pitch, tempo
        else:
            self.s.add(PresetModel(song_id=song_id, user_id=user_id, pitch=pitch, tempo=tempo))
