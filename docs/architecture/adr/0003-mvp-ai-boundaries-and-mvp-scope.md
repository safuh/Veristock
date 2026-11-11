# ADR 0003 — MVP scope and AI domain boundaries

- **Status:** Accepted for MVP implementation
- **Date:** 2026-11-11
- **Decision owners:** Veristock product and engineering

## Context

Veristock is a multi-tenant stock-taking and inventory intelligence platform. Stocktakes may be performed by Veristock personnel or by employees of the client organization. Client users must also be able to record sales (stock-out transactions) through the portal so that balances, forecasts and reports reflect operational activity without waiting for purchase-order or receipt document processing.

The MVP includes four intelligent capabilities:

1. Computer-vision-assisted stocktaking.
2. Inventory demand forecasting and replenishment recommendations.
3. Stock discrepancy and suspicious-activity detection.
4. Automated reporting and business intelligence.

The existing application is a modular monolith built on FastAPI, Pydantic, SQLAlchemy and PostgreSQL. The product must remain usable when AI providers are unavailable.

## Decision

### 1. Domain ownership

Inventory, stocktaking, sales, reconciliation and reporting facts belong to business domains. AI is a separate top-level domain at `src/veristock/ai/`.

AI modules may depend on stable application-level interfaces and read models, but business domains must not import AI modules. AI must not own stock balances, stock movements, sale transactions, count observations, reconciliation decisions or report facts.

The dependency direction is:

```text
API / application composition
          |
          +---- inventory domain
          +---- stocktaking domain
          +---- sales domain
          +---- reporting domain
          +---- AI domain
                    |
                    +---- vision adapters
                    +---- forecasting adapters
                    +---- anomaly detection
                    +---- narrative generation
```

The AI domain consumes authorized, tenant-scoped inputs from application services. It returns typed proposals, scores, forecasts or narratives. A business use case validates and applies any approved action.

### 2. Tenant and actor model

Every client-owned inventory resource is scoped by `organization_id`; branch-owned resources are additionally scoped by `branch_id`. The authenticated organization membership is resolved before use-case execution. Resource repositories always include tenant predicates; a caller-supplied organization ID is never treated as proof of access.

A stocktake records its owner organization, branch, performer type and performing user. The performer is either:
- a client employee with an active membership in the client organization and the required stocktake permission; or
- a Veristock employee with active platform membership and an explicit assignment to the client stocktake/branch scope.

A Veristock platform role alone must not grant ambient access to all client inventory. Cross-tenant field work requires an explicit assignment and is audited. Client employees do not need a Veristock employee profile.

### 3. Inventory and sales as the reporting ledger

Stock balances are derived from an auditable stock-movement ledger, not independently edited by portal forms. MVP movement types include opening balance, sale/stock-out, stocktake adjustment and approved correction. Each movement records tenant, branch, item, quantity, unit, effective time, actor, source reference and idempotency key.

Clients record sales through a portal/API workflow. A sale contains one or more lines. Posting a sale validates item and branch ownership, available quantity policy, unit, idempotency and permission, then atomically writes the sale and its stock-out movements. The sale is immutable after posting; corrections use explicit reversal/adjustment movements. The system must not allow the AI layer to post sales or mutate balances.

This gives analytics and forecasting a time series of stock-outs and observed demand. The MVP does not include POS integrations, purchase-order processing, goods-received-note processing, invoice OCR or supplier-document ingestion. Initial stock can be onboarded through a validated structured import/manual opening-balance process.

### 4. Stocktaking workflow and computer vision

The same stocktake/count workflow serves client employees and assigned Veristock employees. Blind counts do not expose expected quantities or unit costs to counters. Submitted count rounds are immutable; recounts create new rounds. Reconciliation compares a frozen expected-stock snapshot with an accepted count round and requires an authorized reviewer before any adjustment is posted.

Computer vision assists with barcode/label reading, product candidate matching and evidence capture. It may suggest an item or count, but it must not silently create observations or post stock movements. Low-confidence or ambiguous results require manual confirmation. Camera-based quantity estimation is advisory and is not a substitute for a verified physical count.

### 5. AI capabilities

| Capability | MVP implementation boundary | Safe output |
|---|---|---|
| Vision | Image preprocessing, barcode/OCR, optional product detection and catalogue matching | Candidate SKU, extracted label, confidence, evidence reference |
| Forecasting | CPU-friendly baseline models over posted sales/movements | Demand forecast, stockout risk, reorder suggestion and uncertainty |
| Anomaly detection | Rules and statistical baselines first; model-based scoring after enough history | Explainable risk signal for human review |
| BI/report narratives | SQL aggregates and deterministic metrics first; optional LLM narrative layer | Summary with metric definitions, period and source references |

Forecasting and anomaly detection must have deterministic baselines and be testable without model downloads or hosted APIs. LLMs may summarize approved metrics and answer questions using explicitly authorized analytics tools; they must not invent totals, perform authoritative arithmetic, or bypass row/tenant permissions.

### 6. Reporting and data freshness

Reports are generated from committed stock movements, posted sales, stocktake/reconciliation results and product/branch metadata. Every metric has a defined time basis and source. Operational dashboards can show near-real-time aggregates; generated reports record their period, generation time, filters and source version/watermark.

Sales posting and stock movement creation occur in one database transaction. Analytics may use indexed SQL views/queries initially; introduce asynchronous projections only when measured load justifies them. A failed AI service must never block sales posting, counting, reconciliation or deterministic report exports.

### 7. Security, audit and human control

- Enforce authorization in FastAPI dependencies and application services, never in prompts.
- Enforce tenant filters in repositories and test cross-tenant denial for each resource family.
- Blind-count endpoints must not return expected quantities, cost or valuation.
- Record actor, tenant, branch, request ID and source on sensitive stock changes.
- Store uploaded images in private object storage; serve them only after parent-resource authorization.
- Validate image MIME type, size and checksum; do not trust client filenames.
- Use idempotency keys for sales posting, count submissions and stock movements.
- AI output is untrusted input: validate with Pydantic, apply bounds and require human approval for consequential actions.
- Suspicious-activity signals are risk indicators, not findings of fraud or misconduct.

## Consequences

The MVP is a modular monolith with one database and explicit domain boundaries. This is intentionally simpler than microservices and can be split later if operational scale requires it.

The MVP does not implement purchase-document processing, supplier integrations, POS integrations, fixed-asset verification, advanced billing/accounting, employee performance ranking, or general customer-support agents. These remain later capabilities.

## Initial implementation sequence

1. Complete tenant-scoped inventory items, units, branch stock balances and append-only stock movements.
2. Implement client sale entry and atomic stock-out posting with idempotency.
3. Implement stocktake, count rounds, evidence metadata, reconciliation and approvals for both performer types.
4. Implement SQL reporting and exports from the business ledger.
5. Add the isolated AI package: provider interfaces, vision adapter, forecast service, anomaly scoring and narrative adapter.
6. Add evaluation datasets, model/version provenance, confidence thresholds, observability and failure-mode tests.
