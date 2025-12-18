# tests/unit/test_storage.py

import json
import os
import pytest
from pathlib import Path
from yww.storage import generate_filename, save_file, persist_transcript, DEFAULT_INDEX_FILE

@pytest.fixture(autouse=True)
def clean_tmp(tmp_path, monkeypatch):
    # Change l'index pour être dans tmp
    monkeypatch.setattr("yww.storage.DEFAULT_INDEX_FILE", str(tmp_path / "idx.json"))
    yield
    # Aucun cleanup nécessaire, tmp_path est isolé

def test_generate_filename_basic():
    meta = {"title": "Foo", "id": "X1", "ext": "mkv"}
    name = generate_filename("{title}-{id}.{ext}", meta)
    assert name == "Foo-X1.mkv"

def test_save_file_creates_and_suffix(tmp_path):
    # Prépare un fichier source
    src = tmp_path / "a.txt"
    src.write_text("hello")
    # 1re sauvegarde
    out = save_file(str(src), str(tmp_path / "out"), "a.txt")
    assert os.path.exists(out)
    # 2e sauvegarde => suffix (1)
    out2 = save_file(str(src), str(tmp_path / "out"), "a.txt")
    assert out2.endswith("a(1).txt")

def test_persist_transcript_and_index(tmp_path):
    meta = {"title": "Bar", "id": "Y2"}
    text = "contenu de test"
    outdir = tmp_path / "outtx"
    tx_path = persist_transcript(meta, text, str(outdir), format="txt")
    assert Path(tx_path).exists()
    # Vérifie le contenu du transcript
    assert (outdir / "Bar_Y2.txt").read_text() == text
    # Vérifie l'index JSON
    idx = json.loads(open(DEFAULT_INDEX_FILE).read())
    assert isinstance(idx, list)
    assert any(rec["id"] == "Y2" for rec in idx)
