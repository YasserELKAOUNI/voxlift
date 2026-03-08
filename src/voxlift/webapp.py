import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contextlib import asynccontextmanager

from .config_manager import load_config_file
from .logging_manager import init_logger, log_event
from .storage import DEFAULT_TRANSCRIPTS_DIR, list_transcripts, search_transcripts
from .transcriber import preload_model, get_model_info
from .scheduler import get_scheduler, submit_job
from .media import parse_timecode


# Paths
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_PATH = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan: preload Whisper model at startup to eliminate cold start.
    """
    init_logger(level="INFO")
    cfg = load_config_file()
    backend = cfg.get("transcription_backend", "faster-whisper")
    compute_type = cfg.get("transcription_compute_type", "int8")
    default_model = cfg.get("transcription_model", "small")

    log_event(
        "webapp",
        "startup",
        "Initializing Voxlift Web...",
        level="INFO",
        data={"pid": os.getpid()},
    )

    # Preload the default model - eliminates 10+ second cold start
    try:
        preload_model(default_model, backend=backend, compute_type=compute_type)
        info = get_model_info()
        log_event(
            "webapp",
            "startup_complete",
            "Startup ready",
            level="INFO",
            data={"device": info["device"], "cached_models": info["cached_models"]},
        )
    except Exception as e:
        log_event(
            "webapp",
            "startup_warning",
            "Model preload failed",
            level="WARNING",
            data={"error": str(e)},
        )

    yield

    log_event("webapp", "shutdown", "Shutting down Voxlift Web", level="INFO", data={"pid": os.getpid()})

app = FastAPI(title="Voxlift Web", version="0.6.0", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def default_transcripts_dir() -> str:
    """Get default directory for transcripts."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cfg = load_config_file()
    configured = cfg.get("transcripts_dir")
    if configured:
        if os.path.isabs(configured):
            return configured
        return os.path.join(repo_root, configured)
    return os.path.join(repo_root, "transcripts")


def default_temp_dir() -> str:
    """Get default directory for temp audio files."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cfg = load_config_file()
    configured = cfg.get("temp_dir")
    if configured:
        if os.path.isabs(configured):
            return configured
        return os.path.join(repo_root, configured)
    return os.path.join(repo_root, "temp")


def truncate_path(path: str, max_len: int = 45) -> str:
    """Truncate path for display, keeping the end visible."""
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3):]


@dataclass
class Job:
    """Local job tracking for API responses."""
    id: str
    url: str
    out: str
    model: str
    lang: str
    format: str = "srt"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    keep_audio: bool = False
    status: str = "pending"  # pending|running|completed|error
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        self.events.append({"event": event, **payload, "ts": time.time()})


JOBS: Dict[str, Job] = {}


class ProcessRequest(BaseModel):
    url: str
    out: Optional[str] = None
    model: Optional[str] = "small"  # Changed default from tiny
    lang: Optional[str] = "auto"
    format: Optional[str] = "srt"   # Changed default from txt
    keep_audio: Optional[bool] = False  # NEW: option to keep audio file
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    backend: Optional[str] = None
    compute_type: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve the main HTML page with template variables replaced."""
    out_path = default_transcripts_dir()

    if not TEMPLATE_PATH.exists():
        return get_fallback_html(out_path)

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace("{{OUTPUT_PATH}}", out_path)
    html = html.replace("{{OUTPUT_PATH_DISPLAY}}", truncate_path(out_path))
    return html


def get_fallback_html(out_path: str) -> str:
    """Minimal fallback HTML if static files are missing."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Voxlift</title>
    <style>
        body {{ font-family: system-ui; background: #1a1a1c; color: #f5f5f7; padding: 40px; }}
        input, button {{ padding: 12px; font-size: 16px; }}
        input {{ width: 400px; background: #242426; border: 1px solid #3d3d40; color: white; border-radius: 8px; }}
        button {{ background: #0a84ff; color: white; border: none; border-radius: 8px; cursor: pointer; }}
    </style>
</head>
<body>
    <h1>Voxlift - YouTube Transcriber</h1>
    <p>Static files not found. Run from project root.</p>
    <div>
        <input id="url" placeholder="Paste YouTube URL">
        <button onclick="submit()">Transcribe</button>
    </div>
    <pre id="out"></pre>
    <script>
        async function submit() {{
            const url = document.getElementById('url').value;
            const r = await fetch('/api/process', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{url, out: '{out_path}'}})
            }});
            document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
        }}
    </script>
</body>
</html>"""


