---
name: babysit
description: Drive an open pull request to green required CI and zero unresolved review threads, with Better Review triage, main merges, one fix batch per round, and a round-5 chief review. Use for an explicit babysit request or step 10 of the ship pipeline.
argument-hint: "[<PR URL or number>]"
allowed-tools: Read, Grep, Glob, LSP, Edit, Write, Agent, SendMessage, Bash
---

# Babysit

Bring the PR in `$ARGUMENTS`, or the current branch's PR, to green required CI and zero unresolved threads on the current head.

## Push boundary

Before every authorized feature push, including direct invocation, retries, round fixes, and main merges, apply the [resolved destination preflight](../ship/references/pipeline.md#9-push-and-pr). Use only `git push origin HEAD:refs/heads/<feature-branch>` with the verified literal feature branch substituted. Writers prepare evidence only; the authorized driver executes the preflight and push; writers retain zero push authority, including push dry-runs. Preserve existing push authority, approval holds, merge holds, and verification gates.

Apply [CI reads and flaky guard locks](../ship/references/ci-and-locks.md) during polling and guard execution.

## One round

1. **Wait for Better Review.** For `.github/workflows/better-review.yml`, the sole reader takes an initial snapshot of the latest `better-review/review` check through `gh pr checks` or `gh pr view --json statusCheckRollup`.
   Pending work uses the installed chief-of-chiefs `watchers.py wait` route in [CI reads and flaky guard locks](../ship/references/ci-and-locks.md), with Bash `run_in_background: true`; model polling and watcher subagents are forbidden. Unchanged samples stay silent; after each wait exits, the sole reader verifies Better Review on the current head. Messages contain only transitions, blockers, or decision needs. The 5-minute polling cadence covers the initial snapshot and every reader handoff. Better Review custody finishes before the CI reader starts. While it is `in_progress` and younger than 25 minutes, do not push or merge main. A push during a run discards that run.
2. **Wait for CI.** The same background `watchers.py wait` route owns recurring reads. At CI entry and after the wait exits, the sole reader checks required contexts on the current head with `bash "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/watch-checks.sh" <PR> 0 0`, subject to the same cadence. This invocation takes one snapshot and never runs beside the background wait. The checker requires every context from classic protection and branch rules to report and pass. An absent context counts as pending. Pending contexts return custody to the background wait; a rollup transition alone proves neither required-context success nor Better Review coverage. Exit 4 means the checker cannot determine the required contexts; its reason blocks progress until access or protection configuration permits verification. `WATCH_CHECKS_IGNORE` defaults to empty and accepts exact context names, one per line. For checks that report only after `/merge`, the snapshot command is `WATCH_CHECKS_IGNORE="Merge Queue Gate" bash "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/watch-checks.sh" <PR> 0 0`. Ignore only the repository's post-merge-command checks.
3. **Collect.** Read one failed log once per failure with `gh run view <run-id> --log-failed`. List threads with `bash "${CLAUDE_SKILL_DIR}/scripts/threads.sh" <PR>`.
4. **Triage.** Give the failures and threads to `ship:triage--sol`. It returns `real`, `false-positive`, `duplicate`, or `already-fixed` for each item, with evidence.
5. **Fix.** Collect every failing check and every unresolved thread before the fix. Send all `real` items to `ship:writer--sol` as one batch. Rerun the affected tests, unless the brief bans local test execution; then CI reruns them. Push once for the round. Never push a partial batch.
6. **Answer every thread.** Reply with the fix commit or the refuting evidence, then resolve the thread:

   ```bash
   gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -F id=<thread-id>
   ```

7. **Record.** Append `babysit` to the ledger with the head SHA and verdict `round-<n>`.

## Better Review

- The bot login is `betterreview`. Resolve its threads yourself; the bot does not resolve them.
- In repositories where a push starts a run automatically, do not post a trigger. Elsewhere, post a comment whose whole body is `/better-review`, optionally followed by one of `full`, `rerun`, or `default`. Any other text stops the trigger.
- Coverage is a `better-review/review` check with conclusion `success` on the current head. A `neutral` conclusion is not coverage; trigger a new run when the head did not move.
- Better Review is the only review bot in this flow.

## Merge main

When `gh pr view --json mergeStateStatus` reports `BEHIND` or `DIRTY`, merge current remote main into the branch. Resolve conflicts, rerun affected tests, and push in the same round as other fixes. Never rebase or force-push a published branch without explicit authority.

## Breaker

- Target 6 pushes or fewer per PR.
- When the same failure signature repeats twice, dispatch `ship:reviewer--sol` on the failures, the threads, and the fix history. Follow its root-cause plan in the next round.
  Require flaky-risk findings with file, line, and mechanism, or explicit none with inspected scope, in this review brief and every fallback.
- At round 5, stop for a chief review. Send the chief, or the user when no chief runs, the open failures and threads, each with its link, the fix history, and the next action. Resume only with the chief's plan.

## Done

End when required CI passes on the head, `threads.sh` prints nothing, and a successful Better Review check covers the head where the workflow exists. Append `babysit` with verdict `pass`.
