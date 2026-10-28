# Trainly MVP

Trainly turns training into a module with lessons, timed knowledge checks, and learner results. This local MVP uses FastAPI, Uvicorn, and SQLite.

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

The worker claims queued video jobs from SQLite, inspects them with FFprobe, and uses FFmpeg to create an H.264/AAC MP4 when the source is not browser playable. Use `worker.py --once` to process a single queued job. Set `TRAINLY_WORKER_POLL_SECONDS` to change how often it checks for new jobs, or set `TRAINLY_FFMPEG` and `TRAINLY_FFPROBE` to point to the executable paths.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The app creates `trainly.sqlite3` and stores uploaded videos in `storage/` on first launch. Video processing requires FFprobe on `PATH`; FFmpeg is also needed when a source needs conversion. Set `TRAINLY_FFPROBE` or `TRAINLY_FFMPEG` to use a specific executable. Set `PORT`, `TRAINLY_DB`, or `TRAINLY_STORAGE` to change those locations. `TRAINLY_MAX_VIDEO_BYTES` and `TRAINLY_MAX_VIDEO_SECONDS` set positive integer upload limits (defaults: 1 GiB and 7200 seconds). Set `TRAINLY_SECURE_COOKIE=1` when serving behind HTTPS.

Run the API checks with `.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests`. If Node.js is installed, run the editor state check with `node tests\editor_state.test.cjs`.

## Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Creator | `creator@trainly.local` | `trainly` |
| Learner | `learner@trainly.local` | `trainly` |

The creator can edit the sample module, create a new module, add and reorder lessons and multiple choice questions, upload a video, publish versioned content, assign modules to learners by email, and review results by learner. Video uploads are stored and queued for inspection; the creator can see queue, processing, ready, or failure status and retry an inspection without uploading again. If the learner has no account, Assign creates a one-use invitation link valid for seven days. The creator shares that link with the learner, who sets a name and password and receives the module assignment. The learner can open assigned modules, jump between lesson ranges, answer timed questions, and see feedback. Quiz answers, scores, playback position, completed lessons, and unfinished attempts are stored in SQLite so learners can resume their progress.

The bundled `vids/sample vid.mp4` is seeded as the published **LTspice model walkthrough** module and assigned to the demo learner. Its four timed knowledge checks appear throughout the video. Sign in as the learner and open that module to demonstrate playback and questions; sign in as the creator to edit it.

## Current scope

The MVP starts with one local workspace and two seeded demo users. Workspace membership scopes modules, assignments, attempts, results, and private media. New learner accounts can join through invitation links; invitations are not emailed by the app. Passwords are stored with PBKDF2 hashes; existing plaintext demo passwords are upgraded when used to sign in. Module authoring, processing jobs, media asset metadata, and learner progress use SQLite. Uploaded videos are inspected for format, codecs, and duration; files that need conversion get a browser playable derivative. Private media is served through an authenticated byte-range route. Each publish snapshots its source and playback media paths, so saved answers remain tied to the version used for that attempt.

Automatic transcription and AI draft generation are not connected yet because the product plan leaves the provider and video data handling decision open. Creators can add that content manually. For a public deployment, the app still needs reviewed schema migrations, secure deployment configuration, account recovery, and the remaining audio and AI processing stages.
