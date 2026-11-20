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

The plugin defines 21 agents. [`skills/ship/references/roster.md`](skills/ship/references/roster.md) lists each model, effort, use, and fallback chain.

- Writers: `gpt-6.2-sol` at xhigh effort, with `claude-sonnet-5-5` (high) as the fallback.
- Reviewers: `gpt-6.2-sol` at xhigh, `claude-opus-5-5`, `gpt-6.2-astra` and `gpt-6-luna`.
- Opt-in Fable 5.2 seats: `writer--fable52` and `reviewer--fable52` run `claude-fable-5-2`. Dispatch them only when the brief or the owner names Fable 5.2.
- Read-only agents get read, LSP, and web tools only. Planners and researchers also get fff tools. Reviewers, triage and verifiers use no MCP (`mcp__`) tools, and their LSP use is hover and documentSymbol only.

Non-Claude models need a gateway. See [`docs/setup-shunt.md`](../../docs/setup-shunt.md).

## Hooks

| Hook | Event | Effect |
|---|---|---|
| Model guard | PreToolUse `Agent` | Denies a `model` override on a `ship:*` agent |
| Role guard | PreToolUse `Bash`, `Edit`, `Write` | Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; commit grants permit local base-branch merges into their own lane branch. The ban covers every path. The hook denies common CLI forms and harness-config edits. |
| Reviewer, triage and verifier boundary | PreToolUse `Read`, `Grep`, `Glob`, `LSP`, `WebFetch`, `mcp__fff__*` | Reviewers, triage and verifiers pass exact canonical absolute paths and scope every search. The hook denies `tests/mutation` paths, `.git` paths, Claude data under `~/.claude` and `CLAUDE_CONFIG_DIR` (except `CLAUDE.md`, `plugins/cache`, and `plugins/marketplaces`), and the `mcp__fff__*` tools and the three `mcp__bettercoding__` Input tools, the only `mcp__` tools the hook sees. A driver-written admission record admits Read or Grep of the exact row files it lists. |
| Review-thread guard | PreToolUse `Bash`, every caller | Requires `thread_reply.py` for review-thread replies and resolves. The helper checks the thread's repository and PR number through GitHub. |
| Row re-anchor gate | PreToolUse `Bash`, every caller | Admits only the exact isolated `row_reanchor.py` command for a writer with a matching driver-written admission record. |
| Research budget | PreToolUse discovery tools | Denies the 41st discovery call of a researcher |
| Ledger owed | SubagentStop, Stop | Retains pending evidence; blocks once per canonical owed state; accounts each result against its agent ID |
| Compact handoff | SessionStart `compact` | Prints the re-read instruction and the open ledger run |

The ship hooks need Claude Code 2.1.295 or later.

The prose hook checks `SendMessage`, `create_input`, and `update_input` text.
Only owner-facing text gets the 25-word sentence limit and the section checks.
The `decision` and `result` CLI modes check owner-facing text. The `peer` mode checks peer text.
Decision Inputs need the five decision sections. Result Inputs can use free-form text.
`Agent` and `Task` prompts get receipt checks only.

Set `SHIP_LINT_OFF` to a comma-separated list of rule names, such as `glued,sentence`.
Use `all` to disable every rule in this list.
Input classification, safety, and receipt checks stay active.

| Rule | Check |
|---|---|
| `glued` | Glued words and compressed shorthand |
| `sentence` | Sentences longer than 25 words in owner-facing text |
| `sections` | Missing sections in decision text |
| `hold` | Repeated standing holds in peer status messages |
| `unicode` | Invalid Unicode in message and Input fields |

The first four rules warn and let the call proceed.
Input HTML requires exactly one `output-kind` marker with the value `decision` or `result`.
Invalid Unicode and classification findings give an exact remedy for a resend.
Keep the action, recipient, and non-prose fields the same on a resend.

