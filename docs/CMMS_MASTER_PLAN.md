# CMMS Master Plan — Petroleum Industry Platform
> Last updated: 2026-06-13
> Base system: RAG / Knowledge Management (FastAPI + PostgreSQL + Elasticsearch + ChromaDB + Celery)

---

## 1. What Already Exists (Foundation)

The existing codebase is a production-ready RAG system. Every new module builds **on top of** this — it is not replaced.

| Existing Module | What it has |
|---|---|
| `document_management` | Upload, version, chunk, embed documents |
| `tag_management` | Tag any entity; semantic tag search |
| `model_management` | AI model configs, document linking, ask/chat |
| `buying_management` | Items master, costs, purchase receipts, processes |
| `financial_management` | Financial receipts, cards, customers |
| `property_management` | Properties catalog, warehouse skeleton |
| `routs/` | Auth, users, company, RBAC, chat, assets, STT |
| `core/` | Chunking, embedding, semantic search, agents skeleton |
| `retrieval/` | Vector (ChromaDB) + keyword (Elasticsearch) hybrid search |
| `db/` | SQLAlchemy + Alembic migrations |
| `Models/` | User, Company, RBAC, Document, Chunk, Chat, FileAsset |

**Key architectural rule (keep forever):**
Each feature area lives in its **own app folder** (`buying_management/`, `warehouse_management/`, etc.).
Apps talk to each other **only through their own REST API** — no cross-app direct DB joins.
This keeps each module independently deployable and testable.

---

## 2. Overall Architecture Principles

```
┌─────────────────────────────────────────────────────────┐
│                    SINGLE FASTAPI PROCESS                │
│   (all apps registered as APIRouter on main app)        │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │warehouse │ │procure   │ │asset_mgmt│ │work_order│  │
│  │_mgmt     │ │_mgmt     │ │          │ │_mgmt     │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │
│       │             │             │             │         │
│  ┌────▼─────────────▼─────────────▼─────────────▼─────┐ │
│  │              SHARED SERVICES LAYER                  │ │
│  │  • RBAC (permission checks)                        │ │
│  │  • Document Intelligence (attach docs to anything) │ │
│  │  • Tag System (tag anything)                       │ │
│  │  • Notification Engine (events → notifications)   │ │
│  │  • AI Search (semantic search across all modules) │ │
│  │  • Audit Log (every write is recorded)            │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  STORAGE: PostgreSQL + Elasticsearch + ChromaDB  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**AI-Friendliness Rules (apply to every module):**
1. Every entity that has meaningful text fields gets indexed in the semantic search.
2. Every list endpoint supports `?q=` for AI-powered natural language search.
3. Every module exposes a `/ask` endpoint (like model_management does today) so the AI agent can query it.
4. Documents can be attached to any entity (work orders, purchase orders, assets, etc.).
5. Tags can be applied to any entity.

---

## 3. Delivery Phases

### Phase 1 — Commerce & Warehouse (First Delivery)
> Target users: Procurement team, Warehouse keepers, Storekeepers

| # | Module | Priority |
|---|---|---|
| 1.1 | **Warehouse Management** (locations, stock, movements) | P0 |
| 1.2 | **Material Master** (items catalog, units, categories) | P0 |
| 1.3 | **Procurement** (MR → RFQ → PO → GRN) | P0 |
| 1.4 | **Supplier Management** (vendor registry, evaluation) | P1 |
| 1.5 | **Inventory Reports & AI Search** | P1 |

### Phase 2 — Maintenance & Admin (Second Delivery)
> Target users: Maintenance engineers, Planners, Admins

| # | Module | Priority |
|---|---|---|
| 2.1 | **Asset Management** (equipment registry, hierarchy) | P0 |
| 2.2 | **Work Order Management** (CM + PM work orders) | P0 |
| 2.3 | **Maintenance Planning** (PM schedules, checklists) | P0 |
| 2.4 | **Notification & Workflow Engine** | P1 |
| 2.5 | **Maintenance KPI Dashboard** | P1 |

### Phase 3 — Human Resources (Third Delivery)
> Target users: HR managers, Department heads

| # | Module | Priority |
|---|---|---|
| 3.1 | **Employee Management** (master data, org chart) | P0 |
| 3.2 | **Leave Management** | P0 |
| 3.3 | **Training & Certification Tracking** | P0 |
| 3.4 | **Personnel Documents** | P1 |
| 3.5 | **Payroll basics** | P2 |

### Phase 4 — Full Platform (Final Delivery)
> Target users: Everyone in the petroleum facility

| # | Module | Priority |
|---|---|---|
| 4.1 | **Internal Communication** (letters, memos, announcements) | P0 |
| 4.2 | **HSE Module** (incidents, permits, risk assessments) | P0 |
| 4.3 | **Project Management** | P1 |
| 4.4 | **AI Manager Agent** (natural language → reports) | P0 |
| 4.5 | **Advanced Reporting & Dashboards** | P1 |
| 4.6 | **Contractor Management** | P2 |

---

## 4. Cross-Cutting Modules (Build Once, Used by All)

These are not phase-specific — they are shared infrastructure that every phase uses.
Build them progressively starting from Phase 1.

### 4.1 Notification Engine
- Internal bell notifications (already have user model)
- Email notifications (async via Celery)
- Rules: "when X happens in module Y, notify user Z"
- Every module publishes events; the engine routes them

### 4.2 Approval Workflow Engine
- Generic configurable workflow: Draft → Submitted → Approved/Rejected → Executed
- Applies to: Purchase Orders, Work Orders, Leave Requests, Permits, etc.
- Each workflow step has: approver role, deadline, escalation

### 4.3 Audit Log
- Every write (create/update/delete) on every entity is logged
- Who, what, when, old value → new value
- Searchable by AI agent

### 4.4 AI Manager Agent (evolves over phases)
- Phase 1: Can answer "what is current stock of item X?" or "show pending POs"
- Phase 2: Can answer "what work orders are overdue?" or "which assets need PM?"
- Phase 3: Can answer "who is on leave this week?"
- Phase 4: Full cross-module natural language reporting

---

## 5. Detailed Feature Breakdown Per Phase

---

### PHASE 1 — Commerce & Warehouse

#### Module 1.1 — Warehouse Management

**What it does:**
Manages physical storage locations and tracks where stock is.

**Entities:**
- `Warehouse` (main warehouse, secondary warehouses)
- `Zone` (area within warehouse: A, B, C)
- `Shelf` / `Bin` (specific location within zone)
- `StockItem` (what material is stored where, how much)
- `StockMovement` (every in/out/transfer is recorded permanently)
- `StockCount` (periodic physical count records)

**Key features:**
- Multi-warehouse support
- Location tree: Warehouse → Zone → Shelf → Bin
- Minimum/maximum stock level alerts
- Stock movement history (never deleted, only appended)
- AI search: "find all bins with item X" or "which items are below minimum"
- Attach documents to any item (datasheets, safety sheets)
- Barcode/QR code field on items

**Integration points:**
- Receives stock from Procurement (GRN creates StockMovement IN)
- Issues stock to Maintenance (Work Order material consumption creates StockMovement OUT)
- Reports to Financial (stock valuation)

**AI touchpoints:**
- `/warehouse/ask` — natural language queries on stock
- Stock items indexed in semantic search (description, category, specs)
- Alert summaries can be consumed by Manager Agent

---

#### Module 1.2 — Material Master (Items Catalog)

**What it does:**
Central registry of all materials, spare parts, and consumables.

**Entities:**
- `ItemCategory` (Electrical, Mechanical, Instrumentation, Chemical, PPE, Office, etc.)
- `Unit` (KG, Liter, Piece, Meter, Box, etc.)
- `Item` (master item: code, name, description, category, unit, specs)
- `ItemAlternative` (alternate item codes / vendor codes)
- `ItemDocument` (linked manuals, datasheets, safety data sheets)

**Key features:**
- Unique item code per company
- Duplicate detection on create
- Specs stored as JSON (flexible per category)
- AI search on item description + specs
- Import from Excel (bulk upload)
- Tag items (critical spare, fast-moving, slow-moving, etc.)

---

#### Module 1.3 — Procurement

**What it does:**
Full procurement lifecycle from need to delivery.

**Workflow:**
```
Material Requisition (MR)
        ↓
