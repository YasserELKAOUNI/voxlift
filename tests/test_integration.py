# tests/test_integration.py
"""
Integration tests for YWW transcription pipeline.

These tests verify the core functionality works end-to-end.
Run with: pytest tests/test_integration.py -v
"""

import os
import pytest
import tempfile
import json
from pathlib import Path

# Test video URLs - short videos for fast testing
TEST_VIDEOS = {
    "rick_astley": {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "id": "dQw4w9WgXcQ",
        "title_contains": "Never Gonna Give You Up",
        "duration_approx": 212,  # ~3:32
    },
    # Short educational video (~1 min)
    "3blue1brown_short": {
        "url": "https://www.youtube.com/watch?v=r6sGWTCMz2k",
        "id": "r6sGWTCMz2k",
        "title_contains": "essence",
        "duration_approx": 60,
    },
}


class TestModuleImports:
    """Test that all modules can be imported."""

    def test_import_audio_extractor(self):
        from src.yww import audio_extractor
        assert hasattr(audio_extractor, 'extract_audio')
        assert hasattr(audio_extractor, 'cleanup_temp_file')

    def test_import_storage(self):
        from src.yww import storage
        assert hasattr(storage, 'save_transcript')
        assert hasattr(storage, 'search_transcripts')
        assert hasattr(storage, 'list_transcripts')

    def test_import_scheduler(self):
        from src.yww import scheduler
        assert hasattr(scheduler, 'submit_job')
        assert hasattr(scheduler, 'get_scheduler')
        assert hasattr(scheduler, 'JobPhase')

    def test_import_transcriber(self):
        from src.yww import transcriber
        assert hasattr(transcriber, 'transcribe_audio')
        assert hasattr(transcriber, 'preload_model')
        assert hasattr(transcriber, 'get_model_info')

    def test_import_config_manager(self):
        from src.yww import config_manager
        assert hasattr(config_manager, 'load_config_file')


class TestConfigManager:
    """Test configuration loading."""

    def test_load_config(self):
        from src.yww.config_manager import load_config_file
        cfg = load_config_file()

        # Check required keys exist
        assert 'transcription_model' in cfg
        assert 'output_format' in cfg
        assert 'transcription_backend' in cfg

    def test_config_defaults(self):
        from src.yww.config_manager import load_config_file
        cfg = load_config_file()

        # Verify our new defaults
        assert cfg.get('output_format') == 'srt'
        assert cfg.get('transcription_model') == 'small'
        assert cfg.get('keep_audio') == False


class TestStorage:
    """Test storage functions."""

    def test_sanitize_filename(self):
        from src.yww.storage import sanitize_filename

        # Test basic sanitization
        assert sanitize_filename("Hello World") == "Hello World"
        assert sanitize_filename("Hello/World") == "Hello_World"
        assert sanitize_filename("Hello:World") == "Hello_World"
        assert sanitize_filename("Hello\nWorld") == "Hello_World"

        # Test length limit
        long_name = "A" * 200 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 180

    def test_srt_time_formatting(self):
        from src.yww.storage import _format_srt_time

        assert _format_srt_time(0) == "00:00:00,000"
        assert _format_srt_time(61.5) == "00:01:01,500"
        assert _format_srt_time(3661.123) == "01:01:01,123"

    def test_index_load_empty(self):
        from src.yww.storage import _load_index

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            os.unlink(temp_path)  # Ensure it doesn't exist
            result = _load_index(temp_path)
            assert result['version'] == 2
            assert result['transcripts'] == {}
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_save_and_load_transcript(self):
        from src.yww.storage import save_transcript, get_transcript, _load_index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, 'index.json')
            transcripts_dir = os.path.join(tmpdir, 'transcripts')

            # Save a transcript
            video_id = "test123"
            text = "Hello world, this is a test."
            segments = [
                {"start": 0.0, "end": 2.0, "text": "Hello world,"},
                {"start": 2.0, "end": 4.0, "text": "this is a test."},
            ]
            metadata = {
                "title": "Test Video",
                "uploader": "Test Channel",
                "duration": 4,
            }

            filepath = save_transcript(
                video_id=video_id,
                text=text,
                segments=segments,
                metadata=metadata,
                output_format="srt",
                transcripts_dir=transcripts_dir,
                index_file=index_file,
            )

            # Verify file was created
            assert os.path.exists(filepath)
            assert filepath.endswith('.srt')

            # Verify index was updated
            entry = get_transcript(video_id, index_file)
            assert entry is not None
            assert entry['title'] == "Test Video"
            assert entry['text'] == text
            assert len(entry['segments']) == 2

            # Verify SRT content
            with open(filepath, 'r') as f:
                srt_content = f.read()
            assert "Hello world" in srt_content
            assert "-->" in srt_content  # SRT timestamp format


class TestMediaUtils:
    """Test media utility functions."""

    def test_parse_timecode(self):
        from src.yww.media import parse_timecode

        # Seconds (integer format)
        assert parse_timecode("90") == 90.0

        # MM:SS
        assert parse_timecode("1:30") == 90.0
        assert parse_timecode("01:30") == 90.0

        # HH:MM:SS
        assert parse_timecode("1:30:00") == 5400.0
        assert parse_timecode("01:30:00") == 5400.0

        # With milliseconds (5ms = 0.005 seconds)
        assert parse_timecode("1:30.5") == 90.005
        assert parse_timecode("1:30.500") == 90.5

        # Invalid - raises ValueError
        with pytest.raises(ValueError):
            parse_timecode(None)
        with pytest.raises(ValueError):
            parse_timecode("")


class TestTranscriberInfo:
    """Test transcriber info functions (no actual transcription)."""

    def test_get_model_info(self):
        from src.yww.transcriber import get_model_info

        info = get_model_info()
        assert 'device' in info
        assert 'mps_available' in info
        assert 'cached_models' in info

    def test_device_detection(self):
        from src.yww.transcriber import get_device

        device = get_device()
        # On M1 Mac, should be 'mps' or 'cpu'
        assert device in ['mps', 'cpu', 'cuda']


class TestAudioExtractor:
    """Test audio extractor functions (without actual download)."""

    def test_cleanup_nonexistent_file(self):
        from src.yww.audio_extractor import cleanup_temp_file

        # Should return False for non-existent file
        result = cleanup_temp_file("/nonexistent/path/file.webm")
        assert result == False

    def test_cleanup_existing_file(self):
        from src.yww.audio_extractor import cleanup_temp_file

        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
            f.write(b"test content")

        assert os.path.exists(temp_path)
        result = cleanup_temp_file(temp_path)
        assert result == True
        assert not os.path.exists(temp_path)


@pytest.mark.slow
class TestEndToEnd:
    """
    End-to-end tests that actually download and transcribe.

    These are marked as 'slow' and can be skipped with: pytest -m "not slow"
    """

    def test_audio_extraction_short_video(self):
        """Test audio extraction with a very short video."""
        from src.yww.audio_extractor import extract_audio, cleanup_temp_file

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use a known short video
            url = TEST_VIDEOS["rick_astley"]["url"]

            # Extract only first 10 seconds to keep test fast
            temp_path, info = extract_audio(
                url=url,
                temp_dir=tmpdir,
                start_time=0,
                end_time=10,
            )

            try:
                # Verify file was created
                assert os.path.exists(temp_path)
                assert os.path.getsize(temp_path) > 0

                # Verify info
                assert info.get('id') == TEST_VIDEOS["rick_astley"]["id"]
            finally:
                cleanup_temp_file(temp_path)


# Pytest configuration
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
