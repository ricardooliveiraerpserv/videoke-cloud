"""Fábrica do LibraryClient — ponto único de acesso ao Library Core.

Política (arquitetura de serviço): as aplicações SEMPRE falam com o daemon.
Se ele não estiver no ar, sobe-o automaticamente. Assim há um único dono do
banco (o daemon) e nenhuma app abre o SQLite diretamente.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

from .http_client import HttpLibraryClient

DEFAULT_URL = "http://127.0.0.1:8770"


def daemon_url() -> str:
    return os.environ.get("KK_LIBRARY_URL", DEFAULT_URL)


def is_up(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _spawn_daemon(url: str) -> None:
    parsed = urlparse(url)
    port = str(parsed.port or 8770)
    # No exe empacotado (PyInstaller), sys.executable é o próprio app: reinvoca com --daemon
    # (o launcher roteia). Em dev, roda o módulo do daemon do mesmo ambiente Python.
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--daemon", "run", "--host", "127.0.0.1", "--port", port]
    else:
        cmd = [sys.executable, "-m", "kk_core.service.daemon", "run", "--host", "127.0.0.1", "--port", port]
    kwargs: dict = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform.startswith("win"):
        # CREATE_NO_WINDOW | DETACHED_PROCESS — sem janela de console piscando, processo solto
        kwargs["creationflags"] = 0x08000000 | 0x00000008
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def get_library_client(*, spawn: bool = True, wait: float = 10.0) -> HttpLibraryClient:
    url = daemon_url()
    if not is_up(url) and spawn:
        _spawn_daemon(url)
        deadline = time.time() + wait
        while time.time() < deadline and not is_up(url):
            time.sleep(0.2)
    if not is_up(url):
        raise RuntimeError(f"Library Core daemon indisponível em {url} (rode 'kk-libraryd').")
    return HttpLibraryClient(url)
