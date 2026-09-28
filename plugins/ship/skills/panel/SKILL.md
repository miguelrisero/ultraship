---
name: panel
description: Run an independent cross-model review panel (light, design, high, or final) on a frozen subject such as a plan, branch diff, or decision, and return an evidence-based verdict. Use for an explicit panel or council request, or a ship pipeline panel step.
argument-hint: "[light|design|high|final] [<type>|custom <p1,p2,...>] <subject> | list [<type>]"
allowed-tools: Read, Grep, Glob, LSP, WebFetch, WebSearch, Agent, SendMessage, Bash(git:*), Bash(gh:*)
---

# Panel

Return one verdict from independent model seats that review the same frozen subject. Default tier: `high`.

## Arguments

- `[tier] [<type>] <subject>`: infer the type when absent.
- `[tier] custom <p1,p2,...> <subject>`: use 3 to 6 bundled persona names. Validate them before dispatch.
- `list` or `list <type>`: print the tiers, types, and personas without dispatch.
- An empty or unclear subject: ask one question.

## Dispatch

1. Read `${CLAUDE_SKILL_DIR}/references/panels.md` for the seats and persona lenses.
2. Read the selected `${CLAUDE_SKILL_DIR}/personas/<name>.md` files and `personas/_format.md`.
3. Freeze the subject. For code, record the base SHA, head SHA, and diff. All seats get the same SHA.
4. Build one self-contained brief: subject, type, lenses, constraints, required decision, absolute paths, SHAs, and the diff. Leave out your own conclusions and any other seat's output.
5. Launch one Agent call per seat, together in one message. Use the scoped `ship:reviewer--*` names and leave `model` unset.
6. On an unavailable seat, dispatch the next agent in its fallback chain from `${CLAUDE_PLUGIN_ROOT}/skills/ship/references/roster.md`. Seats with no fallback stay missing.

## Verdict

Read `${CLAUDE_SKILL_DIR}/references/synthesis.md` and return its report contract.

- Count one vote per model family. Two seats from one family count as one vote.
- A failed, empty, or refused seat is missing. A missing required seat makes the verdict `provisional`.
- Never invent a missing response or claim a full panel when a seat is missing.
- A panel gives advice. Implementation, commits, and publication need their own authority.
- In a ship run, the driver appends the verdict to the ledger before it acts on it.
