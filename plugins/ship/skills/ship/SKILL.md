---
name: ship
description: Ship a scoped engineering task through planned slices, frozen-SHA reviews, one fix batch, a CI-green pull request, and a ledger-backed completion gate. Invoke for an explicit /ship:ship request or a chief lane contract. Modes full (default), light, goal, help.
argument-hint: "[full|light|goal] <task> | help"
---

# Ship

Deliver the task in `$ARGUMENTS` to a ready-for-review pull request that passes the completion gate. An explicit `/ship:ship` request or a chief lane contract authorizes this workflow within the user's permissions.

## Arguments

Consume leading `full`, `light`, and `goal` tokens. The rest is the task, verbatim.

| Input | Result |
|---|---|
| `<task>` or `full <task>` | All 13 steps in [pipeline](references/pipeline.md) |
| `light [<task>]` | Steps 1, 3, 5, 7, 9, 10, 12. Without a task, use the chief lane contract or the latest clear task in the chat |
| `goal [light] <task>` | Print the `/goal` block from [goal](references/goal.md) and stop |
| `help` | Print this table and stop |

Empty input asks for a task. Freeze scope and success checks before any code is written.

## Roles

The session that runs this skill is the driver. It plans, dispatches, records, and ships. Writers write code.

Act by default. The brief grants this lane's authority; use it in the same turn and never ask for it again.
Routine lane work needs no new GO or receipt: reads, read-only scripts, touched-file tests, lint, typecheck, commits, pushes, the PR, and a granted merge after its required review and CI.
Stop a step only for a hook denial, a failed check, a hard rule, an owner refusal, a special-run GO (mutation, timing, shared database, paid), or an owner-only item.
Owner-only items: product, billing, security policy or tenant isolation, big architecture, customer-data deletion, new recurring spend, flag flips or deploy changes, public output in the owner's name, and credentials only the owner holds.
An unverified detail that no rule names is not a stop: name it in one line and continue. A rule that names a missing receipt or evidence still stops its step.
End each turn with a forward action: a writer dispatch, a commit, a push, a PR update, or a merge. A board edit alone is not progress.
In a status message, never restate standing holds; send what changed, what it means, and the next action. Briefs still carry their required restrictions.
Bad: "Bridge admission remains held; execution credit stays zero." Good: "Tests pass at 1a2b3c4. I push and open the PR now."

