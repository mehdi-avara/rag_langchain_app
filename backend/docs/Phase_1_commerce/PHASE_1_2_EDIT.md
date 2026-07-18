# Phase 1.2 Edit - PO Lines and Flexible Delivery Phases

Phase 1 is already finished. This file defines the Phase 1.2 changes that must
be implemented on top of the existing commerce flow.

## 1. Required Business Behavior

A purchase order must contain at least one product. A PO header without a
product is not a valid purchase order.

Every PO starts with at least one delivery phase. At creation time, all ordered
quantities can be assigned to the first phase. Users must be able to add another
phase later and move all or part of an unreceived quantity to that phase.

Example:

```text
PO line: Pump, ordered quantity 10

At creation:
  Phase 1 -> Pump: 10

Supplier later confirms split delivery:
  Phase 1 -> Pump: 4, expected sooner
  Phase 2 -> Pump: 6, expected later

PO total remains Pump: 10
```

A phase is a delivery schedule. It must not become the only record of what was
commercially ordered.

## 2. Target Data Model

The current implementation stores products only as `PurchasePhaseItem` rows:

```text
PurchaseOrder
  -> PurchasePhase
      -> PurchasePhaseItem
```

That is sufficient for a fixed delivery schedule, but it mixes the commercial
PO line with its phase allocation. Phase 1.2 should introduce a stable PO line:

```text
PurchaseOrder
  -> PurchaseOrderLine                 commercial commitment
  -> PurchasePhase                     delivery group
      -> PurchasePhaseItem             quantity allocated to a phase
          -> PurchaseOrderLine
```

Minimum `PurchaseOrderLine` fields:

```text
id
purchase_order_id
item_id
item_code
item_name
item_description nullable
ordered_quantity
unit
unit_price
currency_id
unit_price_base
base_currency_id
exchange_rate_used
line_total
line_total_base
source_type                       manual | mr | rfq
material_requisition_item_id      nullable FK
rfq_item_id                       nullable FK
quotation_response_item_id        nullable FK
notes nullable
created_at
updated_at
```

Add `purchase_order_line_id` as a required FK on `PurchasePhaseItem` after
migrating existing data. `PurchasePhaseItem.quantity` becomes the quantity of
that PO line assigned to that phase. Existing item and price snapshot fields may
remain temporarily for backward-compatible reads, but the PO line is the source
of the commercial quantity and price.

Use database foreign keys for source rows in the shared database. Purchase code
must resolve source details through the owning module's service/interface and
must not import another module's SQLAlchemy models.

## 3. PO Creation Rules

### 3.1 PO Created From RFQ

Keep:

```text
POST /purchase/orders/from-rfq/{rfq_id}
```

The backend must create everything in one database transaction:

```text
winning quotation response
  -> PurchaseOrder
  -> one PurchaseOrderLine per winning quotation item
  -> Phase 1
  -> one Phase 1 allocation per PO line
```

The products, quantities, units, prices, currencies, supplier, and source links
come from the winning quotation response. The frontend must not enter unrelated
products for this creation path.

### 3.2 Manual PO Without RFQ

The manual creation request must include at least one line selected from the
shared Item catalog:

```text
POST /purchase/orders
```

Example request:

```json
{
  "title": "Manual pump purchase",
  "supplier_id": 55,
  "currency_id": 1,
  "base_currency_id": 1,
  "exchange_rate_used": 1,
  "lines": [
    {
      "item_id": 99,
      "ordered_quantity": 10,
      "unit_price": 1200,
      "currency_id": 1,
      "unit_price_base": 1200,
      "base_currency_id": 1,
      "exchange_rate_used": 1
    }
  ],
  "initial_phase": {
    "title": "Initial delivery",
    "expected_delivery_date": null
  }
}
```

The backend creates the PO, its lines, Phase 1, and Phase 1 allocations in one
transaction. `lines` must have at least one entry and each ordered quantity must
be greater than zero.

### 3.3 Direct Purchase From MR

If an approved MR goes to direct purchase without an RFQ, the PO lines must be
created from the approved MR lines. Users may select which approved MR lines are
included, but they must not add unrelated catalog items through this path.

Recommended endpoint:

```text
POST /purchase/orders/from-mr/{mr_id}
```

It follows the same transaction rule: create the PO, at least one PO line, the
initial phase, and phase allocations together.

