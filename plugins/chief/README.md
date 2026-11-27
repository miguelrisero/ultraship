# chief

Coordinate multi-lane engineering work from the main session. Chief plans, dispatches one `ship:driver` per lane, and keeps a persistent board.
Chief reports on transitions and deadlines. Chief tracks each ticket until the change passes production verification.

```text
/chief:run <task>
/chief:run review <scope>
```

Chief runs at the session model and needs the `ship` plugin.
Upgrade Chief to `1.8.10` and Ship to `1.15.59` together before using these routes.
Start a fresh session with both plugins loaded.

| Work | Agent |
|---|---|
| Planning | `ship:planner--opus` |
| Important planning, including P0 | `ship:planner--fable52` |
| Code | `ship:writer--sol` |
| A lane's ship tail | `ship:driver` (`claude-opus-5-5`), running `/ship:ship light`; `ship:driver--sol` at low Claude quota only |
| Research | `ship:researcher--luna` |
| Billing and authorization verification | `ship:verifier--opus` |

- Lanes: no cap in the Green and Amber quota tiers; the CoC emergency limits apply in Red and Critical; when cap risk is flagged, the recovery rules apply ([`skills/run/SKILL.md`](skills/run/SKILL.md)).
- Board and recovery: [`skills/run/references/state.md`](skills/run/references/state.md).
- Dispatch check and brief template: [`skills/run/references/dispatch.md`](skills/run/references/dispatch.md).
- Landing and live verification: [`skills/run/references/landing.md`](skills/run/references/landing.md).

## Worktree teardown

`skills/run/scripts/lane-teardown.sh` removes a merged lane worktree only when its head is reachable from the remote. Test it with a workspace-local `TMPDIR`:

```bash
TMPDIR="$PWD/.scratch" bash plugins/chief/skills/run/scripts/lane-teardown.test.sh
```
