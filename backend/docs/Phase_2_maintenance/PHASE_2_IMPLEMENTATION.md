# PHASE 2 - Maintenance Management Implementation

This document is the implementation contract for the maintenance part of the CMMS.
It replaces the older Phase 2 maintenance explanation where work orders were mainly
attached to assets only.

The maintenance design must preserve two histories at the same time:

- history of the plant position: all work that happened at a tag or functional location
- history of the physical unit: all work that happened to a specific pump, motor, valve, etc.

That is why Phase 2 must model `tag`, `asset`, `item`, and `asset_installation` separately.

## 1. Core Meanings

| Term | Meaning | Owner |
|---|---|---|
| `Item` | Purchasable and stockable catalog thing: spare part, material, consumable, complete equipment. | `material_management` |
| `Tag` | Permanent functional position in the plant or P&ID, such as `P-1001A`. | `tag_management` |
| `Asset` | Physical lifecycle-tracked unit, usually serialized, such as pump serial `SN-88921`. | `asset_management` |
| `AssetInstallation` | Historical relationship showing which asset was installed at which tag and when. | `asset_management` |
| `StockSerial` | Serialized warehouse inventory unit before it becomes, or without becoming, an asset. | `warehouse_management` |
| `WorkOrder` | Work requested, planned, executed, completed, and closed at a tag and/or on an asset. | `work_order_management` |

Important distinction:

```text
Item = what can be bought and stored
Asset = physical unit selected for lifecycle/maintenance tracking
Tag = where in the plant/system the asset is installed
```

Example:

```text
Item:  Centrifugal Pump ABC-200
Tag:   P-1001A pump position
Asset: Pump serial SN-88921

AssetInstallation:
  Pump SN-88921 installed at tag P-1001A from 2026-01-10 to 2028-04-02
```

When the pump is replaced, the tag remains the same and a new installation row is
created. Old work orders must not be rewritten.

## 2. Shared Rules For Phase 2

Follow the repository rules in `AGENTS.md`:

- Alembic owns schema changes.
- Register every model in `backend/Models/__init__.py`.
- Every route must be RBAC-protected and permissions must be seeded.
- Cross-module reads go through service functions.
- Cross-module writes go through Celery events.
- Cross-module foreign keys are allowed and preferred in the shared database.
- Do not import another module's SQLAlchemy models, route functions, or Pydantic schemas.
- Heavy work returns `202 + task_id`.
- Raise only catalogued errors.
- Tests are required.

## 3. Target Build Order

Build Phase 2 in this order:

```text
1. asset_management
2. asset/tag installation support
3. work_order_management
4. defect_management
5. pm_management
6. inspection_management
7. maintenance and warehouse material integration
8. notification engine
9. maintenance KPI/reporting dashboard
10. assistant tools for Phase 2 modules
```

Asset foundation must come before work orders. Work orders need a reliable way to
identify both the plant position and the physical equipment.

## 4. Asset Management

### 4.1 Purpose

Asset management owns physical equipment and its lifecycle.

It does not replace `tag_management`. Tags are existing functional positions.
Asset management links physical units to those positions through installation
history.

### 4.2 Asset Hierarchy

Use this hierarchy for equipment organization:

```text
Plant
  -> AssetSystem / Unit
      -> Asset / Equipment
          -> Component / Sub-component
```

The tag hierarchy remains separate and should continue to represent functional
positions.

### 4.3 Models

#### Plant

```text
Plant
  id
  company_id
  code
  name
  plant_type: refinery / platform / pipeline / terminal / other
  location
  description
  is_active
  created_at
  updated_at
```

#### AssetSystem

```text
AssetSystem
  id
  company_id
  plant_id FK -> plants.id
  parent_system_id FK -> asset_systems.id nullable
  code
  name
  system_type: process / utility / fire_gas / instrument / electrical / other
  description
  is_active
  created_at
  updated_at
```

#### Asset

`Asset` is the physical lifecycle-tracked unit.

```text
Asset
  id
  company_id
  asset_number auto, e.g. AST-2026-0001
  item_id FK -> material_management.items.id nullable
  model_id FK -> model_management.managed_models.id nullable
  source_stock_serial_id nullable, FK to future warehouse serial row if implemented
  serial_number nullable but strongly recommended for serialized equipment
  name
  description
  asset_type: rotating / static / electrical / instrument / civil / piping / tool / other
  criticality: A / B / C
  lifecycle_status: in_stock / installed / standby / under_maintenance / removed / overhauled / decommissioned / scrapped
  asset_system_id FK -> asset_systems.id nullable
  parent_asset_id FK -> assets.id nullable
  installation_date nullable
  warranty_expiry nullable
  description_embedding Vector(1024) nullable
  created_at
  updated_at
```

