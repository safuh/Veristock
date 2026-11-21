# Veristock One — MVP Acceptance Tracker

This tracker defines the Veristock One MVP across its browser workspaces and Android field application. A checkbox means the criterion has been verified; implementation alone is not verification.

## Product scope

**Included:** FastAPI backend, React + TypeScript browser application, management workspace, field operations workspace, client portal, PostgreSQL, tenant isolation, RBAC, branch/item/unit inventory, opening-stock onboarding, client-entered sales, stocktaking by either Veristock or client employees, reconciliation, inventory analytics/reporting, forecasting, discrepancy-risk detection and computer-vision-assisted counts.

**Explicitly excluded from this MVP:** purchase-order/receipt/invoice document processing, supplier and POS integrations, fixed-asset verification, advanced accounting/billing, native iOS app, microservices, general-purpose support agents and employee performance ranking. AI/ML, LLMs, computer vision, OCR and model-provider integrations are explicitly deferred until the deterministic product is accepted.

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

- [x] Client administrator permission to invite tenant members and manage branch assignments.
- [x] Client portal Team & access page to invite members with a one-time token, assign active members to branches and remove assignments without revoking organization membership.

- [x] Tenant-scoped branch staff assignment records and client-administrator assignment APIs with audit provenance.
- [x] Branch assignment management UI in the client portal.

**Status: in progress — business enrollment, platform-side client administration, tenant profile/branch/contact APIs, employee profiles and invitations are implemented; lifecycle verification and workforce workflows remain open.**

- [x] Client organization profile, branches and contacts.
- [x] Single-use, hashed, 72-hour organization invitations with revocation and acceptance.
- [x] Invitation acceptance creates or reuses a user, activates membership and grants the selected tenant-scoped role.
- [x] Tenant-scoped membership listing, role grants/revocation and membership suspension/reactivation/revocation, with protection against removing the final active invitation administrator.
- [ ] Veristock employee profiles and availability.
- [ ] Role assignment and employee access administration.
- [ ] Assignment membership and branch-scope enforcement.

**Implemented in the current M9 slice:** authenticated business enrollment; platform-only enrollment review and client directory/status management; atomic client tenant provisioning with the first client administrator; current-tenant profile read/update; branch and contact create/list/update; internal employee profile create/list/update restricted to active platform members; single-use invitation creation, revocation and acceptance; invitation-token digest storage; tenant-scoped role validation; migrations `0006`–`0009`; initial enrollment, branch-isolation and invitation-flow tests. Employee availability, member role grant/revocation, broader lifecycle tests and assignment-level access remain outstanding.

### M10 — Commercial and operational management

- [ ] Quotation creation, versioning, sending and acceptance/rejection.
- [ ] Engagement creation from accepted scope and terms snapshot.
- [ ] Assignment planning, scheduling, location and team allocation.
- [ ] Assignment status transitions and audit events.
- [ ] Basic invoice and payment tracking.

### M11 — Inventory and sales ledger

**Status: in progress — catalogue creation, opening balances, append-only stock movements, current-balance projections and atomic idempotent sales posting are implemented; full reconciliation and correction workflows remain open.**

- [x] Tenant-owned inventory items with barcode/SKU identifiers and explicit base-unit codes.
- [ ] Controlled unit-of-measure catalogue and item categories.
- [x] Branch-scoped opening balances.
- [ ] Optional warehouse/bin locations.
- [x] Validated manual opening-stock entry with actor provenance and idempotency.
- [x] Reasoned manual stock adjustments with actor provenance, signed quantity validation, idempotency and atomic ledger/balance updates.
- [x] Branch-scoped read access to append-only stock movement history, including adjustment reasons and actor provenance.
- [x] React client portal stock-adjustment form with non-zero signed quantity and reason validation, plus recent branch-scoped stock ledger history.
- [ ] Validated structured import with row-level error reporting.
- [x] Append-only stock movement ledger and current-balance projection.
- [x] Branch-scoped lot/batch records with manufacture/expiry dates, supplier references and quarantined/recalled/closed states.
- [x] Batch-level quantity balances and traceable receipt/issue stock movements.
- [x] FEFO batch allocation that excludes expired, quarantined, recalled and closed lots; atomic balance updates and idempotent issue replay.
- [x] Expiry-window batch listing for operational alerts.
- [x] Client portal/API sales entry with line items and posting validation.
- [x] Atomic sale + stock-out movement posting with idempotency.
- [x] Manual adjustment reversal by appending a reasoned, actor-attributed compensating movement; database-enforced single reversal and non-negative balance guard.
- [ ] Posted sale reversal/correction workflow; no direct edits to posted sales or movements.
- [x] Initial tenant-scoped inventory catalogue and stock-on-hand read APIs.
- [ ] Tenant/branch-scoped inventory search, pagination and filtering beyond the initial read endpoints.
- [ ] Permission matrix and cross-tenant tests for inventory and sales.

