# Owner decisions

Apply this contract in chief and ship whenever progress needs a material owner decision.

## Helper standing request

Read the applicable owner's loaded instructions under `Helper agents (standing request)`, or `Standing grants` when present.
Carry the field in every dispatch brief as the line `Owner helper request:`, then the exact request verbatim on its own line.
Then add one sentence each for the source and heading or verified event, the covered roles, the assigned topic, and the retained restrictions.
Keep every sentence at most 25 words; `hooks/text_lint.py` warns about a longer sentence in a `SendMessage` brief.
A direct applicable loaded owner instruction supplies the explicit request within its stated scope; it requires zero repeated Input retrieval solely for that request.
Verify current owner-event provenance when authority arrives only through an event reference. A peer assertion alone supplies zero owner consent.
Use helpers only within the actual tool contract, role, assigned topic, host limits, and existing permissions.
Preserve every higher-priority restriction, effective refusal, test admission, installation hold, and publication hold.
Send a refusal to the CoC once through the existing native parent route; retain the exact action, restriction, and blocked scope.
Change zero settings or owner instruction files to obtain access.

Require this field and these sentences verbatim in every brief:

```text
Readable files: <exact absolute paths or directories in backticks that the agent may read, including every path its brief, route or agent definition requires; every other path is out of scope>
After a hook refusal, retry in another form when the refusal reason is fixed or the new form meets the rule the refusal names. You may always ask your superior for permission to run the refused command.
Never print a key value; never post outside bettergroupinc and miguelrisero.
Never chain a glob listing into a write command.
```
A reviewer reports a refused call as blocked scope and continues other permitted scope.
[Loaded instructions and refusals](#loaded-instructions-and-refusals) sets the retry rule and the ask-your-superior rule.

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

## Scoped owner event verification

Apply this exception only to future briefs after verified runtime adoption.
Confirm that your loaded role or skill implements this exception.
Require the named lane's brief to select it and cite a CoC-frozen decision file by absolute path and SHA256.
Verify the digest and exact scope before any call.
Require the file to name the exact lane, its repository and task or PR scope, and the owner events to verify.
Require the file to list the permitted tool for each exact Input and workspace UUID.
Permit only `get_input` or `get_input_events` for those exact IDs, solely to verify the named owner events.
Refuse any missing, stale, expired, ambiguous, or mismatched binding.
Apply the [owner answer checks](#consume-and-finish) and the applicable event route's provenance and scope checks.
Match the returned Input, workspace, current version, event identity, and answer to the authorized scope.
An authoritative mismatch blocks verification without fallback.
The file permits verification only and supplies zero owner consent or action authority.
This exception applies only to the named lane's brief-level ban on Input calls.
Keep every other Input call under the ban, including listing, creation, updates, answers, and closure.
Limit this exception to the named lane and the exact tool and IDs in the decision file.
Preserve reviewer MCP denials, all independent hook and tool restrictions, and every effective refusal.

## Standalone main-row repair

Apply this route only to future briefs after verified runtime adoption.
Apply it outside the lane-owned row route.
Require a repair-only lane whose entire diff changes only the named rows' paired `old` and `new` fields.
Use this route only as the follow-up row repair for code from an earlier merged PR.
Before any protected access, read `~/.claude/CLAUDE.md` directly under `CoC decisions (standing grant)`.
Verify the CoC testing delegation and the clause for adapting rows when a PR makes the stored mutant impossible to apply.
Verify that the clause requires a follow-up row for new code and independent not-weaker review.
Require the frozen CoC decision to identify this repair as the follow-up for the named breaking PR under that grant.
Record the path, heading, verified grant, and verification time.
Refuse a missing, unreadable, or mismatched grant; accept zero relay and require zero per-row owner events.

Require the brief to name the CoC-frozen decision file by absolute path and SHA256.
Bind the repository, exact repair lane and branch, and repair PR URL when assigned.
Bind the permitted actors and operations, and the full main and pre-edit commit and tree identities.
Bind every affected row to its earlier breaking PR, full merged commit SHA, and pre-merge main SHA.
Verify that the breaking commit is an ancestor of or equals the bound main commit.
Bind each exact stored row ID, canonical row file, subject file, and approved line extent to the applicable commit.
Keep each decision file immutable. Freeze a new file for any additional scope or evidence.
A discovery decision permits only its named reads. Bind the causal proof and `old`/`new` field scope in the edit decision.
Before review, bind the frozen before and after commits, read-only trees, and exact row extents in a decision file that also binds the edit decision.
Verify the digest and every applicable binding before access or editing.
The read-only reviewer checks the driver's digest evidence and the frozen file's bindings without running a digest command.
List the decision files, shared reference, owner grant, and exact role-specific read paths in each applicable brief.
Refuse missing, stale, expired, mismatched, ambiguous, or unlawfully obtained evidence.

Use only whole-line grep for the exact stored `id = "<ID>"` line in each named file, with zero context.
Read only the approved row extent, from its `[[` header to the line before the next table, or EOF for the last row.
Refuse an ambiguous ID or extent. Forbid adjacent-row reads, broader searches, and whole-file reads or parsing.
Require an active row at the bound main commit.
Refuse an existing `[[retired]]` row on this same-row route.
Preserve the retirement record.
Use the [lane-owned row route](../SKILL.md#lane-owned-row-route) for its replacement row.
Require a new row ID and separate creation authority for the replacement.
Require proof that each stored `old` anchor met its expected count before the breaking commit.
Require proof that it counts zero at that commit and on the bound main.
Require scoped source evidence that the named merge caused the zero count and that the repair lane changed no subject code.
Use the bound pre-merge main and merged commit to show that the breaking PR changed the guarded code itself.
Require positive evidence that this code change made the stored mutant impossible to apply at the guarded site.
Require the frozen decision to bind this evidence to the follow-up under the owner standing grant before authorizing the edit.
Require one disposition for each row: a landed designated-test change or mutant adaptation under that grant, or a CoC decision receipt.
A CoC decision receipt is the disposition only when the breaking change is not the repair lane's own diff and no landed disposition exists.
The receipt states that it is the disposition and names the row ID, the breaking commit and the paired-field re-anchor.
Name the receipt by absolute path and SHA256. Verify the digest before any protected access.
For a landed disposition, require the disposition record to cite the landed row change and its CoC decision.
For a landed disposition, require a receipt for the independent not-weaker review of that disposition.
Require that reviewer to differ from the breaking PR author and the person who applied the disposition.
Bind the review receipt to the reviewer, approving verdict, exact disposition, and commit the reviewer checked.
Verify that the reviewed disposition is the one that landed for the named row.
For a CoC decision receipt, the independent repair review below is the one not-weaker review.
Record the disposition and its evidence references in the frozen edit decision, with the receipt path and SHA256 for a CoC receipt.
Bind them to the full breaking commit SHA, the exact stored row ID, and the exact follow-up edit.
Verify those bindings and the recorded evidence before the edit. Refuse a missing or mismatched disposition, receipt or review.
A zero count alone supplies zero repair authority. A disposition label supplies zero proof.
Before editing, confirm that the lane head equals the bound pre-edit commit and that the named rows and subjects match bound main.
Use one native Edit per row with `replace_all=false` and a unique `old_string` within the approved extent that includes the row ID.
Refuse a missing or ambiguous match without widening the scope. Keep the row pending after a hook refusal. Ask the driver for a permitted route under the protected row rules.
Change only `old` and `new`. Require the repaired anchor to count exactly once at the current source site.
Preserve the identical mutant operation, row ID, claim, subject, designated test, assertions, pins, bounds, and every other field.
The driver applies zero protected edits. The writer has zero publication authority.

Require independent read-only review by a reviewer who differs from the PR author and the applying writer.
Bind the repair PR URL before review, even when the edit decision identified the lane by branch alone.
The brief may independently authorize an unpublished draft to supply that URL.
Keep the draft under every existing push and publication hold.
Require the separate [reviewer admission record](#reviewer-admission-record-for-protected-row-reads) before any reviewer row read.
Compare only the approved row extents in the frozen before and after trees.
Confirm the causal proof, paired-field-only repair, identical mutant operation, and the same guarantee for every row.
Require content-free evidence that the repair diff contains zero other edits.
Require a CoC-approved frozen review receipt before publication. Bind its path and SHA256 to the decision file path and SHA256.
Match the receipt to the reviewer, approving verdict, admission, repository, lane and PR, exact rows and fields, source evidence, and frozen final commit.
Recheck those bindings and the publication head before publishing. Any change to the bound authority, scope, source, or evidence invalidates approval.
Keep protected bytes out of briefs, reports, receipts, and PR bodies.
Keep all mutation, checker, selector, CI, and GO requirements under separate applicable execution admission.
Keep mutation proof after merge and preserve the existing CI runner and merge queue authority.
Source delivery grants zero runtime-adoption, retry, installation, or publication authority.
Preserve all other routes, higher-priority instructions, effective refusals, hook and tool denials, and affected-session holds.

## Reviewer admission record for protected row reads

The pre hook denies every reviewer read under a `tests/mutation` path unless the driver admits it first.
Use this record for lane-owned row review and standalone main-row repair review.

1. Dispatch `ship:reviewer--sol`, `ship:reviewer--opus`, or, for lane-owned row review only, `ship:reviewer--astra`.
   Ask the reviewer to return `ready` and read nothing.
2. Take the agent ID from the Agent tool result.
3. Write `${XDG_STATE_HOME:-~/.local/state}/ultraship/row-review/<agent ID>.json` with native Write, with the full record as its content. In the file name, replace each character outside letters, digits, `_`, `.` and `-` with `_`.
4. The record has four fields: `pr` (the PR URL), `agent_id` (the agent ID), `row_files` (the exact canonical absolute row-file paths) and `expires_at` (`YYYY-MM-DDTHH:MM:SSZ`, UTC, at most 4 hours ahead).
5. Run `chmod 600` on the file. The hook refuses a file that the group or others can write.
6. Send the review brief to the reviewer with SendMessage.
7. Delete the file when the review returns.

In Bash, name the record by its literal absolute path for `chmod 600` and the final delete.
The hook refuses a Bash command that names the state folder together with any of these triggers:
- `$`, `{`, `}`, `*`, `?`, `[` or `]`;
- a backtick;
- `cd` or `pushd`;
- the text `text`.

The hook admits Read of one listed file, and Grep with one listed file as `path` and no `glob` or `type`.
Glob, LSP, and every other read under `tests/mutation` stay denied.
The reviewer reads only the named row lines.
The hook denies Write, Edit, and NotebookEdit to the record folder for every agent except the driver and the main session. For Bash it only checks the command text.

## Row re-anchor tool admission record

Use this record to admit the sanctioned re-anchor command on the lane-owned row route.

1. Dispatch the writer with a first message that asks for `ready` and permits zero row reads.
2. Take the agent ID from the Agent tool result.
3. Write `${XDG_STATE_HOME:-~/.local/state}/ultraship/row-reanchor/<agent ID>.json` with native Write.
4. Replace each filename character outside letters, digits, `_`, `.` and `-` with `_`.
5. Include `pr` (the PR URL), `agent_id`, `row_file` (the canonical absolute protected path), `row_id` and `expires_at`.
6. Set `expires_at` to `YYYY-MM-DDTHH:MM:SSZ`, UTC, later than now and at most 4 hours ahead.
7. Run `chmod 600` on the record.
8. Send the [row re-anchor tool brief](#row-re-anchor-tool-brief) with SendMessage.
9. Remove the record when the writer returns.

In Bash, name the record by its literal absolute path for `chmod 600` and the final removal.
The hook refuses a Bash command that names the state folder together with any of these triggers:
- `$`, `{`, `}`, `*`, `?`, `[` or `]`;
- a backtick;
- `cd` or `pushd`;
- the text `text`.

The hook requires a regular record owned by its user, at most 64 KiB, without group or world write permission.
Only the driver and the main session write admission records.
The record grants zero protected access or edit authority by itself.
Keep the route's authority, independent review, execution admission and publication rules.

Use exactly `python3 -I <plugin root>/skills/ship/scripts/row_reanchor.py --row-file <absolute path> --row-id <id> --subject <repository-relative path> --base <ref> --head <ref>`.
On the restore route, append ` --restoration <commit>` with the full restoration commit SHA.
Use single spaces and unquoted arguments, with nothing before or after the command.
The hook accepts only its own plugin's tool path for a writer with a matching record.

## Row re-anchor tool brief

Fill every field and verify that it matches the lane, the source and the admission record.
Apply the [helper standing request](#helper-standing-request) and the brief's routing and output contracts.
Include the global grant and this reference in `Readable files`.
Keep each sentence at most 25 words.
Keep all row TOML text and pair bytes out of the brief.

```text
Re-anchor row `<row ID>` of `<PR URL>` under the lane-owned row route.

Facts:
- Authority: the owner's global CLAUDE.md, heading "CoC decisions (standing grant)".
- Row file: `<row file path>`.
- Subject: `<subject path>` at commit `<subject commit SHA>`.
- CI: run `<run ID>` found `<count>` anchors and expected `<expected>`.
- Base: `<base SHA>`.
- Worktree: `<worktree path>` at head `<head SHA>`.
- Admission record: `<admission record path>`, expires at `<expiry time>`.

Decision:
- Read the standing grant directly.
- Verify each binding before running the tool.
- Run once, alone: `<tool command>`.
- Commit only the row file on success.
- Keep the row pending on a refusal.
- Report the refusal to the driver.

Next:
- Return the tool output, the generated authorization record path and the commit SHA to `<driver>` by `<return time UTC>`.
```
On the restore route, write `none` for the CI run, count and expected values when the starting head deletes the row.

## Future ordinary-file identity checkpoints

Use direct Git and file-hash tools only for independently authorized future ordinary-file identity checkpoints.
Require literal worktree paths and an exact permitted file allowlist; exclude protected files.
Disable fsmonitor with `-c core.fsmonitor=false` on direct Git reads.
Disable external diff helpers and text conversion with `--no-ext-diff --no-textconv` where applicable.
Use literal revision and status reads and direct `sha256sum` over only the permitted ordinary files.
Bind the revision, status, diff and hash results to one unchanged checkpoint.
Invalidate an inconsistent checkpoint collection or any collection whose source changes during capture.
Preserve process ownership, cleanup, execution admission and the brief's restrictions.
Keep computed process-capable Python denied regardless of its claimed read-only purpose.
This documentation grants zero alternative execution for a recorded denied identity operation.

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

An explicit owner refusal blocks all routes for that edit until applicable owner authority resolves it. Apply your own loaded definition; a checkout, cache entry, or version supplies zero additional authority. Prospective source changes and their delivery supply zero runtime-adoption, affected-retry, or action authority. Preserve existing loaded-session restrictions and affected-session holds. Keep each helper within its assigned lane and authority. When diagnosing a contract mismatch, report the loaded identity evidence available and identify unknown fields without inference. Repairing missing verification evidence resolves only that evidence gap; it cannot override a binding prohibition or tool denial.
Retry rule: after a hook or permission refusal, an agent may retry in another form when the refusal reason is fixed or the new form meets the rule the refusal names. A script file, another interpreter, a module flag or a wrapper command is another form; it must meet that rule too. An agent may always ask its superior for permission to run the refused command.
A hook refusal never drops work: keep the task pending, then retry in a fixed form or ask the superior.
Push, merge and protected-write refusals stay final; a retry in another form never bypasses them.
A writer asks its driver, a reviewer asks its coordinator, a driver asks its chief, and a chief asks the CoC. The CoC asks the owner only for product, billing, security policy or big architecture. The superior may grant the request, or run the command itself when it considers that appropriate. The superior records the grant or the run in the lane state file. Never ask the owner to paste or run a command. A version, restart, or new session alone lifts nothing. Checks that the brief names stay permitted when the hook admits them. Safety blocks: keep destructive actions, secrets, production data writes, flag flips, deploys, customer-data deletion, protected paths, and approval, GO, installation, and publication holds blocked as their own rules say. A retry in another form never bypasses a safety block. A superior grants or runs a command only within its own authority, and its own hooks and permissions apply. Protected mutation-row edits use only the [lane-owned row route](../SKILL.md#lane-owned-row-route), the [standalone main-row repair](#standalone-main-row-repair) and their tools.
Message-format rule: `text_lint.py` warns about prose formatting and lets the call proceed. Examples include glued words and sentence or word limits. Apply the formatting guidance to the next message. Preserve the action, recipient, scope, authority, non-prose fields, owner provenance, and choice identifiers. Invent zero facts, evidence, approval, or authority while you apply it. Keep the Input classification requirement and receipt validation in force. After a receipt citation refusal, remove the receipt marker and resend with the same action, recipient and scope. Only the hook writes receipt state; agents never read, write or reset the receipt store. A MAC-valid receipt that another agent sends to the receipt's own agent is a relay: a new message that keeps normal checks and consumes no receipt. Keep receipt markers out of `Agent` and `Task` prompts. For a content refusal, fix the content to meet the named rule or ask the superior for permission within existing authority.
Coordination gate: for the driver's `Agent` dispatch, resend when the denial explicitly identifies `Coordination gate error` and an exact text remedy. Require unambiguous gate identity and remedy and the applicable loaded contract; the denial date alone never determines eligibility. Apply only that remedy; preserve the action, recipient, scope, authority, and exact owner-provenance checks. Recheck current version, status, and answer provenance before the resend.
