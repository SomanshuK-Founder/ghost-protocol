from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from app.config import get_settings
from app.database import Base
from app import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().resolved_database_url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    # Callers that have already verified the exact database identity can pass
    # that same connection through Alembic's Config.attributes.
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        do_run_migrations(supplied_connection)
        return

    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        do_run_migrations(connection)

run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