**MVP boundary:** batch receiving is currently a controlled stock receipt, not a purchase-order/GRN workflow. No purchase orders, invoice ingestion, supplier integrations or POS integrations are included yet. The sales portal is the initial source of demand/stock-out history for reporting and forecasting.

### M12 — Physical stocktaking

- [x] Enforce explicit branch assignment for field count scope, observation restore/write/replay, round submission and evidence upload; branch managers retain cross-branch access.
- [x] Extend branch authorization to inventory balance/summary reads, sales posting/history, opening-balance replay, replenishment policies, inventory reporting, demand forecasts and forecast evaluation.
- [ ] Verify branch authorization with full CI and add end-to-end browser/Android role acceptance.

**Status: in progress — tenant-scoped branch snapshots, blind scope listing, immutable count observations, idempotent capture, complete-round submission, recount rounds and separately authorized approval-to-ledger reconciliation are implemented for client-organization counters. Veristock cross-tenant staff assignment, production-grade shared evidence storage/scanning and broader supervisor separation-of-duties enforcement remain open. React and Android photo-evidence controls are implemented; full end-to-end device/browser acceptance remains open.**

- [x] Stocktake creation and branch/item scope definition with frozen expected quantities.
- [ ] Performer type: client employee or assigned Veristock employee (client-member counter access is implemented).
- [ ] Explicit Veristock assignment and branch-scope authorization.
- [x] Client membership and permission authorization for client counters.
- [x] Blind-count API behavior; expected quantities are withheld from blind count scope responses.
- [x] Manual/barcode-identified item quantity capture API.
- [x] Tenant-scoped image evidence upload/retrieval for count observations, with generated private storage keys, upload-size/type checks, SHA-256 metadata and authorized retrieval.
- [ ] Shared object-storage adapter, malware/content scanning, image re-encoding and retention lifecycle controls.
- [ ] Vision-assisted barcode/OCR/catalogue matching with confidence and manual confirmation.
- [ ] Batch, serial, expiry and condition capture where enabled by item policy.
- [x] Idempotent count observations and immutable count rounds with completeness checks.\n- [x] Counter-only retrieval of the current user's active-round observations, allowing Android count sessions to resume without revealing another counter's blind-count values.
- [x] Recount round creation and separately authorized approval of submitted counts; approved variances post idempotent `stocktake_adjustment` ledger movements while preserving movements recorded after each observation.
- [x] API-enforced count/approval separation of duties.
- [x] Tenant-scoped supervisor review queue with branch filtering, latest-round totals and shortage/surplus counts.
- [x] Standardized recount reason codes and mandatory explanation, plus append-only recount-requested and approval decision history.
- [x] Supervisor rejection with mandatory reason code and explanation; rejected submissions are reopened as a new immutable count round, with actor and decision retained in the audit history.
- [x] Client portal supervisor review queue with variance summaries, permission-gated approve/reject controls, mandatory rejection explanation and decision-history display.\n- [x] Web and Android count sessions can restore the current counter's active-round observations and evidence metadata after reopening; the restore API never exposes another counter's in-progress blind-count values.

### M13 — Reconciliation and discrepancy intelligence

- [x] Immutable reconciliation runs against frozen expected-stock snapshots and submitted count rounds.
- [x] Shortage, surplus and matched classifications with signed quantity variance.
- [x] Reviewer approval/rejection with separation-of-duties and atomic stock-ledger posting.
- [x] Optimistic stock-balance version checks prevent stale reconciliation approvals.
- [x] Supervisor review queue, recount/rejection decisions and decision history.
- [ ] Configurable matching grain and unit validation.
- [x] Deterministic shortage, surplus and match classifications; missing-scope, unrecognized-item and condition exceptions remain open.
- [ ] Quantity variance and verified-cost financial variance.
- [ ] Exception resolution and recount handoff.
- [ ] Reviewer approval and separation-of-duties enforcement.
- [ ] Immutable, versioned reconciliation runs.
- [ ] Deterministic anomaly rules for unusual adjustments, sales and stock movement patterns.
- [ ] Explainable risk signals with evidence references; human review only, no automated accusations.

### M14 — Forecasting, reporting and business intelligence

