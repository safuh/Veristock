# Veristock AI Architecture

## Current implementation

The reporting API currently exposes `GET /api/reports/inventory/summary`, protected by `inventory.read`. It returns organization-scoped inventory totals, branch breakdowns and stable source references. These deterministic metrics are the first approved input source for future narrative generation.\n\nThe AI package is isolated under `src/veristock/ai`. It contains strict Pydantic
contracts for model provenance, vision assessments, demand forecasts, anomaly
findings and report narratives. The provider execution boundary currently supports
an injectable report-narrative provider; no commercial or hosted model SDK is a
mandatory dependency.

## Design rules

1. AI is advisory. It must never directly change stock balances, post sales,
   submit stocktake observations, approve reconciliation or write ledger entries.
2. Domain services remain the source of truth. AI receives precomputed,
   authorized metrics, not database sessions, ORM entities or arbitrary SQL.
3. Organization and actor identity are required at the application boundary.
   These identifiers stay inside Veristock and are not forwarded to providers.
4. Provider adapters implement the `AIProvider` protocol. Domain modules must not
   import vendor SDKs.
5. Provider calls have bounded timeouts. Provider failures must not interrupt
   inventory, sales, stocktaking or deterministic reporting.
6. Outputs use strict Pydantic contracts and carry provider/model provenance.
   Report narratives may cite only source references included in their input.
7. Any recommendation that can affect operations requires human review.

## Report narrative flow

1. A permission-checked reporting use case retrieves tenant-scoped metrics.
2. The reporting use case builds a `ReportNarrativeRequest` from those metrics.
3. `AIService` receives trusted organization/actor context for audit correlation.
4. The provider receives only the structured report request.
5. The result is checked for provider/model provenance and allowed source references.
6. The narrative is returned as advisory content; deterministic metrics remain
   authoritative.

## Deliberately not implemented yet

- Hosted LLM or vision provider adapters and secret configuration.
- Persistent AI operation/audit records and token/cost metering.
- Demand forecast execution and evaluation pipelines.
- Deterministic anomaly detection and evidence collection.
- Vision model inference and private image storage.
- User-facing AI chat or autonomous agents.
- Generated SQL execution.

Natural-language reporting must not execute model-generated SQL. It should use
predefined, parameterized report queries and provide only their authorized results
to the narrative provider.
