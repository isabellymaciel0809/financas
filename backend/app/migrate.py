"""Aplica as migrações do banco (Alembic) ao iniciar o app."""

import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.database import Base

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE = "0001"  # esquema de quando o banco era criado com create_all, antes do Alembic


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["skip_logging"] = True  # não sobrescreve o logging do app
    return config


def run_migrations(engine: Engine) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if tables and "alembic_version" not in tables:
            # Banco criado antes das migrações existirem. Se já bate com os modelos, só marca
            # como atualizado; senão, marca o esquema inicial e aplica o que falta.
            up_to_date = not compare_metadata(MigrationContext.configure(connection), Base.metadata)
            command.stamp(config, "head" if up_to_date else BASELINE)
            logger.info(
                "Banco sem histórico de migrações marcado como %s",
                "head" if up_to_date else BASELINE,
            )
        command.upgrade(config, "head")
