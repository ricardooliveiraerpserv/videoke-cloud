"""Separação artista × música a partir do nome do arquivo.

Nomes de videokê variam MUITO (ordem 'MÚSICA - ARTISTA' e 'ARTISTA - MÚSICA',
'&' vs ' e ', anos soltos '1992', decorações 'Karaokê'…). Identificamos o(s)
artista(s) pela RECORRÊNCIA na pasta (ou por dica explícita) e o resto vira a
música — tolerando as variações acima.
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from .text import normalize

_SPLIT_DASH = re.compile(r"\s[-–—]\s")
# separa só convidados (feat./part.); duplas ("João Paulo e Daniel",
# "Chitãozinho & Xororó") ficam como UM artista.
_SPLIT_NAMES = re.compile(r"\s*(?:\bfeat\.?\b|\bpart\.?\b|\bpart\b)\s*", re.IGNORECASE)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# palavras que denunciam decoração (não são nome de artista)
_STOPWORD = {
    "karaoke", "karaoke", "playback", "cover", "violao", "oficial",
    "modao", "remasterizado", "instrumental", "sequencia", "vocal",
}


def _akey(s: str) -> str:
    """Chave canônica de comparação: sem acento/caixa, '&'→'e', sem ano solto,
    sem pontuação ('Ira!' == 'Ira', 'Charlie Brown Jr.' == 'Charlie Brown Jr')."""
    k = normalize(s).replace("&", " e ")
    k = _YEAR.sub(" ", k)
    k = re.sub(r"[^\w\s]", " ", k)          # tira pontuação (!, ., -, …)
    return re.sub(r"\s+", " ", k).strip()


def _is_junk(akey: str) -> bool:
    return bool(set(akey.split()) & _STOPWORD)


def _has_words(hay: str, needle: str) -> bool:
    """`needle` (chave canônica) aparece como sequência de palavras inteiras em `hay`."""
    if not needle:
        return False
    return re.search(rf"\b{re.escape(needle)}\b", hay) is not None


def split_names(artist: str) -> list[str]:
    return [a.strip() for a in _SPLIT_NAMES.split(artist) if a.strip()] or [artist.strip()]


# blocos Unicode de emojis/pictogramas/símbolos (não pega letras acentuadas, que ficam bem abaixo)
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"          # emoji principais (emoticons, pictogramas, transporte, símbolos suplem.)
    "\U00002600-\U000027BF"          # misc symbols + dingbats (☀ ✂ ✅ ✨…)
    "\U0001F1E6-\U0001F1FF"          # bandeiras (regional indicators)
    "\U00002B00-\U00002BFF"          # estrelas/setas (⭐ ✳)
    "\U00002190-\U000021FF"          # setas
    "\U00002300-\U000023FF"          # misc técnico (⏱ ⌚ ⏳)
    "\U00002460-\U000024FF"          # circundados (①  Ⓜ)
    "\U00002122\U000000AE\U00002139" # ™ ® ℹ
    "\U0000FE00-\U0000FE0F"          # variation selectors
    "\U0000200D\U0000FEFF\U0000FE0E\U0000FE0F"  # ZWJ / marcadores
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Remove emojis/pictogramas/símbolos de emoji do texto, preservando letras
    (inclusive acentuadas), números e pontuação comum. Colapsa espaços e bordas."""
    t = _EMOJI.sub(" ", text or "")
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" -–—|/·:.\t")


def name_similarity(a: str, b: str) -> float:
    """Similaridade 0..1 entre dois nomes de artista (sem acento/caixa, '&'→'e')."""
    return SequenceMatcher(None, _akey(a), _akey(b)).ratio()


