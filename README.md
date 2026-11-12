# Veristock One

Veristock One is the inventory verification and stocktaking platform for Veristock Inventory Solutions Ltd. The target MVP includes a FastAPI backend and three browser workspaces: Veristock management, field operations and the client portal. The current implementation provides the initial management and client workspaces; the field workspace is still planned.

**Architecture:** Modular monolith · FastAPI · Python · SQLAlchemy 2.x · Alembic · PostgreSQL · React + TypeScript

**AI policy:** AI contracts, provider-neutral narrative execution, tenant-scoped execution audit persistence and the first inventory narrative API are implemented. No hosted model provider is enabled by default. An optional OpenAI-compatible adapter can be enabled for compatible hosted gateways or self-hosted Ollama endpoints; no vendor SDK is required.

## Current implementation status

The repository is a modular-monolith MVP foundation with a tenant-aware FastAPI backend, PostgreSQL persistence, a React PWA client portal and a Flutter Android field application.

Implemented capabilities:

- Organization enrollment, platform-side review and client organization provisioning.
- Tenant-scoped organizations, branches, contacts, memberships, roles and permission checks.
- JWT authentication, browser refresh-cookie flow, identity context and platform administration APIs.
- Tenant-scoped inventory catalogue creation, stock-on-hand reads and branch opening balances.
- Append-only stock movement records for opening balances and posted sales.
- Idempotent, atomic sales posting with unit validation and insufficient-stock protection.
- Physical stocktake creation with frozen branch/item expected quantities, blind count scope, immutable count observations, complete-round submission and recount rounds.
- React client workspace flows for item creation, opening balances, sales and stocktaking.
- Flutter Android field workflows for open stocktake retrieval, barcode matching, count capture and round submission.
- Installable PWA shell; service-worker caching is limited to static assets and does not cache authenticated API responses.
- Tenant-scoped deterministic inventory summary reporting, including branch totals and traceable source metrics.
- Tenant-scoped demand planning endpoint and client reporting table using posted sales velocity, current stock, days of cover, lead-time and safety-stock assumptions, and a configurable target coverage horizon. Branch/item replenishment policies are persisted through permission-protected APIs with actor provenance and applied automatically in branch-scoped forecasts; explicit request overrides take precedence. The client portal supports branch selection and inline policy management.
- Initial AI contracts for vision assessments, demand forecasts, anomaly findings and report narratives, plus a provider-neutral narrative service with tenant-context separation, bounded inputs, timeouts and source-reference validation.
- Tenant-scoped AI execution audit persistence and a permission-protected inventory narrative endpoint. Audit records retain actor, organization, provider/model provenance, latency, source references and safe failure codes without storing prompts or raw report payloads.
- CI coverage for Python 3.11–3.13, React production builds, Flutter analysis/tests and Android debug builds.

Important MVP boundaries still being completed:

- Veristock staff cross-tenant stocktake assignment and evidence upload.
- Reconciliation runs, discrepancy review/approval and controlled ledger corrections.
- Richer reporting, supplier master data, forecast evaluation and anomaly detection. Persisted branch/item replenishment policies are implemented; applying them automatically in branch forecasts remains outstanding.
- Hosted AI providers, deterministic anomaly detection, vision inference and user-facing AI workflows remain outstanding. The first deterministic sales-velocity forecast is implemented; advanced forecast evaluation and seasonality remain outstanding.
- Email delivery, password recovery, rate limiting, production release signing, deployment secrets and operational monitoring.
- Offline Android capture and conflict-safe synchronization are not enabled; current mobile count capture requires connectivity.

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

API documentation is available at http://127.0.0.1:8000/docs.\n\nTo enable optional AI narrative generation, install the HTTP adapter and configure `AI_PROVIDER`, `AI_BASE_URL`, and `AI_MODEL` in `.env` (plus `AI_API_KEY` when your endpoint requires it), then restart the API:\n\n```bash\nuv sync --extra dev\n```\n\nLeave `AI_PROVIDER` unset to keep AI disabled. For a local Ollama-compatible endpoint, the base URL is commonly `http://localhost:11434/v1`; select a model already pulled by your Ollama instance. Provider configuration is server-side only and should never be exposed to client browsers.

In a second terminal, run the browser application:

```bash
cd web
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` requests to `http://127.0.0.1:8000`; set `VERISTOCK_API_URL` in the web environment if the API runs elsewhere.

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

## Frontend applications

### Web PWA

```bash
cd web
npm install
npm run dev
```

The web application can be installed from supported browsers. Offline mode currently makes the static application shell available only; authenticated organization data is not cached and operational offline writes are not enabled.

### Flutter Android client

```bash
cd mobile
flutter create --platforms=android --project-name=veristock_mobile .
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api
```

The default URL is for the Android emulator. Use the development machine's LAN IP for a physical device. The Android client provides authentication, organization selection, open-stocktake retrieval, barcode-to-item matching, online count capture and count-round submission. Offline queueing and conflict-safe sync are not yet enabled.
