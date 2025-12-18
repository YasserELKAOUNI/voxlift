# src/yww/audio_extractor.py
"""
Lightweight audio extraction for transcription.

Design principles:
1. Extract audio-only (smallest bandwidth)
2. Download to temp directory (auto-cleaned)
3. Use opus/webm format (~50% smaller than m4a)
4. Support time range extraction
5. Clean up after transcription completes

This replaces the heavy downloader.py for the transcription flow.
"""

import os
import tempfile
from typing import Any, Callable, Dict, Optional, Tuple

from yt_dlp import YoutubeDL, DownloadError

from .logging_manager import log_event, log_error


# Default format: opus in webm container (smallest for speech)
# Falls back to any best audio if webm not available
DEFAULT_AUDIO_FORMAT = "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio"

DEFAULT_MAX_RETRIES = 3


def extract_audio(
    url: str,
    temp_dir: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Tuple[str, Dict[str, Any]]:
    """
    Extract audio from YouTube URL to a temporary file.

    This is optimized for transcription:
    - Downloads audio-only (no video)
    - Uses smallest viable format (opus/webm preferred)
    - Saves to temp directory for automatic cleanup
    - Supports time range extraction for partial transcription

    Args:
        url: YouTube video URL
        temp_dir: Directory for temp files (default: system temp)
        start_time: Optional start time in seconds for range extraction
        end_time: Optional end time in seconds for range extraction
        progress_hook: Callback for download progress updates
        max_retries: Number of retry attempts on failure

    Returns:
        Tuple of (temp_file_path, video_info_dict)

    Raises:
        DownloadError: If download fails after all retries
    """
    # Use provided temp dir or system temp
    if temp_dir:
        os.makedirs(temp_dir, exist_ok=True)
        work_dir = temp_dir
    else:
        work_dir = tempfile.gettempdir()

    # Template: simple filename in temp dir
    # Using video ID to avoid conflicts and enable caching
    template = os.path.join(work_dir, "yww_%(id)s.%(ext)s")

    opts: Dict[str, Any] = {
        "format": DEFAULT_AUDIO_FORMAT,
        "outtmpl": template,
        "noplaylist": True,
        "retries": max_retries,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        # Don't keep partial files on failure
        "nopart": True,
        # Overwrite if exists (temp file from previous failed attempt)
        "overwrites": True,
    }

    # Time range extraction - downloads only the needed section
    # This is a MAJOR bandwidth optimization for long videos
    if start_time is not None:
        _start, _end = start_time, end_time

        # yt-dlp download_ranges expects list of dicts with start_time/end_time keys
        def make_ranges(info_dict, ydl, s=_start, e=_end):
            return [{"start_time": s, "end_time": e}]

        opts["download_ranges"] = make_ranges
        opts["force_keyframes_at_cuts"] = True

        log_event(
            "audio_extractor",
            "range_extraction",
            "Extracting audio range",
            level="INFO",
            data={"start": start_time, "end": end_time, "url": url},
        )

    # Add progress hook if provided
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    log_event(
        "audio_extractor",
        "extract_start",
        "Starting audio extraction",
        level="INFO",
        data={
            "url": url,
            "format": DEFAULT_AUDIO_FORMAT,
            "temp_dir": work_dir,
            "start_time": start_time,
            "end_time": end_time,
        },
    )

    last_exc: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)

                # Verify file exists
                if not os.path.isfile(filename):
                    raise FileNotFoundError(f"Expected file not found: {filename}")

                file_size = os.path.getsize(filename)

                log_event(
                    "audio_extractor",
                    "extract_complete",
                    "Audio extraction complete",
                    level="INFO",
                    data={
                        "file": filename,
                        "size_bytes": file_size,
                        "size_mb": round(file_size / (1024 * 1024), 2),
                        "video_id": info.get("id"),
                        "title": info.get("title"),
                        "duration": info.get("duration"),
                    },
                )

                return os.path.abspath(filename), info

        except DownloadError as e:
            last_exc = e
            log_event(
                "audio_extractor",
                "extract_retry",
                f"Attempt {attempt}/{max_retries} failed",
                level="WARNING",
                data={"url": url, "error": str(e), "attempt": attempt},
            )

    # All attempts failed
    log_error(
        "audio_extractor",
        "extract_failed",
        f"Audio extraction failed after {max_retries} attempts",
        exc=last_exc,
        data={"url": url},
    )
    raise last_exc or RuntimeError(f"Failed to extract audio from {url}")


def cleanup_temp_file(file_path: str) -> bool:
    """
    Remove a temporary audio file after transcription.

    Args:
        file_path: Path to the temp file to delete

    Returns:
        True if file was deleted, False if it didn't exist or failed
    """
    if not file_path:
        return False

    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
            log_event(
                "audio_extractor",
                "cleanup_complete",
                "Temp file cleaned up",
                level="DEBUG",
                data={"file": file_path},
            )
            return True
        return False
    except OSError as e:
        log_event(
            "audio_extractor",
            "cleanup_failed",
            "Failed to clean up temp file",
            level="WARNING",
            data={"file": file_path, "error": str(e)},
        )
        return False


def get_video_info(url: str) -> Dict[str, Any]:
    """
    Get video metadata without downloading.

    Useful for:
    - Validating URL before processing
    - Getting duration for time estimates
    - Displaying video info in UI

    Args:
        url: YouTube video URL

    Returns:
        Video info dictionary from yt-dlp
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    log_event(
        "audio_extractor",
        "info_fetched",
        "Video info retrieved",
        level="DEBUG",
        data={
            "video_id": info.get("id"),
            "title": info.get("title"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
        },
    )

    return info
