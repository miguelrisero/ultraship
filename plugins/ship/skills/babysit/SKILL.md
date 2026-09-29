---
name: babysit
description: Drive an open pull request to green required CI and zero unresolved review threads, with Better Review triage, main merges, and a 10-round breaker. Use for an explicit babysit request or step 10 of the ship pipeline.
argument-hint: "[<PR URL or number>]"
allowed-tools: Read, Grep, Glob, LSP, Edit, Write, Agent, SendMessage, Bash
---

# Babysit

Bring the PR in `$ARGUMENTS`, or the current branch's PR, to green required CI and zero unresolved threads on the current head.

## One round

1. **Wait for Better Review.** In a repository with `.github/workflows/better-review.yml`, read the latest `better-review/review` check run on the head. While it is `in_progress` and younger than 25 minutes, do not push or merge main. A push during a run discards that run.
2. **Wait for CI.** Run `bash "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/watch-checks.sh" <PR>` in the background. An empty required-check list means CI did not start.
3. **Collect.** Get failed logs with `gh run view <run-id> --log-failed`. List threads with `bash "${CLAUDE_SKILL_DIR}/scripts/threads.sh" <PR>`.
4. **Triage.** Give the failures and threads to `ship:triage--glm`. It returns `real`, `false-positive`, `duplicate`, or `already-fixed` for each item, with evidence.
5. **Fix.** Send all `real` items to `ship:writer--sol` as one batch. Rerun the affected tests. Push once for the round.
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

- At round 5, or when the same failure signature repeats twice, dispatch `ship:reviewer--sol` on the failures, the threads, and the fix history. Follow its root-cause plan in the next round.
- At round 10, stop. Report the open failures and threads, each with its link, and the next action.

## Done

End when required CI passes on the head, `threads.sh` prints nothing, and a successful Better Review check covers the head where the workflow exists. Append `babysit` with verdict `pass`.
