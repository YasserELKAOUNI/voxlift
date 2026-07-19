import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "download_video.py"
SPEC = importlib.util.spec_from_file_location("download_video_tool", MODULE_PATH)
download_video_tool = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(download_video_tool)


def test_selects_native_h264_480p_when_available():
    formats = [
        {"format_id": "397", "ext": "mp4", "height": 480, "vcodec": "av01.0.04M.08", "acodec": "none", "tbr": 600},
        {"format_id": "135", "ext": "mp4", "height": 480, "vcodec": "avc1.4d401f", "acodec": "none", "tbr": 900},
        {"format_id": "136", "ext": "mp4", "height": 720, "vcodec": "avc1.64001f", "acodec": "none", "tbr": 1800},
    ]

    assert download_video_tool.select_video_format(formats, 480) == ("135", False, 480)


def test_selects_next_higher_source_when_480p_is_missing():
    formats = [
        {"format_id": "134", "ext": "mp4", "height": 360, "vcodec": "avc1.4d401e", "acodec": "none", "tbr": 500},
        {"format_id": "136", "ext": "mp4", "height": 720, "vcodec": "avc1.64001f", "acodec": "none", "tbr": 2000},
        {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1.640028", "acodec": "none", "tbr": 4000},
    ]

    assert download_video_tool.select_video_format(formats, 480) == ("136", True, 720)


def test_selects_format_140_audio_when_available():
    formats = [
        {"format_id": "139", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.5", "abr": 49},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129},
    ]

    assert download_video_tool.select_audio_format(formats) == "140"


def test_find_downloaded_file_treats_video_id_brackets_literally(tmp_path):
    target = tmp_path / "Jayden Raith" / "Example [abc-123_DEF].mp4"
    target.parent.mkdir()
    target.write_text("placeholder")

    assert download_video_tool.find_downloaded_file(tmp_path, "abc-123_DEF", ".mp4") == target