Request for Quotation (RFQ)  [optional]
        ↓
Purchase Order (PO)
        ↓
Goods Receipt Note (GRN)
        ↓
Stock Movement IN (automatic)
```

**Entities:**
- `MaterialRequisition` (who needs what, how much, when, why)
- `MRItem` (line items on MR)
- `RequestForQuotation` (sent to suppliers)
- `QuotationResponse` (supplier response)
- `PurchaseOrder` (approved order to supplier)
- `POItem` (line items on PO)
- `GoodsReceiptNote` (what actually arrived)
- `GRNItem` (what was received per line)

**Approval workflow:**
- MR: requester → department head → procurement → approved
- PO: procurement → finance → GM (above threshold) → approved

**AI touchpoints:**
- "What are all pending POs for supplier X?"
- "How long does procurement take on average?"
- "Which items have been ordered most this year?"

**Integration:**
- GRN auto-creates StockMovement IN in Warehouse module
- PO links to Supplier in Supplier Management
- MR can be created from Work Order (maintenance requests parts)

---

#### Module 1.4 — Supplier Management

**What it does:**
Central registry of all vendors and their performance.

**Entities:**
- `Supplier` (company name, code, contact, country, type)
- `SupplierContact` (multiple contacts per supplier)
- `SupplierCategory` (what they supply)
- `SupplierDocument` (contracts, certifications, licenses)
- `SupplierEvaluation` (periodic scoring: delivery, quality, price)

**Key features:**
- Supplier approval status (pending → approved → blacklisted)
- Attach procurement documents (contract, NDA, catalog)
- Performance score from PO history (on-time delivery %, quality issues)
- AI search across supplier name, category, products they supply

---

### PHASE 2 — Maintenance & Admin

#### Module 2.1 — Asset Management

**What it does:**
Equipment and asset registry for the petroleum facility.

**Hierarchy:**
```
Plant
  └── Unit / System
        └── Equipment
              └── Component / Sub-component
