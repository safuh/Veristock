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
- Sales posting, opening-balance writes, and sales history: branch-scoped.
- Replenishment policy listing and updates: branch-scoped.
- Broader reporting and other branch-sensitive workflows: further enforcement
  work remains.
- Catalogue item metadata remains organization-wide because it is shared across
  branches; quantities and branch stock position are restricted.

## Verification

`tests/test_inventory_branch_scope.py` covers assigned versus unassigned
branch balances, explicit cross-branch lookup denial, and summary aggregation.
Sales and replenishment branch-scope integration coverage should be added before
this enforcement area is considered fully verified.
