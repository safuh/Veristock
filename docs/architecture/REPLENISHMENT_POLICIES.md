# Replenishment planning policies

## Purpose

Veristock now supports durable, tenant-owned planning assumptions at the
branch/item level. A policy stores supplier lead time and safety-stock days
without introducing a supplier or purchase-order domain before those workflows
are part of the product scope.

## API

- `GET /api/inventory/replenishment-policies` lists the active organization's
  policies. Optional `branch_id`, `limit` and `offset` filters are supported.
  Requires `inventory.read`.
- `PUT /api/inventory/replenishment-policies/{branch_id}/{item_id}` creates
  or replaces a policy. Requires `inventory.manage`.

Both inputs are bounded to 0–180 days. The write route verifies that the
branch and item are active and belong to the caller's selected organization.
Each write records the user who last changed the policy. Policies do not
change stock, create orders or contact suppliers.

## Scope and next integration

Policies are unique by organization, branch and item. They intentionally do
not infer a supplier relationship or imply a purchase commitment. The current
forecast endpoint still accepts explicit lead-time and safety-stock assumptions;
the next integration step is to make a branch-scoped forecast resolve saved
policies by default while allowing clearly marked, request-level overrides.
An all-branches forecast must not silently combine different branch policies.