Notes:

- `item_id` connects the asset back to the material catalog and procurement/warehouse flow.
- `model_id` connects the asset to the equipment model type.
- `source_stock_serial_id` connects the asset to the serialized stock unit it came from.
- Do not store `tag_id` as the only source of installation truth on `Asset`.
  Use `AssetInstallation`.

#### AssetInstallation

This is required. It is the missing piece in the older Phase 2 plan.

```text
AssetInstallation
  id
  company_id
  tag_id FK -> tag_management.system_tags.id
  asset_id FK -> assets.id
  installed_at
  removed_at nullable
  is_current boolean
  installed_by_user_id FK -> users.id nullable
  removed_by_user_id FK -> users.id nullable
  installation_work_order_id FK -> work_orders.id nullable
  removal_work_order_id FK -> work_orders.id nullable
  removal_reason nullable
  notes nullable
  created_at
  updated_at
```

Rules:

- A tag should have at most one current installed asset at a time for the same maintainable position.
- An asset should have at most one current installation at a time.
- Removing/replacing equipment closes the previous installation by setting `removed_at` and `is_current=false`.
- Creating a new installation must not edit old work orders.

Use partial unique indexes for current rows:

```text
unique(company_id, tag_id) where is_current = true
unique(company_id, asset_id) where is_current = true
```

#### AssetSpecification

```text
AssetSpecification
  id
  asset_id FK -> assets.id
  specs JSONB
  created_at
  updated_at
```

#### AssetSpare

Connects an asset or asset model to valid spare items.

```text
AssetSpare
  id
  company_id
  asset_id FK -> assets.id nullable
  model_id FK -> managed_models.id nullable
  item_id FK -> material_management.items.id
  qty_required nullable
  recommended_stock_qty nullable
  criticality: critical / recommended / optional
  notes nullable
  created_at
  updated_at
```

Rules:

- Either `asset_id` or `model_id` must be present.
- `item_id` is the spare part or consumable to request/buy/stock.
- Use the material service to resolve item display fields.

#### AssetDocument

```text
AssetDocument
  id
  asset_id FK -> assets.id
  file_asset_id FK -> file_assets.id
  document_type: manual / datasheet / pid / drawing / certificate / photo / other
  note nullable
  created_at
```

#### AssetHistory

Append-only lifecycle log.

```text
AssetHistory
  id
  asset_id FK -> assets.id
  event_type: created / received / installed / removed / repaired / overhauled / moved / decommissioned / scrapped
  event_at
  user_id FK -> users.id nullable
  work_order_id FK -> work_orders.id nullable
  tag_id FK -> system_tags.id nullable
  asset_installation_id FK -> asset_installations.id nullable
  description
  data JSONB nullable
  created_at
```

### 4.4 Asset Endpoints

Use these route groups:

```text
GET    /assets
POST   /assets
GET    /assets/{asset_id}
PATCH  /assets/{asset_id}
DELETE /assets/{asset_id}

GET    /assets/tree
GET    /assets/{asset_id}/history
POST   /assets/{asset_id}/history

GET    /assets/{asset_id}/installations
POST   /assets/{asset_id}/install
POST   /assets/{asset_id}/remove

GET    /tags/{tag_id}/current-asset
GET    /tags/{tag_id}/asset-history

GET    /assets/{asset_id}/spares
POST   /assets/{asset_id}/spares
DELETE /assets/{asset_id}/spares/{spare_id}

POST   /assets/search
POST   /assets/ask
```

### 4.5 Asset Frontend

Build:

- asset list and filters
- asset detail
- current tag/installation card
- installation history
- asset tree by plant/system/component
- spare parts tab
- documents tab
- lifecycle timeline
- action: install asset at tag
- action: remove asset from tag
- action: request spare parts
- action: create work order

In the tag hierarchy UI, show the current asset under the tag as context, but do
not make the asset a child tag.

Example:

```text
P-1001A [Tag]
  Current asset: Pump SN-88921
  Status: installed
  Open WOs: 2
  Open defects: 1
```

