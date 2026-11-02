"""A throw-away migrated database, so tests do not touch the shared in-memory one."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import run_migrations


@contextmanager
def temp_db(directory: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{directory / 'test.db'}")
    with engine.begin() as connection:
        run_migrations(connection)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
