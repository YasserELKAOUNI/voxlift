# src/yww/storage.py
"""
Storage module for YWW transcripts.

Design principles:
1. Transcripts are the primary artifact (not media files)
2. Index stores full text for search capability
3. Deduplicate by video_id (upsert, not append)
4. Schema versioned for future migrations
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logging_manager import log_event

# Index schema version - increment when schema changes
INDEX_VERSION = 2

# Default paths (relative to project root)
DEFAULT_TRANSCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "transcripts")
)
DEFAULT_INDEX_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "transcripts_index.json")
)

# Legacy index for backward compatibility
LEGACY_INDEX_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "downloads_index.json")
)


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """
    Sanitize a filename for macOS: remove or replace forbidden characters,
    normalize whitespace, and cap length to avoid filesystem limits.
    """
    invalid = '\\/:*?"<>|\n\r\t'
    sanitized = ''.join('_' if ch in invalid else ch for ch in name)
    sanitized = ' '.join(sanitized.split())
    sanitized = sanitized.strip(' .')
    if len(sanitized) > max_length:
        root, ext = os.path.splitext(sanitized)
        keep = max_length - len(ext) - 3
        sanitized = root[:max(1, keep)] + '...' + ext
    return sanitized or "untitled"


def _load_index(index_file: str = DEFAULT_INDEX_FILE) -> Dict[str, Any]:
    """
    Load index from file, handling both v1 (array) and v2 (object) formats.
    Returns v2 format structure.
    """
    if not os.path.isfile(index_file):
        return {"version": INDEX_VERSION, "transcripts": {}}

    try:
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": INDEX_VERSION, "transcripts": {}}

    # Handle v1 format (array) - migrate to v2
    if isinstance(data, list):
        transcripts = {}
        for record in data:
            video_id = record.get("id")
            if video_id:
                transcripts[video_id] = record
        return {"version": INDEX_VERSION, "transcripts": transcripts}

    # Already v2 format
    if isinstance(data, dict) and "version" in data:
        return data

    # Unknown format, start fresh
    return {"version": INDEX_VERSION, "transcripts": {}}


def _save_index(index_data: Dict[str, Any], index_file: str = DEFAULT_INDEX_FILE) -> None:
    """Save index to file with atomic write."""
    os.makedirs(os.path.dirname(index_file), exist_ok=True)

    # Write to temp file first, then rename (atomic)
    temp_file = index_file + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)

    os.replace(temp_file, index_file)


def save_transcript(
    video_id: str,
    text: str,
    segments: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    output_format: str = "srt",
    transcripts_dir: str = DEFAULT_TRANSCRIPTS_DIR,
    index_file: str = DEFAULT_INDEX_FILE,
) -> str:
    """
    Save transcript file and update index with full text.

    This is the main storage function for the transcription pipeline.
    - Saves transcript file organized by uploader
    - Stores full text in index for search
    - Deduplicates by video_id (upserts existing entries)

    Args:
        video_id: YouTube video ID (unique key)
        text: Full transcript text
        segments: List of segment dicts with start/end/text
        metadata: Video metadata (title, uploader, duration, url, etc.)
        output_format: Output format (srt, txt, vtt)
        transcripts_dir: Base directory for transcript files
        index_file: Path to index JSON file

    Returns:
        Absolute path to saved transcript file
    """
    # Create directory structure: transcripts/{uploader}/
    uploader = sanitize_filename(metadata.get("uploader", "Unknown"))
    output_dir = os.path.join(transcripts_dir, uploader)
    os.makedirs(output_dir, exist_ok=True)

    # Generate filename
    title = sanitize_filename(metadata.get("title", "untitled"))
    filename = f"{title} [{video_id}].{output_format}"
    filepath = os.path.join(output_dir, filename)

    # Write transcript file
    if output_format == "txt":
        content = text
    elif output_format == "srt":
        content = _segments_to_srt(segments)
    elif output_format == "vtt":
        content = _segments_to_vtt(segments)
    else:
        content = text

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    log_event(
        "storage",
        "transcript_saved",
        "Transcript file saved",
        level="INFO",
        data={"path": filepath, "format": output_format, "video_id": video_id},
    )

    # Update index with full text (for search)
    now = datetime.utcnow().isoformat() + "Z"
    index_data = _load_index(index_file)

    # Check if updating existing entry
    is_update = video_id in index_data["transcripts"]

    index_data["transcripts"][video_id] = {
        "title": metadata.get("title"),
        "uploader": metadata.get("uploader"),
        "url": metadata.get("webpage_url") or metadata.get("url"),
        "duration": metadata.get("duration"),
        "transcript_file": filepath,
        "text": text,
        "segments": segments,
        "language": metadata.get("language", "auto"),
        "model": metadata.get("model"),
        "format": output_format,
        "created_at": index_data["transcripts"].get(video_id, {}).get("created_at", now),
        "updated_at": now,
    }

    _save_index(index_data, index_file)

    log_event(
        "storage",
        "index_updated",
        "Index updated" if not is_update else "Index entry updated (deduplicated)",
        level="INFO",
        data={
            "video_id": video_id,
            "total_entries": len(index_data["transcripts"]),
            "is_update": is_update,
        },
    )

    return os.path.abspath(filepath)


def get_transcript(video_id: str, index_file: str = DEFAULT_INDEX_FILE) -> Optional[Dict[str, Any]]:
    """
    Get transcript entry by video ID.

    Args:
        video_id: YouTube video ID

    Returns:
        Transcript entry dict or None if not found
    """
    index_data = _load_index(index_file)
    return index_data["transcripts"].get(video_id)


def search_transcripts(
    query: str,
    index_file: str = DEFAULT_INDEX_FILE,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Search transcripts by text content.

    Simple substring search - can be enhanced with better search later.

    Args:
        query: Search query string
        index_file: Path to index file
        limit: Maximum results to return

    Returns:
        List of matching transcript entries
    """
    query_lower = query.lower()
    index_data = _load_index(index_file)

    results = []
    for video_id, entry in index_data["transcripts"].items():
        # Search in title, uploader, and text
        searchable = " ".join([
            entry.get("title", ""),
            entry.get("uploader", ""),
            entry.get("text", ""),
        ]).lower()

        if query_lower in searchable:
            results.append({"video_id": video_id, **entry})
            if len(results) >= limit:
                break

    return results


