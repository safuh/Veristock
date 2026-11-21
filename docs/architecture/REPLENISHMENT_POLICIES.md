# Replenishment planning policies

## Purpose

Veristock supports durable, tenant-owned planning assumptions at the
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

## Forecast integration

Branch-scoped demand forecasts apply saved branch/item policies by default.
Explicit `lead_time_days` or `safety_stock_days` query parameters override
the corresponding saved value, and every forecast item reports whether its
planning values came from a saved policy, a request override or the default.

All-branches forecasts deliberately do not combine branch-specific policies.
They use shared request overrides when supplied and otherwise use zero-day
defaults. The client reporting screen supports branch selection and inline
policy editing/saving. Forecasts remain advisory and never create purchase
orders or mutate stock.

## Scope and next work

Policies are unique by organization, branch and item. They intentionally do
not infer supplier relationships or imply purchase commitments. Supplier
master data, minimum order quantities, order multiples and service-level
configuration remain future planning capabilities.
