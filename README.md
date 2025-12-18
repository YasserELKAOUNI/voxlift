# Voxlift

**Privacy-first local YouTube transcription for Mac**

Paste a YouTube URL, get a transcript. No cloud, no data leaving your machine.

## Features

- **Local processing**: Whisper runs on your Mac (MPS/Metal acceleration on M1/M2)
- **Minimal bandwidth**: Audio-only extraction, smallest format (opus/webm)
- **Clean storage**: Transcripts only, temp files auto-deleted
- **Multiple formats**: SRT (default), VTT, plain text
- **Time range support**: Transcribe specific portions of videos
- **Full-text search**: Index stores complete transcript text

## Quick Start

```bash
# Clone and setup
git clone https://github.com/YOUR_USERNAME/voxlift.git
cd voxlift
python3 -m venv .venv && source .venv/bin/activate
pip install poetry && poetry install

# Run web UI
python -m src.yww.webapp
# Open http://localhost:8765
```

## Requirements

- macOS (optimized for Apple Silicon M1/M2)
- Python 3.11+
- FFmpeg (`brew install ffmpeg`)

## Usage

### Web UI (Recommended)

```bash
python -m src.yww.webapp
```

Open `http://localhost:8765`, paste a YouTube URL, click Transcribe.

### CLI

```bash
# Process single video
python -m src.yww.cli process -u "https://youtube.com/watch?v=..." -m small

# With time range
python -m src.yww.cli process -u "URL" --start 1:30 --end 5:00
```

## Output

```
transcripts/
├── index.json              # Metadata + full text (searchable)
└── {Channel Name}/
    └── {Video Title} [id].srt
```

## Configuration

Edit `config/settings.yaml`:

```yaml
transcription_model: small    # tiny, base, small, medium, large
output_format: srt            # srt, vtt, txt
keep_audio: false             # Delete audio after transcription
```

## Models

| Model | Speed | Accuracy | VRAM |
|-------|-------|----------|------|
| tiny | Fastest | Basic | ~1GB |
| base | Fast | Good | ~1GB |
| small | Balanced | Better | ~2GB |
| medium | Slow | High | ~5GB |
| large | Slowest | Best | ~10GB |

## Architecture

- **audio_extractor.py**: Lightweight yt-dlp wrapper, temp file management
- **transcriber.py**: faster-whisper with MPS acceleration
- **storage.py**: Index v2 schema with deduplication
- **scheduler.py**: Resource-aware job pools (3 extract, 1 transcribe)
- **webapp.py**: FastAPI + static web UI

## Testing

```bash
# Run all tests (excluding slow network tests)
pytest tests/ -m "not slow"

# Run all tests including E2E
pytest tests/ -v
```

## License

MIT
