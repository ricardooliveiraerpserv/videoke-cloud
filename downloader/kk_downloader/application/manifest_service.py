"""Manifesto de download: um CSV (url, artista, musica, categoria) é a FONTE DA VERDADE.

Fluxo: gerar a partir de uma playlist/canal (o parser PROPÕE artista/música) → você
revisa/corrige no Excel → aplicar: baixa e cataloga cada linha com o artista/música/
categoria EXATOS (curados, sem passar pela quarentena)."""
from __future__ import annotations

import csv
from dataclasses import dataclass

from kk_shared.contracts.dtos import PageReq

from ..infrastructure.metadata_parser import parse as parse_meta

FIELDS = ["url", "artista", "musica", "categoria"]


@dataclass
class ManifestRow:
    url: str
    artista: str
    musica: str
    categoria: str


def generate_rows(backend, source: str, *, categoria: str = "",
                  limit: int | None = None, cookies: str = "") -> list[ManifestRow]:
    """Lista a playlist/canal e PROPÕE artista/música pelo parser (você corrige depois)."""
    rows: list[ManifestRow] = []
    for url, title in backend.playlist_entries(source, cookies=cookies, limit=limit):
        song, arts = parse_meta(title)
        rows.append(ManifestRow(url=url, artista=(arts[0] if arts else ""),
                                musica=song, categoria=categoria))
    return rows


def export_library(lib) -> list[ManifestRow]:
    """Exporta o ACERVO ATUAL como manifesto: uma linha por música (url, artista, música,
    categoria) — a curadoria pra outra máquina REBAIXAR idêntico, sem copiar mídia.
    Só músicas com source_url (dá pra rebaixar). Categoria = estilo do artista."""
    art_cat = {a.name.strip().lower(): (a.category or "") for a in lib.list_artists_detail()}
    rows: list[ManifestRow] = []
    after = None
    while True:
        page = lib.browse_songs(PageReq(limit=500, after=after))
        for s in page.items:
            url = next((v.source_url for v in s.versions if v.source_url), None)
            if not url:
                continue
            artista = s.artists[0] if s.artists else ""
            rows.append(ManifestRow(url=url, artista=artista, musica=s.title,
                                    categoria=art_cat.get(artista.strip().lower(), "")))
        after = page.next_cursor
        if not after:
            break
    return rows


def rows_to_songs(rows: list[ManifestRow]) -> list[dict]:
    """ManifestRow → dicts do arsenal na nuvem (só linhas com URL — dá pra rebaixar)."""
    return [
        {"url": r.url, "artista": r.artista, "musica": r.musica, "categoria": r.categoria}
        for r in rows if r.url
    ]


def songs_to_rows(songs: list[dict]) -> list[ManifestRow]:
    """dicts do arsenal (nuvem) → ManifestRow, prontos pro apply_rows (rebaixa o que faltar)."""
    out: list[ManifestRow] = []
    for s in songs or []:
        url = (s.get("url") or "").strip()
        if not url:
            continue
        out.append(ManifestRow(
            url=url, artista=(s.get("artista") or "").strip(),
            musica=(s.get("musica") or "").strip(), categoria=(s.get("categoria") or "").strip(),
        ))
    return out


def write_csv(path: str, rows: list[ManifestRow]) -> int:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig = Excel PT-BR feliz
        w = csv.writer(f)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow([r.url, r.artista, r.musica, r.categoria])
    return len(rows)


def read_csv(path: str) -> list[ManifestRow]:
    out: list[ManifestRow] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out.append(ManifestRow(
                url=(r.get("url") or "").strip(), artista=(r.get("artista") or "").strip(),
                musica=(r.get("musica") or "").strip(), categoria=(r.get("categoria") or "").strip(),
            ))
    return out


def apply_rows(app, rows: list[ManifestRow], *, max_height: int = 720, audio: bool = False,
               cookies: str = "", skip_existing: bool = True, progress=None) -> dict:
    """Baixa+cataloga cada linha com artista/música/categoria EXATOS. Pula URL que já está no
    acervo (sem rebaixar). progress(i,total,row,status)."""
    lib = app.library
    cat_cache: dict[str, str | None] = {}

    def cat_id(name: str):
        name = (name or "").strip()
        if not name:
            return None
        if name not in cat_cache:
            cid = next((c.id for c in lib.list_categories() if c.name.strip().lower() == name.lower()), None)
            cat_cache[name] = cid or lib.add_category(name).id
        return cat_cache[name]

    total = len(rows); ok = skip = fail = 0

    # conferência INCREMENTAL: numa única consulta descobre tudo que já está no acervo,
    # pra baixar só as novas (evita rebaixar e milhares de checagens 1-a-1). Se a consulta
    # em lote falhar (daemon antigo), cai no modo 1-a-1.
    existing: set[str] = set(); batch_ok = False
    if skip_existing:
        urls = [r.url for r in rows if r.url]
        if progress:
            progress(0, total, None, f"conferindo {len(urls)} música(s) no acervo…")
        try:
            existing = set(lib.existing_media_urls(urls)); batch_ok = True
        except Exception:  # noqa: BLE001
            batch_ok = False

    def _already(url: str) -> bool:
        if batch_ok:
            return url in existing
        try:
            return lib.has_media_url(url)
        except Exception:  # noqa: BLE001
            return False

    for i, r in enumerate(rows, 1):
        if not (r.url and r.artista and r.musica):
            skip += 1
            if progress:
                progress(i, total, r, "pulada (faltou url/artista/música)")
            continue
        if skip_existing and _already(r.url):
            skip += 1
            if progress:
                progress(i, total, r, "já no acervo (não rebaixa)")
            continue
        try:
            if progress:
                progress(i, total, r, "baixando…")
            app.download.execute(r.url, audio_only=audio, max_height=max_height,
                                 artist_hint=r.artista, title_hint=r.musica, cookies=cookies)
            cid = cat_id(r.categoria)
            if cid:
                aid = next((a.id for a in lib.list_artists_detail()
                            if a.name.strip().lower() == r.artista.lower()), None)
                if aid:
                    lib.set_artist_category(aid, cid)
            ok += 1
            if progress:
                progress(i, total, r, "ok")
        except Exception as e:  # noqa: BLE001
            fail += 1
            if progress:
                progress(i, total, r, f"erro: {e}")
    return {"ok": ok, "skip": skip, "fail": fail, "total": total}
