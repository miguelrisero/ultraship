# ship

Ship one task to a ready-for-review pull request. Every review runs at a frozen SHA, every result goes into a ledger, and the run ends only when the ledger has no gaps.

```text
/ship:ship <task>            full pipeline
/ship:ship light [<task>]    short pipeline for chief lanes
/ship:ship goal <task>       print a /goal block
/ship:panel [tier] <subject> cross-model panel
/ship:review [simplify] [<target>]
/ship:babysit [<PR>]
```

## Pipeline

1. Guard the branch and open the ledger run.
2. Plan slices and premises with falsifiers.
3. Write each slice, test it, and review it.
4. High panel on the frozen branch.
5. Simplify and deep review, in parallel.
6. Select findings.
7. One fix batch and one fix read.
8. Final panel.
9. Merge main, run full checks, push, open the PR.
10. Babysit CI and Better Review to green.
11. Closing pass over the commits since the last review.
12. Completion gate.
13. Handoff.

Light mode runs steps 1, 3, 5, 7, 9, 10, and 12. Detail: [`skills/ship/references/pipeline.md`](skills/ship/references/pipeline.md).

## Agents

The plugin defines 26 model-pinned agents. [`skills/ship/references/roster.md`](skills/ship/references/roster.md) lists each model, effort, use, and fallback chain.

- Writers: `claude-opus-5-5` at max effort, with `gpt-6-luna` and `claude-sonnet-5` as fallbacks.
- Reviewers: `gpt-6-sol`, `gpt-5.6-sol`, `claude-opus-5-5`, `claude-fable-5-1`, `gpt-6-astra`, `cf-glm-5.3`, `cf-deepseek-v4-pro`, and `kimi-k3`.
- Read-only agents get read, LSP, fff, and web tools only.

Non-Claude models need a gateway. See [`docs/setup-shunt.md`](../../docs/setup-shunt.md).

## Hooks

| Hook | Event | Effect |
|---|---|---|
| Model guard | PreToolUse `Agent` | Denies a `model` override on a `ship:*` agent |
| Role guard | PreToolUse `Bash`, `Edit`, `Write` | Denies push, merge, deploy, publish, and harness-config edits for writers |
| Research budget | PreToolUse discovery tools | Denies the 41st discovery call of a researcher |
| Ledger owed | SubagentStop, Stop | Blocks the stop once when a reviewer result has no ledger row |
| Compact handoff | SessionStart `compact` | Prints the re-read instruction and the open ledger run |

Hook state lives in `${XDG_STATE_HOME:-~/.local/state}/ultraship`. The ledger lives in `$(git rev-parse --git-common-dir)/ship/ledger/<branch>.tsv`.

## Test

```bash
TMPDIR="$PWD/.scratch" python3 plugins/ship/hooks/ultraship_test.py
```
