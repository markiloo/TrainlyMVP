"""Persistence adoption: schema parity, legacy data, transactions, and worker isolation."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from database import TrainlySession, make_engine, unit_of_work
from migrations import configuration, upgrade_database
from models import Base, User, Workspace, TrainingModule, Lesson

ROOT = Path(__file__).resolve().parent.parent


def test_fresh_schema_matches_models_and_reopens(tmp_path):
    engine = make_engine(tmp_path / 'fresh.sqlite3')
    upgrade_database(engine)
    upgrade_database(engine)
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == '0006'
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())
    engine.dispose()


def test_app_and_worker_start_on_existing_legacy_database(tmp_path):
    path = tmp_path / 'installed.sqlite3'
    engine = make_engine(path)
    with engine.begin() as connection:
        command.upgrade(configuration(connection), 'head')
        connection.exec_driver_sql('DROP TABLE alembic_version')
        connection.exec_driver_sql("INSERT INTO users(id,email,name,password,role) VALUES(42,'saved@example.com','Saved','hash','creator')")
        connection.exec_driver_sql("INSERT INTO workspaces VALUES('saved','Saved workspace')")
        connection.exec_driver_sql("INSERT INTO memberships VALUES('saved',42,'creator')")
        connection.exec_driver_sql("INSERT INTO modules(id,owner,workspace_id,title,video) VALUES('saved',42,'saved','Saved training','private.mp4')")
    engine.dispose()
    env = dict(os.environ, TRAINLY_DB=str(path), TRAINLY_STORAGE=str(tmp_path / 'media'))
    script = "import app; from sqlalchemy.orm import Session; c=app.db(); assert isinstance(c,Session); assert c.get(__import__('models').TrainingModule,'saved').video=='private.mp4'; c.close()"
    for args in ([sys.executable, '-c', script], [sys.executable, 'worker.py', '--once'], [sys.executable, '-c', script]):
        result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0006'
        assert connection.execute("SELECT password FROM users WHERE id=42").fetchone()[0] == 'hash'


@pytest.mark.parametrize('version', range(7))
def test_legacy_versions_upgrade_without_losing_content(tmp_path, monkeypatch, version):
    import migrations
    monkeypatch.setattr(migrations, 'ROOT', tmp_path)
    # ROOT also controls configuration, so explicitly use the repository path.
    from alembic.config import Config
    def config(connection):
        value = Config(str(ROOT / 'alembic.ini'))
        value.set_main_option('script_location', str(ROOT / 'alembic'))
        value.attributes['connection'] = connection
        return value
    monkeypatch.setattr(migrations, 'configuration', config)
    path = tmp_path / 'legacy.sqlite3'
    engine = make_engine(path)
    # Build a real revision boundary, then remove Alembic's tracking to simulate
    # an installed PRAGMA-user_version database from that release.
    with engine.begin() as connection:
        command.upgrade(config(connection), f'{version:04}')
        connection.exec_driver_sql('DROP TABLE alembic_version')
        connection.exec_driver_sql(f'PRAGMA user_version={version}')
        connection.exec_driver_sql("INSERT INTO users(id,email,name,password,role) VALUES(42,'saved@example.com','Saved','hash','creator')")
        connection.exec_driver_sql("INSERT INTO workspaces VALUES('saved','Saved workspace')")
        connection.exec_driver_sql("INSERT INTO memberships VALUES('saved',42,'creator')")
        connection.exec_driver_sql("INSERT INTO modules(id,owner,title,video) VALUES('saved',42,'Saved training','private.mp4')")
        connection.exec_driver_sql("INSERT INTO lessons(id,module_id,ord,title,summary,start,end) VALUES('lesson','saved',0,'Saved lesson','Keep this',0,10)")
    migrations.upgrade_database(engine)
    with TrainlySession(engine) as session:
        assert session.get(User, 42).password == 'hash'
        assert session.get(TrainingModule, 'saved').video == 'private.mp4'
        assert session.get(Lesson, 'lesson').summary == 'Keep this'
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == '0006'
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
    backups = list((tmp_path / 'backups').glob('*/*.sqlite3'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == version
        assert backup.execute("SELECT video FROM modules WHERE id='saved'").fetchone()[0] == 'private.mp4'
    migrations.upgrade_database(engine)
    assert len(list((tmp_path / 'backups').glob('*/*.sqlite3'))) == 1
    engine.dispose()


def test_each_connection_enforces_sqlite_settings_and_rollback(tmp_path):
    engine = make_engine(tmp_path / 'transactions.sqlite3')
    upgrade_database(engine)
    for _ in range(3):
        with engine.connect() as connection:
            assert connection.exec_driver_sql('PRAGMA journal_mode').scalar_one() == 'wal'
            assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1
            assert connection.exec_driver_sql('PRAGMA busy_timeout').scalar_one() == 20000
    with pytest.raises(RuntimeError):
        with unit_of_work(engine) as session:
            session.add(Workspace(id='rolled-back', name='Rollback'))
            session.flush()
            raise RuntimeError('abort')
    with unit_of_work(engine) as session:
        assert session.get(Workspace, 'rolled-back') is None
    with pytest.raises(IntegrityError):
        with unit_of_work(engine) as session:
            session.add(Lesson(id='bad', module_id='missing', title='Missing parent'))
    engine.dispose()


def test_failed_upgrade_rolls_back_schema_and_revision(tmp_path, monkeypatch):
    import migrations
    monkeypatch.setattr(migrations, 'ROOT', ROOT)
    engine = make_engine(tmp_path / 'rollback.sqlite3')
    with engine.begin() as connection:
        command.upgrade(configuration(connection), '0004')
        connection.exec_driver_sql('DROP TABLE alembic_version')
        connection.exec_driver_sql('PRAGMA user_version=4')
        # Simulate an invalid historical membership. The admin-check rebuild
        # must fail without losing the original membership table or rows.
        connection.exec_driver_sql('PRAGMA ignore_check_constraints=ON')
        connection.exec_driver_sql("INSERT INTO users(id,email) VALUES(1,'saved@example.com')")
        connection.exec_driver_sql("INSERT INTO workspaces VALUES('local','Local')")
        connection.exec_driver_sql("INSERT INTO memberships VALUES('local',1,'invalid')")
    # Baseline already accepts admin; force the historical constraint definition.
    with engine.begin() as connection:
        connection.exec_driver_sql('PRAGMA ignore_check_constraints=ON')
        connection.exec_driver_sql('ALTER TABLE memberships RENAME TO old_memberships')
        connection.exec_driver_sql("CREATE TABLE memberships(workspace_id TEXT NOT NULL,user_id INTEGER NOT NULL UNIQUE,role TEXT NOT NULL CHECK(role IN ('creator','learner')),PRIMARY KEY(workspace_id,user_id))")
        connection.exec_driver_sql('INSERT INTO memberships SELECT * FROM old_memberships')
        connection.exec_driver_sql('DROP TABLE old_memberships')
    with pytest.raises(IntegrityError):
        upgrade_database(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA user_version').scalar_one() == 4
        assert connection.exec_driver_sql('SELECT role FROM memberships').scalar_one() == 'invalid'
        assert 'memberships_legacy' not in inspect(connection).get_table_names()
        assert 'alembic_version' not in inspect(connection).get_table_names()
    engine.dispose()
