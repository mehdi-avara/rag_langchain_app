# Maintenance Management Flow

This file explains Phase 2 maintenance in product and frontend terms.
It is based on the corrected implementation contract in `PHASE_2_IMPLEMENTATION.md`.

## 1. The Main Idea

The system should let teams move from a plant problem or maintenance plan to
parts, purchasing, stock, work execution, cost, and history.

The shared concepts are:

```text
Item  = thing we can buy, stock, issue, consume, or install
Tag   = permanent plant position or functional location
Asset = physical lifecycle-tracked unit
WO    = maintenance work at a tag and/or on an asset
```

The most important rule:

```text
Commerce buys Items.
Warehouse stores Items.
Maintenance turns selected Items/serials into Assets when lifecycle tracking is required.
Maintenance installs Assets at Tags.
```

## 2. Why Tag And Asset Are Both Needed

`Tag` answers:

```text
Where in the plant did this happen?
```

Example:

```text
P-1001A pump position
```

`Asset` answers:

```text
Which physical equipment was involved?
```

Example:

```text
Pump serial SN-88921
```

If a pump is replaced, the tag stays the same:

```text
P-1001A
  old asset: Pump SN-88921
  new asset: Pump SN-99010
```

So a work order should preserve both histories:

```text
WorkOrder
  tag_id
  asset_id
  asset_installation_id
```

That allows:

```text
Show all maintenance at P-1001A
Show all maintenance on Pump SN-88921
Show what asset was installed when WO-2026-0007 happened
```

## 3. Asset Installation

Do not put `asset_id` directly on the tag as the only source of truth.
Do not put `tag_id` directly on the asset as the only source of truth.

Use installation history:

```text
AssetInstallation
  tag_id
  asset_id
  installed_at
  removed_at
  is_current
```

This supports:

```text
What is currently installed at tag P-1001A?
Where has asset SN-88921 been installed?
What was installed at this tag last year?
```

Frontend should show the current installed asset under the tag node, but the
asset is not a child tag.

Example tree:

```text
Crude Unit
  Pumping System
    P-1001A [Tag]
      Current asset: Pump SN-88921
      Open WOs: 2
      Open defects: 1
```

## 4. Item To Asset Flow

An item becomes an asset only when the business wants lifecycle or maintenance
tracking for a physical unit.

Flow:

```text
Commerce buys Item
Warehouse receives Item
Warehouse records serial if needed
Maintenance creates Asset from that serial/item
Maintenance installs Asset at Tag
```

Serial number is not enough by itself.

```text
Serial number = identifies physical unit
Asset = lifecycle/maintenance record for that physical unit
```

Examples that often become assets:

```text
pump
motor
compressor
control valve
analyzer
generator
transformer
special calibrated tool
```

Examples that usually do not become assets:

```text
bolt
gasket
oil
grease
chemical
PPE
generic consumable
```

Useful item flags:

```text
is_serial_tracked
is_asset_candidate
requires_asset_registration
```

## 5. Team Responsibilities

### Maintenance Team

Owns:

```text
tags in maintenance context
assets
asset installations
defects
work orders
PM plans
inspections
required materials
maintenance history
```

Maintenance tells commerce:

```text
what item is needed
why it is needed
which WO/defect/tag/asset needs it
when it is needed
priority
quantity
acceptable alternatives/specifications
```

### Commerce Team

Owns:

```text
MR review/procurement flow
RFQ
quotation comparison
supplier selection
purchase order
```

Commerce tells warehouse:

```text
what was ordered
supplier
expected delivery date
PO lines and quantities
destination warehouse if known
linked MR/WO/defect context
```

### Warehouse Team

Owns:

```text
receiving
GRN
stock
serial capture
reservation
issue
return
transfer
stock counts
```

Warehouse tells maintenance:

```text
what is available
what is reserved for a WO
what was issued
what is short
what arrived
what was rejected/damaged
where the item is stored
which serial numbers are available
```

### Financial Team

Owns:

```text
invoices
receipts
payments
PO/GRN/invoice matching
cost allocation
maintenance cost reports
```

Financial should report cost by:

```text
work order
tag
asset
asset system
item
supplier
period
```

## 6. Main Maintenance Flows

### 6.1 Corrective Maintenance From Defect