def reference_duration(title: str, hits, *, min_count: int = 2,
                       low: int = 60, high: int = 720) -> tuple[int, int]:
    """(mediana, nº de referências) da duração de OUTRAS versões cujo TÍTULO casa
    com `title` — para detectar arquivos incompletos.

    Só conta resultados cuja duração está entre `low` e `high` segundos E cujo
    título contém >=60% das palavras (>=3 letras) do título da música (evita
    comparar com vídeo/compilação de OUTRA música). Retorna mediana=0 quando há
    menos de `min_count` referências confiáveis (= 'não identificada')."""
    from statistics import median

    tkeys = {w for w in _akey(title).split() if len(w) >= 3}
    durs: list[int] = []
    for h in hits:
        d = getattr(h, "duration_s", 0) or 0
        if not (low <= d <= high):
            continue
        hkey = set(_akey(getattr(h, "title", "")).split())
        if not tkeys or len(tkeys & hkey) / len(tkeys) >= 0.6:
            durs.append(d)
    if len(durs) < min_count:
        return 0, len(durs)
    return int(median(durs)), len(durs)


def best_match(name: str, candidates, threshold: float = 0.88,
               same_word_count: bool = True) -> str | None:
    """Candidato mais parecido com `name` (ou None se nada passar do limiar).

    CONSERVADOR por padrão: exige o MESMO número de palavras — assim 'Daniel'
    (solo) nunca é fundido em 'João Paulo e Daniel' (dupla). Match exato de
    normalização vence na hora. Use `same_word_count=False` só onde há
    confirmação humana (sugestões de duplicata)."""
    nk = _akey(name)
    if not nk:
        return None
    n_tokens = len(nk.split())
    best, best_score = None, threshold
    for cand in candidates:
        ck = _akey(cand)
        if not ck:
            continue
        if ck == nk:
            return cand                                  # idêntico após normalizar
        if same_word_count and len(ck.split()) != n_tokens:
            continue                                     # nº de palavras difere → não arrisca
        score = SequenceMatcher(None, nk, ck).ratio()
        if score > best_score:
            best, best_score = cand, score
    return best


def detect_artists(cleaned_names: list[str], min_count: int = 3) -> list[str]:
    """Segmentos (entre ' - ') que se repetem na pasta = artistas prováveis.

    Colapsa variantes ('&'/'e', acentos, anos) numa mesma chave, soma as
    ocorrências e devolve a grafia mais comum de cada — ordenado por frequência.
    Cobre pasta com vários artistas.
    """
    counts: Counter[str] = Counter()
    spellings: dict[str, Counter] = {}
    for name in cleaned_names:
        seen: set[str] = set()
        for part in (p.strip() for p in _SPLIT_DASH.split(name) if p.strip()):
            k = _akey(part)
            if len(k) >= 5 and not _is_junk(k) and k not in seen:
                seen.add(k)
                counts[k] += 1
                spellings.setdefault(k, Counter())[part] += 1
    thr = max(2, min(min_count, int(len(cleaned_names) * 0.15) or min_count))
    keys = [k for k, c in counts.most_common() if c >= thr]
    return [spellings[k].most_common(1)[0][0] for k in keys]


def detect_artist(cleaned_names: list[str]) -> str | None:
    found = detect_artists(cleaned_names, min_count=2)
    return found[0] if found else None


# frases de canal de karaokê (não são artista NEM música) — removidas antes de
# separar/contar, senão viram "artista" por aparecerem em muitos arquivos.
_CHANNEL_JUNK = re.compile(
    r"(?iu)\b(solte\s+a\s+voz(\s+com\s+est[ea])?|backtracking|"
    r"karaok[eê]\s+(club|version|channel|vers[aã]o)|the\s+karaoke\s+channel|"
    r"sing\s+king|cante\s+junto|com\s+letra\s+na\s+tela)\b")


def strip_channel_junk(name: str) -> str:
    """Remove decorações de canal ('Solte a Voz com Este', 'Backtracking'…) e
    limpa traços/espaços que sobrarem — preservando artista e música."""
    t = _CHANNEL_JUNK.sub(" ", name or "")
    t = re.sub(r"\s*[-–—]\s*(?=[-–—])", " ", t)         # traços órfãos consecutivos
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|/·:.")
    return t


