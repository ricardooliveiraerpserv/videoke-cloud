"""Deep links tipados entre aplicações (seção 5.1). Evita strings soltas."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlparse


@dataclass(frozen=True)
class DeepLink:
    scheme: str          # "videodownloader" | "karaoke" | "library"
    action: str          # "search" | "download" | "song" | ...
    params: dict[str, str]

    def to_url(self) -> str:
        query = "&".join(f"{k}={quote(str(v))}" for k, v in self.params.items())
        base = f"{self.scheme}://{self.action}"
        return f"{base}?{query}" if query else base

    @classmethod
    def parse(cls, url: str) -> "DeepLink":
        u = urlparse(url)
        action = (u.netloc or u.path.lstrip("/")).strip("/")
        flat = {k: v[0] for k, v in parse_qs(u.query).items()}
        return cls(scheme=u.scheme, action=action, params=flat)


# Fábricas convenientes (contratos estáveis de integração)
def downloader_search(query: str) -> DeepLink:
    return DeepLink("videodownloader", "search", {"query": query})


def karaoke_song(song_id: str) -> DeepLink:
    return DeepLink("karaoke", "song", {"id": song_id})


def karaoke_queue_add(song_id: str, singer: str) -> DeepLink:
    return DeepLink("karaoke", "queue/add", {"song": song_id, "singer": singer})
