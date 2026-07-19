#!/usr/bin/env python3
"""Download a YouTube video as an MP4 and file it into a notes directory.

This intentionally wraps the exact operational workflow used for local video
archiving: inspect formats, prefer a native MP4 stream at the requested height,
merge with AAC audio, and transcode from the next higher MP4 stream when the
requested height is not offered by YouTube.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


DEFAULT_NOTES_DIR = "~/Documents/5_Notes"
DEFAULT_DOWNLOADS_DIR = "downloads"
DEFAULT_FFMPEG_LOCATION = "/opt/homebrew/bin"


def _run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    printable = " ".join(_quote(part) for part in cmd)
    print(f"+ {printable}", file=sys.stderr)
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=None,
    )


def _quote(value: str) -> str:
    if not value or any(ch.isspace() or ch in "'\"[]()&;|" for ch in value):
        return "'" + value.replace("'", "'\"'\"'") + "'"
    return value


def resolve_yt_dlp(explicit: str | None, repo_root: Path) -> str:
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.append(str(repo_root / ".venv" / "bin" / "yt-dlp"))
    found = shutil.which("yt-dlp")
    if found:
        candidates.append(found)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
        if shutil.which(candidate):
            return candidate

    raise FileNotFoundError("yt-dlp not found. Install it or pass --yt-dlp PATH.")


def resolve_tool(name: str, location: str) -> str:
    direct = Path(location).expanduser() / name
    if direct.exists() and os.access(direct, os.X_OK):
        return str(direct)

    found = shutil.which(name)
    if found:
        return found

    raise FileNotFoundError(f"{name} not found. Install it or pass --ffmpeg-location DIR.")


def fetch_metadata(yt_dlp: str, url: str) -> dict[str, Any]:
    result = _run([yt_dlp, "-J", "--no-playlist", url], capture=True)
    return json.loads(result.stdout)


def _is_video_only(fmt: dict[str, Any]) -> bool:
    return fmt.get("vcodec") not in (None, "none") and fmt.get("acodec") in (None, "none")


def _is_audio_only(fmt: dict[str, Any]) -> bool:
    return fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none")


def _is_h264(fmt: dict[str, Any]) -> bool:
    return str(fmt.get("vcodec", "")).startswith("avc")


def _bitrate(fmt: dict[str, Any]) -> float:
    value = fmt.get("tbr") or fmt.get("vbr") or fmt.get("abr") or 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def select_video_format(formats: Iterable[dict[str, Any]], height: int) -> tuple[str, bool, int]:
    """Return (format_id, needs_transcode, source_height)."""
    mp4_video = [
        fmt
        for fmt in formats
        if _is_video_only(fmt)
        and fmt.get("ext") == "mp4"
        and isinstance(fmt.get("height"), int)
        and fmt.get("format_id")
    ]
    if not mp4_video:
        raise ValueError("No MP4 video-only format is available for this URL.")

    def native_key(fmt: dict[str, Any]) -> tuple[int, float]:
        return (1 if _is_h264(fmt) else 0, _bitrate(fmt))

    exact = [fmt for fmt in mp4_video if fmt["height"] == height]
    if exact:
        chosen = max(exact, key=native_key)
        return str(chosen["format_id"]), False, int(chosen["height"])

    higher = [fmt for fmt in mp4_video if fmt["height"] > height]
    if higher:
        source_height = min(int(fmt["height"]) for fmt in higher)
        candidates = [fmt for fmt in higher if int(fmt["height"]) == source_height]
        chosen = max(candidates, key=native_key)
        return str(chosen["format_id"]), True, int(chosen["height"])

    lower = sorted(mp4_video, key=lambda fmt: int(fmt["height"]), reverse=True)
    chosen = max(
        [fmt for fmt in lower if int(fmt["height"]) == int(lower[0]["height"])],
        key=native_key,
    )
    return str(chosen["format_id"]), True, int(chosen["height"])


def select_audio_format(formats: Iterable[dict[str, Any]]) -> str:
    audio = [
        fmt
        for fmt in formats
        if _is_audio_only(fmt)
        and fmt.get("ext") == "m4a"
        and fmt.get("format_id")
    ]
    if not audio:
        raise ValueError("No M4A audio-only format is available for this URL.")

    for fmt in audio:
        if str(fmt.get("format_id")) == "140":
            return "140"

    return str(max(audio, key=_bitrate)["format_id"])


def find_downloaded_file(downloads_dir: Path, video_id: str, suffix: str) -> Path:
    marker = f"[{video_id}]{suffix}"
    matches = sorted(path for path in downloads_dir.rglob(f"*{suffix}") if marker in path.name)
    if not matches:
        raise FileNotFoundError(f"Could not find downloaded file for {video_id} with suffix {suffix}")
    return matches[-1]


def ffprobe_summary(ffprobe: str, path: Path) -> str:
    probes = [
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name,avg_frame_rate", "-of", "default=noprint_wrappers=1:nokey=0", str(path)],
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,channels,sample_rate", "-of", "default=noprint_wrappers=1:nokey=0", str(path)],
        [ffprobe, "-v", "error", "-show_entries", "format=duration,size", "-of", "default=noprint_wrappers=1:nokey=0", str(path)],
    ]
    return "\n".join(_run(cmd, capture=True).stdout.strip() for cmd in probes)


def move_to_notes(path: Path, notes_dir: Path, *, force: bool) -> Path:
    uploader = path.parent.name
    destination_dir = notes_dir / uploader
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name

    if destination.exists():
        if not force:
            raise FileExistsError(f"Destination already exists: {destination}")
        destination.unlink()

    shutil.move(str(path), str(destination))
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return destination


def download_video(args: argparse.Namespace) -> Path:
    default_repo_root = Path(__file__).resolve().parents[1]
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else default_repo_root
    downloads_dir = (repo_root / args.downloads_dir).resolve()
    notes_dir = Path(args.notes_dir).expanduser().resolve()
    yt_dlp = resolve_yt_dlp(args.yt_dlp, repo_root)
    ffmpeg = resolve_tool("ffmpeg", args.ffmpeg_location)
    ffprobe = resolve_tool("ffprobe", args.ffmpeg_location)

    metadata = fetch_metadata(yt_dlp, args.url)
    video_id = metadata["id"]
    formats = metadata.get("formats") or []
    video_format, needs_transcode, source_height = select_video_format(formats, args.quality)
    audio_format = select_audio_format(formats)
    merged_format = f"{video_format}+{audio_format}"

    print(
        f"Selected video={video_format} ({source_height}p), audio={audio_format}, "
        f"target={args.quality}p, transcode={needs_transcode}",
        file=sys.stderr,
    )

    output_suffix = ".source.%(ext)s" if needs_transcode else ".%(ext)s"
    output_template = str(downloads_dir / "%(uploader)s" / f"%(title)s [%(id)s]{output_suffix}")
    _run(
        [
            yt_dlp,
            "--ffmpeg-location",
            args.ffmpeg_location,
            "--no-playlist",
            "-f",
            merged_format,
            "--merge-output-format",
            "mp4",
            "-o",
            output_template,
            args.url,
        ]
    )

    if needs_transcode:
        source = find_downloaded_file(downloads_dir, video_id, ".source.mp4")
        final = source.with_name(source.name.replace(".source.mp4", ".mp4"))
        _run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vf",
                f"scale=-2:{args.quality}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(args.crf),
                "-c:a",
                "copy",
                str(final),
            ]
        )
        if not args.keep_source:
            source.unlink()
    else:
        final = find_downloaded_file(downloads_dir, video_id, ".mp4")

    summary = ffprobe_summary(ffprobe, final)
    destination = move_to_notes(final, notes_dir, force=args.force)

    print(summary)
    print(f"Stored: {destination}")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a YouTube video as MP4 and store it under ~/Documents/5_Notes/<Uploader>/."
    )
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--quality", type=int, default=480, help="Target video height. Default: 480")
    parser.add_argument("--notes-dir", default=DEFAULT_NOTES_DIR, help=f"Destination notes directory. Default: {DEFAULT_NOTES_DIR}")
    parser.add_argument("--downloads-dir", default=DEFAULT_DOWNLOADS_DIR, help="Temporary downloads directory under repo root")
    parser.add_argument("--repo-root", default=None, help="Repository root. Default: inferred from this script")
    parser.add_argument("--yt-dlp", default=None, help="Path to yt-dlp. Defaults to .venv/bin/yt-dlp, then PATH")
    parser.add_argument("--ffmpeg-location", default=DEFAULT_FFMPEG_LOCATION, help="Directory containing ffmpeg and ffprobe")
    parser.add_argument("--crf", type=int, default=23, help="x264 CRF used when transcoding. Default: 23")
    parser.add_argument("--keep-source", action="store_true", help="Keep the higher-resolution source when transcoding")
    parser.add_argument("--force", action="store_true", help="Replace an existing destination file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        download_video(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