```text
Report Defect
  -> tag_id required
  -> asset_id optional/current asset resolved
  -> status open

Acknowledge Defect
  -> status acknowledged

Create Work Order
  -> WO copies tag_id, asset_id, asset_installation_id
  -> defect stores work_order_id

Plan Work
  -> tasks
  -> labor/team
  -> materials
  -> schedule

Reserve/Issue Materials
  -> warehouse event
  -> stock reserved/issued

Start Work
  -> status in_progress

Complete Work
  -> actual labor/material/failure data
  -> status completed

Close Work
  -> supervisor closes
  -> status closed
  -> linked defect resolves by event
```

### 6.2 Manual Work Order

```text
Create WO manually
  -> choose tag for site work
  -> auto-fill current asset if known
  -> or choose asset for workshop work

Submit
Approve
Plan
Start
Complete
Close
```

### 6.3 Preventive Maintenance

```text
Create PM Plan
  -> target tag, asset, asset system, or route

Add PM Tasks
  -> craft
  -> estimated hours
  -> required items
  -> checklist

Add Trigger
  -> calendar or meter

Generate PM Schedule
  -> pending due dates

Celery Beat checks due schedules
  -> emits event
  -> WO module creates PM Work Order

Execute and close WO
  -> schedule becomes generated/completed
  -> next due date calculated
```

### 6.4 Inspection

```text
Create checklist
Execute inspection
Record result
If failed:
  create defect
  or create work order
```

### 6.5 Buying A Spare Part For A WO

```text
WO needs Item
  -> check warehouse availability

If available:
  reserve/issue from warehouse

If not available:
  maintenance creates MR with WO/tag/asset context
  commerce buys through RFQ/PO
  warehouse receives GRN
  warehouse notifies maintenance
  maintenance reserves/issues item to WO
```

### 6.6 Buying A Whole Asset

```text
Maintenance requests complete equipment Item
  -> MR references replacement tag/asset context

Commerce buys Item
  -> PO

Warehouse receives Item
  -> captures serial

Maintenance creates Asset from received serial
  -> installs Asset at Tag
  -> old AssetInstallation removed
  -> new AssetInstallation current
```

## 7. Frontend Screens

### Asset Screens

Build:

```text
asset list
asset detail
asset tree by plant/system
tag tree with current asset card
asset installation history
spare parts tab
documents tab
lifecycle timeline
create asset from serial
install/remove asset
request spare parts
```

### Work Order Screens

Build:

```text
WO list
WO detail
status timeline
task checklist
material planning
material reservation/issue status
labor entry
failure analysis
attachments/photos
job card print/PDF
approval/transition actions
```

Show both:

```text
Tag: P-1001A
Asset: Pump SN-88921
```

### Defect Screens

Build:

```text
report fault form
defect register
defect detail
comments/timeline
create/link WO button
filters by tag, asset, severity, status
```

### PM Screens

Build:

```text
PM plan list
PM plan editor
task editor
trigger editor
required items
PM calendar
due/overdue schedules
generated WO link
```

### Inspection Screens

Build:

```text
checklist builder
inspection execution form
inspection result detail
failed item follow-up: create defect or WO
```

### Dashboard

Build:

```text
critical tags with open faults
open WO backlog
overdue WOs
MTTR
MTBF
PM compliance
maintenance cost
material shortages
```

Charts:

```text
backlog trend
WO by status
WO by type
faults by criticality
top failing tags
top failing assets
PM compliance
maintenance cost
```

## 8. Rules For Frontend Actions

Do not directly edit statuses.

Do not send:

```text
PATCH /work-orders/{id} { "status": "closed" }
```

Use workflow actions:

```text
submit
approve
reject
plan
hold
resume
start
complete
close
cancel
```

The backend should decide if a transition is allowed.

## 9. Minimum Data To Show On Work Order

Every WO detail page should clearly show:

```text
WO number
type
priority
status
tag
asset
asset installation
source: manual / defect / PM / inspection
requested by
assigned to
scheduled dates
actual dates
tasks
planned materials
reserved/issued materials
labor
failure data
attachments
linked defect
linked PM schedule
cost summary
```

## 10. What Not To Do

Do not make assets children in the tag hierarchy.

Do not store only `asset_id` on work orders.

Do not store only `tag_id` on work orders.

Do not make serial entry automatically create an asset unless customer policy
requires it.

Do not make commerce buy assets directly. Commerce buys items.

Do not make warehouse own maintenance assets. Warehouse owns stock and serial stock.

Do not let frontend manually set workflow statuses.

