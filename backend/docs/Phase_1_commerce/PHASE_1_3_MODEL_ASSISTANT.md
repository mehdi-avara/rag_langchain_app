# Phase 1.3 — Equipment Model Assistant

Phase 1.3 registers `model_management` with the unified assistant using the
same configured, draft-only pattern as material and supplier management.

## Capabilities

- `search_models` and grounded `ask_models`
- `add_model` draft: requires `manufacturer` and `model`; optionally accepts
  `description` and `type`
- `update_model` draft for an existing numeric model ID
- `managed_model` reference resolution for material-item drafts

Writes are never committed by chat. The frontend submits a reviewed draft to
`POST /models/` or `PATCH /models/{id}`, where the existing `models:create` or
`models:update` permission and model-management validation are applied.

No schema migration or new RBAC permission is required.
