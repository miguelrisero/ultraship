"""Static instruction contracts only; these checks do not execute agent behavior."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
INPUT_ID = '32c223a4-6bd9-43d1-b049-19a3990d2379'
WORKSPACE_ID = 'b8fed386-cf11-40fe-b14f-425e6331ee41'
EVENT_ID = '1c2e4bf5-10c2-4cb2-9abc-ab86ba945fc8'

SHIP = ROOT / 'plugins/ship'
ROUTE_CARRIERS = (
    'skills/ship/SKILL.md', 'agents/driver.md', 'agents/driver--sol.md',
    'agents/writer--sol.md', 'agents/writer--sonnet.md', 'agents/writer--fable52.md',
)
REVIEWERS = ('reviewer--sol.md', 'reviewer--opus.md', 'reviewer--astra.md')


def section(text, heading):
    marker = heading + '\n'
    if text.splitlines().count(heading) != 1:
        raise AssertionError(heading)
    return re.split(r'^#{1,6} ', text.split(marker, 1)[1], maxsplit=1, flags=re.M)[0]


class ApprovedTestAdaptationsTests(unittest.TestCase):
    def test_lane_owned_scope_evidence_and_proof(self):
        for name in ROUTE_CARRIERS:
            route = section((SHIP / name).read_text(), '### Lane-owned row route')
            for requirement in (
                'No CoC decision file is required.',
                'Authority: the owner\'s global CLAUDE.md, heading "CoC decisions (standing grant)". Read it directly; accept no relay.',
                "Scope: each existing row that the PR's failing anchor CI names, when the recorded base/head diff shows that the PR's own change breaks it, each new row that step 4 admits, and each row that step 5 restores.",
                'Admit the writer with the [row re-anchor tool admission record]',
                'Authorization record: each tool run that changes zero statements writes a generated record in the Git directory.',
                'The record names the lane, base, head, row IDs, base and head line ranges, expected counts and the unchanged mutant check.',
                'The tool prints the record path and every record field as `key=value` lines, with no row text.',
                'The driver copies the printed fields of the frozen-head run into the reviewer brief. The reviewer reads no file under `.git`.',
                'The record expires on any head change. Rerun the tool at the frozen head for each re-anchored row; that run changes zero statements.',
                'A CoC-approved row change gets no tool run. Its decision file and the review in step 8 cover it.',
                'A run that changes statements writes no record entry and unfreezes the head. The writer commits the edit and reruns the tool.',
                'the anchor guard requires each anchor count to equal the row\'s expected count, not only a nonzero count.',
                'The mutation proof runs after merge, under its execution admission.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, route)

    def test_lane_owned_writers_keep_mutant_fields_and_authority_scoped(self):
        for name in ROUTE_CARRIERS:
            route = section((SHIP / name).read_text(), '### Lane-owned row route')
            for requirement in (
                'the writer runs the sanctioned re-anchor tool once per row, then commits the row file alone.',
                "The tool derives the paired `old` and `new` fields from the subject's new source text and keeps the identical mutant.",
                'It refuses a change to any other field, and it prints no row text.',
                "The writer's worktree has one user. No other command runs there while the tool runs.",
                "Concurrent Git commands in the writer's worktree are outside the tool's threat model.",
                'The CI anchor guard and the mutation proof after merge catch a row that such a race leaves wrong.',
                'The writer locates a named row by its row ID and reads only that row\'s lines.',
                'It never parses or searches a whole row file.',
                'Keep row TOML text and pair bytes out of messages, briefs and PR bodies. Name each edit by path, row ID and field.',
                'The driver applies zero protected edits. Writers keep zero publication authority.',
                "Send these rows to the CoC: a new or changed mutant on an existing row, a changed designated test, a retirement without a replacement, and a row that the PR's own diff does not break.",
                'Not weaker means the same test and the same mutant intent with the same claim or a CoC-approved narrowed claim, or a replacement that guards as tightly.',
                'A lane may narrow the claim of a row that its own PR breaks, under a CoC approval.',
                'A narrowed claim keeps the same designated test and the same mutant. It claims less than the old claim and nothing that the test does not prove.',
                'Send a widened or otherwise changed claim to the CoC. The CoC approves it only with a current task-specific owner event.',
                'A CoC approval is a frozen decision file named by absolute path and SHA256.',
                'It binds the row ID, the source commit, the fields and their replacement values.',
                "The writer verifies its SHA256 and bindings before the edit. The driver verifies them again at the frozen head and records the result in the reviewer brief.",
                'The writer applies only those fields with native Edit and `replace_all=false`, then commits the row file alone.',
                'Step 8 reviews that row, and a follow-up row guards any new code.',
                'The CoC audits a 10% sample of lane-owned row changes.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, route)

    def test_lane_owned_retirement_and_creation_keep_replacement_coverage(self):
        for name in ROUTE_CARRIERS:
            route = section((SHIP / name).read_text(), '### Lane-owned row route')
            for requirement in (
                'when the PR deletes the guarded code, the writer deletes the row table and runs `retire-rows.py`.',
                'The script appends one `[[retired]]` table per row with the row ID, the reason and the `replacement` row ID.',
                'The replacement row guards the new code.',
                'The anchor guard fails a removed row without a `[[retired]]` entry.',
                "the writer adds rows for the PR's own new code, each with a claim, a designated test, a subject and a mutant.",
                'Each new row ID must be absent at the base; the recorded base/head diff shows it. A new row needs no failing CI.',
                'A test-only follow-up PR may also add rows for code that a named earlier merged PR added, when the CoC grants it.',
                "Its diff changes no subject code, and the parent's merge commit is an ancestor of the recorded base.",
                "Its PR body names the parent PR URL, the parent's full merge commit SHA and the CoC decision file by absolute path and SHA256.",
                'Each such row keeps the identical mutant edit that the decision file names and passes the review in step 8.',
                'The driver opens the PR as a draft, so CI runs and the reviewer admission record can name the PR.',
                'Opening the draft and pushing to it publish nothing. Marking it ready, a push to a ready PR and any merge are publication.',
                'The driver marks the draft ready only after the review in step 8 passes at the exact head.',
                'one independent reviewer confirms that every changed, retired, restored or added row is not weaker.',
                'The reviewer differs from the PR author and the writer, and reads rows only under its [reviewer admission record]',
                'The driver supplies read-only checkouts at the base and the frozen head. The admission record lists the row file in each checkout.',
                'The writer reports the base and head line ranges of each retired or CoC-approved row. The driver copies them into the reviewer brief.',
                'For a row file absent at the base, the driver first verifies the base with `git cat-file -e <base SHA>^{commit}`.',
                'From the repository root, the driver records that `git ls-tree --name-only <base SHA> -- <repository-relative path>` exits 0 and prints nothing.',
                'The driver then admits only the head copy.',
                'Any later push to the PR needs a new review at the pushed head. Return a ready PR to draft before that push.',
                'Mark it ready again only after the new review passes.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, route)

    def test_lane_owned_route_and_review_copies_match(self):
        for names, heading in ((ROUTE_CARRIERS, '### Lane-owned row route'),
                               ([f'agents/{name}' for name in REVIEWERS], '## Lane-owned row review')):
            canonical = section((SHIP / names[0]).read_text(), heading).rstrip('\n')
            for name in names[1:]:
                with self.subTest(path=name):
                    copy = section((SHIP / name).read_text(), heading).rstrip('\n')
                    self.assertEqual(canonical, copy.replace('](../skills/ship/references/', '](references/'))

    def test_lane_owned_review_pins_independence_scope_and_all_row_verdicts(self):
        for name in REVIEWERS:
            text = (SHIP / 'agents' / name).read_text()
            route = section(text, '## Lane-owned row review')
            tools = [line for line in text.split('\n---\n', 1)[0].splitlines() if line.startswith('tools:')]
            self.assertEqual(tools, ['tools: Read, Grep, Glob, LSP, WebFetch, WebSearch'])
            for requirement in (
                'Use this review when the brief names the lane-owned row route.',
                'Authority: the owner\'s global CLAUDE.md, heading "CoC decisions (standing grant)". Read it directly; accept no relay.',
                "Read rows only under the driver's reviewer admission record. Read only the named row lines at the named commits.",
                'You differ from the PR author and the writer.',
                'For each re-anchored row, confirm the same test, the same claim and the same mutant intent at the base and the frozen head.',
                'Confirm that the paired `old` and `new` fields are the only changed fields of that row.',
                'Use the record fields that the brief copies from the tool output. Read no file under `.git`.',
                'Confirm that those fields name the frozen head, the row ID, the expected count, an unchanged mutant and zero changed statements.',
                'For each retired row, confirm that the PR deletes the guarded code and that its `[[retired]]` table names a `replacement` row.',
                'Confirm that the replacement row guards the new code at least as tightly as the retired row guarded the old code.',
                'Read each row in the base checkout and the frozen-head checkout that the admission record lists, at the base and head line ranges.',
                'For each added row, grep the base copy of the row file for its ID and confirm zero matches.',
                'When the brief records the verified base commit and a root-level `git ls-tree` result with exit status 0 and empty output, use that proof in place of the grep.',
                'Confirm its claim, designated test, subject and mutant, and that the test detects the claimed violation.',
                'For an added row in a test-only follow-up PR, confirm that the PR changes no subject code and that the mutant matches the CoC decision file that the brief names.',
                'For a CoC-approved row change, match each applied value to the decision file that the brief names by path and SHA256.',
                "Use that file only when the brief records the driver's SHA256 and binding check at the frozen head.",
                'Confirm that no other field changed and that the row is not weaker.',
                'Return a blocking finding for an unapproved changed claim, mutant or test, or a weaker row. The CoC decides those rows.',
                'For a narrowed claim, confirm the same designated test and mutant at the base and the frozen head, that the claim keeps only part of the base claim, and that the test proves all of it.',
                'A widened or otherwise changed claim also needs a current task-specific owner event, which the CoC obtains.',
                'Report only paths, row IDs, fields and content-free findings. Quote no row text.',
                'You keep zero edit, execution and publication authority.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, route)

    def test_lane_owned_restore_contract(self):
        restore = (
            "5. Restore: the writer returns rows that only the lane's own unmerged commits changed to their bytes at the merge base.\n"
            '   A restored row needs no failing CI report, so a row that the starting head deletes stays in scope.\n'
            '   Its evidence is the merge-base diff and the tool fields `starting_lines`, `base_lines` and `restoration_lines`.\n'
            '   When a lane commit changed only those rows, the writer runs a plain `git revert` of that commit.\n'
            '   When it also changed other lines, the writer uses native Edit only for rows that exist at the starting head, and keeps the other edits.\n'
            '   A row that such a mixed lane commit deleted leaves the restore route.\n'
            '   That row follows the re-anchor route or goes to the CoC.\n'
            '   The writer commits the restoration alone. Then it runs the re-anchor tool on each restored row.\n'
            '   That run passes the merge base as `--base` and the restoration commit as `--restoration`.\n'
            '   The tool binds the restoration commit and its own parent, the starting head. A later commit never moves that parent.\n'
            '   The tool refuses unless each restored row equals the merge base byte for byte and the rest of the commit equals the starting head.\n'
            '   Only blank separator lines between tables, outside every row, may return with a restored row. Every other byte stays exact.\n'
            '   It also refuses a row ID that is not unique, and it prints both results and `insert_after` as `key=value` lines.\n'
            '   Any byte difference leaves the restore route. That row follows the re-anchor route or goes to the CoC.\n'
            '   The driver copies the lane commits that changed each row file after the merge base into the reviewer brief.\n'
            "   The driver names the verified merge base in the reviewer brief. The reviewer refuses unless the record's base equals it.\n"
            '   The reviewer matches every restored row ID in the record to the approved scope before publication.\n'
            '6. Authorization record:'
        )
        for name in ROUTE_CARRIERS:
            with self.subTest(path=name):
                route = section((SHIP / name).read_text(), '### Lane-owned row route')
                self.assertIn('\n' + restore, route)
                self.assertIn(
                    '   The record names the lane, base, head, row IDs, base and head line ranges, expected counts and the unchanged mutant check.\n'
                    '   A restore entry also names the restoration commit, its parent, the three row ranges and `insert_after`.\n',
                    route,
                )
                self.assertIn(
                    '   The record expires on any head change. Rerun the tool at the frozen head for each re-anchored row; that run changes zero statements.\n'
                    '   On the restore route, that rerun keeps `--restoration` and prints `changed_statements=0`.\n',
                    route,
                )
        review = (
            'Confirm that the replacement row guards the new code at least as tightly as the retired row guarded the old code.\n'
            'For each restored row, confirm from the copied record fields `restoration_base_equal=true`, `restoration_outside_equal=true` and `changed_statements=0`.\n'
            'Confirm that `restoration` and `restoration_parent` match the brief, and that `starting_lines` is `null` for a row that the starting head deletes.\n'
            "Refuse unless the record's base equals the verified merge base that the brief names.\n"
            'Group the restored rows by restoration commit and row file. Match every restored row ID to the approved scope.\n'
            'Confirm that restored_rows in each entry equals the number of approved row IDs in its group.\n'
            'Refuse a restored row outside that scope.\n'
            "Confirm from the brief's commit list that only the lane's own unmerged commits changed the row file after the merge base.\n"
            'Read the row lines at the merge base and the frozen head. Confirm that they are equal, or that only a re-anchor changed the paired fields.\n'
        )
        for name in REVIEWERS:
            with self.subTest(path=name):
                text = (SHIP / 'agents' / name).read_text()
                self.assertIn(review, section(text, '## Lane-owned row review'))
        decisions = (SHIP / 'skills/ship/references/owner-decisions.md').read_text()
        admission = section(decisions, '## Row re-anchor tool admission record')
        command = next(line for line in admission.splitlines() if line.startswith('Use exactly '))
        self.assertIn(
            command + '\nOn the restore route, append ` --restoration <commit>` with the full restoration commit SHA.\n',
            admission,
        )
        self.assertIn(
            '\n```\nOn the restore route, write `none` for the CI run, count and expected values when the starting head deletes the row.\n',
            section(decisions, '## Row re-anchor tool brief'),
        )

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
                'A CoC decision never covers product, billing, security-policy, architecture, resource, host, or spend bounds;',
                'The fixed-coordinate comparator applies only to categories 1–4 in this standing owner rule.',
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
        self.assertIn('For categories 1–4, the driver puts the Input ID and workspace ID in the writer brief.', text)
        self.assertIn('and the [lane-owned row route](#lane-owned-row-route) below.', text)
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


class ScopedDecisionRouteTests(unittest.TestCase):
    ship = ROOT / 'plugins/ship'
    reference = ship / 'skills/ship/references/owner-decisions.md'
    lanes = ('driver.md', 'driver--sol.md', 'writer--sol.md', 'writer--sonnet.md',
             'writer--fable52.md')
    reviewers = ('reviewer--sol.md', 'reviewer--opus.md')
    skill = ship / 'skills/ship/SKILL.md'

    def check_route(self, heading, clauses):
        marker = f'## {heading}\n'
        text = self.reference.read_text()
        self.assertEqual(text.count(marker), 1)
        section = text.split(marker, 1)[1].split('\n## ', 1)[0]
        for clause in clauses:
            with self.subTest(clause=clause):
                self.assertIn(clause, section)

    def test_main_row_repair_requires_exact_causal_scope_and_separate_gates(self):
        self.check_route('Standalone main-row repair', (
            'only to future briefs after verified runtime adoption',
            'Apply it outside the lane-owned row route.',
            'Require a repair-only lane',
            'read `~/.claude/CLAUDE.md` directly under `CoC decisions (standing grant)`',
            'clause for adapting rows when a PR makes the stored mutant impossible to apply',
            'follow-up row for new code and independent not-weaker review',
            'frozen CoC decision to identify this repair as the follow-up for the named breaking PR under that grant',
            'accept zero relay and require zero per-row owner events',
            'CoC-frozen decision file by absolute path and SHA256',
            'exact repair lane and branch, and repair PR URL when assigned',
            'full main and pre-edit commit and tree identities',
            'earlier breaking PR, full merged commit SHA, and pre-merge main SHA',
            'each exact stored row ID, canonical row file, subject file, and approved line extent',
            'only whole-line grep for the exact stored `id = "<ID>"` line',
            'Read only the approved row extent, from its `[[` header to the line before the next table',
            'met its expected count before the breaking commit',
            'counts zero at that commit and on the bound main',
            'source evidence that the named merge caused the zero count',
            'bound pre-merge main and merged commit to show that the breaking PR changed the guarded code itself',
            'positive evidence that this code change made the stored mutant impossible to apply at the guarded site',
            'frozen decision to bind this evidence to the follow-up under the owner standing grant',
            'A zero count alone supplies zero repair authority',
            'Keep the row pending after a hook refusal',
            'Ask the driver for a permitted route under the protected row rules',
            'Change only `old` and `new`',
            'Preserve the identical mutant operation',
            'reviewer who differs from the PR author and the applying writer',
            'before any reviewer row read',
            'the same guarantee for every row',
            'Require a CoC-approved frozen review receipt before publication',
            'Bind its path and SHA256 to the decision file path and SHA256',
            'Recheck those bindings and the publication head before publishing',
            'separate applicable execution admission',
            'Preserve all other routes, higher-priority instructions, effective refusals, hook and tool denials',
        ))
        for path in (self.skill, *(self.ship / 'agents' / name for name in self.lanes + self.reviewers)):
            with self.subTest(path=path):
                self.assertIn('owner-decisions.md#standalone-main-row-repair', path.read_text())
        for name in self.reviewers:
            with self.subTest(reviewer=name):
                text = (self.ship / 'agents' / name).read_text()
                self.assertIn('in place of the lane-owned row review only for its exact frozen scope', text)
                self.assertIn('Require protected row admission separately from the CoC decision', text)
        astra = (self.ship / 'agents/reviewer--astra.md').read_text()
        self.assertNotIn('owner-decisions.md#standalone-main-row-repair', astra)

    def test_main_row_repair_routes_retired_rows_to_separate_creation(self):
        self.check_route('Standalone main-row repair', (
            'Require an active row at the bound main commit.',
            'Refuse an existing `[[retired]]` row on this same-row route.',
            'Preserve the retirement record.',
            'Use the [lane-owned row route](../SKILL.md#lane-owned-row-route) for its replacement row.',
            'Require a new row ID and separate creation authority for the replacement.',
        ))

    def test_main_row_repair_requires_proof_of_earlier_reviewed_disposition_before_edit(self):
        self.check_route('Standalone main-row repair', (
            'Require one disposition for each row: a landed designated-test change or mutant adaptation under that grant, or a CoC decision receipt.',
            'For a landed disposition, require the disposition record to cite the landed row change and its CoC decision.',
            'For a landed disposition, require a receipt for the independent not-weaker review of that disposition.',
            'For a landed disposition, require that reviewer to differ from the breaking PR author and the person who applied the disposition.',
            'For a landed disposition, bind the review receipt to the reviewer, approving verdict, exact disposition, and commit the reviewer checked.',
            'For a landed disposition, verify that the reviewed disposition is the one that landed for the named row.',
            'Record the disposition and its evidence references in the frozen edit decision, with the receipt path and SHA256 for a CoC receipt.',
            'Bind them to the full breaking commit SHA, the exact stored row ID, and the exact follow-up edit.',
            'Verify those bindings and the recorded evidence before the edit. Refuse a missing or mismatched disposition, receipt or landed-disposition review.',
            'A zero count alone supplies zero repair authority. A disposition label supplies zero proof.',
            'accept zero relay and require zero per-row owner events',
        ))

    def test_main_row_repair_accepts_coc_receipt_as_disposition(self):
        self.check_route('Standalone main-row repair', (
            'Require one disposition for each row: a landed designated-test change or mutant adaptation under that grant, or a CoC decision receipt.',
            "A CoC decision receipt is the disposition only when the breaking change is not the repair lane's own diff and no landed disposition exists.",
            'The receipt states that it is the disposition and names the row ID, the breaking commit and the paired-field re-anchor.',
            'The receipt also records the evidence that no landed disposition exists for the row in every commit from the breaking commit through the bound main commit.',
            'It names that range by the full breaking commit SHA and the full bound main SHA.',
            'Before publication, recheck that range through the current main SHA. Record that SHA and the result in a separate note beside the frozen receipt digest. A disposition that landed after the bound main commit invalidates the receipt.\n'
            'The receipt itself stays unchanged.',
            'Name the receipt by absolute path and SHA256. Verify the digest before any protected access.',
            'A CoC decision receipt needs no landed disposition and no prior disposition review.',
            'For a CoC decision receipt, the independent repair review below is the one not-weaker review.',
            'That reviewer also differs from the breaking PR author.',
            'For a CoC decision receipt, require the independent repair review below before publication.',
            'Record the disposition and its evidence references in the frozen edit decision, with the receipt path and SHA256 for a CoC receipt.',
            'Verify those bindings and the recorded evidence before the edit. Refuse a missing or mismatched disposition, receipt or landed-disposition review.',
        ))

    def test_ordinary_file_checkpoint_binds_literal_scope_and_unchanged_source(self):
        self.check_route('Future ordinary-file identity checkpoints', (
            'Require literal worktree paths and an exact permitted file allowlist; exclude protected files.',
            'Disable fsmonitor with `-c core.fsmonitor=false` on direct Git reads.',
            'Disable external diff helpers and text conversion with `--no-ext-diff --no-textconv` where applicable.',
            'Bind the revision, status, diff and hash results to one unchanged checkpoint.',
            'Invalidate an inconsistent checkpoint collection or any collection whose source changes during capture.',
        ))

    def test_scoped_owner_event_verification_preserves_all_other_input_bans(self):
        self.check_route('Scoped owner event verification', (
            'Confirm that your loaded role or skill implements this exception',
            "named lane's brief to select it and cite a CoC-frozen decision file by absolute path and SHA256",
            'Verify the digest and exact scope before any call',
            'exact lane, its repository and task or PR scope, and the owner events to verify',
            'the permitted tool for each exact Input and workspace UUID',
            'Permit only `get_input` or `get_input_events` for those exact IDs, solely to verify the named owner events',
            'supplies zero owner consent or action authority',
            "only to the named lane's brief-level ban on Input calls",
            'Keep every other Input call under the ban',
            'Preserve reviewer MCP denials, all independent hook and tool restrictions, and every effective refusal',
        ))
        for path in (self.skill, *(self.ship / 'agents' / name for name in self.lanes)):
            with self.subTest(path=path):
                self.assertIn('owner-decisions.md#scoped-owner-event-verification', path.read_text())
        for path in (self.ship / 'agents').glob('reviewer--*.md'):
            with self.subTest(reviewer=path.name):
                text = path.read_text()
                self.assertNotIn('owner-decisions.md#scoped-owner-event-verification', text)
                self.assertIn('tools: Read, Grep, Glob, LSP, WebFetch, WebSearch\n', text)


if __name__ == '__main__':
    unittest.main()
