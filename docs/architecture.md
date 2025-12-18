# YWW Architecture

## Overview

YWW (YouTube-Whisper-Wrapper) is a privacy-first local transcription tool that downloads audio from YouTube and transcribes it using OpenAI's Whisper model. All processing happens locally - no data is sent to external servers except for optional LLM enhancements.

## Core Philosophy

- **Single Action**: Paste URL, get transcript
- **Privacy First**: Local Whisper, no cloud dependencies
- **Idempotent**: Safe to re-run, caches results
- **Mac-Native Feel**: Keyboard shortcuts, Finder integration

---

## System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web UI (FastAPI)                         │
│  ┌──────────────┐ ┌──────────────────────────────────────────┐ │
│  │   Sidebar    │ │              Main Content                 │ │
│  │   (Jobs)     │ │  ┌────────────────────────────────────┐  │ │
│  │              │ │  │         URL Input (CTA)            │  │ │
│  │  - Queued    │ │  │  ┌──────────────────────────────┐  │  │ │
│  │  - Running   │ │  │  │ Paste YouTube URL...    [GO] │  │  │ │
│  │  - Done      │ │  │  └──────────────────────────────┘  │  │ │
│  │  - Failed    │ │  │                                    │  │ │
│  │              │ │  │    Quality: [Fast|Balanced|Best]   │  │ │
│  │              │ │  │    Language: [Auto|en|fr|...]      │  │ │
│  │              │ │  │    Output: ~/Downloads [Reveal]    │  │ │
│  │              │ │  │                                    │  │ │
│  │              │ │  │    [Advanced Options ▼]            │  │ │
│  │              │ │  └────────────────────────────────────┘  │ │
│  └──────────────┘ │                                          │ │
│                   │  ┌────────────────────────────────────┐  │ │
│                   │  │  Pipeline: Fetch→Download→Transcribe│ │
│                   │  │  Progress: ████████░░░░ 65%         │ │
│                   │  └────────────────────────────────────┘  │ │
│                   └──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Orchestrator                              │
│  process_url(url, output_dir, config) → {file, transcript, meta}│
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Downloader  │    │  Transcriber │    │   Storage    │
│  (yt-dlp)    │    │  (Whisper)   │    │  (index.json)│
└──────────────┘    └──────────────┘    └──────────────┘
```

---

## Components

### 1. Web UI (`webapp.py` + `static/`)

**Technology**: FastAPI + vanilla HTML/CSS/JS

**Features**:
- Split-view layout (sidebar + main content)
- Single primary CTA (paste URL → transcribe)
- 4-step pipeline visualization
- Real-time progress via polling
- Mac-native patterns: ⌘L focus, ⌘K new, ⌘O reveal
- Drag & drop URL support
- Context menus on jobs
- Actionable error messages

**Static Files**:
```
static/
├── css/
│   └── app.css      # Design system (8pt grid, dark mode)
├── js/
│   └── app.js       # Application logic
└── index.html       # Main template
```

### 2. Orchestrator (`orchestrator.py`)

Main pipeline coordinator. Handles the flow:

```
process_url(url, output_dir, config, force, event_cb)
    │
    ├─→ 1. Download (audio-only via yt-dlp)
    │       emit("start", {url})
    │       emit("progress", {bytes, speed, eta})
    │       emit("downloaded", {file})
    │
    ├─→ 2. Transcribe (Whisper, cached)
    │       emit("transcribed", {output_file, chars})
    │       OR emit("skip_transcription", {output_file})
    │
    └─→ 3. Index (append to index.json)
            emit("indexed", {record})
```

### 3. Downloader (`downloader.py`)

**Library**: yt-dlp

**Features**:
- Audio-only extraction
- Idempotent via download archive
- Progress callbacks for UI
- Retry logic (configurable)

**Output Path Template**:
```
{output_dir}/{uploader}/{title} [{id}].{ext}
```

### 4. Transcriber (`transcriber.py`)

**Library**: openai-whisper

**Features**:
- Model caching (avoid reloading)
- Multiple output formats: TXT, SRT, VTT
- Language auto-detection or explicit

**Models** (UI maps friendly names):
| UI Label   | Model  | Speed    | Accuracy |
|------------|--------|----------|----------|
| Fast       | tiny   | Fastest  | Basic    |
| Balanced   | base   | Fast     | Good     |
| Best       | small  | Moderate | Better   |
| (Advanced) | medium | Slow     | High     |
| (Advanced) | large  | Slowest  | Best     |

### 5. Storage (`storage.py`)

- `sanitize_filename()` - Safe filenames for APFS
- `update_index()` - Append to index.json

**Index Record Schema**:
```json
{
  "id": "abc123def",
  "title": "Video Title",
  "uploader": "Channel Name",
  "webpage_url": "https://youtube.com/watch?v=...",
  "file": "/path/to/audio.m4a",
  "transcript": "/path/to/transcript.txt",
  "duration": 1234,
  "language": "auto",
  "created_at": "2025-12-14T20:13:00.000Z"
}
```

### 6. Media Helpers (`media.py`)

- `parse_timecode()` - Parse HH:MM:SS to seconds
- `extract_segment()` - FFmpeg slice for range transcription

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/` | Serve web UI |
| GET | `/static/*` | Serve CSS/JS assets |
| POST | `/api/process` | Start transcription job |
| GET | `/api/jobs/{id}` | Poll job status |
| GET | `/api/index` | Query transcript index |
| POST | `/api/transcribe-range` | Transcribe time segment |
| POST | `/api/reveal` | Reveal file in Finder |
| POST | `/api/enhance` | LLM enhancement (optional) |

