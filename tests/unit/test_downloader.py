# tests/unit/test_downloader.py
import pytest

from voxlift.downloader import DownloadError, download_video


def test_download_video_uses_progress_hook_and_returns_path(tmp_path, monkeypatch):
    progress_events = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
            return {"id": "abc123xyz00", "title": "Demo", "uploader": "Channel"}

        def prepare_filename(self, info):
            path = tmp_path / "Channel" / "Demo [abc123xyz00].m4a"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("audio", encoding="utf-8")
            return str(path)

    monkeypatch.setattr("voxlift.downloader.YoutubeDL", FakeYoutubeDL)

    path, info = download_video(
        "https://youtube.com/watch?v=abc123xyz00",
        str(tmp_path),
        {"download_format": "bestaudio", "max_retries": 1},
        progress_hook=lambda payload: progress_events.append(payload),
    )

    assert path.endswith("Demo [abc123xyz00].m4a")
    assert info["id"] == "abc123xyz00"
    assert progress_events[0]["downloaded_bytes"] == 5


def test_download_invalid_url_raises_after_retries(tmp_path, monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, _opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            raise DownloadError(f"boom for {url}")

    monkeypatch.setattr("voxlift.downloader.YoutubeDL", FakeYoutubeDL)

    cfg = {"download_format": "mp4", "max_retries": 2}
    with pytest.raises(DownloadError):
        download_video("https://youtube.com/watch?v=invalid_id", str(tmp_path), cfg)
