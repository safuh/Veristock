"""Alembic migration environment for the Veristock application."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from veristock.ai import models as ai_models  # noqa: F401
from veristock.core.config import get_settings
from veristock.core.database import Base
from veristock.identity import (
    MembershipRole,  # noqa: F401
    Organization,  # noqa: F401
    OrganizationMembership,  # noqa: F401
    Permission,  # noqa: F401
    RefreshToken,  # noqa: F401
    Role,  # noqa: F401
    RolePermission,  # noqa: F401
    User,  # noqa: F401
)
from veristock.inventory import models as inventory_models  # noqa: F401
from veristock.inventory import policies as replenishment_policies  # noqa: F401
from veristock.invitations.models import OrganizationInvitation  # noqa: F401
from veristock.organizations.models import (
    Branch,  # noqa: F401
    OrganizationContact,  # noqa: F401
    OrganizationEnrollment,  # noqa: F401
)
from veristock.stocktaking import models as stocktaking_models  # noqa: F401
from veristock.stocktaking import evidence_models as stocktake_evidence_models  # noqa: F401
from veristock.workforce.models import EmployeeProfile  # noqa: F401

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
