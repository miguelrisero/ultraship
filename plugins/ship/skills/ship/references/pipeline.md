# Ship pipeline

Each step names its ledger `step`. Light mode runs steps 1, 3, 5, 7, 9, 10, and 12.
Apply the [important planning gate](#important-planning) in either mode when its scope applies.

At any owner-dependent step, apply [owner decisions](owner-decisions.md). Record the Input and blocked scope on the board. Continue independent work without claiming the dependent step passes. Keep external CI/deploy waits tied to their run identities.

Require flaky-risk findings or explicit none with inspected scope in all direct, fallback, closing, babysit, delegated, and replacement review briefs.
Code findings identify file, line, and mechanism; plan findings identify relevant evidence locations.

<a id="security-review-triage"></a>**Security review triage.**

Copy this block verbatim into every review brief, including verification and fix reads:

```text
Prioritize evidence of clear danger, a realistic attacker path, or harm to customer data, money, or secrets.
Report uncertainty and missing evidence explicitly.
Preserve severity definitions, blocking findings, required fixes, independent review, fix reads, and all merge gates.
```

The driver consolidates deferred security findings at [handoff](#13-handoff).
Avoid another review round solely for a security finding the existing gates permit deferring.

Every initial, verification, and replacement brief lists permitted paths and exclusions.
Apply this rule to every review dispatch, including slice, selection, fix-read, closing, and delegated review seats.
Scope every search call to the permitted paths.
Exclude `tests/mutation/`, generated and vendored content, and any other brief exclusions.
Reviewers use Grep, Glob, and Read with exact absolute paths.
An exact absolute path has no `~`, `.` or `..` segment, repeated or trailing `/`, symlink, surrounding whitespace, or Unicode that is not in NFC form.
A directory path has no trailing `/`: `/abs/repo/backend/api/services`, not `/abs/repo/backend/api/services/`.
When a hook refusal says to report the blocked scope, reviewers report that call as blocked scope in the verdict.
Reviewers may retry that call in another form when the new form meets the rule the refusal names, or ask the coordinator for permission or a new brief.
Reviewers use LSP hover and documentSymbol on one file only.
Reviewers use no MCP (`mcp__`) tools.
Reviewers search only directories that contain no `tests/mutation/` directory.
Report a failed or empty scoped search to the coordinator; never widen the search scope.
Triage and verifier briefs follow these reviewer search rules.
An explicit repository-root path does not authorize broader discovery.

For the [lane-owned row route](../SKILL.md#lane-owned-row-route), dispatch a separate admitted reviewer for the named rows at the frozen head.
Use one independent Sol reviewer for a same-mutant re-anchor of rows the lane's own diff breaks.
Allow the authorized draft push for anchor CI under the lane-owned row route. Require the verdict before marking ready, pushing to a ready PR, or merging.
For [standalone main-row repair](owner-decisions.md#standalone-main-row-repair), except the default row path exclusion only for the separately admitted reviewer and approved row extents.
Keep ordinary review briefs free of protected paths and row hunks. Keep pair bytes and row TOML text out of every brief.
Require the matching frozen review receipt before publication, even when step 9 would otherwise permit it.
Preserve execution admission and the reviewer MCP ban under both [scoped decision routes](owner-decisions.md#scoped-owner-event-verification).

| # | Step | Ledger step | Agents |
|---|---|---|---|
| 1 | Guard the branch, open the run | `run-start` | driver |
| 2 | Plan and premises | `plan` | `planner--opus` (normal), `planner--fable52` (important and P0) |
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

Start normal plans with `ship:planner--opus`. Follow the normal planner chain in the [roster](roster.md).
Start important and P0 plans with `ship:planner--fable52`, then follow the important planner chain in the [roster](roster.md). Apply the [important planning gate](#important-planning) only to important plans.
Give the planner the objective, constraints, and evidence paths. Freeze its output in the run scratch file:

- Slices in build order, each with files, a test, and an acceptance check.
- Premises, each with a falsifier. Check each falsifier before step 3. Return to planning on a falsified premise. Apply the important planning rework limit when applicable.
- A conformance snapshot: the acceptance checks the finished branch must meet.

Require prior confirmation only when the important planning gate applies.
Run `ship:panel design` on the frozen plan before step 3 for design-heavy work.

### Important planning

Use this route only for important planning, such as architecture, contracts, migrations, security, and billing.
P0 alone selects the Fable 5.2 planner chain. The gate applies only if the plan also qualifies as important.
The coordinator owns both rounds; the planner and reviewers stay read-only.
Apply the [helper standing request](owner-decisions.md#helper-standing-request) to every brief, including fallbacks.
List exact permitted paths and exclusions. Apply the reviewer search rules and [security review triage](#security-review-triage) above.
Share only authorized evidence. Keep secrets, protected content, and confidential data outside the brief and any external query.

Apply existing model eligibility and privacy rules to every planner dispatch.
Dispatch `ship:planner--fable52` first for important planning. If Fable is unavailable, use `ship:planner--sol` next.
Follow the important planner chain in the [roster](roster.md). Record the planner that authored the draft.
Keep the plan and dependent work pending when no eligible planner is available.

Before refutation, freeze all evidence outside the repository commit in permitted read-only snapshots.
Record the source identity, exact readable snapshot path, and SHA256 of each item in an evidence manifest.
Use the same manifest in both rounds. Review only the frozen commit and the named snapshots for plan evidence.
Include the evidence manifest SHA256 in both briefs and both review records.
Use an empty manifest when the commit contains all evidence.

1. Dispatch one independent `ship:reviewer--astra` to refute the frozen draft.
   Give the refuter the draft, evidence locations, constraints, and falsifiers without earlier verdicts or coordinator conclusions.
   Ask for counterexamples to material premises, alternatives that meet the constraints, and missing checks, with cited evidence.
2. Resolve each material finding with cited evidence or a change to the plan. Record its disposition separately from the plan.
   Freeze the final plan with its decision, slices, constraints, evidence, falsifiers, and acceptance checks.
   Return to refutation if the final plan introduces a material decision, premise, or scope outside the reviewed draft.
3. Start a fresh `ship:reviewer--opus` Agent with only the frozen final plan, its permitted evidence, and the required brief rules.
   Do not resume any earlier agent. Omit earlier verdicts, review transcripts, and coordinator conclusions.
   Keep the refute findings and the disposition record out of the confirmation brief and its readable files.
   Give the confirmer this task: "Confirm the exact final plan against its evidence and falsifiers. Report a verdict with coverage."

Leave `model` unset. Use the [existing roster fallback chains](roster.md) for unavailable or ineligible seats and record substitutions.
Skip any seat whose pinned model authored the plan or served in the other round. Never use a fallback to bypass a refusal.
Withhold credit if observed routing shows that two roles used the same model.
Include the frozen repository SHA and the SHA256 of the reviewed draft or final plan in each brief.
Use a new agent for each replacement. Require each verdict to name the reviewed identities and its evidence coverage.
Verify the repository evidence at its frozen commit.
Recompute the plan, manifest, and snapshot digests before each review dispatch and before accepting its verdict.
Verify the plan digest and all evidence digests before each dependent dispatch, including the design panel and dependent slices.
Match the recomputed digests to the confirmation record for the final plan.
Recheck them before marking planning complete and before any other dependent action.
Keep dependent work pending on missing, unreadable, or mismatched evidence.
Keep the plan pending if either round is missing, blocked, incomplete, or stale.
Keep unresolved material contradictions pending, even after a confirmation pass. Require a passing confirmation for the exact final plan.

Allow one rework attempt after the initial attempt.
Apply this limit to every return to planning or refutation, including after a failed confirmation or an evidence change.
Persist the rework count in the run record before any return to planning or refutation.
Keep the count for the same planning scope across handoff and recovery.
Return to refutation if the evidence changes between rounds and the limit permits.
Repeat both rounds if the plan or its evidence changes after confirmation and the limit permits.
On exhaustion, keep the plan and dependent slices pending. Report the unresolved issue and the next permitted action to the superior.
Continue independent work. Route owner decisions through the [existing contract](owner-decisions.md) and preserve [execution admission](../SKILL.md#execution-admission).

Record each result under `plan-refute` or `plan-confirm` as it returns.
Use the exact `agent-type@agent-id`, repository SHA, verdict, and frozen plan digest.
Record a passing `plan` row only after both rounds qualify. Keep dependent slices pending until then.
The review gives zero authority for implementation or publication.

## 3. Slices

Start every writer brief with `You may always` and `Only the owner` from the loaded writer definition. Keep the exact brief scope and its prohibitions.
Copy the [flaky guard lock rule](ci-and-locks.md#flaky-guard-lock) into every writer brief that can run the flaky-pattern guard.

Prepare verified event evidence and exact scope under [Task-specific test adaptations](owner-decisions.md#task-specific-test-adaptations) for an explicitly designated owner-event route.
Apply [Loaded instructions and refusals](owner-decisions.md#loaded-instructions-and-refusals).
Keep operative rules in the writer's loaded definition.
When a main merge changes migration files or the brief names migration scope, prepare graph, migration revision-head, Git merge-head, and target-parent evidence.

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

1. Send the accepted list to `writer--sol` as one batch. Follow the [writer brief rules](#3-slices). The writer returns one fix commit.
2. Dispatch `reviewer--sol` once on the fix diff: did each fix land, and did it break anything?
3. A new P0 or P1 from the fix read gets one more fix commit and one more read. After that, stop and report.

## 8. Final panel

Freeze the branch head. Run `ship:panel final`. A P0 returns to step 7 with that finding only.

## 9. Push and PR

Apply the [writer brief rules](#3-slices) to every writer dispatched here.

Use this step early for authorized draft CI on the lane's own feature branch. Required CI and independent review may follow the draft push.
Keep the other pipeline steps pending. Require exact-head green CI and independent review before marking ready or sending `/merge`.
Apply the repository's [queue check rule](../../babysit/SKILL.md#one-round) for checks that start only after `/merge`.
Return a ready PR to draft before an early CI push. Keep it in draft until all applicable readiness gates pass.
Apply existing push holds, protected-row receipts, and preflight requirements even for a draft.

1. Merge current remote main into the branch. Resolve conflicts and rerun the affected tests that the brief admits.
2. Run the full lint and test suite locally when the brief admits it. When the brief bars local tests, use authorized CI or the coordinator's gated run for that proof. Keep any check that the repository requires before push.
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
4. Open one PR at the first push with PR authority, or update the open PR. Use a draft for early CI. Open it before mutation batteries or live checks. Put scope, behavior, verification steps, and risks in the body.

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
- A `Deferred` list: findings the applicable gates permit deferring, each with a reason.
- Remaining owner actions, each with a link.

Consolidate duplicate deferred security findings by mechanism. Give each distinct finding a concise hardening proposal.
Reuse an existing Linear ticket for the same issue. Create one only in the verified, authorized Linear team.
Include its URL in the `Deferred` entry. If custody or access is unclear, keep the entry and report the routing gap.
Send the list to the chief for batched owner review. In a standalone run, include it in the result handoff.
