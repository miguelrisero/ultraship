"""Static instruction contracts only; these checks do not execute agent behavior."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
INPUT_ID = '32c223a4-6bd9-43d1-b049-19a3990d2379'
WORKSPACE_ID = 'b8fed386-cf11-40fe-b14f-425e6331ee41'
EVENT_ID = '1c2e4bf5-10c2-4cb2-9abc-ab86ba945fc8'


class ApprovedTestAdaptationsTests(unittest.TestCase):
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
            shared = text
            for heading, body in sorted(
                ((direct_heading, direct), (private_heading, private)),
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
                'Pairs from a private derivation stay in the private-proposal route.',
            )
            for phrase in (
                category,
                *route_selection_clauses,
                'Categories 1–4 retain their existing CoC-or-Chief approval routes and owner-event verification requirements.',
                'Category 5 requires separate applicable loaded edit/access authority before any writer edit; missing authority blocks editing.',
                'Written approval and CI evidence grant zero protected access and do not replace applicable loaded edit/access authority.',
                'The PR author product diff supplies supporting evidence only at the CI-named subject file.',
                'The CoC reviews the same-operation, same-claim reason; product diff text alone cannot establish equivalent mutant semantics.',
                'Each approved row has an exact committed row-file path, unique row ID, and CI-named subject file.',
                'PR ownership requires the recorded base/head diff and exact approved row allowlist; a subject name alone is insufficient.',
                'Evidence binds the repository, PR, base SHA, author head SHA, tested merge SHA/tree, CI run ID, attempt, and job ID/name.',
                'The tested merge must contain the recorded base and author head; changed evidence invalidates the approval and applicable GO.',
                'Dry-run proof and CI at the new head require separate admission; this adaptation authorizes no mutation command execution.',
                'Only the exact approved paired `old` and `new` fields may change under category 5.',
                'Row identity, claims, subjects, designated tests, pins, operators, assertions, bounds, and unrelated fields remain unchanged under category 5.',
                'Missing, ambiguous, stale, mismatched, or unlawfully obtained evidence blocks the edit.',
                'Owner provenance, effective refusals, protected holds, and zero writer publication authority remain binding.',
                'This adaptation grants no TOML search or parse authority, protected reads, or anchor extraction.',
            ):
                with self.subTest(path=name, shared_control=phrase):
                    self.assertIn(phrase, shared)
                for route, body in (('explicit_pair', direct), ('private_proposal', private)):
                    with self.subTest(path=name, shared_control=phrase, outside_route=route):
                        self.assertNotIn(phrase, body)
            for phrase in route_selection_clauses:
                for route, heading in (('explicit_pair', direct_heading), ('private_proposal', private_heading)):
                    with self.subTest(path=name, route_selection_before=route, phrase=phrase):
                        self.assertTrue(heading and 0 <= text.rfind(phrase) < heading.start())
            for phrase in (
                'Category 5 requires written CoC approval supplying both exact replacement strings for each CI-named approved row.',
                'Category 5 approval supplies exact current and replacement bytes for both `old` and `new` fields in each approved row.',
                'Existing CI identifiers and quoted evidence suffice; this adaptation requires no producer, artifact, or digest.',
                'Evidence includes the quoted job log line and the job log URL where supplied.',
            ):
                with self.subTest(path=name, route='explicit_pair', phrase=phrase):
                    self.assertIn(phrase, direct)
                with self.subTest(path=name, route='explicit_pair_only', phrase=phrase):
                    self.assertNotIn(phrase, shared + '\n' + private)
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
                    self.assertNotIn(phrase, shared + '\n' + direct)
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
                    '- Every other control stays: caller-owned TERM escalation only, no D1160 commands, no mutation TOML search, the protected-path rules, and zero writer push authority.',
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
                    for route, body in (('explicit_pair', direct), ('private_proposal', private)):
                        with self.subTest(path=name, standing_control=phrase, outside_route=route):
                            self.assertNotIn(phrase, body)
                for route, heading in (('explicit_pair', direct_heading), ('private_proposal', private_heading)):
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
                            self.assertNotIn(phrase, shared + '\n' + private)
                with self.subTest(path=name, category=5):
                    self.assertIn('  5. ' + category, text.splitlines())
            elif Path(name).name.startswith('driver'):
                phrase = 'Do not treat driver evidence preparation as authority to apply the writer edit.'
                with self.subTest(path=name, shared_role=phrase):
                    self.assertIn(phrase, shared)
                for route, body in (('explicit_pair', direct), ('private_proposal', private)):
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
                            self.assertNotIn(phrase, shared + '\n' + private)
            else:
                with self.subTest(path=name, skill_contract='category_count'):
                    self.assertIn('five standing test adaptations', text)
                phrase = 'Drivers prepare category 5 evidence; writers verify it and apply only separately permitted exact edits.'
                with self.subTest(path=name, skill_contract='category_roles'):
                    self.assertIn(phrase, shared)
                for route, body in (('explicit_pair', direct), ('private_proposal', private)):
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
                        shared + '\n' + private,
                    )
                with self.subTest(path=name, skill_contract='obsolete_closed_list'):
                    self.assertNotIn(
                        'a writer applies a register classification, a census re-pin from CI output after a reviewed body PASS, '
                        'a race-helper timeout replacement, or a setup-only fixture change when the CoC or the topic Chief approved that exact edit.',
                        text,
                    )

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