## 5. Item To Asset Flow

`Item` is already the shared commerce and warehouse object. Maintenance should
create assets from selected items only when lifecycle tracking is needed.

```text
Commerce buys Item
Warehouse receives Item
Warehouse records serial if required
Maintenance registers selected serial/item as Asset
Maintenance installs Asset at Tag
```

### 5.1 Item Flags To Add Or Support

These flags belong in `material_management.Item` or an extension table:

```text
is_serial_tracked
is_asset_candidate
requires_asset_registration
```

Meaning:

- `is_serial_tracked`: warehouse must record serial numbers for received units.
- `is_asset_candidate`: UI can offer "Create Asset" for received serials.
- `requires_asset_registration`: the item cannot be installed/issued to service without asset registration.

### 5.2 Warehouse Serial Tracking

If not already present, add a warehouse serial table:

```text
StockSerial
  id
  company_id
  item_id FK -> items.id
  stock_item_id FK -> stock_items.id nullable
  grn_id FK -> goods_receipt_notes.id nullable
  grn_item_id FK -> goods_receipt_items.id nullable
  serial_number
  status: in_stock / reserved / issued / installed / returned / scrapped
  warehouse_id FK -> warehouses.id nullable
  storage_location_id FK -> storage_locations.id nullable
  created_at
  updated_at
```

Rules:

- Warehouse captures serial numbers during GRN for serial-tracked items.
- Adding a serial does not automatically create a maintenance asset.
- Asset creation is a deliberate lifecycle-registration action.
- If `requires_asset_registration=true`, require asset creation before installation/use.

### 5.3 Create Asset From Received Item

Add an asset endpoint like:

```text
POST /assets/from-stock-serial/{stock_serial_id}
```

It creates:

```text
Asset
  item_id = stock_serial.item_id
  source_stock_serial_id = stock_serial.id
  serial_number = stock_serial.serial_number
  lifecycle_status = in_stock or standby
```

Then installation is a separate step:

```text
POST /assets/{asset_id}/install
```

## 6. Work Order Management

### 6.1 Purpose

Work orders are the operational core of the CMMS.

They must support both:

- site work at a plant position
- workshop or lifecycle work on a physical asset

Therefore, work orders must store `tag_id` and `asset_id`.

### 6.2 Work Order Types

```text
CM           corrective maintenance
PM           preventive maintenance
Inspection   inspection work
Modification engineering or small change
Workshop     repair/overhaul away from installed position
```

### 6.3 Work Order Statuses

```text
draft
submitted
approved
rejected
planned
on_hold
in_progress
completed
closed
cancelled
```

### 6.4 State Machine

Use transition endpoints. Do not allow arbitrary frontend status patches.

```text
draft -> submitted
submitted -> approved
submitted -> rejected
approved -> planned
planned -> in_progress
in_progress -> completed
completed -> closed

submitted|approved|planned|in_progress -> on_hold
on_hold -> planned
on_hold -> in_progress
draft|submitted|approved|planned -> cancelled
```

Rules:

- Only `draft` work orders are fully editable.
- Approval requires `work_order_management:approve`.
- Close requires `work_order_management:close`.
- Closing locks normal editing.
- In Phase 4, HSE permit/access can gate `planned -> in_progress`.

### 6.5 WorkOrder Model

```text
WorkOrder
  id
  company_id
  wo_number auto, e.g. WO-2026-0001
  type: cm / pm / inspection / modification / workshop
  priority: critical / high / medium / low
  status

  tag_id FK -> tag_management.system_tags.id nullable
  asset_id FK -> asset_management.assets.id nullable
  asset_installation_id FK -> asset_installations.id nullable
  asset_system_id FK -> asset_systems.id nullable

  title
  description
  requested_by_user_id FK -> users.id nullable
  assigned_to_user_id FK -> users.id nullable
  assigned_team_name nullable

  source_type: manual / defect / pm_schedule / inspection / low_stock / other
  source_id nullable
  parent_pm_schedule_id nullable
  defect_id nullable

  scheduled_start nullable
  scheduled_end nullable
  actual_start nullable
  actual_end nullable
  completed_at nullable
  closed_at nullable
  approved_by_user_id nullable
  closed_by_user_id nullable

  downtime_start nullable
  downtime_end nullable
  downtime_hours nullable
  mttr_hours nullable

  description_embedding Vector(1024) nullable
  created_at
  updated_at
```

