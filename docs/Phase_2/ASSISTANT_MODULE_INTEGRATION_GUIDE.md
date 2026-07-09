# Assistant Module Integration Guide

This guide documents the conventions for adding new backend modules to the existing
assistant without redesigning the assistant core.

The assistant core must stay generic and reusable:

- `backend/assistant/registry.py`
- `backend/assistant/router.py`
- `backend/assistant/graph.py`
- `backend/assistant/runner.py`
- `backend/assistant/service.py`
- `backend/assistant/models.py`
- `backend/assistant/routes.py`

Module-specific behavior belongs in the owning module's `assistant_tools.py`.

## Core Rule

The assistant never commits domain writes.

For write requests, the assistant only creates a draft. The frontend commits by
calling:

```text
draft.commit_target.method + draft.commit_target.endpoint
```

with:

```text
draft.payload
```

This is true even if the user says "confirm", "do it", or asks in Persian. Chat
text alone must never commit writes.

## Frontend Contract

Draft payload fields stay in English and match backend API schemas.

Persian is supported for user input and assistant answers, but payload keys must
not be localized. Examples:

```json
{
  "needed_by_date": "2026-08-01",
  "reason": "pump repair",
  "items": [
    {
      "item_id": 99,
      "quantity": "2"
    }
  ]
}
```

Use backend field names such as:

- `item_id`
- `supplier_id`
- `supplier_ids`
- `mr_id`
- `rfq_id`
- `purchase_phase_id`
- `purchase_phase_item_id`
- `warehouse_id`
- `storage_location_id`
- `currency_id`
- `base_currency_id`
- `exchange_rate_used`

## Module Adapter Convention

Each assistant-enabled module should add:

```text
backend/<module>/assistant_tools.py
```

Each adapter should define:

- `MODULE`: exact backend package name, such as `requisition_management`
- `API_PREFIX`: endpoint prefix used by the module routes
- permission constants matching real RBAC strings
- read/search intents
- write/draft intents
- resource registrations for FK-like references owned by that module
- `register()` that calls `register_toolset(...)`

The adapter must be imported at startup, currently through `backend/assistant/routes.py`
or an assistant toolset loader.

## Intent Convention

Read/search intents should use names like:

- `search_suppliers`
- `ask_suppliers`
- `search_items`
- `ask_items`
- `search_stock`
- `ask_warehouse_stock`
- `search_requisitions`
- `ask_requisitions`
- `search_rfqs`
- `ask_rfqs`
- `search_purchase_orders`
- `search_goods_receipts`
- `ask_goods_receipts`

Write intents should use names like:

- `add_supplier`
- `update_supplier`
- `add_item`
- `update_item`
- `add_material_requisition`
- `update_material_requisition`
- `add_rfq`
- `update_rfq`
- `add_purchase_order`
- `update_purchase_order`
- `add_goods_receipt`
- `update_goods_receipt`
- `add_stock_adjustment`

Draft `target_action` should use verb-object naming:

- `create_supplier`
- `update_supplier`
- `create_item`
- `update_item`
- `create_material_requisition`
- `update_material_requisition`
- `create_rfq`
- `update_rfq`
- `create_purchase_order`
- `update_purchase_order`
- `create_goods_receipt`
- `update_goods_receipt`
- `create_stock_adjustment`

## Read/Search Convention

Read handlers must call existing module service/search functions. Do not call
route functions and do not duplicate business logic.

Read outputs should return:

```python
{
    "retrieved_items": [...],
    "citations": [...],
    "answer": "",
    "summary": None,
}
```

For `ask_*` intents, use the module's existing grounded search/ask behavior or
the shared Phase 1 ask helper. Persian questions should be answered in Persian
when practical.

## Write/Draft Convention

Write handlers return `DraftData`.

Incomplete writes return:

```python
DraftData(
    target_module="<module>",
    target_action="<action>",
    payload=<partial_payload>,
    commit_target={},
    validation={
        "valid": False,
        "missing": [...],
        "errors": {},
    },
    valid=False,
    clarify_question="...",
)
```

Complete writes return:

```python
DraftData(
    target_module="<module>",
    target_action="<action>",
    payload=<complete_payload>,
    commit_target={
        "method": "POST",
        "endpoint": "/module/endpoint",
        "permission": "module:create",
    },
    validation={"valid": True},
    valid=True,
)
```

For updates, `commit_target` must include `entity_id`:

```json
{
  "method": "PATCH",
  "endpoint": "/suppliers/42",
  "permission": "supplier_management:update",
  "entity_id": 42
}
```

## Foreign Key / Reference Convention

Use the shared reference-resolution pattern for FK-like fields.

The owning module registers a resource with `ResourceSpec`. A draft builder then
declares FK-like fields with `ReferenceFieldSpec`.

Example resource keys:

- `material_item`
- `supplier`
- `material_requisition`
- `rfq`
- `warehouse`
- `storage_location`
- `purchase_phase`
- `purchase_phase_item`
- `currency`
- `item_category`
- `material_unit`
- `managed_model`

Reference behavior:

1. If the user gives a numeric id, use it.
2. If the user gives a name/code/text, search the registered resource.
3. If one clear match exists, write the English id field into the payload.
4. If multiple matches exist, return `partial_draft` with alternatives.
5. If no match exists and the resource is creatable, return `partial_draft` with
   a `create_suggestion`.
6. Never invent ids.
7. Never commit writes.

Example `ReferenceFieldSpec` for a nested item list:

