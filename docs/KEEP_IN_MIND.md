# Keep In Mind — Schema, Migrations, RBAC & Deployment

This is the project's "don't get burned again" guide. It captures real problems we
hit and the rules that prevent them. **Read this before adding a model, writing a
migration, changing RBAC, or deploying to an existing database.** It is also meant
to be loaded into AI/Claude context — when you ask an AI to add a model or a new
module, point it here first.

---

## TL;DR — Golden rules

1. **Alembic owns the schema. Nothing creates tables at runtime.** Never call
   `Base.metadata.create_all()` in request code or app startup. The only way a
   table gets created is an Alembic migration.
2. **Every model must be imported in `backend/Models/__init__.py`.** If it isn't,
   Alembic autogenerate can't see it and silently leaves the table out of the
   migration (this is how `currencies`, `exchange_rates`, and all `purchase_*`
   tables went missing).
3. **Declare each index/constraint exactly once.** Do not combine column-level
   `index=True`/`unique=True` with an explicit `Index(...)`/`UniqueConstraint(...)`
   of the same name. That produces `relation "ix_..." already exists`.
4. **Authorization = RBAC permissions, not the legacy `users.role` column.** Adding
   an endpoint with `require_permission("x:y")` means you must add `"x:y"` to
   `seed_rbac.py`, or even admins get 403.
5. **Never run `alembic upgrade head` against a DB that already has the schema.**
   Use `alembic stamp` instead. Editing an already-applied migration does NOT
   re-run it.
6. **Circular foreign keys must be deferred** in migrations (create tables without
   the back-reference, then `op.create_foreign_key` after both exist).
7. **AI assistant work has its own rules.** The agent calls services not its own HTTP
   routes, runs with exactly the caller's RBAC (never more), commits writes only via
   draft-and-confirm, raises only catalogued errors, and ships with full tests. See the
   "AI Assistant Backbone" section below and Section 12 of the Master Plan before touching it.

---

## Adding a new model / table (do this every time)

1. Define the model under its module (e.g. `purchase_management/models.py`), using
   `from db.base import Base`.
2. **Register it for Alembic**: import the model classes in `backend/Models/__init__.py`.
   `alembic/env.py` builds `target_metadata` from `import Models` only — anything
   not reachable from there is invisible to autogenerate. (Importing it in a router
   makes it work at runtime but NOT in migrations — that mismatch is the bug that
   bit us repeatedly.)
3. Generate the migration: `alembic revision --autogenerate -m "add <thing>"`.
4. **Review the generated migration by hand** for: table ordering vs. foreign keys,
   circular FKs, duplicate indexes, and `pgvector` columns (see below).
5. Run `alembic upgrade head` on a *fresh* DB and confirm it applies cleanly.
6. If the model needs access control, add its permissions to `seed_rbac.py`
   (see RBAC section).
7. Run `alembic check` to confirm models and DB are in sync (no drift).

---

## Migration authoring rules

- **Dependency order.** Create root tables (no FKs) first, leaf tables last. A
  table referenced by a FK must already exist when the referencing table is created.
- **Circular FK pairs** (in this codebase: `users ↔ file_assets`,
  `documents ↔ document_versions`). Pattern:
  1. create table A without the FK to B,
  2. create table B (with its FK to A),
  3. `op.create_foreign_key(...)` to add A→B after both exist.
  In `downgrade()`, drop the deferred constraint **before** dropping the table it
  points to, and drop tables in reverse dependency order.
- **pgvector columns** need `import pgvector.sqlalchemy` at the top of the migration
  file, and are written as `pgvector.sqlalchemy.Vector(dim=1024)`. The DB needs the
  extension: `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`.
- **Naming convention** is defined in `backend/db/base.py` (`ix_`, `uq_`, `fk_`,
  `pk_`, `ck_`). Hand-written migrations must use the same names autogenerate would
  produce, so the schema stays consistent and `alembic check` passes.
- **Module isolation by design**: some "foreign keys" are deliberately plain
  `Integer` columns with no FK (e.g. `purchase_order_receipt_links.financial_receipt_id`,
  `purchase_orders.supplier_id`). This keeps modules decoupled; integrity is enforced
  in application code. Don't "fix" these into real FKs without understanding the intent.

---

## Schema ownership (no runtime DDL)

- `Base.metadata.create_all()` must never run in the request path or at startup.
  It previously lived in `db/init_db.get_db()` and ran on **every request**, which
  (a) was slow, (b) split schema ownership between Alembic and runtime, and (c)
  masked the missing-table bugs because it silently created what migrations forgot.
- `get_db` is the canonical session dependency in `db/session.py`; `db/init_db.py`
  re-exports it. Data seeding (default admin user) happens once at startup, not
  per request.

