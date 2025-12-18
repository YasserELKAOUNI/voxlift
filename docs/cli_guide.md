# Voxlift CLI Guide

A command-line interface for transcribing YouTube videos locally, with full privacy and no cloud dependencies.

---

## Installation

```bash
git clone https://github.com/YasserELKAOUNI/voxlift.git
cd voxlift
python3 -m venv .venv && source .venv/bin/activate
pip install poetry && poetry install
```

Verify installation:

```bash
python -m src.yww.cli --version
```

---

## Quick Start

Transcribe a video in one command:

```bash
python -m src.yww.cli transcribe "https://youtube.com/watch?v=dQw4w9WgXcQ"
```

Or start the web UI:

```bash
python -m src.yww.cli serve
```

---

## Commands

### `transcribe`

Transcribe a YouTube video to text.

```bash
python -m src.yww.cli transcribe [OPTIONS] URL
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `URL` | YouTube video URL (required) |

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--model` | `-m` | `small` | Whisper model size |
| `--lang` | `-l` | `auto` | Language code or auto-detect |
| `--output` | `-o` | `./transcripts` | Output directory |
| `--format` | `-f` | `srt` | Output format: srt, vtt, txt |
| `--start` | `-s` | — | Start time (e.g., `1:30`) |
| `--end` | `-e` | — | End time (e.g., `5:00`) |
| `--keep-audio` | `-k` | `false` | Keep audio file after transcription |
| `--force` | — | `false` | Re-transcribe even if exists |
| `--quiet` | `-q` | `false` | Minimal output |
| `--json` | — | `false` | JSON output for scripting |

**Examples:**

```bash
# Basic transcription
python -m src.yww.cli transcribe "https://youtube.com/watch?v=..."

# Use medium model with English language
python -m src.yww.cli transcribe URL -m medium -l en

# Transcribe only a specific time range
python -m src.yww.cli transcribe URL --start 1:30 --end 5:00

# Output as plain text instead of SRT
python -m src.yww.cli transcribe URL --format txt

# Quiet mode for scripts
python -m src.yww.cli transcribe URL -q

# JSON output for automation
python -m src.yww.cli transcribe URL --json
```

---

### `serve`

Start the web UI server.

```bash
python -m src.yww.cli serve [OPTIONS]
```

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--port` | `-p` | `8765` | Port number |
| `--host` | `-h` | `127.0.0.1` | Host address |
| `--no-browser` | — | `false` | Don't open browser automatically |

**Examples:**

```bash
# Start with default settings (opens browser)
python -m src.yww.cli serve

# Custom port
python -m src.yww.cli serve --port 9000

# Don't open browser
python -m src.yww.cli serve --no-browser

# Listen on all interfaces
python -m src.yww.cli serve --host 0.0.0.0
```

---

### `list`

List all transcripts in the index.

```bash
python -m src.yww.cli list [OPTIONS]
```

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output` | `-o` | `./transcripts` | Transcripts directory |
| `--limit` | `-n` | `20` | Maximum items to display |

**Examples:**

```bash
# List recent transcripts
python -m src.yww.cli list

# Show more items
python -m src.yww.cli list -n 50

# Use custom directory
python -m src.yww.cli list -o ~/Documents/MyTranscripts
```

---

### `search`

Search within transcript contents.

```bash
python -m src.yww.cli search [OPTIONS] QUERY
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `QUERY` | Search term (required) |

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output` | `-o` | `./transcripts` | Transcripts directory |
| `--limit` | `-n` | `10` | Maximum results to display |

**Examples:**

```bash
# Search for a phrase
python -m src.yww.cli search "machine learning"

# Limit results
python -m src.yww.cli search "hello world" -n 5
```

---

### `info`

Display system information and configuration status.

```bash
python -m src.yww.cli info
```

**Output includes:**

- Version number
- Compute device (cpu, mps, cuda)
- MPS availability (Apple Silicon)
- Transcription backend
- Compute type
- Cached models

---

### `open-folder`

Open the transcripts folder in Finder.

```bash
python -m src.yww.cli open-folder [OPTIONS]
```

**Options:**

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output` | `-o` | `./transcripts` | Transcripts directory |

---

## Models

Voxlift uses OpenAI Whisper models via the faster-whisper backend.

| Model | Speed | Accuracy | Memory |
|-------|-------|----------|--------|
| `tiny` | Fastest | Basic | ~1 GB |
| `base` | Fast | Good | ~1 GB |
| `small` | Balanced | Better | ~2 GB |
| `medium` | Slow | High | ~5 GB |
| `large` | Slowest | Best | ~10 GB |

**Recommendation:** Start with `small` (default). Use `medium` or `large` for difficult audio (accents, background noise, technical content).

---

## Time Formats

Time ranges accept multiple formats:

| Format | Example | Seconds |
|--------|---------|---------|
| Seconds | `90` | 90 |
| MM:SS | `1:30` | 90 |
| HH:MM:SS | `1:30:00` | 5400 |
| With ms | `1:30.500` | 90.5 |

---

## Output Formats

| Format | Extension | Description |
|--------|-----------|-------------|
| `srt` | `.srt` | SubRip subtitles with timestamps |
| `vtt` | `.vtt` | WebVTT subtitles |
| `txt` | `.txt` | Plain text without timestamps |

---

## Output Structure

Transcripts are organized by uploader:

```
transcripts/
├── transcripts_index.json
└── {Channel Name}/
    └── {Video Title} [video_id].srt
```

The index file contains metadata and full transcript text for search functionality.

---

## JSON Output

For scripting and automation, use `--json`:

```bash
python -m src.yww.cli transcribe URL --json
```

**Success response:**

```json
{
  "status": "success",
  "video_id": "dQw4w9WgXcQ",
  "title": "Video Title",
  "duration": 213,
  "language": "en",
  "segments": 69,
  "file": "/path/to/transcript.srt"
}
```

**Error response:**

```json
{
  "status": "error",
  "message": "Error description"
}
```

---

## Shell Completion

Enable tab completion for your shell:

```bash
# Bash
python -m src.yww.cli --install-completion bash

# Zsh
python -m src.yww.cli --install-completion zsh

# Fish
python -m src.yww.cli --install-completion fish
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VOXLIFT_OUTPUT` | Default output directory |
| `VOXLIFT_MODEL` | Default Whisper model |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (check stderr or JSON output) |

---

## Examples

### Batch Processing

```bash
# Process multiple URLs
for url in "URL1" "URL2" "URL3"; do
  python -m src.yww.cli transcribe "$url" -q
done
```

### Extract Specific Segment

```bash
# Transcribe only minutes 5-10
python -m src.yww.cli transcribe URL --start 5:00 --end 10:00
```

### CI/CD Integration

```bash
# JSON output for parsing
result=$(python -m src.yww.cli transcribe URL --json)
file=$(echo "$result" | jq -r '.file')
```

---

## Troubleshooting

### "MPS not available"

Ensure you're running on Apple Silicon (M1/M2) with macOS 12.3+.

### "Model not found"

Models are downloaded automatically on first use. Ensure internet connectivity.

### "FFmpeg not found"

Install FFmpeg:

```bash
brew install ffmpeg
```

### Slow transcription

- Use a smaller model (`tiny` or `base`)
- Transcribe only the needed time range
- Ensure no other heavy processes are running

---

## See Also

- [README.md](../README.md) — Project overview
- [Architecture](architecture.md) — Technical documentation
- Web UI — `python -m src.yww.cli serve`
