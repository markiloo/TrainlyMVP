# Repository Guidelines

## Project Structure & Module Organization

Trainly is a local video-training MVP built with FastAPI, SQLite, and vanilla JavaScript. `app.py` defines HTTP routes, authentication, private media delivery, and WebSocket call signaling. `data.py` owns database helpers, validation, and media utilities; `migrations.py` contains versioned SQLite migrations. `worker.py` processes durable media jobs, and `providers.py` integrates optional AI services.

The browser shell lives in `templates/index.html`, with behavior and styles in `static/app.js` and `static/app.css`. Tests live in `tests/`. Product requirements, visual guidance, and implementation tracking live in `design_plan/`. `scripts/backup.py` backs up the database and private `storage/` files.

## Build, Test, and Development Commands

Run commands from the repository root in PowerShell:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
.\venv\Scripts\python.exe worker.py --once
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests
node tests\editor_state.test.cjs
```

These install dependencies, start the app at `http://127.0.0.1:8000` with its media worker, process one queued job separately, and run Python and JavaScript checks. No frontend build step is required. Video inspection requires FFprobe; conversion and audio extraction require FFmpeg.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` functions and variables, and `PascalCase` classes. Follow nearby JavaScript conventions: `camelCase` functions and compact formatting. Keep CSS in `static/app.css`. No formatter or linter is configured.

Preserve existing `/api` paths and response shapes. Keep database transactions short and media or provider work outside write transactions. Use the existing migration mechanism for schema changes; SQLAlchemy, Alembic, and Jinja2 adoption remains planned work.

## Testing Guidelines

Python checks use pytest and FastAPI `TestClient`; JavaScript checks use Node's built-in test runner. Name Python files `test_*.py` and functions `test_*`. Use isolated test databases and mock external providers and media tools. Cover changed authorization, validation, publishing, or progress behavior. No numerical coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent commits use short, lowercase descriptions such as `added call tones` and `fixed connection reset bug`. Keep commits focused. PRs should describe the resulting behavior, list validation performed, link relevant issues when available, and include screenshots for visible UI changes. Update documentation and the implementation checklist when applicable.

## Security & Configuration

Configure paths and providers through `TRAINLY_*` environment variables. Never commit credentials, local databases, uploaded media, or backups. Preserve workspace authorization, CSRF checks, and authenticated media access. Back up existing data before schema upgrades.
