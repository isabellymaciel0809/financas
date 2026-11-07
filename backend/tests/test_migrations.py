"""As migrações precisam produzir exatamente o esquema dos modelos."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.database import Base
from app.migrate import BASELINE, alembic_config, run_migrations


def _engine(tmp_path, name):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _diff(engine):
    with engine.connect() as connection:
        return compare_metadata(MigrationContext.configure(connection), Base.metadata)


def test_banco_novo_fica_igual_aos_modelos(tmp_path):
    engine = _engine(tmp_path, "novo.db")
    run_migrations(engine)
    assert _diff(engine) == []


def test_banco_antigo_sem_historico_recebe_as_colunas_novas(tmp_path):
    """Simula o banco de quem usava o app antes do Alembic (criado no esquema inicial)."""
    engine = _engine(tmp_path, "antigo.db")
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, BASELINE)
        connection.exec_driver_sql("DROP TABLE alembic_version")  # como se fosse create_all

    run_migrations(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("expenses")}
    assert {"proposal", "entry_type"} <= columns
    assert _diff(engine) == []
