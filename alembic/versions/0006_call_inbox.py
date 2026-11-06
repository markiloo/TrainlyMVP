"""call inbox. Converted from PRAGMA user_version 6."""
from alembic import op
from sqlalchemy.engine import Connection

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

def _columns(c: Connection, table: str) -> set[str]:
    return {row[1] for row in c.exec_driver_sql(f"PRAGMA table_info({table})")}

def _add_column(c: Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(c, table):
        c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def migration_6_call_inbox(c: Connection) -> None:
    """Store learner-to-creator call requests, history, and durations."""
    c.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS calls(
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            module_id TEXT NOT NULL,
            learner INTEGER NOT NULL,
            creator INTEGER NOT NULL,
            initiated_by TEXT NOT NULL DEFAULT 'learner',
            status TEXT NOT NULL DEFAULT 'ringing',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            accepted_at INTEGER,
            ended_at INTEGER,
            duration INTEGER,
            ended_by INTEGER,
            failure_reason TEXT,
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id),
            FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE,
            FOREIGN KEY(learner) REFERENCES users(id),
            FOREIGN KEY(creator) REFERENCES users(id)
        )"""
    )
    c.exec_driver_sql("CREATE INDEX IF NOT EXISTS calls_creator_created ON calls(creator,created_at)")
    c.exec_driver_sql("CREATE INDEX IF NOT EXISTS calls_learner_created ON calls(learner,created_at)")

def upgrade():
    migration_6_call_inbox(op.get_bind())
    op.get_bind().exec_driver_sql("PRAGMA user_version=6")

def downgrade():
    raise RuntimeError("Trainly migrations are forward only; restore a backup to downgrade.")
