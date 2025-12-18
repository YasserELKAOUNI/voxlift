# tests/unit/test_transcriber.py

import os
import pytest
import whisper
from yww.transcriber import transcribe_audio

class DummyModel:
    def transcribe(self, file_path, language="auto"):
        return {"text": "dummy text", "segments": []}

@pytest.fixture(autouse=True)
def patch_load_model(monkeypatch):
    # Monkeypatch whisper.load_model pour renvoyer DummyModel
    monkeypatch.setattr(whisper, "load_model", lambda size: DummyModel())
    yield

def test_transcribe_file_not_found():
    with pytest.raises(FileNotFoundError):
        transcribe_audio("no_such_file.mp3")

def test_transcribe_returns_text(tmp_path):
    # Crée un fichier dummy
    f = tmp_path / "dummy.wav"
    f.write_bytes(b"")
    res = transcribe_audio(str(f), language="en", model_size="tiny")
    assert isinstance(res, dict)
    assert res["text"] == "dummy text"

def test_transcribe_writes_output_file(tmp_path):
    f = tmp_path / "dummy2.wav"
    f.write_bytes(b"")
    outdir = tmp_path / "out"
    res = transcribe_audio(str(f), language="en", model_size="tiny", output_format="txt", output_dir=str(outdir))
    out_path = outdir / f"{f.stem}.txt"
    assert out_path.exists()
    assert out_path.read_text() == "dummy text"
    assert res["output_file"] == str(out_path)
