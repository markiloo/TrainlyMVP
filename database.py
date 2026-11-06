"""SQLAlchemy engines and short-lived sessions shared by API and media worker."""
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool


class Record(dict):
    """Mapping returned by textual reports; positional access supports scalar queries."""

    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)

    def __iter__(self):
        return iter(self.values())


class Records:
    def __init__(self, result):
        self.result = result

    @property
    def lastrowid(self):
        return self.result.lastrowid

    @property
    def rowcount(self):
        return self.result.rowcount

    def fetchone(self):
        row = self.result.mappings().fetchone()
        return Record(row) if row is not None else None

    def fetchall(self):
        return [Record(row) for row in self.result.mappings().fetchall()]

    def __iter__(self):
        return (Record(row) for row in self.result.mappings())


def bind_query(statement, parameters):
    """Bind existing SQLite report placeholders through SQLAlchemy, never interpolation."""
    if isinstance(parameters, Mapping):
        return text(statement), parameters
    values = tuple(parameters or ())
    parts, quote, index, offset = [], None, 0, 0
    while offset < len(statement):
        char = statement[offset]
        if quote:
            parts.append(char)
            if char == quote:
                if offset + 1 < len(statement) and statement[offset + 1] == quote:
                    parts.append(char)
                    offset += 1
                else:
                    quote = None
        elif char in ("'", '"'):
            quote = char
            parts.append(char)
        elif char == '?':
            parts.append(f':p{index}')
            index += 1
        else:
            parts.append(char)
        offset += 1
    if index != len(values):
        raise ValueError('Query parameter count does not match placeholders.')
    return text(''.join(parts)), {f'p{i}': value for i, value in enumerate(values)}


class TrainlySession(Session):
    """Normal ORM session with bound textual SQL support for existing reports/routes."""

    def execute(self, statement, params=None, **kwargs):
        if isinstance(statement, str):
            statement, params = bind_query(statement, params)
            result = super().execute(statement, params, **kwargs)
            # Textual writes can touch rows already loaded through the ORM.
            if not result.returns_rows:
                self.expire_all()
            return Records(result)
        return super().execute(statement, params, **kwargs)


def make_engine(path):
    engine = create_engine(
        URL.create('sqlite+pysqlite', database=str(Path(path).resolve())),
        connect_args={'timeout': 20, 'check_same_thread': False},
        poolclass=NullPool,
    )

    @event.listens_for(engine, 'connect')
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute('PRAGMA busy_timeout=20000')
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA foreign_keys=ON')
        finally:
            cursor.close()

    return engine


@contextmanager
def unit_of_work(engine):
    with TrainlySession(engine, expire_on_commit=False) as session:
        with session.begin():
            yield session
