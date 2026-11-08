"""Mapeadores domínio -> DTOs de leitura (CQRS leve)."""
from __future__ import annotations

from kk_shared.contracts.dtos import MediaFileView, SongRowView, SongView

from ..domain.catalog.entities import Song, SongRow


def _format_label(container: str | None, resolution: str | None) -> str | None:
    """Rótulo de formato/qualidade da 1ª versão, ex.: 'MP4 · 1080p'.
    container em CAIXA ALTA + altura da resolução ('1920x1080' -> '1080p')."""
    parts: list[str] = []
    if container:
        parts.append(container.upper())
    res = resolution or ""
    if "x" in res:
        try:
            parts.append(f"{int(res.split('x')[1])}p")
        except (ValueError, IndexError):
            parts.append(res)
    elif res:
        parts.append(res)
    return " · ".join(parts) or None


def to_song_row_view(row: SongRow) -> SongRowView:
    return SongRowView(
        id=row.id,
        title=row.title,
        artists=list(row.artists),
        language=row.language,
        category=row.category,
        format_label=_format_label(row.container, row.resolution),
        duration_s=row.duration_s,
        version_count=row.version_count,
    )


def to_song_view(song: Song) -> SongView:
    return SongView(
        id=song.id,
        title=song.title,
        artists=[a.name for a in song.artists],
        album=song.album,
        language=song.language,
        versions=[
            MediaFileView(
                id=m.id,
                channel=m.channel.name if m.channel else None,
                duration_s=m.duration.seconds,
                resolution=str(m.resolution) or None,
                container=m.container,
                status=m.status,
                path=m.path,
                source_url=m.source_url,
                source_title=m.source_title,
            )
            for m in song.media_files
        ],
    )