Rules:

- Field/site WO: `tag_id` is required. `asset_id` is optional but should be auto-filled from current installation when available.
- Workshop WO: `asset_id` is required. `tag_id` can be null or reference the previous/current tag.
- WO from defect: copy `tag_id`, `asset_id`, and current `asset_installation_id` from the defect context.
- WO from PM: copy target tag/asset/system from the PM plan.
- Old work orders must never change when an asset is replaced.

### 6.6 WorkOrderTask

```text
WorkOrderTask
  id
  work_order_id FK -> work_orders.id
  sequence
  title
  description
  status: pending / done / skipped
  completed_by_user_id nullable
  completed_at nullable
  result_note nullable
```

### 6.7 WorkOrderLabor

Employee is Phase 3, so use a nullable fallback now.

```text
WorkOrderLabor
  id
  work_order_id FK -> work_orders.id
  work_date
  hours
  craft_type: mechanical / electrical / instrument / operations / contractor / other
  user_id FK -> users.id nullable
  employee_id nullable
  employee_name nullable
  rate_amount nullable
  rate_currency_id nullable
  rate_amount_base nullable
  exchange_rate_used nullable
  notes nullable
```

If labor cost is recorded, use the four-column money rule.

### 6.8 WorkOrderMaterial

```text
WorkOrderMaterial
  id
  work_order_id FK -> work_orders.id
  item_id FK -> material_management.items.id
  planned_qty
  reserved_qty default 0
  issued_qty default 0
  actual_qty default 0
  returned_qty default 0
  unit_cost nullable
  currency_id nullable
  unit_cost_base nullable
  exchange_rate_used nullable
  warehouse_id nullable
  storage_location_id nullable
  notes nullable
```

Rules:

- Planned material does not reduce stock.
- Reservation should create/update warehouse reservation through a Celery event.
- Issue/actual consumption should create `StockMovement` OUT through a Celery event.
- Returned unused material should create `StockMovement` RETURN through a Celery event.

### 6.9 WorkOrderFailure

Only required for corrective maintenance.

```text
WorkOrderFailure
  id
  work_order_id FK -> work_orders.id
  failure_code
  failure_mode
  failure_cause
  corrective_action
  root_cause
  downtime_hours nullable
  notes nullable
```

Use ISO 14224-style taxonomy where possible.

### 6.10 WorkOrderAttachment

```text
WorkOrderAttachment
  id
  work_order_id FK -> work_orders.id
  file_asset_id FK -> file_assets.id
  attachment_type: photo / report / permit / checklist / other
  note nullable
  created_at
```

### 6.11 Work Order Endpoints

```text
GET    /work-orders
POST   /work-orders
GET    /work-orders/{wo_id}
PATCH  /work-orders/{wo_id}
DELETE /work-orders/{wo_id}

POST   /work-orders/{wo_id}/submit
POST   /work-orders/{wo_id}/approve
POST   /work-orders/{wo_id}/reject
POST   /work-orders/{wo_id}/plan
POST   /work-orders/{wo_id}/hold
POST   /work-orders/{wo_id}/resume
POST   /work-orders/{wo_id}/start
POST   /work-orders/{wo_id}/complete
POST   /work-orders/{wo_id}/close
POST   /work-orders/{wo_id}/cancel

GET    /work-orders/{wo_id}/tasks
POST   /work-orders/{wo_id}/tasks
PATCH  /work-orders/{wo_id}/tasks/{task_id}
DELETE /work-orders/{wo_id}/tasks/{task_id}

GET    /work-orders/{wo_id}/materials
POST   /work-orders/{wo_id}/materials
PATCH  /work-orders/{wo_id}/materials/{line_id}
POST   /work-orders/{wo_id}/materials/{line_id}/reserve
POST   /work-orders/{wo_id}/materials/{line_id}/issue
POST   /work-orders/{wo_id}/materials/{line_id}/return

GET    /work-orders/{wo_id}/labor
POST   /work-orders/{wo_id}/labor
PATCH  /work-orders/{wo_id}/labor/{labor_id}
DELETE /work-orders/{wo_id}/labor/{labor_id}

GET    /work-orders/{wo_id}/failure
PUT    /work-orders/{wo_id}/failure

POST   /work-orders/{wo_id}/attachments
GET    /work-orders/{wo_id}/attachments
DELETE /work-orders/{wo_id}/attachments/{attachment_id}

GET    /work-orders/{wo_id}/job-card
POST   /work-orders/search
POST   /work-orders/export
POST   /work-orders/ask
```

