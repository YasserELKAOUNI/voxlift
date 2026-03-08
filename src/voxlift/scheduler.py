# src/voxlift/scheduler.py
"""
Resource-aware job scheduler optimized for M1 Mac.

Key design principles:
1. Separate pools for different resource classes:
   - Extract pool: I/O bound, can run 3-4 concurrent (yt-dlp outside GIL)
   - Transcribe pool: CPU/GPU bound, limit to 1-2 workers (memory constraint on M1)

2. Queue with backpressure to prevent memory explosion

3. Pseudo-streaming: Start transcription as soon as extraction completes,
   don't wait for all extractions in a batch

4. Temp file cleanup: Audio files deleted after transcription (unless keep_audio=True)
"""

import os
import threading
import time
import queue
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

from .logging_manager import log_event, log_error


class JobPhase(Enum):
    QUEUED = "queued"
    EXTRACTING = "extracting"  # Changed from DOWNLOADING
    TRANSCRIBING = "transcribing"
    SAVING = "saving"  # Changed from FINALIZING
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ScheduledJob:
    """A job with its current state and callbacks."""
    id: str
    url: str
    output_dir: str
    config: Dict[str, Any]
    phase: JobPhase = JobPhase.QUEUED
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    # File paths
    temp_audio_path: Optional[str] = None  # Temporary audio file (to be cleaned)
    transcript_path: Optional[str] = None  # Permanent transcript file

    # Time range for partial transcription
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    # Timestamps
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Options
    keep_audio: bool = False  # If True, don't delete audio after transcription

    # Callbacks
    on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None


