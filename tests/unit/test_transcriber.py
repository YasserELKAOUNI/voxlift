# tests/unit/test_transcriber.py
import pytest
import whisper

from voxlift.transcriber import transcribe_audio


@pytest.fixture(autouse=True)
def patch_audio_loading(monkeypatch):
    monkeypatch.setattr(whisper, "load_audio", lambda _path: [0] * whisper.audio.SAMPLE_RATE)


@pytest.fixture
def patch_faster_whisper(monkeypatch):
    calls = {}

    def fake_transcribe(file_path, language, model_size, compute_type, num_workers):
        calls["args"] = {
            "file_path": file_path,
            "language": language,
            "model_size": model_size,
            "compute_type": compute_type,
            "num_workers": num_workers,
        }
        return (
            "dummy text",
            [{"start": 0.0, "end": 1.0, "text": "dummy text"}],
            language,
        )

    monkeypatch.setattr(
        "voxlift.transcriber._transcribe_with_faster_whisper",
        fake_transcribe,
    )
    return calls

def test_transcribe_file_not_found():
    with pytest.raises(FileNotFoundError):
        transcribe_audio("no_such_file.mp3")

def test_transcribe_returns_text(tmp_path, patch_faster_whisper):
    f = tmp_path / "dummy.wav"
    f.write_bytes(b"")
    res = transcribe_audio(str(f), language="en", model_size="tiny")

    assert isinstance(res, dict)
    assert res["text"] == "dummy text"
    assert res["backend"] == "faster-whisper"
    assert patch_faster_whisper["args"]["compute_type"] == "int8"

def test_transcribe_writes_output_file(tmp_path, patch_faster_whisper):
    f = tmp_path / "dummy2.wav"
    f.write_bytes(b"")
    outdir = tmp_path / "out"
    res = transcribe_audio(str(f), language="en", model_size="tiny", output_format="txt", output_dir=str(outdir))

    out_path = outdir / f"{f.stem}.txt"
    assert out_path.exists()
    assert out_path.read_text() == "dummy text"
    assert res["output_file"] == str(out_path)
