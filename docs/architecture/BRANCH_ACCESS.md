# Branch-level authorization

Field members holding `stocktake.count` are restricted to active branches for
which their organization membership has an active `branch_memberships` record.
The `branch.manage` permission preserves tenant-wide branch-manager access.
Users without the field-counter permission continue to follow their existing
organization-level permissions.

The inventory balance and summary read endpoints apply this policy on the
server. A field member cannot widen the result by supplying another
`branch_id`; an inaccessible explicit branch is returned as not found, and a
member with no active assignments receives no branch stock rows.

This policy is additive to organization membership and permission checks. It
does not grant access to inventory or stocktaking by itself, and it does not
change the authoritative stock ledger or balances.

## Current enforcement boundary

- Inventory summary and stock-balance reads: branch-scoped for field counters.
- Stocktaking scope, own-observation restore, count writes/retries, submission,
  and evidence upload/retrieval: branch-scoped.
- Sales posting, opening-balance writes, sales history, manual stock adjustments,
  and stock movement history: branch-scoped.
- Replenishment policy listing and updates: branch-scoped.
- Inventory report summary, demand forecast and forecast evaluation: sales and
  stock aggregates are restricted to assigned branches. Explicit inaccessible
  branch filters are hidden as not found.
- Other branch-sensitive workflows: further enforcement work remains.
- Catalogue item metadata remains organization-wide because it is shared across
  branches; quantities and branch stock position are restricted.

## Verification

`tests/test_inventory_branch_scope.py` covers assigned versus unassigned
branch balances, explicit cross-branch lookup denial, and summary aggregation.
`tests/test_sales_branch_scope.py` covers sale, opening-balance and manual-adjustment
authorization before replay lookup, plus assigned-branch sales and stock-ledger
history. Reporting tests
assert that summary and forecast SQL aggregates include the assigned-branch
filters. These tests still require CI execution on the latest branch head.


## Manual adjustment reversals

- Reversals are available only for manual adjustment movements; sale correction remains a separate workflow.
- The caller must retain access to the original movement's branch and hold `inventory.manage`.
- Reversal appends the exact opposite quantity as a new ledger movement with a mandatory reason and actor provenance.
- The original movement is never updated or deleted. A tenant-scoped unique constraint allows at most one reversal per original movement.
- A reversal is rejected if its compensating quantity would make the current balance negative.
