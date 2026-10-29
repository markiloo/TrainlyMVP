"""Small, reviewable SQLite schema migrations.

The MVP uses plain SQLite rather than SQLAlchemy/Alembic. Each migration is
idempotent, runs inside the caller's transaction, and is recorded in
``PRAGMA user_version`` so existing databases upgrade safely on startup.
"""

from __future__ import annotations

import sqlite3


def _columns(c: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in c.execute(f"PRAGMA table_info({table})")}


def _add_column(c: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(c, table):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migration_1_workspaces_and_versions(c: sqlite3.Connection) -> None:
    _add_column(c, "modules", "published_version", "INTEGER NOT NULL DEFAULT 0")
    _add_column(c, "modules", "workspace_id", "TEXT NOT NULL DEFAULT 'local'")
    _add_column(c, "modules", "upload_job_id", "TEXT")
    _add_column(c, "modules", "playback_video", "TEXT NOT NULL DEFAULT ''")
    _add_column(c, "modules", "media_asset_id", "TEXT")
    _add_column(c, "module_versions", "playback_video", "TEXT NOT NULL DEFAULT ''")
    _add_column(c, "module_versions", "media_asset_id", "TEXT")
    _add_column(c, "attempts", "version", "INTEGER NOT NULL DEFAULT 0")


def migration_2_passing_score_and_ai_pipeline(c: sqlite3.Connection) -> None:
    _add_column(c, "modules", "pass_score", "INTEGER NOT NULL DEFAULT 70")
    _add_column(c, "processing_jobs", "audio_path", "TEXT")
    _add_column(c, "processing_jobs", "transcript_state", "TEXT NOT NULL DEFAULT 'pending'")
    _add_column(c, "processing_jobs", "draft_state", "TEXT NOT NULL DEFAULT 'pending'")
    _add_column(c, "processing_jobs", "provider", "TEXT")
    _add_column(c, "processing_jobs", "message", "TEXT")


def migration_3_generated_drafts_and_events(c: sqlite3.Connection) -> None:
    c.execute(
        """CREATE TABLE IF NOT EXISTS generated_drafts(
            module_id TEXT PRIMARY KEY,
            transcript TEXT NOT NULL DEFAULT '[]',
            lessons TEXT NOT NULL DEFAULT '[]',
            questions TEXT NOT NULL DEFAULT '[]',
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            provider TEXT,
            state TEXT NOT NULL DEFAULT 'ready',
            created_at INTEGER NOT NULL,
            error TEXT,
            FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            workspace_id TEXT,
            user_id INTEGER,
            module_id TEXT,
            created_at INTEGER NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS events_name_created ON events(name,created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS events_module ON events(module_id,created_at)")


def migration_4_generated_item_origin(c: sqlite3.Connection) -> None:
    _add_column(c, "lessons", "origin", "TEXT NOT NULL DEFAULT 'manual'")
    _add_column(c, "questions", "origin", "TEXT NOT NULL DEFAULT 'manual'")


def migration_5_admin_accounts_and_setup(c: sqlite3.Connection) -> None:
    """Add administrator memberships and one-time account setup tokens.

    SQLite cannot alter a CHECK constraint in place, so an older memberships
    table is rebuilt only when it does not already accept the admin role.
    """
    c.execute(
        """CREATE TABLE IF NOT EXISTS account_setups(
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            expires INTEGER NOT NULL,
            accepted INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS account_setups_user ON account_setups(user_id)")
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='memberships'").fetchone()
    if row and "'admin'" not in (row[0] or ""):
        c.execute("ALTER TABLE memberships RENAME TO memberships_legacy")
        c.execute(
            """CREATE TABLE memberships(
                workspace_id TEXT NOT NULL,
                user_id INTEGER NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK(role IN ('creator','learner','admin')),
                PRIMARY KEY(workspace_id,user_id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        c.execute("INSERT INTO memberships(workspace_id,user_id,role) SELECT workspace_id,user_id,role FROM memberships_legacy")
        c.execute("DROP TABLE memberships_legacy")


MIGRATIONS = (
    (1, "workspaces and published versions", migration_1_workspaces_and_versions),
    (2, "passing score and AI pipeline", migration_2_passing_score_and_ai_pipeline),
    (3, "generated drafts and events", migration_3_generated_drafts_and_events),
    (4, "generated item origin", migration_4_generated_item_origin),
    (5, "admin accounts and one-time setup", migration_5_admin_accounts_and_setup),
)


def migrate(c: sqlite3.Connection) -> None:
    version = c.execute("PRAGMA user_version").fetchone()[0]
    for number, _name, migration in MIGRATIONS:
        if version >= number:
            continue
        # Column checks make older, partially migrated databases safe to open.
        migration(c)
        c.execute(f"PRAGMA user_version={int(number)}")
        version = number
