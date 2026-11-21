# Branch reconciliation and continuation policy

This note records the repository's pre-existing development lines so completed work is not lost or reimplemented.

## Known branches

| Branch | Latest observed tip | Scope and disposition |
|---|---|---|
| `main` | `5d7471c` | Initial repository foundation. |
| `feat/mvp-architecture-domain-model` | `de50e13` | Product MVP baseline: tenancy, RBAC, organization onboarding, invitations, workforce profiles, tenant-scoped inventory, sales posting, physical stocktake capture/recounts, browser shell and Android client foundation. Selected as the baseline for the current no-AI continuation. |
| `feat/ai-foundation` | `cfe9a09` | Later superset of the MVP line. It contains additional non-AI work (branch assignments, evidence uploads, stocktake approval/rejection, manual adjustments and reversals, replenishment policies, deterministic reports, and browser/mobile refinements) alongside AI work. Do not merge this branch wholesale while AI is deferred. Port and verify its non-AI improvements selectively, preserving the migration chain. |
| `feat/inventory-core` | `18444cf` (local) | Earlier standalone catalogue/warehouse/stock-ledger prototype. Its generic product/category/warehouse schema is superseded by the tenant-owned inventory and branch model in the MVP line. Preserve the branch as historical work; do not merge its conflicting migration/model layer directly. |

The two remote feature branches were observed to share the initial `main` base. The local `feat/inventory-core` work is a separate implementation and is not an ancestor of the product MVP line.

## Current continuation

The active implementation branch is `feat/continue-mvp-no-ai`, based on `feat/mvp-architecture-domain-model`. It deliberately excludes the AI package/contracts from the baseline and keeps the current scope deterministic.

The current increment adds:
- Versioned, immutable reconciliation runs tied to a submitted count round.
- Frozen expected-versus-physical quantity lines and shortage/surplus/matched classification.
- Independent reviewer approval/rejection with separation-of-duties checks.
- Atomic posting of approved variance to stock balances and the movement ledger.
- Stock-balance versioning so an approval is rejected if intervening stock movements occurred after the stocktake snapshot.
- A forward Alembic migration and end-to-end API tests.

## Integration rules

1. Do not merge `feat/ai-foundation` wholesale while AI is excluded.
2. Port non-AI changes as coherent slices with their tests and documentation.
3. Reconcile Alembic revision ancestry before importing any migration from another branch; never leave multiple heads or rewrite already-released migrations.
4. Keep tenant authorization, branch scope, immutable count observations and approval separation-of-duties intact.
5. Do not merge to `main` until the product acceptance tracker and full CI suite are green.
