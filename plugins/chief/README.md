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
| Code | `ship:writer--sol` |
| A lane's ship tail | `ship:driver` (`claude-opus-5-5`), running `/ship:ship light`; `ship:driver--sol` at low Claude quota only |
| Research | `ship:researcher--luna` |
| Billing and authorization verification | `ship:verifier--fable` |

- Lanes: no cap; when cap risk is flagged, the recovery rules apply ([`skills/run/SKILL.md`](skills/run/SKILL.md)).
- Board and recovery: [`skills/run/references/state.md`](skills/run/references/state.md).
- Dispatch check and brief template: [`skills/run/references/dispatch.md`](skills/run/references/dispatch.md).
- Landing and live verification: [`skills/run/references/landing.md`](skills/run/references/landing.md).

## Worktree teardown

`skills/run/scripts/lane-teardown.sh` removes a merged lane worktree only when its head is reachable from the remote. Test it with a workspace-local `TMPDIR`:

```bash
TMPDIR="$PWD/.scratch" bash plugins/chief/skills/run/scripts/lane-teardown.test.sh
```
