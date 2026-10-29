"""Trainly's durable media processing worker. Run with ``python worker.py``."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import providers
from data import (
    FILES,
    db,
    extract_audio,
    inspect_video_details,
    prepare_browser_playback,
    record_event,
    save_generated_draft,
)

CLAIM_TIMEOUT_SECONDS = 6 * 60 * 60


def safe_inspection_error(error):
    message = str(error)
    safe_prefixes = (
        "The selected file is not a valid video",
        "The video duration could not be read",
        "This video is longer than",
        "Video inspection is unavailable",
        "Video inspection took too long",
        "The selected file could not be inspected",
        "Video conversion is unavailable",
        "Video conversion took too long",
        "Video conversion failed",
        "Audio extraction is unavailable",
        "Audio extraction took too long",
        "Audio extraction failed",
        "Automatic transcription is not configured",
        "Automatic draft generation is not configured",
        "The AI provider",
        "The extracted audio file",
        "No speech was detected",
        "No usable speech segments",
        "The generated draft",
        "A generated lesson",
        "A generated question",
    )
    return message if message.startswith(safe_prefixes) else "Video processing failed unexpectedly. You can retry this job."


def claim_job():
    """Recover stale claims and atomically claim the oldest queued job."""
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        now = int(time.time())
        c.execute(
            "UPDATE processing_jobs SET state='queued',claimed_at=NULL,updated_at=? "
            "WHERE state='processing' AND claimed_at<?",
            (now, now - CLAIM_TIMEOUT_SECONDS),
        )
        job = c.execute(
            "SELECT * FROM processing_jobs WHERE state='queued' "
            "ORDER BY created_at,id LIMIT 1"
        ).fetchone()
        if job:
            c.execute(
                "UPDATE processing_jobs SET state='processing',stage='inspection',claimed_at=?,updated_at=?,error=NULL,message=NULL WHERE id=?",
                (now, now, job["id"]),
            )
            c.execute("UPDATE media_assets SET state='processing' WHERE id=?", (job["id"],))
        c.commit()
        return dict(job) if job else None
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def finish_job(
    job,
    details=None,
    playback_path=None,
    audio_path=None,
    transcript=None,
    lessons=None,
    questions=None,
    title="",
    description="",
    transcript_state="skipped",
    draft_state="skipped",
    provider=None,
    notice=None,
    error=None,
    failed_stage="inspection",
):
    """Save the result only if this job is still the module's active upload."""
    c = db()
    discard_asset = False
    try:
        c.execute("BEGIN IMMEDIATE")
        now = int(time.time())
        row = c.execute(
            "SELECT state FROM processing_jobs WHERE id=?", (job["id"],)
        ).fetchone()
        if not row or row["state"] != "processing":
            c.rollback()
            return
        module = c.execute(
            "SELECT upload_job_id FROM modules WHERE id=?", (job["module_id"],)
        ).fetchone()
        active = module and module["upload_job_id"] == job["id"]
        if not active:
            c.execute(
                "UPDATE processing_jobs SET state='superseded',updated_at=?,claimed_at=NULL WHERE id=?",
                (now, job["id"]),
            )
            c.execute("UPDATE media_assets SET state='superseded' WHERE id=?", (job["id"],))
            discard_asset = True
        elif details is None:
            c.execute(
                "UPDATE processing_jobs SET state='failed',stage=?,updated_at=?,claimed_at=NULL,error=? WHERE id=?",
                (failed_stage, now, error or "Video processing failed. You can retry this job.", job["id"]),
            )
            c.execute("UPDATE media_assets SET state='failed' WHERE id=?", (job["id"],))
            record_event(c, "video_processing_failed", job.get("workspace_id"), None, job["module_id"], {"job_id": job["id"], "stage": failed_stage})
        else:
            c.execute(
                "UPDATE media_assets SET playback_path=?,container=?,video_codec=?,audio_codec=?,duration=?,state='ready' WHERE id=?",
                (
                    Path(playback_path).name,
                    ",".join(details["container"]),
                    details["video_codec"],
                    details["audio_codec"],
                    details["duration"],
                    job["id"],
                ),
            )
            c.execute(
                "UPDATE modules SET video=?,playback_video=?,media_asset_id=?,duration=? WHERE id=? AND upload_job_id=?",
                (
                    job["asset"],
                    Path(playback_path).name,
                    job["id"],
                    details["duration"],
                    job["module_id"],
                    job["id"],
                ),
            )
            if transcript:
                save_generated_draft(
                    c,
                    job["module_id"],
                    transcript,
                    lessons or [],
                    questions or [],
                    title=title,
                    description=description,
                    provider=provider,
                    state="ready" if draft_state == "ready" else "transcript_ready",
                    error=error,
                )
            c.execute(
                "UPDATE processing_jobs SET state='ready',stage='complete',duration=?,updated_at=?,claimed_at=NULL,"
                "error=?,audio_path=?,transcript_state=?,draft_state=?,provider=?,message=? WHERE id=?",
                (
                    details["duration"],
                    now,
                    error,
                    Path(audio_path).name if audio_path else None,
                    transcript_state,
                    draft_state,
                    provider,
                    notice,
                    job["id"],
                ),
            )
            record_event(
                c,
                "video_processing_completed",
                job.get("workspace_id"),
                None,
                job["module_id"],
                {"job_id": job["id"], "duration": details["duration"], "transcript_state": transcript_state, "draft_state": draft_state, "ai_error": bool(error)},
            )
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    if discard_asset:
        stem = Path(job["asset"]).stem
        (FILES / Path(job["asset"]).name).unlink(missing_ok=True)
        (FILES / f"{stem}-playback.mp4").unlink(missing_ok=True)
        (FILES / f"{stem}-audio.wav").unlink(missing_ok=True)