```

**Entities:**
- `Plant` (refinery, pipeline, offshore platform)
- `AssetSystem` (process unit, utility system)
- `Asset` (individual equipment: pump, compressor, valve, instrument)
- `AssetSpecification` (technical specs as structured JSON per asset type)
- `AssetDocument` (manuals, P&IDs, drawings, certificates)
- `AssetHistory` (lifecycle events: installed, modified, replaced, decommissioned)

**Key features:**
- Unique tag number per asset (e.g., P-1001 for pump)
- Asset types: Rotating, Static, Electrical, Instrument, Civil
- Criticality rating (A/B/C) — drives PM frequency
- Link to spare parts in Item Master (which items are used for this asset)
- Attach P&ID drawings, datasheets, vendor manuals
- AI: "show me all criticality-A pumps in Unit 2"

---

#### Module 2.2 — Work Order Management

**What it does:**
Core of CMMS — managing all maintenance jobs.

**Work Order Types:**
- **CM** (Corrective Maintenance): reactive, something broke
- **PM** (Preventive Maintenance): scheduled, time/meter-based
- **PdM** (Predictive): based on condition monitoring
- **Inspection**: periodic inspection
- **Modification/Project**: small engineering change

**Lifecycle:**
```
Draft → Submitted → Approved → Planned → In Progress → Completed → Closed
         (with option to Reject or Put On Hold at any step)
```

**Entities:**
- `WorkOrder` (header: type, asset, description, priority, dates)
- `WorkOrderTask` (checklist steps / job tasks)
- `WorkOrderLabor` (who worked, how many hours)
- `WorkOrderMaterial` (which items consumed from warehouse)
- `WorkOrderFailure` (for CM: failure code, cause, action taken)
- `WorkOrderAttachment` (photos, reports)

**Key features:**
- Priority: Critical / High / Medium / Low
- Failure coding (ISO 14224 standard for petroleum)
- Material reservation from warehouse before work starts
- Labor tracking (technician, hours, craft type)
- Print job card as PDF
- AI: "how many CM work orders has asset P-1001 had in the last year?"

---

#### Module 2.3 — Maintenance Planning

**What it does:**
Preventive maintenance schedules so nothing breaks unexpectedly.

**Entities:**
- `MaintenancePlan` (plan for an asset or group: what to do, how often)
- `MaintenanceTask` (individual task within a plan: lubricate, inspect, replace)
- `TaskFrequency` (every X days / every X hours / every X cycles)
- `PMSchedule` (generated calendar of upcoming PM due dates)
- `InspectionChecklist` (step-by-step checklist for inspections)
- `ChecklistItem` (individual check: Pass/Fail/Measure)

**Key features:**
- Auto-generate Work Orders from due PM schedules (via Celery)
- Meter-based triggering (run hours, km, cycles)
- Route maintenance (multiple assets same route, one work order)
- Calendar view of upcoming maintenance
- AI: "what PM is due next week for Unit 3?"

---

#### Module 2.4 — Notification & Workflow Engine

Covered in section 4 above. Implement from Phase 2 onward.

---

### PHASE 3 — Human Resources

#### Module 3.1 — Employee Management

**Entities:**
- `Department` (organizational units)
- `Position` (job title/role within org)
- `Employee` (master record: personal info, position, department, hire date)
- `OrgChart` (derived from Employee.department + Employee.reports_to)
- `EmployeeDocument` (contracts, ID copies, qualifications)

**Key features:**
- Org chart visualization data
- Employee linked to User account (or standalone if they don't use the system)
- Position-based access control (integrates with existing RBAC)
- AI: "who is the maintenance manager?" or "list all engineers in Instrument department"

---

#### Module 3.2 — Leave Management

**Entities:**
- `LeaveType` (Annual, Sick, Emergency, etc.)
- `LeaveBalance` (per employee per year)
- `LeaveRequest` (employee requests leave)
- `LeaveApproval` (manager approves/rejects)
- `LeaveCalendar` (view team availability)

---

#### Module 3.3 — Training & Certification

**Entities:**
- `Training` (course name, provider, duration)
- `Certification` (certifications required for certain jobs: H2S, BOSIET, etc.)
- `EmployeeTraining` (employee completed a training on a date, expiry date)
- `EmployeeCertification` (employee holds a cert, expiry alert)
- `TrainingPlan` (annual training plan per department)

**AI touchpoint:** "which employees have expired H2S certification?"

---

### PHASE 4 — Full Platform

#### Module 4.1 — Internal Communication

**Entities:**
- `Letter` (formal internal letter / memo with reference number)
- `LetterRecipient` (to whom, CC)
- `LetterAttachment`
- `Announcement` (broadcast to roles/departments)
- `InternalMessage` (thread-based messaging between users)

**Key features:**
- Auto-numbering for formal letters (e.g., MAINT-2026-001)
- Letter status: Draft → Sent → Acknowledged
- Full-text search on all letters
- AI: "find all letters about pump P-1001 in the last 6 months"

---

#### Module 4.2 — HSE Module

**Entities:**
- `Incident` (near miss, first aid, LTI, fatality, environmental)
- `IncidentInvestigation` (root cause analysis)
- `PermitToWork` (hot work, confined space, electrical isolation, height)
- `PTWStep` (steps completed on permit)
- `RiskAssessment` (job safety analysis)
- `SafetyObservation` (positive or negative safety behavior observed)
- `HSEStatistic` (weekly/monthly KPIs: TRIR, LTI days, etc.)

**Key features:**
- Permit to Work is a critical safety gate before maintenance work begins
- PTW can be linked to a Work Order (WO cannot start without valid PTW)
- Incident reports are confidential (role-restricted access)
- AI: "what is our TRIR for Q1?" or "show all open hot work permits"

---

#### Module 4.3 — AI Manager Agent

**What it does:**
A conversational agent that a manager can ask questions and get cross-module answers.

**How it works (technical):**
- Agent receives a natural language question
- Agent determines which modules are relevant (tool selection)
- Agent calls each relevant module's `/ask` endpoint
- Agent synthesizes results into a coherent answer with sources
- Optionally generates a structured report

**Example queries:**
- "What is the current state of the maintenance backlog?"
- "Which assets have had the most failures this year?"
- "What materials are below minimum stock level?"
- "How many employees are on leave this week?"
- "Show me all overdue work orders for the compressor train"

**Technical approach:**
- Uses existing `core/agents/` skeleton
- Each module registers itself as an "agent tool"
- LangChain tool-use or function-calling pattern
- Results include source references (which WO, which asset, etc.)

---

## 6. Shared Technical Requirements

### AI Search (every module must have this)
```
GET /warehouse/items/?q=hydraulic+pump+seal
GET /work-orders/?q=pump+P-1001+bearing+failure
GET /employees/?q=instrument+engineer+certification
```
Implementation: semantic search via existing `retrieval/` module, same as documents.

### Document Attachment (every module must have this)
Every entity should support: `POST /assets/{entity_type}/{entity_id}/documents`
Uses existing `document_management` + `file_assets` system.

### Tag Support (every module must have this)
Every entity should support: `POST /tags/{entity_type}/{entity_id}`
Uses existing `tag_management` system.

### Audit Trail (every write endpoint)
Log: user_id, action, entity_type, entity_id, old_value, new_value, timestamp

### Pagination + Filtering (every list endpoint)
Standard: `?page=1&size=20&sort=created_at&order=desc&status=active`

---

## 7. Implementation Order — Day by Day Structure

Each "day" = one focused implementation session.
Each session follows this pattern:

```
Day N: [Module Name]
  ├── Models (SQLAlchemy)
  ├── Alembic migration
  ├── Schemas (Pydantic)
  ├── Services (business logic)
  ├── Routes (FastAPI endpoints)
  ├── Tests
  ├── AI integration (semantic indexing + /ask endpoint)
  └── Frontend spec
