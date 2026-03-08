# Voxlift Architecture

## Purpose

Voxlift is a local-first YouTube transcription tool for macOS. It downloads audio with `yt-dlp`, transcribes it with `faster-whisper`, and stores searchable transcript artifacts on disk.

## Main flow

1. The user submits a YouTube URL from the CLI or web UI.
2. `audio_extractor.py` downloads audio-only media to a temp location.
3. `transcriber.py` runs local speech-to-text with `faster-whisper`.
4. `storage.py` writes the transcript file and updates the v2 transcript index.
5. `scheduler.py` coordinates extract/transcribe/save work for the web UI.

## Runtime modules

- `src/voxlift/cli.py`
  Main CLI entrypoint exposed as `voxlift` and `vox`.
- `src/voxlift/webapp.py`
  FastAPI app serving the web UI and job APIs.
- `src/voxlift/scheduler.py`
  Resource-aware async job scheduler used by the web app.
- `src/voxlift/audio_extractor.py`
  Temp-file-oriented audio extraction for transcription jobs.
- `src/voxlift/transcriber.py`
  Local transcription backend with model caching and progress events.
- `src/voxlift/storage.py`
  Transcript persistence and searchable index management.
- `src/voxlift/media.py`
  Timecode parsing and local media segment helpers.

## Storage model

- Transcript files are stored under `transcripts/{uploader}/`.
- The searchable index is stored in `transcripts_index.json`.
- Temp audio goes to the configured `temp/` directory and is deleted unless `keep_audio` is enabled.

## Boundaries

- Offline transcription is supported for local files when the required Whisper model is already cached.
- YouTube extraction still requires network access.
- Slow tests that hit real external services are marked `slow` and are excluded from the default test run.