## 7. Defect Management

### 7.1 Purpose

Defect reporting is the entry point for fault-based maintenance.

A defect says:

```text
This tag has a problem, and optionally this installed asset is the failed unit.
```

### 7.2 Defect Statuses

```text
open
acknowledged
in_progress
resolved
closed
rejected
```

### 7.3 DefectReport Model

```text
DefectReport
  id
  company_id
  defect_number auto, e.g. DEF-2026-0001
  tag_id FK -> tag_management.system_tags.id
  asset_id FK -> assets.id nullable
  asset_installation_id FK -> asset_installations.id nullable
  severity: low / medium / high / critical
  status
  description
  description_embedding Vector(1024) nullable
  reported_by_user_id FK -> users.id nullable
  reported_at
  acknowledged_by_user_id nullable
  acknowledged_at nullable
  work_order_id FK -> work_orders.id nullable
  resolved_at nullable
  closed_at nullable
  rejected_reason nullable
  created_at
  updated_at
```

Rules:

- `tag_id` is required.
- `asset_id` is optional. If omitted, service should try to resolve current installed asset for the tag.
- Creating a WO from a defect copies `tag_id`, `asset_id`, and `asset_installation_id`.
- Closing a WO auto-resolves the linked defect through a Celery event.
- The defect itself does not grant permission to start work. HSE gates are Phase 4.

### 7.4 DefectComment

```text
DefectComment
  id
  defect_id FK -> defect_reports.id
  user_id FK -> users.id nullable
  comment
  old_status nullable
  new_status nullable
  created_at
```

### 7.5 Defect Endpoints

```text
GET    /defects
POST   /defects
GET    /defects/{defect_id}
PATCH  /defects/{defect_id}

POST   /defects/{defect_id}/acknowledge
POST   /defects/{defect_id}/reject
POST   /defects/{defect_id}/create-work-order
POST   /defects/{defect_id}/link-work-order
POST   /defects/{defect_id}/resolve
POST   /defects/{defect_id}/close

GET    /defects/{defect_id}/comments
POST   /defects/{defect_id}/comments

POST   /defects/search
POST   /defects/export
POST   /defects/ask
```

## 8. Preventive Maintenance

### 8.1 Purpose

PM management creates planned work before failures happen.

PM can target:

- a tag
- an asset
- an asset system
- a route/group of tags or assets

### 8.2 MaintenancePlan

```text
MaintenancePlan
  id
  company_id
  plan_number auto, e.g. MP-2026-0001
  name
  description
  target_type: tag / asset / asset_system / route
  tag_id nullable
  asset_id nullable
  asset_system_id nullable
  is_active
  created_at
  updated_at
```

Rules:

- Exactly one target must match `target_type`, except route plans which use route lines.
- If target is tag and a current asset exists, generated WOs should copy both tag and current asset.
- If target is asset, generated WOs should include current tag if installed.

### 8.3 MaintenanceTask

```text
MaintenanceTask
  id
  plan_id FK -> maintenance_plans.id
  sequence
  task_name
  description
  craft_type
  estimated_hours
  required_items JSONB or child rows
  created_at
  updated_at
```

If using child rows for required items:

```text
MaintenanceTaskItem
  id
  task_id FK -> maintenance_tasks.id
  item_id FK -> material_management.items.id
  quantity
  notes
```

### 8.4 TaskTrigger

```text
TaskTrigger
  id
  task_id FK -> maintenance_tasks.id
  trigger_type: calendar / meter
  frequency_value
  frequency_unit: days / weeks / months / hours / km / cycles
  last_done_date nullable
  last_done_meter_reading nullable
  next_due_date nullable
  next_due_meter_reading nullable
```

### 8.5 PMSchedule

```text
PMSchedule
  id
  company_id
  plan_id FK -> maintenance_plans.id
  task_id FK -> maintenance_tasks.id
  due_date
  status: pending / generated / overdue / skipped / cancelled
  generated_work_order_id FK -> work_orders.id nullable
  generated_at nullable
  created_at
  updated_at
```

Rules:

- Celery Beat checks due schedules daily.
- Due schedules emit a Celery event that work order module consumes.
- PM module must not synchronously create work orders by importing WO internals.

### 8.6 PM Endpoints