```

### Recommended Day Order:

**Week 1 — Warehouse Foundation**
- Day 1: Material Master (Items, Categories, Units)
- Day 2: Warehouse Locations (Warehouse, Zone, Shelf, Bin)
- Day 3: Stock & StockMovements
- Day 4: Stock Alerts + AI Search on Inventory
- Day 5: Inventory Reports API

**Week 2 — Procurement**
- Day 6: Supplier Management
- Day 7: Material Requisition (MR)
- Day 8: Purchase Order (PO) + approval workflow
- Day 9: Goods Receipt Note (GRN) + auto stock movement
- Day 10: Procurement Reports + AI Search

**Week 3 — Asset & Work Orders**
- Day 11: Asset Management (Plant, System, Asset)
- Day 12: Work Order core (CM work orders)
- Day 13: Work Order Labor + Material tracking
- Day 14: Work Order approval workflow
- Day 15: Work Order AI search + reports

**Week 4 — Maintenance Planning**
- Day 16: Maintenance Plans + Tasks
- Day 17: PM Schedules + Celery auto-generation
- Day 18: Inspection Checklists
- Day 19: Notification Engine (Phase 1)
- Day 20: Maintenance KPI endpoints

**Week 5 — HR**
- Day 21: Department + Position + Employee
- Day 22: Leave Management
- Day 23: Training & Certification
- Day 24: Employee documents + org chart API

**Week 6 — Communication & HSE**
- Day 25: Internal Letters + Messaging
- Day 26: Announcements
- Day 27: HSE Incidents + Investigations
- Day 28: Permit to Work
- Day 29: HSE Statistics API

**Week 7 — AI Agent**
- Day 30: Agent tool registry
- Day 31: Cross-module query routing
- Day 32: Manager Dashboard API
- Day 33: Agent response formatting
- Day 34: End-to-end agent testing

---

## 8. Prompts for Each Implementable Module

Use the following prompts when starting each day's session.
Each prompt is self-contained — it gives me full context about the project so I can plan that module's implementation in detail.

---

### PROMPT 1 — Material Master (Items Catalog)

```
PROJECT CONTEXT:
We are building a CMMS (Computerized Maintenance Management System) for the petroleum industry.
The backend is FastAPI + PostgreSQL + SQLAlchemy + Alembic + ChromaDB + Elasticsearch + Celery.
Architecture: each module lives in its own app folder (e.g. buying_management/, warehouse_management/).
Apps communicate via REST API only (no cross-app DB joins).
The system already has: document management, tag management, RBAC, user/company management,
semantic search (vector + keyword hybrid), file assets, and AI chat.

EXISTING RELEVANT CODE:
- backend/buying_management/ has partial item/cost/receipt models — review these first
- backend/Models/rbac.py for RBAC pattern
- backend/routs/documents.py for document route pattern
- Every module folder has: models.py, schemas.py, routes/, tests/

TODAY'S TASK: Material Master module
Build the central item/material catalog that all other modules reference.

