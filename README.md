# Veristock One

Veristock One is the inventory verification and stocktaking platform for Veristock Inventory Solutions Ltd. The target MVP includes a FastAPI backend and three browser workspaces: Veristock management, field operations and the client portal. The current implementation provides the initial management and client workspaces; the field workspace is still planned.

**Architecture:** Modular monolith · FastAPI · Python · SQLAlchemy 2.x · Alembic · PostgreSQL · React + TypeScript

**AI policy:** No AI integration, AI dependencies, agents, LLM providers or vector database are included in the MVP.

## Current implementation status

The repository began as a reusable FastAPI foundation. It now contains the initial organization onboarding workflow and a React browser application foundation for Veristock staff and client users. The browser workspaces are being connected incrementally to the inventory and stocktaking APIs.

- Existing application factory, async persistence, migrations, JWT primitives, Docker assets and tests are retained.
- Organization, membership, role and permission schema is added through forward migrations.
- Authenticated identity and organization-context endpoints are available.
- Organization enrollment, platform-side client management, tenant-scoped branches and contacts, employee profiles, secure invitations, and membership/role administration are implemented as initial APIs.\n- The React + TypeScript web app provides browser login/session restoration, organization selection, a Veristock management dashboard for applications and client organizations, and a client workspace shell with branch visibility.\n- Inventory, sales, stocktaking, forecasting, discrepancy and reporting screens are not complete yet; they will be connected as their protected APIs are implemented.
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

API documentation is available at http://127.0.0.1:8000/docs.\n\nIn a second terminal, run the browser application:\n\n```bash\ncd web\nnpm install\nnpm run dev\n```\n\nOpen http://localhost:5173. Vite proxies `/api` requests to `http://127.0.0.1:8000`; set `VERISTOCK_API_URL` in the web environment if the API runs elsewhere.

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
- Browser login/refresh/logout use HttpOnly refresh cookies and CSRF validation; browser responses do not expose refresh tokens.
- Select an organization with X-Organization-ID; the API verifies active membership before returning context.
- Role scope must match organization kind.
- Self-registration is disabled by default. Production onboarding will use controlled invitations.
- Invitation tokens are single-use, stored as SHA-256 digests and expire after 72 hours; delivery is not yet integrated with an email provider, so the token is returned once to the authorized inviter for secure delivery.
- Rate limiting and password-recovery flows remain implementation requirements before production release.

Review [SECURITY.md](SECURITY.md) before deployment.

## Deployment

Docker and Docker Compose assets are included. Kubernetes/Kustomize deployment is optional and is not an MVP prerequisite.
