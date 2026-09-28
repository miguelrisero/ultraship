# chief

Coordinate multi-lane engineering work from the main session. Chief plans, dispatches one `ship:driver` per lane, keeps a persistent board, and closes lanes at verified pull requests.

```text
/chief:run <task>
/chief:run review <scope>
```

Chief runs at the session model and needs the `ship` plugin.

| Work | Agent |
|---|---|
| Important planning | `ship:planner--sol` |
| Code | `ship:writer--opus` |
| A lane's ship tail | `ship:driver`, running `/ship:ship light` |
| Research | `ship:researcher--flash` |
| Billing and authorization verification | `ship:verifier--fable` |

- Lanes: at most three active, or six for explicitly selected cheap work.
- Board and recovery: [`skills/run/references/state.md`](skills/run/references/state.md).
- Dispatch check and brief template: [`skills/run/references/dispatch.md`](skills/run/references/dispatch.md).
- Landing and live verification: [`skills/run/references/landing.md`](skills/run/references/landing.md).

## Worktree teardown

`skills/run/scripts/lane-teardown.sh` removes a merged lane worktree only when its head is reachable from the remote. Test it with a workspace-local `TMPDIR`:

```bash
TMPDIR="$PWD/.scratch" bash plugins/chief/skills/run/scripts/lane-teardown.test.sh
```