The review-thread guard scans command text. It admits one static, single-quoted GraphQL query through a narrow `gh api graphql` read route. The data argument rule applies only when every command is plain `printf`, `echo`, safe-option `grep`, `ps` or a literal assignment. A command substitution keeps the full runner check. Script files run by path, `gh` aliases and extensions, and command words built from variables or globs escape its checks. It also misses opaque URLs in other clients and files written by Write or Edit then run. Interpreter scripts such as `python3 -c` or `node -e` can run `gh` outside this check. Shell runners can also build `gh` from escapes or expansions. The upgrade path is a GitHub token that the driver cannot use for review-thread writes.

This boundary checks names and paths. It cannot see a copy of a protected row kept under another name, such as a scratch file. GitHub addresses content by ID, such as a blob or a `.diff`, with no path, so the hook denies `WebFetch` for these agents when the raw or decoded URL names `github.com`, `githubusercontent.com` or a subdomain after Unicode normalization, and denies any host that stays non-ASCII. A URL on another code host that addresses content by ID carries no path, so the hook cannot check it.

An admission record lives at `row-review/<agent ID>.json` in the hook state folder or at `<workspace>/.scratch/ultraship/row-review/<agent ID>.json`.
The hook starts at the real path of the reviewer's working directory.
It uses the first directory with a `.scratch` folder as the workspace, checking that path and then its parents.
When the shared record path exists, the hook reads only that record.
The hook checks the workspace path only when the shared path is absent.
The workspace record's parent must belong to the hook user and have zero symlink components.
The record holds `pr`, `agent_id`, `row_files`, and `expires_at` (UTC, at most 4 hours ahead).
The hook user must own the file. The file must deny group and world writes.
The hook denies Write, Edit, and NotebookEdit in both folders for every agent except the driver and the main session.
For Bash, the hook only checks the command text for `ultraship/row-review`, so a path built from pieces passes this check.

