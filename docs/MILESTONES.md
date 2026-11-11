# Veristock One — MVP Acceptance Tracker

This tracker defines the full browser-based Veristock One MVP. A checkbox means the criterion has been verified; implementation alone is not verification.

## Product scope

**Included:** FastAPI backend, React + TypeScript browser application, management workspace, field operations workspace, client portal, PostgreSQL, tenant isolation, RBAC, branch/item/unit inventory, opening-stock onboarding, client-entered sales, stocktaking by either Veristock or client employees, reconciliation, inventory analytics/reporting, forecasting, discrepancy-risk detection and computer-vision-assisted counts.

**Explicitly excluded from this MVP:** purchase-order/receipt/invoice document processing, supplier and POS integrations, fixed-asset verification, advanced accounting/billing, native Android/iOS apps, microservices, general-purpose support agents and employee performance ranking. AI is in scope only for the four capabilities in ADR 0003; no general agent platform or vector database is required initially.

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

**Current limitation:** the standard issuer and validator are composed from JWT_SECRET_KEY when configured, or may be explicitly injected; custom implementations must share the same signing configuration. Browser endpoints now use HttpOnly refresh cookies and CSRF validation; legacy JSON-body token endpoints remain for non-browser clients. Invitation creation, acceptance and revocation are implemented; rate limiting, password recovery and business-resource authorization remain open. The bootstrap command creates the first platform owner but does not yet provide client-organization onboarding or invitations.

### M9 — Client organizations and workforce

**Status: in progress — initial tenant provisioning, branch/contact administration, employee profiles and single-use organization invitations are implemented; verification and remaining lifecycle workflows are open.**

- [ ] Client organization profile, branches and contacts.
- [x] Single-use, hashed, 72-hour organization invitations with revocation and acceptance.
- [x] Invitation acceptance creates or reuses a user, activates membership and grants the selected tenant-scoped role.
- [x] Tenant-scoped membership listing, role grants/revocation and membership suspension/reactivation/revocation, with protection against removing the final active invitation administrator.
- [ ] Veristock employee profiles and availability.
- [ ] Role assignment and employee access administration.
- [ ] Assignment membership and branch-scope enforcement.

**Implemented in the current M9 slice:** client tenant creation from an authorized platform context; current-tenant profile read/update; branch create/list/update with organization-scoped queries; contact create/list/update; internal employee profile create/list/update restricted to active platform members; migration `0006_organization_workforce`; single-use invitation creation, revocation and acceptance; invitation-token digest storage; tenant-scoped role validation; migration `0007_organization_invitations`; initial branch-isolation and invitation-flow tests. CI verification is pending. Employee availability, member role grant/revocation, broader lifecycle tests and assignment-level access remain outstanding.

### M10 — Commercial and operational management

- [ ] Quotation creation, versioning, sending and acceptance/rejection.
- [ ] Engagement creation from accepted scope and terms snapshot.
- [ ] Assignment planning, scheduling, location and team allocation.
- [ ] Assignment status transitions and audit events.
- [ ] Basic invoice and payment tracking.

### M11 — Inventory and sales ledger

**Status: planned — next business-domain implementation slice.**

- [ ] Tenant-owned inventory items, categories and controlled units of measure.
- [ ] Branch-scoped opening balances and optional warehouse locations.
- [ ] Validated structured import/manual opening-stock entry with provenance.
- [ ] Append-only stock movement ledger and current-balance projection.
- [ ] Client portal/API sales entry with line items and posting validation.
- [ ] Atomic sale + stock-out movement posting with idempotency.
- [ ] Reversal/correction workflow; no direct edits to posted sales or movements.
- [ ] Tenant/branch-scoped inventory search and stock-on-hand queries.
- [ ] Permission matrix and cross-tenant tests for inventory and sales.

**MVP boundary:** no purchase orders, goods-received notes, invoice ingestion, supplier integrations or POS integrations. The sales portal is the initial source of demand/stock-out history for reporting and forecasting.

### M12 — Physical stocktaking

**Status: planned — shared workflow for client and Veristock counters.**

- [ ] Stocktake creation and branch/location/item scope definition.
- [ ] Performer type: client employee or assigned Veristock employee.
- [ ] Explicit Veristock assignment and branch-scope authorization.
- [ ] Client membership/permission authorization for client counters.
- [ ] Blind-count API and UI behavior.
- [ ] Barcode/manual item identification and quantity capture.
- [ ] Image evidence upload with private storage and authorized retrieval.
- [ ] Vision-assisted barcode/OCR/catalogue matching with confidence and manual confirmation.
- [ ] Batch, serial, expiry and condition capture where enabled by item policy.
- [ ] Idempotent count submission and immutable count rounds.
- [ ] Recount workflow, supervisor queue and audit events.

### M13 — Reconciliation and discrepancy intelligence

- [ ] Reconciliation against frozen expected-stock snapshots and accepted count rounds.
- [ ] Configurable matching grain and unit validation.
- [ ] Shortage, surplus, missing, unrecognized and condition exceptions.
- [ ] Quantity variance and verified-cost financial variance.
- [ ] Exception resolution and recount handoff.
- [ ] Reviewer approval and separation-of-duties enforcement.
- [ ] Immutable, versioned reconciliation runs.
- [ ] Deterministic anomaly rules for unusual adjustments, sales and stock movement patterns.
- [ ] Explainable risk signals with evidence references; human review only, no automated accusations.

### M14 — Forecasting, reporting and business intelligence

- [ ] SQL-backed daily/weekly sales, stock movement and stock-on-hand metrics.
- [ ] Branch/item inventory valuation only where verified unit cost and currency exist.
- [ ] Low-stock, fast/slow-moving and stockout-risk reports.
- [ ] CPU-friendly baseline demand forecasts and reorder suggestions with uncertainty.
- [ ] Replenishment calculations use lead time, safety stock and configured service levels.
- [ ] Report period, filters, generation timestamp and source watermark are recorded.
- [ ] PDF/spreadsheet exports from deterministic query results.
- [ ] Optional LLM narrative grounded only in authorized, precomputed metrics.
- [ ] Tenant-scoped reporting permissions and cross-tenant tests.
- [ ] Reports remain available when AI providers are unavailable.

### M14A — AI platform foundations

- [ ] Separate `veristock.ai` package with provider-neutral interfaces.
- [ ] Model/provider configuration and safe timeouts; no provider secrets in domain modules.
- [ ] Structured outputs validated with Pydantic.
- [ ] Model/version, confidence, latency and failure metadata recorded.
- [ ] Evaluation fixtures for OCR/matching, forecasts, anomaly signals and report narratives.
- [ ] Human approval for any proposed action that can affect stock or business decisions.
- [ ] AI failure isolation: inventory, sales, counting and deterministic reporting continue without AI.

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

- [ ] Full unit, integration, tenant-isolation, authorization, AI evaluation and browser test suites pass.
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
