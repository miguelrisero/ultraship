# Landing and live verification

## Ready and merge authority

A ready lane meets the shipping gate on its current head: pushed commits, required CI, completed independent reviews, addressed comments, and actual end-to-end evidence. Verify these against GitHub and the diff. Treat missing evidence as an open gate.

Default to a ready-for-review handoff. Merge only within explicit task or durable repository authority. Required review approval remains mandatory; an admin override needs a specific user instruction. Keep schema, API contracts, migrations, destructive operations, security, billing, authorization, and repository policy invariants under human review. Keep such lanes draft-only until the chief's independent review passes.

Billing and authorization require an independent adversarial verification lane, separate from the builder's panels. Use `ship:verifier--fable` with replay/idempotency, tenant isolation, and authorization cases. Supply authorized test boundaries. Apply the same product guards and permission limits to every reviewer.

Before landing, compare every changed bound, validator, fixture, and golden with the base branch. A green test encoding a relaxed policy cannot prove policy compliance. Run a negative control for merge-critical guards in an isolated environment, restore the source, and confirm the passing case. A checker that finds none of its expected patterns reports an error. A pattern-based drift instrument also needs a known-detecting negative control and a known-clean positive control, tuned to avoid false matches; preserve that evidence. Missing grep matches do not prove absent tests; use an isolated mutation check when practical, then restore and confirm green.

## Concurrent lanes

Check remote main against the board's last-seen SHA at actionable checkpoints. For each observed foreign merge, record SHA, URL, attribution, and whether main CI stayed green after that merge; unknown is not green. Notify overlapping or dependent lanes. Merge main into already-pushed lane branches and rerun affected evidence. Preserve published history unless the user explicitly authorizes a rewrite.

Use the repository's serial merge queue when it validates the speculative merged result. Otherwise test the combined result after integrating current main. When a migration lands, notify other migration lanes immediately and chain their migration parent onto the new head. Preserve a single migration head.

A merge-queue infrastructure change needs a real base-move retry test, including the identity that triggers the retry. Coordinate authorized deploys to avoid unnecessary restart churn.

## Dark releases

Use independent default-off flags when the approved delivery mode is dark. Prove the disabled behavior and canonical identity equal the base behavior. Prove each enabled flag changes its intended result. A disabled feature contributes no extra canonical/digest fields.

Record the activation action, owner, and verification criteria. Report the release as dark until activation evidence exists.

## Post-merge completion

Execute lane teardown at the verified merged transition. Preserve any `KEPT` disposition on the board. Perform deployment verification through the PR and deployed artifact, retaining the checkout when a documented test needs it.

Use only authorized production operations. A missing deployment requires diagnosis; triggering one needs applicable deployment authority. Never publish a message, alter a live flag, or replay a payment merely to complete a checklist.

| Stage | Evidence |
|---|---|
| Deployed | The correct deployment triggers and reaches live on the intended version. |
| Verified | The artifact, migration, endpoint, and health checks demonstrate that version is present. |
| Tested | The actual changed behavior runs successfully through the deepest safe supported path. |
| Converted | For a recurring failure, eligible events and successful outcomes demonstrate the fix's effect. |

Define conversion eligibility, success, and data source before landing. Zero eligible events means unproven; eligible events with zero conversions mean failed verification. A decline path needs an observable reason.

Reproduce the specific failure predicate against the fixed head and record both versions. Use safe isolated replay; use a fixture or fresh equivalent event when replay creates side effects. Inspect failures and unexpected outcomes during verification. Record a genuinely unavailable stage with its cause and next action.

Close a deployable lane as `live-verified` only when its applicable stages pass. Close an approved dark release as `dark` with an activation runbook. A `ready-for-review` handoff retains its worktree and direct PR URL.