# marca de faixa de videokê/karaokê no TÍTULO ou no NOME DO CANAL
_KARAOKE_MARK = re.compile(
    r"(?iu)\b(karaok[eê]|videok[eê]|play\s?back|instrumental|sem\s+vocal|"
    r"com\s+letra|cante?\s+junto|vers[aã]o\s+karaok[eê]|2[ªa]?\s*voz)\b")


def looks_like_karaoke(*texts: str) -> bool:
    """True se algum dos textos (título e/ou canal) tem cara de faixa de
    videokê/karaokê. Serve p/ filtrar clipe oficial, lyric video e ao-vivo que
    NÃO são videokê. Ex.: canal 'Clubinho do Karaokê' já casa pelo canal."""
    return bool(_KARAOKE_MARK.search(" ".join(t or "" for t in texts)))


def build_segment_freq(cleaned_names: list[str]):
    """Frequência (e grafia mais comum) de cada segmento entre ' - ' na pasta.
    O ARTISTA se repete pela pasta; o TÍTULO costuma ser único."""
    freq: Counter[str] = Counter()
    spell: dict[str, Counter] = {}
    for name in cleaned_names:
        seen: set[str] = set()
        for part in (p.strip() for p in _SPLIT_DASH.split(name) if p.strip()):
            k = _akey(part)
            if len(k) >= 3 and not _is_junk(k) and k not in seen:
                seen.add(k)
                freq[k] += 1
                spell.setdefault(k, Counter())[part] += 1
    return freq, spell


def split_by_frequency(name: str, freq, spell, total: int, *,
                       min_count: int = 2) -> tuple[list[str], str]:
    """Separa 'A - B [- …]' escolhendo como ARTISTA o segmento que MAIS se repete
    na pasta (o título costuma ser único). PRECISÃO > cobertura: só decide quando há
    MAIORIA ESTRITA (sem empate) e nunca deixa artista == música. Devolve
    ([artista], título) ou ([], name) quando não dá p/ decidir com segurança."""
    parts = [p.strip() for p in _SPLIT_DASH.split(name) if p.strip()]
    if len(parts) < 2:
        return [], name
    deco_cut = max(min_count + 1, int(total * 0.30))   # acima disso = decoração de canal
    # frequência de cada parte, descartando tags de canal ultra-frequentes (3+ partes)
    scored = []
    for p in parts:
        f = freq.get(_akey(p), 0)
        if f > deco_cut and len(parts) > 2:
            continue
        scored.append((f, p))
    if not scored:
        return [], name
    scored.sort(key=lambda x: x[0], reverse=True)
    top_f, art_part = scored[0]
    if top_f < min_count:
        return [], name
    # MAIORIA ESTRITA: o artista tem de aparecer mais que qualquer outra parte
    if len(scored) > 1 and scored[1][0] >= top_f:
        return [], name                                # empate → não arrisca
    ak = _akey(art_part)
    artist = spell[ak].most_common(1)[0][0] if ak in spell else art_part
    song = " - ".join(p for p in parts if _akey(p) != ak)
    song = _clean_song(song)
    if not song or _akey(song) == ak:                  # nada sobrou / artista == música
        return [], name
    return split_names(artist), song


# decoração a remover de DENTRO do título (palavras/frases), com ou sem acento
_TITLE_JUNK = re.compile(
    r"(?iu)\b(karaok[eê]|videok[eê]|play\s?back|instrumental|viol[aã]o|"
    r"ac[uú]stico|ao\s+vivo|vers[aã]o\s+karaok[eê]|com\s+2[ªa]?\s*voz|sem\s+vocal|"
    r"segunda\s+voz|voz\s+original|com\s+letra|tom\s+(baixo|alto)|remasterizado)\b"
)


