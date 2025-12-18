import os
import re
import subprocess
import tempfile
from typing import Optional


_TC = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?$")


def parse_timecode(value: str) -> float:
    """
    Parse HH:MM:SS[.ms] or MM:SS[.ms] into seconds (float).
    Accepts integers as seconds as well.
    """
    s = str(value).strip()
    if s.isdigit():
        return float(int(s))
    m = _TC.match(s)
    if not m:
        raise ValueError(f"Invalid timecode: {value}")
    h = m.group(1)
    mm = int(m.group(2))
    ss = int(m.group(3))
    ms = int(m.group(4) or 0)
    total = (int(h) if h else 0) * 3600 + mm * 60 + ss + ms / 1000.0
    return float(total)


def extract_segment(input_path: str, start: float, end: Optional[float] = None, duration: Optional[float] = None) -> str:
    """
    Use ffmpeg to extract an audio segment as mono 16kHz WAV.
    Returns the path to the generated temporary WAV file.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(input_path)
    if end is None and duration is None:
        raise ValueError("Provide end or duration")
    if end is not None and end <= start:
        raise ValueError("end must be > start")

    # Build ffmpeg args
    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(start),
    ]
    if end is not None:
        args += ["-to", str(end)]
    elif duration is not None:
        args += ["-t", str(duration)]
    args += [
        "-i",
        input_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
    ]

    fd, tmp = tempfile.mkstemp(prefix="yww_slice_", suffix=".wav")
    os.close(fd)
    try:
        subprocess.check_call(args + [tmp])
        return tmp
    except subprocess.CalledProcessError as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise RuntimeError(f"ffmpeg failed: {e}")

