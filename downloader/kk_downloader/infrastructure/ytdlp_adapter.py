"""Backend yt-dlp — porta o aprendizado do protótipo: cliente `android`
primeiro (baixa o progressivo sem 403), fallback de clientes e cookies.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .ports import DownloadedMedia, IDownloaderBackend, ProgressCb, SearchHit

PLAYER_CLIENTS = [["android"], ["ios"], ["tv"], ["web_safari"], None]
_RETRYABLE = ("page needs to be reloaded", "403", "forbidden",
              "requested format is not available", "unable to download")


def _ffmpeg_location() -> str | None:
    try:
        import imageio_ffmpeg
        return str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
    except Exception:
        return None


def _retryable(exc: Exception) -> bool:
    m = str(exc).lower()
    return any(k in m for k in _RETRYABLE)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _with_client(opts: dict, client) -> dict:
    out = dict(opts)
    if client is not None:
        out["extractor_args"] = {"youtube": {"player_client": client}}
    return out


def _cookies(opts: dict, browser: str) -> dict:
    if browser:
        opts = dict(opts)
        opts["cookiesfrombrowser"] = (browser,)
    return opts


class YtDlpBackend(IDownloaderBackend):
    def search(self, query: str, limit: int, deep: bool, cookies: str = "") -> list[SearchHit]:
        import yt_dlp

        suffixes = ("karaokê", "videokê", "playback") if deep else ("karaokê",)
        base = _cookies(
            {"quiet": True, "no_warnings": True, "extract_flat": True}, cookies
        )
        seen: set[str] = set()
        hits: list[SearchHit] = []
        for suffix in suffixes:
            term = query if "karaok" in query.lower() else f"{query} {suffix}"
            info = None
            for client in PLAYER_CLIENTS:
                try:
                    with yt_dlp.YoutubeDL(_with_client(base, client)) as ydl:
                        info = ydl.extract_info(f"ytsearch{limit}:{term}", download=False)
                    break
                except Exception as exc:  # noqa: BLE001
                    if not _retryable(exc):
                        break
            for e in (info or {}).get("entries") or []:
                if not e:
                    continue
                vid = e.get("id") or e.get("url") or ""
                if vid in seen:
                    continue
                seen.add(vid)
                hits.append(SearchHit(
                    url=e.get("url") or e.get("webpage_url") or vid,
                    title=e.get("title", ""),
                    channel=e.get("channel") or e.get("uploader") or "",
                    channel_id=e.get("channel_id"),
                    duration_s=int(e.get("duration") or 0),
                ))
        return hits

    def playlist_entries(self, url: str, *, cookies: str = "", limit: int | None = None) -> list[tuple[str, str]]:
        """(url, título) de uma PLAYLIST/CANAL via extração FLAT (rápida, sem baixar).
        Usado pra gerar o manifesto que o usuário revisa antes de baixar."""
        import yt_dlp

        opts = _cookies({"quiet": True, "no_warnings": True, "skip_download": True,
                         "extract_flat": "in_playlist"}, cookies)
        if limit:
            opts["playlistend"] = int(limit)
        for client in PLAYER_CLIENTS:
            info = None
            try:
                with yt_dlp.YoutubeDL(_with_client(opts, client)) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as exc:  # noqa: BLE001
                if not _retryable(exc):
                    continue
            out: list[tuple[str, str]] = []
            for e in (info or {}).get("entries") or []:
                if not e:
                    continue
                vid = e.get("id")
                u = e.get("url") or e.get("webpage_url") or (
                    f"https://www.youtube.com/watch?v={vid}" if vid else None)
                if u:
                    out.append((u, e.get("title") or ""))
            if out:
                return out
        return []

    def video_info(self, url_or_id: str, *, cookies: str = "") -> SearchHit | None:
        """Metadados de UM vídeo (a partir da URL ou do ID) como SearchHit.
        Usado quando o usuário COLA a URL: traz só aquele vídeo, sem passar
        pela busca (nem pelos filtros de videokê/duração)."""
        import yt_dlp

        url = url_or_id
        if "://" not in url_or_id:
            url = f"https://www.youtube.com/watch?v={url_or_id}"
        base = _cookies({"quiet": True, "no_warnings": True, "skip_download": True,
                         "extract_flat": False}, cookies)
        for client in PLAYER_CLIENTS:
            try:
                with yt_dlp.YoutubeDL(_with_client(base, client)) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as exc:  # noqa: BLE001
                if not _retryable(exc):
                    continue
                info = None
            if not info:
                continue
            # URL de playlist → pega o 1º item
            if info.get("entries"):
                info = next((e for e in info["entries"] if e), None)
                if not info:
                    continue
            vid = info.get("id") or ""
            return SearchHit(
                url=info.get("webpage_url") or url,
                title=info.get("title", "") or "",
                channel=info.get("channel") or info.get("uploader") or "",
                channel_id=info.get("channel_id"),
                duration_s=int(info.get("duration") or 0),
            )
        return None

    def youtube_title(self, url_or_id: str, *, cookies: str = "") -> str | None:
        """Título canônico do vídeo no YouTube (a partir da URL ou do ID)."""
        import yt_dlp

        url = url_or_id
        if "://" not in url_or_id:
            url = f"https://www.youtube.com/watch?v={url_or_id}"
        base = _cookies({"quiet": True, "no_warnings": True, "skip_download": True,
                         "extract_flat": False}, cookies)
        for client in PLAYER_CLIENTS:
            try:
                with yt_dlp.YoutubeDL(_with_client(base, client)) as ydl:
                    info = ydl.extract_info(url, download=False)
                t = (info or {}).get("title")
                if t:
                    return t
            except Exception as exc:  # noqa: BLE001
                if not _retryable(exc):
                    continue
        return None

    def youtube_duration(self, url_or_id: str, *, cookies: str = "") -> int:
        """Duração (segundos) do vídeo no YouTube — 0 se não conseguir.
        Usado para detectar downloads incompletos (arquivo local << original)."""
        import yt_dlp

        url = url_or_id
        if "://" not in url_or_id:
            url = f"https://www.youtube.com/watch?v={url_or_id}"
        base = _cookies({"quiet": True, "no_warnings": True, "skip_download": True,
                         "extract_flat": False}, cookies)
        for client in PLAYER_CLIENTS:
            try:
                with yt_dlp.YoutubeDL(_with_client(base, client)) as ydl:
                    info = ydl.extract_info(url, download=False)
                d = int((info or {}).get("duration") or 0)
                if d:
                    return d
            except Exception as exc:  # noqa: BLE001
                if not _retryable(exc):
                    continue
        return 0

    def stream_url(self, url: str, *, max_height: int = 720, cookies: str = "") -> str:
        """Resolve uma URL de mídia tocável direto (prévia sem baixar).

        Prefere formato progressivo (áudio+vídeo juntos, ~360p do cliente android),
        que o mpv reproduz por HTTP sem precisar mesclar faixas."""
        import yt_dlp

        fmt = (f"best[height<={max_height}][acodec!=none][vcodec!=none]"
               f"/best[acodec!=none][vcodec!=none]/best")
        base = _cookies({"quiet": True, "no_warnings": True, "skip_download": True,
                         "format": fmt}, cookies)
        last: Exception | None = None
        for client in PLAYER_CLIENTS:
            try:
                with yt_dlp.YoutubeDL(_with_client(base, client)) as ydl:
                    info = ydl.extract_info(url, download=False)
                direct = info.get("url")
                if direct:
                    return direct
                fmts = [f for f in info.get("formats", []) if f.get("url")
                        and f.get("acodec") not in (None, "none")
                        and f.get("vcodec") not in (None, "none")]
                if fmts:
                    return fmts[-1]["url"]
            except Exception as exc:  # noqa: BLE001
                last = exc
                if not _retryable(exc):
                    continue
        raise RuntimeError(f"não consegui resolver o stream: {last}")

    def download(
        self, url: str, staging_dir: str, *, audio_only: bool = False, max_height: int = 720,
        cookies: str = "", progress: ProgressCb | None = None,
    ) -> DownloadedMedia:
        import yt_dlp

        outtmpl = str(Path(staging_dir) / "%(id)s.%(ext)s")
        fmt = "bestaudio/best" if audio_only else f"best[height<={max_height}]/best"
        pps = []
        if audio_only:
            pps.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3"})

        def hook(d):
            if progress and d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                progress((got / total * 100) if total else 0, d.get("_speed_str", ""))

        opts = _cookies({
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": fmt, "outtmpl": outtmpl, "postprocessors": pps,
            "progress_hooks": [hook], "retries": 5,
        }, cookies)
        ff = _ffmpeg_location()
        if ff:
            opts["ffmpeg_location"] = ff

        last: Exception | None = None
        for client in PLAYER_CLIENTS:
            try:
                with yt_dlp.YoutubeDL(_with_client(opts, client)) as ydl:
                    info = ydl.extract_info(url, download=True)
                reqs = info.get("requested_downloads") or []
                path = reqs[0]["filepath"] if reqs else ydl.prepare_filename(info)
                w, h = info.get("width"), info.get("height")
                return DownloadedMedia(
                    path=path, title=info.get("title", ""),
                    channel=info.get("channel") or info.get("uploader"),
                    channel_id=info.get("channel_id"),
                    duration_s=int(info.get("duration") or 0),
                    resolution=f"{w}x{h}" if w and h else None,
                    container=Path(path).suffix.lstrip("."),
                    video_codec=info.get("vcodec") if info.get("vcodec") != "none" else None,
                    audio_codec=info.get("acodec") if info.get("acodec") != "none" else None,
                    sha256=_sha256(path), source_url=info.get("webpage_url", url),
                )
            except Exception as exc:  # noqa: BLE001
                last = exc
                if not _retryable(exc):
                    raise
        raise last  # type: ignore[misc]
