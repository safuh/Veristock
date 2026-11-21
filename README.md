# Veristock One

Veristock One is the inventory verification and stocktaking platform for Veristock Inventory Solutions Ltd. The target MVP includes a FastAPI backend and three browser workspaces: Veristock management, field operations and the client portal. The current React application provides initial management and client workspaces; the responsive browser field workspace remains planned, while a separate Flutter Android field app supports online stocktake capture.

**Architecture:** Modular monolith · FastAPI · Python · SQLAlchemy 2.x · Alembic · PostgreSQL · React + TypeScript

**Scope:** Deterministic inventory management, stocktaking, reconciliation, reporting and replenishment. No AI provider or AI dependency is included in this delivery.

## Current implementation status

The repository is a modular-monolith MVP foundation with a tenant-aware FastAPI backend, PostgreSQL persistence, a React PWA client portal and a Flutter Android field application.

Implemented capabilities:

- Organization enrollment, platform-side review and client organization provisioning.
- Tenant-scoped organizations, branches, contacts, memberships, roles and permission checks.
- Explicit branch staff assignments with tenant-scoped membership validation, duplicate protection, assignment provenance and client-administrator management APIs.
- JWT authentication, browser refresh-cookie flow, identity context and platform administration APIs.
- Tenant-scoped inventory catalogue creation, stock-on-hand reads and branch opening balances.
- Append-only stock movement records for opening balances and posted sales.
- Reasoned manual stock adjustments through `POST /api/inventory/adjustments`, with actor provenance, idempotency, unit validation, non-negative balance enforcement and atomic ledger/projection updates.
- Branch-scoped stock movement history through `GET /api/inventory/movements`, including source, reason and actor metadata.
- Idempotent, atomic sales posting with unit validation and insufficient-stock protection.
- Physical stocktake creation with frozen branch/item expected quantities, blind count scope, immutable count observations, optional JPEG/PNG/WebP photo evidence, complete-round submission and recount rounds.
- React client workspace flows for item creation, opening balances, sales and stocktaking, including restoration of the latest open blind count and the current user's saved observations/evidence after a browser reload.
- Flutter Android field workflows for open stocktake retrieval, barcode matching, count capture, optional photo evidence upload and round submission. The field app restores the signed-in counter's own saved observations and attached-evidence metadata after reopening a stocktake; it does not expose other counters' in-progress blind counts.
- Installable PWA shell; service-worker caching is limited to static assets and does not cache authenticated API responses.
- Tenant-scoped deterministic inventory summary reporting, including branch totals and traceable source metrics.
- Tenant-scoped demand planning endpoint and client reporting table using posted sales velocity, current stock, days of cover, lead-time and safety-stock assumptions, and a configurable target coverage horizon. Branch/item replenishment policies are persisted through permission-protected APIs with actor provenance and applied automatically in branch-scoped forecasts; explicit request overrides take precedence. The client portal supports branch selection and inline policy management.
- CI coverage for Python 3.11–3.13, React production builds, Flutter analysis/tests and Android debug builds.

Important MVP boundaries still being completed:

- Branch assignments now gate field stocktake scope, own-observation restoration, count creation/replay, round submission and evidence upload. Applying branch-level authorization to inventory, sales and reporting remains outstanding.
- Veristock staff cross-tenant stocktake assignment and evidence upload.
- Immutable stocktake reconciliation runs compare the frozen expected snapshot with submitted physical counts, classify shortages/surpluses/matches, enforce reviewer separation-of-duties and atomically post approved adjustments with stale-snapshot protection. A tenant-scoped supervisor review queue now lists submitted stocktakes with branch, latest-round and shortage/surplus totals; recount requests now require a standardized reason code and explanation, and recount, rejection and approval actions are exposed through an audited decision history; the client portal provides a permission-gated supervisor queue with variance summaries, approval, reason-coded rejection and decision-history review. Supervisor rejection requires a reason and reopens the stocktake in a new immutable count round. Financial variance, unmatched-item exceptions and controlled correction remain outstanding.
- Richer reporting, supplier master data, broader forecast evaluation and anomaly detection. Initial rolling-origin evaluation is available for a selected item/branch; portfolio-wide accuracy and seasonality remain outstanding. Persisted branch/item replenishment policies are applied automatically in branch forecasts.
- Deterministic anomaly rules, verified-cost valuation, broader forecast evaluation and seasonality remain outstanding. The initial deterministic sales-velocity forecast, stockout-availability evidence and rolling-origin forecast evaluation are implemented.
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

API documentation is available at http://127.0.0.1:8000/docs.


In a second terminal, run the browser application:

```bash
cd web
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` requests to `http://127.0.0.1:8000`; set `VERISTOCK_API_URL` in the web environment if the API runs elsewhere.

## Database and initial platform owner

SQLite is configured for local development using a separate Veristock database file. Configure DATABASE_URL in .env for PostgreSQL.

**Existing database warning:** if you previously ran the standalone inventory-core branch, do not point this product branch at its old backbone.db file. This branch has a different tenant-aware migration history. Keep the old file as a backup and use a fresh veristock.db or a separate PostgreSQL database for this branch.

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

Client administrators can use the browser Team & access area to invite organization members, assign active members to branches and remove those assignments without deactivating their organization accounts. Invitations are single-use, expire after 72 hours and return a one-time token for secure manual delivery until an email provider is integrated. Field stocktaking endpoints enforce active branch assignments. Member invitation and assignment management remain permission-controlled.


Manual stock adjustments can be reversed through `POST /api/inventory/movements/{movement_id}/reversal`. The endpoint appends an exact compensating ledger event, requires a reason and `inventory.manage`, prevents duplicate reversals at the database level, and refuses a reversal that would make stock negative. Posted sale reversals remain a separate workflow.
