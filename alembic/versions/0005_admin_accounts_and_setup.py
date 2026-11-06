"""admin accounts and one-time setup. Converted from PRAGMA user_version 5."""
from alembic import op
from sqlalchemy.engine import Connection

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

def _columns(c: Connection, table: str) -> set[str]:
    return {row[1] for row in c.exec_driver_sql(f"PRAGMA table_info({table})")}

def _add_column(c: Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(c, table):
        c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def migration_5_admin_accounts_and_setup(c: Connection) -> None:
    """Add administrator memberships and one-time account setup tokens.

    SQLite cannot alter a CHECK constraint in place, so an older memberships
    table is rebuilt only when it does not already accept the admin role.
    """
    c.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS account_setups(
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            expires INTEGER NOT NULL,
            accepted INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )"""
    )
    c.exec_driver_sql("CREATE INDEX IF NOT EXISTS account_setups_user ON account_setups(user_id)")
    row = c.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='table' AND name='memberships'").fetchone()
    if row and "'admin'" not in (row[0] or ""):
        c.exec_driver_sql("ALTER TABLE memberships RENAME TO memberships_legacy")
        c.exec_driver_sql(
            """CREATE TABLE memberships(
                workspace_id TEXT NOT NULL,
                user_id INTEGER NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK(role IN ('creator','learner','admin')),
                PRIMARY KEY(workspace_id,user_id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        c.exec_driver_sql("INSERT INTO memberships(workspace_id,user_id,role) SELECT workspace_id,user_id,role FROM memberships_legacy")
        c.exec_driver_sql("DROP TABLE memberships_legacy")

def upgrade():
    migration_5_admin_accounts_and_setup(op.get_bind())
    op.get_bind().exec_driver_sql("PRAGMA user_version=5")

def downgrade():
    raise RuntimeError("Trainly migrations are forward only; restore a backup to downgrade.")