---

## RBAC & permissions

- Access is checked by `deps.require_permission("resource:action")`, which flattens
  `user.roles → role.permissions`. The legacy `users.role` text column is **cosmetic
  for authorization** — it is NOT consulted by `require_permission`. A user can show
  `role="admin"` and still have zero access if they have no `user_role` link or the
  linked role has no permissions.
- **When you add/rename an endpoint permission**, update `seed_rbac.py`:
  - add the permission string to `permissions_data` (so the row exists),
  - the admin role automatically receives the full set,
  - grant it to other roles via the admin RBAC API at runtime (the seed only sets
    the `user` role's defaults on first creation, so admin-managed assignments are
    not overwritten on restart).
- **Renames are dangerous**: when `buying_management` became `purchase_management`,
  the permission strings changed in the routes but not in the seed, so every purchase
  endpoint returned 403. If you rename a module/resource, grep for the old permission
  prefix across `routes/`, `seed_rbac.py`, and the frontend.
- A user must be **linked to a role** (`user_role`) to have any permission. Setting
  only `users.role="admin"` does nothing. `seed_default_user()` now attaches the
  system admin role for this reason.

---

## Deploying / migrating an existing database

- **Fresh/empty DB** → `alembic upgrade head` (creates everything).
- **DB that already has the schema** (e.g. prod, or a DB built before a squash) →
  `alembic stamp --purge head`. This only writes the revision row; it runs no DDL.
  Running `upgrade` here causes `relation "..." already exists` and crashes the
  container (entrypoint runs `alembic upgrade head` on every boot).
- **Editing an already-applied migration does not re-run it.** If you add tables to
  a migration whose revision is already recorded, existing DBs won't get them. Your
  options: recreate the DB (fresh deploys/new servers), or ship a *new* follow-up
  migration — but a follow-up that `CREATE`s tables will collide on any DB that
  already has them, so stamp those.
- One-off commands without triggering the entrypoint's `upgrade`:
  `docker compose run --rm backend alembic stamp --purge head`
  (the Dockerfile uses `CMD`, so `run` replaces it cleanly).
- `psql` inside the container: pass `-U <user> -d <db>` explicitly, or wrap in
  `sh -c '... "$POSTGRES_USER" ...'`. Host shells don't have the `.env` vars, so a
  bare `-U "$POSTGRES_USER"` resolves to the OS user (`root`) and fails.

---

## Config / environment

- `base_url` must include the scheme and no trailing slash
  (`https://host`), because it's used to build absolute URLs
  (`f"{base_url}/{doc_id}/images/..."`). A bare hostname produces broken links.
- `cors_allow_origins` is a `List[str]` parsed from `.env` as JSON. Each entry must
  be a full origin with scheme and (if needed) port, no path, e.g.
  `["https://app.example.com","http://127.0.0.1:8001"]`. These should be the
  **frontend** origins that call the API in a browser — not the API's own domain.

---

## Most important problems in the current code (tech debt to address)

Ordered roughly by impact:

1. **Incomplete model registration for Alembic.** `Models/__init__.py` does not
   import `shared.currency.models` or `purchase_management.models`; they only get
   registered via router imports at runtime. This is the root cause of the missing
   tables. **Fix:** import every model module centrally so autogenerate + `alembic
   check` see the whole schema. Add `alembic check` to CI.
2. **Hardcoded secret in version control.** `docker-compose.yml` (the `celery`
   service) contains a literal `POSTGRES_PASSWORD`. **Fix:** remove it, source from
   `.env`, and rotate the credential since it has been committed.
3. **Default/weak seeded credentials.** `seed_rbac.py` creates `admin/admin123` and
   `user1/user123`. **Fix:** drive these from env and/or force a password change on
   first login; never ship fixed admin passwords to production.
4. **Duplicate index declarations** were present in several models (`currencies`,
   `purchase_orders`, `purchase_phases`). Audit remaining models for column
   `index=True`/`unique=True` that overlaps an explicit `__table_args__` entry.
5. **Schema was historically split between Alembic and `create_all`.** Now fixed,
   but verify no other code path calls `create_all` (tests included) against a
   migration-managed DB.
6. **Dead code on disk.** `buying_management/` was removed from imports but the
   folder remains, which confuses greps and autogenerate-style tooling. **Fix:**
   delete it.
7. **Deprecated FastAPI startup hooks.** `api.py` uses `@app.on_event("startup")`
   (deprecated). Migrate to the `lifespan` context manager when convenient.
8. **`docker-compose.yml` declares an obsolete `version:` key** — remove it to
   silence the warning.

---

