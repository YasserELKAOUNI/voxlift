# src/voxlift/downloader.py
"""
YouTube downloader module using yt-dlp.

Key features:
- Audio-only download for transcription efficiency
- Range download support (--download-sections) for partial transcription
- Progress hooks for real-time UI updates
- Automatic retry on failure
"""

import os
from typing import Dict, Any, Optional, Tuple, Callable
from yt_dlp import YoutubeDL, DownloadError
from .logging_manager import log_event

DEFAULT_MAX_RETRIES = 3


def download_video(
    url: str,
    output_path: str,
    config: Dict[str, Any],
    ytdl_opts: Optional[Dict[str, Any]] = None,
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Download a YouTube video via yt-dlp.

    Args:
        url: YouTube video URL
        output_path: Directory to save the file
        config: Configuration dict (download_format, max_retries, etc.)
        ytdl_opts: Additional yt-dlp options
        progress_hook: Callback for download progress
        start_time: Optional start time in seconds for range download
        end_time: Optional end time in seconds for range download

    Returns:
        Tuple of (absolute file path, video info dict)
    """
    # Prefer audio-only by default for transcription
    fmt = config.get("download_format", "bestaudio[ext=m4a]/bestaudio/best")
    retries = config.get("max_retries", DEFAULT_MAX_RETRIES)
    os.makedirs(output_path, exist_ok=True)

    # Organize singles by uploader
    template = os.path.join(output_path, "%(uploader)s", "%(title)s [%(id)s].%(ext)s")

    opts: Dict[str, Any] = {
        "format": fmt,
        "outtmpl": template,
        "noplaylist": True,
        "retries": retries,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "nopart": True,
        "overwrites": False,
    }

    # Add range download if specified
    # This is a HUGE optimization - downloads only the needed section!
    if start_time is not None:
        # yt-dlp expects {"start_time": float, "end_time": Optional[float]} dicts
        _start = start_time
        # yt-dlp formats the end_time with {:.1f}; None explodes. Use +inf as sentinel.
        _end = end_time if end_time is not None else float("inf")
        opts["download_ranges"] = lambda info_dict, ydl, s=_start, e=_end: [{
            "start_time": s,
            "end_time": e,
        }]
        opts["force_keyframes_at_cuts"] = True

        log_event("downloader", "range_download",
                  "Downloading section",
                  level="INFO",
                  data={"start": start_time, "end": end_time})

    if ytdl_opts:
        opts.update(ytdl_opts)

    if progress_hook:
        hooks = opts.get("progress_hooks", [])
        hooks = list(hooks) + [progress_hook]
        opts["progress_hooks"] = hooks

    log_event(
        "downloader",
        "download_start",
        "Starting download",
        level="INFO",
        data={
            "url": url,
            "format": fmt,
            "retries": retries,
            "start": start_time,
            "end": end_time,
        },
    )

    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                log_event(
                    "downloader",
                    "download_success",
                    "Download complete",
                    level="INFO",
                    data={
                        "file": filename,
                        "video_id": info.get("id"),
                        "title": info.get("title"),
                        "start": start_time,
                        "end": end_time,
                    },
                )
                return os.path.abspath(filename), info
        except DownloadError as e:
            last_exc = e
            log_event(
                "downloader",
                "download_error",
                f"Attempt {attempt}/{retries} failed",
                level="WARNING",
                data={"attempt": attempt, "url": url, "error": str(e)},
            )

    # All attempts failed
    msg = f"Download failed after {retries} attempts"
    log_event(
        "downloader",
        "download_fail",
        msg,
        level="ERROR",
        data={"attempts": retries, "url": url},
    )
    raise last_exc or RuntimeError(msg)


def download_range(
    url: str,
    output_path: str,
    config: Dict[str, Any],
    start_time: float,
    end_time: Optional[float] = None,
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Download only a specific time range from a YouTube video.

    This is much more efficient than downloading the full video
    when you only need a portion.

    Args:
        url: YouTube video URL
        output_path: Directory to save the file
        config: Configuration dict
        start_time: Start time in seconds
        end_time: End time in seconds (None = until end)
        progress_hook: Callback for download progress

    Returns:
        Tuple of (absolute file path, video info dict)
    """
    return download_video(
        url=url,
        output_path=output_path,
        config=config,
        progress_hook=progress_hook,
        start_time=start_time,
        end_time=end_time,
    )


def download_playlist(
    playlist_url: str,
    output_path: str,
    config: Dict[str, Any]
) -> Dict[str, str]:
    """
    Download a YouTube playlist (up to config['max_playlist_items']).

    Returns:
        Dict mapping video URLs to downloaded file paths
    """
    max_items = config.get("max_playlist_items", 25)
    os.makedirs(output_path, exist_ok=True)

    opts = {
        "format": config.get("download_format", "bestaudio[ext=m4a]/bestaudio/best"),
        "outtmpl": os.path.join(output_path, "%(playlist_title)s", "%(title)s [%(id)s].%(ext)s"),
        "noplaylist": False,
        "playlistend": max_items,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "nopart": True,
        "overwrites": False,
    }

    log_event(
        "downloader",
        "playlist_start",
        "Starting playlist download",
        level="INFO",
        data={"playlist_url": playlist_url, "max_items": max_items},
    )

    result: Dict[str, str] = {}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        entries = info.get("entries") or []
        for entry in entries[:max_items]:
            video_url = entry.get("webpage_url")
            try:
                file_path, _ = download_video(video_url, output_path, config, ytdl_opts=opts)
                result[video_url] = file_path
            except Exception as e:
                log_event(
                    "downloader",
                    "playlist_item_error",
                    "Playlist item failed",
                    level="ERROR",
                    data={"url": video_url, "error": str(e)},
                )

    log_event(
        "downloader",
        "playlist_end",
        "Playlist download finished",
        level="INFO",
        data={
            "downloaded": len(result),
            "considered": min(len(entries), max_items),
            "playlist_url": playlist_url,
        },
    )
    return result
