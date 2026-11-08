"""Metadata Engine (aquisição): extrai artista/música do título do vídeo.

Usa o MESMO dicionário/limpeza da curadoria (kk_shared.platform.naming +
known_artists): reconhece a dupla INTEIRA (não quebra 'João Paulo e Daniel'),
resolve apelidos p/ a grafia canônica e limpa o lixo dos títulos de karaokê.
"""
from __future__ import annotations

import re
from pathlib import Path

from kk_shared.platform.known_artists import KNOWN_ARTISTS, canonical_artist
from kk_shared.platform.naming import clean_song_title, split, split_names

_YT_ID = re.compile(r"\s*\[[A-Za-z0-9_-]{6,}\]\s*$")   # [idDoYoutube] no fim

# lixo recorrente nos títulos de download (removido antes de separar)
_JUNK = [
    r"-==.*$", r"\bRaf\s*electronics\b", r"@\S+", r"#\S+",
    r"\b\d{2}\s?\d{4,5}[-\s]?\d{4}\b",
    r"\(?\s*playbacks?[^)]*\)?", r"\bplayback\b", r"\bkaraok\w*\b", r"\bvideok\w*\b",
    r"\bvers[aã]o\b", r"\bversion\b", r"\binstrumental\b", r"\bcover\b",
    r"\bofficial\b", r"\boficial\b", r"\b4k\b", r"\bhd\b", r"\bdvd\b",
    r"\bao\s+vivo\b", r"\bcom\s+letra\b", r"\bcom\s+2[ªa]?\s*voz\b", r"\bsegunda\s+voz\b",
    r"\d+\s*tom\s+(abaixo|acima|baixo|alto)", r"\bremasterizado\b",
]
_JUNK_RE = [re.compile(p, re.IGNORECASE) for p in _JUNK]

# artistas conhecidos, mais específicos primeiro (duplas antes de nomes soltos)
_POOL = sorted(KNOWN_ARTISTS, key=len, reverse=True)
_CONNECTOR = re.compile(r"\s(?:e|&)\s", re.IGNORECASE)


_CAT_NUM = re.compile(r"^\s*\d{3,6}\s*-\s*")           # nº de catálogo do videokê no início

def _strip_junk(text: str) -> str:
    text = _CAT_NUM.sub("", text)                      # "01416 - FREJAT - ..." → "FREJAT - ..."
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", text)      # remove (...) [...]
    for rx in _JUNK_RE:
        t = rx.sub(" ", t)
    t = re.sub(r"[＊*·•▪●○◆➤►]+", " ", t)
    t = re.sub(r"\s+_\s+", " - ", t)                  # separador '_' (Artista _ Música _ …)
    t = re.sub(r"\s*[-–—|/:=]\s*", " - ", t)
    t = re.sub(r"(?:\s*-\s*){2,}", " - ", t)
    return re.sub(r"\s+", " ", t).strip(" -–—|/:·")


def _strip_noise(text: str) -> str:   # compat com import antigo
    return _strip_junk(text)


_MEDIA_EXT = re.compile(
    r"\.(mp4|mkv|avi|webm|mov|m4v|flv|wmv|mpg|mpeg|3gp|mp3|m4a|flac|wav|ogg|opus|"
    r"aac|wma|cdg|zip|mid|kar)$", re.IGNORECASE)


def clean_title(filename: str) -> str:
    """Nome de arquivo/título de vídeo → título legível (tira extensão, [id] e ruído).

    Não usa Path().stem: uma source_title de YouTube pode conter '/', e o stem
    trataria '/' como separador de diretório, descartando tudo antes dele
    ('Cai a Noite - Capital Inicial / Versão Karaokê' → só 'Versão Karaokê')."""
    name = _YT_ID.sub("", filename)
    name = _MEDIA_EXT.sub("", name)
    return _strip_junk(name) or name


def _fallback(cleaned: str) -> tuple[list[str], str]:
    """Sem artista no dicionário: em 'A - B[ - C]', o lado com conector ('e'/'&') é a
    dupla; senão adota a convenção de karaokê 'Artista - Música' (1º pedaço = artista)."""
    parts = [p.strip() for p in re.split(r"\s-\s", cleaned) if p.strip()]
    if len(parts) >= 2:
        conn = [p for p in parts if _CONNECTOR.search(p)]
        if len(conn) == 1:                       # só um lado é dupla → é o artista
            artist = conn[0]
            song = " - ".join(p for p in parts if p is not artist).strip(" -")
            return split_names(artist), song
        # "Artista - Música": 1º pedaço é o artista (guard: curto o bastante p/ ser nome).
        if 1 < len(parts[0]) <= 60:
            return split_names(parts[0]), " - ".join(parts[1:]).strip(" -")
    return [], cleaned


# videokê "NNNNN -Artista [Música] karaokê …" (a música vive no colchete). Só com o nº de
# catálogo na frente, senão pegaria [HD]/[Official]/[idYoutube] de títulos normais.
_VIDEOKE_BRACKET = re.compile(r"^\s*\d{3,6}\s*-?\s*([^\[\]]+?)\s*\[([^\[\]]+?)\]")


def parse(video_title: str, *, artist_hint: str | None = None,
          title_hint: str | None = None) -> tuple[str, list[str]]:
    if title_hint and artist_hint:
        return title_hint, [artist_hint]
    if not artist_hint and not title_hint:
        m = _VIDEOKE_BRACKET.match(video_title)
        if m:
            a, sng = m.group(1).strip(" -"), _strip_junk(m.group(2))
            if 1 < len(a) <= 60 and sng:
                artists = [canonical_artist(x) for x in split_names(a)]
                return (clean_song_title(sng, artists) or sng).strip(), artists
    cleaned = _strip_junk(video_title)
    arts, song = split(cleaned, _POOL)               # tenta pelo dicionário (dupla inteira)
    if not arts:
        arts, song = _fallback(cleaned)
    artists = [canonical_artist(a) for a in arts]
    song = clean_song_title(song, artists) or song
    if artist_hint:
        artists = [artist_hint]
        # o hint é confiável (busca por artista) → tira o nome dele do título
        song = clean_song_title(song, artists) or song
    if title_hint:
        song = title_hint
    return (song or video_title).strip(), [a.strip() for a in artists if a.strip()]
