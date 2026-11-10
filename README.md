# Veristock One

Veristock One is the inventory verification and stocktaking platform for Veristock Inventory Solutions Ltd. The MVP includes a FastAPI backend and three browser workspaces: Veristock management, field operations and the client portal.

**Architecture:** Modular monolith · FastAPI · Python · SQLAlchemy 2.x · Alembic · PostgreSQL · React + TypeScript

**AI policy:** No AI integration, AI dependencies, agents, LLM providers or vector database are included in the MVP.

## Current implementation status

The repository began as a reusable FastAPI foundation. The product architecture and domain model are documented, and the first identity/tenancy/RBAC foundation is being implemented.

- Existing application factory, async persistence, migrations, JWT primitives, Docker assets and tests are retained.
- Organization, membership, role and permission schema is being added through forward migrations.
- Authenticated identity and organization-context endpoints are being added.
- Management, field and client browser interfaces and the inventory business modules are not yet implemented.

See [Product Architecture](docs/architecture/PRODUCT_ARCHITECTURE.md), [Domain Model](docs/architecture/DOMAIN_MODEL.md), and [MVP Acceptance Tracker](docs/MILESTONES.md).

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker if you use the container workflow.

```bash
uv sync --extra dev
cp .env.example .env
```

Set a unique high-entropy JWT_SECRET_KEY in .env before using login or authenticated identity endpoints. Public self-registration is disabled by default.

Run checks and start the API:

```bash
make check
make run
```

API documentation is available at http://127.0.0.1:8000/docs.

## Database and initial platform owner

SQLite is configured for local development. Configure DATABASE_URL in .env for PostgreSQL.

Apply migrations:

```bash
make migrate-up
```

After migrations, bootstrap the first Veristock platform owner. Supply credentials through environment variables; do not place the password in shell history or source control.

```bash
export BOOTSTRAP_ADMIN_EMAIL="admin@example.com"
read -s BOOTSTRAP_ADMIN_PASSWORD
export BOOTSTRAP_ADMIN_PASSWORD
uv run python scripts/bootstrap_platform_admin.py
unset BOOTSTRAP_ADMIN_PASSWORD
```

The bootstrap command is idempotent for the same active account. It creates the initial platform organization, active membership and platform-owner role assignment. It does not create client organizations or invitations; those are subsequent product workflows.

## Security notes

- JWT issuer and access-token validator are composed from JWT_SECRET_KEY when configured.
- Protected identity routes require a valid bearer access token.
- Select an organization with X-Organization-ID; the API verifies active membership before returning context.
- Role scope must match organization kind.
- Self-registration is disabled by default. Production onboarding will use controlled invitations.
- Browser refresh-token cookie/CSRF handling and rate limiting remain implementation requirements before production release.

Review [SECURITY.md](SECURITY.md) before deployment.

## Deployment

Docker and Docker Compose assets are included. Kubernetes/Kustomize deployment is optional and is not an MVP prerequisite.
