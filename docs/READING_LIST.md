# Reading List — Understanding This System by Phase

> A domain + architecture reading guide, mapped to the delivery phases in `CMMS_MASTER_PLAN.md` (§3).
> There is **no single book** for the whole platform — it spans procurement, inventory, maintenance, HR,
> safety, finance, and an AI assistant — so this lists the canonical reference per area, plus one ERP
> overview that ties the breadth together. ⭐ marks the top pick in each group.

---

## Start here — one book for the whole breadth

- ⭐ **"Concepts in Enterprise Resource Planning"** — Monk & Wagner.
  The best single overview of how procurement, inventory, finance, HR, and reporting fit together as one
  integrated system. Read this to understand *why* the platform is split into these phases at all.

---

## Building it well — the software architecture (cross-cutting, all phases)

These explain the modular-monolith / clean-seam rules in `AGENTS.md` and master plan §0.5.

- ⭐ **"Architecture Patterns with Python"** (*Cosmic Python*) — Percival & Gregory.
  DDD + repository + service layer + domain events in this exact FastAPI/SQLAlchemy style. The modules,
  service functions, and Celery events map almost 1:1 to this book. **Read this first for the code side.**
- **"Domain-Driven Design"** — Eric Evans (or the lighter **"Implementing DDD"** — Vaughn Vernon).
  Your "modules with clean seams" *are* bounded contexts; this is the theory behind no-cross-module-imports.
- **"Designing Data-Intensive Applications"** — Martin Kleppmann.
  The idempotency, locking, and consistency concerns in the stock/movement code (unique constraints,
  `with_for_update`, advisory locks) are covered here.
- **"Monolith to Microservices"** — Sam Newman.
  The "modular monolith, extractable later" goal and the §0.5 extraction recipe come straight from here.
- **"Patterns of Enterprise Application Architecture"** — Martin Fowler.
  The pattern catalog behind this codebase, incl. the **Money pattern** (your 4-column money rule, Phase 0.3).
- **"Enterprise Integration Patterns"** — Hohpe & Woolf.
  The Celery cross-module event backbone (and Phase 5 messaging) as messaging patterns.

---

## Phase 0 / 1 — Foundation, Purchase, Warehouse, Material Master, Supplier

The procure-to-pay + inventory core.

- ⭐ **"Introduction to Materials Management"** — Arnold, Chapman, Clive.
  Requisitions, purchasing, inventory, warehousing, MRP. Closest match to the buy-and-stock flow.
- **"Purchasing and Supply Chain Management"** — Monczka et al.
  The procure-to-pay cycle, **three-way match**, supplier sourcing, and the financial controls.
- The **APICS / ASCM CPIM** body of knowledge — the dictionary for every term in this domain.
- Money handling (Phase 0.3 multi-currency): the **Money pattern** in Fowler's *PoEAA* (above).

---

## Phase 2 — Maintenance & Admin (Asset, Work Order, Maintenance Planning, Fault Reporting, KPIs)

The actual **CMMS core** — most important for this product.

- ⭐ **"Maintenance Planning and Scheduling Handbook"** — Doc Palmer.
  The standard for work orders + PM schedules (Modules 2.2, 2.3).
- **"Reliability-Centred Maintenance II"** — John Moubray.
  *Why* PM plans, failure codes, and maintenance strategy look the way they do.
- **"Uptime: Strategies for Excellence in Maintenance Management"** — Campbell & Reyes-Picknell.
  Ties asset management + KPIs together (Modules 2.1, 2.6).
- **ISO 55000** — asset management as a formal discipline.

---

## Phase 3 — Human Resources (Employee, Leave, Training & Certification)

- ⭐ **"Human Resource Management"** — Gary Dessler.
  The standard intro to the HR processes being modeled.
- **"Human Resource Information Systems"** — Kavanagh & Johnson.
  The *systems* angle — building HR as software, which is what this phase is.

---

## Phase 4 — Full Platform (HSE Module, Permit-to-Work, Internal Comms, AI Manager)

Petroleum-specific, so HSE is heavy and domain-specific.

- ⭐ **"Lees' Loss Prevention in the Process Industries"** — the bible for process/petroleum safety:
  incidents, risk assessment, permits. Large but canonical for this industry.
- **"Guidelines for Risk Based Process Safety"** — CCPS (AIChE).
- **UK HSE HSG250, "Guidance on permit-to-work systems"** (free PDF) — directly matches the
  fault → permit → dual-approval workflow (Module 4.2 / the Phase 4 permit gate on work orders).

---

## Cross-cutting — the AI Assistant track (Phase 0-AI + every phase's thin AI track)

The RAG + LangGraph agent is the system's primary interface (`AGENTS.md`, master plan §12). Go deep here.

- ⭐ **"AI Engineering"** — Chip Huyen (2025).
  The current best book on RAG, agents, tool use, and evaluating/deploying LLM systems in production.
  Maps directly to the `backend/assistant/` design (router, tools, drafts, streaming).
- **"Natural Language Processing with Transformers"** — Tunstall, von Werra, Wolf.
  The embeddings/transformer foundation under the pgvector semantic search.

---

## Suggested order for this product

1. **Concepts in ERP** (breadth — how it all fits).
2. **Architecture Patterns with Python** (how to build it with clean seams).
3. **Introduction to Materials Management** (the Phase 0/1 buy-and-stock core you're in now).
4. **Doc Palmer — Maintenance Planning & Scheduling** (the CMMS heart, Phase 2).
5. **Chip Huyen — AI Engineering** (the assistant, the product's primary interface).

HR/HSE books (Phases 3–4) are reference material to pull in when you actually reach those phases.
