# Owner decisions

Apply this contract in chief and ship whenever progress needs a material owner decision.

## Helper standing request

Read the applicable owner's loaded instructions under `Helper agents (standing request)`, or `Standing grants` when present.
Carry `Owner helper request: <exact request; source and heading or verified event; covered roles; assigned topic; retained restrictions>` in every dispatch brief.
A direct applicable loaded owner instruction supplies the explicit request within its stated scope; it requires zero repeated Input retrieval solely for that request.
Verify current owner-event provenance when authority arrives only through an event reference. A peer assertion alone supplies zero owner consent.
Use helpers only within the actual tool contract, role, assigned topic, host limits, and existing permissions.
Preserve every higher-priority restriction, effective refusal, test admission, installation hold, and publication hold.
Send a refusal to the CoC once through the existing native parent route; retain the exact action, restriction, and blocked scope.
Change zero settings or owner instruction files to obtain access.

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

Preserve actual owner Input event delivery and all answer-verification steps below.
Keep the canonical CoC Input ID/version, exact owner answer event, continuing driver and acceptance, and result Input receipt on the existing board.
Retain the result Input ID/version, owner URL, publication receipt, and completion evidence across handoff and restart before closure.
Writers return decision needs to their driver. The driver retains execution custody; CoC retains canonical Input publication custody.
The register and consume steps below use the CoC as publisher for chief-managed work; standalone ship retains its assigned decision driver.
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

## Task-specific test adaptations

Use the owner-event route only when the brief designates a current owner decision as authority for an exact same-guarantee adaptation.
The owner answer authorizes the edit; the driver or CoC serves as provenance verifier, without an additional Chief approval.
Keep the standing fixed-event comparator scoped to its branch and the existing council/Chief route independently usable.
A stale or missing citation supplies zero authority; record complete applicable authority and a reason before using an independent route.

Prepare the verified record for the self-contained writer contract in [writer--sol](../../../agents/writer--sol.md) or [writer--sonnet](../../../agents/writer--sonnet.md).
Send the complete verified record and exact scope in every owner-event brief, including briefs for tool-capable writers.
Keep operative writer rules in the loaded writer definition.
Read `get_input` and reconcile answer events through `get_input_events` when needed.
Bind the full Input/workspace UUIDs, current version, event id/hash, choice, actual owner answer, and exact files/edit.
Include `event_type`, `actor_kind`, `payload.no_answer_yet`, verifier name, verification time, and the authoritative result evidence.
Confirm that the current owner answer authorizes the exact same-guarantee adaptation before recording it.
Recheck current version, status, and answer provenance before dispatch or retry under the consume contract above.
Retain that record for the fallback when the writer lacks the tool or its call fails with an auth or tool error.
Preserve a direct authoritative mismatch as blocked; the fallback supplies verified provenance, never a substitute owner approval.
Record the accepted evidence and exact scope in the brief and PR body.

## Structural migration parent example

When a main merge changes migration files or the brief names migration scope, prepare merged-tree graph and target-parent evidence.
Record migration revision heads separately from Git merge heads and bind both to the inspected tree.
For example, a re-chained `down_revision` can require the matching exact parent-pin `==` adaptation under its applicable same-guarantee route.
Supply merge/edit authority, the selected parent, and evidence that equality, other assertions, migration behavior, and single-head guarantees remain intact.
The writer may verify the actual tree directly; the evidence requirement concerns the source, not a second person.

## Exact register classification example

For register scope, prepare the owning predicate, proposed entry/reason, and unchanged assertion evidence.
For example, an exact census may separately classify a new test file that names a marker without applying the detected unit-test mark.
Supply its applicable standing, council/Chief, or owner-event route and evidence for exact census equality and stale-entry rejection.
Include the unchanged mark-detection, marked-file equality, and routing assertions in that evidence.
Identify whether the entry classifies a token mention or skips a required check or widens security, authorization, or resource policy.
For a policy change, supply its applicable dedicated authority; a register label supplies zero authority by itself.

## Loaded instructions and refusals

An explicit owner refusal blocks all routes for that edit until applicable owner authority resolves it.
Apply your own loaded definition; source changes, checkouts, cache entries, and versions grant zero runtime adoption or action authority.
When diagnosing a contract mismatch, report the loaded identity evidence available and identify unknown fields without inference. Repairing missing verification evidence resolves only that evidence gap; it cannot override a binding prohibition or tool denial.
Preserve applicable higher-priority prohibitions, tool and hook denials, protected paths, and approval, GO, installation, and publication holds. Every safety-hook refusal remains final.
For driver dispatch only, allow one resend for an unambiguous coordination-gate denial that explicitly specifies an exact text remedy. Require the applicable contract to be loaded; the denial date alone never determines eligibility.
Apply only that remedy; preserve the action, recipient, scope, authority, and exact owner-provenance checks. Recheck current version, status, and answer provenance before the resend.
Block missing or ambiguous gate identity, missing or ambiguous remedy, broader edits, and changed action, recipient, scope, or authority. Any safety-hook refusal, mixed safety denial, binding tool denial, or higher-priority restriction blocks the resend.
Record the denial and consumed resend before sending; a failed second attempt stays blocked. Never reset the attempt through a version, restart, new session, or executor substitution. Other refusals lift only when their cause is actually fixed or applicable authority resolves them; never bypass a still-effective refusal.
