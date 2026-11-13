"""Static instruction contracts only; these checks do not execute agent behavior."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
INPUT_ID = '32c223a4-6bd9-43d1-b049-19a3990d2379'
WORKSPACE_ID = 'b8fed386-cf11-40fe-b14f-425e6331ee41'
EVENT_ID = '1c2e4bf5-10c2-4cb2-9abc-ab86ba945fc8'

EXPECTED_LANE_REVIEW = [
    '## Lane-derived row review',
    'For an owner-approved protected-row subject route adaptation, paired review compares the subject commit with the final commit while preserving the subject and every field freeze; keep the original base and author head for CI binding.',
    "On that combined route only, use the subject commit as this section's row comparison base and the final commit as its frozen SHA after the edit.",
    'Keep the original base for the PR-breaking source diff, tested-merge containment and CI evidence requirements below; the subject commit supplies only the paired row comparison base.',
    'Use this read-only route only when the brief names the lane-derived route and one of the two owner authorities below.',
    'Authority A: the owner standing grant in the owner global CLAUDE.md (`~/.claude/CLAUDE.md`), section "CoC decisions".',
    'Under authority A, read that file yourself and confirm that the section grants a lane re-anchoring the protected mutation rows its own diff breaks, with an identical mutant edit and an independent not-weaker review.',
    'Under authority A, block every protected read when the file or section is missing or grants less; authority A needs no owner-event record.',
    'Under authority A, bind the file path, section heading, quoted grant sentence, and verification time.',
    'Authority B: the complete verified owner-event record below.',
    'Owner authority: Input `31f787fe-1463-4447-82fa-6a5e21e17a87`, version 1, choice B, in CoC workspace `b8fed386-cf11-40fe-b14f-425e6331ee41`.',
    'The `owner_ui` event is `aacba25c-5e99-438e-85c7-9bb128ecf4b8`, dated 2026-11-08T18:03:15.357469375Z.',
    'The event hash is `d56c4fd20ef712921654f06869818b5b2189a13e9b52249b32379ca5362468a8`.',
    'Owner-selected option B: "Each lane moves the protected rows its own PR breaks: same test, new line text, nothing weaker. An independent reviewer checks every row change, and the mutation proof still runs after merge."',
    'Input context: "Peral keeps CI runner and merge queue changes."',
    'Under authority B, bind full Input/workspace UUIDs, current version, event id/hash, choice, actual owner answer, verifier name, and verification time.',
    'Under authority B, record selected choice B and `payload.answer.text=null` separately; distinguish the selected option text from Input context.',
    'Under authority B, require `event_type=answer_submitted`, `actor_kind=owner_ui`, and `payload.no_answer_yet=false` for this Input and current version.',
    "Under authority B, use `get_input` directly when available; accept the driver's or CoC's complete verified record only after tool absence or auth/tool error.",
    'Under authority B, an authoritative mismatch blocks access and cannot use fallback.',
    "Under authority B, check the relayed record's internal consistency, answer, and exact scope; refuse stale, superseded, cancelled, inconsistent, or invented provenance.",
    'Under authority B, block every protected read on a missing record, missing field, or mismatch.',
    "Require the CoC-approved exact allowlist of row-file paths and unique row IDs from the PR's own failing anchor CI evidence.",
    'Require the recorded base SHA, author head SHA, and frozen SHA after the edit before any protected read.',
    'Require the brief to name two read-only trees: one at the base SHA and one at the frozen SHA after the edit.',
    'Read rows only inside those two trees.',
    'Require every supplied diff to leave out the row-file hunks.',
    "Require the recorded diff between the base SHA and frozen SHA after the edit to show that the PR's own subject change breaks each named row.",
    'Bind CI evidence to the repository, PR, base SHA, author head SHA, tested merge SHA/tree, run ID, attempt, and job ID/name.',
    'Require the tested merge to contain the recorded base SHA and author head SHA.',
    'Require the frozen SHA after the edit to contain the author head SHA.',
    'Bind each row to its CI-named subject file.',
    'Refuse stale, ambiguous, unrelated, or unlawfully obtained scope or evidence before any protected read.',
    'Permit locating each named row by its row ID inside its named file in each named read-only tree.',
    "Read only that row's lines in the named trees at the base SHA and frozen SHA after the edit.",
    'Permit no whole-file parse, unnamed-row read, or search outside the named files.',
    'Require the reviewer to differ from the PR author and the applying writer.',
    'Confirm for every row the same row ID, claim, subject, designated test, pins, operator, assertions, bounds, and unrelated fields.',
    'Confirm that only the paired `old` and `new` fields changed.',
    "Confirm that each new `old` text matches the subject's new source text at the site the PR changed.",
    'Confirm the identical mutant transformation from `old` to `new` and nothing weaker for every row.',
    'Bind the verdict and receipt to reviewer identity, approving verdict, authority (A or B), commit SHA, row-file paths, row IDs, and CI evidence.',
    "Bind the receipt's commit SHA to the frozen SHA after the edit.",
    'Require CoC approval of the review receipt before publication; changed source or evidence invalidates the receipt and approval.',
    'Identify rows in findings, verdicts, and receipts only by path, row ID, and field.',
    'For a row finding, give path, row ID, and field in place of `line`, and cite the rule, not the row text, as evidence.',
    'Include zero pair bytes and zero TOML text in findings, verdicts, and receipts.',
    'Grant zero edit, execution, mutation, or checker authority.',
    'Grant zero TOML search or anchor extraction authority outside these row-ID lookups and row-line reads.',
    'Grant zero whole-file parse or writer publication authority.',
    'Keep mutation proof after merge under separate applicable execution admission.',
    "Retain Peral's authority over CI runners and the merge queue.",
    'Preserve higher-priority instructions, effective refusals, tool and hook denials, and protected holds.',
]


EXPECTED_RETIREMENT_REVIEW = [
    '## Row retirement with replacement review',
    'Use this read-only route only when the brief names the retirement route and carries the CoC ruling that admits the retirement.',
    'A brief that names the removed-behavior retirement route uses Removed-behavior retirement review above instead.',
    'The CoC rules under the owner\'s testing delegation in the owner global CLAUDE.md, "CoC decisions".',
    'Admit the retirement of a protected row only when all four conditions hold:',
    "  1. The same PR adds a replacement row in the PR's own rows file.",
    '  2. The PR body names the retired row, the replacement row, and why the guarded behavior changes on purpose.',
    "  3. CI or anchor evidence at the PR head shows that the replacement row's designated test kills its mutant.",
    '  4. You give a not-weaker verdict: the replacement row guards the new behavior at least as tightly as the retired row guarded the old behavior.',
    'Refuse on any doubt about any condition.',
    'Refuse a retirement when the PR adds no replacement row.',
    'Require the CoC-approved exact allowlist: the row-file path and unique row ID of the retired row and of the replacement row.',
    "Require the retired row to come from the PR's own failing anchor CI evidence.",
    "Require the recorded diff between the base SHA and the PR head SHA to show that the PR's own subject change breaks the retired row.",
    'Bind the retired row to its CI-named subject file.',
    'Require the recorded base SHA and PR head SHA, and read-only trees at those two SHAs.',
    'Require every supplied diff to leave out the row-file hunks.',
    "Read only the retired row's lines at the base SHA and the replacement row's lines at the PR head SHA.",
    'Bind CI evidence to the repository, PR, base SHA, PR head SHA, tested merge SHA/tree, run ID, attempt, and job ID/name.',
    'Require the tested merge to contain the recorded base SHA and PR head SHA.',
    'Require the reviewer to differ from the PR author and the writer who made the row edits.',
    'Bind the verdict and receipt to reviewer identity, approving verdict, CoC ruling identity, PR head SHA, row-file paths, row IDs, and CI evidence.',
    'Require CoC approval of the review receipt before publication; changed source or evidence invalidates the receipt and approval.',
    'Identify rows in findings, verdicts, and receipts only by path, row ID, and field; include zero TOML text.',
    'Grant zero edit, execution, mutation, or checker authority.',
    'An admission grants zero writer or driver edit authority.',
    'Review every other row change under Lane-derived row review below.',
    'Preserve higher-priority instructions, effective refusals, tool and hook denials, and protected holds.',
]


EXPECTED_REMOVED_RETIREMENT_ROUTE = [
    "Use this route only to retire a protected row that the PR's own diff removed together with the source behavior that the row guarded.",
    'Require the CoC decision that admits each retirement and name this route in the brief.',
    'On this route, the loaded edit authority is that CoC decision (owner standing grant: "The CoC decides CI/CD, testing and tooling items for me"); Owner-scoped protected row access grants nothing on this route.',
    "Limit scope to CoC-named exact row-file paths and unique row IDs from the PR's own failing anchor CI log line that reports the row `in the base file, missing at HEAD`.",
    'Require the recorded base/head diff to show that the PR removes each named row and the source behavior that the row guarded.',
    'Require the PR body to give the reason for each removed row.',
    'Append exactly one `[[retired]]` table per named row at the end of its named file.',
    'Set its `id` to the row ID and copy its `reason` verbatim from the PR body as one TOML basic string, escaping `\\`, `"`, and every control character such as a line break.',
    'Start the appended text with an empty line, so it never joins the last existing line.',
    'Change nothing else in the named file: no existing line, row, field, pin, or table.',
    'Another approved exact edit to the same file, such as a `claims` pin change, needs its own authority and its own commit; this route grants none.',
    'Read, search, or parse no existing content of the named file.',
    'Permit the applying writer to parse only the appended text, never the named file, to check that it is valid TOML.',
    'Append with one isolated `python3 -I -` heredoc that imports only `tomllib`, checks the appended text with `tomllib.loads`, and appends to the literal absolute row-file path.',
    'Run nothing else in that Bash call; get the line counts with `git diff --numstat` in a later, separate call.',
    'Check the retirement commit only with content-free line counts for each named file: added lines only, zero deleted lines.',
    'Refuse a row whose guarded behavior still exists in any form, including a changed form at the same site, or that moved or has a replacement row.',
    'Before the push, require an independent reviewer to run its Removed-behavior retirement review and confirm for every named row that the guarded behavior is gone and not moved, and that the file change is only the appended tables.',
    'Require that reviewer to differ from the PR author and the applying writer.',
    'Bind the review receipt to reviewer identity, approving verdict, CoC decision identity, commit SHA, row-file paths, row IDs, and CI evidence.',
    'Require CoC approval of that review receipt before the push; changed source or evidence invalidates the receipt and approval.',
    'Keep messages, briefs, and PR bodies free of pair bytes and row TOML text; identify each edit only by path, row ID, and the appended `[[retired]]` table.',
    'Beyond that check of the appended text, this route grants zero TOML search or parse authority, protected reads, or anchor extraction.',
    'Require separate admission for every mutation or checker execution; keep mutation proof after merge.',
    "Preserve zero writer publication authority, effective refusals, tool and hook denials, protected holds, and Peral's CI-runner and merge-queue authority.",
]


EXPECTED_REMOVED_RETIREMENT_REVIEW = [
    '## Removed-behavior retirement review',
    'Use this read-only route only when the brief names the removed-behavior retirement route and carries the CoC decision that admits the retirement.',
    'The CoC decides under the owner\'s testing delegation in the owner global CLAUDE.md, "CoC decisions".',
    'Admit the retirement of a protected row only when all four conditions hold:',
    "  1. The PR's own failing anchor CI evidence reports the row `in the base file, missing at HEAD`.",
    '  2. The recorded diff between the base SHA and the author head SHA removes the source behavior that the row guarded.',
    '  3. The guarded behavior is gone from the tree at the frozen SHA after the edit: not changed in place, moved, renamed, or reimplemented elsewhere.',
    '  4. The retirement commit appends exactly one `[[retired]]` table per named row, with that row ID and the PR-body reason, and changes nothing else in the file.',
    'Refuse on any doubt about any condition.',
    'Refuse a retirement when the guarded behavior still exists anywhere in the tree at the frozen SHA after the edit.',
    "Refuse when an identical mutant of the row's operation, with the same claim, still applies at the frozen SHA after the edit; that row uses the lane-derived route.",
    'Review a retirement with a replacement row under Row retirement with replacement review below, and every other row change under Lane-derived row review below.',
    'Require the CoC-approved exact allowlist: the row-file path and unique row ID of each retired row.',
    'Require the brief to quote the PR-body reason for each retired row.',
    'Require the recorded base SHA, author head SHA, and frozen SHA after the edit, and read-only trees at the base SHA and the frozen SHA after the edit.',
    'Require the brief to give the retirement commit SHA and content-free line counts for each named file between that commit and its parent.',
    'Require every supplied diff to leave out the row-file hunks.',
    'Permit locating each named row and each appended `[[retired]]` table by its row ID inside its named file.',
    "Read only each retired row's lines at the base SHA and each appended `[[retired]]` table at the frozen SHA after the edit.",
    "Confirm from those line counts that each named file gains exactly the appended tables' lines and loses none.",
    'Search only non-row source and test files for the guarded behavior.',
    'Bind each retired row to the subject file that its base row names.',
    'Bind CI evidence to the repository, PR, base SHA, author head SHA, tested merge SHA/tree, run ID, attempt, and job ID/name.',
    'Require the tested merge to contain the recorded base SHA and author head SHA.',
    'Require the frozen SHA after the edit to contain the author head SHA and the retirement commit.',
    'Require the reviewer to differ from the PR author and the writer who made the row edits.',
    'Bind the verdict and receipt to reviewer identity, approving verdict, CoC decision identity, frozen SHA after the edit, row-file paths, row IDs, and CI evidence.',
    'Require CoC approval of the review receipt before the push; changed source or evidence invalidates the receipt and approval.',
    'Identify rows in findings, verdicts, and receipts only by path, row ID, and field; include zero TOML text.',
    'Grant zero edit, execution, mutation, or checker authority.',
    'Grant zero TOML search or anchor extraction authority outside these row-ID lookups and row-line reads.',
    'An admission grants zero writer or driver edit authority.',
    'Preserve higher-priority instructions, effective refusals, tool and hook denials, and protected holds.',
]


class ApprovedTestAdaptationsTests(unittest.TestCase):
    def test_owner_approved_subject_route_keeps_authority_application_and_review_scoped(self):
        carriers = (
            'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/agents/driver.md', 'plugins/ship/agents/driver--sol.md',
            'plugins/ship/skills/ship/SKILL.md',
        )
        contracts = {
            'authority': (r'Owner-scoped protected row access', r'separate.*task-specific.*owner.*event',
                          r'allowlist.*(?:equal|exact.*match)', r'current.*replacement',
                          r'both.*(?:records|authorit).*same.*(?:source|identit)',
                          r'mismatch.*(?:entire|whole).*batch', r'authoritative mismatch.*(?:fallback|reject)',
                          r'(?:absen|auth/tool error|auth or tool error)'),
            'application': (r'native Edit', r'replace_all\s*=\s*false',
                            r'old_string.*unique.*(?:row|ID)', r'old_string.*(?:inside|within).*approved.*(?:row|lines)',
                            r'(?:missing|non-unique).*match.*(?:refuse|block)|(?:refuse|block).*non-unique.*match',
                            r'paired.*separate.*authority.*separate commit.*separate receipt',
                            r'combined.*(?:review|result)', r'(?:preserve|unchanged).*assertions.*bounds'),
            'review': (r'independent.*read-only', r'identical mutant', r'CoC.*receipt.*before publication'),
            'combined_checkpoints': (
                r'subject alone.*subject commit.*paired fields alone.*final commit',
                r'paired review.*subject commit.*final commit',
                r'original base.*author head.*CI binding',
                r'subject review.*only.*subject.*subject commit',
                r'combined.*defer.*exactly.once.*final combined review',
                r'final combined review.*original base.*final commit',
                r'final.*receipt.*both.*(?:earlier|prior).*receipts.*authorit.*commit identit',
            ),
        }
        for name in carriers:
            text = (ROOT / name).read_text()
            _, heading, after = text.partition('### Owner-approved protected-row subject route\n')
            route = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', after, maxsplit=1, flags=re.MULTILINE)[0]
            with self.subTest(path=name):
                self.assertTrue(heading)
                for contract, patterns in contracts.items():
                    for pattern in patterns:
                        with self.subTest(contract=contract, pattern=pattern):
                            self.assertRegex(route, '(?is)' + pattern)
                _, _, access = text.partition('#### Owner-scoped protected row access\n')
                access = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', access, maxsplit=1, flags=re.MULTILINE)[0]
                self.assertIn('owner-approved protected-row subject route', access)
                _, _, lane = text.partition('#### Lane-derived route\n')
                lane = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', lane, maxsplit=1, flags=re.MULTILINE)[0]
                self.assertIn('Keep row ID, claim, subject, designated test, pins, operator, assertions, bounds, and unrelated fields unchanged.', lane)
                self.assertRegex(route, r'(?is)(?:only|solely).*subject.*(?:scope|replacement)')
                self.assertRegex(route, r'(?is)(?:other|outside).*subject.*(?:freeze|unchanged)')
        fable = (ROOT / 'plugins/ship/agents/writer--fable52.md').read_text()
        self.assertTrue(any(
            re.search(r'\brefuse\b', sentence, re.IGNORECASE)
            and 'owner-approved protected-row subject route' in sentence
            and 'loaded definition' in sentence
            for sentence in re.split(r'[.!?](?:\s|$)', fable)
        ))

    def test_owner_approved_subject_review_preserves_other_subject_freezes(self):
        for name in ('reviewer--sol.md', 'reviewer--opus.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            _, heading, after = text.partition('## Owner-approved protected-row subject review\n')
            route = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', after, maxsplit=1, flags=re.MULTILINE)[0]
            with self.subTest(path=name):
                self.assertTrue(heading)
                for pattern in (r'both.*authorit.*(?:matching|same)', r'read-only.*(?:base|trees).*final',
                                r'old anchor.*exactly once.*new subject', r'identical mutant.*(?:claim|test)',
                                r'CoC.*receipt.*before publication', r'line counts.*(?:only|cannot)',
                                r'paired.*separate.*receipt', r'combined.*(?:review|result)',
                                r'reviewer.*(?:differ|independent).*PR author.*applying writer',
                                r'only.*approved fields.*(?:change|changed)|only.*(?:change|changed).*approved fields'):
                    self.assertRegex(route, '(?is)' + pattern)
                for pattern in (
                    r'access.*fixed Authority B.*Lane-derived row review',
                    r'Authority A.*(?:zero|nothing|no authority)',
                    r'Authority B.*(?:relay|fallback).*checks',
                    r'protected.*reads.*only.*named row files',
                    r'ordinary.*reads.*original subject.*base.*approved subject.*subject.*final commit',
                    r'subject review.*only.*subject.*subject commit',
                    r'combined.*defer.*exactly.once.*final combined review',
                    r'paired review.*subject commit.*final commit.*subject.*unchanged',
                    r'original base.*author head.*CI binding',
                    r'final combined review.*original base.*final commit',
                    r'final combined review.*anchor.*exactly once.*new subject.*identical mutant.*unchanged guarantees',
                    r'final.*receipt.*both.*(?:earlier|prior).*receipts.*authorit.*commit identit',
                ):
                    with self.subTest(contract=pattern):
                        self.assertRegex(route, '(?is)' + pattern)
                self.assertTrue(any(
                    'Authority A' in sentence
                    and re.search(r'\b(?:zero (?:protected )?access|grants nothing)\b', sentence, re.IGNORECASE)
                    for sentence in re.split(r'[.!?](?:\s|$)', route)
                ))
                self.assertNotIn('row-line reads in those trees', route)
                _, _, lane = text.partition('## Lane-derived row review\n')
                self.assertIn('Confirm for every row the same row ID, claim, subject, designated test, pins, operator, assertions, bounds, and unrelated fields.', lane)
                self.assertRegex(
                    lane,
                    r'(?is)owner-approved protected-row subject route.*paired.*subject commit.*final commit.*original base.*author head.*CI binding',
                )

    def test_subject_route_shared_boundary_preserves_denials_and_identity_scope(self):
        text = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        _, heading, after = text.partition('## Owner-approved protected-row subject route\n')
        self.assertTrue(heading)
        boundary = re.split(r'^ {0,3}#{1,2}(?:[ \t]+|$)', after, maxsplit=1, flags=re.MULTILINE)[0]
        for pattern in (r'future briefs.*verified runtime adoption', r'Native Edit.*zero.*alternate.*denied',
                        r'actual cause.*fresh applicable disposition', r'(?:never|zero).*replay.*(?:equivalent|actor)',
                        r'product-limit.*cost.*zero.*(?:protected|subject)',
                        r'literal.*(?:worktree|path).*allowlist', r'fsmonitor.*(?:external diff|text conversion)',
                        r'(?:inconsistent|changed).*checkpoint.*(?:invalid|block)|invalid.*(?:inconsistent|changed).*checkpoint',
                        r'exclude.*protected files', r'computed.*process-capable Python.*denied'):
            with self.subTest(pattern=pattern):
                self.assertRegex(boundary, '(?is)' + pattern)

    def test_writers_require_verified_authority_and_preserve_controls(self):
        for name in ('writer--sol.md', 'writer--sonnet.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            for phrase in (
                INPUT_ID, WORKSPACE_ID, EVENT_ID, 'get_input', 'owner_ui',
                'Outside the exceptions in the guard paragraph above, never make a test, pin, census, register, or bound edit on your own initiative.',
                'approved that exact edit and cites this owner rule',
                'Then apply the edit with no council round and no owner question.',
                'stop and report to the driver',
                '`answer_submitted`', 'choice `plugin_rule`',
                'Record the approver, the exact edit, and the Input ID in the PR body.',
                'Never loosen an assertion, widen a bound, or delete a check',
                'zero writer push authority',
                'You may return a frozen source checkpoint to request a GO for a run that requires GO.',
                'Report the exact worktree, branch, base/HEAD SHAs, changed paths, file hashes, and complete diff digest.',
                'Include staged, unstaged, and relevant untracked content in the path inventory, file hashes, and complete scoped content fingerprint.',
                'A tracked Git diff alone omits untracked content.',
                'Require a new checkpoint and fresh applicable GO after any source change to a run that requires GO.',
                'List pending checks and identify every unexecuted proof.',
                'Make no final completion or pass claim in this intermediate request.',
                'Keep all applicable final test and check requirements binding.',
                'A checkpoint grants zero test execution authority; apply the execution admission rules above and the brief.',
                'An exact-path exception or register entry named in a Chief/CoC brief may use an already applicable same-guarantee authority route.',
                'Verify the owning predicate, exact path, entry, reason, and unchanged guarantees.',
                'Send the driver the quoted applicable existing authority clause and exact approved scope before applying the scoped edit.',
                'Internal reasoning alone does not satisfy this driver-visible requirement.',
                'Use an existing standing, council/Chief, or owner-event route; retain every applicable provenance and fixed-event check.',
                'Bare naming supplies zero authority.',
                'Preserve higher-priority prohibitions, effective denials, security/resource policy, and protected holds under every route.',
                'Verify the owner event yourself when you have a `get_input` tool',
                'Verifier fallback: when you have no `get_input` tool, or the call fails with an auth or tool error, the driver or the CoC runs `get_input`',
                'the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name',
                'Check that the recorded Input UUID, workspace UUID, event id, and choice id equal the values quoted in this definition',
                'On a match, apply the exact approved edit.',
                'Fail closed: when your own `get_input` call returns an event that does not match, when `get_input` fails and the brief has no verified event record, when any recorded field is missing or differs from the values in this definition, or when the brief does not name the exact edit, make no edit; stop and report to the driver.',
            ):
                with self.subTest(path=name, phrase=phrase):
                    self.assertIn(phrase, text)
            for number, phrase in enumerate((
                'EXPECTED_GROUPS', 'census digest',
                'tests.race_helpers.wait_for_task', 'setup-only fixture',
            ), 1):
                with self.subTest(path=name, case=number):
                    self.assertTrue(any(
                        line.startswith(f'  {number}. ') and phrase in line
                        for line in text.splitlines()
                    ))

    def test_drivers_supply_owner_event_coordinates(self):
        for name in ('driver.md', 'driver--sol.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            for phrase in (
                INPUT_ID, WORKSPACE_ID, EVENT_ID, 'get_input',
                'Outside the exceptions in the writer guard paragraph, never ask a writer for a test, pin, census, register, or bound edit that the CoC or the topic Chief did not approve.',
                'the exact edit and file, the approver and the approval time, the owner rule citation, the Input ID, and the workspace ID',
                'Loosened assertions, widened bounds, and deleted checks stay forbidden.',
                'A writer without a `get_input` tool depends on your record',
                'the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name',
                'Record only values read from a `get_input` result.',
            ):
                with self.subTest(path=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_fifth_standing_adaptation_requires_scoped_ci_anchor_evidence(self):
        category = 'Refresh paired `old` and `new` anchor strings only in exact approved PR-owned rows.'
        for name in (
            'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/agents/driver.md', 'plugins/ship/agents/driver--sol.md',
            'plugins/ship/skills/ship/SKILL.md',
        ):
            text = (ROOT / name).read_text()
            direct_heading = re.search(r'^#### Explicit-pair route$', text, flags=re.MULTILINE)
            direct = text[direct_heading.end() + 1:] if direct_heading else ''
            direct = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)|^.+\n {0,3}(?:=+|-+)[ \t]*$',
                              direct, maxsplit=1, flags=re.MULTILINE)[0]
            private_heading = re.search(r'^#### Private-proposal route$', text, flags=re.MULTILINE)
            private = text[private_heading.end() + 1:] if private_heading else ''
            private = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)|^.+\n {0,3}(?:=+|-+)[ \t]*$',
                               private, maxsplit=1, flags=re.MULTILINE)[0]
            lane_heading = re.search(r'^#### Lane-derived route$', text, flags=re.MULTILINE)
            lane = text[lane_heading.end() + 1:] if lane_heading else ''
            lane = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)|^.+\n {0,3}(?:=+|-+)[ \t]*$',
                            lane, maxsplit=1, flags=re.MULTILINE)[0]
            removed_heading = re.search(r'^#### Removed-behavior retirement route$', text, flags=re.MULTILINE)
            removed = text[removed_heading.end() + 1:] if removed_heading else ''
            removed = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)|^.+\n {0,3}(?:=+|-+)[ \t]*$',
                               removed, maxsplit=1, flags=re.MULTILINE)[0]
            shared = text
            for heading, body in sorted(
                ((direct_heading, direct), (private_heading, private), (lane_heading, lane),
                 (removed_heading, removed)),
                key=lambda route: route[0].start() if route[0] else -1,
                reverse=True,
            ):
                if heading:
                    shared = shared[:heading.start()] + shared[heading.end() + 1 + len(body):]
            with self.subTest(path=name, route='explicit_pair'):
                self.assertTrue(direct_heading)
            with self.subTest(path=name, route='private_proposal'):
                self.assertTrue(private_heading)
            route_selection_clauses = (
                'Category 5 uses exactly one route below, named in the brief.',
                'Every requirement of the named route applies; route-specific sentences bind only that route.',
                'Pairs from an admitted derivation gate stay in the private-proposal route.',
                "A row that the PR's own diff removed, with the source behavior it guarded, uses the removed-behavior retirement route.",
            )
            for phrase in (
                category,
                *route_selection_clauses,
                'Categories 1–4 retain their existing CoC-or-Chief approval routes and owner-event verification requirements.',
                'Category 5 requires loaded edit/access authority before any writer edit. On its named route, Owner-scoped protected row access below is that authority when all its requirements hold, including an identical mutant edit and an independent not-weaker review.',
                'Written approval and CI evidence grant zero protected access and do not replace applicable loaded edit/access authority.',
                'The PR author product diff supplies supporting evidence only at the CI-named subject file.',
                'The CoC reviews the same-operation, same-claim reason; product diff text alone cannot establish equivalent mutant semantics.',
                'Each approved row has an exact committed row-file path, unique row ID, and CI-named subject file.',
                'PR ownership requires the recorded base/head diff and exact approved row allowlist; a subject name alone is insufficient.',
                'Evidence binds the repository, PR, base SHA, author head SHA, tested merge SHA/tree, CI run ID, attempt, and job ID/name.',
                'The tested merge must contain the recorded base and author head; changed evidence invalidates the approval and applicable GO.',
                'Dry-run proof and CI at the new head require separate admission; this adaptation authorizes no mutation command execution.',
                'Only the exact approved paired `old` and `new` fields may change under category 5.',
                'The removed-behavior retirement route is the sole exception to the paired-field limit: it appends one `[[retired]]` table per approved row and changes no existing line.',
                'On that route, the CoC decision it names is the loaded edit authority.',
                'On that route, the independent review that the guarded behavior is gone replaces the CI-named subject, same-operation, same-claim, and identical-mutant requirements.',
                'Row identity, claims, subjects, designated tests, pins, operators, assertions, bounds, and unrelated fields remain unchanged under category 5.',
                'Missing, ambiguous, stale, mismatched, or unlawfully obtained evidence blocks the edit.',
                'Owner provenance, effective refusals, protected holds, and zero writer publication authority remain binding.',
                'Except for the reads that Owner-scoped protected row access permits on its named route, this adaptation grants no TOML search or parse authority, protected reads, or anchor extraction.',
            ):
                with self.subTest(path=name, shared_control=phrase):
                    self.assertIn(phrase, shared)
                for route, body in (('explicit_pair', direct), ('private_proposal', private), ('lane_derived', lane), ('removed_retirement', removed)):
                    with self.subTest(path=name, shared_control=phrase, outside_route=route):
                        self.assertNotIn(phrase, body)
            for phrase in route_selection_clauses:
                for route, heading in (('explicit_pair', direct_heading), ('private_proposal', private_heading), ('lane_derived', lane_heading), ('removed_retirement', removed_heading)):
                    with self.subTest(path=name, route_selection_before=route, phrase=phrase):
                        self.assertTrue(heading and 0 <= text.rfind(phrase) < heading.start())
            for phrase in (
                'Apply only CoC-approved exact current/replacement bytes for both paired `old` and `new` fields.',
                'Require independent same-operation, same-claim review of every row change before CoC pair approval.',
                'Bind reviewer identity and approving verdict to the exact pairs, row scope, source identities, and CI evidence.',
                'Category 5 requires written CoC approval supplying both exact replacement strings for each CI-named approved row.',
                'Category 5 approval supplies exact current and replacement bytes for both `old` and `new` fields in each approved row.',
                'Existing CI identifiers and quoted evidence suffice; this adaptation requires no producer, artifact, or digest.',
                'Evidence includes the quoted job log line and the job log URL where supplied.',
            ):
                with self.subTest(path=name, route='explicit_pair', phrase=phrase):
                    self.assertIn(phrase, direct)
                with self.subTest(path=name, route='explicit_pair_only', phrase=phrase):
                    self.assertNotIn(phrase, shared + '\n' + private + '\n' + lane + '\n' + removed)
            for phrase in (
                'Use the private-proposal route only with separately authorized and admitted derivation before any protected access.',
                'Freeze exact current/replacement pairs privately with source identity and the exact approved row scope.',
                'Written CoC approval binds the exact private proposal identity and SHA256, derivation launcher identity and receipt, source, rows, and CI evidence.',
                'Require independent in-gate review of the same-operation, same-claim evidence and exact approved scope.',
                'The reviewer differs from the PR author, the derivation operator, and the applying writer.',
                'Complete semantic review before written CoC approval in a separately authorized and admitted review context.',
                'A derivation admission supplies zero independent review authority.',
                'A lawful non-content review receipt binds reviewer identity, verdict, review admission identity, reviewed proposal SHA256, source identity, and exact scope.',
                'Written CoC approval binds that semantic review receipt, including its reviewer, verdict, review admission, reviewed proposal SHA256, source identity, and exact scope.',
                'A success receipt without bound semantic review remains insufficient for approval or application.',
                'Application refuses any mismatch between reviewed, approved, and applied proposal SHA256 values, source identities, or exact scopes.',
                'Application verifies the bound semantic review receipt and its approving verdict before any edit.',
                'Private CI evidence outside admission contains only content-free FAIL or WARN summaries and metadata, including the job log URL where supplied.',
                'Never open or quote anchor-bearing job log lines outside separately authorized and admitted access.',
                'A digest proves identity only; derivation success and a checksum cannot replace semantic review or authority.',
                'Approvers review lawful non-content evidence without opening the protected proposal.',
                'On this route, the brief and PR body identify the exact edit by proposal SHA256, row-file paths, row IDs, and fields.',
                'The brief and PR body contain zero pair bytes.',
                'Application requires separate applicable loaded edit/access authority and fresh admission.',
                'Application admission binds the stage-two launcher identity, exact approved proposal, and permitted checker scope.',
                'A derivation GO supplies zero application authority.',
                'Identify each derivation, review, and application gate by name and SHA256, never by an executable command line.',
                'Keep every brief command-free under the existing dispatch boundary.',
                'Inside the admitted application gate, verify proposal SHA256, exact current bytes, source identity, and approved scope before any edit.',
                'Apply only the approved paired fields and preserve every unrelated field.',
                'Run only the separately permitted checker inside its admitted scope.',
                'Refuse stale source, an altered proposal, ambiguity, missing evidence, or missing authority.',
                'Keep protected bytes inside admitted gates; emit zero raw pair bytes outside those gates.',
                'Approved proposal or launcher digests never override effective denials, protected holds, or higher-priority instructions.',
                'This instruction grants zero derivation, protected access, application, checker execution, or writer publication authority.',
            ):
                with self.subTest(path=name, route='private_proposal', phrase=phrase):
                    self.assertIn(phrase, private)
            for phrase in (
                'On this route, the brief and PR body identify the exact edit by proposal SHA256, row-file paths, row IDs, and fields.',
                'The brief and PR body contain zero pair bytes.',
            ):
                with self.subTest(path=name, route='private_proposal_only', phrase=phrase):
                    self.assertNotIn(phrase, shared + '\n' + direct + '\n' + lane + '\n' + removed)
            if Path(name).name.startswith('writer--'):
                with self.subTest(path=name, route='private_proposal', report_before_application=True):
                    self.assertIn(
                        'Send the driver the quoted authority clause, lawful non-content approval evidence, and exact approved scope before application; disclose zero protected bytes.',
                        private,
                    )
                private_role = 'Verify lawful non-content approval evidence; inspect and apply private pairs only inside separately authorized and admitted gates.'
            elif Path(name).name.startswith('driver'):
                private_role = 'Prepare the private-proposal brief from lawful non-content evidence; include derivation, review, and application gate identities without opening or quoting protected pairs.'
            else:
                private_role = 'Drivers and approvers use lawful non-content evidence; protected pair verification and application stay inside separately authorized and admitted gates.'
            with self.subTest(path=name, route='private_proposal', role=True):
                self.assertIn(private_role, private)
            with self.subTest(path=name, obsolete_source=True):
                self.assertNotIn(
                    'Use replacement text solely from CI `mutation-anchors` output bound to the tested head and exact approved row.',
                    text,
                )
            if Path(name).name.startswith('writer--'):
                standing_controls = (
                    '- Never loosen an assertion, widen a bound, or delete a check under this rule.',
                    '- Fail closed: when your own `get_input` call returns an event that does not match, when `get_input` fails and the brief has no verified event record, when any recorded field is missing or differs from the values in this definition, or when the brief does not name the exact edit, make no edit; stop and report to the driver.',
                    '- Record the approver, the exact edit, and the Input ID in the PR body.',
                    '- Every other control stays: caller-owned TERM escalation only, no D1160 commands, and the protected-path rules. Preserve the mutation TOML search prohibition outside the owner-scoped lane-derived route and the owner-approved protected-row subject route\'s named row-ID lookup, and preserve zero writer push authority.',
                )
                _, _, standing = text.partition('### Standing owner rule\n')
                standing = re.split(r'^ {0,3}#{1,3}(?:[ \t]+|$)|^.+\n {0,3}(?:=+|-+)[ \t]*$',
                                    standing, maxsplit=1, flags=re.MULTILINE)[0]
                for phrase in route_selection_clauses:
                    with self.subTest(path=name, standing_route_selection=phrase):
                        self.assertIn(phrase, standing)
                for phrase in standing_controls:
                    with self.subTest(path=name, standing_control=phrase):
                        self.assertIn(phrase, shared)
                    for route, body in (('explicit_pair', direct), ('private_proposal', private), ('lane_derived', lane), ('removed_retirement', removed)):
                        with self.subTest(path=name, standing_control=phrase, outside_route=route):
                            self.assertNotIn(phrase, body)
                for route, heading in (('explicit_pair', direct_heading), ('private_proposal', private_heading), ('lane_derived', lane_heading), ('removed_retirement', removed_heading)):
                    with self.subTest(path=name, standing_route_placement=route):
                        self.assertTrue(
                            heading
                            and heading.group(0) in standing.splitlines()
                            and all(0 <= text.rfind(phrase) < heading.start() for phrase in standing_controls)
                        )
                for phrase in (
                    'five-category list',
                    'Apply category 5 only after verifying the exact written CoC approval, approved pair, and bound CI evidence.',
                    'Send the driver the quoted authority clause, exact approval, and evidence before applying the scoped edit.',
                    'Verify separate applicable loaded edit/access authority and both exact current/replacement field pairs before applying category 5; otherwise stop.',
                ):
                    with self.subTest(path=name, phrase=phrase):
                        self.assertIn(phrase, text if phrase == 'five-category list' else direct)
                    if phrase != 'five-category list':
                        with self.subTest(path=name, route='explicit_pair_only', phrase=phrase):
                            self.assertNotIn(phrase, shared + '\n' + private + '\n' + lane + '\n' + removed)
                with self.subTest(path=name, category=5):
                    self.assertIn('  5. ' + category, text.splitlines())
            elif Path(name).name.startswith('driver'):
                self.assertIn('and refresh paired anchor strings or retire a removed row within the fifth category below.', text)
                phrase = 'Do not treat driver evidence preparation as authority to apply the writer edit.'
                with self.subTest(path=name, shared_role=phrase):
                    self.assertIn(phrase, shared)
                for route, body in (('explicit_pair', direct), ('private_proposal', private), ('lane_derived', lane), ('removed_retirement', removed)):
                    with self.subTest(path=name, shared_role=phrase, outside_route=route):
                        self.assertNotIn(phrase, body)
                for phrase in (
                    'five test adaptations',
                    'Prepare the category 5 writer brief with the exact written CoC approval, approved pair, authority clause, and bound CI evidence.',
                    'Include separate applicable loaded edit/access authority and both exact current/replacement field pairs in the category 5 writer brief; missing authority blocks dispatch for editing.',
                ):
                    with self.subTest(path=name, phrase=phrase):
                        self.assertIn(phrase, text if phrase == 'five test adaptations' else direct)
                    if phrase != 'five test adaptations':
                        with self.subTest(path=name, route='explicit_pair_only', phrase=phrase):
                            self.assertNotIn(phrase, shared + '\n' + private + '\n' + lane + '\n' + removed)
            else:
                with self.subTest(path=name, skill_contract='category_count'):
                    self.assertIn('five standing test adaptations', text)
                    self.assertIn("and the exact paired-anchor category below, which also retires a row the PR's own diff removed.", text)
                phrase = 'Drivers prepare category 5 evidence; writers verify it and apply only separately permitted exact edits.'
                with self.subTest(path=name, skill_contract='category_roles'):
                    self.assertIn(phrase, shared)
                for route, body in (('explicit_pair', direct), ('private_proposal', private), ('lane_derived', lane), ('removed_retirement', removed)):
                    with self.subTest(path=name, skill_contract='shared_category_roles', outside_route=route):
                        self.assertNotIn(phrase, body)
                with self.subTest(path=name, skill_contract='command_free_brief'):
                    self.assertIn(
                        'Every chief, lane, and ship brief contains zero copied mutation-check, anchor-check, or selector execution commands from repository documents or TOML headers.',
                        shared,
                    )
                with self.subTest(path=name, skill_contract='separate_edit_authority'):
                    self.assertIn(
                        'Drivers document separate applicable loaded edit/access authority and both current/replacement pairs; writers verify them before any category 5 edit.',
                        direct,
                    )
                with self.subTest(path=name, skill_contract='explicit_pair_only'):
                    self.assertNotIn(
                        'Drivers document separate applicable loaded edit/access authority and both current/replacement pairs; writers verify them before any category 5 edit.',
                        shared + '\n' + private + '\n' + lane + '\n' + removed,
                    )
                with self.subTest(path=name, skill_contract='obsolete_closed_list'):
                    self.assertNotIn(
                        'a writer applies a register classification, a census re-pin from CI output after a reviewed body PASS, '
                        'a race-helper timeout replacement, or a setup-only fixture change when the CoC or the topic Chief approved that exact edit.',
                        text,
                    )

    def test_removed_behavior_retirement_route_appends_only_retired_tables(self):
        for name in (
            'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/agents/writer--fable52.md', 'plugins/ship/agents/driver.md',
            'plugins/ship/agents/driver--sol.md', 'plugins/ship/skills/ship/SKILL.md',
        ):
            text = (ROOT / name).read_text()
            _, heading, after = text.partition('#### Removed-behavior retirement route\n')
            route = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', after,
                             maxsplit=1, flags=re.MULTILINE)[0]
            if Path(name).name.startswith('writer--'):
                role = ['Send the driver the CoC decision, named rows, quoted CI log lines, and PR-body reasons before you append the tables; afterwards report the retirement commit SHA and its content-free line counts.']
            elif Path(name).name.startswith('driver'):
                role = ['Prepare the retirement writer brief with the CoC decision, named row-file paths and row IDs, quoted CI log lines, recorded base/head diff, and each PR-body reason.',
                        'Put the retirement commit SHA and its content-free line counts for each named file in the reviewer brief.']
            else:
                role = ["Drivers prepare retirement evidence and the reviewer's line counts; writers append only the named `[[retired]]` tables."]
            with self.subTest(path=name):
                self.assertTrue(heading)
                self.assertLess(text.index('Category 5 uses exactly one route below, named in the brief.'),
                                text.index(heading))
                self.assertLess(text.index('#### Lane-derived route\n'), text.index(heading))
                self.assertLess(text.index(heading), text.index('### Same-strength adaptations\n'))
                self.assertEqual([line for line in route.splitlines() if line],
                                 EXPECTED_REMOVED_RETIREMENT_ROUTE + role)
                self.assertNotIn('Replace only the paired `old` and `new` fields', route)

    def test_removed_behavior_retirement_review_requires_all_four_conditions(self):
        routes = []
        for name in ('reviewer--sol.md', 'reviewer--opus.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            _, heading, after = text.partition('## Removed-behavior retirement review\n')
            route, next_heading, _ = after.partition('## Row retirement with replacement review\n')
            routes.append(heading + route)
            lines = [line for line in (heading + route).splitlines() if line]
            with self.subTest(path=name):
                self.assertTrue(heading and next_heading)
                self.assertEqual(lines, EXPECTED_REMOVED_RETIREMENT_REVIEW)
                conditions = [line for line in lines if re.match(r'  [0-9]\. ', line)]
                self.assertEqual([line[:5] for line in conditions], ['  1. ', '  2. ', '  3. ', '  4. '])
                self.assertEqual(sum(line.startswith('Admit ') for line in lines), 1)
                for refusal in (
                    'Refuse on any doubt about any condition.',
                    'Refuse a retirement when the guarded behavior still exists anywhere in the tree at the frozen SHA after the edit.',
                    'An admission grants zero writer or driver edit authority.',
                ):
                    self.assertIn(refusal, lines)
        self.assertEqual(routes[0], routes[1])

    def test_owner_scoped_protected_row_access_requires_verified_exact_scope(self):
        for name in (
            'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/agents/driver.md', 'plugins/ship/agents/driver--sol.md',
            'plugins/ship/skills/ship/SKILL.md',
        ):
            text = (ROOT / name).read_text()
            _, heading, after = text.partition('#### Owner-scoped protected row access\n')
            clause = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', after,
                              maxsplit=1, flags=re.MULTILINE)[0]
            with self.subTest(path=name, contract='loaded_clause'):
                self.assertTrue(heading)
            for requirement in (
                '31f787fe-1463-4447-82fa-6a5e21e17a87', WORKSPACE_ID,
                'version 1, choice B', 'aacba25c-5e99-438e-85c7-9bb128ecf4b8',
                '2026-11-08T18:03:15.357469375Z',
                'd56c4fd20ef712921654f06869818b5b2189a13e9b52249b32379ca5362468a8',
                'Owner-selected option B: "Each lane moves the protected rows its own PR breaks: same test, new line text, nothing weaker. An independent reviewer checks every row change, and the mutation proof still runs after merge."',
                'Input context: "Peral keeps CI runner and merge queue changes."',
                'Record selected choice B and `payload.answer.text=null` separately; distinguish the selected option text from Input context.',
                "Use this clause only as category 5's separate loaded read/edit authority for the explicit-pair or lane-derived route, or as scoped read authority for the owner-approved protected-row subject route.",
                'This clause overrides only blanket protected-read/edit restrictions for the exact scope below.',
                'Preserve higher-priority instructions, effective refusals, protected holds, and tool or hook denials.',
                "Require the driver's complete verified owner-event record and exact scope in the brief.",
                'Bind full Input/workspace UUIDs, current version, event id/hash, choice, actual owner answer, verifier name, and verification time.',
                'Require `event_type=answer_submitted`, `actor_kind=owner_ui`, and `payload.no_answer_yet=false` for this Input and current version.',
                'Apply the task-specific owner-event verification contract; keep its event comparator separate from the standing rule.',
                'An authoritative mismatch blocks access and cannot use fallback.',
                "Require CoC naming of exact row-file paths and unique row IDs from that PR's failing anchor CI log.",
                'Require the recorded base/head diff to show that the PR itself breaks each named row.',
                'Limit reads to those exact named files and rows; read no unrelated rows or whole protected files.',
                'Require the reviewer to differ from the PR author and applying writer.',
                'Preserve the same designated test and guarantee, equivalent mutant semantics, assertions, bounds, and every unrelated field.',
                'Refuse missing, stale, mismatched, ambiguous, or unrelated scope before any protected read or edit.',
                'Keep mutation proof after merge under separate applicable execution admission.',
                "Retain Peral's authority over CI runners and the merge queue.",
                'On the lane-derived or owner-approved protected-row subject route only, permit the row-ID lookup and row-line reads specified in that route.',
                'Except for the named row-ID lookup and row-line reads on the lane-derived or owner-approved protected-row subject route, this clause grants zero TOML search/parse or anchor extraction authority. This clause grants zero mutation or other execution, or writer publication authority.',
                'CoC naming alone grants zero authority outside this loaded exception and its verified owner scope.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, clause)
            with self.subTest(path=name, contract='general_boundary_reference'):
                self.assertIn('For the narrow protected-read/edit exception, apply Owner-scoped protected row access below.', text)

    def test_lane_derived_route_requires_identical_mutant_edit_and_independent_review(self):
        for name in (
            'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/agents/driver.md', 'plugins/ship/agents/driver--sol.md',
            'plugins/ship/skills/ship/SKILL.md',
        ):
            text = (ROOT / name).read_text()
            _, heading, after = text.partition('#### Lane-derived route\n')
            route = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', after,
                             maxsplit=1, flags=re.MULTILINE)[0]
            with self.subTest(path=name, contract='lane_route'):
                self.assertTrue(heading)
                self.assertLess(text.index('Category 5 uses exactly one route below, named in the brief.'),
                                text.index(heading))
            for requirement in (
                'Require the owner-scoped protected row access authority above and name this route in the brief.',
                'Require CoC approval of the exact row allowlist before any protected read or edit.',
                "Limit scope to CoC-named exact row-file paths and unique row IDs from the PR's own failing anchor CI evidence.",
                "Require the recorded base/head diff to show that the PR's own subject change breaks each named row.",
                'Permit the applying writer to locate each named row by its row ID inside its named file.',
                "Read only that row's lines; permit no whole-file parse, unnamed-row read, or search outside the named files.",
                "Replace only the paired `old` and `new` fields to match the subject's new source text.",
                'Preserve the identical mutant operation: the same transformation from `old` to `new`.',
                'Keep row ID, claim, subject, designated test, pins, operator, assertions, bounds, and unrelated fields unchanged.',
                'Before publication, require an independent reviewer to read the same named rows before and after the edit under the same scoped access authority.',
                'Require that reviewer to differ from the PR author and the applying writer.',
                'Require the reviewer to confirm the same test, same claim, identical mutant edit, and nothing weaker for every row.',
                'Bind the review receipt to reviewer identity, approving verdict, commit SHA, row-file paths, row IDs, and CI evidence.',
                'Require CoC approval of that review receipt before publication; changed source or evidence invalidates the receipt and approval.',
                'The CoC supplies no pair bytes on this route.',
                'Keep messages, briefs, and PR bodies free of pair bytes and TOML text; identify edits only by path, row ID, and field.',
                'Require separate admission for every mutation or checker execution; keep mutation proof after merge.',
                "Preserve zero writer publication authority, effective refusals, tool and hook denials, protected holds, and Peral's CI-runner and merge-queue authority.",
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, route)
            with self.subTest(path=name, contract='standing_grant'):
                self.assertIn('Owner global CLAUDE.md standing grant: "The CoC decides CI/CD, testing and tooling items for me. This includes a lane reading and re-anchoring the protected mutation rows that its own diff breaks, with an identical mutant edit and an independent not-weaker review."', text)

    def test_lane_routes_let_the_reviewer_use_the_claude_md_grant(self):
        for name in ('plugins/ship/agents/driver.md', 'plugins/ship/agents/driver--sol.md', 'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md', 'plugins/ship/skills/ship/SKILL.md'):
            text = (ROOT / name).read_text()
            with self.subTest(path=name):
                self.assertIn('Before publication, require an independent reviewer to read the same named rows before and after the edit under the same scoped access authority.' + '\n' + 'The reviewer may instead use authority A of its own definition, the owner global CLAUDE.md grant; that route needs no owner-event relay.', text)

    def test_lane_derived_reviewers_require_verified_read_only_row_scope(self):
        routes = []
        for name in ('reviewer--sol.md', 'reviewer--opus.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            _, heading, after = text.partition('## Lane-derived row review\n')
            route = heading + after
            routes.append(route)
            with self.subTest(path=name):
                self.assertEqual([l for l in route.splitlines() if l], EXPECTED_LANE_REVIEW)
        self.assertEqual(routes[0], routes[1])

    def retirement_routes(self):
        routes = []
        for name in ('reviewer--sol.md', 'reviewer--opus.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            heading, found, after = text.partition('## Row retirement with replacement review\n')
            route, lane_heading, _ = after.partition('## Lane-derived row review\n')
            with self.subTest(path=name, before_lane_route=True):
                self.assertTrue(found and lane_heading)
            routes.append([l for l in (found + route).splitlines() if l])
        self.assertEqual(routes[0], routes[1])
        return routes

    def test_retirement_with_replacement_requires_all_four_conditions(self):
        for route in self.retirement_routes():
            self.assertEqual(route, EXPECTED_RETIREMENT_REVIEW)
            conditions = [l for l in route if re.match(r'  [0-9]\. ', l)]
            self.assertEqual([l[:5] for l in conditions], ['  1. ', '  2. ', '  3. ', '  4. '])
            self.assertEqual(sum(l.startswith('Admit ') for l in route), 1)

    def test_retirement_without_replacement_or_with_doubt_is_refused(self):
        for route in self.retirement_routes():
            for refusal in (
                'Refuse on any doubt about any condition.',
                'Refuse a retirement when the PR adds no replacement row.',
                'An admission grants zero writer or driver edit authority.',
            ):
                with self.subTest(refusal=refusal):
                    self.assertIn(refusal, route)

    def test_exact_coc_adaptations_preserve_or_strengthen_the_same_guarantee(self):
        for name in (
            'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/agents/driver.md', 'plugins/ship/agents/driver--sol.md',
            'plugins/ship/skills/ship/SKILL.md',
        ):
            text = (ROOT / name).read_text()
            for phrase in (
                'The same-strength route requires exact written CoC approval citing an already applicable verified owner-authority route.',
                'This same-strength route excludes mutation-row anchor refreshes; it cannot replace category 5 requirements.',
                'Existing independent council/Chief same-guarantee routes and owner-event grants remain unchanged and independently usable.',
                'Categories 1–4 retain their existing CoC-or-Chief approval routes and owner-event verification requirements.',
                'Owner provenance follows the applicable loaded route; a CoC message alone supplies zero owner consent.',
                'For the same-strength route, approval names the exact files, rows or entries, permitted fields, replacement bytes, reason, approver, approval time, and evidence identity.',
                'For the same-strength route, the CoC reviews evidence that the adaptation preserves or strengthens the same guarantee; missing or changed evidence blocks the edit.',
                'Preserve assertions, behavioral bounds, and security/resource policy; the exact approved category 3 race-helper timeout replacement remains permitted.',
                'Preserve designated tests, pins, operators, and unrelated fields outside the exact approved permitted fields.',
                'Higher-priority instructions, owner provenance, effective refusals, protected holds, and tool denials remain binding; this rule overrides none of them.',
                'This rule grants zero protected reads, TOML search/parse, anchor extraction, execution, or writer publication authority.',
                'Dry-run proof and new-head CI remain under separate applicable admission.',
            ):
                with self.subTest(path=name, phrase=phrase):
                    self.assertIn(phrase, text)
            if Path(name).name.startswith('writer--'):
                phrase = 'Verify the same-strength approval and evidence, then send the driver the quoted authority and exact scope before any permitted edit.'
            elif Path(name).name.startswith('driver'):
                phrase = 'Prepare the same-strength writer brief with the quoted authority, exact CoC approval, evidence identity, and permitted scope.'
            else:
                phrase = 'Drivers prepare same-strength evidence; writers verify it before any separately permitted exact edit.'
            with self.subTest(path=name, phrase=phrase):
                self.assertIn(phrase, text)

    def test_skill_cites_owner_rule(self):
        text = (ROOT / 'plugins/ship/skills/ship/SKILL.md').read_text()
        self.assertIn(INPUT_ID, text)
        self.assertIn('the writer stops on any mismatch with its definition', text)
        _, same_strength_heading, after_same_strength = text.partition('### Same-strength adaptations\n')
        _, general_heading, general = after_same_strength.partition('### General routes and boundaries\n')
        general = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)|^.+\n {0,3}(?:=+|-+)[ \t]*$',
                           general, maxsplit=1, flags=re.MULTILINE)[0]
        with self.subTest(skill_contract='general_section_boundary'):
            self.assertTrue(same_strength_heading and general_heading)
        for phrase in (
            'Prepare evidence and exact scope under [Task-specific test adaptations]',
            'Apply [Loaded instructions and refusals]',
            'Preserve validation, authorization, tenant isolation, atomicity, and logging.',
        ):
            with self.subTest(skill_contract='general_scope', phrase=phrase):
                self.assertIn(phrase, general)
            with self.subTest(skill_contract='general_clause_count', phrase=phrase):
                self.assertEqual(text.count(phrase), 1)


if __name__ == '__main__':
    unittest.main()