REQUIREMENTS:
1. ItemCategory model (tree structure, parent_id for sub-categories)
2. Unit model (KG, Liter, Piece, Meter, etc.)
3. Item model (code, name, description, category, unit, specs as JSON, barcode, is_active)
4. ItemAlternative model (vendor codes / alternate item numbers)
5. AI search: index item name + description + specs in semantic search
6. Attach documents to items (use existing file_asset system)
7. Tag items (use existing tag_management)
8. RBAC: warehouse_manager can create/edit, others can only view
9. All list endpoints: pagination + ?q= semantic search + filters

Please:
A) List all models with their fields and relationships
B) List all API endpoints with HTTP method, path, request body, response
C) List integration points with other existing modules
D) List AI search fields and indexing strategy
E) List what needs to be migrated in Alembic
F) At the end, provide the frontend specification: what screens/components the frontend team needs to build for this module
```

---

### PROMPT 2 — Warehouse Locations & Stock

```
PROJECT CONTEXT:
[Same as Prompt 1 — copy the PROJECT CONTEXT block]

WHAT IS ALREADY BUILT AT THIS POINT:
- Material Master (Items, Categories, Units) — fully implemented
- backend/property_management/ has partial warehouse model — review first

TODAY'S TASK: Warehouse Management module
Build the physical warehouse structure and stock tracking system.

REQUIREMENTS:
1. Warehouse model (name, code, location, type: main/secondary/field)
2. Zone model (area within warehouse, belongs to Warehouse)
3. StorageLocation model (shelf/bin, belongs to Zone, has capacity)
4. StockItem model (Item × StorageLocation = quantity, min_level, max_level)
5. StockMovement model (every in/out/transfer permanently recorded — append-only)
   - movement_type: RECEIPT (from GRN), ISSUE (to work order), TRANSFER, ADJUSTMENT, RETURN
   - reference_type + reference_id (links to the GRN or Work Order that caused it)
6. StockCount model (physical inventory count sessions)
7. StockCountLine (counted quantity per item per location)
8. Business logic:
   - Stock quantity is always calculated from StockMovements (not stored separately — or if stored, always reconciled)
   - Alert when stock goes below min_level
   - Prevent issuing more than available stock
9. AI search on: item name, location code, category
10. RBAC: storekeeper can issue/receive, warehouse_manager can adjust

Please provide:
A) All models with fields and relationships
B) All API endpoints
C) How StockMovement references other modules (GRN, Work Order)
D) Celery tasks: daily stock alert check, periodic reconciliation
E) AI search strategy
F) Frontend specification: screens for warehouse keepers and storekeepers
```

---

### PROMPT 3 — Procurement (MR → PO → GRN)

```
PROJECT CONTEXT:
[Same as Prompt 1 — copy the PROJECT CONTEXT block]

WHAT IS ALREADY BUILT AT THIS POINT:
- Material Master (Items, Categories, Units)
- Warehouse Management (Warehouse, Zone, Location, StockMovement)
- Supplier Management (Supplier, SupplierContact, SupplierDocument)
- backend/buying_management/ has partial purchase models — review first

TODAY'S TASK: Full Procurement module
Build the complete purchasing workflow from need to delivery.

WORKFLOW:
MaterialRequisition → [optional: RFQ → QuotationResponse] → PurchaseOrder → GoodsReceiptNote → StockMovement IN

REQUIREMENTS:
1. MaterialRequisition (MR): requester, department, needed_by_date, items list, reason, status
2. MRItem: item, quantity, unit, notes
3. RequestForQuotation (RFQ): links to MR, sent to multiple suppliers
4. QuotationResponse: supplier responds with price + delivery date per item
5. PurchaseOrder (PO): links to MR (and optionally RFQ winner), supplier, payment_terms, delivery_date
6. POItem: item, quantity, unit_price, total_price
7. GoodsReceiptNote (GRN): what physically arrived, links to PO
8. GRNItem: item, received_quantity, accepted_quantity, rejected_quantity
9. On GRN save: auto-create StockMovement IN in warehouse module
10. Approval workflow:
    - MR: requester → dept_head → procurement_officer → approved
    - PO: procurement_officer → finance_manager → (if >threshold) general_manager → approved
11. Status tracking at every step
12. AI search: "find all POs for supplier X this year" / "pending MRs for department Y"
13. Print PO as PDF (use existing PDF/document system or generate)

Please provide:
A) All models with fields and relationships
B) Complete API endpoint list
C) Approval workflow implementation (state machine)
D) How GRN auto-triggers StockMovement (service call pattern)
E) AI search and indexing strategy
F) Frontend specification: screens for procurement team and department heads
```

---

### PROMPT 4 — Supplier Management

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: Material Master, Warehouse

TODAY'S TASK: Supplier Management module

REQUIREMENTS:
1. Supplier model (code, name, type: local/international, country, status: pending/approved/blacklisted)
2. SupplierContact (name, email, phone, role, is_primary)
3. SupplierCategory (what product categories they supply)
4. SupplierDocument (contract, NDA, catalog, certificate — uses existing file_asset)
5. SupplierEvaluation (periodic score: delivery 0-10, quality 0-10, price 0-10, total_score, evaluated_by, date)
6. SupplierPerformance (auto-calculated from PO history once procurement is built):
   - on_time_delivery_rate, order_count, rejection_rate
7. AI search on: supplier name, category, products, country
8. RBAC: procurement_officer can create/edit suppliers

Please provide:
A) All models
B) All endpoints
C) Performance calculation logic
D) Frontend specification
```

