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

The plugin defines 18 agents. [`skills/ship/references/roster.md`](skills/ship/references/roster.md) lists each model, effort, use, and fallback chain.

- Writers: `gpt-6.1-sol` at high effort, with `claude-sonnet-5-5` (high) as the fallback.
- Reviewers: `gpt-6.1-sol`, `claude-opus-5-5`, `gpt-6-astra`, `gpt-6-luna`, and `kimi-k3`.
- Read-only agents get read, LSP, fff, and web tools only.

Non-Claude models need a gateway. See [`docs/setup-shunt.md`](../../docs/setup-shunt.md).

## Hooks

| Hook | Event | Effect |
|---|---|---|
| Model guard | PreToolUse `Agent` | Denies a `model` override on a `ship:*` agent |
| Role guard | PreToolUse `Bash`, `Edit`, `Write` | Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; they may locally merge the base branch into their lane branch. The hook also denies harness-config edits. |
| Research budget | PreToolUse discovery tools | Denies the 41st discovery call of a researcher |
| Ledger owed | SubagentStop, Stop | Retains pending evidence and blocks until each reviewer result has a ledger row |
| Compact handoff | SessionStart `compact` | Prints the re-read instruction and the open ledger run |

Hook state lives in `${XDG_STATE_HOME:-~/.local/state}/ultraship`.

A checkout with its Git directory inside the checkout uses `<common-git-dir>/ship/ledger/<branch>.tsv`. An existing parent `.scratch` identifies the workspace for a direct-child linked checkout. A common Git directory inside that workspace also uses the common-directory default. An external common Git directory selects `<workspace>/.scratch/ship-ledgers/<canonical-checkout-sha256>/<branch>.tsv`. The resolver canonicalizes roots and rejects symlink escapes. Ambiguous layouts require an absolute `SHIP_LEDGER_DIR`.

The first local resolution imports the same-branch legacy TSV byte-for-byte, including its open run and all evidence. A sidecar `.import.json` records the canonical legacy path and SHA256. Cooperating first users share an exclusive local import lock. Readers and writers then use the local ledger exclusively. The legacy ledger remains frozen history. Import errors preserve the source and require resolution.

The sole driver must hold run custody and retire old legacy writers before import. Old writers can race the snapshot read. Local locking covers cooperating importers only. Import requires legacy read permission and local directory write permission. It grants zero legacy write permission. CLI commands, completion checks, Stop, and compact share the resolver. Stop retains exact pending evidence through access failures, missing runs, and failed appends. Notifications bind to the ledger path and run-start identity when ledger access succeeds. Stop accepts accounting from that run after successful closure. Persistent hook-state receipts consume each accounting row once across Stop cycles and sessions. Each notification has a fresh ID, including repeat notifications from the same agent. Receipt publication precedes pending-evidence clearing. Legacy notifications require one unambiguous time-containing run; ambiguous evidence stays pending.

Set `SHIP_LEDGER_DIR` to an absolute permitted directory for an explicit home, for example `export SHIP_LEDGER_DIR="$PWD/../.scratch/ship-ledgers"`. Export it for ledger commands and hooks. The directory directly contains the branch TSV; branch filenames replace `/` with `__`. Empty and relative values raise an error. The override selects its home without legacy import.

## Test

```bash
TMPDIR="$PWD/.scratch" python3 plugins/ship/hooks/ultraship_test.py
```
