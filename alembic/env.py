"""CLI and startup migrations use the same connection and model metadata."""
import os
from pathlib import Path

from alembic import context
from database import make_engine
from models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get('connection')
if connection is not None:
    run(connection)
elif context.is_offline_mode():
    raise RuntimeError('Trainly migrations inspect SQLite; use an online database connection.')
else:
    # Importing data would seed the app and recursively invoke Alembic.
    from migrations import upgrade_database
    engine = make_engine(Path(os.environ.get('TRAINLY_DB', 'trainly.sqlite3')))
    upgrade_database(engine, runner=run)
    engine.dispose()
