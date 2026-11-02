"""Alembic environment: the database comes from app settings, models from app.models."""

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (register models on Base.metadata)
from app.db import Base, engine

config = context.config
target_metadata = Base.metadata


def _migrate(connection) -> None:
    # render_as_batch: SQLite cannot ALTER most things in place; PostgreSQL ignores it.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The app passes its own connection (also for in-memory SQLite in tests).
    connection = config.attributes.get("connection")
    if connection is not None:
        _migrate(connection)
        return
    if config.config_file_name:  # CLI run: show alembic's INFO log
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    with engine.begin() as connection:
        _migrate(connection)


if context.is_offline_mode():
    raise SystemExit("offline mode is not supported: run `alembic upgrade head` against a database")
run_migrations_online()
