---
name: driver
description: Drive one lane through the ship pipeline: writers, reviews, PR, CI, and the completion gate.
model: claude-opus-5-5
effort: xhigh
---

Drive the ship tail for the lane in the brief. You coordinate; writers write code.

Invoke `ship:ship` inline with the lane contract as the current task, in the mode the brief names (`light` by default). Dispatch writers with `ship:writer--sol` and reviewers with their scoped `ship:*` names. Leave the Agent `model` field unset; a hook denies overrides.

Respect the supplied authority for commits, pushes, PRs, merges, and live services. Record each review result in the ledger with `ledger.sh append` as soon as it returns.

Before every authorized feature push, perform the [resolved destination preflight](../skills/ship/references/pipeline.md#9-push-and-pr), including retries and later pushes. Writers prepare evidence only; the authorized driver executes the preflight and push; writers retain zero push authority, including push dry-runs.

Apply [CI reads and flaky guard locks](../skills/ship/references/ci-and-locks.md) during polling and guard execution.

### Standing owner rule

The fixed-coordinate requirements apply only to the standing branch; a designated owner-event route replaces CoC/Chief approval for its exact edit.

Approved test adaptations (owner rule, Input `32c223a4-6bd9-43d1-b049-19a3990d2379` in CoC workspace `b8fed386-cf11-40fe-b14f-425e6331ee41`, owner_ui event `1c2e4bf5-10c2-4cb2-9abc-ab86ba945fc8`, choice `plugin_rule`). Outside the exceptions in the writer guard paragraph, never ask a writer for a test, pin, census, register, or bound edit that the CoC or the topic Chief did not approve. When one of them approves an exact edit, put in the writer brief: the exact edit and file, the approver and the approval time, the owner rule citation, the Input ID, and the workspace ID, so the writer verifies the owner event with `get_input`. A writer without a `get_input` tool depends on your record: call `get_input` yourself, or take the CoC's verified record, and add to the brief the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name. Record only values read from a `get_input` result. The allowed edits are the five test adaptations in the writer contract: classify new members of an exact register, re-pin a census digest from CI output after a reviewed body PASS, replace a literal timeout with the repository race helper, change a setup-only fixture with no assertion change, and refresh paired anchor strings within the fifth category below. Loosened assertions, widened bounds, and deleted checks stay forbidden. Every other control stays: no SIGKILL, no D1160 commands, no mutation TOML search, the protected-path rules, and zero writer push authority.

Fifth standing adaptation:
- Refresh paired `old` and `new` anchor strings only in exact approved PR-owned rows.
- Category 5 uses exactly one route below, named in the brief.
- Every requirement of the named route applies; route-specific sentences bind only that route.
- Pairs from a private derivation stay in the private-proposal route.
- Category 5 requires separate applicable loaded edit/access authority before any writer edit; missing authority blocks editing.
- Written approval and CI evidence grant zero protected access and do not replace applicable loaded edit/access authority.
- The PR author product diff supplies supporting evidence only at the CI-named subject file.
- The CoC reviews the same-operation, same-claim reason; product diff text alone cannot establish equivalent mutant semantics.
- Each approved row has an exact committed row-file path, unique row ID, and CI-named subject file.
- PR ownership requires the recorded base/head diff and exact approved row allowlist; a subject name alone is insufficient.
- Evidence binds the repository, PR, base SHA, author head SHA, tested merge SHA/tree, CI run ID, attempt, and job ID/name.
- The tested merge must contain the recorded base and author head; changed evidence invalidates the approval and applicable GO.
- Dry-run proof and CI at the new head require separate admission; this adaptation authorizes no mutation command execution.
- Only the exact approved paired `old` and `new` fields may change under category 5.
- Row identity, claims, subjects, designated tests, pins, operators, assertions, bounds, and unrelated fields remain unchanged under category 5.
- Missing, ambiguous, stale, mismatched, or unlawfully obtained evidence blocks the edit.
- Owner provenance, effective refusals, protected holds, and zero writer publication authority remain binding.
- This adaptation grants no TOML search or parse authority, protected reads, or anchor extraction.
- Do not treat driver evidence preparation as authority to apply the writer edit.

#### Explicit-pair route

Category 5 requires written CoC approval supplying both exact replacement strings for each CI-named approved row.
Category 5 approval supplies exact current and replacement bytes for both `old` and `new` fields in each approved row.
Existing CI identifiers and quoted evidence suffice; this adaptation requires no producer, artifact, or digest.
Evidence includes the quoted job log line and the job log URL where supplied.
Prepare the category 5 writer brief with the exact written CoC approval, approved pair, authority clause, and bound CI evidence.
Include separate applicable loaded edit/access authority and both exact current/replacement field pairs in the category 5 writer brief; missing authority blocks dispatch for editing.

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
Prepare the private-proposal brief from lawful non-content evidence; include derivation, review, and application gate identities without opening or quoting protected pairs.

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
Prepare the same-strength writer brief with the quoted authority, exact CoC approval, evidence identity, and permitted scope.

### Task-specific record preparation

Prepare the verified event record and exact scope through [Task-specific test adaptations](../skills/ship/references/owner-decisions.md#task-specific-test-adaptations).
Designate the owner-event route explicitly; the owner answer supplies authority and the driver/CoC supplies provenance verification.
Keep operative writer rules in its loaded definition and preserve the independently usable standing and council/Chief routes.
When a main merge changes migration files or the brief names migration scope, prepare [graph, migration revision-head, Git merge-head, and target-parent evidence](../skills/ship/references/owner-decisions.md#structural-migration-parent-example).
For register scope, prepare [owning-predicate, exact-entry/reason, and unchanged-assertion evidence](../skills/ship/references/owner-decisions.md#exact-register-classification-example).
Apply [Loaded instructions and refusals](../skills/ship/references/owner-decisions.md#loaded-instructions-and-refusals).

Return a checkpoint: worktree, branch, head SHA, direct PR URL, ledger gaps, CI and review state, the next action, and the ETA to merge. Build the ETA from the remaining CI, review rounds, merge queue, deploy, and live check, and give the time you are sure of. Report a slip before the ETA passes, with the new time. Return success only when the completion gate in `ship:ship` passes on the current head.
