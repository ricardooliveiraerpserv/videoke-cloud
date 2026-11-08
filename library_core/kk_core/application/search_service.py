"""Caso de uso: buscar músicas (o Karaokê chama isto). FTS5 + filtros."""
from __future__ import annotations

from kk_shared.contracts.dtos import Page, PageReq, SearchFilters, SongView

from .mappers import to_song_view


class SearchSongsUseCase:
    def execute(
        self, uow, query: str, filters: SearchFilters | None, page: PageReq | None
    ) -> Page[SongView]:
        filters = filters or SearchFilters()
        page = page or PageReq()

        ids = uow.search.search(query, page.limit, page.after,
                                filters.artist_id, filters.category_ids)
        # 1 query em lote (evita o N+1 de um get() por id) e reordena p/ a ordem do FTS
        by_id = {s.id: s for s in uow.songs.get_many(ids)}
        views: list[SongView] = []
        for sid in ids:
            song = by_id.get(sid)
            if not song:
                continue
            if filters.language and (song.language or "") != filters.language:
                continue
            if filters.only_playable and song.best_version() is None:
                continue
            views.append(to_song_view(song))

        offset = int(page.after) if (page.after and page.after.isdigit()) else 0
        next_cursor = str(offset + page.limit) if len(ids) == page.limit else None
        return Page[SongView](
            items=views, next_cursor=next_cursor,
            total_estimate=uow.search.count(query, filters.artist_id, filters.category_ids),
        )
