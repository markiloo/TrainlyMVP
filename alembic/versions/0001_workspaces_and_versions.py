"""workspaces and published versions. Converted from PRAGMA user_version 1."""
from alembic import op
from sqlalchemy.engine import Connection

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None

def _columns(c: Connection, table: str) -> set[str]:
    return {row[1] for row in c.exec_driver_sql(f"PRAGMA table_info({table})")}

def _add_column(c: Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(c, table):
        c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def migration_1_workspaces_and_versions(c: Connection) -> None:
    _add_column(c, "modules", "published_version", "INTEGER NOT NULL DEFAULT 0")
    _add_column(c, "modules", "workspace_id", "TEXT NOT NULL DEFAULT 'local'")
    _add_column(c, "modules", "upload_job_id", "TEXT")
    _add_column(c, "modules", "playback_video", "TEXT NOT NULL DEFAULT ''")
    _add_column(c, "modules", "media_asset_id", "TEXT")
    _add_column(c, "module_versions", "playback_video", "TEXT NOT NULL DEFAULT ''")
    _add_column(c, "module_versions", "media_asset_id", "TEXT")
    _add_column(c, "attempts", "version", "INTEGER NOT NULL DEFAULT 0")

def upgrade():
    migration_1_workspaces_and_versions(op.get_bind())
    op.get_bind().exec_driver_sql("PRAGMA user_version=1")

def downgrade():
    raise RuntimeError("Trainly migrations are forward only; restore a backup to downgrade.")
