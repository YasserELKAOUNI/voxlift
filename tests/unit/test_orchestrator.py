from pathlib import Path

from voxlift.orchestrator import process_url
from voxlift.storage import sanitize_filename


def test_process_url_transcribes_and_cleans_temp_file(tmp_path, monkeypatch):
    temp_audio = tmp_path / "temp" / "clip.webm"
    temp_audio.parent.mkdir(parents=True, exist_ok=True)
    temp_audio.write_text("audio", encoding="utf-8")

    events = []
    saved = {}

    monkeypatch.setattr(
        "voxlift.orchestrator.extract_audio",
        lambda **kwargs: (
            str(temp_audio),
            {
                "id": "abc123xyz00",
                "title": "Demo Video",
                "uploader": "Demo Channel",
                "duration": 42,
                "webpage_url": kwargs["url"],
            },
        ),
    )
    monkeypatch.setattr(
        "voxlift.orchestrator.transcribe_audio",
        lambda *args, **kwargs: {
            "text": "hello world",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
            "language": "en",
        },
    )

    def fake_save_transcript(video_id, text, segments, metadata, output_format, transcripts_dir):
        output_path = (
            Path(transcripts_dir)
            / sanitize_filename(metadata["uploader"])
            / f"{sanitize_filename(metadata['title'])} [{video_id}].{output_format}"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        saved["path"] = str(output_path)
        saved["metadata"] = metadata
        return str(output_path)

    monkeypatch.setattr("voxlift.orchestrator.save_transcript", fake_save_transcript)

    cleaned = []

    def fake_cleanup(path):
        cleaned.append(path)
        Path(path).unlink(missing_ok=True)
        return True

    monkeypatch.setattr("voxlift.orchestrator.cleanup_temp_file", fake_cleanup)

    result = process_url(
        url="https://youtube.com/watch?v=abc123xyz00",
        output_dir=str(tmp_path / "transcripts"),
        config={"output_format": "txt", "transcription_model": "small"},
        event_cb=lambda event, payload: events.append((event, payload)),
        start_time="0:10",
        end_time="0:20",
    )

    assert result["transcript"] == saved["path"]
    assert Path(saved["path"]).read_text(encoding="utf-8") == "hello world"
    assert cleaned == [str(temp_audio)]
    assert any(event == "transcribed" for event, _ in events)
    assert result["meta"]["title"].endswith(".0m10s-0m20s")


def test_process_url_skips_existing_transcript(tmp_path, monkeypatch):
    temp_audio = tmp_path / "temp" / "clip.webm"
    temp_audio.parent.mkdir(parents=True, exist_ok=True)
    temp_audio.write_text("audio", encoding="utf-8")

    video_id = "abc123xyz00"
    uploader = "Demo Channel"
    title = "Existing Video"
    transcript_path = (
        tmp_path
        / "transcripts"
        / sanitize_filename(uploader)
        / f"{sanitize_filename(title)} [{video_id}].txt"
    )
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("already done", encoding="utf-8")

    monkeypatch.setattr(
        "voxlift.orchestrator.extract_audio",
        lambda **kwargs: (
            str(temp_audio),
            {
                "id": video_id,
                "title": title,
                "uploader": uploader,
                "duration": 42,
                "webpage_url": kwargs["url"],
            },
        ),
    )
    monkeypatch.setattr(
        "voxlift.orchestrator.transcribe_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not transcribe")),
    )

    cleaned = []
    monkeypatch.setattr(
        "voxlift.orchestrator.cleanup_temp_file",
        lambda path: cleaned.append(path) or Path(path).unlink(missing_ok=True) or True,
    )

    result = process_url(
        url="https://youtube.com/watch?v=abc123xyz00",
        output_dir=str(tmp_path / "transcripts"),
        config={"output_format": "txt"},
        force=False,
    )

    assert result["transcript"] == str(transcript_path)
    assert result["meta"]["language"] == "auto"
    assert cleaned == [str(temp_audio)]
