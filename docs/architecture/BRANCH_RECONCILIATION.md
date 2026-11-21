# Branch reconciliation and continuation policy

This document records completed development branches and the integration decision used for the current non-AI product line.

## Preserved branches

| Branch | Latest observed tip | Scope and disposition |
|---|---|---|
| `main` | `5d7471c` | Initial repository foundation; not modified by this integration. |
| `feat/mvp-architecture-domain-model` | `de50e13` | Product MVP baseline: tenancy, RBAC, organization onboarding, inventory, sales, stocktake capture, browser and Android foundations. |
| `feat/ai-foundation` | `cfe9a09` | 222 commits beyond the common product baseline. Contains substantial non-AI work as well as AI features. Preserved unchanged as a source branch. |
| `feat/inventory-core` | `18444cf` | Earlier standalone product/category/warehouse prototype. Preserved as historical work; its schema conflicts with the tenant-owned branch/item model. |
| `feat/continue-mvp-no-ai` | `0f1832e` | Non-AI baseline plus immutable reconciliation/approval and balance-version safeguards. Preserved unchanged. |

## Integrated branch

The active integration branch is `feat/integrated-no-ai`. It merges the completed non-AI capabilities from `feat/ai-foundation` into `feat/continue-mvp-no-ai`, while explicitly excluding AI implementation.

Non-AI capabilities retained from the source branch include:
- Branch membership assignments and branch-scoped field access.
- Private stocktake evidence metadata, upload and authorized retrieval.
- Supervisor review queue, recount reasons, rejection and immutable decision history.
- Reasoned manual stock adjustments and database-enforced single reversal.
- Branch/item replenishment policies.
- Deterministic inventory summary, sales-velocity demand planning, stock availability evidence and rolling-origin forecast evaluation.
- React report/policy/stocktake workflow refinements and Android session restoration.

The pure deterministic forecast calculations were moved from the old AI package to `veristock.analytics.forecasting`. Reporting endpoints now expose deterministic results only. AI provider composition, narrative endpoints, AI audit storage/API, AI migrations, AI tests and AI environment settings are excluded.

## Migration reconciliation

The migration chain is linear:
- `0013_client_stocktake_submit`
- `0014_reconciliation` — immutable reconciliation runs, approval records and stock-balance version snapshots
- `0015_replenishment_policies`
- `0016_stocktake_approval`
- `0017_stocktake_decisions`
- `0018_stocktake_rejection`
- `0019_stocktake_evidence`
- `0020_branch_memberships`
- `0021_client_admin_member_invite`
- `0022_stock_movement_reason`
- `0023_stock_movement_reversal`

The AI-only audit migration was removed. The replenishment migration now follows `0014_reconciliation`. SQLite portability fixes use Alembic batch operations for the stocktake and decision check-constraint changes. Existing released migration files before this chain remain unchanged.

## Approval safety

There are two historical stocktake approval surfaces. They must not both post stock adjustments for one stocktake. The reconciliation approval now marks the stocktake completed and records an approved decision; the legacy direct stocktake approval endpoint only accepts submitted stocktakes. The reconciliation endpoint also rejects a stocktake already completed by the legacy flow. This makes the terminal state mutually exclusive and prevents double posting.

## Integration rules

1. Do not merge the AI implementation back into this branch while AI remains deferred.
2. Keep deterministic forecasting in the analytics domain, not in an AI-named package.
3. Preserve the linear Alembic history; never create multiple heads or rewrite released migrations.
4. Maintain tenant/branch authorization, immutable count observations, separation of duties and append-only stock movement history.
5. Do not merge into `main` until the full backend, browser, Android, migration and tenant-isolation acceptance suites are green.