Read [owner decisions](references/owner-decisions.md) before dispatch. Apply its chief-managed CoC delivery contract when a chief owns the run.
Apply its [helper standing request](references/owner-decisions.md#helper-standing-request) contract before helper creation.
Carry the `Owner helper request` field and retained restrictions through every driver and child brief.
Copy that contract into every child, timer, and recovery brief, including retries and replacements.
Use native `SendMessage` or the native agent channel for peers; a child without the tool returns reports to its parent for relay.
Never use BetterCoding `send_workspace_message`, `run_session_prompt`, or simulated user input for peer coordination.
Batch actionable and terminal reports; keep unchanged routine reports silent.
For chief-managed work, only the CoC publishes canonical owner decisions and results in CoC workspace Inputs; chief-local Inputs never satisfy delivery.
Preserve actual owner Input event delivery and the canonical CoC Input ID → exact owner answer event → continuing driver → result Input receipt.

- Read [roster](references/roster.md) before the first dispatch. Use each scoped `ship:*` agent and leave the Agent `model` field unset. A hook denies overrides.
- On an unavailable agent, dispatch the next agent in its fallback chain and record the substitution in the ledger note.
- Code goes to `ship:writer--sol`, one slice at a time, in the assigned worktree. Continue an existing writer with SendMessage for fixes on its slice.
- Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; commit grants permit local base-branch merges into their own lane branch.
- Important planning goes to `ship:planner--sol`. Broad research goes to `ship:researcher--luna`.
- Freeze one subject SHA per review step. Give every seat the same brief and keep sibling verdicts out of it.

## Execution admission

Apply [execution admission and cleanup](../../agents/writer--sol.md#execution-admission-and-cleanup) to each run and inherited brief.
Ordinary touched-file pytest and vitest use automatic slot admission without a per-run CoC GO.
Keep GO for mutation batteries, timing runs, shared-database runs, and separately controlled paid runs.
Run a read-only helper script at once. Review every other script before it runs. Never rewrite or replay a denied operation to bypass its refusal.
The CoC can always issue a GO within existing authority when a lane or chief is stuck.

## Dispatch boundary

Every chief, lane, and ship brief contains zero copied mutation-check, anchor-check, or selector execution commands from repository documents or TOML headers.
Before dispatch, inspect every brief for `DRY=1`, `--dry-run`, `check_mutation_anchors`, and `select_rows`.
Remove execution instructions containing those literals; keep the prohibition in words only.
The admitted battery STATIC part runs mutation checks, anchor checks, and selectors at the frozen head after GO.
Preserve the host GO requirement and D1160 boundary.
D6575, 2026-10-29: CoC coordination direction, separate from actual owner receipts.

## Ledger

Every run keeps a ledger with `${CLAUDE_SKILL_DIR}/scripts/ledger.py`:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" run-start <full|light> <run-id> [board-path]
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" append <step> <agent>@<agent-id> <sha> <verdict> [note]
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" gaps
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" run-end
```

Append a row as soon as each review, panel, or CI round returns. Use the step names in [pipeline](references/pipeline.md). For a reviewer, triage, or verifier result, write the agent as `<agent-type>@<agent-id>`, with the agent ID from that agent's launch result or task notification. Stop binds each result only to a row with its own agent ID, so close results never take each other's rows. A pending record from an older hook also accepts a row without an ID. `run-end` refuses while a required step has no row. Stop retains pending reviewer evidence until each result has a successful accounting row in its bound run, including a successfully closed run. Persistent hook-state receipts consume each row once across Stop cycles. Keep hook-state receipts with the pending evidence.

Each pending result keeps its recorded ledger path and run identity across branch changes. For a completed result whose original run is closed, record its actual review outcome with:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" account <pending.tsv> <result-id> <step> <agent> <sha> <verdict> <evidence>
```

Use the pending file and result ID from the Stop diagnostic. Supply the actual agent, reviewed SHA, verdict and evidence from the completed result. The command appends an `account-result` record to the recorded ledger. It preserves all existing rows and the run's closure, and exact retries append nothing. This bookkeeping covers only the named result; it grants no pipeline step, review or completion evidence of its own. Never reopen a closed run or invent review rows to clear Stop.

When an accounted result is bound to another result's row, move its credit with:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" correct-binding <result-id> <ledger-line> <reason>
```

The line is the 1-based line of the correct review row in the bound ledger file, in the same run and with the same agent column. The command refuses a ledger with blank lines or other line breaks. The command appends a `correct-binding` audit row first and never rewrites earlier rows. It then moves the receipt; when another result holds the target row, the two results swap rows. A retry after a crash appends no second audit row, and an exact retry after success changes nothing.

A linked checkout with an external common Git directory uses its existing parent `.scratch/ship-ledgers` with checkout and branch isolation. First use imports the legacy branch history and open run once, with canonical path and SHA256 provenance. The sole driver must hold run custody and retire old writers before import; old legacy writers can race the snapshot. Import needs legacy read permission and local write permission. All subsequent access uses the local ledger. Full checkouts retain the common-directory default. Ambiguous layouts require an absolute `SHIP_LEDGER_DIR`; the override directly contains branch files. See [ledger storage and permissions](../../README.md#hooks).

## Completion gate

Anchor every claim to the current pushed head SHA:

```bash
gh pr view "<PR URL>" --json isDraft,headRefOid,statusCheckRollup,reviewDecision,mergeStateStatus
gh pr checks "<PR URL>" --required
```

All conditions must hold:

1. The intended head is pushed and the working tree is clean.
2. Required CI passes on that head. An empty required-check list means CI did not start.
3. Reviews cover that head, and every P0 and P1 finding is fixed or answered with evidence.
4. Better Review and human threads are resolved: zero unresolved threads.
5. End-to-end evidence covers that head at the deepest safe level.
6. `ledger.py gaps` reports none, and `run-end` succeeds.
7. Every UI PR passes the [real-browser premerge gate](references/pipeline.md#ui-browser-gate); the default route requires the current pushed head and matching preview.
   This includes dashboard `frontend/app/**`, UI-affecting frontend design-package changes, and marketing UI through its existing Vercel preview route.
   Only when preview sign-in requires secret handling, accept qualified local real-browser evidence under the pipeline's conditional local route.
   Require the same exact pushed head, Chromium interaction, synthetic isolation, safe screenshot evidence, and post-check head equality on that route.
   Local evidence qualifies only for behavior faithfully reproduced by the local stack.
   Preview/deployment/config-dependent behavior retains its preview-proof hold when appropriate preview proof is unavailable.
   Preserve every credential refusal and user/project rule on both routes.
   Missing or failed browser evidence blocks merge. CI and review supply zero substitute browser evidence.

Re-read `headRefOid` after verification. A changed head reopens the affected steps. Finish with the direct PR URL. Merge and production actions need their own authority.

## Proof after merge

Mutation proof runs after merge (owner decision, 2026-10-31: merge on green CI and review; the mutation proof runs after the merge).
The required real-browser UI check runs before merge and remains a merge gate.

- The merge gate requires green CI on the head, an independent review, every review thread dispositioned, and applicable real-browser UI proof.
- Send the merge within 2 hours of green required CI.
- Run the proof once at the merge commit within 24 hours of the merge. Post its record on the merged PR.
- A survivor's fix ships in a follow-up PR.

## Boundaries

Never widen, raise, or relax a limit, cap, timeout, budget, bound, or guard constant — and never adjust a validator or test to accept a new value — to make a check pass. Report the blocking bound and fix the consumer side. This covers test baselines, fixtures, and goldens. Exception: an owner-requested product-limit change is a feature (owner rule, Input 2b7e497e-a794-4ab2-a62c-0f1748396967, owner_ui event 485, a_allow). The writer implements only the specifically requested product limit, including when that limit exists on origin/main. Add boundary tests that accept the new limit and refuse the limit plus one unit; for byte limits, refuse one additional byte (for example, accept 536870912 bytes and refuse 536870913 bytes). For every bound the owner did not ask to change, preserve the stop-and-report rule and fix the consumer side, subject to the existing branch-only and same-guarantee test-edit exceptions below. This product-limit exception grants no authority to change unrelated safety, security, resource, budget, or timeout bounds or to weaken other guarantees. Preserve normal review, CI, and applicable consent requirements. Record the owner request and its exact scope in the brief and PR body. This product-limit exception applies independently of the two exceptions below. This rule covers limits that exist on origin/main. Exception: a limit, cap, timeout, budget, or bound that only this PR branch added is the lane's design choice (owner rule, Input 6e43dda9-a1b8-4b0e-a8c8-f3525a67a5e9). Run `git fetch origin main` first and record the `origin/main` SHA; when the fetch fails, the exception does not apply. Compare the behavior the bound constrains, not its path or name: `git grep` main's whole tree and read the branch diff (`git diff origin/main...HEAD`) for the same invariant, including replacements, duplicates, validators, test baselines, fixtures, and goldens. A missing path on main is not enough evidence. When main has no such bound, change or remove it without an owner question, and record the reason and the main SHA in the PR body. Every bound already on main keeps this rule, also when the branch moves, renames, replaces, or changes it. Exception: a test, fixture, mutation row, census or register edit is allowed without an owner question after one council round (no Fable or cf-* models) agrees that the guard keeps its guarantee (owner grant 2026-10-26: "ok I give you from now onwards full power to change tests, no need to check with me, just do one council round to analyze it makes sense and is appropiate, and do it."). Weakening a test to hide a real regression stays forbidden. Record the council verdict and the owner words in the PR body. Exception: no step waits for a human to apply an edit. When the executor is certain and its Chief or the CoC checked the change, that check replaces the council round, and an agent applies it (owner order 2026-10-30: "if agent is certain that its ok and he checked with his CoC or Chief ALL GOOD remove that blocker everywhere"). Record that check in the PR body.

The fixed-event comparator in the following paragraph applies only to the standing owner-rule branch.

Approved test adaptations follow the writer contract (owner rule, Input `32c223a4-6bd9-43d1-b049-19a3990d2379`, workspace `b8fed386-cf11-40fe-b14f-425e6331ee41`): five standing test adaptations cover register classification, a census re-pin from CI output after a reviewed body PASS, a race-helper timeout replacement, a setup-only fixture change, and the exact paired-anchor category below, which also retires a row the PR's own diff removed. The driver puts the Input ID and workspace ID in the writer brief. For a writer without a `get_input` tool, the driver or the CoC runs `get_input` and the brief also records the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name; the writer stops on any mismatch with its definition. Loosened assertions, widened bounds, and deleted checks stay forbidden.

### Fifth standing adaptation

Refresh paired `old` and `new` anchor strings only in exact approved PR-owned rows.
Category 5 uses exactly one route below, named in the brief.
Every requirement of the named route applies; route-specific sentences bind only that route.
Pairs from an admitted derivation gate stay in the private-proposal route.
A row that the PR's own diff removed, with the source behavior it guarded, uses the removed-behavior retirement route.
Category 5 requires loaded edit/access authority before any writer edit. On its named route, Owner-scoped protected row access below is that authority when all its requirements hold, including an identical mutant edit and an independent not-weaker review.
Written approval and CI evidence grant zero protected access and do not replace applicable loaded edit/access authority.
The PR author product diff supplies supporting evidence only at the CI-named subject file.
The CoC reviews the same-operation, same-claim reason; product diff text alone cannot establish equivalent mutant semantics.
Each approved row has an exact committed row-file path, unique row ID, and CI-named subject file.
PR ownership requires the recorded base/head diff and exact approved row allowlist; a subject name alone is insufficient.
Evidence binds the repository, PR, base SHA, author head SHA, tested merge SHA/tree, CI run ID, attempt, and job ID/name.
The tested merge must contain the recorded base and author head; changed evidence invalidates the approval and applicable GO.
Dry-run proof and CI at the new head require separate admission; this adaptation authorizes no mutation command execution.
Only the exact approved paired `old` and `new` fields may change under category 5.
The removed-behavior retirement route is the sole exception to the paired-field limit: it appends one `[[retired]]` table per approved row and changes no existing line.
On that route, the CoC decision it names is the loaded edit authority.
On that route, the independent review that the guarded behavior is gone replaces the CI-named subject, same-operation, same-claim, and identical-mutant requirements.
Row identity, claims, subjects, designated tests, pins, operators, assertions, bounds, and unrelated fields remain unchanged under category 5.
Missing, ambiguous, stale, mismatched, or unlawfully obtained evidence blocks the edit.
Owner provenance, effective refusals, protected holds, and zero writer publication authority remain binding.
Except for the reads that Owner-scoped protected row access permits on its named route, this adaptation grants no TOML search or parse authority, protected reads, or anchor extraction.
Drivers prepare category 5 evidence; writers verify it and apply only separately permitted exact edits.

For the narrow protected-read/edit exception, apply Owner-scoped protected row access below.

#### Owner-scoped protected row access

Owner authority: Input `31f787fe-1463-4447-82fa-6a5e21e17a87`, version 1, choice B, in CoC workspace `b8fed386-cf11-40fe-b14f-425e6331ee41`.
The `owner_ui` event is `aacba25c-5e99-438e-85c7-9bb128ecf4b8`, dated 2026-11-08T18:03:15.357469375Z.
The event hash is `d56c4fd20ef712921654f06869818b5b2189a13e9b52249b32379ca5362468a8`.
Owner-selected option B: "Each lane moves the protected rows its own PR breaks: same test, new line text, nothing weaker. An independent reviewer checks every row change, and the mutation proof still runs after merge."
Input context: "Peral keeps CI runner and merge queue changes."
Owner global CLAUDE.md standing grant: "The CoC decides CI/CD, testing and tooling items for me. This includes a lane reading and re-anchoring the protected mutation rows that its own diff breaks, with an identical mutant edit and an independent not-weaker review."

Use this clause only as category 5's separate loaded read/edit authority for the explicit-pair or lane-derived route, or as scoped read authority for the owner-approved protected-row subject route.
This clause overrides only blanket protected-read/edit restrictions for the exact scope below.
Preserve higher-priority instructions, effective refusals, protected holds, and tool or hook denials.
Require the driver's complete verified owner-event record and exact scope in the brief.
Bind full Input/workspace UUIDs, current version, event id/hash, choice, actual owner answer, verifier name, and verification time.
Record selected choice B and `payload.answer.text=null` separately; distinguish the selected option text from Input context.
Require `event_type=answer_submitted`, `actor_kind=owner_ui`, and `payload.no_answer_yet=false` for this Input and current version.
Apply the task-specific owner-event verification contract; keep its event comparator separate from the standing rule.
Use `get_input` directly when available; accept the driver's or CoC's complete verified record only after tool absence or auth/tool error.
An authoritative mismatch blocks access and cannot use fallback.
Require CoC naming of exact row-file paths and unique row IDs from that PR's failing anchor CI log.
Require the recorded base/head diff to show that the PR itself breaks each named row.
Limit reads to those exact named files and rows; read no unrelated rows or whole protected files.
Preserve all category 5 source identities, CI evidence, route requirements, and applicable execution admission.
Require the reviewer to differ from the PR author and applying writer.
Preserve the same designated test and guarantee, equivalent mutant semantics, assertions, bounds, and every unrelated field.
Refuse missing, stale, mismatched, ambiguous, or unrelated scope before any protected read or edit.
Keep mutation proof after merge under separate applicable execution admission.
Retain Peral's authority over CI runners and the merge queue.
On the lane-derived or owner-approved protected-row subject route only, permit the row-ID lookup and row-line reads specified in that route.
Except for the named row-ID lookup and row-line reads on the lane-derived or owner-approved protected-row subject route, this clause grants zero TOML search/parse or anchor extraction authority. This clause grants zero mutation or other execution, or writer publication authority.
CoC naming alone grants zero authority outside this loaded exception and its verified owner scope.

#### Explicit-pair route

Apply only CoC-approved exact current/replacement bytes for both paired `old` and `new` fields.
Require independent same-operation, same-claim review of every row change before CoC pair approval.
Bind reviewer identity and approving verdict to the exact pairs, row scope, source identities, and CI evidence.
Category 5 requires written CoC approval supplying both exact replacement strings for each CI-named approved row.
Category 5 approval supplies exact current and replacement bytes for both `old` and `new` fields in each approved row.
Existing CI identifiers and quoted evidence suffice; this adaptation requires no producer, artifact, or digest.
Evidence includes the quoted job log line and the job log URL where supplied.
Drivers document separate applicable loaded edit/access authority and both current/replacement pairs; writers verify them before any category 5 edit.

#### Private-proposal route

Use the private-proposal route only with separately authorized and admitted derivation before any protected access.
Freeze exact current/replacement pairs privately with source identity and the exact approved row scope.
Written CoC approval binds the exact private proposal identity and SHA256, derivation launcher identity and receipt, source, rows, and CI evidence.
Require independent in-gate review of the same-operation, same-claim evidence and exact approved scope.
The reviewer differs from the PR author, the derivation operator, and the applying writer.
Complete semantic review before written CoC approval in a separately authorized and admitted review context.
A derivation admission supplies zero independent review authority.
A lawful non-content review receipt binds reviewer identity, verdict, review admission identity, reviewed proposal SHA256, source identity, and exact scope.
Written CoC approval binds that semantic review receipt, including its reviewer, verdict, review admission, reviewed proposal SHA256, source identity, and exact scope.
A success receipt without bound semantic review remains insufficient for approval or application.
Application refuses any mismatch between reviewed, approved, and applied proposal SHA256 values, source identities, or exact scopes.
Application verifies the bound semantic review receipt and its approving verdict before any edit.
Private CI evidence outside admission contains only content-free FAIL or WARN summaries and metadata, including the job log URL where supplied.
Never open or quote anchor-bearing job log lines outside separately authorized and admitted access.
A digest proves identity only; derivation success and a checksum cannot replace semantic review or authority.
Approvers review lawful non-content evidence without opening the protected proposal.
On this route, the brief and PR body identify the exact edit by proposal SHA256, row-file paths, row IDs, and fields.
The brief and PR body contain zero pair bytes.
Application requires separate applicable loaded edit/access authority and fresh admission.
Application admission binds the stage-two launcher identity, exact approved proposal, and permitted checker scope.
A derivation GO supplies zero application authority.
Identify each derivation, review, and application gate by name and SHA256, never by an executable command line.
Keep every brief command-free under the existing dispatch boundary.
Inside the admitted application gate, verify proposal SHA256, exact current bytes, source identity, and approved scope before any edit.
Apply only the approved paired fields and preserve every unrelated field.
Run only the separately permitted checker inside its admitted scope.
Refuse stale source, an altered proposal, ambiguity, missing evidence, or missing authority.
Keep protected bytes inside admitted gates; emit zero raw pair bytes outside those gates.
Approved proposal or launcher digests never override effective denials, protected holds, or higher-priority instructions.
This instruction grants zero derivation, protected access, application, checker execution, or writer publication authority.
Drivers and approvers use lawful non-content evidence; protected pair verification and application stay inside separately authorized and admitted gates.

#### Lane-derived route

Require the owner-scoped protected row access authority above and name this route in the brief.
Require CoC approval of the exact row allowlist before any protected read or edit.
Limit scope to CoC-named exact row-file paths and unique row IDs from the PR's own failing anchor CI evidence.
Require the recorded base/head diff to show that the PR's own subject change breaks each named row.
Permit the applying writer to locate each named row by its row ID inside its named file.
Read only that row's lines; permit no whole-file parse, unnamed-row read, or search outside the named files.
Replace only the paired `old` and `new` fields to match the subject's new source text.
Preserve the identical mutant operation: the same transformation from `old` to `new`.
Keep row ID, claim, subject, designated test, pins, operator, assertions, bounds, and unrelated fields unchanged.
Before publication, require an independent reviewer to read the same named rows before and after the edit under the same scoped access authority.
The reviewer may instead use authority A of its own definition, the owner global CLAUDE.md grant; that route needs no owner-event relay.
Require that reviewer to differ from the PR author and the applying writer.
Admit each reviewer row read with the [reviewer admission record](references/owner-decisions.md#reviewer-admission-record-for-protected-row-reads).
Require the reviewer to confirm the same test, same claim, identical mutant edit, and nothing weaker for every row.
Bind the review receipt to reviewer identity, approving verdict, commit SHA, row-file paths, row IDs, and CI evidence.
Require CoC approval of that review receipt before publication; changed source or evidence invalidates the receipt and approval.
The CoC supplies no pair bytes on this route.
Keep messages, briefs, and PR bodies free of pair bytes and TOML text; identify edits only by path, row ID, and field.
Require separate admission for every mutation or checker execution; keep mutation proof after merge.
Preserve zero writer publication authority, effective refusals, tool and hook denials, protected holds, and Peral's CI-runner and merge-queue authority.

For newly admitted future operations, use native Edit with replace_all=false.
Require a unique approved row-ID-contained old_string within the approved row extent.
Change only the approved paired old/new fields; preserve every frozen field.
Refuse missing or ambiguous matches and reads wider than the approved row scope.
Keep every hook classifier decision unchanged.
Native Edit grants zero alternate form for an existing or recorded denied operation.

#### Removed-behavior retirement route

Use this route only to retire a protected row that the PR's own diff removed together with the source behavior that the row guarded.
Require the CoC decision that admits each retirement and name this route in the brief.
On this route, the loaded edit authority is that CoC decision (owner standing grant: "The CoC decides CI/CD, testing and tooling items for me"); Owner-scoped protected row access grants nothing on this route.
Limit scope to CoC-named exact row-file paths and unique row IDs from the PR's own failing anchor CI log line that reports the row `in the base file, missing at HEAD`.
Require the recorded base/head diff to show that the PR removes each named row and the source behavior that the row guarded.
Require the PR body to give the reason for each removed row.
Append exactly one `[[retired]]` table per named row at the end of its named file.
Set its `id` to the row ID and copy its `reason` verbatim from the PR body as one TOML basic string, escaping `\`, `"`, and every control character such as a line break.
Start the appended text with an empty line, so it never joins the last existing line.
Change nothing else in the named file: no existing line, row, field, pin, or table.
Another approved exact edit to the same file, such as a `claims` pin change, needs its own authority and its own commit; this route grants none.
Read, search, or parse no existing content of the named file.
Permit the applying writer to parse only the appended text, never the named file, to check that it is valid TOML.
Append with one isolated `python3 -I -` heredoc that imports only `tomllib`, checks the appended text with `tomllib.loads`, and appends to the literal absolute row-file path.
Run nothing else in that Bash call; get the line counts with `git diff --numstat` in a later, separate call.
Check the retirement commit only with content-free line counts for each named file: added lines only, zero deleted lines.
Refuse a row whose guarded behavior still exists in any form, including a changed form at the same site, or that moved or has a replacement row.
Before the push, require an independent reviewer to run its Removed-behavior retirement review and confirm for every named row that the guarded behavior is gone and not moved, and that the file change is only the appended tables.
Require that reviewer to differ from the PR author and the applying writer.
Bind the review receipt to reviewer identity, approving verdict, CoC decision identity, commit SHA, row-file paths, row IDs, and CI evidence.
Require CoC approval of that review receipt before the push; changed source or evidence invalidates the receipt and approval.
Keep messages, briefs, and PR bodies free of pair bytes and row TOML text; identify each edit only by path, row ID, and the appended `[[retired]]` table.
Beyond that check of the appended text, this route grants zero TOML search or parse authority, protected reads, or anchor extraction.
Require separate admission for every mutation or checker execution; keep mutation proof after merge.
Preserve zero writer publication authority, effective refusals, tool and hook denials, protected holds, and Peral's CI-runner and merge-queue authority.
Drivers prepare retirement evidence and the reviewer's line counts; writers append only the named `[[retired]]` tables.

### New lane-owned row review route

Use this route only when the brief explicitly selects the new lane-owned row review route.
Verify ~/.claude/CLAUDE.md directly under heading CoC decisions (standing grant).
Require the exact sentence: The CoC decides CI/CD, testing and tooling items for me.
Refuse missing, unreadable or mismatched delegation before protected access; accept zero relay for this direct verification.
Require exact CoC read admission naming the independent reviewer, repository, PR, base SHA, author head SHA and frozen final commit.
Require explicit protected-read authority for exact files, unique new row IDs, complete approved extents and named commits before any lookup or read.
Require lawful content-free evidence of lane ownership and absence of each new ID at the base.
Reject existing IDs, unrelated rows, ambiguous extents and stale evidence.
A named new file alone establishes zero authority over every row inside it.
Keep existing-row re-anchoring, disposition and retirement routes separate and their authority requirements unchanged.
Keep fixed existing-row grants, event coordinates and permitted lookup route lists unchanged.
Preserve fixed-event provenance whenever the brief invokes a separately applicable owner-event route.
Read authority grants zero derivation, writer creation, execution or publication authority.
Permit only named row-ID lookups and approved row-line reads at the frozen final commit.
Read zero adjacent rows or whole protected files; parse zero whole protected files.
Require the reviewer to differ from the author, applying writer and proposal deriver.
Review each claim, designated test, subject binding, operator, mutant validity and the test's detection mechanism.
Require independent evidence that the designated test detects the claimed violation.
Preserve assertions, bounds, policy guarantees and every unrelated entry.
Require scoped creation authority for the author and applying writer as separate recorded evidence.
Bind the receipt to reviewer identity, verdict, exact authorities, repository, PR, base SHA, author head SHA, frozen final commit, files, IDs, extents and ordinary evidence identities.
Require CoC approval of the frozen receipt before publication.
Changed source, authority, scope or evidence invalidates every affected receipt and approval.
Keep proof execution after merge under separate applicable admission.
Grant zero reviewer edit, execution, retry or publication authority.
Report only paths, IDs, fields, digests and content-free findings.

Apply this route only to future briefs after verified runtime adoption.
Source delivery grants zero runtime-adoption authority.
Source delivery grants zero retry authority.
Source delivery grants zero installation authority.
Source delivery grants zero publication authority.
Preserve every existing refusal, tool and hook denial, and affected-session hold.
Never replay a denied command, equivalent operation or substitute actor while its refusal remains effective.
Require actual cause resolution and fresh applicable disposition before any affected-session attempt.
Source delivery, installation, version, cache, restart, executor and tool changes alone resolve zero existing denial.

### Lane-owned disposition route

Use only the lane-owned disposition route explicitly named in the brief, outside category 5.
Keep category 5, its fixed grants and every existing route requirement unchanged.
Owner-scoped protected row access, Authority A and Authority B grant nothing on this disposition route.
Apply the following delegation and two-decision requirements only when the brief selects retirement.
For retirement, directly verify ~/.claude/CLAUDE.md, heading CoC decisions (standing grant), and the exact sentence: The CoC decides CI/CD, testing and tooling items for me.
Refuse missing, unreadable or mismatched delegation; accept zero relay for this verification.
Require the first exact CoC decision to admit explicit protected-read authority for the independent proposal reviewer only.
Name exact files, unique row IDs, full approved table extents and one pre-edit commit in that read admission.
Require that reviewer to establish removed guarded behavior and complete table extent before the ordinary retirement proposal exists.
Prepare the ordinary retirement proposal only from the content-free extent receipt and ordinary source and test evidence.
Limit that proposal to path, row ID, escaped replacement table, reason and extent line range at the named commit.
Include zero original row bytes or anchors in the ordinary retirement proposal.
Require the second exact CoC decision to bind the ordinary proposal SHA256 and independent review receipt.
Name the applying writer, permitted protected reads, exact retirement, independent applied reviewer and final-commit read scope in that decision.
End the retirement-only authority block; apply every subsequent shared requirement to both branches unless explicitly scoped.
For changed mutant semantics, require a current task-specific owner event naming exact protected reads, rows, semantic adaptation and permitted gates.
Require that event and the admitted gates to cover independent applied review at the final commit.
For changed mutant semantics, apply the task-specific owner-event verification contract to the current event and exact semantic scope.
Preserve every historical fixed-event comparator unchanged within its existing standing branch only.
Use get_input directly when available; accept complete verified driver or CoC relay only after tool absence or auth/tool error.
An authoritative mismatch blocks access and application without fallback.
CoC approval supplies zero missing owner-event authority for changed mutant semantics.
A fixed identical-operation grant supplies zero changed-semantic authority on this route.
Keep read authority, proposal derivation, semantic approval and application authority separate.
Before any lookup or read, require explicit protected-read authority for the exact actor, files, IDs, complete approved extents and named commits.
Permit only named row-ID lookup and approved table-line reads; forbid whole-file parsing, adjacent-row reads and unrelated searches.
Limit retirement applied review to named row-ID lookup, retired table lines and the required base row extent.
Limit semantic applied review to exact edited row lines and the required base extent.
Require exact CoC disposition approval naming files, unique row IDs and permitted fields.
Bind repository, PR, base SHA, author head SHA, tested merge SHA/tree, failing CI identity and proposal SHA256.
Require the tested merge to contain the recorded base and author head.
Require the PR source diff to break each named row.
First verify branch-specific authority and proposal scope; then prepare only the permitted ordinary or private proposal.
Obtain independent semantic review before exact CoC proposal approval, then verify current source, current bytes, SHA256 and scope before application.
Require the semantic reviewer to differ from the author, applying writer and proposal deriver.
For semantic proposals, reuse the separately admitted private-proposal derivation, digest, review and application gates by name.
Name gates by identity and digest only; copy zero execution commands into briefs.
Use direct sha256sum only for the ordinary retirement proposal; compute protected-proposal digests only inside separately authorized admitted gates.
Refuse any difference between proposed, reviewed, approved and applied proposal SHA256 values, source identities or exact scopes.
A digest establishes identity only and supplies zero semantic verdict or authority.
Apply only the approved proposal, then obtain independent applied review at the frozen final commit.
Require every applied reviewer to differ from the author and applying writer.
Bind the final receipt to reviewer identity, approving verdict, authorities, exact scope, proposal SHA256, final commit and CI evidence.
Require CoC approval of that frozen final receipt before publication.
Changed source, scope, authority, proposal or evidence invalidates every affected receipt and approval.
Keep protected bytes inside separately admitted contexts; reports, briefs and PR bodies identify only path, row ID, fields and proposal digest.
This route grants reviewers zero edit, execution or publication authority.
Preserve Peral's CI-runner and merge-queue authority and zero writer publication authority.
For retirement only, require the applying writer to emit a content-free validation receipt with proposal digest, validator, admission and result.
Require an application receipt naming proposal digest, source identities, admitted scope, tool shape and result.
Keep protected bytes out of both receipts.
These receipt duties grant zero execution or publication authority.
Reviewer inspection requires separately admitted receipt and content scope.

Apply the following retirement requirements only when the brief selects retirement.
Define the protection point as guarded behavior, never only anchor text.
Require ordinary source and test evidence that the PR removes the entire guarded behavior throughout the final source tree.
Refuse retirement when that behavior survives in any form, changes at the same site, moves or has replacement protection.
Require zero surviving, moved or replacement protection requirement for the claim.
Replace only the approved row or hand_run table with exactly one retired table carrying its exact ID.
Allow only id and reason in the replacement table; require a nonempty reason identifying the removed behavior.
Encode the reason as a TOML basic string with backslash, quote and every control character escaped.
Validate only generated replacement text through one quoted-delimiter python3 -I - heredoc importing only tomllib.
Run that inert parse alone in its Bash call; read zero files and write zero files.
A hook refusal blocks application with zero alternate validation path; parse zero existing protected file.
Require old_string to cover the full approved table extent, including all owned child tables and the unique approved row ID.
Refuse unclear extent, missing or multiple matches, and any unapproved neighboring content.
Use native Edit with replace_all=false for newly admitted future operations only.
Require independent applied confirmation of exactly one retired entry and zero active entries for each approved ID within lawful scope.
Require matching content-free line counts as supporting evidence alongside exact scoped applied review.
Preserve every unrelated table, field and pin.
Send CI reports that say in the base file, missing at HEAD only to the existing append-only retirement route with its separate prerequisites.

Apply the following surviving-claim requirements only when the brief selects a surviving-claim adaptation.
Use the existing lane-derived route when an identical-operation re-anchor fits.
Use the surviving-claim disposition only for an independently reviewed narrower mutant that preserves the full claim guarantee.
Permit only the exact approved mutant fields under the task-specific owner event and admitted private-proposal gates.
Preserve row ID, claim, designated test, subject, operator, pins, assertions, bounds and unrelated fields.
Review original and proposed local transformations inside separately admitted private scope.
Identify the concrete violation of the surviving claim and the designated test's detection mechanism.
Review relevant regressions that the narrower operation could omit.
Refuse an adaptation that reduces the surviving guarantee or hides a product defect.
A killed mutant or passing checker alone supplies insufficient same-guarantee evidence.
Use native Edit with replace_all=false and a unique approved row-ID-contained old_string within the approved row extent.
Refuse ambiguous or missing matches, altered proposal identities and reads wider than the approved scope.
Keep refuted claims and valid equivalent survivors under their separate repository dispositions.
A valid equivalent survivor remains a measured mutant; retirement never hides its result.
Keep mutation proof after merge under separate applicable execution admission.

Apply this route only to future briefs after verified runtime adoption.
Source delivery grants zero runtime-adoption authority.
Source delivery grants zero retry authority.
Native Edit grants zero alternate form for an existing or recorded denied operation.
Never replay a denied command, equivalent operation or substitute actor while its refusal remains effective.
Preserve every effective refusal, tool and hook denial, and affected-session hold.
Require actual cause resolution and fresh applicable disposition before any affected-session attempt.
Source delivery, installation, version, cache, restart, executor and tool changes alone resolve zero existing denial.
The driver applies zero protected edits; the writer has zero publication authority.

### Owner-approved protected-row subject route

Apply [the shared prospective boundary](references/owner-decisions.md#owner-approved-protected-row-subject-route) before this route.
Use only this named route for its exact approved subject replacement scope; preserve every other route's subject freezes unchanged.
Require Owner-scoped protected row access above and a separate current task-specific owner answer event approving the exact subject edit.
Keep both authorities independent: access grants zero subject-edit authority, and edit approval grants zero protected access.
Require the brief's allowlist to equal the CoC's exact row-file paths and unique row IDs.
Require exact owner approval for each row's subject field, current value and replacement value.
Any scope or approval mismatch blocks the entire batch before access or application.
Bind both verified authority records and brief scope to the same repository, PR, base SHA, author head SHA and source identities.
A standing access event needs no per-head owner answer; its verified record and the brief establish the current source binding.
Bind each record to full Input/workspace UUIDs, current version, event id/hash, choice, actual answer, verifier and verification time.
Require `event_type=answer_submitted`, `actor_kind=owner_ui` and `payload.no_answer_yet=false` for both Inputs and current versions.
Use `get_input` directly when available; an authoritative mismatch rejects access and application without fallback.
Accept complete current driver or CoC verified provenance only after tool absence or an auth/tool error.
Check both records' internal consistency and exact scope; refuse missing, stale, superseded, cancelled, ambiguous, inconsistent, invented or unrelated authority.
A product-limit or cost approval alone supplies zero protected read or subject-edit authority.
Keep the access clause's PR-ownership requirements and evidence contract binding.
Require the PR's own base/head diff to break each named row.
Bind failing CI evidence to its run, attempt, job, tested merge SHA/tree, repository, PR, base SHA and author head SHA.
Require the tested merge to contain the recorded base and author head.
Permit the applying writer only named row-ID lookup inside each named file and exact row-line reads.
Forbid whole-file parsing, unnamed-row reads, adjacent-row reads and broader searches.
Require native Edit with `replace_all=false` for only the exact owner-approved subject replacement in newly admitted future operations.
Require `old_string` to contain the named row's unique ID and stay inside that row's approved read lines.
Refuse a missing or non-unique match without broadening scope or reading adjacent rows.
Preserve row ID, claim, designated test, pins, operator, assertions, bounds and every unrelated field.
Keep paired-field adaptation independent: require separate authority, a separate commit and a separate receipt.
When both adaptations apply, commit the subject alone first as the subject commit, then commit paired fields alone as the final commit.
Require the paired review to compare the subject commit with the final commit and preserve every field freeze, including the unchanged subject.
Keep the original base and author head for CI binding; the paired comparison changes neither identity.
Require the subject review to check only the subject field at the subject commit.
For a combined adaptation, defer the exactly-once anchor check to final combined review.
Require final combined review to compare the original base with the final commit and confirm the final anchor exactly once at the new subject.
Require identical mutant operation and unchanged guarantees in that final combined review.
Bind the final review receipt to both earlier receipts, all applicable authorities and the original base, author head, subject and final commit identities.
Require CoC approval of the final receipt before publication; changed evidence invalidates all affected approvals.
Before publication, require an independent read-only subject reviewer with complete matching scoped authority.
Require that reviewer to differ from the PR author and applying writer.
Require identical mutant operation, the same claim and test, and nothing weaker for every row.
Bind the review receipt to both authority identities, reviewer, approving verdict, frozen commit, scope, source identities and CI evidence.
Require CoC approval of that receipt before publication; changed authority, source, scope or evidence invalidates approval.
Keep messages, briefs, findings, receipts and PR bodies free of protected bytes; identify edits only by path, row ID and field.
Grant zero checker, mutation, other execution, configuration, permission or session authority.
The writer publishes nothing; the driver applies zero protected edits.
Keep mutation proof after merge under separate applicable admission.

### Same-strength adaptations

Categories 1–4 retain their existing CoC-or-Chief approval routes and owner-event verification requirements.
The same-strength route requires exact written CoC approval citing an already applicable verified owner-authority route.
This same-strength route excludes mutation-row anchor refreshes; it cannot replace category 5 requirements.
Existing independent council/Chief same-guarantee routes and owner-event grants remain unchanged and independently usable.
Owner provenance follows the applicable loaded route; a CoC message alone supplies zero owner consent.
For the same-strength route, approval names the exact files, rows or entries, permitted fields, replacement bytes, reason, approver, approval time, and evidence identity.
For the same-strength route, the CoC reviews evidence that the adaptation preserves or strengthens the same guarantee; missing or changed evidence blocks the edit.
Preserve assertions, behavioral bounds, and security/resource policy; the exact approved category 3 race-helper timeout replacement remains permitted.
Preserve designated tests, pins, operators, and unrelated fields outside the exact approved permitted fields.
Higher-priority instructions, owner provenance, effective refusals, protected holds, and tool denials remain binding; this rule overrides none of them.
This rule grants zero protected reads, TOML search/parse, anchor extraction, execution, or writer publication authority.
Dry-run proof and new-head CI remain under separate applicable admission.
Drivers prepare same-strength evidence; writers verify it before any separately permitted exact edit.

### General routes and boundaries

Prepare evidence and exact scope under [Task-specific test adaptations](references/owner-decisions.md#task-specific-test-adaptations); designate that owner-event route explicitly.
Apply [Loaded instructions and refusals](references/owner-decisions.md#loaded-instructions-and-refusals); preserve applicable higher-priority instructions and existing holds.

Preserve validation, authorization, tenant isolation, atomicity, and logging. Honor permission denials. Skip hook bypasses and force-pushes without explicit user authority. Keep scratch files outside lane worktrees and version control.
