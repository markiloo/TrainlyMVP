# Trainly MVP web stack

**Status:** Selected for the MVP  
**Date:** 2026-10-19

## Stack decision

| Layer | Choice | Use in Trainly |
| --- | --- | --- |
| Language | Python 3.12+ | Main application, processing worker, and integrations. |
| Web framework | FastAPI | HTTP routes, validation, authentication checks, and API endpoints used by the player. |
| Page rendering | Jinja2 | Server rendered creator and learner pages. Enable HTML autoescaping. |
| Browser interaction | Native JavaScript modules | Upload progress, transcript seeking, lesson editing, timed quiz overlays, and progress saves through `fetch`. |
| Styling | Plain CSS using `visual_identity.md` tokens | Responsive layout and components without a CSS framework. Poppins Light (300) and Bold (700). |
| Database | SQLite | Accounts, modules, published versions, processing jobs, assignments, answers, and progress. |
| Database access and migrations | SQLAlchemy 2.x and Alembic | Typed models, explicit sessions, and reviewed schema migrations. |
| Background processing | Separate Python worker using a SQLite job table | Durable media and AI jobs, retries, and visible status. One worker for the MVP. |
| Media tools | FFmpeg | Inspect uploads, extract audio, and prepare browser playable video when needed. |
| Video storage | Private directory on a persistent local volume | Original and derived video, audio, and caption files. The app authorizes playback and supports byte range requests. |
| AI integration | Python provider interfaces | Speech transcription and module draft generation. Provider selection remains open pending the data handling decision. |
| App server and deployment | Uvicorn behind an HTTPS reverse proxy, one writable app instance | Serve the FastAPI app on a single host with persistent database and media volumes. |
| Dependency management | `pyproject.toml` with `uv` | Reproducible local and deployment installs. |

## Why this fits the MVP

Trainly's creator dashboard, transcript review, and results pages are mainly forms and structured content. Jinja2 keeps those pages close to the Python application. Small JavaScript modules handle the parts that need immediate browser behavior, especially the video timeline and quiz checkpoints. This avoids a separate frontend app and build pipeline for the first release.

The app and worker use separate SQLite connections. Enable write ahead logging, foreign keys, and a busy timeout; keep write transactions short. The worker claims a job, commits that claim, performs media or AI work outside the transaction, then records the result. Stale claims can be retried after a crash. Keep the database on a local persistent volume and make regular backups.

Media files stay outside the web static directory. Only an authorized route can serve them, including range requests needed for seeking. The first deployment uses one host and one processing worker. Scale and hosting choices can be revisited if video volume or concurrent writes exceed this setup.

## Application boundaries

```text
Browser (Jinja pages + JavaScript modules + CSS)
    |
    v
FastAPI routes and services ----> SQLite
    |                               ^
    | create processing job         | claim/update job
    v                               |
Private media directory <---- Python worker ----> FFmpeg and AI providers
```

- **HTML routes:** Dashboard, module editor, learner player, and results.
- **JSON endpoints:** Upload status, transcript and lesson edits, quiz positions and answers, and playback progress.
- **Service layer:** Authorization, draft validation, publishing, scoring, and job orchestration. Routes should not contain media processing logic.
- **Worker:** FFmpeg, transcription, draft generation, retries, and error recording. Long jobs do not run inside an HTTP request.

## Implementation conventions

- Use server side sessions with an HTTP only, secure cookie that holds an opaque session identifier. Protect state changing browser requests with a CSRF token.
- Use SQLAlchemy sessions per request or worker unit of work. Enable SQLite foreign key enforcement on every connection.
- Store video paths and provider credentials in configuration; keep secrets out of templates and logs.
- Version published modules so learner attempts remain tied to the content they saw.
- Organize browser code by feature (`upload.js`, `editor.js`, `player.js`) and keep shared behavior small.
- Serve Poppins from a controlled font asset in deployment; the preview may load it from Google Fonts.

## Reference documentation

- [FastAPI templates](https://fastapi.tiangolo.com/advanced/templates/) describe its Jinja2 integration and static files.
- [FastAPI background task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/) notes that heavy computation belongs in a separate worker approach.
- [SQLAlchemy SQLite documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) covers the SQLite dialect and foreign key setup.
- [Alembic documentation](https://alembic.sqlalchemy.org/en/latest/) covers schema migrations with SQLAlchemy.
- [Jinja2 autoescaping documentation](https://jinja.palletsprojects.com/en/stable/api/#autoescaping) covers safe HTML template configuration.
