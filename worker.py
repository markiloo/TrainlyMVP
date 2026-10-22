"""Trainly's durable media processing worker. Run with ``python worker.py``."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from data import FILES, db, inspect_video_details, prepare_browser_playback

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
    )
    return message if message.startswith(safe_prefixes) else "The video could not be inspected. You can retry this job."


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
                "UPDATE processing_jobs SET state='processing',stage='inspection',claimed_at=?,updated_at=? WHERE id=?",
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


def finish_job(job, details=None, playback_path=None, error=None, failed_stage='inspection'):
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
        elif error:
            c.execute(
                "UPDATE processing_jobs SET state='failed',stage=?,updated_at=?,claimed_at=NULL,error=? WHERE id=?",
                (failed_stage, now, error, job["id"]),
            )
            c.execute("UPDATE media_assets SET state='failed' WHERE id=?", (job["id"],))
        else:
            c.execute(
                "UPDATE media_assets SET playback_path=?,container=?,video_codec=?,audio_codec=?,duration=?,state='ready' WHERE id=?",
                (Path(playback_path).name, ','.join(details['container']), details['video_codec'], details['audio_codec'], details['duration'], job["id"]),
            )
            c.execute(
                "UPDATE modules SET video=?,playback_video=?,media_asset_id=?,duration=? WHERE id=? AND upload_job_id=?",
                (job["asset"], Path(playback_path).name, job["id"], details['duration'], job["module_id"], job["id"]),
            )
            c.execute(
                "UPDATE processing_jobs SET state='ready',stage='complete',duration=?,updated_at=?,claimed_at=NULL,error=NULL WHERE id=?",
                (details['duration'], now, job["id"]),
            )
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    if discard_asset:
        (FILES / Path(job["asset"]).name).unlink(missing_ok=True)
        (FILES / f"{Path(job['asset']).stem}-playback.mp4").unlink(missing_ok=True)


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
    stage = 'inspection'
    try:
        details = inspect_video_details(path, job["extension"])
        stage = 'conversion'
        set_stage(job["id"], 'conversion')
        playback_path, _converted = prepare_browser_playback(path, job["extension"], details)
    except ValueError as exc:
        finish_job(job, error=safe_inspection_error(exc), failed_stage=stage)
    except Exception:
        finish_job(job, error="Video processing failed unexpectedly. You can retry this job.", failed_stage=stage)
    else:
        finish_job(job, details=details, playback_path=playback_path)
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
