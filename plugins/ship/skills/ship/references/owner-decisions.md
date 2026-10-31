# Owner decisions

Apply this contract in chief and ship whenever progress needs a material owner decision.

## Chief-managed CoC delivery

For chief-managed work, apply the chief's native peer routing and model-independent output contracts to every child, timer, and recovery brief.
Separate words with spaces. Use full sentences of at most 25 words; prohibit glued-word shorthand.
Lead peer bodies with the outcome and meaning, then `Facts`, `Decision`, and `Next` with an accountable owner and dated UTC time.
Decision Inputs state `What is wrong`, `Why now`, `Options` A–C with effects, `Recommendation`, and `If no answer`.
Preserve informational result Inputs without artificial choices and preserve existing published choice IDs during retries.
Classify create and update HTML with exactly one `<meta name="output-kind" content="decision">` or `<meta name="output-kind" content="result">`.
Free-text owner decisions use `decision`; informational deliverables with feedback choices use `result`. Missing classification blocks publication.
Preserve the server payload schema and actual owner-answer validation.
The bundled `hooks/text_lint.py` source hook checks outgoing `SendMessage` and Input prose; native completions retain instruction-only enforcement.
Use native `SendMessage` or the native agent channel for peer coordination; a child without the tool returns reports to its parent for relay.
Never use BetterCoding `send_workspace_message`, `run_session_prompt`, or simulated user input for peer coordination, including fallback delivery.
Batch actionable and terminal reports; keep unchanged routine reports silent and CoC peer events out of per-peer user-chat replies.
Chiefs send decision context, options, and a recommendation through the native channel to the CoC.
Verify CoC liveness with its existing recorded identity. Only the CoC publishes canonical owner decisions and results in CoC workspace Inputs.
For chief-managed work, chief-local Inputs never satisfy delivery. Reuse the canonical CoC Input ID and avoid duplicate Inputs.
If CoC is unavailable, preserve the pending decision and critical hold; retry native handoff through existing scheduling with zero additional pollers.
Publish zero Inputs elsewhere during that wait. Continue independent work within existing authority.

Preserve actual owner Input event delivery and all answer-verification steps below.
Keep the canonical CoC Input ID/version, exact owner answer event, continuing driver and acceptance, and result Input receipt on the existing board.
Retain the result Input ID/version, owner URL, publication receipt, and completion evidence across handoff and restart before closure.
Writers return decision needs to their driver. The driver retains execution custody; CoC retains canonical Input publication custody.
The register and consume steps below use the CoC as publisher for chief-managed work; standalone ship retains its assigned decision driver.
Agent messages grant zero owner consent or approval; verify the actual owner event before action.
Actual owner-event delivery may use user input only when that route is required, with the verified event and exact owner words.
Keep authorized lifecycle commands separate from peer reports. Preserve actual permission denials and every approval, deploy, GO, and installation hold.

## Register and continue

- Assign one driver to each independently answerable decision. Writers return decision needs, context, options, and blocked scope to their driver.
- Let only the designated publisher create or maintain the Input: CoC for chief-managed work, the decision driver for standalone ship.
- Chief retains the canonical CoC Input ID on its board and requests publication through native handoff.
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