def clean_song_title(title: str, artists=None) -> str:
    """Remove decorações do TÍTULO (karaokê/videokê/playback…), o nome do artista
    (se aparecer), anos soltos e sobras de pontuação — preservando o nome da música."""
    t = title
    # limpa símbolos ANTES de remover o artista (senão '*Gino' não casa com 'Gino')
    t = re.sub(r"[\"“”＂']", "", t)                     # aspas soltas
    t = re.sub(r"[*_~＊•▪●○◆➤►♪♫🎤🎵🔴❤️😢]+", " ", t)     # asteriscos/emojis/símbolos
    t = re.sub(r"\s{2,}", " ", t).strip()
    for a in (artists or []):                          # tira o nome do artista do título
        stripped = _strip_artist_tokens(t, a)
        if stripped:                                   # não zera o título
            t = stripped
    t = _TITLE_JUNK.sub(" ", t)
    t = _YEAR.sub(" ", t)
    t = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", " ", t)      # parênteses/colchetes vazios
    t = re.sub(r"\s*[-–—|/·:]\s*", " - ", t)            # normaliza separadores
    t = re.sub(r"(?:\s*-\s*){2,}", " - ", t)            # traços repetidos
    t = re.sub(r"\.{2,}", " ", t)                       # reticências/pontos repetidos
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t.strip(" -–—|/·:.*_~＊•")                    # tira lixo nas bordas


def _clean_song(song: str) -> str:
    """Limpa o título final: descarta segmentos de decoração ('… - Karaokê …'),
    anos soltos, números de catálogo ('03140 - …') e palavras de decoração."""
    segs = [s.strip() for s in _SPLIT_DASH.split(song) if s.strip()]
    kept = [s for s in segs if not _is_junk(_akey(s))]
    # nº de catálogo de coletânea no começo (3-6 dígitos sozinhos num segmento)
    while len(kept) > 1 and re.fullmatch(r"\d{3,6}", kept[0]):
        kept = kept[1:]
    out = " - ".join(kept or segs)
    out = re.sub(r"^\d{3,6}\s+", "", out)   # nº colado sem hífen: '3138 Mariana'
    return clean_song_title(out) or song.strip()


def _strip_artist_tokens(name: str, artist: str) -> str:
    """Remove o nome do artista do texto como FRASE (bloco de palavras na ordem),
    preservando conectores soltos do título (ex.: 'Aos Trancos e Barrancos')."""
    a_words = _akey(artist).split()
    if not a_words:
        return name.strip(" -")
    words = name.split()
    keys = [_akey(w) for w in words]
    n = len(a_words)
    out: list[str] = []
    i = 0
    while i < len(words):
        if keys[i:i + n] == a_words:      # bateu o bloco do artista → pula
            i += n
        else:
            out.append(words[i]); i += 1
    return re.sub(r"\s+", " ", " ".join(out)).strip(" -")


