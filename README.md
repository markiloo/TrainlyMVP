# Trainly MVP

Trainly turns training into a module with lessons, timed knowledge checks, and learner results. This local MVP uses FastAPI, Uvicorn, SQLite, and a small vanilla JavaScript frontend.

## Run locally

From this folder, install dependencies and start the server with:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```

In a second terminal, start the durable media worker:

```powershell
.\venv\Scripts\python.exe worker.py
```

The worker claims queued video jobs from SQLite, inspects them with FFprobe, and uses FFmpeg to create an H.264/AAC MP4 when the source is not browser playable. When an AI provider is configured it also extracts audio, transcribes speech, and stores a reviewable lesson/question draft. Use `worker.py --once` to process a single queued job. Set `TRAINLY_WORKER_POLL_SECONDS` to change how often it checks for new jobs, or set `TRAINLY_FFMPEG` and `TRAINLY_FFPROBE` to point to the executable paths.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The app creates `trainly.sqlite3` and stores uploaded videos in `storage/` on first launch. Video processing requires FFprobe on `PATH`; FFmpeg is also needed when a source needs conversion or audio extraction. Set `TRAINLY_FFPROBE` or `TRAINLY_FFMPEG` to use a specific executable. Set `PORT`, `TRAINLY_DB`, or `TRAINLY_STORAGE` to change those locations. `TRAINLY_MAX_VIDEO_BYTES` and `TRAINLY_MAX_VIDEO_SECONDS` set positive integer upload limits (defaults: 1 GiB and 7200 seconds). Set `TRAINLY_SECURE_COOKIE=1` when serving behind HTTPS.

Run the API checks with `.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests`. If Node.js is installed, run the editor state check with `node tests\editor_state.test.cjs`.

## Automatic transcription (optional)

Automatic processing is disabled until a provider is configured. The adapters use an OpenAI-compatible HTTP API; provider choice and data handling remain a deployment decision. Set:

```powershell
$env:TRAINLY_AI_BASE_URL = "https://api.openai.com/v1"  # or a self-hosted compatible endpoint
$env:TRAINLY_AI_API_KEY = "..."
$env:TRAINLY_TRANSCRIBE_MODEL = "whisper-1"
$env:TRAINLY_DRAFT_MODEL = "gpt-4o-mini"
$env:TRAINLY_AI_TIMEOUT_SECONDS = "600"
```

The creator editor warns that uploaded video and transcript content may be sent to the configured provider. Generated transcripts, lessons, and questions are stored as a separate draft for creator review. Applying a draft fills empty sections by default and keeps creator-written content unless the creator chooses to replace it. A failed AI stage leaves the ready video and existing creator edits intact; use **Retry processing** to try again.

## Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Creator | `creator@trainly.local` | `trainly` |
| Learner | `learner@trainly.local` | `trainly` |

The creator can edit the sample module, create a new module, delete a module with its media and progress, add and reorder lessons and multiple choice questions, edit timestamped transcript segments, upload a video, review an AI draft, publish versioned content, assign modules to learners by email, and review results by learner. Video uploads are stored and queued for inspection; the creator can see queue, processing, ready, or failure status and retry processing without uploading again. If the learner has no account, Assign creates a one-use invitation link valid for seven days. The creator shares that link with the learner, who sets a name and password and receives the module assignment. The learner can open assigned modules, jump between lesson ranges, answer timed questions, use captions generated from the reviewed transcript, and see feedback. Quiz answers, scores, playback position, completed lessons, and unfinished attempts are stored in SQLite so learners can resume their progress. Each module has a passing score (70% by default) that is shown in the editor, learner view, and results; completion and passing are reported separately.

The bundled `vids/sample vid.mp4` is seeded as the published **LTspice model walkthrough** module and assigned to the demo learner. Its four timed knowledge checks appear throughout the video. Sign in as the learner and open that module to demonstrate playback and questions; sign in as the creator to edit it.

## Schema migrations

Schema changes live in [`migrations.py`](./migrations.py) and run automatically when the app or worker opens SQLite. Migrations are idempotent and recorded in `PRAGMA user_version`, so existing local databases upgrade in place. Take a backup before upgrading a database that matters.

```powershell
.\venv\Scripts\python.exe scripts\backup.py
```

The backup script writes a consistent SQLite copy plus the private `storage/` files and a manifest to `backups/`. To restore, stop the app and worker, then copy the backed-up database and storage files back to the configured `TRAINLY_DB` and `TRAINLY_STORAGE` locations.

## Current scope

The MVP starts with one local workspace and two seeded demo users. Workspace membership scopes modules, assignments, attempts, results, and private media. New learner accounts can join through invitation links; invitations are not emailed by the app. Passwords are stored with PBKDF2 hashes; existing plaintext demo passwords are upgraded when used to sign in. Module authoring, processing jobs, media asset metadata, generated drafts, product events, and learner progress use SQLite. Uploaded videos are inspected for format, codecs, and duration; files that need conversion get a browser playable derivative. Private media and WebVTT captions are served through authenticated routes, with byte-range seeking for video. Each publish snapshots its source and playback media paths, transcript, and passing score, so saved answers remain tied to the version used for that attempt.

Automatic transcription and AI draft generation are available through replaceable provider adapters once a provider is configured. Provider selection, video data handling, retention, account recovery, and production deployment still need an explicit decision. For a public deployment, the app still needs reviewed deployment configuration, HTTPS enforcement at the reverse proxy, account recovery, and the remaining pilot-readiness checks in [`design_plan/checklist.md`](./design_plan/checklist.md).
