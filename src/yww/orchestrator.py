import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from .downloader import download_video
from .logging_manager import init_logger, log_event
from .storage import update_index
from .transcriber import transcribe_audio
from .media import extract_segment, parse_timecode


def _emit_json(event: str, payload: Dict[str, Any]) -> None:
    obj = {"event": event, **payload}
    print(json.dumps(obj, ensure_ascii=False))


def process_url(
    url: str,
    output_dir: str,
    config: Dict[str, Any],
    *,
    force: bool = False,
    json_events: bool = False,
    event_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    End-to-end: download audio-only, transcribe to TXT, update index.
    Idempotent: if transcript exists and not force, skip transcription.

    Args:
        start_time: Optional start timestamp (e.g., "1:30" or "90") for partial transcription
        end_time: Optional end timestamp for partial transcription

    Returns a dict with useful paths and metadata.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Init logging once (safe to call multiple times)
    init_logger(level=config.get("logging_level", "INFO"))

    archive = os.path.join(output_dir, ".ytdl-archive.txt")

    def progress_hook(status: Dict[str, Any]) -> None:
        ev = {
            "status": status.get("status"),
            "downloaded_bytes": status.get("downloaded_bytes"),
            "total_bytes": status.get("total_bytes") or status.get("total_bytes_estimate"),
            "speed": status.get("speed"),
            "eta": status.get("eta"),
            "tmpfilename": status.get("tmpfilename"),
            "filename": status.get("filename"),
        }
        if event_cb:
            try:
                event_cb("progress", ev)
            except Exception:
                pass
        if json_events:
            _emit_json("progress", ev)

    # Build yt-dlp options focused on audio-only and idempotency
    ytdl_opts = {
        "download_archive": archive,
        "progress_hooks": [progress_hook] if json_events else [],
    }

    if event_cb:
        try:
            event_cb("start", {"url": url, "output_dir": output_dir})
        except Exception:
            pass
    if json_events:
        _emit_json("start", {"url": url, "output_dir": output_dir})
    log_event(
        "orchestrator",
        "start",
        "Processing URL",
        level="INFO",
        data={
            "url": url,
            "output_dir": output_dir,
            "force": force,
            "start_time": start_time,
            "end_time": end_time,
        },
    )

    # Parse time range if provided
    start_seconds = None
    end_seconds = None
    time_range_suffix = ""

    if start_time:
        start_seconds = parse_timecode(start_time)
        end_seconds = parse_timecode(end_time) if end_time else None

        # Create a suffix for the output file
        def fmt_time(sec: float) -> str:
            m, s_val = divmod(int(sec), 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"{h}h{m:02d}m{s_val:02d}s"
            return f"{m}m{s_val:02d}s"

        time_range_suffix = f".{fmt_time(start_seconds)}"
        if end_seconds is not None:
            time_range_suffix += f"-{fmt_time(end_seconds)}"

        if event_cb:
            try:
                event_cb("range_specified", {
                    "start": start_time,
                    "end": end_time,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                })
            except Exception:
                pass
        log_event(
            "orchestrator",
            "range_specified",
            "Range provided",
            level="INFO",
            data={
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

    # 1) Download (with optional range - this downloads ONLY the needed section!)
    file_path, info = download_video(
        url, output_dir, config,
        ytdl_opts=ytdl_opts,
        progress_hook=progress_hook,
        start_time=start_seconds,
        end_time=end_seconds,
    )
    media_dir = os.path.dirname(file_path)
    base, _ext = os.path.splitext(file_path)
    transcript_txt = f"{base}{time_range_suffix}.txt"

    if event_cb:
        try:
            event_cb("downloaded", {"file": file_path, "range": bool(start_time)})
        except Exception:
            pass
    if json_events:
        _emit_json("downloaded", {"file": file_path})

    # 2) Transcribe (idempotent)
    # With range download, the file already contains only the needed segment
    audio_to_transcribe = file_path

    # Check for existing transcript (with time range suffix if applicable)
    if os.path.exists(transcript_txt) and not force:
        log_event(
            "orchestrator",
            "skip_transcription",
            "Transcript already exists",
            level="INFO",
            data={"transcript": transcript_txt, "force": force},
        )
        if event_cb:
            try:
                event_cb("skip_transcription", {"output_file": transcript_txt})
            except Exception:
                pass
        if json_events:
            _emit_json("skip_transcription", {"output_file": transcript_txt})
        text = open(transcript_txt, "r", encoding="utf-8").read()
    else:
        result = transcribe_audio(
            audio_to_transcribe,
            language=config.get("transcription_language", "auto"),
            model_size=config.get("transcription_model", "base"),
            output_format=config.get("output_format", "txt"),
            output_dir=media_dir,
            backend=config.get("transcription_backend", "faster-whisper"),
            compute_type=config.get("transcription_compute_type", "int8_float16"),
        )
        text = result.get("text", "")
        out_file = result.get("output_file", transcript_txt)

        # Rename output file if we have a time range suffix
        if time_range_suffix and out_file and out_file != transcript_txt:
            try:
                os.replace(out_file, transcript_txt)
                out_file = transcript_txt
            except Exception:
                pass

        if event_cb:
            try:
                event_cb("transcribed", {"output_file": out_file, "chars": len(text)})
            except Exception:
                pass
        if json_events:
            _emit_json("transcribed", {"output_file": out_file, "chars": len(text)})

    # 3) Index
    record = {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url") or url,
        "file": file_path,
        "transcript": transcript_txt,
        "duration": info.get("duration"),
        "language": config.get("transcription_language", "auto"),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    update_index(record)
    if event_cb:
        try:
            event_cb("indexed", {"index_record": record})
        except Exception:
            pass
    if json_events:
        _emit_json("indexed", {"index_record": record})
    log_event(
        "orchestrator",
        "done",
        "Job finished",
        level="INFO",
        data={"transcript": transcript_txt, "id": record.get("id")},
    )

    return {"file": file_path, "transcript": transcript_txt, "meta": record}


def transcribe_range(
    file_path: str,
    *,
    start: str,
    end: Optional[str] = None,
    duration: Optional[str] = None,
    model: str = "base",
    lang: str = "auto",
) -> Dict[str, Any]:
    """
    Transcribe only a range of a local media file. Returns paths and meta.
    """
    s = parse_timecode(start)
    e = parse_timecode(end) if end else None
    d = parse_timecode(duration) if duration else None
    slice_wav = extract_segment(file_path, start=s, end=e, duration=d)
    try:
        media_dir = os.path.dirname(file_path)
        base = os.path.splitext(file_path)[0]
        # Suffix for the slice transcript
        def fmt(sec: float) -> str:
            ms = int(round(sec * 1000))
            s, ms = divmod(ms, 1000)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h:02d}h{m:02d}m{s:02d}s"
        label = f"{fmt(s)}-{fmt(e) if e is not None else 'dur'+fmt(d or 0)}"
        result = transcribe_audio(
            slice_wav,
            language=lang,
            model_size=model,
            output_format="txt",
            output_dir=media_dir,
        )
        out_file = result.get("output_file")
        # Rename to include label
        if out_file:
            labeled = f"{base}.slice_{label}.txt"
            try:
                os.replace(out_file, labeled)
                result["output_file"] = labeled
            except Exception:
                pass
        return {"slice": slice_wav, "result": result}
    finally:
        try:
            os.remove(slice_wav)
        except Exception:
            pass