def split(cleaned_name: str, artists) -> tuple[list[str], str]:
    """(artistas, título). `artists` pode ser str ou lista de candidatos (mais
    frequente primeiro); casa o primeiro candidato que aparecer neste nome —
    tolerando '&'/'e', acentos, anos e decorações ao redor."""
    if isinstance(artists, str):
        artists = [artists]
    parts = [p.strip() for p in _SPLIT_DASH.split(cleaned_name) if p.strip()]
    part_keys = [(p, _akey(p)) for p in parts]

    # 1) formato 'A - B' (2+ partes): descarta a parte que CONTÉM o artista (leva
    # junto lixo). Só com hífen — sem hífen o nome inteiro seria "uma parte" e o
    # artista casaria no MEIO do título (falso positivo). Aí vai pro passo 2.
    if len(parts) >= 2:
        for artist in (artists or []):
            ak = _akey(artist)
            n = len(ak.split())
            for p, pk in part_keys:
                # candidato de 1 palavra: só casa se FOR o segmento inteiro ('Amor'
                # não pode casar dentro de 'Amor Perfeito'). 2+ palavras: sinal forte,
                # pode casar dentro do segmento (leva junto o lixo).
                ok = (pk == ak) if n == 1 else _has_words(pk, ak)
                if ok:
                    song = " - ".join(x for x in parts if x is not p).strip(" -")
                    return split_names(artist), (_clean_song(song) or cleaned_name)

    # 2) SEM ' - ' (segmento único): o artista tem de estar nas BORDAS (começo/fim)
    # do nome — um candidato de UMA palavra no MEIO do título ('…meu AMOR por você')
    # é coincidência e traria artista que o usuário não pediu. Nome de 2+ palavras
    # em qualquer posição já é sinal forte. Com hífen (2+ partes) NÃO cai aqui: a
    # estrutura é por segmento (passo 1), senão 'Amor Perfeito - X' viraria 'Amor'.
    if len(parts) >= 2:
        return [], cleaned_name
    wtokens = _akey(cleaned_name).split()
    for artist in (artists or []):
        at = _akey(artist).split()
        n = len(at)
        if not n or n > len(wtokens):
            continue
        edge = wtokens[:n] == at or wtokens[-n:] == at
        if edge or (n >= 2 and _has_words(" ".join(wtokens), " ".join(at))):
            song = _strip_artist_tokens(cleaned_name, artist)
            return split_names(artist), (_clean_song(song) or cleaned_name)

    return [], cleaned_name


# marcadores de canal de karaokê que APRESENTAM o intérprete original
_CTX_MARKER = re.compile(
    r"(?iu)(?:made\s+(?:popular|famous)\s+by|no\s+estilo\s+d[eo]s?|"
    r"in\s+the\s+style\s+of|style\s+of|\bstyle\b|sucesso\s+d[eo]s?)\s+(.+)$")
_BRACKET_GRP = re.compile(r"[\(\[\{]([^\)\]\}]+)[\)\]\}]")


def artist_from_context(raw_title: str, pool=None) -> str | None:
    """Descobre o intérprete em títulos de karaokê onde ele NÃO vem em 'Artista -
    Música', e sim num marcador — 'Made Popular By X', 'No Estilo de X',
    'Style X', 'Sucesso de X' — ou entre parênteses '(Fulano e Beltrano)'.
    O parser normal descarta parênteses; aqui olhamos ANTES de descartar.
    Retorna a grafia canônica do dicionário quando reconhece, senão o nome cru."""
    raw = raw_title or ""
    pool = pool or []
    trusted, loose = [], []
    for grp in _BRACKET_GRP.findall(raw):            # dentro de (…) [] {}
        m = _CTX_MARKER.search(grp)
        (trusted if m else loose).append(m.group(1) if m else grp)
    m = _CTX_MARKER.search(raw)                      # marcador no texto corrido
    if m:
        trusted.append(m.group(1))

    def _clean(s: str) -> str:
        s = _TITLE_JUNK.sub(" ", s)
        s = re.sub(r"[\(\)\[\]\{\}]", " ", s)
        s = _YEAR.sub(" ", s)
        return re.sub(r"\s+", " ", s).strip(" -–—|/·:.,")

    def _pick(cands, strict: bool) -> str | None:
        for cand in cands:
            c = _clean(cand); ck = _akey(c)
            if not c or _is_junk(ck):
                continue
            hit = next((a for a in pool if _has_words(ck, _akey(a))), None)
            if hit:
                return hit                          # grafia canônica do dicionário
            has_conn = " e " in f" {ck} "
            n = len(c.split())
            if not strict and (has_conn or 2 <= n <= 4):
                return c                            # marcador confiável (nomeia o artista)
            if strict and has_conn and n <= 4:
                return c                            # parêntese solto: só dupla clara
        return None

    return _pick(trusted, strict=False) or _pick(loose, strict=True)
