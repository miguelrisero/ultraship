---
name: run
description: Coordinate a multi-lane engineering task through ship writers and drivers, verified pull requests, and a persistent status board. Use for an explicit /chief:run request; use review <scope> for a bounded independent review.
argument-hint: "[review <scope> | <task>]"
---

# Chief

Coordinate the task in `$ARGUMENTS` from the main session, at the session model. Keep decisions and the status board here. Delegate planning, research, code, and the ship tail.

Chief needs the `ship` plugin. Check that `ship:driver` and `ship:writer--sol` are available before the first dispatch.

## Roles

| Work | Agent |
|---|---|
| Important planning | `ship:planner--sol` |
| Code for one slice | `ship:writer--sol` |
| A lane's ship tail: reviews, PR, CI, gate | `ship:driver` |
| Broad research | `ship:researcher--flash` |
| Independent review | `ship:review` or a `ship:reviewer--*` seat |
| Billing and authorization verification | `ship:verifier--fable` |

Leave the Agent `model` field unset. Fallback chains are in the ship plugin's `skills/ship/references/roster.md`. Record every substitution on the board.

Nesting: chief → driver → writers and reviewers. Keep ship, panel, and review inline inside the driver.

## Entry points

- `review <scope>`: gather the diff and base and head SHAs. Run `ship:review` read-only. Return verified findings. Take no shipping action.
- `<task>`: establish scope, acceptance criteria, repository, and delivery authority. Ask only for a decision that blocks progress.
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

Each lane gets a branch and a linked worktree based on current remote main, inside the permitted workspace. Serialize overlapping file ownership.

Dispatch `ship:driver` for each lane with:

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
```

The driver dispatches `ship:writer--sol` for code and keeps every fix inside its lane.

Cap active development at three lanes, or six for explicitly selected cheap work. Drain the queue when capacity frees up. Surface lanes queued over four hours with an ETA or a priority decision.

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
