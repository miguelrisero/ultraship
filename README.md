# ultraship

How I ship code with Claude Code: a model-pinned review pipeline (`ship`) and a multi-lane coordinator (`chief`).

## Install

```text
/plugin marketplace add miguelrisero/ultraship
/plugin install ship@ultraship
/plugin install chief@ultraship
```

Then set up the tools the agents use:

1. [Better Shunt](docs/setup-shunt.md): a local gateway that routes GPT, GLM, DeepSeek, and Kimi model IDs.
2. [fff](docs/setup-fff.md): an indexed file and content search MCP server.
3. [BetterCoding](docs/setup-bettercoding.md): isolated workspaces for agent sessions. Optional.

## The flow

```text
/chief:run <task>
  └─ plan (ship:planner--sol) → freeze lanes → panel
  └─ per lane: ship:driver runs /ship:ship light
       ├─ ship:writer--sol writes each slice
       ├─ ship:reviewer--sol-xhigh reviews each slice
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
| Planner | `gpt-6-sol` | xhigh | `claude-opus-5-5` (xhigh), `claude-sonnet-5` |
| Writer | `gpt-6-sol` | max | `claude-sonnet-5-5` (high), `cf-glm-5.3` (high) |
| Slice review, selection, fix read | `gpt-6-sol` | xhigh | `claude-opus-5-5` (xhigh), `claude-sonnet-5` |
| Closing pass, final panel lead | `gpt-5.6-sol` | max | `gpt-6-sol`, `claude-opus-5-5` (xhigh), `claude-sonnet-5` |
| Deep review, simplify | `claude-opus-5-5` | xhigh | `claude-sonnet-5` |
| Required panel seat, billing and authorization verifier | `claude-fable-5-1` | xhigh | `gpt-6-astra` (xhigh) |
| Babysit triage | `cf-glm-5.3` | high | `gpt-6-sol`, `claude-sonnet-5` |
| Research | `cf-deepseek-v4-flash` | medium | `cf-glm-5.3-flash`, `gpt-6-luna`, `claude-sonnet-5` |
| Chief, driver | session model | — | — |

`claude-sonnet-5` fallbacks run at effort high. Opus never runs at effort max. The full roster, with panels, is in [`plugins/ship/skills/ship/references/roster.md`](plugins/ship/skills/ship/references/roster.md).

## Panels

| Panel | Seats | Use |
|---|---|---|
| `light` | DeepSeek Flash, GLM Flash, Luna | Cheap checks |
| `design` | Astra, Fable, GLM, DeepSeek Pro | Design and architecture |
| `high` | Sol max, GLM, DeepSeek Pro | Plan refutation and branch review |
| `final` | Sol 5.6 max, Fable, GLM, DeepSeek Pro, Kimi | Final review before push |

## Rules the plugins enforce

- Every review runs at a frozen SHA, and every result gets a ledger row.
- Writers do not push, merge, deploy, or publish. A hook denies these commands.
- Agents keep their pinned model. A hook denies per-call overrides.
- Researchers get 40 discovery calls per assignment.
- Nobody relaxes a limit, validator, fixture, or golden to make a check pass.
- Done means required CI is green on the head, zero review threads are open, and the ledger has no gaps.

## Develop

```bash
python3 scripts/check-plugins.py
TMPDIR="$PWD/.scratch" python3 plugins/ship/hooks/ultraship_test.py
TMPDIR="$PWD/.scratch" bash plugins/chief/skills/run/scripts/lane-teardown.test.sh
```

Bump the plugin version in `plugin.json` and `.claude-plugin/marketplace.json` for every change inside `plugins/<name>/`. Claude Code caches plugins by version.

## License

MIT
