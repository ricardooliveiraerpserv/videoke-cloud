"""HttpLibraryClient — implementação do contrato LibraryClient sobre HTTP.

Mesma interface do InProcessLibraryClient (ADR-1): as aplicações não sabem se
falam com o Core na memória, num daemon local ou num servidor na LAN. Usa só a
stdlib (urllib + threads) — sem framework. Eventos chegam por SSE (/events).
"""
from __future__ import annotations

import json
import threading
import urllib.request
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from ..contracts.dtos import (
    ArtistCategoryView,
    ArtistView,
    EnqueueDTO,
    HistoryEntryView,
    LyricsView,
    MediaSourceDTO,
    Page,
    PageReq,
    PlaylistItemView,
    PlaylistView,
    PresetDTO,
    QueueItemView,
    RegisterMediaDTO,
    SearchFilters,
    SongRequestView,
    SongRowView,
    SongView,
)
from ..contracts.enums import QueueStatus
from ..events.bus import Handler, Subscription


class HttpLibraryClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8770", timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._sse_thread: threading.Thread | None = None
        self._sse_stop = threading.Event()

    # ---- RPC ----
    def _rpc(self, method: str, **params: Any) -> Any:
        body = json.dumps({"method": method, "params": params}).encode()
        req = urllib.request.Request(
            f"{self.base}/rpc", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "erro remoto no Library Core"))
        return payload.get("result")

    # ---- catálogo ----
    def register_media(self, dto: RegisterMediaDTO) -> SongView | None:
        r = self._rpc("register_media", dto=dto.model_dump(mode="json"))
        return SongView.model_validate(r) if r else None       # None = na lista negra

    def blacklist_song(self, song_id: str) -> None:
        self._rpc("blacklist_song", song_id=song_id)

    def blacklist_songs(self, song_ids: list[str]) -> int:
        return int(self._rpc("blacklist_songs", song_ids=song_ids) or 0)

    def trash_songs(self, song_ids: list[str]) -> int:
        return int(self._rpc("trash_songs", song_ids=song_ids) or 0)

    def blacklist_media(self, media_file_id: str) -> None:
        self._rpc("blacklist_media", media_file_id=media_file_id)

    def purge_songs(self, song_ids: list[str]) -> dict:
        return dict(self._rpc("purge_songs", song_ids=song_ids) or {})

    def list_trash(self) -> list[SongView]:
        return [SongView.model_validate(x) for x in (self._rpc("list_trash") or [])]

    def restore_song(self, song_id: str) -> SongView | None:
        r = self._rpc("restore_song", song_id=song_id)
        return SongView.model_validate(r) if r else None

    def search_songs(self, query, filters=None, page=None) -> Page[SongView]:
        r = self._rpc(
            "search_songs", query=query,
            filters=filters.model_dump(mode="json") if filters else None,
            page=page.model_dump(mode="json") if page else None,
        )
        return Page[SongView].model_validate(r)

    def get_song(self, song_id: str) -> SongView | None:
        r = self._rpc("get_song", song_id=song_id)
        return SongView.model_validate(r) if r else None

    def browse_songs(self, page=None) -> Page[SongView]:
        r = self._rpc("browse_songs", page=page.model_dump(mode="json") if page else None)
        return Page[SongView].model_validate(r)

    def browse_rows(self, page=None) -> Page[SongRowView]:
        r = self._rpc("browse_rows", page=page.model_dump(mode="json") if page else None)
        return Page[SongRowView].model_validate(r)

    def update_song(self, song_id: str, title: str, artists: list[str]) -> SongView | None:
        r = self._rpc("update_song", song_id=song_id, title=title, artists=artists)
        return SongView.model_validate(r) if r else None

    def list_artists(self) -> list[str]:
        return list(self._rpc("list_artists") or [])

    def has_media_url(self, source_url: str) -> bool:
        return bool(self._rpc("has_media_url", source_url=source_url))

    def existing_media_urls(self, urls: list[str]) -> list[str]:
        return list(self._rpc("existing_media_urls", urls=urls) or [])

    # ---- cadastro de artistas ----
    def list_artists_detail(self) -> list[ArtistView]:
        return [ArtistView.model_validate(x) for x in (self._rpc("list_artists_detail") or [])]

    def add_artist(self, name: str) -> ArtistView:
        return ArtistView.model_validate(self._rpc("add_artist", name=name))

    def rename_artist(self, artist_id: str, name: str) -> None:
        self._rpc("rename_artist", artist_id=artist_id, name=name)

    def delete_artist(self, artist_id: str) -> None:
        self._rpc("delete_artist", artist_id=artist_id)

    def artist_songs(self, artist_id: str) -> list[SongView]:
        return [SongView.model_validate(x) for x in (self._rpc("artist_songs", artist_id=artist_id) or [])]

    def delete_artist_with_songs(self, artist_id: str) -> int:
        return int(self._rpc("delete_artist_with_songs", artist_id=artist_id) or 0)

    def merge_artists(self, from_id: str, into_id: str) -> None:
        self._rpc("merge_artists", from_id=from_id, into_id=into_id)

    def artist_duplicate_clusters(self) -> list[list[ArtistView]]:
        r = self._rpc("artist_duplicate_clusters") or []
        return [[ArtistView.model_validate(a) for a in grp] for grp in r]

    def songs_without_artist(self) -> list[SongView]:
        return [SongView.model_validate(x) for x in (self._rpc("songs_without_artist") or [])]

    # ---- categorias de artista ----
    def list_categories(self) -> list[ArtistCategoryView]:
        return [ArtistCategoryView.model_validate(x) for x in (self._rpc("list_categories") or [])]

    def add_category(self, name: str) -> ArtistCategoryView:
        return ArtistCategoryView.model_validate(self._rpc("add_category", name=name))

    def rename_category(self, category_id: str, name: str) -> None:
        self._rpc("rename_category", category_id=category_id, name=name)

    def delete_category(self, category_id: str) -> None:
        self._rpc("delete_category", category_id=category_id)

    def set_artist_category(self, artist_id: str, category_id: str | None) -> None:
        self._rpc("set_artist_category", artist_id=artist_id, category_id=category_id)

    def set_artists_category(self, artist_ids: list[str], category_id: str | None) -> int:
        return int(self._rpc("set_artists_category", artist_ids=artist_ids,
                             category_id=category_id) or 0)

    def browse_by_category(self, category_id: str, page=None) -> Page[SongView]:
        r = self._rpc("browse_by_category", category_id=category_id,
                      page=page.model_dump(mode="json") if page else None)
        return Page[SongView].model_validate(r)

    def browse_by_categories(self, category_ids: list[str], page=None) -> Page[SongView]:
        r = self._rpc("browse_by_categories", category_ids=list(category_ids),
                      page=page.model_dump(mode="json") if page else None)
        return Page[SongView].model_validate(r)

    def browse_by_artist(self, artist_id: str, page=None) -> Page[SongView]:
        r = self._rpc("browse_by_artist", artist_id=artist_id,
                      page=page.model_dump(mode="json") if page else None)
        return Page[SongView].model_validate(r)

    def dedupe_library(self) -> int:
        return int(self._rpc("dedupe_library") or 0)

    def merge_selected_duplicates(self, song_ids: list[str]) -> int:
        return int(self._rpc("merge_selected_duplicates", song_ids=song_ids) or 0)

    def explode_versions(self) -> int:
        return int(self._rpc("explode_versions") or 0)

    def clean_titles(self) -> int:
        return int(self._rpc("clean_titles") or 0)

    def strip_emoji_titles(self) -> int:
        return int(self._rpc("strip_emoji_titles") or 0)

    def extract_artists_from_titles(self) -> int:
        return int(self._rpc("extract_artists_from_titles") or 0)

    def extract_artists_from_youtube(self) -> int:
        return int(self._rpc("extract_artists_from_youtube") or 0)

    def set_artist_bulk(self, song_ids: list[str], artist: str) -> int:
        return int(self._rpc("set_artist_bulk", song_ids=song_ids, artist=artist) or 0)

    def suspect_originals(self) -> list[SongView]:
        return [SongView.model_validate(x) for x in (self._rpc("suspect_originals") or [])]

    def mark_karaoke(self, song_ids: list[str]) -> int:
        return int(self._rpc("mark_karaoke", song_ids=song_ids) or 0)

    def duplicate_groups(self) -> list[list[SongView]]:
        r = self._rpc("duplicate_groups") or []
        return [[SongView.model_validate(s) for s in grp] for grp in r]

    def merge_songs(self, song_ids: list[str]) -> str:
        return str(self._rpc("merge_songs", song_ids=song_ids) or "")

    def resolve_media_source(self, media_file_id: str) -> MediaSourceDTO | None:
        r = self._rpc("resolve_media_source", media_file_id=media_file_id)
        if not r:
            return None
        dto = MediaSourceDTO.model_validate(r)
        # Daemon REMOTO (LAN): o caminho local dele não existe nesta máquina → toca via
        # streaming HTTP (o mpv abre URL direto). Local segue com o arquivo do disco.
        from urllib.parse import urlparse
        host = urlparse(self.base).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1", ""):
            return MediaSourceDTO(media_file_id=media_file_id,
                                  uri=f"{self.base}/media/{media_file_id}", is_local=False)
        return dto

    def get_preset(self, song_id, user_id=None) -> PresetDTO | None:
        r = self._rpc("get_preset", song_id=song_id, user_id=user_id)
        return PresetDTO.model_validate(r) if r else None

    def save_preset(self, song_id, preset: PresetDTO, user_id=None) -> None:
        self._rpc("save_preset", song_id=song_id, preset=preset.model_dump(mode="json"), user_id=user_id)

    # ---- fila ----
    def open_session(self, name: str = "Sessão") -> str:
        return self._rpc("open_session", name=name)

    def enqueue(self, session_id: str, dto: EnqueueDTO) -> QueueItemView:
        return QueueItemView.model_validate(
            self._rpc("enqueue", session_id=session_id, dto=dto.model_dump(mode="json"))
        )

    def queue_list(self, session_id: str) -> list[QueueItemView]:
        return [QueueItemView.model_validate(x) for x in self._rpc("queue_list", session_id=session_id)]

    def reorder_queue(self, session_id, item_id, new_index) -> None:
        self._rpc("reorder_queue", session_id=session_id, item_id=item_id, new_index=new_index)

    def set_queue_status(self, item_id, status: QueueStatus) -> None:
        self._rpc("set_queue_status", item_id=item_id, status=status.value)

    def remove_queue_item(self, item_id) -> None:
        self._rpc("remove_queue_item", item_id=item_id)

    def advance_queue(self, session_id) -> QueueItemView | None:
        r = self._rpc("advance_queue", session_id=session_id)
        return QueueItemView.model_validate(r) if r else None

    def current_queue_item(self, session_id) -> QueueItemView | None:
        r = self._rpc("current_queue_item", session_id=session_id)
        return QueueItemView.model_validate(r) if r else None

    # --- sessão de convidado + pedidos (Fase D) ---
    def open_guest_session(self, name: str = "Pedidos") -> dict:
        return self._rpc("open_guest_session", name=name)

    def session_by_code(self, code: str) -> str | None:
        return self._rpc("session_by_code", code=code)

    def request_song(self, session_id: str, song_id: str, singer: str,
                    note: str = "", device: str = "") -> SongRequestView:
        return SongRequestView.model_validate(self._rpc(
            "request_song", session_id=session_id, song_id=song_id,
            singer=singer, note=note, device=device))

    def list_requests(self, session_id: str,
                     status: str = "pending") -> list[SongRequestView]:
        return [SongRequestView.model_validate(x)
                for x in self._rpc("list_requests", session_id=session_id, status=status)]

    def approve_request(self, request_id: str) -> QueueItemView:
        return QueueItemView.model_validate(self._rpc("approve_request", request_id=request_id))

    def reject_request(self, request_id: str) -> None:
        self._rpc("reject_request", request_id=request_id)

    # ---- playlists / favoritos / histórico / manutenção ----
    def create_playlist(self, name) -> str: return self._rpc("create_playlist", name=name)
    def delete_playlist(self, playlist_id) -> None: self._rpc("delete_playlist", playlist_id=playlist_id)
    def list_playlists(self) -> list[PlaylistView]:
        return [PlaylistView.model_validate(x) for x in self._rpc("list_playlists")]
    def playlist_items(self, playlist_id) -> list[PlaylistItemView]:
        return [PlaylistItemView.model_validate(x) for x in self._rpc("playlist_items", playlist_id=playlist_id)]
    def add_to_playlist(self, playlist_id, song_id) -> str:
        return self._rpc("add_to_playlist", playlist_id=playlist_id, song_id=song_id)
    def remove_playlist_item(self, item_id) -> None: self._rpc("remove_playlist_item", item_id=item_id)
    def enqueue_playlist(self, session_id, playlist_id, singer) -> int:
        return self._rpc("enqueue_playlist", session_id=session_id, playlist_id=playlist_id, singer=singer)
    def add_favorite(self, song_id, user_id=None) -> None: self._rpc("add_favorite", song_id=song_id, user_id=user_id)
    def remove_favorite(self, song_id, user_id=None) -> None: self._rpc("remove_favorite", song_id=song_id, user_id=user_id)
    def is_favorite(self, song_id, user_id=None) -> bool: return bool(self._rpc("is_favorite", song_id=song_id, user_id=user_id))
    def list_favorites(self, user_id=None) -> list[SongView]:
        return [SongView.model_validate(x) for x in self._rpc("list_favorites", user_id=user_id)]
    def list_history(self, limit=100) -> list[HistoryEntryView]:
        return [HistoryEntryView.model_validate(x) for x in self._rpc("list_history", limit=limit)]
    def get_lyrics(self, song_id) -> LyricsView | None:
        r = self._rpc("get_lyrics", song_id=song_id)
        return LyricsView.model_validate(r) if r else None
    def set_lyrics(self, song_id, content, fmt="text", language=None, source="manual") -> None:
        self._rpc("set_lyrics", song_id=song_id, content=content, fmt=fmt, language=language, source=source)
    def mark_missing_media(self) -> int: return int(self._rpc("mark_missing_media"))

    # ---- eventos via SSE ----
    def subscribe(self, event_name: str, handler: Handler) -> Subscription:
        self._handlers[event_name].append(handler)
        self._ensure_sse()
        return Subscription(lambda: self._handlers[event_name].remove(handler))

    def _ensure_sse(self) -> None:
        if self._sse_thread and self._sse_thread.is_alive():
            return
        self._sse_stop.clear()
        self._sse_thread = threading.Thread(target=self._sse_loop, daemon=True)
        self._sse_thread.start()

    def _sse_loop(self) -> None:
        try:
            with urllib.request.urlopen(f"{self.base}/events", timeout=None) as resp:
                for raw in resp:
                    if self._sse_stop.is_set():
                        return
                    line = raw.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip())
                    event = SimpleNamespace(**data)
                    for h in list(self._handlers.get(getattr(event, "name", ""), ())):
                        try:
                            h(event)
                        except Exception:  # noqa: BLE001
                            pass
        except Exception:  # noqa: BLE001
            pass  # daemon indisponível: apps degradam sem eventos

    def close(self) -> None:
        self._sse_stop.set()
