"""Impressão digital da máquina — ID estável que MUDA ao formatar/reinstalar o SO.

Windows: MachineGuid (registro). macOS: IOPlatformUUID. Linux: /etc/machine-id.
Sempre retornamos um hash (não expõe o ID cru)."""
from __future__ import annotations

import hashlib
import platform
import subprocess
import uuid


def _raw_machine_id() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            import winreg  # type: ignore[import-not-found]
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography") as k:
                val, _ = winreg.QueryValueEx(k, "MachineGuid")
                if val:
                    return str(val)
        elif system == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        else:  # Linux e afins
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                try:
                    with open(path) as f:
                        v = f.read().strip()
                        if v:
                            return v
                except OSError:
                    continue
    except Exception:  # noqa: BLE001 — qualquer falha cai no fallback
        pass
    return platform.node() or "unknown"   # último recurso (fraco, mas determinístico)


def machine_fingerprint() -> str:
    """Hash curto e estável da máquina (32 hex)."""
    raw = _raw_machine_id()
    return hashlib.sha256(f"kk-karaoke:{raw}".encode()).hexdigest()[:32]


def mac_address() -> str:
    """MAC principal (via uuid.getnode), formatado 'aa:bb:cc:dd:ee:ff'.
    Vazio quando o Python não achou uma NIC real (getnode devolve MAC aleatório
    com o bit multicast ligado) — assim a Central não mostra um MAC falso."""
    try:
        n = uuid.getnode()
        if (n >> 40) & 0x01:   # bit multicast ligado = aleatório, não é MAC real
            return ""
        h = f"{n:012x}"
        return ":".join(h[i:i + 2] for i in range(0, 12, 2))
    except Exception:  # noqa: BLE001
        return ""


def os_name() -> str:
    """SO amigável p/ a Central, ex.: 'Windows 11', 'macOS 26.6', 'Linux'."""
    try:
        s = platform.system()
        if s == "Darwin":
            return f"macOS {platform.mac_ver()[0]}".strip()
        if s == "Windows":
            return f"Windows {platform.release()}".strip()
        return s or ""
    except Exception:  # noqa: BLE001
        return ""
