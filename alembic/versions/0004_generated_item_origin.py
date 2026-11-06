"""generated item origin. Converted from PRAGMA user_version 4."""
from alembic import op
from sqlalchemy.engine import Connection

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def _columns(c: Connection, table: str) -> set[str]:
    return {row[1] for row in c.exec_driver_sql(f"PRAGMA table_info({table})")}

def _add_column(c: Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(c, table):
        c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def migration_4_generated_item_origin(c: Connection) -> None:
    _add_column(c, "lessons", "origin", "TEXT NOT NULL DEFAULT 'manual'")
    _add_column(c, "questions", "origin", "TEXT NOT NULL DEFAULT 'manual'")

def upgrade():
    migration_4_generated_item_origin(op.get_bind())
    op.get_bind().exec_driver_sql("PRAGMA user_version=4")

def downgrade():
    raise RuntimeError("Trainly migrations are forward only; restore a backup to downgrade.")