---

### PROMPT 5 — Asset Management

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: Material Master, Warehouse, Procurement, Supplier Management

TODAY'S TASK: Asset Management module
Build the complete equipment registry for the petroleum facility.

REQUIREMENTS:
1. Plant model (top level: Refinery, Platform, Pipeline)
2. AssetSystem model (functional system: Process, Utility, Fire & Gas, Instrument)
   - belongs to Plant
3. Asset model (individual equipment):
   - tag_number (unique, e.g., P-1001 for pump, V-2003 for vessel)
   - name, description
   - asset_type: Rotating / Static / Electrical / Instrument / Civil / Piping
   - criticality: A (critical) / B (important) / C (general)
   - status: Active / Standby / Under Maintenance / Decommissioned
   - manufacturer, model_number, serial_number
   - installation_date, warranty_expiry
   - parent_asset_id (for sub-components, tree structure)
   - belongs to AssetSystem
4. AssetSpecification (JSON key-value pairs per asset type, e.g., pump: flow_rate, head, power)
5. AssetSpare (links Asset to Items in Material Master — spare parts for this asset)
6. AssetDocument (manuals, P&IDs, drawings — uses existing file_asset)
7. AssetHistory (lifecycle events: installed, modified, repaired, replaced — append-only log)
8. AI search: tag_number, name, description, manufacturer, specs
9. RBAC: maintenance_engineer can create/edit, others view

Please provide:
A) All models with complete fields
B) All endpoints (including tree/hierarchy endpoint)
C) How AssetSpare links to Material Master
D) AI search indexing strategy
E) Frontend specification: asset tree view, asset detail page, asset history
```

---

### PROMPT 6 — Work Order Management

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: Material Master, Warehouse, Procurement, Supplier, Asset Management

TODAY'S TASK: Work Order Management module — the core of the CMMS

WORK ORDER TYPES:
- CM (Corrective): something broke, reactive
- PM (Preventive): scheduled, from maintenance plan
- Inspection: periodic inspection
- Modification: engineering change

LIFECYCLE: Draft → Submitted → Approved → Planned → In Progress → Completed → Closed
           (also: Rejected, On Hold from any step after Submitted)

REQUIREMENTS:
1. WorkOrder model:
   - wo_number (auto-generated: WO-2026-0001)
   - type: CM/PM/Inspection/Modification
   - priority: Critical/High/Medium/Low
   - asset_id (links to Asset Management)
   - title, description
   - requested_by (user), assigned_to (user or team)
   - scheduled_start, scheduled_end, actual_start, actual_end
   - status (state machine)
   - source: Manual / PM Schedule (if auto-generated)
   - parent_pm_schedule_id (if from PM)
2. WorkOrderTask (checklist steps on the work order)
3. WorkOrderLabor (who worked: employee/user, date, hours, craft_type)
4. WorkOrderMaterial (items consumed from warehouse):
   - item_id, planned_qty, actual_qty
   - On actual_qty save: creates StockMovement OUT in warehouse
5. WorkOrderFailure (for CM only):
   - failure_code (ISO 14224 taxonomy: mechanical, electrical, instrument, etc.)
   - failure_cause, corrective_action, root_cause
6. WorkOrderAttachment (photos, inspection reports — uses file_asset)
7. Approval: draft → maintenance_supervisor approves → starts
8. Material reservation: before work starts, reserve items in warehouse
9. Auto-calculate: MTTR, downtime hours
10. AI search: asset tag, description, failure code, technician name
11. /work-orders/ask endpoint for manager agent

Please provide:
A) Complete models
B) All endpoints including state machine transitions
C) How material consumption creates StockMovement
D) Failure coding taxonomy
E) Frontend specification: WO list, WO detail, job card print view, KPI widgets
```

---

### PROMPT 7 — Maintenance Planning (PM Schedules)

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: Material Master, Warehouse, Procurement, Asset Management, Work Orders

TODAY'S TASK: Preventive Maintenance Planning module

REQUIREMENTS:
1. MaintenancePlan model:
   - plan_number (auto: MP-2026-001)
   - name, description
   - asset_id (or asset_system_id for grouped)
   - is_active
2. MaintenanceTask (task within a plan):
   - task_name, description
   - craft_type (Mechanical / Electrical / Instrument)
   - estimated_hours
   - required_items (list of items needed from warehouse)
3. TaskTrigger (when to do it):
   - trigger_type: CALENDAR (every N days) or METER (every N hours/km/cycles)
   - frequency_value, frequency_unit
   - last_done_date, last_done_meter_reading
   - next_due_date (calculated)
4. PMSchedule (generated future instances):
   - plan_id, task_id, due_date, status: Pending/Generated/Overdue
   - When status=Pending and due_date approaches: auto-generate WorkOrder
5. InspectionChecklist (checklist template):
   - belongs to MaintenanceTask
   - checklist_items: step number, description, response_type: OK/NOT_OK / Numeric / Text
6. Celery Beat task: daily check of due PM schedules → auto-create WorkOrders
7. AI search: "what PM tasks are due next week for Unit 3?"

