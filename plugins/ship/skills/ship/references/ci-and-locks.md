# CI reads and flaky guard locks

## GitHub quota

CI snapshots use GraphQL `gh pr checks` or `gh pr view`; the installed script uses `gh api graphql`. The required-context checker reads classic required status checks and branch rules once at startup to determine the required contexts.
Limit each polling reader to at most once every 5 minutes per PR, including reader handoffs. Run one CI reader at a time during babysit, including Better Review reads and `watch-checks.sh`.
One-shot completion-gate reads in `skills/ship/SKILL.md` are exempt from this polling cadence. Never use `gh run watch`, a check-runs loop, job polling, or repeated status comments.
Read one failed log once per failure with `gh run view <run-id> --log-failed`. Read a merge queue from its own `/mq/queue` endpoint where the repository has one.
Chief and driver watchers use only the installed `chief-of-chiefs` script from `bettergroupinc/better-plugin`; model polling, recurring model timers, and watcher subagents are forbidden.
Discover the active install with `COC_PLUGIN_ROOT="$(jq -er '[.plugins["chief-of-chiefs@better-plugin"][]?.installPath] | unique | if length == 1 then .[0] else error("chief-of-chiefs install missing or ambiguous") end' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json")" || exit 1`. Missing or ambiguous discovery, a missing script, or unavailable runtime configuration blocks the wait; never fall back to model polling.
Launch `python3 "$COC_PLUGIN_ROOT/skills/run/scripts/watchers.py" wait --repo <OWNER/REPO> --pr <number> --interval 300 --max-seconds <remaining-stage-seconds>` with Bash `run_in_background: true`. Keep the existing stage deadlines across rearms: Better Review's 25-minute custody window; CI's 600-second start and 5400-second overall bounds. The script discovers the CoC runtime configuration; repeated `--pr` arguments batch PRs in one repository. Never overlap this wait with another reader for those PRs.
The script's exit notification wakes the caller; unchanged samples stay silent. Messages contain only a state transition, a blocker, or a decision need. A timeout supplies no completion evidence; take the stage snapshot before any rearm. An expired CI bound remains a blocker. A duplicate waiter requires custody resolution. A rollup transition supplies no exact-head required-context or Better Review coverage proof; the sole reader verifies both on the current head within the same five-minute cadence before claiming completion.

## Flaky guard lock

Run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/lock-idle.py" <lock-file>` in the guard's PID namespace.
The probe reads `/proc/locks` and `/proc/[0-9]*/fdinfo/*` and reports holder and waiter PIDs.
The probe skips unreadable fdinfo for other users because the guard and its children share one UID.
The lock serves one holder at a time. Each lane runs at most one guard, which holds the lock or waits as one waiter.
For Patricia, probe `/var/ops/CoC/gate/locks/flaky-guard.lock` before `make test-flaky-patterns`; keep the guard's own bound unchanged.
Launch the guard when the probe lists no PID of the lane's own guard, even behind other holders and waiters.
Record the guard's PID; never start a second guard while that PID holds or waits.
`flock` wakes waiters in no fixed order, so a lane can wait behind a later arrival.
While the lane's guard waits, re-probe every 60 seconds for up to 10 minutes.
If the guard still waits after 10 minutes, report the holder and waiter PIDs to the chief as a blocker and keep the guard waiting.
Never skip the guard silently.
Treat a probe error as a blocker.
Never flock, delete, or signal through the probe.
Drivers copy this lock rule into every writer brief that can run the flaky-pattern guard.
