# Veristock One — MVP Acceptance Tracker

This tracker defines the full browser-based Veristock One MVP. A checkbox means the criterion has been verified; implementation alone is not verification.

## Product scope

**Included:** FastAPI backend, React + TypeScript browser application, management workspace, field operations workspace, client portal, PostgreSQL, tenant isolation, RBAC, inventory onboarding, stocktaking, reconciliation, fixed asset verification, reporting and basic billing.

**Explicitly excluded:** all AI integration and scaffolding (PydanticAI, LLM providers, agents, embeddings, vector databases and AI-generated outputs), native Android/iOS apps, microservices, and advanced accounting/POS integrations.

## Foundation milestones retained from the backend repository

The following milestones describe the existing backend foundation. Their historical verification status is retained; they do not constitute completion of the Veristock One product MVP.

### M1 — Application foundation

**Status: complete and verified.**

- [x] Python src-layout package and application factory.
- [x] Development, test, and production configuration profiles.
- [x] Pydantic Settings validation and environment overrides.
- [x] FastAPI exception handling and stable error envelope.
- [x] Request correlation IDs in middleware and response headers.
- [x] Structured logging.
- [x] Explicit CORS configuration.
- [x] Liveness and database-backed readiness endpoints.
- [x] Deterministic application lifespan and engine disposal.

### M2 — Persistence and migrations

**Status: complete and verified.**

- [x] Async SQLAlchemy 2.x engine and session factory.
- [x] PostgreSQL/asyncpg production driver.
- [x] SQLite/aiosqlite development and test driver.
- [x] Transaction-scoped session helper.
- [x] Explicit Unit of Work transaction boundary.
- [x] Async Alembic environment.
- [x] Versioned foundation and identity migrations.
- [x] Migration upgrade/downgrade integration tests.
- [x] PostgreSQL integration test in CI.
- [x] Explicit migration-before-rollout deployment contract.

### M3 — Identity and JWT foundation

**Status: implemented and verified as reusable primitives; product authorization is not complete.**

- [x] Password hashing with Argon2.
- [x] Generic invalid-credential behavior.
- [x] Signed JWT access and refresh tokens.
- [x] Token expiration, subject, and token-type validation.
- [x] Refresh-token persistence, rotation, replay rejection, and revocation.
- [x] Registration, login, refresh, and logout HTTP endpoints.
- [x] Structured authentication audit events.
- [x] SQLAlchemy identity repositories and composition helper.
- [ ] Mandatory product authentication and browser security configuration.
- [ ] Organization memberships, RBAC, tenant context and resource-level authorization.

### M4 — Docker and local development

**Status: complete and verified.**

- [x] Locked dependency installation using uv.lock.
- [x] Non-root runtime container.
- [x] Production Dockerfile.
- [x] PostgreSQL-backed development Compose stack.
- [x] Container health check.
- [x] Production Compose definition with external database credentials.
- [x] Explicit one-shot Alembic migration before API startup.
- [x] Docker smoke-test script.
- [x] Docker smoke test passes on the release branch.

### M5 — Kubernetes deployment foundation

**Status: complete and verified.**

- [x] Canonical Kustomize base under k8s/base.
- [x] API Deployment and ClusterIP Service.
- [x] ConfigMap and non-committed Secret example.
- [x] Liveness and readiness probes.
- [x] Resource requests and limits.
- [x] Explicit migration Job.
- [x] Production overlay and migration overlay.
- [x] Optional Ingress example.
- [x] Optional HPA overlay.
- [x] Rollout and rollback instructions.
- [x] Production, migration, and HPA overlays render successfully in CI.

### M6 — Foundation release verification

**Status: complete and verified on the foundation release candidate.**

- [x] Ruff passes.
- [x] Mypy passes with no application errors.
- [x] Full test suite passes on Python 3.11, 3.12, and 3.13.
- [x] PostgreSQL integration and migration tests pass.
- [x] Package build and Twine validation pass.
- [x] Docker smoke test passes.
- [x] Production, migration, and HPA Kustomize overlays render successfully.
- [x] Secret scanning and dependency security workflows pass.
- [x] Foundation documentation commands match the repository.

## Veristock One product milestones

### M7 — Architecture and domain model

**Status: drafted; review and acceptance pending.**

- [ ] Approve modular-monolith architecture and browser workspace boundaries.
- [ ] Approve platform/client organization and membership model.
- [ ] Approve tenant isolation and authorization rules.
- [ ] Approve business entities and relationships.
- [ ] Approve stocktake, count-round, reconciliation and approval state machines.
- [ ] Approve role/permission matrix and separation-of-duties rules.
- [ ] Confirm MVP exclusions and delivery sequence.

Reference documents:
- [Product architecture](architecture/PRODUCT_ARCHITECTURE.md)
- [Domain model](architecture/DOMAIN_MODEL.md)

### M8 — Identity, tenancy and authorization

**Status: in progress — schema, seeded RBAC catalogue and initial identity endpoints implemented; full enforcement remains open.**