Please provide:
A) All models
B) All endpoints
C) Celery Beat task implementation approach
D) How auto-generated WOs differ from manual WOs
E) Frontend specification: maintenance calendar, plan editor, checklist editor
```

---

### PROMPT 8 — Notification & Workflow Engine

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: All Phase 1 & 2 modules above

TODAY'S TASK: Cross-cutting Notification & Workflow Engine

REQUIREMENTS:
1. NotificationTemplate model:
   - event_type (string: "work_order.approved", "stock.below_minimum", "pm.due_soon")
   - title_template, body_template (Jinja2)
   - channels: in_app / email / both
2. Notification model:
   - recipient_id (user)
   - title, body
   - entity_type, entity_id (what this is about)
   - is_read, read_at
   - created_at
3. ApprovalWorkflow model:
   - entity_type (PurchaseOrder, WorkOrder, LeaveRequest, etc.)
   - steps: ordered list of (approver_role, deadline_hours, escalate_to_role)
4. ApprovalInstance (active workflow for one entity):
   - entity_type, entity_id
   - current_step, status
5. ApprovalAction (log of approve/reject per step)
6. Event publishing: every module calls notify_service.publish(event_type, entity)
7. Celery task: process events → create Notification records → send emails

Please provide:
A) All models
B) Notification endpoints (list my notifications, mark read)
C) Event publishing pattern (how other modules call it)
D) Approval workflow state machine
E) Frontend specification: notification bell, notification list, approval inbox
```

---

### PROMPT 9 — Employee & HR Module

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: All Phase 1 & 2 modules

TODAY'S TASK: Human Resources module

REQUIREMENTS:
1. Department model (name, code, parent_department_id for org tree, head_employee_id)
2. Position model (title, department, grade_level, is_management)
3. Employee model:
   - employee_number (auto: EMP-001)
   - first_name, last_name, national_id (hashed/encrypted)
   - date_of_birth, gender, nationality
   - hire_date, contract_type: Permanent/Contract/Secondment
   - department_id, position_id
   - reports_to (manager employee_id)
   - status: Active/On Leave/Terminated
   - user_id (optional link to system user account)
4. LeaveType (Annual, Sick, Emergency, Maternity, Study)
5. LeaveBalance (employee × leave_type × year → balance_days, used_days)
6. LeaveRequest (employee, type, from_date, to_date, reason, status, approved_by)
7. Training model (course name, provider, duration_hours, category)
8. Certification model (name, issuing_body, validity_period_months)
9. EmployeeTraining (employee × training × completion_date × score × certificate_file)
10. EmployeeCertification (employee × cert × issue_date × expiry_date × is_valid)
11. Celery: alert when certifications expire within 30 days
12. AI: "which employees have expired safety certifications?"
13. RBAC: hr_manager full access, department_head sees own department, employee sees own data

Please provide:
A) All models
B) All endpoints including org chart API
C) Certification expiry alert Celery task
D) Frontend specification: employee list, profile page, org chart, leave calendar, training matrix
```

---

### PROMPT 10 — Internal Communication (Letters & Messaging)

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: All Phase 1, 2, and 3 modules

TODAY'S TASK: Internal Communication module

REQUIREMENTS:
1. Letter model (formal internal correspondence):
   - letter_number (auto per year: MAINT-2026-001, HR-2026-045)
   - letter_type: Memo / Formal Letter / Circular / Report / Request
   - subject, body (rich text)
   - from_department, from_employee
   - to_department, to_employee (can be multiple)
   - cc list
   - priority: Normal / Urgent / Confidential
   - status: Draft / Sent / Acknowledged / Archived
   - sent_at, acknowledged_at
2. LetterAttachment (uses file_asset)
3. LetterComment (reply/note on a letter)
4. Announcement model:
   - title, body
   - target_audience: All / Specific Departments / Specific Roles
   - published_by, published_at, expires_at
   - is_pinned
5. InternalMessage (direct messaging, thread-based):
   - Thread model (participants list)
   - Message model (sender, thread, body, sent_at, is_read)
6. All letters indexed in semantic search
7. AI: "find all letters about asset P-1001" / "show urgent memos from last month"
8. Number series: configurable prefix per letter_type

Please provide:
A) All models
B) All endpoints
C) Letter numbering logic
D) Search and AI indexing
E) Frontend specification: letter inbox, compose letter, announcement board, direct messages
```

---

### PROMPT 11 — HSE Module

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: All previous modules

TODAY'S TASK: HSE (Health, Safety, Environment) module

REQUIREMENTS:
1. Incident model:
   - incident_number (auto: INC-2026-001)
   - incident_type: Near Miss / First Aid / Medical Treatment / Lost Time / Fatality / Environmental / Property Damage
   - severity: Low / Medium / High / Critical
   - location, occurred_at, reported_by, reported_at
   - description, immediate_action_taken
   - injured_employee_id (optional)
   - status: Reported / Under Investigation / Closed
2. IncidentInvestigation (root cause analysis):
   - immediate_cause, root_cause, contributing_factors
   - corrective_actions (list)
   - action_owner, action_due_date
