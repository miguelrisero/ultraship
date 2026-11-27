# Agent roster

Dispatch the scoped name. Leave the Agent `model` field unset. On an unavailable agent, dispatch the next entry in the chain and record it in the ledger note. If all admitted writer or planner seats are unavailable, retain the task as pending and report the missing seat. A panel with a missing seat and no fallback is incomplete.

Select the plan class before each planning attempt. Within one attempt, stop at the first available seat or at the end of the chain, and never revisit a seat. A rework attempt starts again at the first seat of its class.

Use [reviewer admission for protected row reads](owner-decisions.md#reviewer-admission-record-for-protected-row-reads) to select a seat for a protected row review; the fallback chain does not apply to a protected row review.

| Agent | Model | Effort | Use | Fallback chain |
|---|---|---|---|---|
| `ship:planner--fable52` | `claude-fable-5-2` | xhigh | Important and P0 plans, first seat | `planner--sol`, then `planner--opus` |
| `ship:planner--opus` | `claude-opus-5-5` | xhigh | Plans that are not important or P0, first seat | Normal: `planner--sol`; important and P0: none |
| `ship:planner--sol` | `gpt-6.2-sol` | xhigh | Fallback for normal, important, and P0 plans | Normal: none; important and P0: `planner--opus` |
| `ship:writer--sol` | `gpt-6.2-sol` | xhigh | All code | none |
| `ship:writer--fable52` | `claude-fable-5-2` | high | Code, only when the brief or the owner names Fable 5.2 | `writer--sol` |
| `ship:driver` | `claude-opus-5-5` | xhigh | Lane ship tail | `driver--sol` at low Claude quota only |
| `ship:driver--sol` | `gpt-6.2-sol` | xhigh | Lane ship tail at low Claude quota, with a recorded quota reading | none |
| `ship:reviewer--sol` | `gpt-6.2-sol` | xhigh | Light panel, slice review, selection, fix read, high and final panels, closing pass, babysit breaker | `reviewer--opus`, `reviewer--sonnet` |
| `ship:reviewer--opus` | `claude-opus-5-5` | xhigh | High panel, deep review, simplify | `reviewer--sonnet` |
| `ship:reviewer--opus-panel` | `claude-opus-5-5` | xhigh | Design and final panels (required seat) | `reviewer--astra` |
| `ship:reviewer--fable52` | `claude-fable-5-2` | xhigh | Review or panel seat, only when the brief or the owner names Fable 5.2 | `reviewer--opus-panel` |
| `ship:reviewer--astra` | `gpt-6.2-astra` | xhigh | Design, high and light panels | `reviewer--sol`, `reviewer--sonnet` |
| `ship:reviewer--luna` | `gpt-6-luna` | medium | Design, light and final panels | `reviewer--sonnet` |
| `ship:triage--sol` | `gpt-6.2-sol` | xhigh | Babysit triage | `reviewer--sol`, `reviewer--sonnet` |
| `ship:researcher--luna` | `gpt-6-luna` | medium | Research (40-call budget) | `researcher--sonnet` |
| `ship:verifier--opus` | `claude-opus-5-5` | xhigh | Billing and authorization | `verifier--astra` |
| `ship:verifier--astra` | `gpt-6.2-astra` | xhigh | Billing and authorization, fallback | none |

`claude-sonnet-5-5` at effort high is the last entry in the reviewer and researcher chains that list it. Opus agents never run at effort max. Sol agents run `gpt-6.2-sol` at explicit effort xhigh.

## Tools

- Planners and researchers: `Read, Grep, Glob, LSP, mcp__fff__find_files, mcp__fff__grep, mcp__fff__multi_grep, WebFetch, WebSearch`.
- Reviewers, triage and verifiers: `Read, Grep, Glob, LSP, WebFetch, WebSearch`. These agents use LSP hover and documentSymbol only.
- Writers: every tool except `Agent`. Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; commit grants permit local base-branch merges into their own lane branch. A hook denies harness-config edits.
- Driver: every tool.

## Search order

Reviewers, triage and verifiers skip this order. They use Grep and Glob on an exact canonical absolute path, and Read for files.

Every other role searches in this order.

1. LSP for definitions and references.
2. `mcp__fff__multi_grep` to batch related patterns in one call.
3. `mcp__fff__find_files` and `mcp__fff__grep`.
4. Grep and Glob when fff is not loaded.
