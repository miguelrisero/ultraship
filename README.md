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
| Chief | session model (`claude-opus-5-5`) | — | — |
| Driver | `claude-opus-5-5` | xhigh | `gpt-6.1-sol` (high), at low Claude quota only |

Sonnet fallbacks run `claude-sonnet-5-5` at effort high. Opus never runs at effort max. Sol runs at effort high. The full roster, with panels, is in [`plugins/ship/skills/ship/references/roster.md`](plugins/ship/skills/ship/references/roster.md).

## Panels

| Panel | Seats | Use |
|---|---|---|
| `light` | Luna, Astra, Sol | Cheap checks |
| `design` | Astra, Opus | Design and architecture |
| `high` | Sol | Plan refutation and branch review |
| `final` | Sol, Opus, Kimi | Final review before push |

## Rules the plugins enforce

The mutation-command brief boundary ships in ship `1.4.8` and chief `1.3.7`.
Dispatch briefs keep mutation-check, anchor-check, and selector execution commands in the admitted battery STATIC part at the frozen head.

- Every review runs at a frozen SHA, and every result gets a ledger row.
- Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; commit grants permit local base-branch merges into their own lane branch.
- Writers follow the brief's verification rule. When the brief bans tests, writers run no test runner and never bypass Git hooks.
- Agents keep their pinned model. A hook denies per-call overrides.
- Researchers get 40 discovery calls per assignment.
- Nobody relaxes a limit, validator, fixture, or golden on main to make a check pass. An owner-requested product-limit change is a feature, including limits on main. The writer implements that exact limit and tests acceptance at the limit and refusal one unit above it (one byte for byte limits).
- Every unrequested bound retains the stop-and-report and consumer-side rule, subject to the branch-only and same-guarantee test-edit exceptions. Unrelated safety, security, resource, budget, and timeout bounds and other guarantees keep their protection. Review, CI, and applicable consent requirements apply.
- A bound that exists only on the PR branch is the lane's design choice and needs no owner question. A test, fixture, census or register edit needs one council round that confirms the same guarantee.
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