3. PermitToWork (PTW):
   - permit_number (auto: PTW-2026-001)
   - permit_type: Hot Work / Confined Space / Electrical Isolation / Working at Height / Cold Work / Excavation
   - work_order_id (optional link: WO cannot start without valid PTW)
   - location, description_of_work
   - valid_from, valid_to
   - issuer (safety officer), receiver (technician supervisor)
   - status: Draft / Pending Approval / Active / Suspended / Closed / Cancelled
   - isolation_points (list of what was isolated)
   - JSA_attached (Job Safety Analysis document)
4. PTWChecklistItem (pre-work checks that must all be completed)
5. RiskAssessment:
   - hazard, likelihood (1-5), severity (1-5), risk_score (calculated)
   - control_measures, residual_risk_score
6. SafetyObservation (anyone can report):
   - type: Positive / Unsafe Act / Unsafe Condition
   - location, description, photo
   - reported_by
7. HSEStatistic (auto-calculated weekly/monthly):
   - man_hours_worked, LTI_count, TRIR, LTIR, near_miss_count
8. RBAC: hse_officer manages PTW and incidents, anyone can submit observations
9. PTW gate on Work Orders: check if valid PTW exists before WO can go to In Progress

Please provide:
A) All models
B) All endpoints
C) PTW-WorkOrder integration
D) TRIR/LTIR calculation logic
E) Frontend specification: incident form, PTW issue screen, safety observation wall, HSE dashboard
```

---

### PROMPT 12 — AI Manager Agent

```
PROJECT CONTEXT:
[Same as Prompt 1]

WHAT IS ALREADY BUILT: ALL modules across all phases are implemented.

TODAY'S TASK: AI Manager Agent — cross-module natural language query system

ARCHITECTURE:
The existing system has: core/agents/ skeleton, core/semantic_ask.py, per-module /ask endpoints.
We now build a unified agent that routes questions to the right modules and synthesizes answers.

REQUIREMENTS:
1. AgentTool registry (each module registers what questions it can answer):
   - tool_name: "warehouse_inventory" / "work_orders" / "assets" / "procurement" / "employees" / etc.
   - description (used by LLM to decide which tool to call)
   - endpoint_path (the module's /ask endpoint)
2. AgentSession model (conversation history for manager):
   - session_id, user_id, messages (JSON array), created_at
3. Agent orchestration (POST /agent/ask):
   - Input: user question + session_id (for context)
   - Step 1: LLM determines which tools to call (function calling)
   - Step 2: Call each relevant module's /ask endpoint
   - Step 3: Synthesize results + cite sources (module + entity IDs)
   - Step 4: Return answer + source list + session updated
4. Manager Dashboard aggregation endpoint (GET /agent/dashboard):
   - Calls all modules for their "current status" summary
   - Returns: open WO count, stock alerts count, pending POs, incidents this month, employees on leave
5. Report generation: agent can format answer as structured report
6. RBAC: only managers and above can use the agent
7. Audit: every agent query is logged (who asked what, what was returned)

Please provide:
A) Agent architecture (how tools are registered and called)
B) All models
C) All endpoints
D) LLM prompt template for tool selection
E) How each module's /ask endpoint should be structured for agent compatibility
F) Frontend specification: manager chat interface, dashboard overview, report generation
```

---

## 9. Frontend Specification Format

After each backend implementation, provide the frontend team with this structure:

```
FRONTEND SPEC — [Module Name]

SCREENS:
  1. [Screen Name]
     - Route: /module/screen
     - Access: roles that can see this
     - Purpose: what the user does here
     - Key components:
       • [Component]: what it shows/does
     - API calls:
       • GET /endpoint → what it returns
       • POST /endpoint → what it creates
     - States: loading / empty / error / filled

FORMS:
  1. [Form Name]
     - Trigger: when/how opened
     - Fields: field name (type, required/optional, validation)
     - Submit: which endpoint, success/error behavior

WIDGETS/REUSABLE COMPONENTS:
  - Component name: what it is, what props it takes, which screens use it
```

---

## 10. Naming Conventions (Follow Always)

| Concern | Convention | Example |
|---|---|---|
| App folder | snake_case | `warehouse_management/` |
| Model class | PascalCase | `StockMovement` |
| DB table | snake_case plural | `stock_movements` |
| API route | kebab-case | `/stock-movements` |
| Pydantic schema | PascalCase + suffix | `StockMovementCreate`, `StockMovementRead` |
| Service function | snake_case verb_noun | `create_stock_movement()` |
| Permission name | `module:action` | `warehouse:create_movement` |
| Number series | MODULE-YEAR-NNNN | `WO-2026-0042` |

---

## 11. Quick Reference: What Each Role Can Do

| Role | Phase 1 Access | Phase 2 Access | Phase 3 Access | Phase 4 Access |
|---|---|---|---|---|
| `system_admin` | Full | Full | Full | Full |
| `general_manager` | View + Reports | View + Reports | View + Reports | Full + Agent |
| `procurement_officer` | Full Procurement | View Assets | - | Letters |
| `warehouse_keeper` | Full Warehouse | View Materials | - | Letters |
| `maintenance_engineer` | View Materials + Issue Stock | Full WO + Assets | - | Letters + PTW |
| `maintenance_planner` | View Materials | Full PM Plans | - | Letters |
| `hr_manager` | - | - | Full HR | Letters |
| `hse_officer` | - | View WO | - | Full HSE |
| `department_head` | View Procurement | View WO | View Dept HR + Approve Leave | Letters |
| `employee` | - | - | Own data + Leave | View Announcements |
