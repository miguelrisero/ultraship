# CI reads and flaky guard locks

## GitHub quota

Read CI only through GraphQL `gh pr checks` or `gh pr view`.
Limit each polling reader to at most once every 5 minutes per PR.
Run one CI reader at a time during babysit, including Better Review reads and `watch-checks.sh`.
One-shot completion-gate reads in `skills/ship/SKILL.md` are exempt from this polling cadence.
Never use `gh run watch`, a check-runs loop, job polling, or repeated status comments.
Read one failed log once per failure with `gh run view <run-id> --log-failed`.
Read a merge queue from its own `/mq/queue` endpoint where the repository has one.

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
