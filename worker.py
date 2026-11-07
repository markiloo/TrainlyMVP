"""Trainly's durable media processing worker. Run with ``python worker.py``."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import providers
from sqlalchemy import select, update
from models import ProcessingJob, MediaAsset, TrainingModule
from data import model_record
from data import (
    FILES,
    bootstrap,
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
    with db() as session, session.begin():
        session.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        session.execute(update(ProcessingJob).where(
            ProcessingJob.state == 'processing', ProcessingJob.claimed_at < now - CLAIM_TIMEOUT_SECONDS
        ).values(state='queued', claimed_at=None, updated_at=now))
        job = session.scalar(select(ProcessingJob).where(ProcessingJob.state == 'queued').order_by(ProcessingJob.created_at, ProcessingJob.id).limit(1))
        if job is None:
            return None
        result = dict(model_record(job))
        job.state, job.stage, job.claimed_at, job.updated_at = 'processing', 'inspection', now, now
        job.error, job.message = None, None
        asset = session.get(MediaAsset, job.id)
        if asset:
            asset.state = 'processing'
        return result


def finish_job(
    job, details=None, playback_path=None, audio_path=None, transcript=None,
    lessons=None, questions=None, title='', description='', transcript_state='skipped',
    draft_state='skipped', provider=None, notice=None, error=None, failed_stage='inspection',
):
    """Save a stage result in one short transaction, after provider/media work."""
    discard_asset = False
    with db() as session, session.begin():
        session.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        row = session.get(ProcessingJob, job['id'])
        if row is None or row.state != 'processing':
            return
        module = session.get(TrainingModule, job['module_id'])
        asset = session.get(MediaAsset, job['id'])
        if not module or module.upload_job_id != job['id']:
            row.state, row.updated_at, row.claimed_at = 'superseded', now, None
            if asset:
                asset.state = 'superseded'
            discard_asset = True
        elif details is None:
            row.state, row.stage, row.updated_at, row.claimed_at = 'failed', failed_stage, now, None
            row.error = error or 'Video processing failed. You can retry this job.'
            if asset:
                asset.state = 'failed'
            record_event(session, 'video_processing_failed', job.get('workspace_id'), None, job['module_id'], {'job_id': job['id'], 'stage': failed_stage})
        else:
            if asset:
                asset.playback_path = Path(playback_path).name
                asset.container = ','.join(details['container'])
                asset.video_codec, asset.audio_codec = details['video_codec'], details['audio_codec']
                asset.duration, asset.state = details['duration'], 'ready'
            module.video, module.playback_video = job['asset'], Path(playback_path).name
            module.media_asset_id, module.duration = job['id'], details['duration']
            if transcript:
                save_generated_draft(session, job['module_id'], transcript, lessons or [], questions or [],
                                     title=title, description=description, provider=provider,
                                     state='ready' if draft_state == 'ready' else 'transcript_ready', error=error)
            row.state, row.stage, row.duration = 'ready', 'complete', details['duration']
            row.updated_at, row.claimed_at, row.error = now, None, error
            row.audio_path = Path(audio_path).name if audio_path else None
            row.transcript_state, row.draft_state = transcript_state, draft_state
            row.provider, row.message = provider, notice
            record_event(session, 'video_processing_completed', job.get('workspace_id'), None, job['module_id'],
                         {'job_id': job['id'], 'duration': details['duration'], 'transcript_state': transcript_state,
                          'draft_state': draft_state, 'ai_error': bool(error)})
    if discard_asset:
        stem = Path(job['asset']).stem
        (FILES / Path(job['asset']).name).unlink(missing_ok=True)
        (FILES / f'{stem}-playback.mp4').unlink(missing_ok=True)
        (FILES / f'{stem}-audio.wav').unlink(missing_ok=True)


def set_stage(job_id, stage):
    with db() as session, session.begin():
        session.execute(update(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.state == 'processing').values(stage=stage, updated_at=int(time.time())))


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

    try:
        ai_enabled = providers.ai_enabled()
    except ValueError:
        # A misconfigured backend must not strand the job in 'processing'.
        ai_enabled, config_error = False, True
    else:
        config_error = False

    if ai_enabled:
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
                if transcript and providers.transcription_backend() == 'local':
                    notice = 'Local transcript ready for review. Add lessons and questions manually.'
                if transcript and providers.transcription_backend() != 'local':
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
        notice = (
            "Automatic transcription is not configured. Set TRAINLY_TRANSCRIPTION_BACKEND to disabled, local, or http, then retry."
            if config_error else
            "Automatic transcription is not configured. The video is ready; add lessons and questions manually or configure a provider and retry."
        )

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
    bootstrap()
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