```python
ReferenceFieldSpec(
    field="item_id",
    resource_key="material_item",
    raw_aliases=("item_query", "item_name", "item", "material_item", "part", "part_name"),
    explicit_aliases=("item_id", "material_item_id"),
    missing_label="item",
    collection="items",
)
```

Example list-valued reference:

```python
ReferenceFieldSpec(
    field="supplier_ids",
    resource_key="supplier",
    raw_aliases=("supplier_query", "supplier_name", "supplier"),
    explicit_aliases=("supplier_id",),
    missing_label="supplier",
    as_list=True,
)
```

Lookup tables and enum-like master data follow the same rule. The user should
not need to know backend ids for values such as `category_id`, `unit_id`,
`currency_id`, `base_currency_id`, `warehouse_id`, `storage_location_id`, or
future similar fields. Accept names, codes, labels, Persian text, or synonyms
into raw aliases such as `category`, `category_name`, `unit`, `unit_code`,
`currency`, `base_currency`, `warehouse`, or `location`; resolve them through
the owning module's service/search seam; then write only the English backend id
field into the draft payload. If the value is missing, ambiguous, or not found,
return `partial_draft` with references/choices or a clarification asking for
that exact lookup value.

Current exception: `department_id` on material requisitions remains numeric-only
because this codebase currently has no department module/resource/service seam
to resolve a department name safely. Do not invent department ids; leave it
missing or require an explicit numeric id until a real department resource
exists.

## Current Commerce Reference Behavior

The commerce assistant supports these reference flows:

- Material item:
  - category name/code/text -> `category_id`
  - unit name/code/text -> `unit_id`
  - managed model/manufacturer/model text -> `model_id`
- Material requisition:
  - item name/code -> `items[].item_id`
  - item currency/base-currency code/name -> `items[].currency_id` and `items[].base_currency_id`
- RFQ:
  - MR number/text -> `mr_id`
  - supplier name/code -> `supplier_ids`
  - item name/code -> `items[].item_id`
- Purchase order:
  - supplier name/code -> `supplier_id` for direct PO create
  - currency/base-currency code/name -> `currency_id` and `base_currency_id`
  - RFQ number/text -> `POST /purchase/orders/from-rfq/{rfq_id}`
- Goods receipt:
  - purchase phase text -> `purchase_phase_id`
  - purchase phase item text -> `items[].purchase_phase_item_id`
  - item name/code -> `items[].item_id`
  - warehouse name/code -> `warehouse_id` for create/update
  - storage location name/code -> `items[].storage_location_id`
- Stock adjustment:
  - item name/code -> `item_id`
  - source storage location name/code -> `from_location_id`
  - target storage location name/code -> `to_location_id`
  - currency/base-currency code/name -> `currency_id` and `base_currency_id`

## PO From RFQ Convention

PO from RFQ is not the same as direct PO create.

Direct PO create uses:

```json
{
  "method": "POST",
  "endpoint": "/purchase/orders",
  "permission": "purchase_management:orders:create"
}
```

PO from RFQ uses:

```json
{
  "method": "POST",
  "endpoint": "/purchase/orders/from-rfq/17",
  "permission": "purchase_management:orders:create",
  "additional_permissions": ["rfq_management:read"],
  "entity_id": 17
}
```

The payload is `{}` because the endpoint derives supplier, currency, phase, and
items from the selected RFQ/winning quotation.

## Persian Support

Persian and English user messages are supported through the router and module
draft builders.

The router is instructed to map Persian commerce terms to the correct intent,
for example:

- `تامین‌کننده` -> suppliers
- `کالا` / `قطعه` -> material items
- `موجودی` -> stock
- `درخواست کالا` -> material requisition
- `استعلام قیمت` -> RFQ
- `سفارش خرید` -> purchase order
- `رسید کالا` -> goods receipt

Persian text may be routed into English slot names such as:

- `item_query`
- `item_name`
- `supplier_query`
- `supplier_name`
- `rfq_query`
- `mr_query`

The assistant should answer Persian `ask_*` questions in Persian when practical,
but frontend draft keys must remain English.

## Adding A New Assistant Part

Use this checklist:

1. Inspect existing routes, schemas, permissions, services, and search services.
2. Add or update `backend/<module>/assistant_tools.py`.
3. Define `MODULE`, `API_PREFIX`, and permission constants.
4. Add `SearchSpec` for read/search intents.
5. Add `WriteSpec` for create/update draft intents.
6. Register owned FK-like resources with `ResourceSpec`.
7. Add `ReferenceFieldSpec` for FK-like fields in write specs.
8. Ensure `commit_target` points to an existing module endpoint.
9. Keep draft payload keys in English and schema-compatible.
10. Return partial drafts for missing fields or unresolved references.
11. Import the adapter at startup.
12. Add focused assistant tests.

## Tests To Add

For each new module integration, add tests for:

- registry/RBAC filtering
- read handler returns `retrieved_items`
- ask handler returns `answer` and references where supported
- incomplete write returns `partial_draft`
- complete write returns a valid draft and `commit_target`
- FK/reference text resolves to id
- unresolved FK/reference returns alternatives or create suggestion
- graph write path creates a draft and never commits
- follow-up turn merges previous partial draft

Run:

```bash
pytest backend/assistant/tests -q
```

Also run the module's own tests when touched.

## Things Not To Do

- Do not modify the assistant core for module-specific business logic.
- Do not call FastAPI route functions from assistant adapters.
- Do not duplicate service logic in assistant adapters.
- Do not import another module's SQLAlchemy models into generic assistant core.
- Do not invent ids from user text.
- Do not localize draft payload keys.
- Do not commit writes from chat.
- Do not create schema changes unless the module endpoint truly requires them.
