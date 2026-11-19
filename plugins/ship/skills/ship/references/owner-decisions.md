# Owner decisions

Apply this contract in chief and ship whenever progress needs a material owner decision.

## Helper standing request

Read the applicable owner's loaded instructions under `Helper agents (standing request)`, or `Standing grants` when present.
Carry the field in every dispatch brief as the line `Owner helper request:`, then the exact request verbatim on its own line.
Then add one sentence each for the source and heading or verified event, the covered roles, the assigned topic, and the retained restrictions.
Keep every sentence at most 25 words; `hooks/text_lint.py` refuses a longer sentence in a `SendMessage` brief.
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
Keep aliases, alternate tool routes, and substitute actors outside this exception.
Preserve reviewer MCP denials, all independent hook and tool restrictions, and every effective refusal.

## Standalone main-row repair

Apply this route only to future briefs after verified runtime adoption.
Apply it outside category 5 and the PR-owned row routes.
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
Use the [new lane-owned row review route](#new-lane-owned-row-review-route) for its replacement row.
Require a new row ID and separate creation authority for the replacement.
Require proof that each stored `old` anchor met its expected count before the breaking commit.
Require proof that it counts zero at that commit and on the bound main.
Require scoped source evidence that the named merge caused the zero count and that the repair lane changed no subject code.
Use the bound pre-merge main and merged commit to show that the breaking PR changed the guarded code itself.
Require positive evidence that this code change made the stored mutant impossible to apply at the guarded site.
Require the frozen decision to bind this evidence to the follow-up under the owner standing grant before authorizing the edit.
Require recorded evidence of a landed designated-test change or mutant adaptation under that grant.
Require the disposition record to cite the landed row change and its CoC decision.
Require a receipt for the independent not-weaker review of that disposition.
Require that reviewer to differ from the breaking PR author and the person who applied the disposition.
Bind the receipt to the reviewer, approving verdict, exact disposition, and commit the reviewer checked.
Verify that the reviewed disposition is the one that landed for the named row.
Record both items and their verifiable evidence references in the frozen edit decision.
Bind both items to the full breaking commit SHA, the exact stored row ID, and the exact follow-up edit.
Verify those bindings and the recorded evidence before the edit. Refuse a missing or mismatched record or review.
A zero count alone supplies zero repair authority. A disposition label supplies zero proof.
Before editing, confirm that the lane head equals the bound pre-edit commit and that the named rows and subjects match bound main.
Use one native Edit per row with `replace_all=false` and a unique `old_string` within the approved extent that includes the row ID.
Refuse a missing or ambiguous match without widening the scope. A hook refusal ends the step.
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

## New lane-owned row review route

Apply this route only to future briefs after verified runtime adoption.
Source delivery grants zero runtime-adoption authority.
Source delivery grants zero retry authority.
Source delivery grants zero installation authority.
Source delivery grants zero publication authority.
Preserve every existing refusal, tool and hook denial, and affected-session hold.
Retry a refused command in another form only when the refusal reason is fixed or the new form meets the rule the refusal names.
Require actual cause resolution and fresh applicable disposition before any affected-session attempt.
Source delivery, installation, version, cache, restart, executor and tool changes alone resolve zero existing denial.
A contract-gap refusal is a writer or driver refusal whose quoted reason is only that its loaded contract lacked the route the decision selected.
It made zero protected reads and named no content, scope, protected-access, hook, permission or tool finding.
Its cause resolves only when a new CoC decision, with a new SHA256, quotes the refusal verbatim, names that sole cause and records its zero protected reads.
The next agent in the refusing role must also find the selected route heading in its own loaded contract by native Read, under a section that implements that route and does not refuse it.
A follow-on refusal is a refusal whose only reason is that an earlier refusal stayed effective; it also made zero protected reads.
A follow-on refusal resolves with that earlier refusal when this rule resolves the earlier one and the same CoC decision quotes the follow-on refusal verbatim.
Hook, permission and tool denials, `REFUSED` tool results, and any refusal with a reason outside these two definitions never qualify.
The fresh disposition and every other route requirement still apply.

## Draft PR for new lane-owned row review

Apply this section only with the new lane-owned row review route and its runtime-adoption boundary.
Permit the driver to open the PR that carries the new rows as a draft before protected review.
The draft supplies the repository and PR number that the read admission and receipt name.
In this route, publication means marking the draft ready for review, pushing to a ready PR, posting `/merge` or any other merge.
Opening the draft and pushing to it while it stays a draft publish nothing.
Bind the receipt to the draft PR number and frozen final commit.
A push that moves the draft head away from the frozen final commit invalidates the receipt and its approval.
Before each publication step, confirm that the PR head equals the frozen final commit.
Return a ready PR to draft before any further push, then repeat the review and approval.

## Reviewer admission record for protected row reads

The pre hook denies every reviewer read under a `tests/mutation` path unless the driver admits it first.
Every route that needs row reads uses this flow: lane-derived, lane-owned, retirement, owner-approved subject, and standalone main-row repair.

1. Dispatch a reviewer whose loaded definition implements the selected route. `ship:reviewer--sol` and `ship:reviewer--opus` implement every reviewer row route; `ship:reviewer--astra` implements only the new lane-owned row review route. Make the first message ask it to return `ready` and read nothing.
2. Take the agent ID from the Agent tool result.
3. Write `${XDG_STATE_HOME:-~/.local/state}/ultraship/row-review/<agent ID>.json` with native Write, with the full record as its content. In the file name, replace each character outside letters, digits, `_`, `.` and `-` with `_`.
4. The record has four fields: `pr` (the PR URL), `agent_id` (the agent ID), `row_files` (the exact canonical absolute row-file paths) and `expires_at` (`YYYY-MM-DDTHH:MM:SSZ`, UTC, at most 4 hours ahead).
5. Run `chmod 600` on the file. The hook refuses a file that the group or others can write.
6. Record the `ready` result with `ledger.py append row-review-ready <agent-type>@<agent-id> <sha> ready` before you send the brief.
7. Send the review brief to the reviewer with SendMessage.
8. Delete the file when the review returns.

In Bash, name the record by its literal absolute path for `chmod 600` and the final delete.
The hook refuses a Bash command that names the state folder together with any of these triggers:
- `$`, `{`, `}`, `*`, `?`, `[` or `]`;
- a backtick;
- `cd` or `pushd`;
- the text `text`.
This guidance grants no replay of an earlier refused command and no other tool route.

The hook admits Read of one listed file, and Grep with one listed file as `path` and no `glob` or `type`.
Glob, LSP, and every other read under `tests/mutation` stay denied.
The reviewer reads only the named row lines.
The hook denies Write, Edit, and NotebookEdit to the record folder for every agent except the driver and the main session. For Bash it only checks the command text.

## Row re-anchor tool admission record

1. Dispatch the writer with a first message that asks for `ready` and permits zero row reads.
2. Take the agent ID from the Agent tool result.
3. Write `${XDG_STATE_HOME:-~/.local/state}/ultraship/row-reanchor/<agent ID>.json` with native Write.
4. Replace each filename character outside letters, digits, `_`, `.` and `-` with `_`.
5. Include `pr` (the PR URL), `agent_id`, `row_file` (the canonical absolute protected path), `row_id` and `expires_at`.
6. Set `expires_at` to `YYYY-MM-DDTHH:MM:SSZ`, UTC, later than now and at most 4 hours ahead.
7. Run `chmod 600` on the record.
8. Record the ready result with `ledger.py append row-reanchor-ready <agent-type>@<agent-id> <sha> ready`.
9. Send the exact scoped brief, built from the [row re-anchor tool brief](#row-re-anchor-tool-brief), with SendMessage.
10. Remove the record when the writer returns.

In Bash, name the record by its literal absolute path for `chmod 600` and the final removal.
The hook refuses a Bash command that names the state folder together with any of these triggers:
- `$`, `{`, `}`, `*`, `?`, `[` or `]`;
- a backtick;
- `cd` or `pushd`;
- the text `text`.
This guidance grants no replay of an earlier refused command and no other tool route.

The hook requires a regular record owned by its user, at most 64 KiB, without group or world write permission.
Only the driver and the main session write admission records.
The record grants zero protected access or edit authority by itself.
Keep the route's authority, independent review, execution admission and publication rules.

Use exactly `python3 -I <plugin root>/skills/ship/scripts/row_reanchor.py --row-file <absolute path> --row-id <id> --subject <repository-relative path> --base <ref> --head <ref>`.
Use single spaces and unquoted arguments, with nothing before or after the command.
The hook accepts only its own plugin's tool path for a writer with a matching record.

## Row re-anchor tool brief

The driver fills every field of this template and sends it as the step 9 brief.
Each field supplies one lane-derived route requirement; a writer refuses a missing, unfilled or mismatched field.
Put identifiers in backticks and keep each sentence at most 25 words, so the message passes `text_lint.py`.
`text_lint.py` removes backtick spans, then counts a leading `-` and any punctuation left beside a removed span as words.
It also refuses three or more words of 22 or more characters outside backticks, so times and file names go in backticks.
Each template sentence leaves at least 12 words for its values; split a long value or an added line into short sentences.
The brief carries no row text, pair bytes or TOML text.
For a superseded-ruling free, add one line after `- Earlier attempts:` that names the free's decision file, its SHA256 and the attempt record entry.
Add that decision file to `Readable files:`.
In that brief, replace `The tool attempt for this grant and head is therefore unused.` with `The attempt is used, and the superseded-ruling free authorizes one further attempt.`

```text
Re-anchor row `<row ID>` of <PR URL> once with the sanctioned row re-anchor tool. Then commit the row file.

Owner helper request: the owner's global CLAUDE.md, heading "Helper agents (standing request)", requests helper agents. Covered role: writer. Topic: <assigned topic>. Every permission, denial and gate stays in force.
Readable files: `<worktree path>`, `<plugin root>/skills/ship/references/owner-decisions.md`, `<decision file path>`, `<tool route decision path>`, `<denial record path>`, `<attempt record path>`; every other path is out of scope
A hook refusal is final: report it and stop.
Never print a key value; never post outside bettergroupinc and miguelrisero.
Never chain a glob listing into a write command.

Facts:
- Route: lane-derived, with the sanctioned row re-anchor tool.
- Standing rule: category 5 of owner rule Input `<rule Input UUID>` in workspace `<workspace UUID>`, choice `plugin_rule`.
- Standing rule event: `<rule event ID>`, hash `<rule event hash>`, `answer_submitted`, `owner_ui`. <rule verifier name> read it with `get_input` at `<rule verification time>`.
- Owner access: Input `<Input UUID>` version <version>, workspace `<workspace UUID>`, choice B, answer text null.
- Owner event: `<event ID>`, hash `<event hash>`, `answer_submitted`, `owner_ui`, `no_answer_yet` false.
- Verifier: <verifier name> read the event with `get_input` at `<verification time>`.
- CoC decision: `<decision file path>`, SHA256 `<decision file SHA256>`.
- Allowlist: row file `<row file path>`, stored row ID `<row ID>`, subject `<subject path>`.
- CI: run `<run ID>`, attempt <attempt>, job `<job ID>` named `<job name>`, log <job log URL>.
- CI failure: row `<row ID>` found <count> times, expected <expected>.
- Tested merge `<tested merge SHA>`, tree `<tested merge tree SHA>`, parents `<CI base SHA>` and `<author head SHA>`.
- Subject change: PR commit `<subject commit SHA>` changed `<subject path>` lines <subject line range> at the author head. From the CI base, the subject diff has <added> added and <deleted> deleted lines.
- Same operation: the CoC reviewed the same-operation, same-claim reason at `<review time>`. The decision file above records it.
- Tool base `<tool base SHA>`: <tool base reason>.
- Method-only denials: <method-only denials>. They came at `<denial times>`. Lines <denial record lines> of `<denial record path>` record them. Each named only the method, never row content or scope.
- Tool route: the CoC selected the sanctioned tool for this row in `<tool route decision path>`.
- Earlier attempts: <earlier attempts>. Each made zero native Edit calls and zero tool runs, or ended only in a tool error under another head's grant. None drew `REFUSED` or a hook or permission refusal or denial other than the listed method-only denials. The tool attempt for this grant and head is therefore unused.
- Attempt record: `<attempt record path>`. It names each earlier attempt's decision file, SHA256, head SHA and outcome.
- Admission record: written for your agent ID, expires at `<expiry time>`.
- Worktree: `<worktree path>` at `<author head SHA>`, clean.

Decision:
- Verify the standing rule event with `get_input` against choice `plugin_rule`, and the access event against choice B.
- Without `get_input`, or on an auth or tool error, use the records above.
- Record the tool attempt with the decision file, its SHA256 and `<author head SHA>` in the attempt record. Then run once, alone: `<tool command>`
- Record the run's outcome in the attempt record before any other step.
- On success, stage only the row file by its path and commit once: `<commit subject>`.
- On `REFUSED` or any denial, stop. Push, test and row-line reads stay forbidden.
- A content, scope or protected-access denial blocks the tool run; only the listed method-only denials may precede it.

Next:
- Return the tool output and the commit SHA by `<return time>`.
Receipt: `<decision file name>`
```

## False-claim retirement route

Use this route only when the brief names the False-claim retirement route.
It retires an active protected row whose claim the PR's own design makes false at the final code.
A brief that names this route uses it in place of every other retirement and row review route.
This route is an exception to the identical-mutant edit rule and to the rule that sends every other row change to Lane-derived row review.
Its named row-ID lookups and row-line reads are an exception to the mutation TOML search prohibition.
Refuse a row that CI reports `in the base file, missing at HEAD`; that row uses the Removed-behavior retirement route.
Refuse a row that is absent at the base SHA.
Refuse a row whose lines at the author head SHA differ from its lines at the base SHA.
Keep every other retirement route, its CI-line requirement and its authority unchanged.
Require the PR body to name each row ID and its claim, and to quote the claim.
Require the PR body to state why each claim is false at the final code, citing `file:line` at the PR head.
Require the PR body to state the intended behavior change; a claim that a defect made false never qualifies.
Require the PR's own base/head diff to change the subject file that each named row names.
Refuse a row whose subject file the PR leaves unchanged.
Require a hunk that a PR-authored commit wrote in that subject file to make the claim false; a main merge alone never qualifies.
A merge commit counts as PR-authored unless its subject blob equals the subject blob of the clean automatic merge of its parents.
Refuse when any part of the claim still holds at the final code; that row uses the lane-derived route or the Lane-owned disposition route's surviving-claim adaptation.
Require a CoC decision file that the brief names by absolute path and SHA256.
Require that file to bind the repository, PR, base SHA, author head SHA, row-file path and each exact unique row ID.
Require that file to state that the CoC accepts the behavior change as the PR's intended design.
That file cites owner event `dc03370c-c170-4284-b9e4-75aac2dcaab0` on Input `1b143a6d-e303-4fe4-82ab-69c0f235a4a5` as its authority; it is this route's loaded edit authority.
Verify that event as the Lane-owned disposition route verifies a decision that cites it; the standing grant alone supplies zero authority on this route.
Owner-scoped protected row access grants nothing on this route.
Before any protected read, the driver or writer verifies the file SHA256 and every binding.
A reviewer checks the driver's recorded SHA256 and bindings and runs zero digest commands.
Refuse a SHA256 mismatch, a missing or different binding, a passed expiry that the file states, and a branch head other than the bound author head SHA before the edit.
Permit the applying writer to locate each named row by its row ID inside its named file.
Read only that row's table lines, including its owned child tables.
Forbid whole-file parsing, adjacent-row reads, unnamed-row reads and broader protected searches.
Replace only each named row's table with exactly one `[[retired]]` table that carries its exact ID.
Allow only `id` and `reason` in that table; copy `reason` verbatim from the PR body's statement for that row.
Encode the reason as a TOML basic string with backslash, quote and every control character escaped.
Before the edit, validate only the generated `[[retired]]` text through one quoted-delimiter `python3 -I -` heredoc importing only `tomllib`.
Run that inert parse alone in its Bash call; read zero files and write zero files.
Use native Edit with replace_all=false; require old_string to cover the full row table extent, including all owned child tables and the unique row ID.
Refuse unclear extent, missing or multiple matches, and any unapproved neighboring content.
Change nothing else in the named file: no other line, row, field, pin, or table.
Another approved exact edit to the same file, such as a `claims` pin change, needs its own authority and its own commit; this route grants none.
Commit the retirement alone, with one native Edit per named row.
Check it only with content-free `git diff --numstat` counts for each named file against the retirement commit's parent.
Let s be the lines that a row table and its `[[retired]]` table share, such as the `id` line.
Require the deleted lines to equal the row table lines minus s, and the added lines to equal the `[[retired]]` table lines minus s, summed over the named rows.
Refuse any other count.
Before the push, require an independent reviewer who differs from the PR author and the applying writer.
Require the brief to supply read-only trees at the base SHA, the author head SHA and the frozen commit after the edit, with the retirement commit SHA and its line counts.
Require the frozen commit to contain the author head SHA and the retirement commit.
Admit each reviewer row read with the driver's reviewer admission record for protected row reads.
Permit the reviewer to locate each named row ID and read only its row lines at the base SHA and the author head SHA, and its `[[retired]]` table at the frozen commit.
Permit the reviewer to read the follow-up row's lines by its row ID at its frozen commit; the admission record lists that row file.
Require the reviewer to read each retired row's lines at the base SHA and confirm its row ID, subject file and claim.
Require the reviewer to confirm that the claim held at the base SHA.
Require the reviewer to confirm that the PR body quotes that claim exactly and that the PR's own diff changes that subject file.
Require the reviewer to cite the PR-authored hunk that makes the claim false.
Require the reviewer to read the cited final code at the frozen commit and to search non-row source and test files for the claimed behavior.
Require the reviewer to confirm that no part of the claim holds at the final code and that the final code implements the stated behavior change.
Agreement with the PR body alone supplies zero confirmation.
Require the reviewer to confirm that the retirement commit replaces only the named row tables, each with one `[[retired]]` table, and that the line counts match the lines it read.
Require the reviewer to confirm one `[[retired]]` entry and zero active entries for each named row ID at the frozen commit.
Require a follow-up row that guards the new behavior, in this PR or in a follow-up PR that this PR body names by direct URL.
Create the follow-up row only under its own applicable route; this route grants zero row-creation authority.
Require the same reviewer to read the follow-up row at its frozen commit and confirm that it is not weaker than the retired row.
Not weaker means that the follow-up row guards the new behavior at least as tightly as the retired row guarded the old behavior.
For a follow-up PR, bind its URL, head SHA, row-file path and row ID in the review receipt; a later follow-up head needs a new verdict.
A later head that only merges main keeps the verdict when the follow-up row's lines, its subject file and its designated test file stay byte-identical; judge each merge commit by the merge-commit rule above, applied to those files.
Run this PR's post-merge battery after that follow-up PR merges at a head that keeps the verdict, at a commit that contains both.
The follow-up row merges within 24 hours of this PR's merge, the same limit as the post-merge battery.
If the follow-up PR has not merged 24 hours after this PR merges, run the battery then and report the retired claim to the CoC as unguarded.
After that report, the CoC has the follow-up row merged or the retirement reverted; a retirement never stays on main without a merged follow-up row.
The CoC decides any revert of this retirement.
The lane that applied the retirement opens the revert as a normal PR with an independent review.
A revert that restores retired rows is a CoC-owned protected edit, limited to the rows that this PR retired.
Only a `git revert` of this PR's merge commit may restore those rows; a hand edit never restores a row.
The CoC names the revert commit in a frozen file before the push.
Each restored row must equal its bytes at the parent of this PR's merge commit.
The revert may remove a follow-up row only when this PR's merge commit added it.
Every other line of each row file that the revert changes must equal that file at the revert's parent.
The CoC's content-free git check proves these equalities, without a not-weaker review.
Any other row change in the revert stops the push.
Refuse the retirement when the claim is still true at the final code, or when the reviewer cannot confirm any requirement.
Refuse on any doubt about any requirement.
Bind the review receipt to reviewer identity, approving verdict, decision file SHA256, frozen commit SHA, row-file paths, row IDs, cited `file:line`, cited hunk and follow-up row ID.
Require CoC approval of that review receipt before the push; changed source, decision file or evidence invalidates the receipt and approval.
Keep messages, briefs and PR bodies free of pair bytes and row TOML text; the quoted claim is the only exception.
Identify each edit only by path, row ID and the `[[retired]]` table.
Beyond the reads above, this route grants zero TOML search or parse authority, protected reads, or anchor extraction.
This route grants a reviewer zero edit, execution, mutation or checker authority.
Require separate admission for every mutation or checker execution; keep mutation proof after merge.
Hook, permission and tool denials and every earlier refusal stay effective under their existing rules; this route lifts none of them by itself.
The driver applies zero protected edits; preserve zero writer publication authority, protected holds, and Peral's CI-runner and merge-queue authority.

## Lane-owned disposition route

Apply this route only to future briefs after verified runtime adoption.
Source delivery grants zero runtime-adoption authority.
Source delivery grants zero retry authority.
Native Edit grants zero alternate form for an existing or recorded denied operation.
Retry a refused command in another form only when the refusal reason is fixed or the new form meets the rule the refusal names.
Preserve every effective refusal, tool and hook denial, and affected-session hold.
Require actual cause resolution and fresh applicable disposition before any affected-session attempt.
Source delivery, installation, version, cache, restart, executor and tool changes alone resolve zero existing denial.
A contract-gap refusal is a writer or driver refusal whose quoted reason is only that its loaded contract lacked the route the decision selected.
It made zero protected reads and named no content, scope, protected-access, hook, permission or tool finding.
Its cause resolves only when a new CoC decision, with a new SHA256, quotes the refusal verbatim, names that sole cause and records its zero protected reads.
The next agent in the refusing role must also find the selected route heading in its own loaded contract by native Read, under a section that implements that route and does not refuse it.
A follow-on refusal is a refusal whose only reason is that an earlier refusal stayed effective; it also made zero protected reads.
A follow-on refusal resolves with that earlier refusal when this rule resolves the earlier one and the same CoC decision quotes the follow-on refusal verbatim.
Hook, permission and tool denials, `REFUSED` tool results, and any refusal with a reason outside these two definitions never qualify.
The fresh disposition and every other route requirement still apply.
The driver applies zero protected edits; the writer has zero publication authority.

## Owner-approved protected-row subject route

Apply this route only to future briefs after verified runtime adoption.
A matching existing denial blocks the action, recipient and scope under every route.
Preserve every effective tool, hook, owner and loaded-instruction refusal and every affected-session hold.
Native Edit grants zero alternate form for a denied operation.
Require actual cause resolution and fresh applicable disposition for affected sessions before any attempt.
Retry a refused command in another form only when the refusal reason is fixed or the new form meets the rule the refusal names.
Source delivery, installation, version, cache, restart, executor and tool changes alone resolve zero existing denial.
A contract-gap refusal is a writer or driver refusal whose quoted reason is only that its loaded contract lacked the route the decision selected.
It made zero protected reads and named no content, scope, protected-access, hook, permission or tool finding.
Its cause resolves only when a new CoC decision, with a new SHA256, quotes the refusal verbatim, names that sole cause and records its zero protected reads.
The next agent in the refusing role must also find the selected route heading in its own loaded contract by native Read, under a section that implements that route and does not refuse it.
A follow-on refusal is a refusal whose only reason is that an earlier refusal stayed effective; it also made zero protected reads.
A follow-on refusal resolves with that earlier refusal when this rule resolves the earlier one and the same CoC decision quotes the follow-on refusal verbatim.
Hook, permission and tool denials, `REFUSED` tool results, and any refusal with a reason outside these two definitions never qualify.
The fresh disposition and every other route requirement still apply.
The driver applies zero protected edits; the writer publishes nothing.
A product-limit or cost approval alone grants zero protected read, subject, paired-field, retirement or pin-edit authority.
Require a separate exact written CoC decision for each subject edit under the supported writer's loaded subject route.
That decision cites owner event `dc03370c-c170-4284-b9e4-75aac2dcaab0` on Input `1b143a6d-e303-4fe4-82ab-69c0f235a4a5` as its authority.
Keep Owner-scoped protected row access independent, with its full owner-event verification requirements.
Apply the exact access and edit provenance requirements in the supported writer's loaded subject route.
Keep all other routes' subject and field freezes binding outside that exact approved route scope.

### Future ordinary-file identity checkpoints

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

An explicit owner refusal blocks all routes for that edit until applicable owner authority resolves it. Apply your own loaded definition; a checkout, cache entry, or version supplies zero additional authority. Prospective source changes and their delivery supply zero runtime-adoption, affected-retry, or action authority. For ordinary lane-derived review of a row file the PR creates absent at the CI base, use the last PR commit before the re-anchor as the before tree and row comparison base. Keep the original CI base for causality and evidence; preserve every other route condition. If only main merges into the PR branch changed the subject after the last PR-authored commit before the re-anchor that edited that row file, use that commit as the before tree instead, and require that no PR-authored commit after it changed the subject. A merge commit changes the subject as a PR-authored commit unless its subject blob equals the subject blob of the clean automatic merge of its parents. Preserve existing loaded-session restrictions and affected-session holds. A fresh writer or driver belongs to the named hook-fix lane when its starting brief quotes the CoC ruling naming that lane's owner. Keep actors outside that lane refused.
When diagnosing a contract mismatch, report the loaded identity evidence available and identify unknown fields without inference. Repairing missing verification evidence resolves only that evidence gap; it cannot override a binding prohibition or tool denial.
Retry rule: after a hook or permission refusal, an agent may retry in another form when the refusal reason is fixed or the new form meets the rule the refusal names. A script file, another interpreter, a module flag or a wrapper command is another form; it must meet that rule too. An agent may always ask its superior for permission to run the refused command. A writer asks its driver, a reviewer asks its coordinator, a driver asks its chief, and a chief asks the CoC. The CoC asks the owner only for product, billing, security policy or big architecture. The superior may grant the request, or run the command itself when it considers that appropriate. The superior records the grant or the run in the lane state file. Never ask the owner to paste or run a command. A version, restart, or new session alone lifts nothing. Checks that the brief names stay permitted when the hook admits them.
Safety blocks: keep destructive actions, secrets, production data writes, flag flips, deploys, customer-data deletion, protected paths, and approval, GO, installation, and publication holds blocked as their own rules say. A retry in another form never bypasses a safety block. A superior grants or runs a command only within its own authority, and its own hooks and permissions apply. Protected mutation-row edits keep the row routes and the granted protected-row re-anchor below. Granted protected-row re-anchor: a hook can deny only the shell method, such as a heredoc, `sed` or `python`, of an exact row re-anchor. When that re-anchor is on the explicit-pair or lane-derived route that its verified owner grant covers, one fresh writer applies that route's approved edit once with native Edit and `replace_all=false`. The brief names the CI-named row file and the unique row ID. The edit changes only that row's paired `old` and `new` fields with the identical mutant edit: the CoC-approved pair on the explicit-pair route, or the subject's new source text on the lane-derived route. Require that route's independent not-weaker review before the push. Refuse a native Edit outside the named file, row or paired fields, a second attempt, a denial of the native Edit itself, and every content, scope or protected-access denial. On the lane-derived route, when the brief names the sanctioned row re-anchor tool, run it once in place of native Edit with the brief's row file, row ID, subject, base and head; the tool derives and checks both fields and prints only results. A tool refusal or hook denial ends the attempt. This tool is the only process form for a protected row edit. The tool's statement scan and whole-file `tomllib` check print no row text and are the only exception to the no-whole-file-parse rule; the writer still reads no row lines. This tool form extends only the Granted protected-row re-anchor above, under its existing scope and independent review requirements. The [row re-anchor tool brief](#row-re-anchor-tool-brief) lists the fields that supply this evidence; the tool run is its own single attempt under one CoC grant and its head SHA, unused by an earlier attempt that made zero native Edit calls and zero tool runs, and used by any native Edit call on the row, any tool run, and any refusal or hook denial of the tool command. A new CoC grant bound to a head SHA with no used attempt on the row gets one fresh attempt only when every earlier used attempt ended only in a tool error, such as a native Edit no-match or file-changed error, and no earlier attempt on the row drew `REFUSED` or a hook or permission refusal or denial other than the listed method-only shell denials; any other grant for a head that already used its attempt frees nothing. The attempt record names each native Edit call and tool run on the row with the grant's CoC decision file, its SHA256, the head SHA and its outcome.
Message-format rule: a `text_lint.py` refusal whose findings are all formatting findings always permits a resend with the findings fixed. Examples include glued words, sentence or word limits, and a missing `Facts` heading. Apply only the exact formatting remedy; preserve the action, recipient, scope, authority, non-prose fields, owner provenance, and choice identifiers. A missing `Facts` heading organizes supported existing facts only; invent zero facts, evidence, approval, or authority. Cite the receipt the refusal names as `<!-- ultraship-receipt:ID -->` in the resent prose, or resend without a marker; the hook checks both. Only the hook writes receipt state; agents never read, write or reset the receipt store. A MAC-valid receipt that another agent sends to the receipt's own agent is a relay: a new message that keeps normal checks and consumes no receipt. After a message-format refusal of an `Agent` call, a coordinator may give a fresh agent a new brief for the same approved scope; the hook refuses a receipt marker in an `Agent` or `Task` prompt. A refusal that is not formatting-only permits a resend after the content meets the rule the refusal names, or after the superior grants it.
Coordination gate: for the driver's `Agent` dispatch, resend when the denial explicitly identifies `Coordination gate error` and an exact text remedy. Require unambiguous gate identity and remedy and the applicable loaded contract; the denial date alone never determines eligibility. Apply only that remedy; preserve the action, recipient, scope, authority, and exact owner-provenance checks. Recheck current version, status, and answer provenance before the resend.

A superseded-ruling free is the one exception to every rule that keeps a used protected-row attempt, or its record, consumed. It is also the one exception to the rule that a refusal outside the contract-gap and follow-on definitions never qualifies. Only a fresh CoC row decision file with a new SHA256 grants it, for exactly one further attempt on one named row. That file names the repository, PR, row file and row ID, and quotes each earlier refusal on that row verbatim. It records that every earlier attempt on that row made zero protected reads, zero edits and zero commits. It records that the first refusal named only a chief or CoC ruling, never the row content. It records that each later refusal named only that first refusal or the attempt it used. It supersedes that ruling by name, and it resolves the quoted refusals for that row only. Refuse the free when the file lacks any of these records. A row gets at most one free, whatever the decision file or head SHA; refuse a second free. Only the driver with exclusive custody of the row's attempt record may record a free. Before it admits one writer, the driver records the free, the decision file, its SHA256 and that writer on the row's attempt record. A writer refuses the free when that record is missing or names another writer. Content refusals, method bans, `REFUSED` tool results, and every hook, permission or tool denial keep their row attempts used; no decision frees those attempts. The freed attempt keeps every other route requirement, authority, independent review and publication hold.
