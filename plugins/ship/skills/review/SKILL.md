---
name: review
description: Review a diff, PR, branch, or path for verified, actionable bugs, or run the simplify pass with four Opus lenses. Use for an explicit review request or the ship pipeline review steps.
argument-hint: "[simplify] [--fix] [<PR|branch|path>]"
allowed-tools: Read, Grep, Glob, LSP, Agent, SendMessage, Bash(git:*), Bash(gh:*), ReportFindings
---

# Review

Return verified, actionable findings for the exact target at a frozen SHA. Default to read-only review.

## Modes

- Default: correctness review over every lens in [scope and coverage](references/review.md).
- `simplify`: behavior-preserving cleanup only. Run four `ship:reviewer--opus` seats, one per lens: reuse, simplification, efficiency, altitude.
- `--fix`: after the report, apply validated findings locally. It grants no commit, push, merge, or production permission.

## Boundaries

- If the arguments contain `ultra`, stop before any dispatch. Tell the user to type `/code-review ultra [target]` themselves.
- Cloud review needs the user's explicit invocation. Never start or substitute it automatically.
- The invoking session stays the coordinator.

## Scope and evidence

The coordinator resolves Git evidence and supplies it to read-only agents.
Read [scope and coverage](references/review.md) before dispatch.

1. Resolve the requested PR, branch, or path, or the current branch plus working tree when no target exists.
2. Capture the base SHA, reviewed head SHA, working-tree diff, scoped paths, and applicable instructions.
3. Include intent from commits and the PR body, CI configuration, and relevant history or prior feedback.
4. Check command success and `git diff --stat` against the intended scope.

Exclude generated and vendored content. A failed scope command is a blocked review; an empty scope permits an empty findings array.
For a remote target, supply file content from its reviewed SHA. Never verify remote hunks against unrelated local files.
Record a scoped content fingerprint alongside HEAD, including staged, unstaged, and relevant untracked content.
HEAD alone cannot identify uncommitted work.

## Dispatch

- For broad discovery, use `ship:researcher--flash`.
- Split the diff into bounded slices. Give each slice to a `ship:reviewer--opus` seat with the scope, SHA, evidence, reference path, and read-only boundary. Cover every applicable lens; combine related lenses.
- Leave the Agent `model` field unset. On an unavailable seat, use the fallback chain in `${CLAUDE_PLUGIN_ROOT}/skills/ship/references/roster.md`.
- Send all candidates, with their evidence, to one `ship:reviewer--sol-xhigh` verification pass. It returns `CONFIRMED`, `PLAUSIBLE`, or `REFUTED` for each, per the verification rules in the reference.
- Record requested agents, substitutions, and unavailable seats.

Consolidate duplicate mechanisms. Before reporting, confirm that the reviewed SHA and diff fingerprint still match. Refresh affected evidence when they differ.

## Findings contract

Call `ReportFindings` with `level: "xhigh"` and at most 15 findings, ranked by severity; correctness outranks cleanup.
Each finding contains:

- `file`: repository-relative path
- `line`: current, 1-indexed defect location
- `summary`: the concrete claim
- `short_summary`: at most 60 characters, claim only
- `failure_scenario`: trigger, consequence, and supporting evidence
- `category`: a short kebab-case lens, such as `correctness`, `reuse`, or `conventions`
- `verdict`: `CONFIRMED` or `PLAUSIBLE`

`PLAUSIBLE` requires a verified mechanism and an explicit uncertain trigger. Include what would confirm that trigger.
Exclude `REFUTED` candidates. Anchor removed behavior to its replacement or the actual location needing the guard.
Explain how an unchanged line or caller enters scope. Cite the exact rule for conventions and direct URLs for referenced PRs.

Discover `ReportFindings` if deferred. If unavailable, state the reporting blocker; never claim the tool accepted a report.
The tool call is the findings report. Do not duplicate findings in chat or publish a review artifact.
Report scope, coverage, or routing blockers briefly outside findings; a missing reviewer is never a defect in the code.

## Fix mode

After the first `ReportFindings` call, apply only findings validated against the current code.
Preserve unrelated work. Run relevant tests and independently verify the affected scope again without extra reporting calls.
Call `ReportFindings` once more with the same finding identities and each `outcome`: `fixed`, `skipped`, or `no_change_needed`.
Mark `fixed` only after evidence supports the fix. Report failed or unavailable tests as a remaining blocker.
A plain review ends after its single findings call.
