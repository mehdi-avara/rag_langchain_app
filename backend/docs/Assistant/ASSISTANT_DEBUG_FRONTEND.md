# Assistant debug UI integration

## Purpose and access

The assistant debug API exposes how one assistant response was produced without
exposing private model reasoning, raw prompts, credentials, or uploaded file
contents. All endpoints use the `/assistant/debug` base path, require a Bearer
access token, and require the `assistant:debug` permission. The backend always
applies the authenticated user's company scope.

The frontend should hide the debug entry point when the current user does not
have `assistant:debug`. A `401` means the access token is missing or invalid; a
`403` means the user lacks the permission. Treat a company-scoped `404` as not
accessible and do not try to distinguish it from an ID belonging to another
company.

## Data hierarchy

Render the data using this relationship:

```text
Chat
  ├─ user message
  │    └─ AgentRun
  │         ├─ ordered timeline events
  │         ├─ routing decisions
  │         ├─ drafts and validation
  │         └─ output assistant message
  ├─ assistant message
  └─ next user message
       └─ a different AgentRun
```

One user message starts one run. Join a run to its initiating message using
`run.input_message_id`, and to the resulting assistant message using
`run.output_message_id`. Never combine events merely because they share a
`chat_id`: event `sequence` starts independently for every run.

`AgentRun.state` is only the latest recoverable snapshot. It is useful for a
collapsed “Current state” JSON panel, but it is not the history. The ordered
`timeline` is the execution history.

## Recommended initial request

Open the debug screen with:

```http
GET /assistant/debug/chats/{chat_id}?message_limit=100&run_limit=50&event_limit=100
Authorization: Bearer <access-token>
```

The response contains:

- `chat`: chat metadata;
- `messages`: ordered messages, each shaped as `{ message, run }`; `run` is
  present on the initiating user message when an associated run exists;
- `runs`: the runs returned for the chat;
- `unassociated_runs`: legacy runs that could not safely be linked to an old
  input message.

This response is enough to build the initial screen. A useful layout is the
conversation on the left and the selected user message's run details on the
right. Selecting an assistant message should select the run whose
`output_message_id` matches that message, when one exists.

For large conversations, retrieve messages separately with:

```http
GET /assistant/debug/chats/{chat_id}/messages?offset=0&limit=100
```

## Run and timeline endpoints

| Endpoint | Frontend use |
| --- | --- |
| `GET /assistant/debug/messages/{message_id}/run` | Load the run initiated by one user message. |
| `GET /assistant/debug/runs/{run_id}` | Load one run, its timeline, routes, drafts, errors, state summary, and final output. `event_limit` is 1–200. |
| `GET /assistant/debug/runs/{run_id}/events` | Incrementally retrieve ordered events for an active or large run. |
| `GET /assistant/debug/runs/{run_id}/routes` | Retrieve only routing decisions. |
| `GET /assistant/debug/runs/{run_id}/state` | Refresh current run status, stage, and latest state snapshot. |
| `GET /assistant/debug/runs/{run_id}/drafts` | Retrieve drafts associated with the run. |
| `GET /assistant/debug/chats/{chat_id}/timeline` | Retrieve timelines grouped by run. Do not flatten the groups. |
| `GET /assistant/debug/modules` | Retrieve generic module/task labels and permission metadata. |

The run statuses are `active`, `suspended`, `waiting_on_task`, `completed`,
`cancelled`, and `failed`. Display `current_stage` prominently for active runs.
`suspended` is resumable and may contain a failed event; it is not equivalent to
a successfully completed run.

## Generic timeline rendering

The UI must be module-independent. Render the stable top-level fields and put
anything module-specific in an expandable `data` panel:

```ts
type TimelineItem = {
  id: number;
  agent_run_id: number;
  message_id: number | null;
  sequence: number;
  kind: "route" | "model" | "tool" | "draft" | "validation" |
        "answer" | "error" | "stage" | string;
  event_type: string;
  stage: string;
  module: string | null;
  task: string | null;
  title: string;
  summary: string;
  status: string;
  severity: string;
  duration_ms: number | null;
  error_code: string | null;
  data: Record<string, unknown>;
  created_at: string;
};
```

Suggested presentation:

- use `title` as the row heading and `summary` as the short description;
- show `stage`, `module`, and `task` as optional badges;
- show `duration_ms` when present;
- use `kind` for icons/grouping and `severity`/`status` for colour;
- show `error_code` on failed rows;
- render `data` in a bounded, collapsed JSON viewer;
- key and deduplicate items by `agent_run_id + sequence`.

Do not parse `event_type` to discover module-specific fields. New modules and
providers can add fields inside `data` without requiring a new component. Also
do not render values from `data` as HTML.

## Cursor polling for active runs

Cursor polling is the recommended real-time implementation because the API uses
Bearer authentication:

```http
GET /assistant/debug/runs/{run_id}/events?after_sequence=12&limit=100
Authorization: Bearer <access-token>
```

Example response:

```json
{
  "run_id": 42,
  "after_sequence": 12,
  "next_after_sequence": 12,
  "has_more": false,
  "events": []
}
```

Append `events` in sequence order and use `next_after_sequence` for the next
request. When `has_more` is true, request the next page immediately. Otherwise,
poll an `active` or `waiting_on_task` run every 1–2 seconds. Stop automatic
polling after `completed`, `cancelled`, or `failed`; a `suspended` run can use a
manual refresh or resume-aware polling policy.

Do not increment the cursor locally by array length. Always accept the server's
`next_after_sequence`, including when `events` is empty.

```ts
async function loadNewEvents(runId: number, after: number, token: string) {
  const response = await fetch(
    `/assistant/debug/runs/${runId}/events?after_sequence=${after}&limit=100`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) throw await response.json();
  return response.json() as Promise<{
    run_id: number;
    next_after_sequence: number;
    has_more: boolean;
    events: TimelineItem[];
  }>;
}
```

## Optional SSE stream

The chat stream is:

```http
GET /assistant/debug/chats/{chat_id}/stream?after_event_id={last_event_id}
```

It emits `assistant_event` events containing a `TimelineItem` and periodic
`heartbeat` events. SSE uses the database event `id` cursor, while run polling
uses the run-local `sequence` cursor. Do not interchange them. On reconnect,
send the last received timeline `id` as `after_event_id`.

Native browser `EventSource` cannot attach the required `Authorization` header.
Use authenticated `fetch` streaming or an existing SSE client that supports
headers. If the frontend has no such infrastructure, use cursor polling. Never
put the Bearer token in the query string.

Stream events from different runs can arrive interleaved. Store them under
`agent_run_id`, sort each run by `sequence`, and keep each user message's run
separate.

## Error and empty-state behaviour

- A user message can temporarily have no run while processing has not started,
  or permanently have no run if it predates run association. Show “No debug run
  available” instead of treating this as an empty successful run.
- `output_message_id` and `final_output_message` are null until the answer has
  been persisted.
- Token counts, durations, model identifiers, and routing confidence are
  optional; omit unavailable fields rather than displaying zero.
- An empty event page is normal for an active run.
- Use the returned `errors` collection for an error summary, but retain failed
  events in their original timeline positions.
- Preserve unknown `kind`, `stage`, `status`, and `event_type` values with a
  neutral fallback style so future backend additions remain compatible.

## Privacy expectations

The backend redacts and bounds event payloads, but the debug UI is still an
administrative surface. Do not copy debug payloads into analytics, client logs,
error-reporting breadcrumbs, or local storage. Do not offer an unreviewed
“export everything” feature. The UI must never request or expect hidden model
reasoning, raw prompts, authorization headers, credentials, or complete uploaded
file contents.