```text
GET    /pm/plans
POST   /pm/plans
GET    /pm/plans/{plan_id}
PATCH  /pm/plans/{plan_id}
DELETE /pm/plans/{plan_id}

GET    /pm/plans/{plan_id}/tasks
POST   /pm/plans/{plan_id}/tasks
PATCH  /pm/plans/{plan_id}/tasks/{task_id}
DELETE /pm/plans/{plan_id}/tasks/{task_id}

GET    /pm/tasks/{task_id}/triggers
POST   /pm/tasks/{task_id}/triggers
PATCH  /pm/tasks/{task_id}/triggers/{trigger_id}

GET    /pm/schedules
POST   /pm/schedules/{schedule_id}/generate-work-order
POST   /pm/schedules/{schedule_id}/skip

GET    /pm/calendar
POST   /pm/search
POST   /pm/ask
```

## 9. Inspection Management

### 9.1 Purpose

Inspections provide checklists and execution records. A failed inspection can
create a defect or a work order.

### 9.2 Models

```text
InspectionChecklist
  id
  company_id
  name
  description
  target_type: tag / asset / maintenance_task
  tag_id nullable
  asset_id nullable
  maintenance_task_id nullable
  is_active
  created_at
  updated_at

ChecklistItem
  id
  checklist_id FK -> inspection_checklists.id
  sequence
  description
  response_type: pass_fail / numeric / text
  unit nullable
  min_value nullable
  max_value nullable
  required boolean

InspectionResult
  id
  company_id
  checklist_id FK -> inspection_checklists.id
  tag_id nullable
  asset_id nullable
  asset_installation_id nullable
  work_order_id nullable
  performed_by_user_id nullable
  performed_at
  status: draft / completed / failed / cancelled
  summary nullable

InspectionResultLine
  id
  inspection_result_id FK -> inspection_results.id
  checklist_item_id FK -> checklist_items.id
  value_text nullable
  value_number nullable
  passed nullable
  note nullable
```

### 9.3 Inspection Endpoints

```text
GET    /inspections/checklists
POST   /inspections/checklists
GET    /inspections/checklists/{checklist_id}
PATCH  /inspections/checklists/{checklist_id}

POST   /inspections/checklists/{checklist_id}/items
PATCH  /inspections/checklists/{checklist_id}/items/{item_id}
DELETE /inspections/checklists/{checklist_id}/items/{item_id}

POST   /inspections/results
GET    /inspections/results
GET    /inspections/results/{result_id}
PATCH  /inspections/results/{result_id}
POST   /inspections/results/{result_id}/complete
POST   /inspections/results/{result_id}/create-defect
POST   /inspections/results/{result_id}/create-work-order

POST   /inspections/search
POST   /inspections/ask
```

## 10. Warehouse And Maintenance Integration

### 10.1 Responsibilities

```text
Maintenance says what is needed and why.
Commerce buys the required items.
Warehouse receives, stores, reserves, and issues items.
Financial pays and allocates cost.
```

### 10.2 Work Order Material Flow

```text
WorkOrderMaterial planned_qty
  -> reserve stock before work starts
  -> issue stock when material is handed to maintenance
  -> consume actual_qty during/after work
  -> return unused material if needed
```

Warehouse should expose services for:

```text
reserve_for_work_order(work_order_id, item_id, quantity, location optional)
issue_to_work_order(work_order_id, item_id, quantity, serials optional)
return_from_work_order(work_order_id, item_id, quantity, serials optional)
get_availability(item_id, warehouse/location optional)
```

These are called by Celery event handlers, not by direct cross-module writes.

### 10.3 Maintenance Requests Parts Through MR

When maintenance needs parts not available in stock, it should create an MR:

```text
MaterialRequisition
  source_type = work_order / defect / pm / manual
  source_id
  work_order_id nullable
  defect_id nullable
  tag_id nullable
  asset_id nullable
  needed_by_date
  priority
  reason
  items: item_id, quantity, notes
```

If Phase 1 requisitions do not yet have these source fields, add them in a
backward-compatible migration.

## 11. Commerce And Maintenance Integration

Commerce buys `Item`, not `Asset`.

Maintenance can ask commerce to buy:

- spare parts for an asset
- consumables for a work order
- complete equipment item that may later become an asset

Flow:

