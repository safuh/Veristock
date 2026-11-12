# Veristock AI Architecture

## Current implementation

The reporting API exposes:

- `GET /api/reports/inventory/summary`, protected by `inventory.read`, for deterministic tenant-scoped inventory metrics and branch totals.
- `POST /api/reports/inventory/narrative`, protected by `inventory.read`, for an advisory narrative generated only from the authorized inventory snapshot.
- `GET /api/reports/ai-executions`, protected by `inventory.read`, for the current tenant's recent AI execution history.
- `GET /api/reports/inventory/demand-forecast`, protected by `inventory.read`, for deterministic trailing-sales-average demand and replenishment estimates, optionally scoped to an active branch.

The AI package is isolated under `src/veristock/ai`. It contains strict Pydantic
contracts for model provenance, vision assessments, demand forecasts, anomaly
findings and report narratives. The provider execution boundary supports an
injectable report-narrative provider; no commercial or hosted model SDK is a
mandatory dependency.

AI execution metadata is persisted in `ai_execution_records`. Records identify
the organization and requesting user, operation, outcome, provider/model
provenance, latency, request ID, approved source references and a stable failure
code when applicable. Prompts, raw report payloads and generated narrative text
are deliberately not copied into the audit table. The history API returns only
safe operational fields and applies an explicit organization filter.

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
7. Every narrative execution outcome is recorded with tenant and actor identity.
   Audit records contain operational metadata, not prompts or raw business data.
8. Any recommendation that can affect operations requires human review.

## Report narrative flow

1. The permission-checked reporting route retrieves tenant-scoped inventory metrics.
2. The route builds a `ReportNarrativeRequest` from those deterministic metrics.
3. `AIService` receives trusted organization/actor context for audit correlation.
4. The provider receives only the structured report request.
5. The result is checked for provider/model provenance and allowed source references.
6. A success/failure/unavailable audit record is committed before the response.
7. The narrative is returned as advisory content; deterministic metrics remain
   authoritative.

The application factory accepts an `AIService` instance for provider injection. An optional `OpenAICompatibleProvider` adapter supports compatible hosted gateways and self-hosted servers such as Ollama. It activates only when `AI_PROVIDER=openai-compatible` and its base URL/model are configured. The adapter uses Python standard-library HTTP facilities and remains inactive unless explicitly configured.
Without one, the API uses an unconfigured service and returns HTTP 503 for the
narrative endpoint while recording the unavailable attempt. Provider execution
failures return HTTP 502 after recording a safe failure code.

## Deterministic demand planning baseline

The demand-forecast endpoint is independent of AI providers. It aggregates
posted sale-line quantities over a trailing UTC lookback window and current
stock balances for the same tenant and optional branch. The baseline average
includes zero-sale days. It reports average daily demand, days of cover and
the non-negative quantity needed to reach a caller-selected target coverage
horizon. Defaults are 30 days of sales history and 14 days of target coverage.

This is an intentionally simple baseline, not a statistically evaluated
forecast. It does not yet model supplier lead times, safety stock, service
levels, seasonality, promotions, stockout-censored demand or uncertainty
intervals. It never creates a purchase order or changes inventory. Replenishment
decisions remain with an authorized human.

## Deliberately not implemented yet

- Additional hosted LLM or vision adapters beyond the generic OpenAI-compatible chat-completions adapter.
- Token/cost metering and provider-specific usage reporting.
- Advanced demand forecast evaluation, seasonality and uncertainty pipelines.
- Deterministic anomaly detection and evidence collection.
- Vision model inference and private image storage.
- User-facing AI chat or autonomous agents.
- Generated SQL execution.

Natural-language reporting must not execute model-generated SQL. It should use
predefined, parameterized report queries and provide only their authorized results
to the narrative provider.

The client reporting API also exposes `GET /api/reports/ai-provider/status`,
protected by `inventory.read`. It reports whether a provider is configured and,
when configured, its provider/model identifiers. This is deliberately a
configuration-status check rather than a network health probe: it makes no
outbound request and never returns the provider endpoint or API credential.
