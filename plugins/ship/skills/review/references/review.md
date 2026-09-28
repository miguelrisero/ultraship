# Scope and coverage

## Resolve the scope

For the default review, fetch the remote trunk when permitted. Resolve it with
`git rev-parse --abbrev-ref origin/HEAD` and use that fully qualified ref.
If unset, `git remote set-head origin --auto` can populate it when permitted.
A feature branch's upstream often points to its own pushed head; local `main` can lag.
Check the base and file list before trusting either.
If the remote trunk is unavailable, probe `@{upstream}`, local `main`, then `HEAD~1`.
Record the chosen base and unavailable evidence. Never guess a successful scope from a failed command.

Default scope combines the committed range and `git diff HEAD`, including staged and unstaged edits.
Inspect untracked files and include relevant source files explicitly; `git diff HEAD` omits them.
An explicit target replaces this default scope:

- PR: use its actual base/head and diff; keep unrelated local edits outside scope
- branch: compare its committed head with the resolved base
- path: restrict the branch and working-tree scope to that path

A default scope is empty only when both committed and working-tree scopes contain no relevant content.
For an explicit target, only that target's content determines emptiness. Never widen scope to create review work.
Exclude lockfiles, build output, minified bundles, snapshots, and vendored dependencies.
Probe failures during resolution permit fallbacks. Failure of the selected scope command stops the review.

Use `gh` for PR targets. `gh pr diff` accepts a number, URL, or branch.
Split `owner/repo#N` into `gh pr diff N --repo owner/repo`.
Use `gh repo view --json nameWithOwner -q .nameWithOwner` for repository identity.
Closed and merged PRs remain reviewable. A failed fetch never means a clean review.

## Coverage lenses

Apply all relevant lenses; these are coverage requirements, not separate mandatory agents.

| Lens | Evidence to inspect |
|---|---|
| Line-by-line correctness | Every hunk and enclosing function; inputs, state, timing, platform, conditions, bounds, nulls, missing awaits, wrong variables, swallowed errors, regex escaping |
| Removed behavior | Deleted guards, defaults, branches, validation, errors, and tests; locate the invariant's remaining enforcement |
| Cross-file contracts | Every changed function's callers and callees; return shapes, preconditions, exceptions, timing, and ordering |
| Language pitfalls | Coercion, falsy zero, closure capture, mutable defaults, nil maps, SQL injection, timezones/DST, and float comparisons |
| Wrappers and proxies | Delegate routing, registry re-entry, recursion, and complete forwarding of methods callers use |
| Reuse | Existing helpers in adjacent and shared modules; cite the exact reusable function |
| Simplification | Derivable state, duplication, nesting, dead code; identify the equivalent simpler form |
| Efficiency | Repeated computation/I/O, avoidable serialization, blocking hot paths, and closures retaining large environments |
| Altitude | Fix location and shared mechanisms; trace sibling callers before adding local special cases |
| Conventions | Applicable user, root, ancestor `CLAUDE.md` and `CLAUDE.local.md`; quote the exact scoped rule and violating line |
| History | Blame and commit history for intentionally added invariants; cite the protecting commit SHA |
| Prior review | Relevant earlier PR feedback repeated by this diff; cite a direct PR URL and the still-present defect |
| Code comments | Nearby comments/docstrings: synchronization, ordering, initialization, units, invariants, and preconditions |

For cleanup findings, give the concrete duplication, maintenance cost, or wasted work and an actionable alternative.
History and code-comment findings take the severity of the broken invariant. Prior feedback takes the defect's severity.
A gap pass checks extraction/movement dropping guards, persistent defaults, nondeterministic hashes,
reduced lock scope, side-effectful predicates, test setup/teardown asymmetry, and changed configuration defaults.

## Coordinator history collection

Check `git rev-parse --is-shallow-repository` before using blame.
If shallow, deepen with `git fetch --unshallow` when permitted; otherwise record unavailable history coverage.
A shallow clone's successful blame command does not establish useful history.

For prior review, map recent file commits to PRs:

```bash
git log -n 20 --format=%H -- <path>
gh api repos/<owner>/<repo>/commits/<sha>/pulls --jq '.[].number'
```

PR search matches prose, not changed file paths. Commit-subject `(#N)` parsing misses merge styles.
Exclude only the current PR number resolved from the target or `gh pr view --json number -q .number`.
Skip individual unpublished SHA failures such as HTTP 422 and continue.
If associations are unavailable, including rebase-merge histories, record the coverage gap.
Read all three feedback locations with pagination:

```bash
gh api --paginate repos/<owner>/<repo>/pulls/<N>/comments
gh api --paginate repos/<owner>/<repo>/issues/<N>/comments
gh api --paginate repos/<owner>/<repo>/pulls/<N>/reviews
```

`gh pr view --comments` omits inline threads. API defaults can truncate results at 30 items.
Missing GitHub access or absent associations contribute no candidates. Never invent a finding for missing evidence.

## Independent verification

Give each verifier the candidate, exact diff and source, intent, CI configuration, applicable instructions, and relevant history.
A verifier returns one evidence-backed state:

- `CONFIRMED`: concrete inputs/state produce the named failure; quote the defect line
- `PLAUSIBLE`: the mechanism is verified; identify the uncertain environmental, configuration, or timing trigger and confirmation needed
- `REFUTED`: source, a guard, history, or an applicable rule disproves the candidate; quote the evidence

Refute unrelated pre-existing issues outside touched or re-exposed behavior.
A conventions candidate must already cite an applicable rule; preference alone supplies no finding.
Unchanged lines in touched functions and callers broken by this diff remain eligible.

The following facts alone never disprove a runtime defect:

- CI also detects it; verify whether the check actually gates this scope
- a commit or PR body describes the behavior as intentional; check its consequences and implementation
- a lint/type suppression disables a diagnostic; inspect the underlying behavior

Prioritize by impact. Preserve real defects even when a separate check detects them.
A candidate needs a real mechanism and concrete consequence; uncertainty cannot supply either.
