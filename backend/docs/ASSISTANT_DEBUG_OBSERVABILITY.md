# Assistant debugging and observability

## Execution hierarchy

The persisted hierarchy is:

`Chat → ChatMessage (user) → AgentRun → AssistantEvent* → ChatMessage (assistant)`

One user message starts one `AgentRun`. `input_message_id` identifies that user
message and `output_message_id` is filled after the final assistant message is
persisted. A chat can therefore contain many independent runs without mixing
their timelines. `AgentRun.state` remains only the latest redacted recovery
snapshot; the append-only `AssistantEvent` rows are the execution history.

## Stages and event types

The standard stages are `chat`, `run`, `module_router`, `task_finder`,
`executor`, `validator`, and `answer`. The core records:

- run lifecycle: `chat.started`, `run.started`, `run.completed`, `run.failed`;
- routing: `module_router.*`, `task_finder.*`;
- execution: `executor.*`, `tool.*`, `cross_module_search.*`;
- model calls: `model.started`, `model.completed`, `model.failed`;
- drafts/validation: `draft.created`, `draft.persisted`,
  `partial_draft.created`, `validator.*`;
- output: `answer.started`, `answer.completed`.

Sequences are local to a run. They are allocated by an atomic update of
`AgentRun.last_event_sequence`, so concurrent model/tool completions cannot
receive the same sequence.

## Recording module activity

Domain code should not write `AssistantEvent` rows directly. Assistant adapters
call `assistant.observability.record_tool_call()` for module operations,
`record_route()` for a routing choice, or `record_event()` for a bounded custom
event. Put module-specific fields inside `payload`; keep the top-level stage,
status, module, task, route, duration, and error fields generic. A cross-module
fan-out emits `cross_module_search.started` and `.completed` and identifies only
safe module/resource identifiers.

No event update/delete API exists. Corrections are represented by a later event.

## Privacy rules

Never record raw prompts, hidden model reasoning, authorization/cookie headers,
passwords, tokens, API keys, credentials, request/session objects, file binaries,
complete uploaded/OCR text, or unbounded service responses. All payloads and run
snapshots pass through `assistant.redaction`; sensitive keys and inline secrets
are redacted, non-JSON objects become type metadata, collections are bounded,
and oversized payloads become size/count/key metadata. Limits are configured by
`assistant_event_payload_max_bytes`, `assistant_event_preview_chars`, and
`assistant_state_snapshot_max_bytes`.

## Frontend contract

Debug endpoints require `assistant:debug` and scope every query to the caller's
company. `/assistant/debug/chats/{id}` returns ordered messages plus the distinct
run associated with each initiating user message. Timeline items use the generic
shape `kind`, `event_type`, `stage`, `module`, `task`, `title`, `summary`,
`status`, `severity`, `duration_ms`, `data`, and `created_at`. Module-specific
rendering is optional because specialized data lives only in `data`.

For long or active runs, poll
`/assistant/debug/runs/{run_id}/events?after_sequence=N&limit=100`. The response's
`next_after_sequence` is the next cursor. Chat-level timelines remain grouped by
run and are never flattened across user messages.

For live screens, `/assistant/debug/chats/{chat_id}/stream?after_event_id=N`
provides an SSE tail with heartbeats. Each streamed item still carries
`agent_run_id` and its run-local `sequence`; reconnect with the last event id.

## Adding a model provider

Provider adapters should supply the configured provider/model identifier, attempt
number, token counts when returned, prompt version, SHA-256 prompt hash, response
format/schema name, duration, and catalogued error code. Raw prompts and raw model
responses are not stored. Different router, task-finder, executor, vision, and
answer models may report independent metadata on the same run.
