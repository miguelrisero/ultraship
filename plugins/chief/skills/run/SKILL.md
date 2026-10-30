---
name: run
description: Coordinate a multi-lane engineering task through ship writers and drivers, verified pull requests, and a persistent status board. Use for an explicit /chief:run request; use review <scope> for a bounded independent review.
argument-hint: "[review <scope> | <task>]"
---

# Chief

Coordinate the task in `$ARGUMENTS` from the main session, at the session model. Keep decisions and the status board here. Delegate planning, research, code, and the ship tail.

Chief needs the `ship` plugin. Check that `ship:driver` and `ship:writer--sol` are available before the first dispatch.

Read the shared owner-decision contract at `skills/ship/references/owner-decisions.md` in the installed ship plugin. Apply it to every material owner decision.

## Roles

| Work | Agent |
|---|---|
| Important planning | `ship:planner--sol` |
| Code for one slice | `ship:writer--sol` |
| A lane's ship tail: reviews, PR, CI, gate | `ship:driver` |
| Broad research | `ship:researcher--luna` |
| Independent review | `ship:review` or a `ship:reviewer--*` seat |
| Billing and authorization verification | `ship:verifier--fable` |

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
- The board path and the chief run ID.
- The granted commit, push, PR, merge, and production permissions.
- The instruction to run `ship:ship light` inline, with this contract as its task.
- The checkpoint to return: agent ID, head SHA, PR URL, ledger gaps, CI and review state, next action.
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

Use native completion notifications. Persist the awaited run identity and next action for external CI and deploy waits. Check state before you resume a lane. Continue other eligible work during a model outage or an owner blocker.

At each checkpoint, inspect the lane's commit stack and upstream state. A missing upstream counts as unpushed work. Preserve pushed history; use a revert for a published mistake.

## Verify and finish

Require the ship completion gate before a lane reaches ready-for-review. Recheck GitHub state yourself: head SHA, required CI, unresolved threads, mergeability, and branch freshness. Check the file list for scratch artifacts. Compare changed guards and fixtures with the base policy. Prove merge-critical guards catch a deliberately broken case in an isolated test.

Use [landing and live verification](references/landing.md) for merge authority, dependent lanes, migrations, dark releases, and deployment evidence. Keep sensitive lanes draft-only until the chief's review passes.

At an authorized merged or abandoned transition, run:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/lane-teardown.sh" "<absolute lane worktree>"
```

Use `--abandoned` only for an explicitly closed abandoned lane. Record `REMOVED` or the full `KEPT` reason. Keep ready-for-review worktrees until merge. The script's remote-reachability guard supplements the chief's verified MERGED check.

Finish with a cross-lane check: the goal, combined behavior, remaining decisions, direct PR URLs, verification evidence, and worktree ownership. Keep a concrete external blocker visible with the exact action needed. Continue until the agreed endpoint holds; a draft implementation alone does not satisfy delivery.
