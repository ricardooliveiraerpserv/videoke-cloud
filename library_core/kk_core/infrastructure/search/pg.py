"""F1 — busca full-text no Postgres (equivalente ao FtsSearchIndex do SQLite).

Mesma interface (upsert/remove/search/count). Em vez de FTS5, mantém a tabela
comum `songs_search` e consulta por ILIKE token-a-token (AND), reaproveitando o
`_scope_clause` (portável) para escopar por cantor/categoria.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from kk_shared.platform.text import normalize

from .fts import _scope_clause   # SQL portável (subqueries em song_artists/links)


class PgSearchIndex:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, song_id: str, title_norm: str, artist_norm: str) -> None:
        self.session.execute(
            text(
                "INSERT INTO songs_search(song_id, title_norm, artist_norm) "
                "VALUES (:sid, :t, :a) "
                "ON CONFLICT (song_id) DO UPDATE SET "
                "title_norm = EXCLUDED.title_norm, artist_norm = EXCLUDED.artist_norm"
            ),
            {"sid": song_id, "t": title_norm, "a": artist_norm},
        )

    def remove(self, song_id: str) -> None:
        self.session.execute(text("DELETE FROM songs_search WHERE song_id = :sid"),
                             {"sid": song_id})

    def _where(self, query: str, params: dict) -> str | None:
        toks = [t for t in normalize(query).split() if t]
        if not toks:
            return None
        parts = []
        for i, t in enumerate(toks):
            k = f"t{i}"
            params[k] = f"%{t}%"
            parts.append(f"(title_norm ILIKE :{k} OR artist_norm ILIKE :{k})")
        return " AND ".join(parts)

    def search(self, query: str, limit: int, after: str | None,
               artist_id: str | None = None,
               category_ids: list[str] | None = None) -> list[str]:
        params: dict = {}
        where = self._where(query, params)
        if not where:
            return []
        offset = int(after) if (after and after.isdigit()) else 0
        params.update(lim=limit, off=offset)
        scope = _scope_clause(artist_id, category_ids, params)
        rows = self.session.execute(
            text(f"SELECT song_id FROM songs_search WHERE {where}{scope} "
                 "ORDER BY title_norm LIMIT :lim OFFSET :off"),
            params,
        ).all()
        return [r[0] for r in rows]

    def count(self, query: str, artist_id: str | None = None,
              category_ids: list[str] | None = None) -> int:
        params: dict = {}
        where = self._where(query, params)
        if not where:
            return 0
        scope = _scope_clause(artist_id, category_ids, params)
        row = self.session.execute(
            text(f"SELECT count(*) FROM songs_search WHERE {where}{scope}"), params
        ).one()
        return int(row[0])
