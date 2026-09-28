# Panel seat report

Return one report for the requested model, covering all selected lenses.
Keep findings specific and proportional to the evidence.
Emit a `### Lens progress — <lens>` text block as you complete each lens, before the final report.
A stopped seat then leaves its completed findings in the transcript.

## Verdict: APPROVE | CAUTION | BLOCK

Give a one-sentence reason tied to the challenge.

## Findings

Order findings by priority.
For each finding, include the applicable lenses, evidence, impact, and an actionable recommendation.

| Priority | Meaning |
|----------|---------|
| P0 | Blocker: failure, data loss, or serious harm requires resolution before proceeding. |
| P1 | Critical: significant consequences require prompt resolution. |
| P2 | Important: a meaningful improvement prevents future problems. |
| P3 | Advisory: low-urgency guidance or an optional improvement. |

Use `[verified: <path:line>]` for source evidence you opened.
Cite external evidence with its URL and relevant date.
Use `[provided: <source>]` for evidence supplied by the coordinator.
Use `[inferred: unverified]` for a hypothesis or an unchecked claim.
Distinguish actual defects from assumptions and design preferences.

## Lens coverage

Give each selected lens its findings or `No concerns identified`.
Identify any lens you could not assess and the missing evidence.

## Risk assessment

Score only dimensions relevant to this challenge.
Use a table with dimension, score, and supporting concern.
Scores: 1 minimal, 2 minor, 3 moderate, 4 significant, 5 critical.

## Assumptions and blind spots

Identify assumptions that could change the verdict.
List missing evidence, unassessed scope, and useful follow-up checks.
