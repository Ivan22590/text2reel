from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401  (register models)
from app.db import Base, run_migrations


def test_migrations_build_the_schema_the_models_describe(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    with engine.begin() as connection:
        run_migrations(connection)
    with engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == {
            "alembic_version", "projects", "scenes", "render_jobs",
        }  # fmt: skip
        # Fails when a model changes without a migration (new/removed column, table, index).
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], (
        f"models and migrations diverge, run `alembic revision --autogenerate`: {diff}"
    )


def test_migrations_are_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'twice.db'}")
    for _ in range(2):
        with engine.begin() as connection:
            run_migrations(connection)
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("select version_num from alembic_version").scalar() == "0001"
        )
