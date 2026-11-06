"""generated drafts and events. Converted from PRAGMA user_version 3."""
from alembic import op
from sqlalchemy.engine import Connection

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def _columns(c: Connection, table: str) -> set[str]:
    return {row[1] for row in c.exec_driver_sql(f"PRAGMA table_info({table})")}

def _add_column(c: Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(c, table):
        c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def migration_3_generated_drafts_and_events(c: Connection) -> None:
    c.exec_driver_sql(
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
    c.exec_driver_sql(
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
    c.exec_driver_sql("CREATE INDEX IF NOT EXISTS events_name_created ON events(name,created_at)")
    c.exec_driver_sql("CREATE INDEX IF NOT EXISTS events_module ON events(module_id,created_at)")

def upgrade():
    migration_3_generated_drafts_and_events(op.get_bind())
    op.get_bind().exec_driver_sql("PRAGMA user_version=3")

def downgrade():
    raise RuntimeError("Trainly migrations are forward only; restore a backup to downgrade.")
