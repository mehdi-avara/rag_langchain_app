# Required PO Cost and Payment Changes

This focused change replaces the archived full financial-integration plan.

Frontend handoff:
`PHASE_1_3_PO_COST_PAYMENT_FRONTEND.md`

## 1. Ownership

```text
Purchase module:
  PurchaseOrder
  PurchaseOrderLine
  PurchaseOrderCost

Finance module:
  FinancialReceipt
  PurchaseCostPaymentAllocation
```

Finance creates receipts and payment allocations. Purchase must never create or
update Finance records.

## 2. PurchaseOrderCost Changes

Support these cost types:

```text
goods      کالا
freight    حمل و نقل
customs    گمرک
tax        مالیات
insurance  بیمه
other      سایر
```

Replace the single cost amount with two optional canonical money bundles:

```text
predicted_amount
predicted_currency_id
predicted_amount_base
predicted_exchange_rate_used

actual_amount
actual_currency_id
actual_amount_base
actual_exchange_rate_used
```

Also add:

```text
created_by_user_id
actual_confirmed_at
actual_confirmed_by_user_id
```

Rules:

- At least one of predicted or actual money is required.
- Each money bundle is all-or-nothing: amount, currency, base amount, and frozen
  exchange rate must either all be present or all be null.
- Predicted cost: predicted money exists and actual money is initially null.
- Unpredicted cost: predicted money is null and actual money is provided.
- The backend calculates base amounts.
- Existing cost amounts migrate to predicted amounts.
- Keep `amount` temporarily as a deprecated API alias.
- Deprecate the unused `allocation_method`.

Do not store paid amount, outstanding amount, variance, or payment status on the
cost. They are calculated.

## 3. Finance Allocation Model

Add under `financial_management`:

```text
PurchaseCostPaymentAllocation
  id
  company_id
  financial_receipt_id FK -> financial_receipts.id
  purchase_order_cost_id FK -> purchase_order_costs.id
  allocated_amount
  currency_id
  allocated_amount_base
  exchange_rate_used
  created_by_user_id
  created_at
```

Rules:

- One cost can have multiple receipts.
- One receipt can pay multiple costs.
- Only `output` receipts can pay purchase costs.
- Receipt and cost must belong to the same company.
- Allocations cannot exceed the receipt amount.
- Allocations cannot exceed the cost settlement amount.
- Allocated receipts and costs cannot be hard-deleted.
- Do not copy PO ID, PO description, supplier, or cost type into the allocation.

## 4. Calculations

```text
paid = SUM(Finance allocations)

settlement target =
  actual amount when confirmed
  otherwise predicted amount

outstanding = settlement target - paid
variance = actual amount - predicted amount
```

Calculated payment states:

```text
unpaid
advance_paid
partially_paid
paid
payment_review_required
```

## 5. Lifecycle

Allow a new predicted or actual cost to be added at any time after the PO
exists, regardless of PO status:

```text
draft
ordered
shipped
partially_received
received
closed
cancelled
```

Adding a cost does not reopen the PO and does not change its operational status,
approval status, delivery state, or warehouse history. A late freight, customs,
tax, insurance, cancellation, or other cost is an additional financial fact.

A posted goods receipt, PO closure, or PO cancellation must not block recording
that new fact. Cost operations need their own guard and must not use the
commercial PO amendment guard.

After payment exists, do not change cost type/currency, delete the cost, or
reduce its settlement amount below the amount paid.

## 6. Routes

Purchase-owned routes:

```text
GET    /purchase/orders/{po_id}/costs
POST   /purchase/orders/{po_id}/costs
GET    /purchase/orders/{po_id}/costs/{cost_id}
PATCH  /purchase/orders/{po_id}/costs/{cost_id}
POST   /purchase/orders/{po_id}/costs/{cost_id}/confirm-actual
DELETE /purchase/orders/{po_id}/costs/{cost_id}
GET    /purchase/orders/{po_id}/payment-summary
```

Finance-owned routes:

```text
POST   /financial_management/receipts
GET    /financial_management/receipts/{receipt_id}/purchase-cost-allocations
POST   /financial_management/receipts/{receipt_id}/purchase-cost-allocations
DELETE /financial_management/receipts/{receipt_id}/purchase-cost-allocations/{allocation_id}
```

Receipt creation may include allocations in the same Finance transaction, but
all connection and currency fields are optional:

```text
purchase_cost_allocations = null by default
currency_id = null by default
exchange_rate_used = null by default
```

Minimal request:

```json
{
  "description": "Freight payment",
  "amount": "7000000",
  "direction": "output",
  "credit_card_id": 5,
  "counterparty_name": "Transport Company",
  "receipt_date": "2026-07-26T10:00:00"
}
```

When `purchase_cost_allocations` is null or omitted, Finance creates a normal
receipt without a PO connection.

When `currency_id` is null or omitted, Finance uses the current user's
`Company.base_currency_id`. The configured currency must exist and be active.

When `exchange_rate_used` is null or omitted:

- use `1` when the receipt currency equals the company base currency;
- otherwise load the applicable database exchange rate from the receipt
  currency to the company base currency, effective on `receipt_date`;
- freeze the resolved rate and calculated base amount on the receipt;
- return a catalogued error if no applicable database rate exists.

