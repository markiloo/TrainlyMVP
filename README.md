# Trainly MVP

Trainly turns training into a module with lessons, timed knowledge checks, and learner results. This local MVP uses FastAPI, Uvicorn, and SQLite.

## Run locally

From this folder, install dependencies and start the server with:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The app creates `trainly.sqlite3` and stores uploaded videos in `storage/` on first launch. Video uploads require FFprobe on `PATH` (or set `TRAINLY_FFPROBE` to its executable). Set `PORT`, `TRAINLY_DB`, or `TRAINLY_STORAGE` to change those locations. `TRAINLY_MAX_VIDEO_BYTES` and `TRAINLY_MAX_VIDEO_SECONDS` set positive integer upload limits (defaults: 1 GiB and 7200 seconds). Set `TRAINLY_SECURE_COOKIE=1` when serving behind HTTPS.

Run the API checks with `.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests`. If Node.js is installed, run the editor state check with `node tests\editor_state.test.cjs`.

## Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Creator | `creator@trainly.local` | `trainly` |
| Learner | `learner@trainly.local` | `trainly` |

The creator can edit the sample module, create a new module, add and reorder lessons and multiple choice questions, upload a video, publish versioned content, assign modules to learners by email, and review results by learner. If the learner has no account, Assign creates a one-use invitation link valid for seven days. The creator shares that link with the learner, who sets a name and password and receives the module assignment. The learner can open assigned modules, jump between lesson ranges, answer timed questions, and see feedback. Quiz answers, scores, playback position, completed lessons, and unfinished attempts are stored in SQLite so learners can resume their progress.

## Current scope

The MVP starts with one local workspace and two seeded demo users. Workspace membership scopes modules, assignments, attempts, results, and private media. New learner accounts can join through invitation links; invitations are not emailed by the app. Passwords are stored with PBKDF2 hashes; existing plaintext demo passwords are upgraded when used to sign in. Module authoring and learner progress use SQLite, uploaded videos are inspected for format, video stream, and duration, and private media is served through an authenticated byte-range route. Each publish creates a versioned content and video snapshot, so saved answers remain tied to the version used for that attempt.

Automatic transcription and AI draft generation are not connected yet because the product plan leaves the provider and video data handling decision open. Creators can add that content manually. For a public deployment, the app still needs reviewed schema migrations, secure deployment configuration, account recovery, and an AI/media worker.
