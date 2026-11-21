# Reconciliation module

## Purpose

Reconciliation compares the frozen expected quantities captured when a stocktake was created with the physical quantities from its latest submitted count round. It is deterministic and does not use AI or external model providers.

Variance is always:

`physical_quantity - expected_quantity`

A negative variance is a shortage, a positive variance is a surplus, and zero is matched.

## HTTP workflow

All endpoints are under `/api/reconciliations` and require a valid access token plus an active `X-Organization-ID` context.

| Method and path | Permission | Behaviour |
|---|---|---|
| `POST /stocktakes/{stocktake_id}/calculate` | `reconciliation.run` | Calculates one immutable run for the latest submitted count round. Repeating the request for that round returns the existing run. |
| `GET /{run_id}` | `reconciliation.review` | Returns the run summary and item-level variance lines. |
| `POST /{run_id}/approve` | `reconciliation.approve` | Independently approves a calculated run and atomically posts its stock adjustments. |
| `POST /{run_id}/reject` | `reconciliation.approve` | Rejects a calculated run with a required reason; stock balances remain unchanged. |

The client reviewer role receives run, review and approval permissions in migration `0014_reconciliation`. Count permissions are separate. The API also rejects a decision by any user who recorded an observation in the submitted round.

## Posting safeguards

- Every run has a version and identifies the exact stocktake and submitted count round.
- Every line stores frozen expected quantity, physical quantity, signed variance and unit.
- Only the approved run posts adjustments.
- Approval checks the stock balance version captured by the stocktake. If a sale, opening balance or other posted stock change occurred after the snapshot, approval returns HTTP 409 rather than overwriting newer stock.
- Stock balance changes, stock movement records, approval record and run status update commit in one transaction.
- Repeated calculation and approval requests are idempotent.
- Approved stocktakes cannot be reopened for recount.

## Current boundaries

The first release reconciles at item/unit grain. Batch/serial/location/condition matching, unmatched physical items, evidence-linked exceptions, verified-cost financial variance and richer supervisor queues remain future increments.