## When prompting an AI to add a model or module — checklist to include

Tell the assistant explicitly:

- "Register the new model in `backend/Models/__init__.py` so Alembic sees it."
- "Generate an Alembic migration and verify table creation order, circular FKs,
  duplicate indexes, and `pgvector` import; do not rely on `create_all`."
- "If the feature has protected endpoints, add the permission strings to
  `seed_rbac.py` and confirm the admin role gets them."
- "Keep cross-module references as plain integer columns where the existing modules
  do (module isolation); don't add cross-module FKs without checking the pattern."
- "Match the naming convention in `db/base.py` for all constraints/indexes."
- "Don't put DDL in request/startup code. Don't hardcode secrets."
- "After changes, run `alembic upgrade head` on a fresh DB and `alembic check`."

---

## AI Assistant Backbone (Section 12 of the Master Plan) — don't get burned

The chat page is the system's primary interface and is built as a stateful agent
(`backend/assistant/`). The full spec is **Section 12 of `CMMS_MASTER_PLAN.md`** —
read it before touching the assistant. The rules below are the ones that bite.

### New tables — register them or Alembic skips them

The Assistant Core and related work introduce new models. **Every one must be imported
in `backend/Models/__init__.py`** (same bug that lost `currencies`/`purchase_*`):

- `AgentRun` (agent run-state / status / plan — Section 12.8)
- `Draft` (draft-and-confirm payloads — Section 12.5)
- `TagMetadataField` + the `Tag.metadata` JSONB column (Section 12.10)
- any audit/usage tables added for agent actions and LLM usage (Sections 12.18, 12.20)

The LangGraph Postgres **checkpointer** also creates tables — make sure their creation
is owned by Alembic (or the library's documented migration), never by runtime DDL
(`create_all` is still banned everywhere).

### The agent calls services, NOT its own HTTP routes

- The agent reaches modules through **in-process service-function calls** via each
  module's `assistant_tools.py` adapter — never by making HTTP requests to our own
  routes (loopback HTTP), and never via a duplicated AI-only function layer. This is
  Master Plan Rule 2 + Section 12.4.1.
- If logic lives inside a route handler, push it down into a service function so both
  the route and the tool set call the same code.
- HTTP between modules is only correct **after** a module becomes its own microservice.

### Agent access == the caller's access (never more)

- The agent always runs as `current_user`. It is **not** a privileged service account.
- The route's `require_permission` dependency is bypassed when the agent calls a service
  directly, so the adapter **must** re-check permissions itself (`has_permission` /
  `get_user_permissions`) before any action, and **again at draft confirm time**.
- Reads are scoped to the user/company too. In group chat (Phase 5) each participant
  acts under their own permissions — never leak one user's restricted data to another.

### Drafts are central; modules stay thin

- The `Draft` table + lifecycle (create/edit/confirm/cancel/persist/resume) live in
  `backend/assistant/`. Each module only ships a thin `assistant_tools.py` adapter
  (`search`/`summarize`/`ask`/`add_draft`/`commit_draft`). Don't reinvent draft storage
  per module.

### Ingested content is data, never instructions

- Text from uploaded PDFs/photos or retrieved docs is reference material only. Never let
  instructions found inside a file drive a tool call, and **never auto-commit a write**
  from file contents — a human confirms every draft (Section 12.19).

### Errors: only catalogued codes

- `core/exceptions/error_codes.py` is the single source of truth. New routes/tools raise
  only **catalogued** `AppException` codes (never bare `HTTPException` with ad-hoc text);
  `INTERNAL_SERVER_ERROR` is the only uncatalogued case. The catalog auto-exports to
  `docs/frontend-error-codes.md` + a machine-readable `errors.json` (`GET /errors/catalog`).
  CI should fail on an uncatalogued raise (Section 12.9).

### Logging (Phase 0.5 / Section 4.5) is separate from the Audit Log

- Application logging = structured JSON, levels driven by env, `request_id` propagated
  across web **and** Celery, with `user_id`/`company_id`/route/latency context. **No
  secrets/PII** in logs. Replace ad-hoc `print()` and the loose `logs/` usage with the
  central logger. This is technical logging — distinct from the business Audit Log
  (who-changed-what).

### Tests are required, not optional (Section 12.12)

- Every AI track ships: unit tests with the **LLM mocked** (deterministic), route
  integration tests (incl. RBAC 403 → `PERMISSION_DENIED` and catalogued errors), and
  agent end-to-end tests (intent routing, draft→confirm, draft→cancel, interruption
  pause/resume, resume-after-restart, multilingual). Both the LangGraph layer and the
  backend routes must be covered. CI runs `pytest` + `alembic check`.
