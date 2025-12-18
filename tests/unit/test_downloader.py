# tests/unit/test_downloader.py

import pytest
from yww.downloader import download_video

def test_download_invalid_url(tmp_path):
    """
    Vérifie qu'une URL YouTube invalide déclenche bien une exception.
    """
    cfg = {"download_format": "mp4", "max_retries": 1}
    invalid_url = "https://youtube.com/watch?v=invalid_id"
    with pytest.raises(Exception):
        download_video(invalid_url, str(tmp_path), cfg)
