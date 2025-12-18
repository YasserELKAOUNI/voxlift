YWW – YouTube → Transcript (Mac)

Overview
- Paste a YouTube URL → audio-only download → local Whisper transcription → transcript.txt.
- Works via a CLI (`yww`) and a local web app (http://127.0.0.1:8787).
- Idempotent (resume/skip), safe filenames, JSON index for quick lookup.

Quick Start
- Create venv: `python3 -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install -U pip && pip install yt-dlp PyYAML rich typer openai-whisper torch fastapi 'uvicorn[standard]'`
- Run CLI help: `PYTHONPATH=src python -m yww.cli --help`
- Web app: `PYTHONPATH=src python -m yww.cli web -p 8787`

CLI Examples
- Process one URL: `PYTHONPATH=src python -m yww.cli process -u "<YOUTUBE_URL>" -o "~/Documents/Transcripts" -m base -l auto`
- Progress as NDJSON: add `--json`.
- Open transcript folder on completion: add `--open`.

Outputs
- Layout: `<out>/<uploader>/<title> [id]/transcript.txt`
- Index: `<out>/index.json` records all processed items.

Web UI (V1.1)
- Paste URL, choose model/language/output, click Transcribe.
- Jobs show status and “Open transcript” link when done.
- Search: point to an output folder, search existing items, and transcribe a specific time range of a file.

Segment Transcription (Range)
- From the web app (Search section), pick an existing file and enter a time range (e.g., `00:03:00` → `00:05:30`).
- The app extracts the segment via FFmpeg and transcribes only that slice.

LLM Enhancements (Optional)
- Set `OPENAI_API_KEY` in your environment.
- From the UI or API, request: summary, highlights, chapters (written as `notes.md` next to the transcript).

Config
- YAML: `config/settings.yaml` (defaults: output folder, language, model, logging).
- CLI flags override YAML.

Architecture
- Modules: `downloader` (yt-dlp), `transcriber` (Whisper), `storage` (artifacts + index), `media` (FFmpeg helpers), `orchestrator` (pipeline), `webapp` (FastAPI), `cli` (Typer).
- Pipeline: URL → audio-only download → transcribe → write files → update index.
- Web server exposes `/api/process`, `/api/jobs/{id}`, `/api/index`, `/api/transcribe-range`, `/api/enhance`.

Notes
- Requires FFmpeg (Homebrew `ffmpeg`).
- Privacy-first: local processing; API key only needed for optional LLM features and never logged.