def set_stage(job_id, stage):
    c = db()
    try:
        now = int(time.time())
        c.execute("UPDATE processing_jobs SET stage=?,updated_at=? WHERE id=? AND state='processing'", (stage, now, job_id))
        c.commit()
    finally:
        c.close()


def process_one():
    job = claim_job()
    if not job:
        return False
    path = FILES / Path(job["asset"]).name
    stage = "inspection"
    try:
        details = inspect_video_details(path, job["extension"])
        stage = "conversion"
        set_stage(job["id"], "conversion")
        playback_path, _converted = prepare_browser_playback(path, job["extension"], details)
    except ValueError as exc:
        finish_job(job, error=safe_inspection_error(exc), failed_stage=stage)
        return True
    except Exception:
        finish_job(job, error="Video processing failed unexpectedly. You can retry this job.", failed_stage=stage)
        return True

    audio_path = None
    transcript = []
    lessons = []
    questions = []
    title = ""
    description = ""
    transcript_state = "skipped"
    draft_state = "skipped"
    provider = None
    notice = None
    error = None

    if providers.ai_enabled():
        provider = providers.ai_status()["ai_provider"]
        if not details.get("audio_codec"):
            transcript_state = "no_audio"
            notice = "The video has no audio track, so no transcript draft was created. Add lessons and questions manually."
        else:
            stage = "audio"
            set_stage(job["id"], "audio")
            try:
                audio_path = extract_audio(path)
            except ValueError as exc:
                transcript_state = "failed"
                error = safe_inspection_error(exc)
            else:
                stage = "transcription"
                set_stage(job["id"], "transcription")
                try:
                    transcript = providers.transcribe_audio(audio_path, details["duration"])
                    transcript_state = "ready"
                except ValueError as exc:
                    transcript_state = "failed"
                    error = safe_inspection_error(exc)
                if transcript:
                    stage = "generation"
                    set_stage(job["id"], "generation")
                    try:
                        draft = providers.generate_draft(
                            transcript,
                            details["duration"],
                            current_title=job.get("filename") or "",
                        )
                        lessons = draft["lessons"]
                        questions = draft["questions"]
                        title = draft["title"]
                        description = draft["description"]
                        draft_state = "ready"
                    except ValueError as exc:
                        draft_state = "failed"
                        error = safe_inspection_error(exc)
    else:
        transcript_state = "not_configured"
        draft_state = "not_configured"
        notice = "Automatic transcription is not configured. The video is ready; add lessons and questions manually or configure a provider and retry."

    finish_job(
        job,
        details=details,
        playback_path=playback_path,
        audio_path=audio_path,
        transcript=transcript,
        lessons=lessons,
        questions=questions,
        title=title,
        description=description,
        transcript_state=transcript_state,
        draft_state=draft_state,
        provider=provider,
        notice=notice,
        error=error,
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="Process Trainly video jobs")
    parser.add_argument("--once", action="store_true", help="Process one queued job and exit")
    args = parser.parse_args()
    try:
        poll_seconds = max(0.25, float(os.environ.get("TRAINLY_WORKER_POLL_SECONDS", "2")))
    except ValueError as exc:
        raise SystemExit("TRAINLY_WORKER_POLL_SECONDS must be a number.") from exc
    if args.once:
        process_one()
        return
    while True:
        if not process_one():
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