A re-anchor admission record lives at `row-reanchor/<agent ID>.json` in the hook state folder.
It holds `pr`, `agent_id`, `row_file`, `row_id` and `expires_at` (UTC, at most 4 hours ahead).
The shared record checks require a regular file owned by the hook user, at most 64 KiB, without group or world writes.
The command must match its canonical protected row file and row ID.
Only the driver and the main session write this folder through Write, Edit or NotebookEdit.
The Bash custody check matches `ultraship/row-reanchor` as command text.
The tool derives both fields from Git blobs, preserves the whole-file mutant hunks, and prints only results.
Keep the row task pending after a refusal. Record the outcome and request a permitted route from the driver.
See the [lane-owned row route](skills/ship/SKILL.md#lane-owned-row-route) and its [tool admission record](skills/ship/references/owner-decisions.md#row-re-anchor-tool-admission-record).

The hook sees these tools: `Agent`, `Task`, `Bash`, `Edit`, `Write`, `NotebookEdit`, `WebSearch`, `Read`, `Grep`, `Glob`, `LSP`, `WebFetch`, `mcp__fff__*`, and the three `mcp__bettercoding__` Input tools (`create_input`, `update_input`, `set_input_status`). Reviewer, triage and verifier agents list no MCP tools, so no other `mcp__` tool reaches these agents.

An exception inside the `pre` hook denies every tool call for every caller. A process failure blocks every tool the PreToolUse hooks see. This includes missing `python3`, syntax or import errors, timeouts, and bad exit codes. Input that fails JSON parsing or contains a value other than an object denies the call.

Hook state lives in `${XDG_STATE_HOME:-~/.local/state}/ultraship`.

The hook issues one grant for one exact `account`, `account-auto`, or `correct-binding` call from the main session or driver. Run the command alone on one line with the literal script and pending paths. Copy the pending path from Stop. The grant store uses the OS account home. The CLI consumes the grant before it reads accounting evidence and uses the hook's evidence directory.

Grants expire after five seconds. The hook issues the grant before the permission prompt. A later denial can leave the grant usable for an identical invocation until expiry. The grant protects calls that control arguments and environment variables. It provides no isolation from arbitrary code that runs as the same OS user.

A checkout with its Git directory inside the checkout uses `<common-git-dir>/ship/ledger/<branch>.tsv`. An existing parent `.scratch` identifies the workspace for a direct-child linked checkout. A common Git directory inside that workspace also uses the common-directory default. An external common Git directory selects `<workspace>/.scratch/ship-ledgers/<canonical-checkout-sha256>/<branch>.tsv`. The resolver canonicalizes roots and rejects symlink escapes. Ambiguous layouts require an absolute `SHIP_LEDGER_DIR`.

The first local resolution imports the same-branch legacy TSV byte-for-byte, including its open run and all evidence. A sidecar `.import.json` records the canonical legacy path and SHA256. Cooperating first users share an exclusive local import lock. Readers and writers then use the local ledger exclusively. The legacy ledger remains frozen history. Import errors preserve the source and require resolution.

The sole driver must hold run custody and retire old legacy writers before import. Old writers can race the snapshot read. Local locking covers cooperating importers only. Import requires legacy read permission and local directory write permission. It grants zero legacy write permission. CLI commands, completion checks, Stop, and compact share the resolver. Stop retains exact pending evidence through access failures, missing runs, and failed appends. Notifications bind to the ledger path and run-start identity when ledger access succeeds. Stop accepts accounting from that run after successful closure. Persistent hook-state receipts consume each accounting row once across Stop cycles and sessions. Each notification has a fresh ID, including repeat notifications from the same agent. Receipt publication precedes pending-evidence clearing. Legacy notifications require one unambiguous time-containing run; ambiguous evidence stays pending.

Set `SHIP_LEDGER_DIR` to an absolute permitted directory for an explicit home, for example `export SHIP_LEDGER_DIR="$PWD/../.scratch/ship-ledgers"`. Export it for ledger commands and hooks. The directory directly contains the branch TSV; branch filenames replace `/` with `__`. Empty and relative values raise an error. The override selects its home without legacy import.

## Count source at a commit

Run the executable helper directly to count overlapping UTF-8 literal bytes in a committed regular file.
Pass each option once, with its value as a separate word, in any order.

```bash
<installed ship plugin root>/skills/ship/scripts/source-count.py --repo /absolute/repo --commit <full-sha> --subject src/example.py --literal 'exact text'
```

Use the literal absolute path of the installed plugin's script; the writer hook refuses a shell expansion in that command word.
The writer hook also refuses literals combining `$` with interpreter-like text, ANSI-C quoting, and raw whitespace beyond space, tab, and newline.
Keep the count pending after a refusal. Use the literal helper form above only when it meets the named rule. Ask the driver for a permitted proof route when the literal itself is blocked.

The repository path must be canonical and absolute; the commit must be a full lowercase SHA.
The subject must be a normalized repository-relative POSIX path.
The helper reads the committed blob and ignores checkout edits, replacement objects, and `GIT_*` environment variables.
It refuses `tests/mutation` paths, `.git` path segments, `.env` and `.env.*` files, `.pem` and `.key` files, directories, symlinks, and submodules.
Python isolated mode comes from the executable shebang.

Success prints one JSON line with `result`, `repo`, `commit`, `subject`, `blob`, `count`, `literal_bytes`, and `literal_sha256`.
Refusal prints one JSON line with `error` and `result: REFUSED`, and exits with status 2.
In a partial clone, the helper never fetches a missing object; it refuses with the `git` identifier instead.
The guard needs a Git build that honors `GIT_NO_LAZY_FETCH`; the partial-clone test fails on a build that ignores it.
Bound each run with a caller-owned `timeout --signal=TERM <seconds>`; the signal reaches the helper and its Git child.
Output contains neither source bytes nor the literal; stderr stays empty.
For positive counts, blob readers can recover the literal using `literal_bytes` and `literal_sha256`, so give the output the same handling as the literal.

## Test

```bash
TMPDIR="$PWD/.scratch" python3 plugins/ship/hooks/ultraship_test.py
```
