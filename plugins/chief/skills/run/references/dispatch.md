# Dispatch check

Answer all five questions before each dispatch. A "no" means fix the brief first.

1. **Owner.** Does exactly one agent own this work, and does no other lane touch its files?
2. **Contract.** Does the brief state the goal, the files in scope, and a check that proves done?
3. **Base.** Does the brief name the worktree, branch, and base SHA, based on current remote main?
4. **Authority.** Does the brief state which of commit, push, PR, merge, and production actions are granted?
5. **Return.** Does the brief name the checkpoint fields the agent must return?

## Brief template

```text
Task: <frozen goal, one paragraph>
Repository: <owner/repo>   Worktree: <absolute path>   Branch: <name>   Base SHA: <sha>
In scope: <files or areas>   Out of scope: <files or areas owned by other lanes>
Depends on: <lanes or none>
Done when: <acceptance checks and test commands>
Authority: commit=<yes|no> push=<yes|no> pr=<yes|no> merge=<yes|no> production=<yes|no>
Board: <absolute board path>   Run ID: <run id>
Mode: /ship:ship light
Return: agent ID, head SHA, PR URL, ledger gaps, CI and review state, next action, blockers with evidence
Guard: <the guard constraint block, verbatim>
```
