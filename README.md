# Trainly MVP

Trainly turns training into a module with lessons, timed knowledge checks, and learner results. This first local MVP runs with Python's standard library and SQLite, so it needs no package install.

## Run locally

From this folder, start the server with:

```powershell
.\venv\Scripts\python.exe app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The app creates `trainly.sqlite3` and stores uploaded videos in `storage/` on first launch. Set `PORT`, `TRAINLY_DB`, or `TRAINLY_STORAGE` to change those locations.

## Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Creator | `creator@trainly.local` | `trainly` |
| Learner | `learner@trainly.local` | `trainly` |

The creator can edit the sample module, create a new module, add lessons and multiple choice questions, upload a video, publish, and review learner results. The learner can open published modules, jump between lesson ranges, answer timed questions, and see feedback. Quiz answers, scores, playback position, completed lessons, and unfinished attempts are stored in SQLite so learners can resume their progress.

## Current scope

The MVP supports one local workspace with two seeded demo users. Module authoring and learner progress use SQLite, uploaded video files are private and served through an authenticated byte range route, and draft publishing checks the required lesson and quiz content.

Automatic transcription and AI draft generation are not connected yet because the product plan leaves the provider and video data handling decision open. Creators can add that content manually. For a public deployment, the app still needs a production web framework and server, password hashing and account management, workspace membership, migrations, secure deployment configuration, and an AI/media worker.