The client may select a non-default currency, but the backend resolves its
exchange rate and calculates the base amount. Do not accept a client-calculated
base amount.

## 7. Service Connection

Finance validates costs through a Purchase read service:

```text
get_purchase_cost_reference_for_finance(cost_id)
```

Purchase gets paid totals through a Finance read service:

```text
get_purchase_cost_payment_summaries(cost_ids)
```

Do not import another module's models, routes, or schemas. Use a real FK in the
shared database. Commerce must not call a Finance HTTP route.

## 8. Summary and Optional Finance

The frontend summary has:

```text
Payment Prediction:
  predicted total and totals by cost type

Actual Financial Results:
  actual total, unpredicted total, paid, outstanding, and variance
```

`goods` must not be added on top of the PO-line product total.

Do not add `financial_status`, a financial reopen action, or a setting that
blocks PO closure based on payment settlement.

PO status and payment status are independent:

```text
PO status      = operational state
payment status = calculated financial information
```

Companies can use PO costs without Finance receipt tracking. In that case, the
UI displays payment tracking as `not_tracked`. Closing or cancelling a PO never
prevents a later cost from being recorded.

## 9. Migration and Compatibility

Create a new Alembic migration:

1. Add predicted/actual and audit fields to `PurchaseOrderCost`.
2. Backfill current cost amounts as predictions.
3. Normalize `FinancialReceipt` to canonical currency IDs and frozen rates.
4. Create the Finance-owned allocation table with real FKs and constraints.
5. Preserve old PO receipt links as `legacy_unallocated`; never guess their cost
   or allocation amount.
6. Deprecate `/purchase/orders/{po_id}/receipt-links`.
7. Register the new model in `Models/__init__.py`.

## 10. Permissions, Errors, and Tests

Add and seed permissions for:

```text
purchase_management:costs:read
purchase_management:costs:manage
purchase_management:costs:confirm_actual
purchase_management:payment_summary:read
financial_management:purchase_cost_allocations:read
financial_management:purchase_cost_allocations:create
financial_management:purchase_cost_allocations:delete
```

Add these catalogued errors:

```text
PURCHASE_ORDER_COST_TYPE_INVALID
PURCHASE_ORDER_COST_MONEY_INCOMPLETE
PURCHASE_ORDER_COST_NOT_FINANCIALLY_EDITABLE
PURCHASE_ORDER_COST_ACTUAL_BELOW_PAID
PURCHASE_ORDER_COST_HAS_PAYMENTS
FINANCIAL_RECEIPT_DIRECTION_INVALID_FOR_PURCHASE
FINANCIAL_RECEIPT_PURCHASE_COMPANY_MISMATCH
FINANCIAL_RECEIPT_ALLOCATION_EXCEEDS_RECEIPT
PURCHASE_ORDER_COST_ALLOCATION_EXCEEDS_COST
FINANCIAL_RECEIPT_HAS_ALLOCATIONS
FINANCIAL_RECEIPT_BASE_CURRENCY_NOT_CONFIGURED
FINANCIAL_RECEIPT_EXCHANGE_RATE_NOT_FOUND
```

Test:

- predicted and unpredicted costs;
- all six cost types;
- actual confirmation and variance;
- adding costs in every PO status, including closed and cancelled;
- adding costs after a posted GRN;
- partial/full and many-to-many payments;
- allocation validation and rollback;
- no `goods` double-counting;
- optional Finance usage without changing PO status;
- migration of existing costs and legacy receipt links;
- permissions, error codes, module boundaries, and `alembic check`.

## 11. Critical Implementation Decisions

### Initial Goods Prediction

When a PO is approved, automatically create one `goods` prediction from the
derived PO-line total.

If an approved amendment changes PO-line quantity or price:

- update the goods prediction only when it has no confirmed actual amount and no
  payment allocation;
- otherwise preserve it and return `payment_review_required`;
- never silently rewrite a prediction that Finance has already used.

The goods prediction is a payment forecast. It does not replace PO-line prices
and must not be added again to the commercial product total.

### Actual Cost Confirmation

The actual cost is confirmed explicitly through the Purchase
`confirm-actual` route. It is not copied from a Financial Receipt.

```text
actual cost = final charge
receipt amount = money paid
```

A receipt can be allocated before actual confirmation as an advance payment.
Until actual confirmation, outstanding is provisional against the prediction.

### Receipt Cardinality

One receipt may pay multiple costs and multiple POs only when all referenced
costs:

- belong to the same company;
- belong to the same supplier;
- use a compatible receipt currency and frozen conversion context.

Supplier and PO information are derived through the Purchase service and are not
copied into the allocation table.

### Overpayment

Block overpayment in the first implementation. The total allocated to a cost
cannot exceed its actual amount, or its predicted amount when actual is not yet
confirmed. Do not add an override until a separate approval workflow exists.

### Corrections and Audit History

Never hard-delete a cost or receipt that has allocations.

To correct a mistake:

1. A Finance user with allocation-delete permission removes or reverses the
   incorrect allocation.
2. The action is audit-logged with user, timestamp, reason, old amount, and new
   amount.
3. Purchase may then correct the cost if no remaining allocation blocks it.
4. If the original financial transaction must remain posted, create a separate
   corrective cost/payment record instead of rewriting history.