def list_transcripts(
    index_file: str = DEFAULT_INDEX_FILE,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    List all transcripts, sorted by most recent first.

    Args:
        index_file: Path to index file
        limit: Maximum results to return

    Returns:
        List of transcript entries with video_id included
    """
    index_data = _load_index(index_file)

    entries = [
        {"video_id": vid, **entry}
        for vid, entry in index_data["transcripts"].items()
    ]

    # Sort by updated_at descending
    entries.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    return entries[:limit]


def _segments_to_srt(segments: List[Dict[str, Any]]) -> str:
    """Convert segments to SRT subtitle format."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg.get("start", 0))
        end = _format_srt_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _segments_to_vtt(segments: List[Dict[str, Any]]) -> str:
    """Convert segments to WebVTT subtitle format."""
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = _format_vtt_time(seg.get("start", 0))
        end = _format_vtt_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as WebVTT timestamp (HH:MM:SS.mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


# Legacy compatibility functions

def update_index(record: Dict[str, Any], index_file: str = LEGACY_INDEX_FILE) -> None:
    """
    Legacy function: Append a record to old-style index.
    Kept for backward compatibility with existing code.
    """
    if os.path.isfile(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
    else:
        data = []

    data.append(record)

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log_event(
        "storage",
        "index_updated",
        "Legacy index updated",
        level="INFO",
        data={"index_file": index_file, "records": len(data)},
    )
