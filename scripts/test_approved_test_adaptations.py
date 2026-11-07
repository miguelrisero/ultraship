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
                'You may return a frozen source checkpoint to request a test GO.',
                'Report the exact worktree, branch, base/HEAD SHAs, changed paths, file hashes, and complete diff digest.',
                'Include staged, unstaged, and relevant untracked content in the path inventory, file hashes, and complete scoped content fingerprint.',
                'A tracked Git diff alone omits untracked content.',
                'Require a new checkpoint and fresh applicable GO after any source change.',
                'List pending checks and identify every unexecuted proof.',
                'Make no final completion or pass claim in this intermediate request.',
                'Keep all applicable final test and check requirements binding.',
                'A checkpoint grants zero test execution authority; wait for a GO permitted by the brief and loaded instructions.',
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
            for phrase in (
                category,
                'Categories 1–4 retain their existing CoC-or-Chief approval routes and owner-event verification requirements.',
                'Category 5 requires written CoC approval supplying both exact replacement strings for each CI-named approved row.',
                'Category 5 approval supplies exact current and replacement bytes for both `old` and `new` fields in each approved row.',
                'Category 5 requires separate applicable loaded edit/access authority before any writer edit; missing authority blocks editing.',
                'Written approval and CI evidence grant zero protected access and do not replace applicable loaded edit/access authority.',
                'The PR author product diff supplies supporting evidence only at the CI-named subject file.',
                'The CoC reviews the same-operation, same-claim reason; product diff text alone cannot establish equivalent mutant semantics.',
                'Each approved row has an exact committed row-file path, unique row ID, and CI-named subject file.',
                'PR ownership requires the recorded base/head diff and exact approved row allowlist; a subject name alone is insufficient.',
                'Evidence binds the repository, PR, base SHA, author head SHA, tested merge SHA/tree, CI run ID, attempt, and job ID/name.',
                'Evidence includes the quoted job log line and the job log URL where supplied.',
                'Existing CI identifiers and quoted evidence suffice; this adaptation requires no producer, artifact, or digest.',
                'The tested merge must contain the recorded base and author head; changed evidence invalidates the approval and applicable GO.',
                'Dry-run proof and CI at the new head require separate admission; this adaptation authorizes no mutation command execution.',
                'Only the exact approved paired `old` and `new` fields may change under category 5.',
                'Row identity, claims, subjects, designated tests, pins, operators, assertions, bounds, and unrelated fields remain unchanged under category 5.',
                'Missing, ambiguous, stale, mismatched, or unlawfully obtained evidence blocks the edit.',
                'Owner provenance, effective refusals, protected holds, and zero writer publication authority remain binding.',
                'This adaptation grants no TOML search or parse authority, protected reads, or anchor extraction.',
            ):
                with self.subTest(path=name, phrase=phrase):
                    self.assertIn(phrase, text)
            with self.subTest(path=name, obsolete_source=True):
                self.assertNotIn(
                    'Use replacement text solely from CI `mutation-anchors` output bound to the tested head and exact approved row.',
                    text,
                )
            if Path(name).name.startswith('writer--'):
                for phrase in (
                    'five-category list',
                    'Apply category 5 only after verifying the exact written CoC approval, approved pair, and bound CI evidence.',
                    'Send the driver the quoted authority clause, exact approval, and evidence before applying the scoped edit.',
                    'Verify separate applicable loaded edit/access authority and both exact current/replacement field pairs before applying category 5; otherwise stop.',
                ):
                    with self.subTest(path=name, phrase=phrase):
                        self.assertIn(phrase, text)
                with self.subTest(path=name, category=5):
                    self.assertIn('  5. ' + category, text.splitlines())
            elif Path(name).name.startswith('driver'):
                for phrase in (
                    'five test adaptations',
                    'Prepare the category 5 writer brief with the exact written CoC approval, approved pair, authority clause, and bound CI evidence.',
                    'Do not treat driver evidence preparation as authority to apply the writer edit.',
                    'Include separate applicable loaded edit/access authority and both exact current/replacement field pairs in the category 5 writer brief; missing authority blocks dispatch for editing.',
                ):
                    with self.subTest(path=name, phrase=phrase):
                        self.assertIn(phrase, text)
            else:
                with self.subTest(path=name, skill_contract='category_count'):
                    self.assertIn('five standing test adaptations', text)
                with self.subTest(path=name, skill_contract='category_roles'):
                    self.assertIn(
                        'Drivers prepare category 5 evidence; writers verify it and apply only separately permitted exact edits.',
                        text,
                    )
                with self.subTest(path=name, skill_contract='separate_edit_authority'):
                    self.assertIn(
                        'Drivers document separate applicable loaded edit/access authority and both current/replacement pairs; writers verify them before any category 5 edit.',
                        text,
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
