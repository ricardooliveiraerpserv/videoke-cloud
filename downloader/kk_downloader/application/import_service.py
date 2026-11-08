"""Importa uma pasta de mídia já baixada para o Library Core (cataloga sem baixar).

Referencia os arquivos no lugar (não move). Idempotente: o Core deduplica por
sha256, então reimportar a mesma pasta não duplica."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

_YT_ID = re.compile(r"\[([A-Za-z0-9_-]{11})\]")

from kk_shared.client.library_client import LibraryClient
from kk_shared.contracts.dtos import RegisterMediaDTO
from kk_shared.platform.known_artists import KNOWN_ARTISTS
from kk_shared.platform.naming import (
    build_segment_freq, clean_song_title, detect_artists, split, split_by_frequency,
    strip_channel_junk,
)
from kk_shared.platform.text import normalize

from ..infrastructure.media_probe import MEDIA_EXTS, probe, sha256
from ..infrastructure.metadata_parser import clean_title, parse as parse_meta

Progress = Callable[[int, int, str], None]  # (i, total, título)


def _dedup(names: list[str]) -> list[str]:
    """Remove repetidos (por forma normalizada), preservando a ordem/prioridade."""
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        k = normalize(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


class ImportFolderUseCase:
    def __init__(self, library: LibraryClient):
        self._lib = library

    def execute(self, folder: str, *, recursive: bool = True,
                artist_hint: str | None = None, category: str | None = None,
                title_fetcher: Callable[[str], str | None] | None = None,
                progress: Progress | None = None) -> dict:
        root = Path(folder).expanduser()
        files = sorted(
            p for p in (root.rglob("*") if recursive else root.iterdir())
            if p.is_file() and p.suffix.lower() in MEDIA_EXTS
        )
        # nome base: por padrão o do arquivo; se title_fetcher, busca o título
        # original no YouTube pelo ID [xxxxxxxxxxx] embutido no nome.
        cleaned, raws = [], []
        for i, p in enumerate(files, 1):
            name = p.name
            if title_fetcher:
                m = _YT_ID.search(name)
                if m:
                    if progress:
                        progress(i, len(files), f"YouTube: {name[:40]}")
                    try:
                        yt = title_fetcher(m.group(1))
                    except Exception:  # noqa: BLE001
                        yt = None
                    if yt:
                        name = yt
            raws.append(name)                    # título original (web) / nome do arquivo
            cleaned.append(strip_channel_junk(clean_title(name)))
        # candidatos a artista, em ordem de confiança:
        #   dica explícita  →  recorrência na pasta  →  já no acervo  →  lista conhecida
        if artist_hint:
            candidates = [artist_hint]
        else:
            try:
                from_db = self._lib.list_artists()
            except Exception:  # noqa: BLE001
                from_db = []
            # precedência: a RECORRÊNCIA da PRÓPRIA pasta primeiro (verdade local);
            # cadastro e dicionário entram só como reforço/fallback. Se o cadastro
            # viesse antes, uma música nova casaria com um artista do acervo que
            # apenas aparece no texto → traria artista que o usuário não pediu.
            candidates = _dedup(detect_artists(cleaned) + from_db + KNOWN_ARTISTS)

        # frequência dos segmentos na pasta: o artista se repete, a música é única
        seg_freq, seg_spell = build_segment_freq(cleaned)

        added = skipped = failed = 0
        assigned_artists: set[str] = set()      # p/ categorizar todos ao final
        total = len(files)
        for i, (path, name) in enumerate(zip(files, cleaned), 1):
            if artist_hint:
                # pasta de UM cantor: crava o cantor em TODAS as músicas; o título é o
                # nome sem o cantor. Não deixa a detecção automática inventar outro.
                a2, title = split(name, [artist_hint])
                artists = [artist_hint]
                if not a2:
                    title = clean_song_title(name, [artist_hint]) or name
            else:
                artists, title = split(name, candidates)
                if not artists:        # recorrência/dicionário falhou → decide por frequência
                    artists, title = split_by_frequency(name, seg_freq, seg_spell, total)
                if not artists:        # desconhecido → chute por conector ('A - B')
                    title2, artists2 = parse_meta(name)
                    if artists2:
                        artists, title = artists2, title2
            if progress:
                progress(i, total, title)
            try:
                info = probe(path)
                view = self._lib.register_media(RegisterMediaDTO(
                    title=title, artists=artists, source_path=str(path),
                    container=info.get("container"), video_codec=info.get("video_codec"),
                    audio_codec=info.get("audio_codec"),
                    duration_s=info.get("duration_s", 0), resolution=info.get("resolution"),
                    sha256=sha256(path), source_url="", source_title=raws[i - 1],
                    organize=False,  # referencia no lugar
                ))
                if view is None:          # arquivo na lista negra → ignorado
                    skipped += 1
                    continue
                self._attach_sidecar_lyrics(path, view.id)
                for a in (artists or []):
                    if a and a.strip():
                        assigned_artists.add(a.strip())
                added += 1
            except Exception:  # noqa: BLE001
                failed += 1

        categorized = self._apply_category(category, assigned_artists)
        return {"total": total, "added": added, "skipped": skipped, "failed": failed,
                "categorized": categorized}

    def _apply_category(self, category: str | None, artist_names: set[str]) -> int:
        """Põe os artistas desta importação na categoria (estilo) escolhida — mas
        SÓ os que ainda estão SEM estilo (nunca sobrescreve categoria já definida).
        Cria a categoria se não existir. Retorna quantos artistas foram vinculados."""
        category = (category or "").strip()
        if not category or not artist_names:
            return 0
        cats = {c.name: c.id for c in self._lib.list_categories()}
        cid = cats.get(category) or self._lib.add_category(category).id
        by_norm = {normalize(a.name): a for a in self._lib.list_artists_detail()}
        n = 0
        for name in artist_names:
            art = by_norm.get(normalize(name))
            if art is None or getattr(art, "category_id", None):
                continue                       # já tem estilo → não sobrescreve
            self._lib.set_artist_category(art.id, cid)
            n += 1
        return n

    def _attach_sidecar_lyrics(self, media_path: Path, song_id: str) -> None:
        for ext in (".lrc", ".srt", ".txt"):
            side = media_path.with_suffix(ext)
            if side.exists():
                try:
                    content = side.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    return
                self._lib.set_lyrics(song_id, content, fmt=ext.lstrip("."), source="sidecar")
                return
