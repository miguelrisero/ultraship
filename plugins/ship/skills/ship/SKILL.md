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

Read [owner decisions](references/owner-decisions.md) before dispatch. Register material owner decisions as Inputs and continue independent work.

- Read [roster](references/roster.md) before the first dispatch. Use each scoped `ship:*` agent and leave the Agent `model` field unset. A hook denies overrides.
- On an unavailable agent, dispatch the next agent in its fallback chain and record the substitution in the ledger note.
- Code goes to `ship:writer--sol`, one slice at a time, in the assigned worktree. Continue an existing writer with SendMessage for fixes on its slice.
- Writers cannot push, merge, deploy, or publish. The driver does these steps within the granted authority.
- Important planning goes to `ship:planner--sol`. Broad research goes to `ship:researcher--luna`.
- Freeze one subject SHA per review step. Give every seat the same brief and keep sibling verdicts out of it.

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
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" append <step> <agent> <sha> <verdict> [note]
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" gaps
python3 "${CLAUDE_SKILL_DIR}/scripts/ledger.py" run-end
```

Append a row as soon as each review, panel, or CI round returns. Use the step names in [pipeline](references/pipeline.md). `run-end` refuses while a required step has no row. Stop retains pending reviewer evidence until each result has a successful accounting row in its bound run, including a successfully closed run. Persistent hook-state receipts consume each row once across Stop cycles. Keep hook-state receipts with the pending evidence.

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

Re-read `headRefOid` after verification. A changed head reopens the affected steps. Finish with the direct PR URL. Merge and production actions need their own authority.

## Boundaries

Never widen, raise, or relax a limit, cap, timeout, budget, bound, or guard constant — and never adjust a validator or test to accept a new value — to make a check pass. Report the blocking bound and fix the consumer side. This covers test baselines, fixtures, and goldens. Exception: an owner-requested product-limit change is a feature (owner rule, Input 2b7e497e-a794-4ab2-a62c-0f1748396967, owner_ui event 485, a_allow). The writer implements only the specifically requested product limit, including when that limit exists on origin/main. Add boundary tests that accept the new limit and refuse the limit plus one unit; for byte limits, refuse one additional byte (for example, accept 536870912 bytes and refuse 536870913 bytes). For every bound the owner did not ask to change, preserve the stop-and-report rule and fix the consumer side, subject to the existing branch-only and same-guarantee test-edit exceptions below. This product-limit exception grants no authority to change unrelated safety, security, resource, budget, or timeout bounds or to weaken other guarantees. Preserve normal review, CI, and applicable consent requirements. Record the owner request and its exact scope in the brief and PR body. This product-limit exception applies independently of the two exceptions below. This rule covers limits that exist on origin/main. Exception: a limit, cap, timeout, budget, or bound that only this PR branch added is the lane's design choice (owner rule, Input 6e43dda9-a1b8-4b0e-a8c8-f3525a67a5e9). Run `git fetch origin main` first and record the `origin/main` SHA; when the fetch fails, the exception does not apply. Compare the behavior the bound constrains, not its path or name: `git grep` main's whole tree and read the branch diff (`git diff origin/main...HEAD`) for the same invariant, including replacements, duplicates, validators, test baselines, fixtures, and goldens. A missing path on main is not enough evidence. When main has no such bound, change or remove it without an owner question, and record the reason and the main SHA in the PR body. Every bound already on main keeps this rule, also when the branch moves, renames, replaces, or changes it. Exception: a test, fixture, mutation row, census or register edit is allowed without an owner question after one council round (no Fable or cf-* models) agrees that the guard keeps its guarantee (owner grant 2026-10-26: "ok I give you from now onwards full power to change tests, no need to check with me, just do one council round to analyze it makes sense and is appropiate, and do it."). Weakening a test to hide a real regression stays forbidden. Record the council verdict and the owner words in the PR body. Exception: no step waits for a human to apply an edit. When the executor is certain and its Chief or the CoC checked the change, that check replaces the council round, and an agent applies it (owner order 2026-10-30: "if agent is certain that its ok and he checked with his CoC or Chief ALL GOOD remove that blocker everywhere"). Record that check in the PR body.

Preserve validation, authorization, tenant isolation, atomicity, and logging. Honor permission denials. Skip hook bypasses and force-pushes without explicit user authority. Keep scratch files outside lane worktrees and version control.
