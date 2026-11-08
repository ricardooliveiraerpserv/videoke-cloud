"""Repositórios de álbuns, gêneros, categorias, downloads e thumbnails."""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from kk_shared.platform.text import normalize

from ..db.models import (
    AlbumModel,
    ArtistCategoryLinkModel,
    ArtistCategoryModel,
    CategoryModel,
    DownloadModel,
    GenreModel,
    SongArtistModel,
    SongModel,
    SongCategoryModel,
    SongGenreModel,
    ThumbnailModel,
)


class AlbumRepository:
    def __init__(self, s: Session):
        self.s = s

    def get_or_create(self, name: str, year: int | None = None) -> str:
        norm = normalize(name)
        m = self.s.scalars(select(AlbumModel).where(AlbumModel.name_norm == norm)).first()
        if not m:
            m = AlbumModel(name=name, name_norm=norm, year=year)
            self.s.add(m); self.s.flush()
        return m.id


class TagRepository:
    """Gêneros e categorias (mesmo padrão N:N)."""

    def __init__(self, s: Session):
        self.s = s

    def _get_or_create(self, model, name: str) -> str:
        norm = normalize(name)
        m = self.s.scalars(select(model).where(model.name_norm == norm)).first()
        if not m:
            m = model(name=name, name_norm=norm)
            self.s.add(m); self.s.flush()
        return m.id

    def link_genres(self, song_id: str, names: list[str]) -> None:
        for n in filter(None, (x.strip() for x in names)):
            gid = self._get_or_create(GenreModel, n)
            self.s.merge(SongGenreModel(song_id=song_id, genre_id=gid))

    def link_categories(self, song_id: str, names: list[str]) -> None:
        for n in filter(None, (x.strip() for x in names)):
            cid = self._get_or_create(CategoryModel, n)
            self.s.merge(SongCategoryModel(song_id=song_id, category_id=cid))


class DownloadRecordRepository:
    def __init__(self, s: Session):
        self.s = s

    def record(self, *, url: str, title: str, kind: str, media_file_id: str) -> None:
        self.s.add(DownloadModel(url=url, title=title, kind=kind,
                                 status="done", media_file_id=media_file_id))


class ThumbnailRepository:
    def __init__(self, s: Session):
        self.s = s

    def add(self, media_file_id: str, path: str) -> None:
        self.s.add(ThumbnailModel(media_file_id=media_file_id, path=path))


class ArtistCategoryRepository:
    """Estilos/categorias de artista (Sertanejo, Samba, Rock…). Registro único;
    cada artista tem no máximo UMA categoria (PK do link é o artista)."""

    def __init__(self, s: Session):
        self.s = s

    def get_or_create(self, name: str) -> str:
        norm = normalize(name)
        m = self.s.scalars(
            select(ArtistCategoryModel).where(ArtistCategoryModel.name_norm == norm)).first()
        if not m:
            m = ArtistCategoryModel(name=name.strip(), name_norm=norm)
            self.s.add(m); self.s.flush()
        return m.id

    def rename(self, category_id: str, name: str) -> None:
        m = self.s.get(ArtistCategoryModel, category_id)
        if m:
            m.name = name.strip()
            m.name_norm = normalize(name)
            self.s.flush()

    def delete(self, category_id: str) -> None:
        self.s.execute(delete(ArtistCategoryLinkModel).where(
            ArtistCategoryLinkModel.category_id == category_id))
        self.s.execute(delete(ArtistCategoryModel).where(
            ArtistCategoryModel.id == category_id))
        self.s.flush()

    def set_for_artist(self, artist_id: str, category_id: str | None) -> None:
        """Define (ou limpa, se None) a categoria de um artista."""
        self.s.execute(delete(ArtistCategoryLinkModel).where(
            ArtistCategoryLinkModel.artist_id == artist_id))
        if category_id:
            self.s.add(ArtistCategoryLinkModel(artist_id=artist_id, category_id=category_id))
        self.s.flush()

    def set_for_artists(self, artist_ids: list[str], category_id: str | None) -> int:
        for aid in artist_ids:
            self.set_for_artist(aid, category_id)
        return len(artist_ids)

    def category_of(self, artist_id: str) -> tuple[str, str] | None:
        row = self.s.execute(
            select(ArtistCategoryModel.id, ArtistCategoryModel.name)
            .join(ArtistCategoryLinkModel,
                  ArtistCategoryLinkModel.category_id == ArtistCategoryModel.id)
            .where(ArtistCategoryLinkModel.artist_id == artist_id)
        ).first()
        return (row[0], row[1]) if row else None

    def map_for_artists(self) -> dict[str, tuple[str, str]]:
        """artist_id → (category_id, category_name) para todos os vínculos."""
        rows = self.s.execute(
            select(ArtistCategoryLinkModel.artist_id,
                   ArtistCategoryModel.id, ArtistCategoryModel.name)
            .join(ArtistCategoryModel,
                  ArtistCategoryModel.id == ArtistCategoryLinkModel.category_id)
        ).all()
        return {r[0]: (r[1], r[2]) for r in rows}

    def list_with_counts(self) -> list[tuple[str, str, int, int]]:
        """(id, nome, nº de artistas, nº de músicas vivas) — ordenado por nome."""
        artist_cnt = (
            select(ArtistCategoryLinkModel.category_id,
                   func.count(ArtistCategoryLinkModel.artist_id).label("na"))
            .group_by(ArtistCategoryLinkModel.category_id).subquery()
        )
        song_cnt = (
            select(ArtistCategoryLinkModel.category_id,
                   func.count(func.distinct(SongModel.id)).label("ns"))
            .join(SongArtistModel,
                  SongArtistModel.artist_id == ArtistCategoryLinkModel.artist_id)
            .join(SongModel, (SongModel.id == SongArtistModel.song_id)
                  & SongModel.deleted_at.is_(None))
            .group_by(ArtistCategoryLinkModel.category_id).subquery()
        )
        rows = self.s.execute(
            select(ArtistCategoryModel.id, ArtistCategoryModel.name,
                   func.coalesce(artist_cnt.c.na, 0), func.coalesce(song_cnt.c.ns, 0))
            .outerjoin(artist_cnt, artist_cnt.c.category_id == ArtistCategoryModel.id)
            .outerjoin(song_cnt, song_cnt.c.category_id == ArtistCategoryModel.id)
            .order_by(ArtistCategoryModel.name_norm)
        ).all()
        return [(r[0], r[1], int(r[2]), int(r[3])) for r in rows]
