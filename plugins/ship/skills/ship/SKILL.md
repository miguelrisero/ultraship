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
A refusal never ends the work.
After a refusal, find the cause and retry in a compliant form, or ask your superior how to proceed.
A writer asks its driver, a driver asks its chief, and a chief asks the CoC.
The ask never blocks your other work.
Only the CoC decides whether an owner-only item becomes an owner Input.
With a CoC, decisions reach the owner through the CoC. In a standalone run, an owner-only item becomes a standalone Input.
No agent, the CoC included, sends the owner a refusal, hook or tooling question.
Product, billing, security policy and big architecture decisions still reach the owner through the CoC.
The refused action keeps its gate: push, merge, protected writes, secrets, production and owner-only items still need a compliant form or the authority they lacked.
A compliant retry never bypasses a hook, uses a different credential, or edits a guard.
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

Use the Stop diagnostic's `account-auto` command to account for results with a clear commit and verdict in their recorded turns:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" account-auto "<pending.tsv>"
```

The ship hook issues a single-use grant for the exact accounting command and the caller's session. The grant expires after 15 minutes. An identical call while the grant is live reuses it and keeps its issue time. Run a fresh tool call if the grant expires or the command fails. Use the literal script and pending paths from the Stop diagnostic in every accounting command.

Run the command alone on one line. A result is clear when it names one subject commit and has one verdict line. A label line starts with `Verdict:` or `OVERALL:`. The label permits leading whitespace and Markdown markers, as in `**OVERALL:** PASS`. The command matches labels and whole verdict words without regard to case.

A result with one label line uses that line. A result with several label lines is clear only when its last non-empty line is a label line and its closing paragraph has no other label line. Label lines above the closing paragraph count as earlier rounds. A quoted last line, which starts with `>`, never decides between several label lines. A result with no label line is clear only when its last non-empty line is a bare verdict line: a verdict word, then the line end, a dash or `(`, as in `**PASS** — <sha>` or `FAIL (findings)`. A bare verdict line starts at the margin, so a list item, a quoted line or an indented line is none. A closing paragraph that also holds a list item, a quoted line or another line that leads with a verdict word leaves the result pending. A bare `findings` line with `none`, `no`, `zero` or `0` states no verdict.

The command reads the transcript at an absolute path without symlinks, ending in `<session>/subagents/agent-<agent-id>.jsonl`. The recorded path must match its normalized and resolved forms. A path with `.` or `..` segments or repeated slashes leaves the result pending. The session matches the pending file's stem. The agent ID matches the recorded result.

A review turn with exactly one distinct 40-digit hexadecimal commit SHA names that commit as its subject. A review turn that quotes several SHAs must label exactly one of them as frozen: the word `frozen`, at most three label words, then the SHA on the same line, as in `Frozen commit: <sha>` or `frozen head <sha>`. A label with `not`, `non`, `never` or a word ending in `n't` before it on its line names no subject, and `unfrozen` is no label. Base, head and parent SHAs without that label are quotes. Several SHAs with zero or several frozen SHAs leave the result pending with `expected one commit`. A shorter SHA never names the subject. The command counts SHAs between Markdown underscores or backticks. A SHA has no adjacent hexadecimal digits.

The command strips Markdown markers and whitespace from the value on the verdict line. The first word must be a verdict word. The command recognizes `pass` as positive and `fail`, `failed`, `fails`, `failing`, `failure`, and `findings` as negative. A `pass` value permits only one verdict word and excludes `blocked` and negations: `not`, `no`, `never`, `without`, and words ending in `n't`. The command records `findings` for a negative value that contains `findings`, or `fail` for other negative values. It records `blocked` when `blocked` is the first word. A `blocked` value that also contains `pass` stays pending. Every other shape leaves the result pending with `expected one verdict`.

The command requires exactly one `run-start` row that matches the recorded run before it accepts a receipt or an `account-result` row. The receipt must name the same ledger and run. The receipt row must follow the recorded `run-start`. The first `run-end` or next `run-start`, if present, ends the range. The result's own `account-result` row can also satisfy the receipt outside that range. The plain `account-auto <pending.tsv>` form leaves the result pending if any required evidence is missing or differs. The plain form also leaves it pending if the closing paragraph repeats the verdict label or the verdict value mixes positive and negative words.

Use `--fail-unparsed` to account for legacy results with a bound transcript and one of three parse failures:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" account-auto --fail-unparsed "<pending.tsv>"
```

- `expected one commit`
- `expected one verdict`
- `transcript parse error`

For these failures, the command records `fail` with SHA `0000000000000000000000000000000000000000`. The row names the transcript path, the epoch and the reason. It grants no pipeline step, review or completion evidence. All binding and accounting checks still apply. Other failures stay pending. Results with a clear commit and verdict keep their normal outcomes.

Use `--retire-merged` to retire unclear results whose reviewed work is on the remote default branch:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" account-auto --retire-merged "<pending.tsv>"
```

The command first accounts for every clear result with its own verdict. For a result that stays pending with `expected one commit` or `expected one verdict`, it reads local Git data in the result's recorded working directory. It never contacts GitHub. Each Git read ignores inherited `GIT_*` variables and replacement objects, disables lazy fetch, and has a 60-second limit. A failed or late read leaves the result pending. The remote default branch is the `refs/remotes/origin/` branch that `refs/remotes/origin/HEAD` names, or `refs/remotes/origin/main` when that ref is absent or names another place. The command reads that branch by its exact ref name. A default branch that is itself a symbolic ref proves nothing.

One proof retires the result: the result labels exactly one commit as frozen, that SHA is a commit, and the commit is an ancestor of the remote default branch. An unlabelled commit can be the base, so it proves no merge. A pull request URL is no proof, because local Git holds no pull request record. A squash merge leaves the frozen head outside the default branch, so its results stay pending here.

The command appends an `account-result` record with step `retired` and verdict `retired`. The record names the frozen commit, the proof, the branch tip, the transcript path and the epoch. It states no review verdict and grants no pipeline step, review or completion evidence. A result without proof stays pending. Fetch `origin` first when the merge is recent.

For a merge that only GitHub records, such as a squash merge, a rebase merge or a pull request in another repository, read the pull request state. Then record the result with `account`: use step `retired`, verdict `retired`, the merge commit SHA, and the pull request URL and state as evidence.

Use `--close-unparsed` to close the results that hold no review evidence:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" account-auto --close-unparsed "<pending.tsv>"
```

The command first accounts for every clear result with its own verdict, then retires every result with merge proof as `--retire-merged` does. For a result that still stays pending with `expected one commit`, `expected one verdict` or `transcript parse error`, it appends an `account-result` record with step `closed`, verdict `no-evidence` and `-` in the SHA column. It states no commit and no verdict. The record names the transcript path, the epoch and the reason. It grants no pipeline step, review or completion evidence. All binding and accounting checks still apply, and other failures stay pending. Read a retained result before you close it when its review can still change the work.

Run Stop to publish the receipts. `account-auto` reports new ledger records, existing records that await Stop, and records with a Stop receipt separately.

For a retained v2 result that lacks the ledger or run field and has no Stop receipt, `account-auto` prints an `orphaned` diagnostic. It includes the result ID, agent, recorded transcript path, reason, and an empty SHA. The command leaves the result pending and gives it zero review credit. Stop still applies its existing matching rules. A fresh review with a new agent ID covers its own result only.

When an accounted result is bound to another result's row, move its credit with:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" correct-binding "<pending.tsv>" <result-id> <ledger-line> '<reason>'
```

The line is the 1-based line of the correct review row in the bound ledger file, in the same run and with the same agent column. The command refuses a ledger with blank lines or other line breaks. The command appends a `correct-binding` audit row first and never rewrites earlier rows. It then moves the receipt; when another result holds the target row, the two results swap rows. A retry after a crash appends no second audit row, and an exact retry after success changes nothing.

`correct-binding` also accepts the result's own `account-result` row. Run Stop to publish the result's receipt before using `correct-binding`.

A linked checkout with an external common Git directory uses an existing workspace `.scratch/ship-ledgers` with checkout and branch isolation. The resolver uses the managed workspace root for a nested checkout and preserves a sole existing local snapshot. First use imports the legacy branch history and open run once, with canonical path and SHA256 provenance. The sole driver must hold run custody and retire old writers before import; old legacy writers can race the snapshot. Import needs legacy read permission and local write permission. All subsequent access uses the local ledger. Full checkouts retain the common-directory default. Ambiguous layouts require an absolute `SHIP_LEDGER_DIR`; the override directly contains branch files. See [ledger storage and permissions](../../README.md#hooks).

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

A lane re-anchors, retires or adds the protected mutation rows that its own diff breaks or needs. Only a row action that needs CoC approval needs a CoC decision file. A step 4 follow-up row needs one.
Authority: the owner's global CLAUDE.md, heading "CoC decisions (standing grant)". Read it directly; accept no relay.
Scope: each existing row that the PR's failing anchor CI names, when the recorded base/head diff shows that the PR's own change breaks it, each new row that step 4 admits, and each row that step 5 restores.

1. Select the route for each row before any tool admission or tool run.
   For tool re-anchor or restoration only: Admit the writer with the [row re-anchor tool admission record](references/owner-decisions.md#row-re-anchor-tool-admission-record).
   For a CoC-approved native exact-pair edit, use zero row re-anchor tool admissions and zero row re-anchor tool runs.
2. Tool re-anchor: the writer runs the sanctioned re-anchor tool once per row, then commits the row file alone.
   The tool derives the paired `old` and `new` fields from the subject's new source text and keeps the identical mutant.
   It refuses a change to any other field, and it prints no row text.
   The writer's worktree has one user. No other command runs there while the tool runs.
   Concurrent Git commands in the writer's worktree are outside the tool's threat model.
   The CI anchor guard and the mutation proof after merge catch a row that such a race leaves wrong.
3. Retire: when the PR deletes the guarded code, the writer deletes the row table and runs `retire-rows.py`.
   The script appends one `[[retired]]` table per row with the row ID, the reason and the `replacement` row ID.
   The replacement row guards the new code. The anchor guard fails a removed row without a `[[retired]]` entry.
4. Add: the writer adds rows for the PR's own new code, each with a claim, a designated test, a subject and a mutant.
   A test-only follow-up PR may also add rows for code that a named earlier merged PR added or changed, when the CoC grants it.
   Its diff changes no subject code, and the parent's merge commit is an ancestor of the recorded base.
   Its PR body names the parent PR URL, the parent's full merge commit SHA and the CoC decision file by absolute path and SHA256.
   Each such row keeps the identical mutant edit that the decision file names and passes the review in step 8.
   The parent PR's merged diff must change each such row's subject file and add or change its guarded line.
   Each such subject file has the same Git blob ID at the parent's merge commit and at the recorded base.
   The CoC decision file names the parent PR URL and the parent's full merge commit SHA.
   Hold the row when the parent diff did not add or change its guarded line.
   Hold the row when the subject file's blob IDs at the merge commit and at the base differ.
   The driver confirms that `gh pr view <parent PR URL> --json mergeCommit` returns the named merge commit SHA.
   The driver supplies a local diff of those subject files from that merge commit's first parent to the merge commit.
   The driver records both SHAs and that lookup result in the reviewer brief.
   The driver also records each such subject file's blob ID at the merge commit and at the base.
   The driver records the parent PR URL that it passed to that lookup in the reviewer brief.
   The driver copies the parent PR URL and merge commit SHA from the row PR body into the reviewer brief.

   Earlier test-only parent: add rows for existing subject code when a named earlier PR changed the designated tests.
   Require the parent PR to be merged in the same repository as the row PR.
   Match the recorded merge commit to the full squash SHA in the row PR base history.
   Require the squash to have one parent.
   Verify the complete changed-path inventory in the local first-parent diff.
   Check both paths for renames and copies.
   Require every changed path to contain only tests, test-only fixtures or test-only helpers.
   Tie a changed hunk to the exact designated test selector and relevant cases for each row.
   Show how the changed lines affect the designated assertion.
   Match the Git tree mode, path and blob ID for the designated test and each relevant fixture and helper.
   Compare these files at the squash, row base and frozen head.
   Trace direct, transitive, autouse and runtime fixture use and direct and transitive helper calls.
   Match the subject's Git tree mode, path and blob ID.
   Compare the subject at the first parent, squash, row base and frozen head.
   Limit the complete row base-to-head diff to the approved new rows.
   Require an existing authorized draft for the same repository and lane.
   Before any protected insertion, the writer verifies the frozen CoC decision by absolute path and SHA256.
   Bind it to the writer, repository, lane, draft URL, row base, parent PR URL and full squash SHA.
   Match the approved row file, new ID, claim, designated test, subject, expected anchor count and exact mutant edit.
   The writer uses native Edit with `replace_all=false` for the authorized insertion.
   Preserve all existing protected read and edit restrictions.
   Admit no row re-anchor tool and run none.
   At the frozen head, the driver verifies the decision digest and bindings again against the applied rows.
   The driver names the decision under `Readable files` and supplies the merge lookup, both commit SHAs and local first-parent evidence.
   Include the parent path inventory and hunk-to-test trace.
   Include the Git tree mode, path and blob ID for each file at each comparison point.
   Supply content-free evidence that the row diff leaves every path and byte outside the approved insertions unchanged.
   Name the parent PR URL, full squash SHA and decision path and SHA256 in the row PR body.
   Use the shared anchor proof in step 7 and the independent reviewer admission in step 8.
   Keep live proof under separate execution admission and GO.
   Hold the row on any missing, stale or mismatched evidence.

   Each new row ID must be absent at the base; the recorded base/head diff shows it. A new row needs no failing CI.
5. Restore: the writer returns rows that only the lane's own unmerged commits changed to their bytes at the merge base.
   A restored row needs no failing CI report, so a row that the starting head deletes stays in scope.
   Its evidence is the merge-base diff and the tool fields `starting_lines`, `base_lines` and `restoration_lines`.
   When a lane commit changed only those rows, the writer runs a plain `git revert` of that commit.
   When it also changed other lines, the writer uses native Edit only for rows that exist at the starting head, and keeps the other edits.
   A row that such a mixed lane commit deleted leaves the restore route.
   That row follows the re-anchor route or goes to the CoC.
   The writer commits the restoration alone. Then it runs the re-anchor tool on each restored row.
   That run passes the merge base as `--base` and the restoration commit as `--restoration`.
   The tool binds the restoration commit and its own parent, the starting head. A later commit never moves that parent.
   The tool refuses unless each restored row equals the merge base byte for byte and the rest of the commit equals the starting head.
   Only blank separator lines between tables, outside every row, may return with a restored row. Every other byte stays exact.
   It also refuses a row ID that is not unique, and it prints both results and `insert_after` as `key=value` lines.
   Any byte difference leaves the restore route. That row follows the re-anchor route or goes to the CoC.
   The driver copies the lane commits that changed each row file after the merge base into the reviewer brief.
   The driver names the verified merge base in the reviewer brief. The reviewer refuses unless the record's base equals it.
   The reviewer matches every restored row ID in the record to the approved scope before publication.
6. Authorization record: each tool run that changes zero statements writes a generated record in the Git directory.
   The record names the lane, base, head, row IDs, base and head line ranges, expected counts and the unchanged mutant check.
   A restore entry also names the restoration commit, its parent, the three row ranges and `insert_after`.
   The tool prints the record path and every record field as `key=value` lines, with no row text.
   The record expires on any head change. Rerun the tool at the frozen head for each tool re-anchor; that run changes zero statements.
   On the restore route, that rerun keeps `--restoration` and prints `changed_statements=0`.
   A run that changes statements writes no record entry and unfreezes the head. The writer commits the edit and reruns the tool.
   For each tool re-anchor or restoration, require the generated record from the frozen-head run.
   The driver copies the printed fields of the frozen-head run into the reviewer brief. The reviewer reads no file under `.git`.
   A CoC-approved row change gets no tool run. Its decision file and the review in step 8 cover it.
   For a CoC-approved native exact-pair edit, the driver names the frozen decision path, SHA256 and verification result in the reviewer brief.
   The driver lists the decision file under `Readable files` in the reviewer brief.
   The driver verifies the decision against the applying writer, repository, lane, PR, row file, row ID, source commit and exact edit.
7. CI: the anchor guard requires each anchor count to equal the row's expected count, not only a nonzero count.
   Reuse the existing authorized draft for CI and reviewer admission.
   If the route has no PR, the driver opens a draft only with separate authority before CI and reviewer admission.
   Opening the draft and pushing to it publish nothing. Marking it ready, a push to a ready PR and any merge are publication.
   For a CoC-approved native exact-pair edit or an earlier test-only parent row, use the shared anchor proof below.
   The driver supplies content-free evidence from the anchor guard at the authorized draft head.
   The driver records the CI checkout tree SHA and derives the frozen tree SHA from the frozen commit.
   The reviewer brief names both tree SHAs, the CI run ID, head SHA, anchor job result, row ID, and declared anchor count.
   Include proof that the guard selected the row and that a count mismatch on that row fails the job.
   Report an observed count only when the evidence gives it directly.
8. Review: one independent reviewer confirms that every changed, retired, restored or added row is not weaker.
   The driver marks the draft ready only after the review in step 8 passes at the exact head.
   Not weaker means the same test and the same mutant intent with the same claim or a CoC-approved narrowed claim, or a replacement that guards as tightly.
   The reviewer differs from the PR author and the writer, and reads rows only under its [reviewer admission record](references/owner-decisions.md#reviewer-admission-record-for-protected-row-reads).
   The driver supplies read-only checkouts at the base and the frozen head. Admit each copy only when it contains an approved extent for that review.
   The writer reports the base and head line ranges of each retired or CoC-approved row. The driver copies them into the reviewer brief.
   For a row file absent at the base, the driver first verifies the base with `git cat-file -e <base SHA>^{commit}`.
   From the repository root, the driver records that `git ls-tree --name-only <base SHA> -- <repository-relative path>` exits 0 and prints nothing.
   The driver then admits only the head copy.
   For each added row, the driver supplies the [added row ID proof](references/owner-decisions.md#added-row-id-proof) and admits its exact head extent.
   At the base and the frozen head, the driver records the test runner's fixture listing, such as `pytest --fixtures-per-test`.
   From both listings, the driver lists each test that uses a changed, added or removed fixture, directly, transitively or through an autouse fixture.
   For each changed, added or removed helper, the driver traces its callers in both checkouts, directly and transitively, and adds each test that reaches it.
   The driver also traces runtime fixture requests, such as `request.getfixturevalue()`, in both checkouts.
   The driver supplies a map of every active row ID to its designated test at the frozen head, from the repository's mutation tooling, with no row text.
   For each listed test, the driver names every active row that the map assigns to it, with its row ID.
   The admission record lists each such row file path. The reviewer brief names each listed row's exact line range and commit.
   The reviewer confirms from the fixture listing, the helper trace and the diff that the test list is complete.
   The reviewer blocks approval when it cannot determine every test that reaches a changed fixture or helper by any mechanism.
   The reviewer checks every listed test against the map and confirms that every row that designates it is listed.
   For each listed row, the reviewer traces the changed fixture or helper into the test.
   The reviewer confirms that the designated assertion still separates the original result from the mutant result.
   The reviewer blocks approval when the list, the admitted lines or the trace is missing or inconclusive.
   Any later push to the PR needs a new review at the pushed head. Return a ready PR to draft before that push.
   Mark it ready again only after the new review passes.
9. The mutation proof runs after merge, under its execution admission.

Send these rows to the CoC: a new or changed mutant on an existing row, a changed designated test, a retirement without a replacement, and a row that the PR's own diff does not break.
A lane may narrow the claim of a row that its own PR breaks, under a CoC approval.
A narrowed claim keeps the same designated test and the same mutant. It claims less than the old claim and nothing that the test does not prove.
Send a widened or otherwise changed claim to the CoC. The CoC approves it only with a current task-specific owner event.
A CoC approval is a frozen decision file named by absolute path and SHA256.
It binds the row ID, the source commit, the fields and their replacement values.
Before verifying a PR-bound decision, require the verified URL of an existing, authorized draft PR for the same repository and lane.
Keep the row pending if that draft identity is missing or unverified.
Draft creation still requires separate authority.
Match the PR URL in the decision to that draft.
Require the [shared decision preflight](references/row-decision.md) before dispatch when `old` alone changes and all three lines use bare YAML `version: X.Y.Z`.
Check the old line, its replacement, and the unchanged mutant. Use the existing route for other cases.
Use the same schema to check missing fields. Keep all authority and retry checks separate.
The writer verifies its SHA256 and bindings before the edit. The driver verifies them again at the frozen head and records the result in the reviewer brief.
The writer applies only those fields with native Edit and `replace_all=false`, then commits the row file alone.
Step 8 reviews that row, and a follow-up row guards any new code.
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
