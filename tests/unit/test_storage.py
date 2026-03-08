# tests/unit/test_storage.py

import json

from voxlift.storage import _load_index, list_transcripts, save_transcript, search_transcripts


def test_save_transcript_persists_file_and_v2_index(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    index_file = tmp_path / "index.json"

    path = save_transcript(
        video_id="abc123xyz00",
        text="hello world from voxlift",
        segments=[{"start": 0.0, "end": 1.2, "text": "hello world"}],
        metadata={
            "title": "Demo / Video",
            "uploader": "Channel:Name",
            "webpage_url": "https://youtu.be/example",
            "duration": 12,
            "language": "en",
            "model": "small",
        },
        output_format="txt",
        transcripts_dir=str(transcripts_dir),
        index_file=str(index_file),
    )

    assert path.endswith("Demo _ Video [abc123xyz00].txt")
    assert "Channel_Name" in path
    assert json.loads(index_file.read_text())["version"] == 2
    assert "hello world from voxlift" == open(path, encoding="utf-8").read()


def test_save_transcript_upserts_existing_entry(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    index_file = tmp_path / "index.json"

    save_transcript(
        video_id="dup12345678",
        text="first text",
        segments=[],
        metadata={"title": "Video", "uploader": "Uploader"},
        output_format="txt",
        transcripts_dir=str(transcripts_dir),
        index_file=str(index_file),
    )
    save_transcript(
        video_id="dup12345678",
        text="second text",
        segments=[],
        metadata={"title": "Video", "uploader": "Uploader"},
        output_format="txt",
        transcripts_dir=str(transcripts_dir),
        index_file=str(index_file),
    )

    data = _load_index(str(index_file))
    assert list(data["transcripts"]) == ["dup12345678"]
    assert data["transcripts"]["dup12345678"]["text"] == "second text"


def test_search_and_list_transcripts_use_v2_index(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    index_file = tmp_path / "index.json"

    save_transcript(
        video_id="video000001",
        text="alpha beta gamma",
        segments=[],
        metadata={"title": "Alpha", "uploader": "One"},
        output_format="txt",
        transcripts_dir=str(transcripts_dir),
        index_file=str(index_file),
    )
    save_transcript(
        video_id="video000002",
        text="delta epsilon zeta",
        segments=[],
        metadata={"title": "Delta", "uploader": "Two"},
        output_format="txt",
        transcripts_dir=str(transcripts_dir),
        index_file=str(index_file),
    )

    results = search_transcripts("epsilon", index_file=str(index_file))
    assert len(results) == 1
    assert results[0]["video_id"] == "video000002"

    listed = list_transcripts(index_file=str(index_file))
    assert [item["video_id"] for item in listed] == ["video000002", "video000001"]


def test_load_index_migrates_v1_array_format(tmp_path):
    index_file = tmp_path / "legacy.json"
    index_file.write_text(
        json.dumps([
            {"id": "abc", "title": "Old A"},
            {"id": "def", "title": "Old B"},
        ]),
        encoding="utf-8",
    )

    data = _load_index(str(index_file))

    assert data["version"] == 2
    assert set(data["transcripts"]) == {"abc", "def"}