class ResourceScheduler:
    """
    Resource-aware scheduler with separate pools for extraction and transcription.

    On M1 Air:
    - Extract pool: 3 workers (I/O bound, runs outside GIL)
    - Transcribe pool: 1 worker (CPU/memory bound, avoid contention)

    Jobs flow: Queue -> Extract Pool -> Transcribe Pool -> Save -> Cleanup -> Done
    """

    def __init__(
        self,
        extract_workers: int = 3,
        transcribe_workers: int = 1,
        max_queue_size: int = 20,
        temp_dir: Optional[str] = None,
    ):
        self.extract_workers = extract_workers
        self.transcribe_workers = transcribe_workers
        self.temp_dir = temp_dir

        # Separate pools for different resource classes
        self.extract_pool = ThreadPoolExecutor(
            max_workers=extract_workers,
            thread_name_prefix="extract"
        )
        self.transcribe_pool = ThreadPoolExecutor(
            max_workers=transcribe_workers,
            thread_name_prefix="transcribe"
        )

        # Job tracking
        self.jobs: Dict[str, ScheduledJob] = {}
        self.job_lock = threading.Lock()

        # Backpressure: limit queue size
        self.pending_queue: queue.Queue[str] = queue.Queue(maxsize=max_queue_size)

        # Stats
        self.stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "extractions_active": 0,
            "transcriptions_active": 0,
        }
        self.stats_lock = threading.Lock()

        log_event(
            "scheduler",
            "init",
            "Scheduler initialized",
            level="INFO",
            data={
                "extract_workers": extract_workers,
                "transcribe_workers": transcribe_workers,
                "max_queue": max_queue_size,
                "temp_dir": temp_dir,
            },
        )

    def submit(
        self,
        job_id: str,
        url: str,
        output_dir: str,
        config: Dict[str, Any],
        on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        keep_audio: bool = False,
    ) -> ScheduledJob:
        """
        Submit a new job to the scheduler.

        Returns immediately - job runs asynchronously through the pipeline.
        """
        job = ScheduledJob(
            id=job_id,
            url=url,
            output_dir=output_dir,
            config=config,
            on_progress=on_progress,
            start_time=start_time,
            end_time=end_time,
            keep_audio=keep_audio,
        )

        with self.job_lock:
            self.jobs[job_id] = job

        with self.stats_lock:
            self.stats["total_submitted"] += 1

        # Submit to extract pool (I/O bound - can run many)
        self.extract_pool.submit(self._run_extract, job_id)

        log_event(
            "scheduler",
            "job_submitted",
            "Job queued",
            level="INFO",
            data={
                "job_id": job_id,
                "url": url,
                "start_time": start_time,
                "end_time": end_time,
                "output_dir": output_dir,
                "keep_audio": keep_audio,
            },
        )
        self._emit_progress(job, "queued", {"position": len(self.jobs)})

        return job

    def _run_extract(self, job_id: str) -> None:
        """Extract audio phase - runs in extract pool (I/O bound)."""
        job = self.jobs.get(job_id)
        if not job:
            return

        job.phase = JobPhase.EXTRACTING
        job.started_at = time.time()

        with self.stats_lock:
            self.stats["extractions_active"] += 1

        try:
            from .audio_extractor import extract_audio

            self._emit_progress(job, "extract_start", {"url": job.url})

            def progress_hook(status: Dict[str, Any]) -> None:
                self._emit_progress(job, "extract_progress", {
                    "downloaded_bytes": status.get("downloaded_bytes"),
                    "total_bytes": status.get("total_bytes") or status.get("total_bytes_estimate"),
                    "speed": status.get("speed"),
                    "eta": status.get("eta"),
                })

            # Extract audio to temp file
            temp_path, info = extract_audio(
                url=job.url,
                temp_dir=self.temp_dir,
                start_time=job.start_time,
                end_time=job.end_time,
                progress_hook=progress_hook,
            )

            job.temp_audio_path = temp_path
            job.result = {"info": info}

            self._emit_progress(job, "extract_complete", {
                "file": temp_path,
                "duration": info.get("duration"),
            })

            # Immediately submit to transcribe pool (pseudo-streaming)
            self.transcribe_pool.submit(self._run_transcribe, job_id)

        except Exception as e:
            job.phase = JobPhase.ERROR
            job.error = str(e)
            log_error(
                "scheduler",
                "extract_error",
                f"Job {job_id} extraction failed",
                exc=e,
                data={"job_id": job_id, "url": job.url},
            )
            self._emit_progress(job, "error", {"message": str(e), "phase": "extract"})
            self._cleanup_temp(job)

            with self.stats_lock:
                self.stats["total_failed"] += 1
        finally:
            with self.stats_lock:
                self.stats["extractions_active"] -= 1

    def _run_transcribe(self, job_id: str) -> None:
        """Transcribe phase - runs in transcribe pool (CPU/GPU bound, limited workers)."""
        job = self.jobs.get(job_id)
        if not job or not job.temp_audio_path:
            return

        job.phase = JobPhase.TRANSCRIBING

        with self.stats_lock:
            self.stats["transcriptions_active"] += 1

        try:
            from .transcriber import transcribe_audio

            self._emit_progress(job, "transcribe_start", {"file": job.temp_audio_path})

            def transcribe_progress(event: str, payload: Dict[str, Any]) -> None:
                self._emit_progress(job, event, payload)

            # Transcribe without saving to file yet
            # (We'll save via storage.save_transcript for proper indexing)
            result = transcribe_audio(
                file_path=job.temp_audio_path,
                language=job.config.get("transcription_language", "auto"),
                model_size=job.config.get("transcription_model", "small"),
                output_format=job.config.get("output_format", "srt"),
                output_dir=None,  # Don't save yet - we'll do it in _run_save
                progress_callback=transcribe_progress,
                backend=job.config.get("transcription_backend", "faster-whisper"),
                compute_type=job.config.get("transcription_compute_type", "int8"),
            )

            job.result["transcription"] = result

            self._emit_progress(job, "transcribe_complete", {
                "text_length": len(result.get("text", "")),
                "segment_count": len(result.get("segments", [])),
                "language": result.get("language"),
            })

            # Save transcript and update index
            self._run_save(job_id)

        except Exception as e:
            job.phase = JobPhase.ERROR
            job.error = str(e)
            log_error(
                "scheduler",
                "transcribe_error",
                f"Job {job_id} transcription failed",
                exc=e,
                data={"job_id": job_id},
            )
            self._emit_progress(job, "error", {"message": str(e), "phase": "transcribe"})
            self._cleanup_temp(job)

            with self.stats_lock:
                self.stats["total_failed"] += 1
        finally:
            with self.stats_lock:
                self.stats["transcriptions_active"] -= 1

    def _run_save(self, job_id: str) -> None:
        """Save phase - store transcript and update index."""
        job = self.jobs.get(job_id)
        if not job or not job.result:
            return

        job.phase = JobPhase.SAVING

        try:
            from .storage import save_transcript

            info = job.result.get("info", {})
            transcription = job.result.get("transcription", {})

            # Prepare metadata for storage
            metadata = {
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "webpage_url": info.get("webpage_url") or job.url,
                "url": job.url,
                "duration": info.get("duration"),
                "language": transcription.get("language"),
                "model": job.config.get("transcription_model", "small"),
            }

            video_id = info.get("id")
            if not video_id:
                # Extract from URL as fallback
                import re
                match = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', job.url)
                video_id = match.group(1) if match else job_id

            # Save transcript file and update index
            transcript_path = save_transcript(
                video_id=video_id,
                text=transcription.get("text", ""),
                segments=transcription.get("segments", []),
                metadata=metadata,
                output_format=job.config.get("output_format", "srt"),
                transcripts_dir=job.output_dir,
            )

            job.transcript_path = transcript_path
            job.result["transcript_path"] = transcript_path
            job.result["video_id"] = video_id

            # Mark complete
            job.phase = JobPhase.COMPLETED
            job.completed_at = time.time()

            elapsed = job.completed_at - job.started_at if job.started_at else 0

            self._emit_progress(job, "completed", {
                "transcript": transcript_path,
                "video_id": video_id,
                "elapsed_seconds": round(elapsed, 1),
            })

            log_event(
                "scheduler",
                "job_completed",
                "Job completed",
                level="INFO",
                data={
                    "job_id": job_id,
                    "video_id": video_id,
                    "elapsed_seconds": round(elapsed, 1),
                    "transcript": transcript_path,
                },
            )

            with self.stats_lock:
                self.stats["total_completed"] += 1

        except Exception as e:
            job.phase = JobPhase.ERROR
            job.error = str(e)
            log_error(
                "scheduler",
                "save_error",
                f"Job {job_id} save failed",
                exc=e,
                data={"job_id": job_id},
            )
            self._emit_progress(job, "error", {"message": str(e), "phase": "save"})

            with self.stats_lock:
                self.stats["total_failed"] += 1
        finally:
            # Always cleanup temp file (unless keep_audio is True)
            self._cleanup_temp(job)

    def _cleanup_temp(self, job: ScheduledJob) -> None:
        """Clean up temporary audio file."""
        if job.keep_audio:
            log_event(
                "scheduler",
                "cleanup_skipped",
                "Keeping audio file (user requested)",
                level="DEBUG",
                data={"job_id": job.id, "file": job.temp_audio_path},
            )
            return

        if job.temp_audio_path and os.path.isfile(job.temp_audio_path):
            try:
                os.remove(job.temp_audio_path)
                log_event(
                    "scheduler",
                    "cleanup_complete",
                    "Temp audio file deleted",
                    level="DEBUG",
                    data={"job_id": job.id, "file": job.temp_audio_path},
                )
            except OSError as e:
                log_event(
                    "scheduler",
                    "cleanup_failed",
                    f"Failed to delete temp file: {e}",
                    level="WARNING",
                    data={"job_id": job.id, "file": job.temp_audio_path},
                )

    def _emit_progress(self, job: ScheduledJob, event: str, payload: Dict[str, Any]) -> None:
        """Emit progress event to job callback."""
        if job.on_progress:
            try:
                job.on_progress(event, {"job_id": job.id, **payload})
            except Exception:
                pass

    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """Get job by ID."""
        return self.jobs.get(job_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        with self.stats_lock:
            return {
                **self.stats,
                "jobs_in_memory": len(self.jobs),
            }

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler."""
        log_event("scheduler", "shutdown", "Shutting down scheduler...", level="INFO")
        self.extract_pool.shutdown(wait=wait)
        self.transcribe_pool.shutdown(wait=wait)


# Global scheduler instance (singleton pattern)
_scheduler: Optional[ResourceScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler(
    extract_workers: int = 3,
    transcribe_workers: int = 1,
    max_queue_size: int = 20,
    temp_dir: Optional[str] = None,
) -> ResourceScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                _scheduler = ResourceScheduler(
                    extract_workers=extract_workers,
                    transcribe_workers=transcribe_workers,
                    max_queue_size=max_queue_size,
                    temp_dir=temp_dir,
                )
    return _scheduler


def submit_job(
    job_id: str,
    url: str,
    output_dir: str,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    keep_audio: bool = False,
    extract_workers: int = 3,
    transcribe_workers: int = 1,
    temp_dir: Optional[str] = None,
) -> ScheduledJob:
    """Convenience function to submit a job to the global scheduler."""
    scheduler = get_scheduler(
        extract_workers=extract_workers,
        transcribe_workers=transcribe_workers,
        temp_dir=temp_dir,
    )
    return scheduler.submit(
        job_id=job_id,
        url=url,
        output_dir=output_dir,
        config=config,
        on_progress=on_progress,
        start_time=start_time,
        end_time=end_time,
        keep_audio=keep_audio,
    )
