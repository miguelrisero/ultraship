# Agent roster

Dispatch the scoped name. Leave the Agent `model` field unset. On an unavailable agent, dispatch the next entry in the chain and record it in the ledger note. A seat with no fallback stays missing, and its panel is incomplete.

| Agent | Model | Effort | Use | Fallback chain |
|---|---|---|---|---|
| `ship:planner--sol` | `gpt-6-sol` | xhigh | Plans, premises | `planner--opus`, `planner--sonnet` |
| `ship:writer--sol` | `gpt-6-sol` | max | All code | `writer--sonnet`, `writer--glm` |
| `ship:writer--sonnet` | `claude-sonnet-5-5` | high | Code, first fallback | `writer--glm` |
| `ship:writer--glm` | `cf-glm-5.3` | high | Code, last fallback | none |
| `ship:driver` | session model | — | Lane ship tail | — |
| `ship:reviewer--sol-xhigh` | `gpt-6-sol` | xhigh | Slice review, selection, fix read | `reviewer--opus`, `reviewer--sonnet` |
| `ship:reviewer--sol-max` | `gpt-6-sol` | max | High panel | `reviewer--sol56-max`, `reviewer--opus`, `reviewer--sonnet` |
| `ship:reviewer--sol56-max` | `gpt-5.6-sol` | max | Final panel, closing pass, babysit breaker | `reviewer--sol-max`, `reviewer--opus`, `reviewer--sonnet` |
| `ship:reviewer--opus` | `claude-opus-5-5` | xhigh | Deep review, simplify | `reviewer--sonnet` |
| `ship:reviewer--fable` | `claude-fable-5-1` | xhigh | Design and final panels (required seat) | `reviewer--astra` |
| `ship:reviewer--astra` | `gpt-6-astra` | xhigh | Design panel | `reviewer--sol-xhigh`, `reviewer--sonnet` |
| `ship:reviewer--glm` | `cf-glm-5.3` | high | Panels | `reviewer--sonnet` |
| `ship:reviewer--deepseek` | `cf-deepseek-v4-pro` | high | Panels | `reviewer--sonnet` |
| `ship:reviewer--kimi` | `kimi-k3` | high | Final panel (trial until 2026-10-09) | none |
| `ship:reviewer--deepseek-flash` | `cf-deepseek-v4-flash` | medium | Light panel | `reviewer--sonnet` |
| `ship:reviewer--glm-flash` | `cf-glm-5.3-flash` | medium | Light panel | `reviewer--sonnet` |
| `ship:reviewer--luna` | `gpt-6-luna` | medium | Light panel | `reviewer--sonnet` |
| `ship:triage--glm` | `cf-glm-5.3` | high | Babysit triage | `reviewer--sol-xhigh`, `reviewer--sonnet` |
| `ship:researcher--flash` | `cf-deepseek-v4-flash` | medium | Research (40-call budget) | `researcher--glm-flash`, `researcher--luna`, `researcher--sonnet` |
| `ship:verifier--fable` | `claude-fable-5-1` | xhigh | Billing and authorization | `verifier--astra` |
| `ship:verifier--astra` | `gpt-6-astra` | xhigh | Billing and authorization, fallback | none |

`claude-sonnet-5-5` at effort high is the last entry of every planner, reviewer, and researcher chain that has one. The writer chain ends at `writer--glm`. Opus agents never run at effort max.

## Tools

- Read-only roles: `Read, Grep, Glob, LSP, mcp__fff__find_files, mcp__fff__grep, mcp__fff__multi_grep, WebFetch, WebSearch`.
- Writers: every tool except `Agent`. A hook denies push, merge, deploy, publish, and harness-config edits.
- Driver: every tool.

## Search order

1. LSP for definitions and references.
2. `mcp__fff__multi_grep` to batch related patterns in one call.
3. `mcp__fff__find_files` and `mcp__fff__grep`.
4. Grep and Glob when fff is not loaded.
