# Video Download Procedure

This procedure archives a YouTube video as an MP4 in `~/Documents/5_Notes/<Uploader>/`.
It is separate from the normal Voxlift transcription flow, which downloads audio-only media.

## One-command workflow

Clone the repo, install dependencies, and run the helper:

```bash
git clone git@github.com:YasserELKAOUNI/voxlift.git
cd voxlift
python3 -m venv .venv
.venv/bin/python -m pip install -U pip yt-dlp
brew install ffmpeg
```

Then run:

```bash
python tools/download_video.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Defaults:

- Target quality: `480p`
- Temporary download folder: `downloads/`
- Final folder: `~/Documents/5_Notes/<Uploader>/`
- FFmpeg location: `/opt/homebrew/bin`
- Preferred format: MP4 video plus M4A/AAC audio

The tool can also be run from outside the repository because it infers the repo root from its own path:

```bash
python /path/to/voxlift/tools/download_video.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Useful options:

```bash
# Explicit 480p
python tools/download_video.py --quality 480 "https://www.youtube.com/watch?v=VIDEO_ID"

# Replace an existing archived file
python tools/download_video.py --force "https://www.youtube.com/watch?v=VIDEO_ID"

# Use another destination root
python tools/download_video.py --notes-dir "$HOME/Documents/5_Notes" "https://www.youtube.com/watch?v=VIDEO_ID"
```

## What the tool does

1. Reads YouTube metadata with `yt-dlp -J --no-playlist`.
2. Selects a video-only MP4 stream at the requested height when it exists.
3. Selects M4A/AAC audio, preferring format `140`.
4. Downloads and merges both streams into MP4 with `yt-dlp`.
5. If YouTube does not offer the requested height, downloads the nearest higher MP4 stream and transcodes down with `ffmpeg`.
6. Verifies the final file with `ffprobe`.
7. Moves the final MP4 into `~/Documents/5_Notes/<Uploader>/`.

## Exact manual commands

Inspect formats:

```bash
.venv/bin/yt-dlp -F "https://www.youtube.com/watch?v=VIDEO_ID"
```

When native 480p exists, use video format `135` plus audio format `140`:

```bash
.venv/bin/yt-dlp --ffmpeg-location /opt/homebrew/bin --no-playlist \
  -f "135+140" --merge-output-format mp4 \
  -o "downloads/%(uploader)s/%(title)s [%(id)s].%(ext)s" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

Verify the merged MP4:

```bash
/opt/homebrew/bin/ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,codec_name,avg_frame_rate \
  -of default=noprint_wrappers=1:nokey=0 "downloads/<Uploader>/<File>.mp4"

/opt/homebrew/bin/ffprobe -v error -select_streams a:0 \
  -show_entries stream=codec_name,channels,sample_rate \
  -of default=noprint_wrappers=1:nokey=0 "downloads/<Uploader>/<File>.mp4"

/opt/homebrew/bin/ffprobe -v error \
  -show_entries format=duration,size \
  -of default=noprint_wrappers=1:nokey=0 "downloads/<Uploader>/<File>.mp4"
```

Move the file:

```bash
mkdir -p "$HOME/Documents/5_Notes/<Uploader>"
mv "downloads/<Uploader>/<File>.mp4" "$HOME/Documents/5_Notes/<Uploader>/"
rmdir "downloads/<Uploader>" 2>/dev/null || true
```

## Missing native 480p

Some videos offer `360p` and `720p`, but not `480p`. In that case, download `720p`
and transcode to 480p:

```bash
.venv/bin/yt-dlp --ffmpeg-location /opt/homebrew/bin --no-playlist \
  -f "136+140" --merge-output-format mp4 \
  -o "downloads/%(uploader)s/%(title)s [%(id)s].source.%(ext)s" \
  "https://www.youtube.com/watch?v=VIDEO_ID"

/opt/homebrew/bin/ffmpeg -y -i "downloads/<Uploader>/<File>.source.mp4" \
  -vf "scale=-2:480" \
  -c:v libx264 -preset veryfast -crf 23 \
  -c:a copy \
  "downloads/<Uploader>/<File>.mp4"
```

Then verify with `ffprobe`, move the final MP4 into `~/Documents/5_Notes/<Uploader>/`,
and delete the `.source.mp4` file unless you intentionally want to keep it.

## Notes

- A URL timestamp like `&t=292s` only controls playback start in YouTube. This procedure downloads the full video.
- The `downloads/` folder is temporary and ignored by git.
- The archived MP4 files under `~/Documents/5_Notes/` are user content and are not committed.
- Keep `yt-dlp` current. YouTube extractor changes often, so update with `.venv/bin/python -m pip install -U yt-dlp` if format listing or download fails.
- If YouTube extraction warns about JavaScript runtimes but still lists formats, the download can continue.
