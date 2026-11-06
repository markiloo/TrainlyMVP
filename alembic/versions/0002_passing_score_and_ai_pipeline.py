"""passing score and AI pipeline. Converted from PRAGMA user_version 2."""
from alembic import op
from sqlalchemy.engine import Connection

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def _columns(c: Connection, table: str) -> set[str]:
    return {row[1] for row in c.exec_driver_sql(f"PRAGMA table_info({table})")}

def _add_column(c: Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(c, table):
        c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def migration_2_passing_score_and_ai_pipeline(c: Connection) -> None:
    _add_column(c, "modules", "pass_score", "INTEGER NOT NULL DEFAULT 70")
    _add_column(c, "processing_jobs", "audio_path", "TEXT")
    _add_column(c, "processing_jobs", "transcript_state", "TEXT NOT NULL DEFAULT 'pending'")
    _add_column(c, "processing_jobs", "draft_state", "TEXT NOT NULL DEFAULT 'pending'")
    _add_column(c, "processing_jobs", "provider", "TEXT")
    _add_column(c, "processing_jobs", "message", "TEXT")

def upgrade():
    migration_2_passing_score_and_ai_pipeline(op.get_bind())
    op.get_bind().exec_driver_sql("PRAGMA user_version=2")

def downgrade():
    raise RuntimeError("Trainly migrations are forward only; restore a backup to downgrade.")
