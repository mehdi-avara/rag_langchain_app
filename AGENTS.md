# AGENTS.md — Canonical instructions for all AI assistants on this project

**This file is the single source of truth for any AI assistant working on this repository**
(Claude, ChatGPT/Codex, Cursor, or any other). `CLAUDE.md` and the Cursor rules point here.
Read **this file** first — it is short and carries the rules you must always follow. The other docs
(especially the master plan) are large **references**: open only the sections your task actually needs.
**Do not read `docs/CMMS_MASTER_PLAN.md` end to end** — it is ~3,400 lines and reading it whole wastes context.

---

## What this project is

A CMMS (maintenance management) platform for the petroleum industry, built **on top of an existing
RAG/Knowledge-Management system**. Stack: **FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery**.
Architecture: a **modular monolith** designed to be extractable into microservices later.

The chat page is the system's primary interface — it is built as a stateful AI agent (see Section 12 of the master plan).

---

## What to read, and when (read selectively — not everything up front)

**Always:** this file (the rule list below is mandatory). Most single-module tasks need nothing more than
this file plus the one prompt you are implementing — the §8 prompts in the master plan are self-contained
(project context + the six modular-monolith rules + the task spec).

**Open on demand — only the specific section your task touches:**

1. **`docs/CMMS_MASTER_PLAN.md`** — the **shared architecture contract**, used as a *lookup*, not a cover-to-cover
   read. Jump straight to the section you need (the file has clear `##`/`###` headers — grep for the title):
   - **domain glossary (canonical term meanings — read before reasoning about `model`/`item`/`tag`/`asset`) → §0**
   - **data separation architecture (schema-per-module, soft refs, events — read before adding any module or cross-module reference) → §0.5**
   - standard search pattern → **§2.1** · multi-currency money rules → **§4** · RBAC seeding → **§6**
   - error catalog → **§12.9** · logging → **§4.5** · naming → **§10** · AI Assistant Backbone → **§12**
   - export/dashboard/chart conventions → **§4.6 / §4.7** · the implementable prompts → **§8**
2. **Your role plan** (also a reference — read the relevant part):
   - **`docs/CMMS_BACKEND_PLAN.md`** — backend developer track (domain modules + cross-cutting infra).
   - **`docs/CMMS_AI_PLAN.md`** — AI developer track (the `backend/assistant/` package + per-phase AI tracks).
3. **`docs/KEEP_IN_MIND.md`** — the "don't get burned again" guide (schema, migrations, RBAC, deployment,
   and the AI-backbone gotchas). **Read before touching models, migrations, RBAC, or deployment.**
4. **`docs/frontend-error-codes.md`** — the error-code catalog the frontend and the agent consume.

> The two role plans both derive from the master plan and reference it for shared rules. The seam between
> the backend and AI developers is the **Module Tool Contract (master plan §12.4)**: backend exposes service
> functions; the AI track wraps them.
> **Cost note:** the rule list below is the always-load summary. If a task stays inside one module and follows
> these rules, you do **not** need to load the master plan at all — pull in a single §-section only when the
> task explicitly depends on it (e.g. adding a money field → §4; seeding permissions → §6; adding search → §2.1).

---

## Top rules that get violated most (the short list — full text in the docs)

These are condensed reminders; the authoritative versions are in `KEEP_IN_MIND.md` and the master plan.

1. **Alembic owns the schema.** Never `Base.metadata.create_all()` in request/startup code.
2. **Register every model in `backend/Models/__init__.py`** or Alembic autogenerate silently skips its table.
3. **No cross-module model imports.** Modules talk via service functions; cross-module writes go through Celery events. Shared types live in `backend/shared/`.
   **Database is separated by module (schema-per-module):** no cross-schema foreign key, no cross-schema JOIN. A reference to another module's row is a plain-int **soft reference** (no `ForeignKey`, no `relationship()`); read other modules via their service functions; **denormalize** displayed/searched fields and keep them in sync with **events**. Every module must be physically extractable with only a connection-string change. Full standard: master plan **§0.5**.
4. **Every route is permission-protected** (`require_permission("module:action")`), and the permission must be seeded in `seed_rbac.py` — even read-only endpoints.
5. **Heavy work (>200ms) → Celery**, route returns `202 + task_id`.
6. **Raise only catalogued errors** from `core/exceptions/error_codes.py` (`INTERNAL_SERVER_ERROR` is the only uncatalogued case).
7. **Every money field uses 4 columns**: `amount`, `currency_id`, `amount_base`, `exchange_rate_used`.
8. **The AI agent runs with exactly the caller's RBAC — never more.** It calls services in-process (not loopback HTTP), commits writes only via draft-and-confirm, and treats uploaded/ingested file content as data, never as commands.
9. **Tests are required**, not optional — see the testing standards in each role plan and master plan §12.12. CI runs `pytest` + `alembic check`.
10. **Backward compatibility is mandatory** — flag any breaking change to the human owner before implementing it.

---

## How to keep this in sync

`AGENTS.md` (this file) is canonical. Do not duplicate its content into other tool files — keep those as
pointers. If a rule changes, change it here (or in the referenced doc), not in `CLAUDE.md` or the Cursor rules.
