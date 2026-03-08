# src/voxlift/transcriber.py
"""
Transcription module for Apple Silicon with two backends:
- PyTorch Whisper (original, MPS-aware)
- faster-whisper (CTranslate2), usually faster/cooler on M1 with int8_float16
"""

import os
import time
from typing import Dict, Any, Optional, Callable, List, Tuple

import torch

from .logging_manager import log_event

# ============================================================================
# Device Detection (M1 optimized)
# ============================================================================

def get_device() -> str:
    """
    Detect best available device for M1 Mac.
    Priority: MPS (Metal) > CPU
    """
    if torch.backends.mps.is_available():
        # Check if MPS is actually usable (not just available)
        try:
            torch.zeros(1).to("mps")
            log_event(
                "transcriber",
                "device_detected",
                "Using MPS (Metal) acceleration",
                level="INFO",
                data={"device": "mps"},
            )
            return "mps"
        except Exception as e:
            log_event(
                "transcriber",
                "mps_fallback",
                "MPS unavailable, falling back to CPU",
                level="WARNING",
                data={"error": str(e)},
            )

    log_event("transcriber", "device_detected", "Using CPU (FP32)", level="INFO", data={"device": "cpu"})
    return "cpu"


# ============================================================================
# Model Cache (Persistent for fast subsequent calls)
# ============================================================================

_TORCH_MODEL_CACHE: Dict[str, Any] = {}
_FASTER_MODEL_CACHE: Dict[str, Any] = {}
_DEVICE: Optional[str] = None


def _get_device() -> str:
    """Get cached device or detect it for torch backend."""
    global _DEVICE
    if _DEVICE is None:
        _DEVICE = get_device()
    return _DEVICE


def _get_torch_model(model_size: str) -> Any:
    """Load (and cache) the PyTorch Whisper model."""
    import whisper

    cache_key = f"{model_size}_{_get_device()}"

    if cache_key not in _TORCH_MODEL_CACHE:
        device = _get_device()
        log_event(
            "transcriber",
            "model_load_start",
            "Loading Whisper model",
            level="INFO",
            data={"model": model_size, "device": device, "backend": "whisper"},
        )

        start = time.time()

        if device == "mps":
            model = whisper.load_model(model_size, device="cpu")
        else:
            model = whisper.load_model(model_size, device=device)

        load_time = time.time() - start
        log_event(
            "transcriber",
            "model_load_complete",
            "Model loaded",
            level="INFO",
            data={"model": model_size, "device": device, "backend": "whisper", "load_time_s": round(load_time, 2)},
        )

        _TORCH_MODEL_CACHE[cache_key] = model

    return _TORCH_MODEL_CACHE[cache_key]


