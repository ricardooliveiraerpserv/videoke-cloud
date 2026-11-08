"""Licenciamento por máquina (ativação online + token assinado, offline-first)."""
from .fingerprint import machine_fingerprint
from .gate import activate_with_key, check_license, renew_if_needed

__all__ = ["machine_fingerprint", "check_license", "activate_with_key", "renew_if_needed"]
