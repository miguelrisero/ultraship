# Goal mode

Freeze the task first. Substitute it into this block, print it, and stop. Do not run the workflow.

```text
/goal Ship "<task>" to a ready-for-review pull request with /ship:ship <mode>. Plan with ship:planner--sol, write code with ship:writer--opus, and review each step at a frozen SHA with the ship:* reviewers. Keep one ledger run and record every review. Resolve real findings and task-related test failures. Require current-head required CI, zero unresolved review threads, end-to-end evidence at the deepest safe level, and `ledger.py gaps` with no gaps. Keep scope fixed, preserve product guards, and follow the repository's attribution and version rules. Continue until these conditions hold or a concrete external blocker needs user action. Merge and production actions need their own authority.
```

Check the length before you print it:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/goal-length-check.py" <<'GOAL'
<the block>
GOAL
```

Tell the user: "Paste the block to start the goal."

Printing this text does not start a goal. The CLI owns `/goal`. If a goal already controls this session, keep it and do not start a second stop mechanism.