@app.post("/api/process")
def api_process(req: ProcessRequest):
    """Submit a URL for transcription."""
    if not req.url or "youtube" not in req.url and "youtu.be" not in req.url:
        raise HTTPException(status_code=400, detail="Provide a valid YouTube URL")

    job_id = uuid.uuid4().hex[:8]
    cfg = load_config_file()

    # Determine output directory
    out_dir = req.out or default_transcripts_dir()

    # Create local Job for API tracking
    job = Job(
        id=job_id,
        url=req.url,
        out=out_dir,
        model=req.model or cfg.get("transcription_model", "small"),
        lang=req.lang or cfg.get("transcription_language", "auto"),
        format=req.format or cfg.get("output_format", "srt"),
        start_time=req.start_time,
        end_time=req.end_time,
        keep_audio=req.keep_audio or cfg.get("keep_audio", False),
    )
    JOBS[job_id] = job

    # Parse time range to seconds if provided
    start_seconds = parse_timecode(req.start_time) if req.start_time else None
    end_seconds = parse_timecode(req.end_time) if req.end_time else None

    # Build config for scheduler
    job_config = {
        "transcription_language": job.lang,
        "transcription_model": job.model,
        "output_format": job.format,
        "transcription_backend": req.backend or cfg.get("transcription_backend", "faster-whisper"),
        "transcription_compute_type": req.compute_type or cfg.get("transcription_compute_type", "int8"),
    }

    def on_progress(event: str, payload: Dict[str, Any]) -> None:
        """Callback from scheduler - update our Job object."""
        job.emit(event, payload)

        # Update job status based on scheduler events
        if event == "extract_start":
            job.status = "running"
        elif event == "error":
            job.status = "error"
            job.error = payload.get("message", "Unknown error")
        elif event == "completed":
            job.status = "completed"
            job.result = {
                "transcript": payload.get("transcript"),
                "video_id": payload.get("video_id"),
            }

    # Submit to resource-aware scheduler
    submit_job(
        job_id=job_id,
        url=req.url,
        output_dir=out_dir,
        config=job_config,
        on_progress=on_progress,
        start_time=start_seconds,
        end_time=end_seconds,
        keep_audio=job.keep_audio,
        extract_workers=cfg.get("extract_workers", 3),
        transcribe_workers=cfg.get("transcribe_workers", 1),
        temp_dir=default_temp_dir(),
    )

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    """Get job status and events."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="No such job")
    return {
        "id": job.id,
        "url": job.url,
        "out": job.out,
        "model": job.model,
        "lang": job.lang,
        "format": job.format,
        "start_time": job.start_time,
        "end_time": job.end_time,
        "keep_audio": job.keep_audio,
        "status": job.status,
        "error": job.error,
        "events": job.events[-50:],
        "result": job.result,
    }


@app.get("/api/system")
def api_system():
    """Get system info including device capabilities, loaded models, and scheduler stats."""
    import platform
    model_info = get_model_info()
    scheduler_obj = get_scheduler()
    scheduler_stats = scheduler_obj.get_stats()
    cfg = load_config_file()

    return {
        "version": "0.6.0",
        "platform": platform.system(),
        "machine": platform.machine(),
        "device": model_info["device"],
        "mps_available": model_info["mps_available"],
        "cached_models": model_info["cached_models"],
        "backend": cfg.get("transcription_backend", "faster-whisper"),
        "compute_type": cfg.get("transcription_compute_type", "int8"),
        "default_model": cfg.get("transcription_model", "small"),
        "default_format": cfg.get("output_format", "srt"),
        "scheduler": {
            "extract_workers": scheduler_obj.extract_workers,
            "transcribe_workers": scheduler_obj.transcribe_workers,
            "extractions_active": scheduler_stats.get("extractions_active", 0),
            "transcriptions_active": scheduler_stats.get("transcriptions_active", 0),
            "total_submitted": scheduler_stats["total_submitted"],
            "total_completed": scheduler_stats["total_completed"],
            "total_failed": scheduler_stats["total_failed"],
        },
        "active_jobs": len([j for j in JOBS.values() if j.status == "running"]),
        "total_jobs": len(JOBS),
    }


@app.get("/api/transcripts")
def api_transcripts(q: Optional[str] = None, limit: int = 100):
    """List all transcripts or search by query."""
    if q:
        return search_transcripts(q, limit=limit)
    return list_transcripts(limit=limit)


@app.get("/api/index")
def api_index(root: Optional[str] = None, q: Optional[str] = None):
    """Legacy endpoint - redirects to /api/transcripts."""
    return api_transcripts(q=q)


class PathRequest(BaseModel):
    path: str


@app.post("/api/reveal")
def api_reveal(req: PathRequest):
    """Reveal a file or folder in Finder (macOS)."""
    path = os.path.expanduser(req.path)

    if not os.path.exists(path):
        return JSONResponse({"error": f"Path not found: {path}"}, status_code=400)

    try:
        if os.path.isfile(path):
            subprocess.run(["open", "-R", path], check=True)
        else:
            subprocess.run(["open", path], check=True)
        return {"ok": True, "path": path}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/open")
def api_open(req: PathRequest):
    """Open a file with default application (macOS)."""
    path = os.path.expanduser(req.path)

    if not os.path.exists(path):
        return JSONResponse({"error": f"Path not found: {path}"}, status_code=400)

    try:
        subprocess.run(["open", path], check=True)
        return {"ok": True, "path": path}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/validate-path")
def api_validate_path(req: PathRequest):
    """Validate and expand a path, creating it if needed."""
    path = os.path.expanduser(req.path)

    # Try to create if it doesn't exist
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            return {"valid": False, "error": f"Cannot create directory: {e}"}

    if not os.path.isdir(path):
        return {"valid": False, "error": "Path is not a directory"}

    # Check if writable
    if not os.access(path, os.W_OK):
        return {"valid": False, "error": "Directory is not writable"}

    return {"valid": True, "path": path}


# AI Enhancement System Prompts
AI_PROMPTS = {
    "summary": {
        "system": "You are an expert summarizer. Create clear, concise summaries that capture the essence of content.",
        "user": """Summarize this transcript in a clear, structured format:

1. **TL;DR** (1-2 sentences max)
2. **Key Points** (3-5 bullet points)
3. **Main Takeaways** (what the audience should remember)

Be concise but comprehensive. Use timestamps if present.

Transcript:
{text}"""
    },
    "highlights": {
        "system": "You are a content curator who identifies the most valuable moments in any content.",
        "user": """Extract the highlights from this transcript:

1. **Notable Quotes** (exact quotes with timestamps if available)
2. **Key Insights** (the 'aha' moments)
3. **Memorable Examples** (stories, analogies, case studies)
4. **Action Items** (if any mentioned)

Format as clean, skimmable markdown.

Transcript:
{text}"""
    },
    "chapters": {
        "system": "You are a video editor creating chapter markers for content.",
        "user": """Create chapter markers for this transcript:

Format each chapter as:
**[TIMESTAMP] Chapter Title**
Brief description (1 sentence)

Identify natural topic transitions and key segments. If no timestamps exist, estimate based on content position (e.g., "Early", "Middle", "Late").

Transcript:
{text}"""
    },
    "action_items": {
        "system": "You are a productivity coach extracting actionable tasks from content.",
        "user": """Extract all actionable items from this transcript:

Format as a task list:
- [ ] **Task** - Context/details (timestamp if available)

Categories:
1. **Immediate Actions** (do now)
2. **Follow-up Tasks** (research, read more)
3. **Long-term Goals** (implement later)

Only include concrete, actionable items.

Transcript:
{text}"""
    },
    "questions": {
        "system": "You are an interviewer identifying the key questions addressed in content.",
        "user": """Extract the Q&A structure from this transcript:

Format:
**Q: [Question]**
A: [Answer summary] (timestamp)

Include:
1. Explicit questions asked
2. Implicit questions being answered
3. Questions raised but not fully answered

Transcript:
{text}"""
    },
    "tweet_thread": {
        "system": "You are a social media expert creating viral Twitter/X threads.",
        "user": """Convert this transcript into a Twitter/X thread:

Rules:
- First tweet: Hook that grabs attention
- Each tweet: Max 280 chars, standalone value
- Use numbers, emojis sparingly
- End with a call to action
- 5-10 tweets total

Format:
1/ [First tweet - the hook]

2/ [Key point 1]

...

Transcript:
{text}"""
    },
}


class EnhanceRequest(BaseModel):
    transcript: str
    type: str = "summary"


@app.post("/api/enhance")
def api_enhance(req: EnhanceRequest):
    """Enhance a transcript using AI (requires OPENAI_API_KEY)."""
    if not os.path.isfile(req.transcript):
        return JSONResponse({"error": "Transcript file not found"}, status_code=400)

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return JSONResponse({"error": "OPENAI_API_KEY not set. Add it to your environment."}, status_code=400)

    prompt_config = AI_PROMPTS.get(req.type)
    if not prompt_config:
        return JSONResponse({"error": f"Unknown enhancement type: {req.type}"}, status_code=400)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)

        text = open(req.transcript, "r", encoding="utf-8").read()

        # Truncate if too long (leave room for response)
        max_chars = 100000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... truncated ...]"

        system_prompt = prompt_config["system"]
        user_prompt = prompt_config["user"].format(text=text)

        model = os.getenv("VOXLIFT_OPENAI_MODEL") or os.getenv("YWW_OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=4000,
        )

        md = resp.choices[0].message.content or ""

        # Save output
        base, _ = os.path.splitext(req.transcript)
        out = f"{base}.{req.type}.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# {req.type.replace('_', ' ').title()}\n\n")
            f.write(f"_Generated from: {os.path.basename(req.transcript)}_\n\n")
            f.write("---\n\n")
            f.write(md)

        return {"file": out, "type": req.type}
    except Exception as e:
        import traceback
        return JSONResponse({"error": str(e), "trace": traceback.format_exc()}, status_code=500)
