# Trainly MVP

Trainly turns training into a module with lessons, timed knowledge checks, and learner results. This first local MVP runs with Python's standard library and SQLite, so it needs no package install.

## Run locally

From this folder, start the server with:

```powershell
.\venv\Scripts\python.exe app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The app creates `trainly.sqlite3` and stores uploaded videos in `storage/` on first launch. Video uploads require FFprobe on `PATH` (or set `TRAINLY_FFPROBE` to its executable). Set `PORT`, `TRAINLY_DB`, or `TRAINLY_STORAGE` to change those locations. Set `TRAINLY_SECURE_COOKIE=1` when serving behind HTTPS.

## Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Creator | `creator@trainly.local` | `trainly` |
| Learner | `learner@trainly.local` | `trainly` |

The creator can edit the sample module, create a new module, add and reorder lessons and multiple choice questions, upload a video, publish versioned content, assign modules to learners by email, and review results by learner. The learner can open assigned modules, jump between lesson ranges, answer timed questions, and see feedback. Quiz answers, scores, playback position, completed lessons, and unfinished attempts are stored in SQLite so learners can resume their progress.

## Current scope

The MVP supports one local workspace with two seeded demo users. Passwords are stored with PBKDF2 hashes; existing plaintext demo passwords are upgraded when used to sign in. Module authoring and learner progress use SQLite, uploaded videos are inspected for format, video stream, and duration, and private media is served through an authenticated byte-range route. Each publish creates a versioned content and video snapshot, so learners and their attempts stay on the version they opened.

Automatic transcription and AI draft generation are not connected yet because the product plan leaves the provider and video data handling decision open. Creators can add that content manually. For a public deployment, the app still needs a production web framework and server, managed account and workspace membership, migrations, secure deployment configuration, and an AI/media worker.
