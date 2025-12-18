# YWW Architecture Overhaul Plan

## User Decisions
- **Keep audio**: Optional checkbox (default OFF)
- **Output format**: SRT with timestamps (default)
- **Index storage**: Full transcript text in index.json (enables search)

---

## Senior Engineering Assessment

### Current State Problems

**1. Storage Bloat (Critical)**
- Downloads folder: **1.05 GB** for just a few videos
- Same video exists as both `.m4a` (292MB) AND `.mp4` (601MB) = 893MB wasted
- Transcripts are tiny (~2KB-86KB) but we're keeping massive media files
- **Root cause**: System downloads full video files, keeps them forever

**2. Bandwidth Waste (Critical)**
- For a 4-hour video with 5-minute transcription target: downloads ENTIRE file
- Range download exists but still downloads to disk first
- No streaming/pipe approach

**3. Architecture Confusion (Medium)**
- `orchestrator.py` vs `scheduler.py` - two paths to same goal
- `download_range()` is just a wrapper around `download_video()`
- Config says `mp4` but code defaults to `bestaudio[ext=m4a]`
- Index has duplicate entries (append-only, no dedup)

**4. What Works Well**
- Resource-aware scheduler (separate pools for I/O vs CPU)
- Model caching and MPS detection
- Structured JSON logging
- Web UI and API design

---

## Target Architecture

### Core Principle: **Audio Stream → Transcribe → Delete**

```
YouTube URL
    ↓
[yt-dlp: extract audio stream info]
    ↓
[Download audio-only to TEMP file]  ← Smallest possible format
    ↓
[Whisper transcribes from temp file]
    ↓
[Save transcript to permanent storage]
    ↓
[DELETE temp audio file]  ← KEY CHANGE
    ↓
Done. Only transcript remains.
```

### Storage Model

**Before (current):**
```
downloads/
├── Lex Fridman/
│   ├── video.mp4      (601 MB)  ← KEPT FOREVER
│   ├── video.m4a      (292 MB)  ← KEPT FOREVER
│   └── video.srt      (86 KB)   ← What we actually want
```

**After (proposed):**
```
transcripts/
├── index.json                    ← Metadata + transcript text
└── Lex Fridman/
    └── video.srt                 (86 KB)  ← Only this!

temp/  ← Auto-cleaned
└── (empty after job completes)
```

---

## Implementation Plan

### Phase 1: Core Pipeline Refactor (Foundation)

**1.1 Create `audio_extractor.py` (NEW)**
- Replace heavy `downloader.py` with lightweight audio extraction
- Download to temp directory only
- Use smallest viable format: `bestaudio[ext=webm]/bestaudio`
- opus/webm is ~50% smaller than m4a for same quality
- Auto-delete after transcription