**Status: in progress — tenant-scoped inventory reporting, deterministic sales-velocity forecasts, stock-availability evidence and an initial rolling-origin forecast evaluation are implemented; advanced planning and evaluation remain open.**

- [x] SQL-backed posted-sales and current-stock aggregates for the initial demand forecast.
- [ ] Branch/item inventory valuation only where verified unit cost and currency exist.
- [ ] Low-stock, fast/slow-moving and stockout-risk reports.
- [x] CPU-friendly trailing-average demand baseline and target-coverage replenishment suggestions.
- [x] Initial rolling-origin backtesting for an explicitly selected item/branch, with MAE per day, WAPE and forecast-bias diagnostics.
- [ ] Broader portfolio evaluation, uncertainty bounds, seasonality and stockout-censored demand validation.
- [x] Replenishment calculations use saved or explicitly overridden lead-time and safety-stock days.
- [ ] Configured service levels, order multiples and minimum order quantities.
- [ ] Report period, filters, generation timestamp and source watermark are recorded.
- [ ] PDF/spreadsheet exports from deterministic query results.
- [x] Optional LLM narrative grounded only in authorized, precomputed metrics.
- [x] Restrict field-counter inventory summaries, demand forecasts and forecast evaluation to assigned branches.
- [ ] Complete broader tenant-scoped reporting permission and cross-tenant test coverage.
- [x] Deterministic report and forecast APIs operate without any AI provider or model dependency.

### AI — explicitly deferred

No AI/ML providers, inference endpoints, OCR/vision workflows, LLM narratives or AI-specific operational dependencies are included in this delivery. Revisit only after deterministic M8–M16 acceptance and explicit product-owner approval.

### M15 — Browser workspaces

**Status: in progress — React + TypeScript browser foundation, browser authentication, management onboarding dashboard and initial client inventory view are implemented.**

- [x] React + TypeScript application foundation and responsive workspace shell.
- [x] Browser login, HttpOnly refresh-cookie session restoration and logout integration.
- [x] Veristock management dashboard for reviewing client applications and listing client organizations.
- [x] Client portal organization context, branch list, inventory summary and stock-balance view.
- [ ] Complete management workspace flows.
- [ ] Field workspace responsive count flows.
- [x] Flutter Android client with secure token storage, session restoration, organization selection, assigned open-stocktake retrieval, blind count capture, barcode matching, count-round submission and photo evidence upload.
- [x] Automatic access-token refresh on 401 with coalesced concurrent refresh attempts and secure-session clearing for invalid refresh credentials.
- [ ] Encrypted offline task storage, conflict-safe synchronization, Android release signing and physical-device acceptance.
- [x] Initial client portal sales posting and stocktaking count flows.
- [ ] Verify end-to-end browser and Android photo-evidence upload/retrieval on supported devices and tenant roles.
- [ ] Client portal discrepancy and advanced forecast flows.
- [x] Client portal deterministic demand-forecast and inventory report view, including configurable lead-time and safety-stock assumptions.
- [x] Persist branch/item lead-time and safety-stock policies with tenant-scoped read/write APIs and updater provenance.
- [x] Apply saved policies automatically in branch-scoped forecasts, support explicit request overrides, and expose policy source per item.
- [x] Add client portal branch selection and inline policy editing/saving; all-branch forecasts intentionally use shared overrides or zero-day defaults.
- [x] Expose historical forecast error diagnostics through the tenant-scoped rolling-origin evaluation API.
- [ ] Add client UI for forecast evaluation and improve stockout-censored demand validation.
- [ ] Typed API integration and loading/error/empty states across all remaining workflows.
- [x] Reports and forecasts load exclusively from deterministic API results.
- [ ] Browser authentication and permission-aware navigation.
- [ ] End-to-end tests for core management, field and client journeys.
- [x] Installable React PWA shell with manifest and static-asset precaching; authenticated API responses are explicitly excluded from service-worker caching.
- [ ] Offline business operations only after encrypted local storage, authorization expiry, idempotent retries, conflict resolution and sync acceptance gates are implemented.

### M16 — Production hardening and release

- [ ] Full unit, integration, tenant-isolation, authorization, deterministic business-workflow and browser test suites pass.
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

AI capabilities are explicitly outside the current MVP scope. Do not add AI providers, inference endpoints, OCR/vision, LLM narratives or model dependencies until the non-AI acceptance criteria are complete and the product owner explicitly reopens the scope. Changes to the agreed product scope, data ownership, authorization model or immutable count/reconciliation rules require an explicit architecture decision and updated acceptance criteria.
