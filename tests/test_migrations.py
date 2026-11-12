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
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'ai_execution_records'"
                )
            )
            ai_audit_columns = {row[0] for row in result}
            result = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
            table_names = {row[0] for row in result}
            result = await connection.execute(
                text("SELECT COUNT(*) FROM permissions")
            )
            permission_count = result.scalar_one()
            result = await connection.execute(
                text("SELECT COUNT(*) FROM roles")
            )
            role_count = result.scalar_one()
            result = await connection.execute(
                text(
                    "SELECT COUNT(*) FROM role_permissions rp "
                    "JOIN roles r ON r.id = rp.role_id "
                    "JOIN permissions p ON p.id = rp.permission_id "
                    "WHERE r.code = 'client_admin' AND p.code = 'employee.invite'"
                )
            )
            client_admin_invite_grant = result.scalar_one()
        assert {"id", "identifier", "password_hash", "status", "created_at"} <= user_columns
        assert {"token_id", "subject", "expires_at", "revoked"} <= refresh_token_columns
        assert {
            "branches",
            "organization_contacts",
            "employee_profiles",
            "organization_invitations",
            "ai_execution_records",
        } <= table_names
        assert {
            "organization_id",
            "user_id",
            "operation",
            "status",
            "provider",
            "model",
            "latency_ms",
            "request_id",
            "source_references",
            "failure_code",
        } <= ai_audit_columns
        assert permission_count > 0
        assert role_count == 10
        assert client_admin_invite_grant == 1
    finally:
        await engine.dispose()

    subprocess.run([*command, "downgrade", "base"], check=True, env=env)
    subprocess.run([*command, "upgrade", "head"], check=True, env=env)
