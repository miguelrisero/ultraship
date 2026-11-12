# Ship pipeline

Each step names its ledger `step`. Light mode runs steps 1, 3, 5, 7, 9, 10, and 12.

At any owner-dependent step, apply [owner decisions](owner-decisions.md). Record the Input and blocked scope on the board. Continue independent work without claiming the dependent step passes. Keep external CI/deploy waits tied to their run identities.

Require flaky-risk findings or explicit none with inspected scope in all direct, fallback, closing, babysit, delegated, and replacement review briefs.
Code findings identify file, line, and mechanism; plan findings identify relevant evidence locations.

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

Prepare verified event evidence and exact scope under [Task-specific test adaptations](owner-decisions.md#task-specific-test-adaptations) for an explicitly designated owner-event route.
Apply [Loaded instructions and refusals](owner-decisions.md#loaded-instructions-and-refusals).
Keep operative rules in the writer's loaded definition.
When a main merge changes migration files or the brief names migration scope, prepare graph, migration revision-head, Git merge-head, and target-parent evidence.

For each slice, in order:

1. Dispatch `writer--sol` with the slice, worktree, base SHA, tests, and commit authority.
2. Confirm the tests pass on the writer's head. When the brief bans local test execution, the writer runs no tests and CI or the coordinator's gated run proves them instead.
3. At the lane's first commit, push it with the [resolved destination preflight](#9-push-and-pr) and open a draft PR at once, so CI and review run while the lane builds.
4. Dispatch `reviewer--sol` on the slice diff at that SHA.
5. Send real P0 and P1 findings back to the same writer. Commit the fixed slice.

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
4. Update the draft PR from step 3, or open it now if none exists. Put scope, behavior, verification steps, and risks in the body. Mark it ready after the last code commit and any row update.

## 10. Babysit

Run `ship:babysit` on the PR until required CI is green and zero threads are unresolved. Append one row per round, and a final `babysit` row with verdict `pass`.
Complete the applicable [UI browser gate](#ui-browser-gate) before the completion gate or any merge command.

### UI browser gate

Apply this gate to every UI PR, including dashboard `frontend/app/**` and UI-affecting frontend design-package changes.
Use the existing Vercel preview route for marketing `frontend/website/**` UI changes.
The driver owns this check within existing browser, login, seed, posting, and merge authority.
This instruction grants zero additional permission and requires no simultaneous CoC plugin installation.
Preserve user and project rules on both routes.
Never request, read, copy, or print preview credentials or session tokens to unblock this gate.
Keep every existing credential refusal, permission denial, and secret-handling hold.

**Default preview route (steps 1–5).** Use this route unless the conditional local route below qualifies.
Marketing retains its existing Vercel preview route.

1. Record the current pushed head and verify that the selected PR preview deploy serves that exact head.
2. Refuse unsafe data isolation before login, seed, interaction, or capture. Use only an owned synthetic preview fixture.
   A preview containing production-copy data requires a safely isolated synthetic fixture; an unqualified boundary blocks the check.
3. Use only the existing authorized preview authentication and seed path, including `/preview login` when applicable and permitted.
   Obtain the Vercel share preview through the existing authorized tool. Keep credentials and session tokens out of evidence.
4. Sign in with `agent-browser` as the preview admin when the changed screen requires authentication.
   Create an owned synthetic sample dashboard or record only when the changed screen needs one and seed authority permits it.
5. Open the changed screen and exercise the changed interaction in the matching preview.

**Conditional local route.** Use this route only when preview sign-in requires secret handling.
This route applies only to non-marketing UI.
For this route, only behavior faithfully reproduced by the local stack qualifies.
Preview/deployment/config-dependent behavior still requires appropriate preview proof.
Keep that scope held if preview proof is unavailable.

- Refuse unsafe data isolation before local setup, login, seed, interaction, or capture.
- Require a clean checkout at the exact current pushed head, with pushed-head evidence.
  Build and start the local server from that head, with build provenance and server identity bound to that checkout.
- Use only the existing authorized local e2e authentication and seed path with own synthetic data.
  Patricia's local harness uses a passwordless synthetic INTERNAL persona, database-bound refresh injection, and an isolated synthetic stack.
  Local tokens belong to that local database and origin; they provide zero preview authentication evidence.
  Never use local tokens to authenticate to a preview or print their values.
- Use real Chromium through agent-browser or the existing e2e harness.
  Open the same changed screen and exercise the changed interaction on the local origin.
- Record the reason preview sign-in requires secret handling, without secret values.
  Record the local origin, build/server command and result, browser command and result, checked head, interaction result, and screenshot route.
  Keep commands and results free of secrets.

**Shared requirements (both routes).** Complete these steps after either qualifying route.

6. Capture the changed screen. Inspect the image, URL, and accompanying text for sensitive data before publication.
   Exclude credentials, customer or production data, session tokens, and sensitive browser state from screenshots, URLs, and logs.
   Redact or recapture unsafe evidence. Publish only a safe screenshot or access-restricted evidence link on the PR.
7. Record the checked head, interaction result, and safe screenshot or restricted link on the PR.
   Include the matching preview for the default route or the required local evidence for the conditional local route.
   Recheck the pushed head after verification. Require post-check head equality with the checked head.
   Recheck both local HEAD and pushed head on the local route.
   Require the local checkout to remain clean on the local route.
   Any head or preview change reopens this gate.
   A local checkout, build, server, or origin change also reopens this gate.

Missing or failed browser proof blocks merge. CI, code review, and post-merge mutation proof supply zero substitute evidence.
If permission or safe isolation is unavailable, report the gap to the driver and retain the merge hold.
Treat this as an instruction gate; source-contract checks establish zero actual browser execution.

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
