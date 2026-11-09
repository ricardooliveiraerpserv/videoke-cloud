"""G1 — Controle remoto + fila automática na nuvem.

A nuvem não tem SSE, então o padrão é "cast" por polling:
- O player (`/m?session=<id>`) é o RECEIVER (a TV): toca a fila em ordem,
  avança sozinho no fim de cada música e lê `/pb/state` para aplicar comandos.
- O controle (`/operador`, autenticado por op_token) manda `/pb/cmd`.

Fonte de verdade do CURSOR da fila (`idx`) = este estado no servidor. O estado é
EFÊMERO (em memória, por sessão): se o processo reiniciar, o player reconecta pela
fila (que vive no banco) — perda aceitável numa festa ao vivo. Uma instância só no
Render free, então um dict em memória basta.

As transições (`apply_cmd`) são puras e testáveis sem FastAPI/Postgres.
"""
from __future__ import annotations

import threading
import time

_STORE: dict[str, dict] = {}
_LOCK = threading.Lock()

TOM_MIN, TOM_MAX = -5, 5        # semitons (presets da UI vão -2..+2; remoto um pouco mais)
RIT_MIN, RIT_MAX = 80, 120      # % de velocidade (presets 90..110)


def new_state() -> dict:
    return {
        "rev": 0,            # muda a cada comando (o player compara para detectar mudança)
        "idx": 0,            # cursor na fila (índice do item que deve tocar)
        "paused": False,
        "tom": 0,            # semitons
        "rit": 100,          # % velocidade
        "seek_nonce": 0,     # incrementa a cada restart/seek (one-shot)
        "seek_to": 0.0,      # segundos
        "now": {},           # o player reporta aqui o que está tocando
        "updated": time.time(),
    }


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def apply_cmd(state: dict, cmd_type: str, arg=None) -> dict:
    """Aplica UM comando sobre `state` (muta e devolve). Pura — sem I/O."""
    t = cmd_type
    if t == "pause":
        state["paused"] = True
    elif t == "play":
        state["paused"] = False
    elif t == "toggle":
        state["paused"] = not state["paused"]
    elif t == "next":
        state["idx"] = state["idx"] + 1
        state["paused"] = False
    elif t == "prev":
        state["idx"] = max(0, state["idx"] - 1)
        state["paused"] = False
    elif t == "goto":
        state["idx"] = max(0, int(arg or 0))
        state["paused"] = False
    elif t == "restart":
        state["seek_nonce"] += 1
        state["seek_to"] = 0.0
        state["paused"] = False
    elif t == "seek":
        state["seek_nonce"] += 1
        state["seek_to"] = float(arg or 0)
    elif t == "tom":
        state["tom"] = _clamp(int(arg or 0), TOM_MIN, TOM_MAX)
    elif t == "rit":
        state["rit"] = _clamp(int(arg if arg is not None else 100), RIT_MIN, RIT_MAX)
    else:
        return state  # comando desconhecido: no-op (sem bump de rev)
    state["rev"] += 1
    state["updated"] = time.time()
    return state


def _ensure(sid: str) -> dict:
    st = _STORE.get(sid)
    if st is None:
        st = new_state()
        _STORE[sid] = st
    return st


def get_state(sid: str) -> dict:
    with _LOCK:
        return dict(_ensure(sid))


def cmd(sid: str, cmd_type: str, arg=None) -> dict:
    with _LOCK:
        st = _ensure(sid)
        apply_cmd(st, cmd_type, arg)
        return dict(st)


def ended(sid: str, idx) -> dict:
    """O player avisa que terminou o item `idx` → avança o cursor (idempotente)."""
    with _LOCK:
        st = _ensure(sid)
        try:
            same = int(idx) == st["idx"]
        except (TypeError, ValueError):
            same = False
        if same:
            st["idx"] += 1
            st["paused"] = False
            st["rev"] += 1
            st["updated"] = time.time()
        return dict(st)


def report(sid: str, now: dict) -> dict:
    """O player reporta o que está tocando (para o controle exibir)."""
    with _LOCK:
        st = _ensure(sid)
        st["now"] = now
        return dict(st)
