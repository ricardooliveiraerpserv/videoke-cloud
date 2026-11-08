"""Índice de busca full-text sobre SQLite FTS5 (seção 12).

Mantido explicitamente pelo repositório de músicas (upsert na escrita) — evita
triggers complexos para agregar artistas por música e mantém o controle no Core.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from kk_shared.platform.text import normalize


def _match_expr(query: str) -> str:
    """Converte texto livre em expressão FTS5 com prefixo por token (AND)."""
    toks = [t for t in normalize(query).split() if t]
    if not toks:
        return ""
    return " ".join(f'"{t}"*' for t in toks)


def _scope_clause(artist_id, category_ids, params: dict) -> str:
    """Monta ' AND …' que escopa a busca a um cantor e/ou a categorias (estilos),
    preenchendo `params`. Mantém a paginação correta (filtra no próprio SQL)."""
    clauses = []
    if artist_id:
        clauses.append("song_id IN (SELECT song_id FROM song_artists WHERE artist_id = :aid)")
        params["aid"] = artist_id
    if category_ids:
        ph = []
        for i, cid in enumerate(category_ids):
            key = f"cat{i}"; params[key] = cid; ph.append(f":{key}")
        clauses.append(
            "song_id IN (SELECT song_id FROM song_artists WHERE artist_id IN "
            "(SELECT artist_id FROM artist_category_links WHERE category_id IN "
            f"({','.join(ph)})))")
    return "".join(f" AND {c}" for c in clauses)


class FtsSearchIndex:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, song_id: str, title_norm: str, artist_norm: str) -> None:
        self.session.execute(text("DELETE FROM songs_fts WHERE song_id = :sid"), {"sid": song_id})
        self.session.execute(
            text(
                "INSERT INTO songs_fts(song_id, title_norm, artist_norm) "
                "VALUES (:sid, :t, :a)"
            ),
            {"sid": song_id, "t": title_norm, "a": artist_norm},
        )

    def remove(self, song_id: str) -> None:
        self.session.execute(text("DELETE FROM songs_fts WHERE song_id = :sid"), {"sid": song_id})

    def search(self, query: str, limit: int, after: str | None,
               artist_id: str | None = None,
               category_ids: list[str] | None = None) -> list[str]:
        expr = _match_expr(query)
        if not expr:
            return []
        offset = int(after) if (after and after.isdigit()) else 0
        params = {"q": expr, "lim": limit, "off": offset}
        scope = _scope_clause(artist_id, category_ids, params)
        rows = self.session.execute(
            text(
                f"SELECT song_id FROM songs_fts WHERE songs_fts MATCH :q{scope} "
                "ORDER BY rank LIMIT :lim OFFSET :off"
            ),
            params,
        ).all()
        return [r[0] for r in rows]

    def count(self, query: str, artist_id: str | None = None,
              category_ids: list[str] | None = None) -> int:
        expr = _match_expr(query)
        if not expr:
            return 0
        params = {"q": expr}
        scope = _scope_clause(artist_id, category_ids, params)
        row = self.session.execute(
            text(f"SELECT count(*) FROM songs_fts WHERE songs_fts MATCH :q{scope}"), params
        ).one()
        return int(row[0])
