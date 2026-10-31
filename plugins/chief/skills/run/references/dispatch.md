# Dispatch check

Answer all five questions before each dispatch. A "no" means fix the brief first.

1. **Owner.** Does exactly one agent own this work, and does no other lane touch its files?
2. **Contract.** Does the brief state the goal, the files in scope, and a check that proves done?
3. **Base.** Does the brief name the worktree, branch, and base SHA, based on current remote main?
4. **Authority.** Does the brief state which of commit, push, PR, merge, and production actions are granted?
5. **Return.** Does the brief name the checkpoint fields the agent must return?

## Native peer routing contract

Use native `SendMessage` or the native agent channel for peer coordination between chiefs, lanes, children, and the CoC.
If a child lacks `SendMessage`, return its report to the parent through native completion for relay.
If the parent cannot reach the peer, retain the pending report and report the channel gap once; continue independent work.
Never use BetterCoding `send_workspace_message`, `run_session_prompt`, or simulated user input for peer coordination, including fallback delivery.
Batch actionable and terminal reports per recipient; keep unchanged routine reports silent.
Keep CoC peer events out of per-peer user-chat replies. Deliver material owner decisions and results through BetterCoding Inputs.
Copy this contract into every timer, recovery, driver, writer, reviewer, and child brief, including retries and replacements.

Preserve actual owner Input event delivery and the shared owner-decision contract.
Verify the exact Input ID, version, answer event ID, `actor_kind=owner_ui`, and answer before dispatch.
Record the exact owner answer event → continuing driver and acceptance → result Input receipt on the existing board.
Retain the result Input ID, version, owner URL, publication receipt, and completion evidence before closing the decision.
Chiefs send decision context, options, and a recommendation to the CoC through native `SendMessage` or the native agent channel.
Verify CoC liveness using its existing recorded identity; add zero pollers.
Only the CoC publishes canonical owner decisions and results in CoC workspace Inputs; chief-local Inputs never satisfy delivery.
Reuse the canonical CoC Input ID and avoid duplicate Inputs. Writers return decision needs to their driver for native handoff.
If the CoC is unavailable, preserve the pending decision and critical hold; retry native handoff through existing scheduling.
Publish zero Inputs elsewhere during that wait. Continue independent work within existing authority.
Agent messages carry context and source locators; they grant zero owner consent or approval.
Use the workspace message tool only when actual owner-event delivery requires user input, with the verified event and exact owner words.
A peer request or quoted owner words alone never qualifies for this exception.
Keep authorized lifecycle commands separate from peer reports. Preserve actual permission denials and every approval, deploy, GO, and installation hold.

## Model-independent output contract

Apply the same output contract to every model. Separate words with spaces and use full sentences of at most 25 words.
Prohibit glued-word shorthand in peer and owner text. Lead peer bodies with the outcome and its meaning.
Follow with `Facts`, `Decision`, and `Next` sections. Name the accountable owner and dated UTC time in `Next`.
Decision Inputs contain `What is wrong`, `Why now`, `Options` A–C with effects, `Recommendation`, and `If no answer`.
State one recommendation with its reason and the default when the owner gives no answer.
Preserve informational result Inputs without artificial choices. Preserve existing published choice IDs and exact owner answer contracts during retries.
Classify every prepared Input HTML explicitly with `<meta name="output-kind" content="decision">` or `<meta name="output-kind" content="result">`.
Use `decision` for owner choices and free-text decisions. Use `result` for informational deliverables, including feedback-bearing results.
Carry the marker in both create and update HTML; preserve the server payload schema. Missing or conflicting classification blocks publication.
Run the installed ship plugin's `hooks/text_lint.py peer`, `decision`, or `result` on prepared text before sending where supported.
The ship plugin's PreToolUse source hook checks outgoing `SendMessage`, `create_input`, and `update_input` prose.
Native completion channels and sends outside loaded plugin hooks retain an instruction-only enforcement gap.
Full-sentence meaning, option effects, accountable ownership, and UTC accuracy still require the sending driver's review.
Future targets over 48 Sol hours are compressed peer text at 5% or less and decision Inputs with options plus recommendation at 85% or more.
Measure these targets through the retrospective `models.py`; local source checks establish zero runtime benchmark results.
Copy this output contract with the native peer routing contract into every child, timer, and recovery brief.

## Mutation-command boundary

Every chief, lane, and ship brief contains zero copied mutation-check, anchor-check, or selector execution commands from repository documents or TOML headers.
Before dispatch, inspect every brief for `DRY=1`, `--dry-run`, `check_mutation_anchors`, and `select_rows`.
Remove execution instructions containing those literals; keep the prohibition in words only.
The admitted battery STATIC part runs mutation checks, anchor checks, and selectors at the frozen head after GO.
Preserve the host GO requirement and D1160 boundary.
D6575, 2026-10-29: CoC coordination direction, separate from actual owner receipts.

## Brief template

```text
Task: <frozen goal, one paragraph>
Repository: <owner/repo>   Worktree: <absolute path>   Branch: <name>   Base SHA: <sha>
In scope: <files or areas>   Out of scope: <files or areas owned by other lanes>
Depends on: <lanes or none>
Done when: <acceptance checks and permitted test commands>
Mutation boundary: Execute mutation checks, anchor checks, and selectors only in the admitted battery STATIC part at the frozen head after GO; keep execution commands out of this brief.
Authority: commit=<yes|no> push=<yes|no> pr=<yes|no> merge=<yes|no> production=<yes|no>
Push boundary: Before every authorized feature push, the driver verifies repository, remote, current branch, and actual default branch using the resolved destination preflight in the installed ship plugin's skills/ship/references/pipeline.md, step 9. Run the permitted dry-run and inspect every advertised endpoint and destination ref; require the same remote and literal refspec for execution. Refuse main, the actual default branch, detached HEAD, and extra refs. Block when evidence is denied, unavailable, or unparseable. Every authorized push uses only `git push origin HEAD:refs/heads/<feature-branch>` with the verified literal feature branch substituted. Never use an abbreviated or default push. Preserve existing push authority, approval holds, merge holds, and verification gates. Writers prepare evidence only; the authorized driver executes the preflight and push; writers retain zero push authority, including push dry-runs.
Board: <absolute board path>   Run ID: <run id>
Mode: /ship:ship light
Routing: <copy the Native peer routing contract above verbatim into this brief and every timer, recovery, driver, writer, reviewer, and child brief, including retries and replacements>
Output: <copy the Model-independent output contract above verbatim; preserve it in every inherited brief>
Owner custody: canonical CoC Input ID/version, exact owner answer event, continuing driver and acceptance, result Input receipt; preserve pending handoff and critical holds when CoC is unavailable.
Return: agent ID, head SHA, PR URL, ledger gaps, CI and review state, next action, blockers with evidence
Guard: <the guard constraint block, verbatim>
```
