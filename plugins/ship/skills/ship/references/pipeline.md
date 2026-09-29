# Ship pipeline

Each step names its ledger `step`. Light mode runs steps 1, 3, 5, 7, 9, 10, and 12.

| # | Step | Ledger step | Agents |
|---|---|---|---|
| 1 | Guard the branch, open the run | `run-start` | driver |
| 2 | Plan and premises | `plan` | `planner--sol` |
| 3 | Slices | `slices` | `writer--sol`, `reviewer--sol-xhigh` |
| 4 | High panel on the frozen branch | `panel-high` | `ship:panel high` |
| 5 | Simplify and deep review, in parallel | `simplify`, `deep-review` | `ship:review simplify`, `ship:review` |
| 6 | Select findings | `select` | `reviewer--sol-xhigh` |
| 7 | One fix batch and one fix read | `fix-read` | `writer--sol`, `reviewer--sol-xhigh` |
| 8 | Final panel | `panel-final` | `ship:panel final` |
| 9 | Push, PR, merge main, full checks | `pr` | driver |
| 10 | Babysit to green | `babysit` | `ship:babysit` |
| 11 | Closing pass | `closing` | `reviewer--sol56-max` |
| 12 | Completion gate | `gate` | driver |
| 13 | Handoff | — | driver |

## 1. Guard and open

1. Confirm the repository, a clean owned worktree, GitHub access, and a branch based on current remote main.
2. Stop on the default branch. Create a branch and worktree first.
3. Run `ledger.py run-start <mode> <run-id> [board-path]`. Reuse an open run on the same branch.

## 2. Plan and premises

Dispatch `planner--sol` with the objective, constraints, and evidence paths. Freeze its output in the run scratch file:

- Slices in build order, each with files, a test, and an acceptance check.
- Premises, each with a falsifier. Check each falsifier before step 3; a falsified premise returns to planning.
- A conformance snapshot: the acceptance checks the finished branch must meet.

For design-heavy work, run `ship:panel design` on the plan before step 3.

## 3. Slices

For each slice, in order:

1. Dispatch `writer--sol` with the slice, worktree, base SHA, tests, and commit authority.
2. Confirm the tests pass on the writer's head.
3. Dispatch `reviewer--sol-xhigh` on the slice diff at that SHA.
4. Send real P0 and P1 findings back to the same writer. Commit the fixed slice.

Append one `slices` row when the last slice is committed. Note the slice count and SHAs.

## 4. High panel

Freeze the branch head. Run `ship:panel high` on the branch diff against the conformance snapshot. Append the row before you act on it.

## 5. Simplify and deep review

Freeze the branch head. Run `ship:review simplify` and `ship:review` on the same SHA, in parallel. Append one row for each.

## 6. Select findings

Give `reviewer--sol-xhigh` every finding from steps 4 and 5 with its evidence. It returns the accepted list, each with a reason, and the rejected list, each with the refuting evidence.

## 7. One fix batch and one fix read

1. Send the accepted list to `writer--sol` as one batch. It returns one fix commit.
2. Dispatch `reviewer--sol-xhigh` once on the fix diff: did each fix land, and did it break anything?
3. A new P0 or P1 from the fix read gets one more fix commit and one more read. After that, stop and report.

## 8. Final panel

Freeze the branch head. Run `ship:panel final`. A P0 returns to step 7 with that finding only.

## 9. Push and PR

1. Merge current remote main into the branch. Resolve conflicts and rerun affected tests.
2. Run the full lint and test suite locally.
3. Push. Open one PR, or update the open PR. Put scope, behavior, verification steps, and risks in the body.

## 10. Babysit

Run `ship:babysit` on the PR until required CI is green and zero threads are unresolved. Append one row per round, and a final `babysit` row with verdict `pass`.

## 11. Closing pass

Dispatch `reviewer--sol56-max` on the first-parent commits since the last reviewed SHA: `git log --first-parent <last-reviewed>..HEAD`. A real finding goes back to step 7, then step 10.

## 12. Completion gate

Run the gate in `SKILL.md`. Append `gate` with the head SHA, then run `ledger.py run-end`.

## 13. Handoff

Report in chat:

- The direct PR URL and head SHA.
- What changed for the user, in two or three sentences.
- A `Deferred` list: findings accepted as out of scope, each with a reason.
- Remaining owner actions, each with a link.