def _get_faster_model(model_size: str, compute_type: str = "int8_float16", device: str = "auto", num_workers: int = 2) -> Any:
    """Load (and cache) a faster-whisper model."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        raise ImportError("faster-whisper is not installed") from e

    cache_key = f"{model_size}_{device}_{compute_type}_{num_workers}"
    if cache_key not in _FASTER_MODEL_CACHE:
        log_event(
            "transcriber",
            "model_load_start",
            "Loading faster-whisper model",
            level="INFO",
            data={"model": model_size, "device": device, "backend": "faster-whisper", "compute_type": compute_type},
        )
        start = time.time()
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            num_workers=num_workers,
        )
        load_time = time.time() - start
        log_event(
            "transcriber",
            "model_load_complete",
            "Model loaded",
            level="INFO",
            data={
                "model": model_size,
                "device": device,
                "backend": "faster-whisper",
                "compute_type": compute_type,
                "load_time_s": round(load_time, 2),
            },
        )
        _FASTER_MODEL_CACHE[cache_key] = model

    return _FASTER_MODEL_CACHE[cache_key]


def _get_faster_model_with_fallback(model_size: str, compute_type: str, device: str, num_workers: int) -> Any:
    """
    Try to load faster-whisper model, falling back to int8 if mixed precision is unsupported.
    """
    try:
        return _get_faster_model(model_size, compute_type=compute_type, device=device, num_workers=num_workers)
    except Exception as e:
        msg = str(e).lower()
        if compute_type != "int8" and ("compute type" in msg or "int8_float16" in msg or "not support" in msg):
            log_event(
                "transcriber",
                "model_load_retry",
                "Retry faster-whisper with int8",
                level="WARNING",
                data={"model": model_size, "prev_compute_type": compute_type},
            )
            return _get_faster_model(model_size, compute_type="int8", device=device, num_workers=num_workers)
        raise


def preload_model(model_size: str = "base", backend: str = "faster-whisper", compute_type: str = "int8") -> None:
    """Pre-load a model into cache (call at app startup to eliminate cold start)."""
    log_event(
        "transcriber",
        "preload_start",
        "Pre-loading model",
        level="INFO",
        data={"model": model_size, "backend": backend, "compute_type": compute_type},
    )
    try:
        if backend == "faster-whisper":
            _get_faster_model_with_fallback(model_size, compute_type=compute_type, device="auto", num_workers=2)
        else:
            _get_torch_model(model_size)
    except ImportError as e:
        log_event(
            "transcriber",
            "preload_warning",
            "faster-whisper missing, falling back to torch",
            level="WARNING",
            data={"model": model_size, "backend": backend, "error": str(e)},
        )
        _get_torch_model(model_size)
    except Exception as e:
        log_event(
            "transcriber",
            "preload_error",
            "Preload failed",
            level="WARNING",
            data={"model": model_size, "backend": backend, "error": str(e)},
        )
        raise
    else:
        log_event(
            "transcriber",
            "preload_complete",
            "Model ready",
            level="INFO",
            data={"model": model_size, "backend": backend},
        )


def get_model_info() -> Dict[str, Any]:
    """Get info about loaded models and device."""
    return {
        "device": _get_device(),
        "cached_models": list(_TORCH_MODEL_CACHE.keys()) + list(_FASTER_MODEL_CACHE.keys()),
        "mps_available": torch.backends.mps.is_available(),
    }


# ============================================================================
# Transcription with Progress
# ============================================================================

def estimate_transcription_time(audio_duration_seconds: float, model_size: str = "base", backend: str = "whisper") -> float:
    """
    Estimate transcription time based on audio duration and model.

    Rough estimates for M1 (base model on CPU):
    - ~0.5-1x realtime for tiny
    - ~1-2x realtime for base
    - ~2-4x realtime for small
    - ~4-8x realtime for medium
    - ~8-15x realtime for large

    With MPS, these can be 2-3x faster.
    """
    multipliers = {
        "tiny": 0.8,
        "base": 1.5,
        "small": 3.0,
        "medium": 6.0,
        "large": 12.0,
    }
    # faster-whisper is typically faster on M1; apply a friendly boost
    if backend == "faster-whisper":
        multipliers = {k: v * 0.6 for k, v in multipliers.items()}
    multiplier = multipliers.get(model_size, 2.0)

    # Reduce estimate if using MPS
    if _get_device() == "mps":
        multiplier *= 0.5

    return audio_duration_seconds * multiplier


def transcribe_audio(
    file_path: str,
    language: str = "auto",
    model_size: str = "base",
    output_format: str = "txt",
    output_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    backend: str = "faster-whisper",
    compute_type: str = "int8",
    num_workers: int = 2,
) -> Dict[str, Any]:
    """
    Transcribe an audio/video file via Whisper.

    Args:
        file_path: Path to media file (audio or video)
        language: Language code (e.g., 'en', 'fr') or 'auto' for detection
        model_size: Model size ('tiny', 'base', 'small', 'medium', 'large')
        output_format: 'txt', 'srt', or 'vtt'
        output_dir: If provided, saves output file there
        progress_callback: Optional callback(event, payload) for progress updates

    Returns:
        Dict with keys: 'text', 'segments', 'output_file' (if a file was generated), 'language'
    """
    def emit(event: str, payload: Dict[str, Any]) -> None:
        """Emit progress event."""
        msg_parts = []
        if "file" in payload:
            msg_parts.append(str(payload.get("file")))
        if "model" in payload:
            msg_parts.append(f"model={payload.get('model')}")
        if "output_file" in payload:
            msg_parts.append(f"out={payload.get('output_file')}")
        message = ", ".join(msg_parts) or event

        log_event("transcriber", event, message, level="INFO", data=payload)
        if progress_callback:
            try:
                progress_callback(event, payload)
            except Exception:
                pass

    # 1. Verify file exists
    if not os.path.isfile(file_path):
        log_event(
            "transcriber",
            "file_not_found",
            "File not found",
            level="ERROR",
            data={"file": file_path},
        )
        raise FileNotFoundError(f"{file_path} not found")

    # Get file info
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)

    # Backend/device selection
    chosen_backend = backend or "faster-whisper"
    device_label = "auto" if chosen_backend == "faster-whisper" else _get_device()

    emit("transcribe_init", {
        "file": file_name,
        "size_mb": round(file_size / (1024 * 1024), 2),
        "model": model_size,
        "language": language,
        "device": device_label,
        "backend": chosen_backend,
        "compute_type": compute_type,
    })

    emit("transcribe_start", {
        "file": file_name,
        "model": model_size,
        "backend": chosen_backend,
    })

    # 3. Get audio duration for estimation
    try:
        import whisper  # local import to avoid forcing torch at module import

        audio = whisper.load_audio(file_path)
        duration_seconds = len(audio) / whisper.audio.SAMPLE_RATE
        estimated_time = estimate_transcription_time(duration_seconds, model_size, chosen_backend)

        emit("transcribe_audio_loaded", {
            "duration_seconds": round(duration_seconds, 1),
            "duration_formatted": _format_duration(duration_seconds),
            "estimated_time_seconds": round(estimated_time, 1) if estimated_time else None,
            "estimated_time_formatted": _format_duration(estimated_time) if estimated_time else None,
        })
    except Exception as e:
        log_event(
            "transcriber",
            "duration_estimate_failed",
            "Failed to compute duration",
            level="WARNING",
            data={"file": file_path, "error": str(e)},
        )
        duration_seconds = None
        estimated_time = None

    # 4. Transcribe with timing
    start_time = time.time()

    try:
        if chosen_backend == "faster-whisper":
            try:
                text, segments, detected_language = _transcribe_with_faster_whisper(
                    file_path=file_path,
                    language=language,
                    model_size=model_size,
                    compute_type=compute_type,
                    num_workers=num_workers,
                )
            except ImportError:
                # Fallback silently to torch if faster-whisper is missing
                chosen_backend = "whisper"
                text, segments, detected_language = _transcribe_with_torch(
                    file_path=file_path,
                    language=language,
                    model_size=model_size,
                )
            except Exception as e:
                msg = str(e).lower()
                if compute_type != "int8" and ("compute type" in msg or "int8_float16" in msg or "not support" in msg):
                    log_event(
                        "transcriber",
                        "model_load_retry",
                        "Retry faster-whisper with int8",
                        level="WARNING",
                        data={"model": model_size, "prev_compute_type": compute_type},
                    )
                    text, segments, detected_language = _transcribe_with_faster_whisper(
                        file_path=file_path,
                        language=language,
                        model_size=model_size,
                        compute_type="int8",
                        num_workers=num_workers,
                    )
                    compute_type = "int8"
                else:
                    raise
        else:
            text, segments, detected_language = _transcribe_with_torch(
                file_path=file_path,
                language=language,
                model_size=model_size,
            )
    except Exception as e:
        log_event(
            "transcriber",
            "transcription_error",
            "Transcription failed",
            level="ERROR",
            data={"file": file_path, "error": str(e), "backend": chosen_backend},
        )
        emit("transcribe_error", {"error": str(e)})
        raise

    elapsed = time.time() - start_time
    rtf = round(duration_seconds / elapsed, 2) if duration_seconds and elapsed > 0 else None
    result: Dict[str, Any] = {
        "text": text,
        "segments": segments,
        "language": detected_language,
        "backend": chosen_backend,
        "model": model_size,
        "compute_type": compute_type,
    }

    emit("transcribe_complete", {
        "elapsed_seconds": round(elapsed, 1),
        "elapsed_formatted": _format_duration(elapsed),
        "text_length": len(text),
        "segment_count": len(segments),
        "detected_language": detected_language,
        "realtime_factor": rtf,
        "backend": chosen_backend,
    })

    # 5. Write output if requested
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(file_path))[0]
        out_path = os.path.join(output_dir, f"{base}.{output_format}")

        if output_format == "txt":
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
        elif output_format in ("srt", "vtt"):
            content = (_segments_to_srt(segments) if output_format == "srt" else _segments_to_vtt(segments))
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)

        emit("transcribe_saved", {"output_file": out_path})
        result["output_file"] = out_path

    return result


def _transcribe_with_torch(
    file_path: str,
    language: str,
    model_size: str,
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    """Transcribe with the original PyTorch Whisper backend."""
    import whisper

    model = _get_torch_model(model_size)

    transcribe_options: Dict[str, Any] = {}
    if language and language != "auto":
        transcribe_options["language"] = language
    if _get_device() == "cpu":
        transcribe_options["fp16"] = False

    result = model.transcribe(file_path, **transcribe_options)
    text = (result.get("text") or "").strip()
    segments_raw = result.get("segments", []) or []

    segments: List[Dict[str, Any]] = []
    for seg in segments_raw:
        segments.append({
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
            "text": (seg.get("text") or "").strip(),
        })

    detected_language = result.get("language", language)
    return text, segments, detected_language


def _transcribe_with_faster_whisper(
    file_path: str,
    language: str,
    model_size: str,
    compute_type: str,
    num_workers: int,
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    """Transcribe with faster-whisper (CTranslate2)."""
    model = _get_faster_model(model_size, compute_type=compute_type, device="auto", num_workers=num_workers)

    options: Dict[str, Any] = {"beam_size": 1}
    if language and language != "auto":
        options["language"] = language

    segments_iter, info = model.transcribe(file_path, **options)

    text_parts: List[str] = []
    segments: List[Dict[str, Any]] = []
    for seg in segments_iter:
        seg_text = (seg.text or "").strip()
        text_parts.append(seg_text)
        segments.append({
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg_text,
        })

    text = " ".join(t for t in text_parts if t).strip()
    detected_language = getattr(info, "language", None) or language
    return text, segments, detected_language


def _format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h, remainder = divmod(int(seconds), 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h {m}m"


def _format_timestamp(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    ms = int(round(seconds * 1000))
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _segments_to_srt(segments: List[dict]) -> str:
    """Convert Whisper segments to SRT format."""
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = _format_timestamp(float(seg.get("start", 0.0)))
        end = _format_timestamp(float(seg.get("end", 0.0)))
        text = (seg.get("text") or "").strip()
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _segments_to_vtt(segments: List[dict]) -> str:
    """Convert Whisper segments to WebVTT format."""
    def fmt_vtt(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        s, ms = divmod(ms, 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    lines = ["WEBVTT", ""]
    for seg in segments:
        start = fmt_vtt(float(seg.get("start", 0.0)))
        end = fmt_vtt(float(seg.get("end", 0.0)))
        text = (seg.get("text") or "").strip()
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)
