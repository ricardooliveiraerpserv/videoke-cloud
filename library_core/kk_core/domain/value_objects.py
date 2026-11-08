"""Value Objects do domínio — imutáveis, auto-validados, sem identidade."""
from __future__ import annotations

from dataclasses import dataclass

from kk_shared.contracts.enums import MediaStatus  # noqa: F401 (reexport)


@dataclass(frozen=True)
class Pitch:
    """Tom em semitons, -6 a +6 (regra de negócio do áudio)."""
    semitones: int = 0

    def __post_init__(self) -> None:
        if not -6 <= self.semitones <= 6:
            raise ValueError("pitch deve estar entre -6 e +6 semitons")


@dataclass(frozen=True)
class Tempo:
    """Velocidade em %, 75 a 125, preservando o tom (Rubber Band)."""
    percent: int = 100

    def __post_init__(self) -> None:
        if not 75 <= self.percent <= 125:
            raise ValueError("tempo deve estar entre 75% e 125%")


@dataclass(frozen=True)
class Duration:
    seconds: int = 0

    def __post_init__(self) -> None:
        if self.seconds < 0:
            raise ValueError("duração não pode ser negativa")

    def as_clock(self) -> str:
        h, rem = divmod(self.seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@dataclass(frozen=True)
class Resolution:
    width: int = 0
    height: int = 0

    @classmethod
    def parse(cls, text: str | None) -> "Resolution":
        if not text or "x" not in text:
            return cls()
        try:
            w, h = text.lower().split("x", 1)
            return cls(int(w), int(h))
        except ValueError:
            return cls()

    def __str__(self) -> str:
        return f"{self.width}x{self.height}" if self.width else ""


@dataclass(frozen=True)
class FileHash:
    sha256: str

    def __post_init__(self) -> None:
        if self.sha256 and len(self.sha256) != 64:
            raise ValueError("sha256 deve ter 64 caracteres hex")
