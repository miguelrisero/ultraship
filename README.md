# ultraship

How I ship code with Claude Code: a model-pinned review pipeline (`ship`) and a multi-lane coordinator (`chief`).

## Install

```text
/plugin marketplace add miguelrisero/ultraship
/plugin install ship@ultraship
/plugin install chief@ultraship
```

Then set up the tools the agents use:

1. [Better Shunt](docs/setup-shunt.md): a local gateway that routes GPT and Kimi model IDs.
2. [fff](docs/setup-fff.md): an indexed file and content search MCP server.
3. [BetterCoding](docs/setup-bettercoding.md): isolated workspaces for agent sessions. Optional.

## The flow

```text
/chief:run <task>
  └─ plan (ship:planner--sol) → freeze lanes → panel
  └─ per lane: ship:driver runs /ship:ship light
       ├─ ship:writer--sol writes each slice
       ├─ ship:reviewer--sol reviews each slice
       ├─ /ship:review simplify + /ship:review (Opus)
       ├─ one fix batch, one fix read
       ├─ push, PR, /ship:babysit (CI + Better Review)
       └─ completion gate + ledger run-end
  └─ verify, land, tear down worktrees
```

Use `/ship:ship <task>` alone for one task. Full mode adds a plan, a high panel, finding selection, a final panel, and a closing pass.

## Models

| Role | Model | Effort | Fallback |
|---|---|---|---|
| Planner | `gpt-6.1-sol` | high | `claude-opus-5-5` (xhigh), `claude-sonnet-5-5` |
| Writer | `gpt-6.1-sol` | high | `claude-sonnet-5-5` (high) |
| Slice review, selection, fix read, high and final panels, closing pass | `gpt-6.1-sol` | high | `claude-opus-5-5` (xhigh), `claude-sonnet-5-5` |
| Deep review, simplify | `claude-opus-5-5` | xhigh | `claude-sonnet-5-5` |
| Required panel seat, billing and authorization verifier | `claude-opus-5-5` | xhigh | `gpt-6-astra` (xhigh) |
| Babysit triage | `gpt-6.1-sol` | high | `gpt-6.1-sol` (reviewer), `claude-sonnet-5-5` (reviewer) |
| Research | `gpt-6-luna` | medium | `claude-sonnet-5-5` |
| Chief, driver | session model | — | — |

Sonnet fallbacks run `claude-sonnet-5-5` at effort high. Opus never runs at effort max. Sol runs at effort high. The full roster, with panels, is in [`plugins/ship/skills/ship/references/roster.md`](plugins/ship/skills/ship/references/roster.md).

## Panels

| Panel | Seats | Use |
|---|---|---|
| `light` | Luna, Astra, Sol | Cheap checks |
| `design` | Astra, Opus | Design and architecture |
| `high` | Sol | Plan refutation and branch review |
| `final` | Sol, Opus, Kimi | Final review before push |

## Rules the plugins enforce

- Every review runs at a frozen SHA, and every result gets a ledger row.
- Writers do not push, merge, deploy, or publish. A hook denies these commands.
- Writers follow the brief's verification rule. When the brief bans tests, writers run no test runner and never bypass Git hooks.
- Agents keep their pinned model. A hook denies per-call overrides.
- Researchers get 40 discovery calls per assignment.
- Nobody relaxes a limit, validator, fixture, or golden to make a check pass.
- Done means required CI is green on the head, zero review threads are open, and the ledger has no gaps.

## Develop

```bash
python3 scripts/check-plugins.py
TMPDIR="$PWD/.scratch" PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p test_model_routing.py -v
TMPDIR="$PWD/.scratch" python3 plugins/ship/hooks/ultraship_test.py
TMPDIR="$PWD/.scratch" bash plugins/chief/skills/run/scripts/lane-teardown.test.sh
```

Bump the plugin version in `plugin.json` and `.claude-plugin/marketplace.json` for every change inside `plugins/<name>/`. Claude Code caches plugins by version.

## License

MIT
