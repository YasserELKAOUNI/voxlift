import json
import os
from typing import Any, Callable, Dict, Optional

from .audio_extractor import cleanup_temp_file, extract_audio
from .logging_manager import init_logger, log_event
from .storage import sanitize_filename, save_transcript
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

    temp_dir = config.get("temp_dir")
    file_path: Optional[str] = None
    transcript_path: Optional[str] = None

    try:
        # 1) Extract audio to a temp file (with optional range extraction)
        file_path, info = extract_audio(
            url=url,
            temp_dir=temp_dir,
            start_time=start_seconds,
            end_time=end_seconds,
            progress_hook=progress_hook,
            max_retries=config.get("max_retries", 3),
        )
        output_format = config.get("output_format", "txt")
        video_id = info.get("id") or "unknown"

        uploader = info.get("uploader", "Unknown")
        title = info.get("title", "untitled")
        if time_range_suffix:
            title = f"{title} {time_range_suffix}"

        transcript_path = os.path.join(
            output_dir,
            sanitize_filename(uploader),
            f"{sanitize_filename(title)} [{video_id}].{output_format}",
        )

        if event_cb:
            try:
                event_cb("downloaded", {"file": file_path, "range": bool(start_time)})
            except Exception:
                pass
        if json_events:
            _emit_json("downloaded", {"file": file_path})

        # 2) Transcribe (idempotent)
        if os.path.exists(transcript_path) and not force:
            log_event(
                "orchestrator",
                "skip_transcription",
                "Transcript already exists",
                level="INFO",
                data={"transcript": transcript_path, "force": force},
            )
            if event_cb:
                try:
                    event_cb("skip_transcription", {"output_file": transcript_path})
                except Exception:
                    pass
            if json_events:
                _emit_json("skip_transcription", {"output_file": transcript_path})
            text = open(transcript_path, "r", encoding="utf-8").read()
            language = config.get("transcription_language", "auto")
        else:
            result = transcribe_audio(
                file_path,
                language=config.get("transcription_language", "auto"),
                model_size=config.get("transcription_model", "base"),
                output_format=output_format,
                output_dir=None,
                backend=config.get("transcription_backend", "faster-whisper"),
                compute_type=config.get("transcription_compute_type", "int8"),
            )
            text = result.get("text", "")
            transcript_path = save_transcript(
                video_id=video_id,
                text=text,
                segments=result.get("segments", []),
                metadata={
                    "title": title,
                    "uploader": uploader,
                    "webpage_url": info.get("webpage_url") or url,
                    "url": url,
                    "duration": info.get("duration"),
                    "language": result.get("language", config.get("transcription_language", "auto")),
                    "model": config.get("transcription_model", "base"),
                },
                output_format=output_format,
                transcripts_dir=output_dir,
            )
            language = result.get("language", config.get("transcription_language", "auto"))

            if event_cb:
                try:
                    event_cb("transcribed", {"output_file": transcript_path, "chars": len(text)})
                except Exception:
                    pass
            if json_events:
                _emit_json("transcribed", {"output_file": transcript_path, "chars": len(text)})

        result_meta = {
            "id": video_id,
            "title": title,
            "uploader": uploader,
            "webpage_url": info.get("webpage_url") or url,
            "file": file_path,
            "transcript": transcript_path,
            "duration": info.get("duration"),
            "language": language,
        }
    finally:
        if file_path and not config.get("keep_audio", False):
            cleanup_temp_file(file_path)

    if event_cb:
        try:
            event_cb("indexed", {"index_record": result_meta})
        except Exception:
            pass
    if json_events:
        _emit_json("indexed", {"index_record": result_meta})
    log_event(
        "orchestrator",
        "done",
        "Job finished",
        level="INFO",
        data={"transcript": result_meta["transcript"], "id": result_meta.get("id")},
    )

    return {"file": file_path, "transcript": result_meta["transcript"], "meta": result_meta}


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
