# PO Cost and Payment — Frontend Description

Backend contract:
`PHASE_1_3_PO_COST_PAYMENT_EDIT.md`

## 1. PO Detail Screen

Add a `Costs and Payments` tab to the PO detail screen. It is available for
every PO status, including closed and cancelled.

Show two summary cards:

```text
Payment Prediction
  predicted total
  predicted total by cost type
  predictions without confirmed actual cost

Actual Financial Results
  confirmed actual total
  unpredicted actual total
  paid total
  outstanding total
  prediction variance
```

Do not show or use a separate `financial_status`.

## 2. Cost Table

Display:

```text
cost type
description
predicted amount
actual amount
variance
paid amount
outstanding amount
payment state
receipt count
created date
```

Persian cost labels:

```text
goods      کالا
freight    حمل و نقل
customs    گمرک
tax        مالیات
insurance  بیمه
other      سایر
```

Payment badges:

```text
unpaid                  پرداخت نشده
advance_paid            پیش‌پرداخت
partially_paid          پرداخت جزئی
paid                    پرداخت شده
payment_review_required نیازمند بررسی
not_tracked             پیگیری مالی غیرفعال
```

## 3. Cost Actions

### Add Predicted Cost

Fields:

```text
cost type
description
predicted amount
currency, optional
```

Do not ask for base amount or exchange rate. The backend resolves them.

### Add Unexpected Actual Cost

Fields:

```text
cost type
description
actual amount
currency, optional
```

Send no predicted amount.

### Confirm Actual Cost

Available on a predicted cost without a confirmed actual amount.

Show:

```text
predicted amount
actual amount input
calculated variance preview
```

### Record Payment

Open the Finance receipt form with the PO cost preselected. This is only a
navigation action; Finance creates the receipt and allocation.

After success, refresh the cost list and payment summary.

## 4. Finance Receipt Form

Fields:

```text
description
amount
direction
card/account
counterparty
receipt date
tracking number, optional
receipt file, optional
currency, optional
PO cost allocations, optional
```

Defaults:

- `direction` defaults to `output` when opened from a PO cost.
- Currency displays the company default but may be omitted from the request.
- Exchange rate is not a normal user input.
- Base amount is read-only and calculated by the backend.
- `purchase_cost_allocations` defaults to null.

If the form is opened from a PO cost:

- preselect that cost;
- suggest its outstanding amount;
- allow the user to change the allocated amount;
- allow removing the allocation and saving a normal unallocated receipt.

For multiple allocations, show:

```text
PO reference
supplier
cost type
settlement amount
already paid
outstanding
amount allocated by this receipt
```

The sum allocated cannot exceed the receipt amount.

## 5. API Calls

PO screen:

```text
GET  /purchase/orders/{po_id}/payment-summary
GET  /purchase/orders/{po_id}/costs
POST /purchase/orders/{po_id}/costs
POST /purchase/orders/{po_id}/costs/{cost_id}/confirm-actual
```

Finance screen:

```text
POST /financial_management/receipts
GET  /financial_management/receipts/{receipt_id}/purchase-cost-allocations
POST /financial_management/receipts/{receipt_id}/purchase-cost-allocations
```

Receipt creation may contain:

```json
{
  "purchase_cost_allocations": [
    {
      "purchase_order_cost_id": 123,
      "allocated_amount": "5000000"
    }
  ]
}
```

Omit `purchase_cost_allocations`, `currency_id`, and `exchange_rate_used` when
the user accepts their defaults.

## 6. Permissions

Hide or disable actions based on:

```text
purchase_management:costs:read
purchase_management:costs:manage
purchase_management:costs:confirm_actual
purchase_management:payment_summary:read
financial_management:receipts:create
financial_management:purchase_cost_allocations:read
financial_management:purchase_cost_allocations:create
financial_management:purchase_cost_allocations:delete
```

A user who can view PO costs but cannot create Finance receipts can see payment
information but cannot use `Record Payment`.

## 7. Important UI Rules

- Costs can be added for any PO status.
- Adding a cost never reopens or changes the PO.
- Do not add `goods` again to the PO product total.
- Do not let users edit calculated paid, outstanding, variance, or status.
- Do not copy PO or supplier data into receipt form state as authoritative data;
  display the values returned by the backend.
- Do not assume receipt creation succeeded until the complete receipt and
  allocation request succeeds.
- Show backend catalogued error messages next to the affected cost or allocation.
- Require a correction reason when removing an existing allocation.