### POST /api/process

**Request**:
```json
{
  "url": "https://youtube.com/watch?v=...",
  "out": "/path/to/output",
  "model": "base",
  "lang": "auto",
  "force": false
}
```

**Response**:
```json
{ "job_id": "a1b2c3d4" }
```

### GET /api/jobs/{id}

**Response**:
```json
{
  "id": "a1b2c3d4",
  "url": "...",
  "status": "running",
  "events": [
    {"event": "start", "url": "...", "ts": 1702...},
    {"event": "progress", "downloaded_bytes": 1024000, "total_bytes": 5000000, "ts": ...},
    {"event": "downloaded", "file": "/path/to/audio.m4a", "ts": ...}
  ],
  "result": null,
  "error": null
}
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| ⌘L | Focus URL input |
| ⌘K | New transcription |
| ⌘O | Reveal output folder |
| ⌘⇧O | Choose output folder |
| Escape | Close panels |

---

## Data Flow

```
User pastes URL
       │
       ▼
┌──────────────┐
│ POST /api/   │
│   process    │──────────────────────────────────┐
└──────────────┘                                  │
       │                                          │
       ▼                                          │
┌──────────────┐                                  │
│ Create Job   │                                  │
│ ID: a1b2c3d4 │                                  │
└──────────────┘                                  │
       │                                          │
       ├─────────────────────────────┐            │
       │  Background Thread          │            │
       ▼                             │            │
┌──────────────┐                     │            │
│ Download     │──→ emit("progress") │            │
│ (yt-dlp)     │                     │            │
└──────────────┘                     │            │
       │                             │            │
       ▼                             │            │
┌──────────────┐                     │            │
│ Transcribe   │──→ emit("transcribed")          │
│ (Whisper)    │                     │            │
└──────────────┘                     │            │
       │                             │            │
       ▼                             │            │
┌──────────────┐                     │            │
│ Update Index │──→ emit("indexed")  │            │
└──────────────┘                     │            │
       │                             │            │
       ▼                             ▼            │
┌──────────────┐              ┌──────────────┐   │
│ job.status = │              │ UI polls     │◄──┘
│ "completed"  │              │ /api/jobs/id │
└──────────────┘              └──────────────┘
```

---

## File Layout

```
{output_dir}/
├── index.json                              # Central index
├── .ytdl-archive.txt                       # Download tracking
└── {uploader}/
    └── {title} [{id}]/
        ├── {title} [{id}].m4a              # Audio file
        ├── {title} [{id}].txt              # Transcript
        ├── {title} [{id}].srt              # Subtitles (optional)
        └── {title} [{id}].slice_*.txt      # Segment transcripts
```

---

## Configuration

**File**: `config/settings.yaml`

```yaml
download_format: "mp4"
output_path: "./downloads"
max_playlist_items: 25
transcription_language: "auto_detect"
transcription_model: "base"
max_retries: 3
logging_level: "INFO"
```

**Precedence**: CLI flags > YAML config > Defaults

---

## Error Handling

Errors are surfaced to the user with:

1. **Human message**: "Download failed"
2. **Probable cause**: "Video may be private or unavailable"
3. **Actions**: Retry, Copy Diagnostics, Show Details

Raw stack traces are hidden behind "Show Details".

---

## Non-Goals (V1)

- Diarization (speaker identification)
- Cloud storage integration
- Multi-engine transcription plugins
- Heavy job queue orchestration
- Mobile UI

---

## Performance & Resilience

- Audio-only downloads (smaller, faster)
- Idempotent outputs (safe to re-run)
- Download archive prevents duplicates
- Cached Whisper models (no reload between jobs)
- Structured logging for debugging
