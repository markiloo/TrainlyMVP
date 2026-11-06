"""Alembic upgrades, including the one-time PRAGMA user_version bridge."""
from pathlib import Path
import sqlite3
import time
import uuid

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent
LEGACY_HEAD = 6


def configuration(connection):
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'alembic'))
    config.attributes['connection'] = connection
    return config


def migrate(connection):
    """Upgrade an explicit SQLAlchemy connection; retain the old utility entry point."""
    if not isinstance(connection, Connection):
        # The maintenance caller retains ownership of this borrowed connection.
        engine = create_engine('sqlite://', creator=lambda: connection, poolclass=StaticPool)
        with engine.connect() as wrapped:
            _upgrade(wrapped)
            wrapped.commit()
        return
    _upgrade(connection)


def _upgrade(connection):
    config = configuration(connection)
    bridge_legacy(connection, config)
    command.upgrade(config, 'head')


def bridge_legacy(connection, config):
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'alembic_version' not in tables and 'modules' in tables:
        version = connection.exec_driver_sql('PRAGMA user_version').scalar_one()
        if not 0 <= version <= LEGACY_HEAD:
            raise RuntimeError(f'Unsupported legacy database version: {version}')
        MigrationContext.configure(connection).stamp(ScriptDirectory.from_config(config), f'{version:04}')


def upgrade_database(engine, runner=None):
    """Run once at startup under a SQLite write lock, before opening sessions."""
    with engine.connect() as connection:
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        current = MigrationContext.configure(connection).get_current_revision()
        head = ScriptDirectory.from_config(configuration(connection)).get_current_head()
        needs_backup = 'modules' in tables and current != head
        connection.commit()
        if needs_backup and engine.url.database not in (None, '', ':memory:'):
            destination = ROOT / 'backups' / f'pre-alembic-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}'
            destination.mkdir(parents=True)
            # The backup API includes committed WAL pages, unlike copying the main file.
            with sqlite3.connect(destination / Path(engine.url.database).name) as target:
                connection.connection.driver_connection.backup(target)
        try:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            if runner is None:
                _upgrade(connection)
            else:
                bridge_legacy(connection, configuration(connection))
                runner(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