**1.2 Update `transcriber.py`**
- Accept temp file path
- No changes to transcription logic (it's solid)
- Ensure cleanup callback capability

**1.3 Update `scheduler.py`**
- Modify `_run_download` → `_run_extract_audio`
- Add cleanup in `_run_finalize` or `finally` block
- Track temp file for cleanup

**1.4 Update `storage.py`**
- New storage model: transcripts-only
- Store transcript text in index.json (for search)
- Keep only `.txt`/`.srt`/`.vtt` files
- Add `cleanup_temp()` function

### Phase 2: Config & Defaults Cleanup

**2.1 Fix `config/settings.yaml`**
```yaml
# REMOVE: download_format: "mp4"
audio_format: "bestaudio[ext=webm]/bestaudio"  # Smallest
temp_dir: "./temp"                              # Auto-cleaned
transcripts_dir: "./transcripts"                # Permanent storage
keep_audio: false                               # NEW: option to keep
```

**2.2 Remove/Deprecate**
- `download_format` config key
- `download_range()` function (redundant)
- `download_playlist()` (separate feature, not MVP)

### Phase 3: Clean Architecture

**3.1 Single Pipeline Path**
```
webapp.py → scheduler.py → [extract → transcribe → save → cleanup]
```
Remove `orchestrator.py` or merge into scheduler.

**3.2 Storage Deduplication**
- Index by video_id (unique key)
- Upsert instead of append
- Add schema version field

**3.3 Separate "Download Video" Feature**
- Optional, explicit feature
- Different endpoint: `POST /api/download`
- Different storage: `downloads/` (user manages)
- Not the default flow

### Phase 4: Testing & Stability

**4.1 Add Integration Tests**
- Test full pipeline: URL → transcript file
- Test cleanup: verify temp files deleted
- Test idempotency: same URL twice = no duplicate

**4.2 Error Recovery**
- Cleanup temp files on error
- Retry with exponential backoff
- Circuit breaker for repeated failures

---

## File Changes Summary

| File | Action | Changes |
|------|--------|---------|
| `audio_extractor.py` | CREATE | New lightweight audio extraction |
| `downloader.py` | DEPRECATE | Keep for optional video download feature |
| `scheduler.py` | MODIFY | Use audio_extractor, add cleanup |
| `storage.py` | MODIFY | Transcripts-only model, dedup index |
| `config/settings.yaml` | MODIFY | New defaults, remove download_format |
| `orchestrator.py` | REMOVE | Merge into scheduler |
| `webapp.py` | MODIFY | Update endpoints, add /api/download |

---

## Priority Order

1. **P0 (This Push)**: Audio extraction + temp cleanup + config fix
2. **P1 (Next)**: Storage dedup + remove orchestrator
3. **P2 (Later)**: Optional video download feature
4. **P3 (Future)**: Playlist support, batch processing

---

## Detailed Implementation Steps

### Step 1: Create `audio_extractor.py`
**Path**: `src/yww/audio_extractor.py`

```python
# Core function signature
def extract_audio(
    url: str,
    temp_dir: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    progress_hook: Optional[Callable] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Extract audio to temp file using smallest format.
    Returns (temp_file_path, video_info)
    """
```

Key features:
- Use `bestaudio[ext=webm]/bestaudio` format (opus codec, ~50% smaller)
- Download to system temp dir or `./temp/`
- Support time range extraction
- Return path for transcriber to consume

### Step 2: Modify `scheduler.py`
**Path**: `src/yww/scheduler.py`

Changes:
- Replace `from .downloader import download_video` with `from .audio_extractor import extract_audio`
- Add `keep_audio: bool` to `ScheduledJob` dataclass
- In `_run_download`: extract to temp, store temp path
- In `_run_finalize`: cleanup temp file unless `keep_audio=True`
- Add cleanup in `except` block for error cases

### Step 3: Modify `storage.py`
**Path**: `src/yww/storage.py`

Changes:
- New function `save_transcript(video_id, text, segments, metadata) -> str`
- Store full text + segments in index.json
- Use video_id as unique key (upsert, not append)
- New index schema:
```json
{
  "version": 2,
  "transcripts": {
    "dQw4w9WgXcQ": {
      "title": "...",
      "uploader": "...",
      "url": "...",
      "duration": 213,
      "transcript_file": "transcripts/Rick Astley/video.srt",
      "text": "full transcript text here...",
      "segments": [...],
      "language": "en",
      "model": "small",
      "created_at": "...",
      "updated_at": "..."
    }
  }
}
```

### Step 4: Update `config/settings.yaml`
```yaml
# Audio extraction (replaces download_format)
audio_format: "bestaudio[ext=webm]/bestaudio"
temp_dir: "./temp"
transcripts_dir: "./transcripts"
keep_audio: false  # Default: delete after transcription

# Transcription
transcription_model: "small"  # Upgrade from tiny for accuracy
transcription_backend: "faster-whisper"
transcription_compute_type: "int8"
output_format: "srt"  # Default: SRT with timestamps

# Performance
download_workers: 3
transcribe_workers: 1
```

### Step 5: Update `webapp.py`
**Path**: `src/yww/webapp.py`

Changes to `ProcessRequest`:
```python
class ProcessRequest(BaseModel):
    url: str
    model: str = "small"
    lang: str = "auto"
    format: str = "srt"        # NEW: output format
    keep_audio: bool = False   # NEW: optional keep
    start_time: Optional[str] = None
    end_time: Optional[str] = None
```

Update UI (`static/index.html`):
- Add "Keep audio file" checkbox (unchecked by default)
- Change default format dropdown to SRT
- Update output path label: "Transcripts" not "Output"

### Step 6: Update Directory Structure
```
yww_project/
├── transcripts/           # NEW: permanent transcript storage
│   └── {uploader}/
│       └── {title}.srt
├── temp/                  # NEW: auto-cleaned temp files
├── downloads/             # KEEP: for optional "keep audio" feature
└── transcripts_index.json # NEW: replaces downloads_index.json
```

### Step 7: Migration Script (Optional)
- Extract transcripts from existing downloads
- Build new index from existing .txt/.srt files
- Optionally delete media files (with user confirmation)

---

## Files to Modify/Create

| File | Action | Priority |
|------|--------|----------|
| `src/yww/audio_extractor.py` | CREATE | P0 |
| `src/yww/scheduler.py` | MODIFY | P0 |
| `src/yww/storage.py` | MODIFY | P0 |
| `config/settings.yaml` | MODIFY | P0 |
| `src/yww/webapp.py` | MODIFY | P0 |
| `src/yww/static/index.html` | MODIFY | P0 |
| `src/yww/static/js/app.js` | MODIFY | P0 |
| `src/yww/orchestrator.py` | REMOVE | P1 |
| `src/yww/downloader.py` | KEEP (optional feature) | P2 |

---

## Testing Checklist

- [ ] New transcription: URL → SRT file created, no audio file remains
- [ ] Keep audio: checkbox ON → audio file preserved
- [ ] Time range: partial transcription works
- [ ] Search: can find text in index.json
- [ ] Cleanup: temp files deleted on success AND error
- [ ] Idempotency: same URL twice → updates existing entry
