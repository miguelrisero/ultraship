# Ship pipeline

Each step names its ledger `step`. Light mode runs steps 1, 3, 5, 7, 9, 10, and 12.

At any owner-dependent step, apply [owner decisions](owner-decisions.md). Record the Input and blocked scope on the board. Continue independent work without claiming the dependent step passes. Keep external CI/deploy waits tied to their run identities.

| # | Step | Ledger step | Agents |
|---|---|---|---|
| 1 | Guard the branch, open the run | `run-start` | driver |
| 2 | Plan and premises | `plan` | `planner--sol` |
| 3 | Slices | `slices` | `writer--sol`, `reviewer--sol` |
| 4 | High panel on the frozen branch | `panel-high` | `ship:panel high` |
| 5 | Simplify and deep review, in parallel | `simplify`, `deep-review` | `ship:review simplify`, `ship:review` |
| 6 | Select findings | `select` | `reviewer--sol` |
| 7 | One fix batch and one fix read | `fix-read` | `writer--sol`, `reviewer--sol` |
| 8 | Final panel | `panel-final` | `ship:panel final` |
| 9 | Push, PR, merge main, full checks | `pr` | driver |
| 10 | Babysit to green | `babysit` | `ship:babysit` |
| 11 | Closing pass | `closing` | `reviewer--sol` |
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

Drivers copy the [flaky guard lock rule](ci-and-locks.md#flaky-guard-lock) into every writer brief that can run the flaky-pattern guard.

For each slice, in order:

1. Dispatch `writer--sol` with the slice, worktree, base SHA, tests, and commit authority.
2. Confirm the tests pass on the writer's head. When the brief bans local test execution, the writer runs no tests and CI or the coordinator's gated run proves them instead.
3. Dispatch `reviewer--sol` on the slice diff at that SHA.
4. Send real P0 and P1 findings back to the same writer. Commit the fixed slice.

Append one `slices` row when the last slice is committed. Note the slice count and SHAs.

## 4. High panel

Freeze the branch head. Run `ship:panel high` on the branch diff against the conformance snapshot. Append the row before you act on it.

## 5. Simplify and deep review

Freeze the branch head. Run `ship:review simplify` and `ship:review` on the same SHA, in parallel. Append one row for each.

## 6. Select findings

Give `reviewer--sol` every finding from steps 4 and 5 with its evidence. It returns the accepted list, each with a reason, and the rejected list, each with the refuting evidence.

## 7. One fix batch and one fix read

1. Send the accepted list to `writer--sol` as one batch. It returns one fix commit.
2. Dispatch `reviewer--sol` once on the fix diff: did each fix land, and did it break anything?
3. A new P0 or P1 from the fix read gets one more fix commit and one more read. After that, stop and report.

## 8. Final panel

Freeze the branch head. Run `ship:panel final`. A P0 returns to step 7 with that finding only.

## 9. Push and PR

Drivers copy the [flaky guard lock rule](ci-and-locks.md#flaky-guard-lock) into every writer brief that can run the flaky-pattern guard.

1. Merge current remote main into the branch. Resolve conflicts and rerun affected tests.
2. Run the full lint and test suite locally.
3. Before every authorized feature push, including retries and later pushes, the driver performs this resolved destination preflight in the lane worktree.
   Writers prepare repository, branch, and command evidence only; the authorized driver executes the preflight and push.
   Preserve existing push authority, approval holds, merge holds, and verification gates; writers retain zero push authority, including push dry-runs.

   - Before recording or capturing any resolved push URL, require supported, permitted credential-safe inspection of the resolved endpoint.
     The inspection must report credential presence and repository identity without exposing raw credential values to tool output, logs, or evidence.
     Refuse credential-bearing HTTPS push URLs, including credentials in userinfo or query parameters, before URL output or a network probe.
     Block if credential-safe inspection is denied, unavailable, or inconclusive; never print a raw URL to discover whether it contains credentials.
     Writers and drivers must keep credential values out of commands, briefs, boards, and evidence.
   - Confirm the repository with `git rev-parse --show-toplevel` and the lane's repository identity through supported repository metadata.
     Only after the credential-safe gate passes, record `git rev-parse HEAD`, `git branch --show-current`, and `git remote get-url --push --all origin`.
     Require the brief's named feature branch and intended repository at the resolved push URL. Refuse detached HEAD and `main`.
     Require exactly one approved push URL after `pushurl`, `insteadOf`, and `pushInsteadOf` resolution; refuse additional or ambiguous endpoints.
     Confirm the actual default branch with `git ls-remote --symref <push-url> HEAD` for that endpoint and supported repository metadata.
     Refuse a missing or ambiguous symbolic default, metadata disagreement, and a feature branch equal to the actual default branch.
   - Run `git rev-parse --abbrev-ref @{u}`. If it names `main`, `origin/main`, or the actual default branch locally or remotely,
     block the push and establish feature tracking, then repeat the check.
     A missing upstream permits every explicit feature push only after the complete resolved destination preflight passes for that push attempt.
     Inherited upstream and `push.default` are risk context, not resolved destination evidence.
   - Substitute the verified literal feature branch into `HEAD:refs/heads/<feature-branch>`.
     The dry-run runs the pre-push hook; block if its workload lacks admission under the current brief.
     Preserve hooks; never use `--no-verify` to obtain destination evidence.
     Run only the permitted `git push --dry-run --porcelain origin HEAD:refs/heads/<feature-branch>` as the destination probe.
     Use the same repository, HEAD SHA, current branch, remote, and literal refspec for the authorized push.
     Set `LC_ALL=C` for parseable Git output and retain stdout, stderr, exit status, and the exact command as evidence.
   - Inspect every `To` endpoint and every porcelain status row, including up-to-date refs.
     Match the dry-run's resolved push URL to the approved repository identity; the remote name `origin` alone proves no identity.
     Require the sole approved endpoint and exactly one destination row with source `HEAD` and destination `refs/heads/<feature-branch>`.
     Accept only a normal update, new branch, or up-to-date status (` `, `*`, or `=`).
     Refuse `main`, the actual default branch, extra refs, tags, deletions, forced updates, and rejected refs anywhere in the output.
     Block when evidence is denied, unavailable, unsuccessful, empty, or unparseable. Never infer success from the command text alone.
   - Recheck the recorded repository, HEAD SHA, branch, push URL, default branch, and command before execution.
     Repeat the complete preflight after any change; evidence applies only to this push attempt.
     To execute, remove only `--dry-run --porcelain`: use `git push origin HEAD:refs/heads/<feature-branch>`.
     Never use an abbreviated or default push. Never target a default branch.
4. Open one PR, or update the open PR. Put scope, behavior, verification steps, and risks in the body.

## 10. Babysit

Run `ship:babysit` on the PR until required CI is green and zero threads are unresolved. Append one row per round, and a final `babysit` row with verdict `pass`.

## 11. Closing pass

Dispatch `reviewer--sol` on the first-parent commits since the last reviewed SHA: `git log --first-parent <last-reviewed>..HEAD`. A real finding goes back to step 7, then step 10.

## 12. Completion gate

Run the gate in `SKILL.md`. Append `gate` with the head SHA, then run `ledger.py run-end`.

## 13. Handoff

Report in chat:

- The direct PR URL and head SHA.
- What changed for the user, in two or three sentences.
- A `Deferred` list: findings accepted as out of scope, each with a reason.
- Remaining owner actions, each with a link.
