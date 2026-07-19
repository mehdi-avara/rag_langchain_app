# Phase 1.2 Backend Closure

## Legacy header-only purchase orders

Historical purchase orders that contain no normalized lines are retained without
inventing commercial data or deleting approval history.

The compatibility policy is:

- They remain readable for audit and historical reporting.
- They cannot be submitted or reapproved while structurally incomplete.
- Draft or rejected records may be normalized by adding valid commercial lines
  and complete allocations.
- Approved records may be normalized only through the purchase-order amendment
  and reapproval workflow.
- They cannot receive goods without normalized allocations.
- No migration fabricates products, quantities, prices, currencies, or source
  references for these records.

All newly created purchase orders require at least one normalized line and an
automatic initial delivery phase.

## Operational-link rule

Goods-receipt lines are the only current operational records linked directly to
purchase-phase allocations. Receipt foreign keys use `ON DELETE RESTRICT`, and
delivery splitting blocks movement when unposted receipts exist and preserves
posted received quantities.

## Cross-module rule

Purchase code may call public services owned by material, RFQ, requisition,
supplier, currency, and goods-receipt modules. It must not import another
module's SQLAlchemy models, routes, or Pydantic schemas.

## Money rule

Transaction prices, base prices, and frozen exchange rates use the canonical
rounding functions in `shared.currency.services`.

## Error rule

Purchase service errors use shared catalogued error codes.

## RBAC rule

The corrective Phase 1.2 closure migration idempotently creates and assigns
`purchase_management:phases:split` to the built-in global admin role. Its
downgrade preserves runtime RBAC assignments.