### 3.4 Breaking-Change Notice

The current `POST /purchase/orders` accepts a header without products. Requiring
`lines` changes that request contract and is a breaking API change. Backend and
frontend deployment must be coordinated. If a staged rollout is required, add a
new atomic creation endpoint first, migrate the frontend, and then deprecate the
header-only behavior. The final Phase 1.2 behavior must not leave a valid PO with
zero products.

## 4. Submission Validation

Creation validation is mandatory, but submission must also defend against old,
migrated, or partially edited data.

Before a PO can be submitted for approval, the backend must verify:

```text
PO has at least one PurchaseOrderLine
PO has at least one PurchasePhase
every PO line has ordered_quantity > 0
every phase allocation has quantity > 0
sum(phase allocations for each PO line) == PO line ordered_quantity
```

If any rule fails, submission returns a catalogued validation error and leaves
the PO in draft status.

## 5. Flexible Phase Management

Users can initially keep all products in one phase. Later they can split that
delivery into a new phase because products will arrive on different dates or in
partial deliveries.

### 5.1 Automatic Initial Phase

Every PO creation path automatically creates the initial phase. The frontend
does not need a second request to create Phase 1.

Backend defaults:

```text
phase_number = 1
title = "Initial delivery" unless supplied
status = draft
currency/exchange rate = inherited from the PO
allocations = full ordered quantity of every PO line
```

This applies to manual, RFQ-based, and direct-MR purchase orders.

### 5.2 One-Step Split Into a New Phase

The normal user action is **Split delivery**. It creates the next phase and
moves selected unreceived quantities in one backend transaction:

```text
POST /purchase/orders/{po_id}/phases/split
```

Example request:

```json
{
  "title": "Later delivery",
  "expected_delivery_date": "2026-08-15T00:00:00",
  "reason": "Supplier confirmed a split delivery",
  "moves": [
    {
      "from_phase_item_id": 501,
      "quantity": 6
    },
    {
      "from_phase_item_id": 502,
      "quantity": 2
    }
  ]
}
```

`moves` must contain at least one row. The backend automatically assigns the
next phase number and uses a generated title such as `Phase 2` when no title is
provided.

The operation must:

1. Validate every move before writing anything.
2. Create the new phase.
3. Reduce each source allocation by the requested movable quantity.
4. Create the matching allocation in the new phase.
5. Keep every PO line's total allocated quantity unchanged.
6. Recalculate phase and PO delivery statuses where required.
7. Write one audit event for the split and its individual quantity moves.
8. Return the new phase and updated source phases.

If any item cannot be moved, the entire request rolls back, including creation
of the new phase. The route should support an idempotency key so a retry or
double click cannot create duplicate phases.

The user enters only the quantity to move. The frontend must not ask the user to
manually calculate and save both the old and new quantities.

Example:

```text
Before: Phase 1 -> Pump = 10
User enters: move 6
After:  Phase 1 -> Pump = 4
        Phase 2 -> Pump = 6
```

### 5.3 Split and History Rules

The maximum transferable quantity is:

```text
source allocation quantity - source received quantity
```

An allocation linked to a posted receipt or a shipment that can no longer be
rescheduled must not be moved. A received quantity is historical fact and must
never be moved to another phase.

If the full unreceived quantity is moved, the source allocation may be removed
only when its `received_quantity` is zero and it has no receipt or shipment
links. Otherwise, retain the source allocation for history.

Closed and cancelled POs cannot be split or rescheduled.

Changing only the expected delivery date or reallocating an unchanged ordered
quantity does not change the commercial PO total. Adding a new PO line,
increasing quantity, changing price, changing currency, or changing supplier
after approval is a PO amendment and must trigger the configured reapproval
workflow.

## 6. PO-Scoped Split Candidates

The global material endpoint:

```text
POST /materials/search
```

is appropriate while creating a manual PO. It must not be used for splitting an
existing PO because a split can only move products already allocated to that
PO.

Add:

```text
GET /purchase/orders/{po_id}/split-candidates
```

Optional query parameters:

```text
source_phase_id
q
```

The candidates are movable allocations from the PO's existing phases,
regardless of whether their PO lines came from an MR, RFQ, or manual purchase.

Example response:

```json
[
  {
    "from_phase_item_id": 501,
    "source_phase_id": 10,
    "source_phase_number": 1,
    "purchase_order_line_id": 77,
    "source_type": "rfq",
    "material_requisition_item_id": 10,
    "rfq_item_id": 20,
    "quotation_response_item_id": 30,
    "item_id": 99,
    "item_code": "PUMP-001",
    "item_name": "Centrifugal Pump",
    "item_description": "Pump description from material catalog",
    "unit_code": "pcs",
    "ordered_quantity": 10,
    "source_allocated_quantity": 10,
    "source_received_quantity": 0,
    "movable_quantity": 10,
    "unit_price": 1200,
    "currency_id": 1,
    "supplier_id": 55,
    "supplier_name": "Supplier A"
  }
]
```

Rules:

- `movable_quantity = source_allocated_quantity - source_received_quantity`.
- The split request identifies each source using `from_phase_item_id`.
- A split can move no more than `movable_quantity` into the new phase.
- The frontend must display ordered, source-allocated, source-received, and
  movable quantities separately.
- Item display fields are resolved through the `material_management` service or
  interface.

## 7. Recipe / Template Support

A recipe is not currently implemented. If customers need repeated delivery
structures, it can be added as an optional Phase 1.2 feature.

Applying a recipe expands into phase allocations only after validating every
entry against the PO's own lines returned by:

```text
GET /purchase/orders/{po_id}/split-candidates
```

A recipe must use the same split service and must not create a new PO product or
bypass MR/RFQ source restrictions.

## 8. Frontend Behavior

### 8.1 Create PO

The manual PO form contains a required product-line table. The Create PO button
is disabled until at least one valid product with quantity greater than zero is
present.

For RFQ-created POs, show the winning quotation lines as read-only creation
inputs. For direct-MR POs, show only selected approved MR lines. In both cases,
the backend remains the authority and copies the source data.

### 8.2 Manage Phases

After creation, show:

```text
PO product totals
Phase 1 allocations and expected date
Phase 2 allocations and expected date
received and movable quantities
```

Provide these actions according to status and permission:

```text
Split delivery
Edit phase delivery date/title
```

The primary Split delivery dialog asks for the new delivery date, optional
title, reason, and quantity to move for each selected product. It calls the
one-step split endpoint, so the user never needs to create a phase first or edit
two item counts.

The dialog must show the maximum movable quantity and must not offer received
quantity.

## 9. Migration and Compatibility

Migration must create one `PurchaseOrderLine` for each logical existing PO
product and link existing `PurchasePhaseItem` rows to it. If the same product
appears in multiple phases with the same commercial terms, migration may group
those phase items into one PO line and set ordered quantity to their quantity
sum. Rows with different prices, currencies, units, or source references remain
separate PO lines.

Make `purchase_order_line_id` nullable only during migration. Backfill and
verify all rows before changing it to non-null. Keep existing response fields
during a deprecation period so current frontend reads do not fail.

## 10. Acceptance Criteria

Phase 1.2 is complete when:

- Manual PO creation rejects an empty `lines` list.
- RFQ creation automatically creates PO lines and initial phase allocations.
- Direct-MR creation uses approved MR lines and cannot add unrelated products.
- PO creation is atomic and never leaves a header-only PO after failure.
- Submission rejects a PO with no products, no phase, or allocation mismatch.
- Every PO creation path automatically creates Phase 1 and its allocations.
- One Split delivery action atomically creates a new phase and moves one or more
  selected quantities.
- A failed split does not leave an empty phase or partially moved quantities.
- Retrying the same split request cannot create a duplicate phase.
- A user can split an unreceived quantity between two or more phases.
- Adding or moving a phase allocation never changes the PO ordered total.
- Received quantities and posted receipt history cannot be moved or deleted.
- Phase changes are permission-protected and audited.
- PO-scoped candidates expose ordered, allocated, received, unassigned, and
  movable quantities.
- Approved commercial changes trigger the configured amendment/reapproval flow.
- Migration preserves existing PO, phase, item, source, and receipt history.
- Tests cover empty creation, RFQ creation, manual creation, direct-MR creation,
  automatic Phase 1, one-step split creation, split rollback and idempotency,
  full and partial splits, over-split rejection, received-line protection,
  concurrent split protection, submission validation, and migration results.

