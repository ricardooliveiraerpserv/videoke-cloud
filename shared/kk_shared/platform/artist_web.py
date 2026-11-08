"""Consulta web do artista: grafia oficial + estilo musical.

Usado pelo download automático e pela curadoria: ao buscar "molejo", resolve
para "Molejo" e descobre o gênero ("pagode" → categoria "Pagode").

Fontes, em cascata (só desce quando a anterior não dá gênero mapeável):
  1. MusicBrainz — tags/gêneros do artista, depois dos álbuns (release-groups);
  2. Wikidata — gênero curado (P136), pelo link do MusicBrainz (página garantida);
  3. Wikipédia — campo "gênero" da ficha, pela página vinculada no Wikidata.
As tags de todas as fontes são AGREGADAS e a especificidade decide (axé > pop).

Sem chave de API (bases abertas; rate-limit ~1 req/s). Qualquer falha de rede
devolve None — o fluxo segue com o dicionário local.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .text import normalize

_UA = {"User-Agent": "KaraokePlatform/1.0 (videoke-familia-silva)"}

# gênero do MusicBrainz (normalizado) → nome da categoria no app
GENRE_MAP: dict[str, str] = {
    "pagode": "Pagode",
    "pagode romantico": "Pagode",
    "samba": "Samba",
    "samba de raiz": "Samba",
    "samba-rock": "Samba",
    "sertanejo": "Sertanejo",
    "musica sertaneja": "Sertanejo",
    "sertanejo universitario": "Sert. Universitário",
    "sertanejo raiz": "Sertanejo",
    "arrocha": "Arrocha",
    "mpb": "MPB",
    "forro": "Forró",
    "axe": "Axé",
    "funk carioca": "Funk",
    "brega": "Brega",
    "piseiro": "Piseiro",
    "gospel": "Gospel",
    "christian music": "Gospel",
    "rock": "Rock",
    # o app não tem categoria "Metal"/"Punk" separada — tudo isso é Rock
    "metal": "Rock",
    "heavy metal": "Rock",
    "hard rock": "Rock",
    "classic rock": "Rock",
    "soft rock": "Rock",
    "folk rock": "Rock",
    "country rock": "Rock",
    "alternative rock": "Rock",
    "progressive rock": "Rock",
    "grunge": "Rock",
    "punk": "Rock",
    "punk rock": "Rock",
    "nu metal": "Rock",
    "new metal": "Rock",
    "alternative metal": "Rock",
    "thrash metal": "Rock",
    "death metal": "Rock",
    "black metal": "Rock",
    "power metal": "Rock",
    "progressive metal": "Rock",
    "groove metal": "Rock",
    "industrial metal": "Rock",
    "industrial rock": "Rock",
    "glam metal": "Rock",
    "metalcore": "Rock",
    "nwobhm": "Rock",
    "pop": "Pop",
    "reggae": "Reggae",
    "bossa nova": "MPB",
    # rótulos como o Wikidata/inglês costuma trazer (P136)
    "pop music": "Pop",
    "musica pop": "Pop",
    "rock music": "Rock",
    "brazilian rock": "Rock",
    "reggae music": "Reggae",
    "musica popular brasileira": "MPB",
    "brazilian popular music": "MPB",
    "gospel music": "Gospel",
    "christian rock": "Gospel",
    "brazilian funk": "Funk",
    "funk": "Funk",
    "brega pop": "Brega",
    "brazilian gospel music": "Gospel",
    # samba-reggae / axé-adjacentes da Bahia (Olodum, Araketu, Reflexu's…) → Axé
    "samba-reggae": "Axé",
    "samba reggae": "Axé",
    "axe music": "Axé",
    "folk-pop": "Pop",
    "folk pop": "Pop",
}

_MIN_SCORE = 85          # confiança mínima do match do MusicBrainz

# gêneros mais ESPECÍFICOS ganham dos guarda-chuvas (Molejo tem 'samba' e
# 'pagode' — pagode diz mais; conta de votos só desempata dentro do nível)
_SPECIFICITY: dict[str, int] = {
    "Pagode": 2, "Sert. Universitário": 2, "Arrocha": 2, "Piseiro": 2,
    "Forró": 2, "Axé": 2, "Funk": 2, "Brega": 2, "Gospel": 2,
    "Sertanejo": 1, "Samba": 1, "MPB": 1, "Rock": 1, "Pop": 1, "Reggae": 1,
}


def _get(url: str, _retries: int = 2) -> dict:
    for attempt in range(_retries + 1):
        req = urllib.request.Request(url, headers=_UA)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (503, 429) and attempt < _retries:  # rate-limit: espera e tenta de novo
                time.sleep(1.5)
                continue
            raise
        except urllib.error.URLError:                        # timeout/conexão: tenta de novo
            if attempt < _retries:
                time.sleep(1.0)
                continue
            raise


def best_genre(tags) -> str | None:
    """Escolhe a categoria a partir das tags/genres [{name, count}, …] —
    só devolve gêneros MAPEADOS (conservador; nada de categoria-lixo)."""
    best, best_rank = None, (-1, -1)
    for t in tags or []:
        cat = GENRE_MAP.get(normalize(t.get("name") or ""))
        if not cat:
            continue
        rank = (_SPECIFICITY.get(cat, 0), int(t.get("count") or 0))
        if rank > best_rank:
            best, best_rank = cat, rank
    return best


def _release_tags(artist_id: str) -> list[dict]:
    """Tags/gêneros agregados dos ÁLBUNS do artista. Muitos artistas BR (ex.:
    Claudia Leitte) têm o registro do artista sem tags, mas os release-groups
    vêm marcados — dá pra inferir o estilo daí."""
    try:
        data = _get(
            f"https://musicbrainz.org/ws/2/release-group?artist={artist_id}"
            "&fmt=json&limit=100&inc=genres+tags")
    except Exception:  # noqa: BLE001 — offline/limite: segue sem web
        return []
    agg: dict[str, int] = {}
    for rg in data.get("release-groups") or []:
        for t in (rg.get("genres") or []) + (rg.get("tags") or []):
            name = t.get("name") or ""
            agg[name] = agg.get(name, 0) + int(t.get("count") or 1)
    return [{"name": k, "count": v} for k, v in agg.items()]


def _wikidata_entity(artist_detail: dict) -> dict:
    """Segue o link do MusicBrainz pro Wikidata e devolve a entidade (1 request).
    O QID garante a página CERTA — nada de busca difusa por nome."""
    qid = ""
    for rel in artist_detail.get("relations") or []:
        if rel.get("type") == "wikidata":
            qid = ((rel.get("url") or {}).get("resource") or "").rstrip("/").split("/")[-1]
            break
    if not qid.startswith("Q"):
        return {}
    try:
        return _get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")["entities"][qid]
    except Exception:  # noqa: BLE001
        return {}


def _p136_tags(ent: dict) -> list[dict]:
    """Gênero curado do Wikidata (propriedade P136), resolvido pra rótulo pt/en."""
    gids = [c["mainsnak"]["datavalue"]["value"]["id"]
            for c in ent.get("claims", {}).get("P136", [])
            if c.get("mainsnak", {}).get("datavalue")]
    if not gids:
        return []
    try:
        lbl = _get("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json"
                   f"&props=labels&languages=en|pt&ids={'|'.join(gids)}")["entities"]
    except Exception:  # noqa: BLE001
        return []
    tags = []
    for gid in gids:
        labels = (lbl.get(gid) or {}).get("labels", {})
        for lang in ("en", "pt"):
            v = labels.get(lang, {}).get("value")
            if v:
                tags.append({"name": v, "count": 1})
    return tags


def _infobox_genres(wikitext: str) -> list[dict]:
    """Extrai o campo 'gênero' (pt) ou 'genre' (en) da ficha da Wikipédia."""
    m = re.search(r"(?is)\|\s*g[êe]nero(?:_musical|s)?\s*=\s*(.*?)(?:\n\s*\|\s*\w|\n\}\})", wikitext)
    if not m:
        m = re.search(r"(?is)\|\s*genres?\s*=\s*(.*?)(?:\n\s*\|\s*\w|\n\}\})", wikitext)
    if not m:
        return []
    v = m.group(1)
    v = re.sub(r"(?is)<ref[^>]*>.*?</ref>|<ref[^>]*/>", " ", v)      # remove notas
    v = re.sub(r"(?is)\{\{\s*(?:citar|cite|refn)[^}]*\}\}", " ", v)  # remove citações
    v = re.sub(r"(?i)\{\{\s*(?:lista horizontal|flatlist|hlist|plainlist|nowrap|nobr)\s*\|", "|", v)
    v = re.sub(r"\}\}", " ", v)
    v = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", v)               # [[x|y]] -> y
    v = re.sub(r"\[\[([^\]]*)\]\]", r"\1", v)                        # [[x]] -> x
    v = re.sub(r"<[^>]+>", " ", v)
    parts = re.split(r"[|,;/\n]|\be\b", v)
    return [{"name": p.strip(" '\"*·•—-"), "count": 1}
            for p in parts if p.strip(" '\"*·•—-")]


def _wikipedia_tags(ent: dict) -> list[dict]:
    """Último recurso: lê o gênero da FICHA da Wikipédia (pt, depois en) pela
    página vinculada no Wikidata. Pega artistas com página mas sem P136 no
    Wikidata (ex.: Saulo Fernandes, Cheiro de Amor)."""
    sitelinks = ent.get("sitelinks") or {}
    for wiki, lang in (("ptwiki", "pt"), ("enwiki", "en")):
        title = (sitelinks.get(wiki) or {}).get("title")
        if not title:
            continue
        try:
            page = _get(f"https://{lang}.wikipedia.org/w/api.php?action=parse&format=json"
                        f"&prop=wikitext&redirects=1&page={urllib.parse.quote(title)}")
            wt = page.get("parse", {}).get("wikitext", {}).get("*", "")
        except Exception:  # noqa: BLE001
            continue
        tags = _infobox_genres(wt)
        if best_genre(tags):     # só aceita se der pra mapear algo
            return tags
    return []


# tipos do Wikidata que confirmam "entidade musical" antes de confiar num match por nome
_MUSIC_INSTANCE = {           # P31 (é um/uma…)
    "Q215380",   # grupo musical
    "Q2088357",  # conjunto musical
    "Q9212979",  # dupla musical
    "Q281643",   # boy band
    "Q7623897",  # girl group
}
_MUSICIAN_OCC = {             # P106 (ocupação) — quando é pessoa (Q5)
    "Q177220",   # cantor(a)
    "Q639669",   # músico(a)
    "Q488205",   # cantor-compositor
    "Q855091",   # guitarrista
    "Q753110",   # compositor(a) de canções
    "Q36834",    # compositor(a)
    "Q183945",   # produtor(a) musical
    "Q2252262",  # rapper
    "Q158852",   # regente
}


def _is_music_entity(ent: dict) -> bool:
    """True se a entidade do Wikidata é banda/grupo OU pessoa com ocupação de músico.
    Evita casar um nome com uma entidade qualquer (cidade, homônimo não-músico)."""
    claims = ent.get("claims", {})
    inst = {c["mainsnak"]["datavalue"]["value"]["id"]
            for c in claims.get("P31", []) if c.get("mainsnak", {}).get("datavalue")}
    if inst & _MUSIC_INSTANCE:
        return True
    occ = {c["mainsnak"]["datavalue"]["value"]["id"]
           for c in claims.get("P106", []) if c.get("mainsnak", {}).get("datavalue")}
    return "Q5" in inst and bool(occ & _MUSICIAN_OCC)


def _wikidata_search_entity(name: str) -> dict:
    """Acha a entidade do artista no Wikidata pelo NOME (quando o MusicBrainz não
    tem link). Estruturado: valida que é músico/banda e que o rótulo casa — sem o
    risco da busca difusa do Wikipédia. Fecha o buraco de famosos sem link no MB
    (ex.: Bell Marques, Durval Lélys, Banda Mel)."""
    import difflib
    key = normalize(name)
    for lang in ("pt", "en"):
        try:
            d = _get("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json"
                     f"&type=item&limit=5&language={lang}&search={urllib.parse.quote(name)}")
        except Exception:  # noqa: BLE001
            continue
        for hit in d.get("search") or []:
            label = hit.get("label") or ""
            nlabel = normalize(label)
            # rótulo tem que bater bem (evita casar 'Saulo' com outra pessoa)
            if nlabel != key and difflib.SequenceMatcher(None, nlabel, key).ratio() < 0.9:
                continue
            try:
                ent = _get(f"https://www.wikidata.org/wiki/Special:EntityData/{hit['id']}.json"
                           )["entities"][hit["id"]]
            except Exception:  # noqa: BLE001
                continue
            if _is_music_entity(ent):
                return ent
    return {}


def _variants(term: str) -> list[str]:
    """Grafias a tentar: como veio, 'e'↔'&' (duplas BR) e sem aspas (fuzzy)."""
    outs = [term]
    if " e " in f" {term} ".lower():
        import re
        outs.append(re.sub(r"(?i)\s+e\s+", " & ", term))
    if "&" in term:
        outs.append(term.replace("&", "e"))
    return outs


def lookup_artist(term: str) -> dict | None:
    """{'name': 'Molejo', 'genre': 'Pagode'} — ou None se não confiável/offline."""
    term = (term or "").strip()
    if not term:
        return None
    a = None
    for cand in _variants(term):
        q = urllib.parse.quote(f'artist:"{cand}"')
        try:
            data = _get(f"https://musicbrainz.org/ws/2/artist/?query={q}&fmt=json&limit=3")
        except Exception:  # noqa: BLE001 — offline/limite: segue sem MusicBrainz
            data = {}
        arts = data.get("artists") or []
        if arts and int(arts[0].get("score") or 0) >= _MIN_SCORE:
            a = arts[0]
            break

    name = ((a.get("name") if a else "") or term).strip()
    det = {}
    genre = best_genre(a.get("tags")) if a else None
    if genre is None and a and a.get("id"):  # detalhe do artista: genres + link Wikidata
        try:
            det = _get(f"https://musicbrainz.org/ws/2/artist/{a['id']}?inc=genres+url-rels&fmt=json")
            genre = best_genre(det.get("genres") or det.get("tags"))
        except Exception:  # noqa: BLE001
            det = {}
    if genre is None:
        # junta as fontes e deixa a ESPECIFICIDADE decidir (ex.: 'axé' ganha de
        # 'pop', sem depender da ordem). Escala requisições conforme precisa.
        tags = list(_release_tags(a["id"])) if a and a.get("id") else []  # álbuns (MusicBrainz)
        ent = _wikidata_entity(det)              # pelo link do MB (página garantida)
        if not ent:                              # MB sem link → busca no Wikidata pelo nome
            ent = _wikidata_search_entity(name)
        if ent:
            tags += _p136_tags(ent)              # gênero curado do Wikidata
            if best_genre(tags) is None:         # ainda nada → ficha da Wikipédia
                tags += _wikipedia_tags(ent)
            if a is None:                        # MB não achou → adota o rótulo do Wikidata
                lbl = ((ent.get("labels") or {}).get("pt")
                       or (ent.get("labels") or {}).get("en") or {}).get("value")
                if lbl:
                    name = lbl.strip()
        genre = best_genre(tags)
    if a is None and genre is None:              # MB não achou e Wikidata não confirmou
        return None
    return {"name": name, "genre": genre}
