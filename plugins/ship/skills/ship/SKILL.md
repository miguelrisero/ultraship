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
Pause a refused tool step and keep the work pending.
Retry under the refusal rule or ask your superior.
Stop a step for a failed check, a hard rule, an owner refusal, a missing special-run GO, or an owner-only item.
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

Apply [standalone main-row repair](references/owner-decisions.md#standalone-main-row-repair) only for the exact repair-only lane that names it.
This separate route excepts the PR-owned causality, per-row owner-event, and protected lookup rules only for its exact frozen scope.
Keep reviewer admission, execution admission, and the matching frozen receipt as separate gates.
Apply [scoped owner event verification](references/owner-decisions.md#scoped-owner-event-verification) only as the named lane's brief-level exception to its Input call ban.
Preserve every other Input ban, reviewer MCP denial, and independent hook and tool restriction.

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

Copy both paths from the Stop diagnostic; run the command alone on one line with evidence in single quotes.

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

### Explicit checks on an unprotected branch

The default completion route requires configured required contexts.
The CoC may approve a nonempty named check set for a branch that positively proves its unprotected state.
This explicit route satisfies condition 2 only when the named-check checker returns exit 0 on the approved pushed head.
Run the checker with the coordinator-approved policy file and its separately approved SHA256:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/watch-checks.sh" <PR> 0 0 --named-checks <absolute-policy.json> --approved-policy-sha256 <approved-sha256>
```

Keep the policy outside PR-controlled source.
Require the coordinator's approval of the digest through a separate trusted channel.
A policy payload supplies zero approval authority.
Use schema version 1 with exactly these fields:

```json
{
  "schema_version": 1,
  "repository_id": 17,
  "pr": 7,
  "base": "main",
  "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "checks": [{
    "workflow_id": 23,
    "workflow_path": ".github/workflows/validate.yml",
    "workflow_blob_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "check_name": "validate",
    "app_id": 31
  }]
}
```

These values illustrate the schema; obtain actual identities from approved repository evidence.
Require numeric repository, PR, workflow and App IDs, the full approved head, and each exact workflow path, blob and check name.
Keep `checks` nonempty and unique.
The route forbids ignore settings, unknown fields and unknown schema versions.
It requires branch `protected=false`, the structured classic `Branch not protected` 404, and completely empty branch rules.
Every collection requires complete pagination within its original API origin and endpoint.
The checker selects the latest matching same-repository `pull_request` run and its latest attempt.
It binds the job through its check-run URL, suite, App, name and head.
Both the job and workflow must complete successfully; skipped and neutral conclusions fail.
Before success, it rechecks protection, the latest run and attempt, and the PR head.
A push or rerun invalidates the receipt.
Exit 1 means unsuccessful evidence; exits 2 and 3 retain the start and overall timeout meanings.
Exit 4 means uncertainty and blocks completion.
Keep the 600-second start, 5400-second overall and 300-second polling defaults.
Select this route explicitly; an ordinary checker failure grants zero opt-in authority.
Source delivery grants zero installation, runtime adoption, historical PASS or affected-retry authority.
Preserve every earlier formal outcome and effective refusal.

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

Approved test adaptations follow the writer contract (owner rule, Input `32c223a4-6bd9-43d1-b049-19a3990d2379`, workspace `b8fed386-cf11-40fe-b14f-425e6331ee41`): five standing test adaptations cover register classification, a census re-pin from CI output after a reviewed body PASS, a race-helper timeout replacement, a setup-only fixture change, and the [lane-owned row route](#lane-owned-row-route) below. For categories 1–4, the driver puts the Input ID and workspace ID in the writer brief. In those four categories, if the writer lacks `get_input`, the driver or the CoC runs `get_input` and the brief also records the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name; the writer stops on any mismatch with its definition. Loosened assertions, widened bounds, and deleted checks stay forbidden.

### Squash-merge containment

Apply this rule to every requirement in this file that a commit contain the author head or a commit that the author head contains.
A single-parent squash commit meets that requirement only when it contains the recorded base and all conditions below hold.
1. GitHub links the squash commit to the PR: the PR state is `MERGED` and its `mergeCommit` equals that commit.
2. The squash tree equals the exact tree from a successful merge of the author head into the squash parent, except for the listed paths below.
The checker uses `git merge-tree --write-tree` with the squash parent first and the author head second.
Require this check even when the squash parent already contains the author's changes.
The `files` field counts the paths that differ between the squash parent and the squash commit.
A path that `squash-containment.json` lists for the PR's repository may differ from that merge only when every other path matches exactly.
Such a path stays a non-executable regular file, and the author head must change it from its merge base with the squash parent.
A merge conflict may touch only such paths; the checker then treats each conflicted path as regenerated.
The squash commit also needs one passing push run of the configured drift check job and step from GitHub Actions.
The `PASS` line names the drift job as `drift_job=<id>` and each such path as `regenerated=<path>`; with no listed path, the exact tree rule stays.
The driver runs `python3 "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/squash-containment.py" <PR URL> <base SHA> <author head SHA> <squash SHA>` in a checkout that holds all four commits.
Accept only a recorded `PASS` line that names the same PR URL, recorded base, author head and squash commit.
Refuse the squash commit when any condition fails or the evidence is missing, stale or ambiguous.
Every other commit keeps the containment requirement unchanged.

### Lane-owned row route

A lane re-anchors, retires or adds the protected mutation rows that its own diff breaks or needs. No CoC decision file is required.
Authority: the owner's global CLAUDE.md, heading "CoC decisions (standing grant)". Read it directly; accept no relay.
Scope: each row that the PR's failing anchor CI names, when the recorded base/head diff shows that the PR's own change breaks it.

1. Admit the writer with the [row re-anchor tool admission record](references/owner-decisions.md#row-re-anchor-tool-admission-record).
2. Re-anchor: the writer runs the sanctioned re-anchor tool once per row, then commits the row file alone.
   The tool derives the paired `old` and `new` fields from the subject's new source text and keeps the identical mutant.
   It refuses a change to any other field, and it prints no row text.
3. Retire: when the PR deletes the guarded code, the writer deletes the row table and runs `retire-rows.py`.
   The script appends one `[[retired]]` table per row with the row ID, the reason and the `replacement` row ID.
   The replacement row guards the new code. The anchor guard fails a removed row without a `[[retired]]` entry.
4. Add: the writer adds rows for the PR's own new code, each with a claim, a designated test, a subject and a mutant.
5. Authorization record: each successful tool run writes a generated record in the Git directory and prints its path.
   The record names the lane, base, head, row IDs, expected counts and the unchanged mutant check.
   The record expires on any head change. Rerun the tool at the frozen head before review; that run changes zero statements.
6. CI: the anchor guard requires each anchor count to equal the row's expected count, not only a nonzero count.
7. Review: one independent reviewer confirms that every changed, retired or added row is not weaker.
   Not weaker means the same test, the same claim and the same mutant intent, or a replacement that guards as tightly.
   The reviewer differs from the PR author and the writer, and reads rows only under its [reviewer admission record](references/owner-decisions.md#reviewer-admission-record-for-protected-row-reads).
8. The mutation proof runs after merge, under its execution admission.

Send these rows to the CoC: a changed claim, a new or changed mutant on an existing row, a changed designated test, a retirement without a replacement, and a row that the PR's own diff does not break.
The CoC audits a 10% sample of lane-owned row changes.
The writer locates a named row by its row ID and reads only that row's lines. It never parses or searches a whole row file.
Keep row TOML text and pair bytes out of messages, briefs and PR bodies. Name each edit by path, row ID and field.
The driver applies zero protected edits. Writers keep zero publication authority.

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
