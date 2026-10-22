"""Trainly's durable media processing worker. Run with ``python worker.py``."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from data import FILES, db, inspect_video

CLAIM_TIMEOUT_SECONDS = 15 * 60


def safe_inspection_error(error):
    message = str(error)
    safe_prefixes = (
        "The selected file is not a valid video",
        "The video duration could not be read",
        "This video is longer than",
        "Video inspection is unavailable",
        "Video inspection took too long",
        "The selected file could not be inspected",
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
        c.commit()
        return dict(job) if job else None
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def finish_job(job, duration=None, error=None):
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
            discard_asset = True
        elif error:
            c.execute(
                "UPDATE processing_jobs SET state='failed',stage='inspection',updated_at=?,claimed_at=NULL,error=? WHERE id=?",
                (now, error, job["id"]),
            )
        else:
            c.execute(
                "UPDATE modules SET video=?,duration=? WHERE id=? AND upload_job_id=?",
                (job["asset"], duration, job["module_id"], job["id"]),
            )
            c.execute(
                "UPDATE processing_jobs SET state='ready',stage='complete',duration=?,updated_at=?,claimed_at=NULL,error=NULL WHERE id=?",
                (duration, now, job["id"]),
            )
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    if discard_asset:
        (FILES / Path(job["asset"]).name).unlink(missing_ok=True)


def process_one():
    job = claim_job()
    if not job:
        return False
    path = FILES / Path(job["asset"]).name
    try:
        duration = inspect_video(path, job["extension"])
    except ValueError as exc:
        finish_job(job, error=safe_inspection_error(exc))
    except Exception:
        finish_job(job, error="Video inspection failed unexpectedly. You can retry this job.")
    else:
        finish_job(job, duration=duration)
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