```text
WO/Defect/PM needs Item
  -> MR
  -> RFQ or direct PO
  -> PO
  -> GRN
  -> Warehouse stock
  -> Issue/install for maintenance
```

When a complete equipment item is received:

```text
GRN accepted item
  -> warehouse captures serial
  -> maintenance creates Asset from serial
  -> maintenance installs Asset at Tag
```

## 12. Financial Integration

Financial should consume cost evidence from commerce, warehouse, and maintenance.

Cost allocation should support:

```text
work_order_id
tag_id
asset_id
asset_installation_id
item_id
purchase_order_id
goods_receipt_id
```

Financial should be able to report:

- cost by work order
- cost by tag
- cost by physical asset
- cost by asset system
- material cost vs labor cost
- maintenance cost trend

Do not make financial own assets. It references maintenance entities through
service functions and FKs where appropriate.

## 13. Notification Engine

The notification engine listens to events and routes messages to users/roles.

Events:

```text
asset.installed
asset.removed
defect.created
defect.acknowledged
defect.rejected
defect.resolved
work_order.submitted
work_order.approved
work_order.rejected
work_order.assigned
work_order.started
work_order.completed
work_order.closed
work_order.overdue
pm.schedule_due
pm.work_order_generated
warehouse.material_reserved
warehouse.material_shortage
warehouse.material_issued
warehouse.serial_installed
```

Notifications should be async Celery work.

## 14. Maintenance Dashboard And Reports

### 14.1 KPI Cards

```text
critical_tags_with_open_fault
open_work_order_backlog
backlog_by_priority
overdue_work_orders
mttr
mtbf
pm_compliance_percent
maintenance_cost_base
material_shortage_count
```

### 14.2 Charts

```text
backlog-trend
wo-by-status
wo-by-type
faults-by-criticality
top-failing-tags
top-failing-assets
pm-compliance
maintenance-cost
material-consumption
```

### 14.3 Filters

```text
from
to
plant_id
asset_system_id
tag_id
asset_id
criticality
work_order_type
priority
```

## 15. Assistant Integration

Each Phase 2 module should add its own `assistant_tools.py`.

Read/search intents:

```text
search_assets
ask_assets
search_work_orders
ask_work_orders
search_defects
ask_defects
search_pm
ask_pm
search_inspections
ask_inspections
```

Draft intents:

```text
add_asset
install_asset
remove_asset
add_work_order
update_work_order
add_defect
create_work_order_from_defect
add_pm_plan
add_inspection_result
```

The assistant creates drafts only. The frontend commits using module endpoints.

## 16. RBAC

Minimum permissions:

```text
asset_management:read
asset_management:create
asset_management:update
asset_management:delete
asset_management:search
asset_management:ask
asset_management:install

work_order_management:read
work_order_management:create
work_order_management:update
work_order_management:delete
work_order_management:approve
work_order_management:close
work_order_management:search
work_order_management:ask
work_order_management:summary

defect_management:read
defect_management:create
defect_management:update
defect_management:resolve
defect_management:search
defect_management:ask
defect_management:export

pm_management:read
pm_management:create
pm_management:update
pm_management:delete
pm_management:search
pm_management:ask

inspection_management:read
inspection_management:create
inspection_management:update
inspection_management:delete
inspection_management:search
inspection_management:ask

maintenance:read
maintenance:export
maintenance:summary
```

Seed all permissions and protect every route.

## 17. Build Completion Checklist

Phase 2 is done only when:

- [ ] `asset_management` exists with `Asset`, `AssetInstallation`, spares, documents, and history.
- [ ] Existing tags are used as functional positions; asset installation links assets to tags.
- [ ] Work orders store `tag_id`, `asset_id`, and optional `asset_installation_id`.
- [ ] Work order statuses change only through transition endpoints.
- [ ] Defects require `tag_id` and optionally resolve current `asset_id`.
- [ ] Defect to WO copies tag and asset context.
- [ ] Closing a WO can resolve the linked defect through a Celery event.
- [ ] PM schedules generate WOs through Celery events.
- [ ] Inspection failures can create defects or WOs.
- [ ] Work order material reservation/issue/return integrates with warehouse through events.
- [ ] Serialized warehouse stock can become an asset through explicit registration.
- [ ] Maintenance costs can be reported by WO, tag, asset, and item.
- [ ] All modules have search, ask, export where required, RBAC, seeded permissions, tests, and migrations.
- [ ] `pytest` and `alembic check` pass.

