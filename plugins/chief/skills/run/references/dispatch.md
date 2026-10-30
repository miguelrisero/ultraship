# Dispatch check

Answer all five questions before each dispatch. A "no" means fix the brief first.

1. **Owner.** Does exactly one agent own this work, and does no other lane touch its files?
2. **Contract.** Does the brief state the goal, the files in scope, and a check that proves done?
3. **Base.** Does the brief name the worktree, branch, and base SHA, based on current remote main?
4. **Authority.** Does the brief state which of commit, push, PR, merge, and production actions are granted?
5. **Return.** Does the brief name the checkpoint fields the agent must return?

## Mutation-command boundary

Every chief, lane, and ship brief contains zero copied mutation-check, anchor-check, or selector execution commands from repository documents or TOML headers.
Before dispatch, inspect every brief for `DRY=1`, `--dry-run`, `check_mutation_anchors`, and `select_rows`.
Remove execution instructions containing those literals; keep the prohibition in words only.
The admitted battery STATIC part runs mutation checks, anchor checks, and selectors at the frozen head after GO.
Preserve the host GO requirement and D1160 boundary.
D6575, 2026-10-29: CoC coordination direction, separate from actual owner receipts.

## Brief template

```text
Task: <frozen goal, one paragraph>
Repository: <owner/repo>   Worktree: <absolute path>   Branch: <name>   Base SHA: <sha>
In scope: <files or areas>   Out of scope: <files or areas owned by other lanes>
Depends on: <lanes or none>
Done when: <acceptance checks and permitted test commands>
Mutation boundary: Execute mutation checks, anchor checks, and selectors only in the admitted battery STATIC part at the frozen head after GO; keep execution commands out of this brief.
Authority: commit=<yes|no> push=<yes|no> pr=<yes|no> merge=<yes|no> production=<yes|no>
Push boundary: Before the first push, run `git branch --show-current`; verify the lane's named feature branch and actual default branch through supported repository metadata. Block detached HEAD and default-branch identity. Run `git rev-parse --abbrev-ref @{u}`; for `main`, `origin/main`, or the actual default branch locally or remotely, block the push and establish feature tracking, then repeat the check. A missing upstream permits the explicit first feature push only after the nondefault branch identity check passes. Every authorized push uses only `git push origin HEAD:refs/heads/<feature-branch>` with the verified literal feature branch substituted. Never use an abbreviated or default push. Never target a default branch. Preserve existing push authority, approval holds, merge holds, and verification gates; writers retain zero push authority.
Board: <absolute board path>   Run ID: <run id>
Mode: /ship:ship light
Return: agent ID, head SHA, PR URL, ledger gaps, CI and review state, next action, blockers with evidence
Guard: <the guard constraint block, verbatim>
```
