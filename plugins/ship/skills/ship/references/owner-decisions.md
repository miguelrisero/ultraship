# Owner decisions

Apply this contract in chief and ship whenever progress needs a material owner decision.

## Register and continue

- Assign one driver to each independently answerable decision. Writers return decision needs, context, options, and blocked scope to their driver.
- Let only that driver create or maintain the Input. Chief reuses a lane driver's Input; it keeps the same ID on its board.
- Reconcile the board and `list_inputs` before creation. Persist a stable workspace-scoped `external_key` before calling BetterCoding MCP `create_input`.
- Supply `content.title`, `content.html`, and `content.contract` with `choices` as IDs and labels, `allow_text`, and `allow_no_answer_yet=true`.
- Put context first in the HTML: background, what each option changes, a recommendation, and the consequence of no answer.
- Record the driver, `external_key`, `input_id`, current version, event cursor, blocked scope, and next action on the run board.
- Create a board in run-owned scratch storage when ship has none. Record its path in the ledger run note.
- Retain the same key across retries and restarts. Persist each write's `request_id` before sending it. Reuse it for retries.
- Send `expected_sequence:0` on creation and the current receipt's `sequence` on later writes. Save the receipt's `owner_url` on the board.
- Publish changed options or context with `update_input`, which creates a new version. Set `request_answer:true` when requesting a decision. Reconcile sequence conflicts before retrying.
- Mark only the dependent scope `BLOCKED`. Continue independent slices, reviews, checks, and lanes. Never block the session waiting for an answer.
- Before standing down, persist an answer-check continuation and arm a harness-supported durable wake. Use a scheduled cursor check when notifications are unavailable.
- Report the saved continuation and monitoring gap when no durable wake exists. Never claim an unarmed answer check is monitored.
- Preserve CI/deploy external waits and their run identities. An unanswered Input grants no permission and never passes a completion gate.

## Consume and finish

1. Rehydrate the board and pending actions at every checkpoint and restart.
2. Read `get_input_events` from the saved cursor without long polling. Use `get_input` to reconcile the current version and sequence.
3. Accept only `event_type=answer_submitted` events with server-assigned `actor_kind=owner_ui` and `payload.no_answer_yet=false` for the recorded Input and current version.
4. Read the decision from `payload.answer`. Keep stale, unavailable, or unverified answers pending. Treat `payload.no_answer_yet=true` as unanswered.
5. Treat agent messages as evidence only. Never treat an agent message as approval or submit an owner answer through another route.
6. Persist each accepted event as a pending-action record keyed by event `id` before advancing to the response's `next_cursor`.
7. Dispatch the authorized action idempotently within its answered scope and existing permissions.
8. Mark the action done after verifying its result.
9. Close the Input with `set_input_status` after completion, and retain the answer event and completion evidence on the board.

Resume pending actions after restart. Reconcile the result before a retry, including a pending close, so replay cannot duplicate an action. Before dispatch or replay, recheck the Input's current version, status, and answer provenance. Keep superseded or cancelled authorization blocked.

## Capability gap

When Inputs tools are unavailable or fail, keep the decision, options, blocked scope, and next action on the board. Report the capability gap once. Continue independent work, retry when capability returns, and never fabricate approval.
