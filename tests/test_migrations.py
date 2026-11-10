import os
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_upgrade_and_downgrade() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    env = os.environ.copy()
    env["DATABASE_URL"] = url
    command = [sys.executable, "-m", "alembic"]
    subprocess.run([*command, "upgrade", "head"], check=True, env=env)

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'users'"
                )
            )
            user_columns = {row[0] for row in result}
            result = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'refresh_tokens'"
                )
            )
            refresh_token_columns = {row[0] for row in result}
            result = await connection.execute(
                text("SELECT COUNT(*) FROM permissions")
            )
            permission_count = result.scalar_one()
            result = await connection.execute(
                text("SELECT COUNT(*) FROM roles")
            )
            role_count = result.scalar_one()
        assert {"id", "identifier", "password_hash", "created_at"} <= user_columns
        assert {"token_id", "subject", "expires_at", "revoked"} <= refresh_token_columns
        assert permission_count > 0
        assert role_count == 9
    finally:
        await engine.dispose()

    subprocess.run([*command, "downgrade", "base"], check=True, env=env)
    subprocess.run([*command, "upgrade", "head"], check=True, env=env)