- [x] Preserve existing identity tables and JWT primitives; add forward migrations only.
- [x] Add organizations, memberships, roles, permissions and membership-role grants, including the restricted client-side field_counter role.
- [x] Add active/suspended/disabled user account status.
- [x] Add tenant-aware authorization queries and active organization-context dependency.
- [x] Add authenticated `GET /api/identity/me` and `GET /api/identity/context` endpoints.
- [x] Compose the standard SQLAlchemy authentication application and access-token validator from JWT settings; retain explicit custom-service injection.
- [x] Add one-time platform-owner bootstrap command; requires migrated database and environment-supplied credentials.
- [x] Disable public self-registration by default; explicit opt-in remains available for controlled environments.
- [x] Add initial repository and HTTP tests for membership, permission scope, field-counter access and cross-tenant denial.
- [ ] Apply mandatory authentication and permission dependencies to every product API as those modules are introduced.
- [ ] Enforce tenant filters and resource-level authorization in every business repository/use case.
- [x] Implement browser-safe HttpOnly refresh-token cookies, CSRF validation and browser logout endpoints.
- [ ] Add login/invitation/password-recovery rate limits.
- [ ] Add cross-tenant negative tests for every protected business resource family.

**Current limitation:** the standard issuer and validator are composed from JWT_SECRET_KEY when configured, or may be explicitly injected; custom implementations must share the same signing configuration. Browser endpoints now use HttpOnly refresh cookies and CSRF validation; legacy JSON-body token endpoints remain for non-browser clients. Rate limiting, invitation/password-recovery flows and business-resource authorization remain open. The bootstrap command creates the first platform owner but does not yet provide client-organization onboarding or invitations.

### M9 — Client organizations and workforce

**Status: in progress — initial tenant provisioning, branch/contact administration and internal employee profile APIs are implemented; verification and lifecycle workflows remain open.**

- [ ] Client organization profile, branches and contacts.
- [ ] User invitations and membership lifecycle.
- [ ] Veristock employee profiles and availability.
- [ ] Role assignment and employee access administration.
- [ ] Assignment membership and branch-scope enforcement.

**Implemented in the current M9 slice:** client tenant creation from an authorized platform context; current-tenant profile read/update; branch create/list/update with organization-scoped queries; contact create/list/update; internal employee profile create/list/update restricted to active platform members; migration `0006_organization_workforce`; initial branch tenant-isolation test. The API routes enforce the seeded RBAC permissions. These items remain unchecked until CI and additional lifecycle tests pass. Invitations, contact/branch lifecycle edge cases, employee availability, role administration and assignment-level access remain outstanding.

### M10 — Commercial and operational management

- [ ] Quotation creation, versioning, sending and acceptance/rejection.
- [ ] Engagement creation from accepted scope and terms snapshot.
- [ ] Assignment planning, scheduling, location and team allocation.
- [ ] Assignment status transitions and audit events.
- [ ] Basic invoice and payment tracking.

### M11 — Inventory onboarding

- [ ] Tenant-owned item catalogue, categories and units of measure.
- [ ] Branch and optional warehouse location hierarchy.
- [ ] Inventory file upload and mapping.
- [ ] Import validation, duplicate detection and error reporting.
- [ ] Immutable import provenance and expected-stock snapshots.
- [ ] Tenant-scoped inventory search and maintenance.

### M12 — Physical stocktaking

- [ ] Stocktake creation and scope definition.
- [ ] Count task allocation by branch/location/scope.
- [ ] Blind-count API and UI behavior.
- [ ] Barcode/manual item identification and quantity capture.
- [ ] Batch, serial, expiry and condition capture.
- [ ] Evidence upload and authorized retrieval.
- [ ] Idempotent count submission and immutable rounds.
- [ ] Recount workflow and supervisor queue.
- [ ] Assignment/stocktake completion controls.

### M13 — Reconciliation and quality assurance

- [ ] Reconciliation against frozen expected-stock snapshots.
- [ ] Configurable matching grain and unit validation.
- [ ] Shortage, surplus, missing, unrecognized and condition exceptions.
- [ ] Quantity variance and verified-cost financial variance.
- [ ] Exception resolution and recount handoff.
- [ ] Reviewer approval and separation-of-duties enforcement.
- [ ] Immutable, versioned reconciliation runs.

### M14 — Fixed assets and reporting

- [ ] Fixed asset register and physical verification.
- [ ] Missing, unregistered, moved and damaged asset exceptions.
- [ ] Draft, approved and published report lifecycle.
- [ ] PDF and spreadsheet exports from approved data.
- [ ] Report provenance, version and file checksum.
- [ ] Client report access and historical engagement views.

### M15 — Browser workspaces

- [ ] React + TypeScript application and shared component system.
- [ ] Management workspace flows.
- [ ] Field workspace responsive count flows.
- [ ] Client portal inventory and report flows.
- [ ] Typed API integration and loading/error/empty states.
- [ ] Browser authentication and permission-aware navigation.
- [ ] End-to-end tests for core management, field and client journeys.
- [ ] PWA/offline support only if its own conflict, encryption, retry and sync acceptance gate is approved.

### M16 — Production hardening and release

- [ ] Full unit, integration, tenant-isolation, authorization and browser test suites pass.
- [ ] PostgreSQL migration upgrade/downgrade and rollback procedures verified.
- [ ] Upload limits, file authorization and storage lifecycle verified.
- [ ] Backup and restore drill completed.
- [ ] Secrets, TLS, CORS, rate limits and operational configuration reviewed.
- [ ] Logs, metrics, health checks and alerting configured.
- [ ] Deployment and operator runbooks complete.
- [ ] Release acceptance signed off against all required product workflows.

## Release definition

The Veristock One MVP is releasable only when required M8–M16 acceptance criteria are verified, the critical client-to-report workflow works end to end, and tenant-isolation/security tests pass. Foundation M1–M6 completion is necessary but not sufficient.

## Change control

No AI integration or AI scaffolding may be introduced into the MVP. Changes to the agreed product scope, data ownership, authorization model or immutable count/reconciliation rules require an explicit architecture decision and updated acceptance criteria.
