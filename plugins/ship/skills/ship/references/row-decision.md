# Version-only row decision preflight

Use schema version 1 for a CoC-approved native re-anchor that changes only `old`.
Require the old line, its replacement, and the unchanged mutant to each use bare YAML `version: X.Y.Z`.
Use the existing route for other cases.
Use the [lane-owned row route](../SKILL.md#lane-owned-row-route) for authority, evidence, execution and review.

1. Verify the existing authorized draft and the failed anchor CI for the exact head and row.
2. Fill the fields in the [executable schema](../scripts/row-decision.py).
3. Freeze the decision as a regular `0444` JSON file in the CoC workspace's `.scratch/coc/rows/` directory.
4. Record its absolute path and SHA-256.
5. Verify the CoC workspace root independently of the decision file.
6. Run the preflight from the trusted, loaded Ship plugin before sending the file.

```text
python3 -I <installed-ship>/skills/ship/scripts/row-decision.py <absolute-decision.json> <sha256> --coc-workspace <absolute-coc-workspace>
```

List the path and digest in the brief. Include the preflight result, which contains no row text.
Use the same schema to check for missing fields when the writer receives the file.
Keep the row pending if preflight fails.

## Required fields

| Fields | Meaning |
| --- | --- |
| `schema_version`, `authority` | `1` and `coc-standing-grant`. The label claims the authority; verify the grant separately. |
| `pr_url`, `lane`, `writer`, `checkout`, `branch` | The canonical draft URL, lane, writer role, absolute checkout path and feature branch. Verify the applying writer separately. |
| `base`, `head`, `head_tree` | Full Git IDs for the row comparison base, pre-edit draft head and its tree. |
| `rows_file`, `row_id`, `base_row_extent`, `head_row_extent` | The repository-relative row path, stored ID and inclusive one-based line ranges. |
| `base_rows_blob`, `head_rows_blob` | Full Git blob IDs for the row file at the base and pre-edit head. |
| `subject`, `base_subject_blob`, `head_subject_blob` | The subject path and its full blob IDs at the same commits. |
| `test`, `claim` | The exact designated test and unchanged claim. |
| `old_before`, `old_after`, `new_unchanged` | The exact three version lines. Only `old` changes; keep every other row field intact. |
| `diagnostic` | The `run_id`, `job_id`, `attempt`, draft `head`, `tested_commit`, `tested_tree`, `row_id`, `observed` count and `expected` count from failed anchor CI. |

The diagnostic must bind the same head, tree and row. The observed count must differ from the expected count.
Verify the tested commit and its tree against the original CI evidence.

## Optional correction record

For a corrected decision, provide `correction` with `prior_path`, `prior_sha256`, `refusal`, `refusal_source` and `defect`.
Use the defective decision's absolute path, its SHA-256, the verbatim refusal, its source and the defect.
The preflight checks the record's fields and the new file's identity. The source identifies who recorded the refusal.
The preflight neither verifies the prior record nor clears the refusal.

Apply the [loaded refusal rules](owner-decisions.md#loaded-instructions-and-refusals) separately. They control who can retry.
A new writer, a new file or a passing preflight alone cannot authorize a retry.

## Verification after preflight

The preflight reads only the named decision JSON. It checks its digest, required bindings and internal consistency.
It cannot verify the live draft, Git objects, CI evidence, exact row text, actor identity or applicable authority.
Verify authority, actor, scope, draft, Git and CI evidence before any protected access.
Compare the exact row text during the admitted read and before the edit.
Keep the native Edit restrictions, the identical mutant, the exact-head anchor proof, the independent not-weaker review and the push grant.
