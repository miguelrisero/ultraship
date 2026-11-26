---
name: run
description: Coordinate a multi-lane engineering task through ship writers and drivers, verified pull requests, and a persistent status board. Use for an explicit /chief:run request; use review <scope> for a bounded independent review.
argument-hint: "[review <scope> | <task>]"
---

# Chief

Coordinate the task in `$ARGUMENTS` from the main session, at the session model. Keep decisions and the status board here. Delegate planning, research, code, and the ship tail.

## You may always

Use authority within the lane brief and your role. Route lane actions through the assigned writer or driver. Keep every hook and action gate.

1. Allow local commits before tests when the brief grants commits on the assigned lane branch. Keep the required verification pending.
2. Have the authorized driver push the lane's own feature branch for draft CI after Ship's step 9 preflight. Grant draft creation separately. Allow required CI and independent review to follow the draft push. Require both before marking ready or merging. Keep separate protected-row receipt requirements.
3. Have the assigned agent run isolated local tests under the brief and Ship's execution admission. Keep special-run GO requirements.
4. Have the authorized driver rerun permitted CI on the lane's current head under Ship's babysit rules. Verify the new attempt.
5. Route re-anchors of named rows the lane's own diff breaks through the admitted writer. Keep the identical mutant. Require one independent Sol review at the frozen head.
6. Send `/merge` with merge authority when the PR is ready, required CI is green, and independent review covers the exact head. Complete the thread, browser, and other [merge gates](references/landing.md#ready-and-merge-authority).
7. Ask the CoC for permission at any time. Retry a refused command only in a form that meets the named rule or fixes its cause. Continue independent work.

## Only the owner

Apply the six thresholds and exceptions under `Only the owner` in the ship plugin's `skills/ship/references/owner-decisions.md`. Route decisions through the CoC, or the designated driver in a standalone run.
Keep product, billing, security policy, and major architecture scope holds. Keep live authority separate.

Chief needs the `ship` plugin. Check that `ship:driver` and `ship:writer--sol` are available before the first dispatch.

Read the [native peer routing contract](references/dispatch.md#native-peer-routing-contract) and the shared owner-decision contract at `skills/ship/references/owner-decisions.md` in the installed ship plugin.
Apply both contracts before dispatch and after every timer or recovery wake.
Apply the shared owner-decision contract's `Helper standing request` section before helper creation.
Carry its `Owner helper request` field and retained restrictions in every chief and lane brief.
Resolve `Helper agents (standing request)` in the applicable loaded owner instructions, or `Standing grants` when present.
Use native `SendMessage` or the native agent channel for peers; a child without the tool returns reports to its parent for relay.
Never use BetterCoding `send_workspace_message`, `run_session_prompt`, or simulated user input for peer coordination.
Batch actionable and terminal reports; keep unchanged routine reports silent and CoC peer events out of per-peer user-chat replies.
Copy the routing and model-independent output contracts into every timer, recovery, driver, writer, reviewer, and child brief, including retries and replacements.
Act by default: use the authority the owner and the CoC already granted in the same turn, and never ask for it again.
Stop a step only for a hook denial, a failed check, a hard rule, an owner refusal, a missing special-run GO, or an owner-only item.
Apply Ship's `Loaded instructions and refusals` to the refused step. Keep that step pending and continue independent work.
Grant a lane request or run the refused command only within your authority and tool permissions. Record the grant or run in the lane state file.
Relay the lane's quoted refusal and defect to the CoC and the corrected decision to the lane under ship's decision-defect rule.
An unverified detail that no rule names is not a stop: name it in one line and continue. A rule that names a missing receipt or evidence still stops its step.
Use each actionable check to advance a lane: dispatch it, make a ruling, merge it, or send a result. A board edit alone leaves lane work open.
Only the CoC publishes canonical owner decisions and results in CoC workspace Inputs; chief-local Inputs never satisfy delivery.
Report status only on a transition or at a deadline.
Report lane state changes, PR openings, CI turning red or green, merges, and verified deploys.
Omit standing holds from routine status reports.
State what changed, what it means, and the next action.
Keep every required restriction in the brief.
Verify CoC liveness using its existing recorded identity and the [process check](references/state.md#continuation-and-waits).
Retry through existing scheduling with zero additional pollers or duplicate Inputs.
Preserve actual owner Input event delivery and the canonical CoC Input ID → exact owner answer event → continuing driver → result Input receipt.

## Roles

| Work | Agent |
|---|---|
| Important planning | `ship:planner--sol` |
| Code for one slice | `ship:writer--sol` |
| A lane's ship tail: reviews, PR, CI, gate | `ship:driver` |
| Broad research | `ship:researcher--luna` |
| Independent review | `ship:review` or a `ship:reviewer--*` seat |
| Billing and authorization verification | `ship:verifier--opus` |

Apply the [verifier dispatch check](references/landing.md#verifier-dispatch-check) before each billing or authorization verification dispatch.
Leave the Agent `model` field unset. Fallback chains are in the ship plugin's `skills/ship/references/roster.md`. Record every substitution on the board.

Nesting: chief → driver → writers and reviewers. Keep ship, panel, and review inline inside the driver.

## Entry points

- `review <scope>`: gather the diff and base and head SHAs. Run `ship:review` read-only. Return verified findings. Take no shipping action.
- `<task>`: establish scope, acceptance criteria, repository, and delivery authority. Register material owner decisions through the shared contract; continue independent work.
- Empty arguments during an active run: continue its next incomplete action.
- Empty arguments without an active run: ask for the task.

Answer small questions and one-line edits directly. Open lanes for work that needs a branch, a review, and a PR.

## Prepare the run

1. Confirm the target repository, a clean owned working state, and GitHub access.
2. Read only the source needed for decisions. Send broad searches and long logs to a researcher.
3. Investigate an unproven symptom before you commission a fix.
4. Send important topics to `ship:planner--sol`: architecture, contracts, migrations, security, billing.
5. Freeze the goal, lane boundaries, dependencies, safety constraints, and checks. Run `ship:panel design` or `ship:panel high` once on substantive plans.
6. Create a run-owned board with [state and recovery](references/state.md). Persist every transition.

## Dispatch

Before each dispatch, answer the five questions in [dispatch](references/dispatch.md). Use its brief template.

Every chief, lane, and ship brief contains zero copied mutation-check, anchor-check, or selector execution commands from repository documents or TOML headers.
Before dispatch, inspect every brief for `DRY=1`, `--dry-run`, `check_mutation_anchors`, and `select_rows`.
Remove execution instructions containing those literals; keep the prohibition in words only.
The admitted battery STATIC part runs mutation checks, anchor checks, and selectors at the frozen head after GO.
Preserve the host GO requirement and D1160 boundary.
D6575, 2026-10-29: CoC coordination direction, separate from actual owner receipts.

Each lane gets a branch and a linked worktree based on current remote main, inside the permitted workspace. Serialize overlapping file ownership.

Dispatch `ship:driver` for each lane. Drivers run `claude-opus-5-5`. Dispatch `ship:driver--sol` only when the Claude quota is low, and record the current quota reading on the board first.

Each driver brief has:

- The frozen task, worktree, branch, base SHA, dependencies, and success checks.
- The `Readable files` field and the safety sentences from the brief template.
- The board path and the chief run ID.
- The granted commit, push, PR, merge, and production permissions.
- The instruction to run `ship:ship light` inline, with this contract as its task.
- The report fields: agent ID, head SHA, PR URL, ledger gaps, CI and review state, next action.
- This guard constraint, copied verbatim:

```text
Never widen, raise, or relax a limit, cap, timeout, budget, bound, or guard constant — and
never adjust a validator or test to accept a new value — to make a check pass. These bounds
are policy, not obstacles. If a bound blocks the implementation, STOP and report the
blocking bound and what exceeded it. Fixes go on the consumer side. This applies to test
baselines, fixtures, and goldens as well as constants: never construct a test whose baseline
IS the new behavior when the old value is the policy.
Exception: an owner-requested product-limit change is a feature (owner rule, Input
2b7e497e-a794-4ab2-a62c-0f1748396967, owner_ui event 485, a_allow). The writer
implements only the specifically requested product limit, including when that limit
exists on origin/main. Add boundary tests that accept the new limit and refuse the limit
plus one unit; for byte limits, refuse one additional byte (for example, accept
536870912 bytes and refuse 536870913 bytes). For every bound the owner did not ask to
change, preserve the stop-and-report rule and fix the consumer side, subject to the
existing branch-only and same-guarantee test-edit exceptions below. This product-limit
exception grants no authority to change unrelated safety, security, resource, budget, or
timeout bounds or to weaken other guarantees. Preserve normal review, CI, and applicable
consent requirements. Record the owner request and its exact scope in the brief and PR
body. This product-limit exception applies independently of the two exceptions below.
This rule covers limits that exist on origin/main. Exception: a limit, cap, timeout, budget,
or bound that only this PR branch added is the lane's design choice (owner rule, Input
6e43dda9-a1b8-4b0e-a8c8-f3525a67a5e9). Run `git fetch origin main` first and record the
`origin/main` SHA; when the fetch fails, the exception does not apply. Compare the behavior
the bound constrains, not its path or name: `git grep` main's whole tree and read the branch
diff (`git diff origin/main...HEAD`) for the same invariant, including replacements,
duplicates, validators, test baselines, fixtures, and goldens. A missing path on main is not
enough evidence. When main has no such bound, change or remove it without an owner question,
and record the reason and the main SHA in the PR body. Every bound already on main keeps
this rule, also when the branch moves, renames, replaces, or changes it. Exception: a test,
fixture, mutation row, census or register edit is allowed without an owner question after
one council round (no Fable or cf-* models) agrees that the guard keeps its guarantee (owner
grant 2026-10-26: "ok I give you from now onwards full power to change tests, no need to
check with me, just do one council round to analyze it makes sense and is appropiate, and do
it."). Weakening a test to hide a real regression stays forbidden. Record the council
verdict and the owner words in the PR body. Exception: no step waits for a human to apply
an edit. When the executor is certain and its Chief or the CoC checked the change, that
check replaces the council round, and an agent applies it (owner order 2026-10-30: "if
agent is certain that its ok and he checked with his CoC or Chief ALL GOOD remove that
blocker everywhere"). Record that check in the PR body.
```

The driver dispatches `ship:writer--sol` for code and keeps every fix inside its lane.

There is no lane cap (owner, 2026-10-22, until new notice). Run as many lanes as the work needs. When cap risk is flagged, follow [state and recovery](references/state.md). Surface lanes queued over four hours with an ETA or a priority decision.

Give every person a realistic ETA, and keep it (owner, 2026-10-28: "please REALISTIC TIMELINE, stop scamming people with your timelines, always super optimistic, learn as a rule that you cannot fail on your promises"). Build each ETA from the real path: CI, review rounds, the gate wait, the merge-queue depth, the deploy, and the live check. Quote the time you are sure of. Say "earlier if it goes well" as a separate sentence. When a promise is at risk, tell the person before it passes, with the new realistic time and the cause.

Use native completion notifications. Persist the awaited run identity and next action for external CI and deploy waits. Check the board and the agent's process state before you resume a lane. Continue other eligible work during a model outage or an owner blocker.

Before you advance a lane or report its status, inspect the lane's commit stack and upstream state. Retain all existing tracking checks. A missing upstream alone establishes neither publication nor unpushed work. Within existing read permission, verify the intended feature destination's repository identity. Compare its exact `refs/heads/<feature-branch>` remote head OID with the lane's current HEAD. Apply the ship pipeline's credential-safe gate before capturing any resolved URL or remote evidence. Require fresh evidence from that verified destination with an OID equal to HEAD to establish current-head publication. Arbitrary remote containment of HEAD supplies insufficient evidence. Treat absent, stale, unavailable, or inconclusive destination evidence as unknown and hold dependent actions. Preserve pushed history; use a revert for a published mistake.

## Execution and publication safeguards

Apply the installed ship plugin's `agents/writer--sol.md` execution admission and cleanup contract to every lane.
Ordinary touched-file pytest and vitest use automatic slot admission without a per-run CoC GO.
Keep mutation, timing, shared-database, and paid-run GOs, spending caps, host safeguards, and caller-owned TERM-grace cleanup.
The CoC can always issue a GO within existing authority when a lane or chief is stuck.
Follow [canonical push and contact safeguards](references/landing.md#canonical-push-and-contact-safeguards) for each authorized publication.

## Verify and finish

Apply Ship's completion gate before marking a PR ready. Apply the repository's queue check rule to checks that start only after `/merge`. Require those checks before the actual merge. Recheck the head SHA, applicable CI, unresolved threads, mergeability, and branch freshness. Check the file list for scratch artifacts. Compare changed guards and fixtures with the base policy. Prove merge-critical guards at the merge commit with an isolated test.

Apply Ship's proof-after-merge rule. Send `/merge` within 30 minutes after all applicable pre-command gates pass. Keep the repository's merge rules and queue holds. Run the mutation proof at the merge commit.

Every owner or High-priority ticket gets a named driver within 4 hours. The driver opens the PR before any proof work.

When a lane's babysit stops at round 5, review its failures, threads, and fix history. Send the driver one root-cause plan for the next round.

Use [landing and live verification](references/landing.md) for merge authority, dependent lanes, migrations, dark releases, and deployment evidence. Keep sensitive lanes draft-only until the chief's review passes.

At an authorized merged or abandoned transition, run:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/lane-teardown.sh" "<absolute lane worktree>"
```

Use `--abandoned` only for an explicitly closed abandoned lane. Record `REMOVED` or the full `KEPT` reason. Keep ready-for-review worktrees until merge. The script's remote-reachability guard supplements the chief's verified MERGED check.

Finish with a cross-lane check: the goal, combined behavior, remaining decisions, direct PR URLs, verification evidence, and worktree ownership. Keep each external blocker and its exact next action on the board. Continue until the agreed endpoint holds; a draft implementation alone does not satisfy delivery.
