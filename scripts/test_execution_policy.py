"""Agent-facing execution contracts; these checks never execute a test workload or signal a process."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


HOOK = Path(__file__).resolve().parents[1] / 'plugins/ship/hooks/ultraship.py'
spec = importlib.util.spec_from_file_location('execution_policy_hook', HOOK)
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text()


class ReviewerSearchTests(unittest.TestCase):
    def decision(self, tool, arguments, agent='ship:reviewer--sol', **event):
        output = io.StringIO()
        with redirect_stdout(output):
            try:
                ultraship.pre({'agent_type': agent, 'tool_name': tool,
                               'tool_input': arguments, **event})
            except SystemExit as exc:
                self.assertEqual(exc.code, 0)
        return json.loads(output.getvalue())['hookSpecificOutput'] if output.getvalue() else {}

    def assert_denied(self, tool, arguments, agent='ship:reviewer--sol', **event):
        decision = self.decision(tool, arguments, agent, **event)
        self.assertEqual(decision.get('permissionDecision'), 'deny', (tool, arguments, agent))
        self.assertIn('reviewer', decision['permissionDecisionReason'].lower())

    def test_explicit_protected_paths_in_each_tool_argument(self):
        for protected in ('/fixture/repo/tests/mutation/x.txt',
                          '/fixture/repo/pkg/tests/mutation/x.txt', '**/tests/mutation/**',
                          'tests/mutation/', '!tests/mutation/**'):
            cases = [
                ('Read', {'file_path': protected}),
                ('LSP', {'filePath': protected}),
                ('Grep', {'path': protected, 'pattern': 'identifier'}),
                ('Grep', {'path': '/fixture/repo/src', 'glob': protected, 'pattern': 'identifier'}),
                ('Glob', {'path': protected, 'pattern': '*.py'}),
                ('Glob', {'path': '/fixture/repo/src', 'pattern': protected}),
                ('mcp__fff__grep', {'query': protected + ' identifier'}),
                ('mcp__fff__find_files', {'query': protected}),
                ('mcp__fff__multi_grep', {'patterns': ['identifier'], 'constraints': protected}),
            ]
            for index in range(3):
                patterns = ['identifier', 'other', 'third']
                patterns[index] = protected
                cases.append(('mcp__fff__multi_grep', {'patterns': patterns, 'constraints': 'src/'}))
            for agent in ('ship:reviewer--sol', 'reviewer--sol'):
                for tool, arguments in cases:
                    with self.subTest(path=protected, agent=agent, tool=tool, arguments=arguments):
                        self.assert_denied(tool, arguments, agent)

    def test_searches_require_directory_scope_even_after_empty_or_failed_results(self):
        cases = [('Grep', {'pattern': 'identifier'}),
                 ('Grep', {'pattern': 'identifier', 'glob': '*.py'}),
                 ('Glob', {'pattern': '**/*.py'})]
        for tool in ('mcp__fff__grep', 'mcp__fff__multi_grep', 'mcp__fff__find_files'):
            base = {'patterns': ['identifier']} if tool.endswith('multi_grep') else {'query': 'identifier'}
            for constraints in ('', '*.py', 'ultraship.py', '!src/', '!src/ *.py'):
                cases.append((tool, {**base, 'constraints': constraints}))
            cases.append((tool, {**base, 'cursor': 'synthetic-cursor'}))
            if tool.endswith('grep') and not tool.endswith('multi_grep'):
                for prefix in ('*.py', 'ultraship.py', '!src/'):
                    cases.append((tool, {'query': prefix + ' identifier'}))
        for agent in ('ship:reviewer--sol', 'reviewer--sol'):
            for tool, arguments in cases:
                for result in (None, {'content': []}, {'is_error': True, 'content': 'synthetic error'}):
                    with self.subTest(agent=agent, tool=tool, arguments=arguments, result=result):
                        self.assert_denied(tool, arguments, agent, tool_response=result)

    def test_scoped_searches_and_near_matches_remain_available(self):
        for directory in ('/fixture/repo/src', '/fixture/repo/tests/mutation_helpers'):
            cases = [('Read', {'file_path': directory + '/x.txt'}),
                     ('LSP', {'filePath': directory + '/x.txt'}),
                     ('Grep', {'path': directory, 'pattern': 'identifier'}),
                     ('Glob', {'path': directory, 'pattern': '**/*.py'})]
            for agent in ('ship:reviewer--sol', 'reviewer--sol'):
                for tool, arguments in cases:
                    with self.subTest(agent=agent, tool=tool, arguments=arguments):
                        self.assertEqual(self.decision(tool, arguments, agent), {})
        for tool, arguments in (
            ('Grep', {'glob': 'src/**/*.py', 'pattern': 'identifier'}),
            ('Glob', {'pattern': 'src/**/*.py'}),
            ('mcp__fff__grep', {'query': 'src/ identifier'}),
            ('mcp__fff__grep', {'query': 'identifier', 'constraints': 'src/ *.py !generated/'}),
            ('mcp__fff__multi_grep', {'patterns': ['identifier'], 'constraints': 'src/'}),
            ('mcp__fff__find_files', {'query': 'src/ identifier'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assertEqual(self.decision(tool, arguments), {})

    def test_every_reviewer_suffix_uses_the_shared_role_boundary(self):
        suffixes = [path.stem for path in (ROOT / 'plugins/ship/agents').glob('reviewer--*.md')]
        self.assertTrue(suffixes)
        for suffix in suffixes:
            for prefix in ('', 'ship:'):
                with self.subTest(agent=prefix + suffix):
                    self.assert_denied('Grep', {'pattern': 'identifier'}, prefix + suffix)

    def test_other_roles_and_existing_denials_keep_their_decisions(self):
        for agent in ('ship:writer--sol', 'ship:researcher--luna', 'Explore'):
            with tempfile.TemporaryDirectory(dir=ROOT.parent) as state, patch.object(ultraship, 'STATE', Path(state)):
                self.assertEqual(self.decision('Grep', {'pattern': 'identifier'}, agent), {})
        decision = self.decision('Bash', {'command': 'git push origin HEAD'}, 'ship:writer--sol')
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('Writers never push', decision['permissionDecisionReason'])
        decision = self.decision('Agent', {'subagent_type': 'ship:reviewer--sol', 'model': 'opus'})
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('ship agents pin their own model.', decision['permissionDecisionReason'])
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as state, patch.object(ultraship, 'STATE', Path(state)):
            for _ in range(40):
                self.assertEqual(self.decision('Grep', {'pattern': 'identifier'}, 'ship:researcher--luna'), {})
            decision = self.decision('Grep', {'pattern': 'identifier'}, 'ship:researcher--luna')
            self.assertEqual(decision['permissionDecision'], 'deny')
            self.assertIn('Research budget of 40 discovery calls is spent.', decision['permissionDecisionReason'])

    def test_dispatch_contract_covers_replacements_and_failed_searches(self):
        for path in ('plugins/ship/skills/review/SKILL.md',
                     'plugins/ship/skills/panel/SKILL.md',
                     'plugins/ship/skills/ship/references/pipeline.md'):
            text = read(path)
            with self.subTest(path=path):
                for requirement in (
                    'Every initial, verification, and replacement brief lists permitted paths and exclusions.',
                    'Scope every search call to the permitted paths.',
                    'Exclude `tests/mutation/`, generated and vendored content, and any other brief exclusions.',
                    'Report a failed or empty scoped search to the coordinator; never widen the search scope.',
                    'An explicit repository-root path does not authorize broader discovery.',
                ):
                    self.assertIn(requirement, text)


class ExecutionPolicyTests(unittest.TestCase):
    def test_each_writer_distinguishes_ordinary_admission_from_special_gos(self):
        for name in ('writer--sol.md', 'writer--sonnet.md'):
            text = read('plugins/ship/agents/' + name)
            admission = text.partition('### Execution admission and cleanup\n')[2].split('\n### ', 1)[0]
            for requirement in (
                'c20baa02-2a62-4a89-93c9-18b2efd44bbd',
                '2adecd1d-fa79-4c29-9baa-2837ba17395c',
                'Run ordinary touched-file pytest or vitest without a per-run CoC GO or GO launcher-hash packet.',
                'Admit every run through the installed, checksum-pinned `slot_gate.sh` implementation and its recognized `battery*.sh` child.',
                'Preserve load, capacity, RAM, disk, runtime caps, timing exclusion, isolated stacks, and cleanup requirements.',
                'Require GO for mutation batteries, timing runs, and shared-database runs; retain paid-run GOs and spending caps.',
                'Honor a no-run brief and every effective permission denial.',
                'The CoC can always issue a GO to unblock a stuck lane or chief within existing authority.',
                'A GO overrides no permission denial, approval hold, publication rule, or customer safety rule.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, admission)
            self.assertNotIn('wait for a GO permitted by the brief', text)

    def test_each_writer_limits_escalation_to_owned_groups_after_term_grace(self):
        for name in ('writer--sol.md', 'writer--sonnet.md'):
            text = read('plugins/ship/agents/' + name)
            for requirement in (
                'Verify the caller started each target process group and recheck its boot/start identity before every signal.',
                'Send TERM first. Allow the existing TERM grace period before SIGKILL to a surviving caller-owned process group.',
                "Never signal another caller's process or a reused PID/PGID.",
                'Apply this boundary to cleanup commands and repository process helpers; preserve their existing grace periods and runtime caps.',
                'Require actual ownership evidence in reviewed launcher cleanup; a command string supplies zero process-group ownership proof.',
                'Refuse unknown or unowned targets and raw `timeout -k` commands without that proof; preserve the command lint refusal.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, text)
            self.assertNotIn('no SIGKILL', text)

    def test_driver_ship_and_chief_inherit_the_execution_contract(self):
        for name in ('driver.md', 'driver--sol.md'):
            text = read('plugins/ship/agents/' + name)
            with self.subTest(path=name):
                self.assertIn('[execution admission and cleanup](writer--sol.md#execution-admission-and-cleanup)', text)
                self.assertIn('including paid-run GOs and caps', text)
                self.assertIn('caller-owned TERM-grace boundary', text)
                self.assertNotIn('no SIGKILL', text)
        ship = read('plugins/ship/skills/ship/SKILL.md')
        self.assertIn('[execution admission and cleanup](../../agents/writer--sol.md#execution-admission-and-cleanup)', ship)
        chief = read('plugins/chief/skills/run/SKILL.md')
        self.assertIn("installed ship plugin's `agents/writer--sol.md` execution admission and cleanup contract", chief)
        self.assertIn('[canonical push and contact safeguards](references/landing.md#canonical-push-and-contact-safeguards)', chief)

    def test_lane_gate_prohibition_preserves_canonical_publication_safeguards(self):
        text = read('plugins/chief/skills/run/references/landing.md')
        policy = text.partition('## Canonical push and contact safeguards\n')[2].split('\n## ', 1)[0]
        for requirement in (
            'Forbid lane-made push, pacing, memory, disk, and time gates, including MAIN_DRIFT holds and arbitrary contact pacing.',
            'Require successful canonical `hostcheck.py admit` for resource admission within existing execution authority.',
            'Keep canonical repository and provider limits; honor GitHub rate limits and retry instructions.',
            "Use the installed ship plugin's `skills/ship/references/pipeline.md` step 9 before every authorized feature push.",
            'credential-safe resolved destination preflight, permitted dry-run, explicit feature refspec, required local checks, and current-main integration requirements',
            "canonical queued-branch stability, merge-train holds, queue rules, and Miguel Peral's approval and scheduling rules",
            'Main advancement alone creates no lane-defined hold; apply canonical freshness and conflict requirements.',
            'Honor permission denials, hooks, publication authority, approval holds, customer safety, and zero writer push authority.',
            'Retain canonical review, CI, real-browser, and merge gates.',
            'A CoC GO grants zero additional publication authority.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, policy)

    def test_each_writer_carries_the_same_scoped_native_file_recipe(self):
        import re

        requirements = (
            ('Native Read requires ordinary-content authority before any effective refusal', (
                'native read', 'authorized ordinary content', 'before any effective refusal',
            )),
            ('Native Edit requires an absolute path and one unique exact replacement', (
                'native edit', 'absolute path', 'replace_all=false', 'one unique exact match',
            )),
            ('Uncertain authority, scope or match requires stopping and reporting to the driver', (
                'if authority, scope or match is uncertain, stop the operation and report it to the driver',
            )),
            ('Protected content retains its grants and review without added access', (
                'protected content', 'exact existing grants', 'independent review', 'zero protected access',
            )),
            ('An effective refusal blocks equivalent operations and substitute actors', (
                'effective refusal', 'blocks equivalent native reads', 'native edits',
                'alternate execution', 'substitute actors',
            )),
            ('The recipe requires verification of the exact brief scope', (
                "verify the brief's exact file scope",
            )),
            ('The recipe requires applicable operation authority', (
                'applicable operation authority',
            )),
            ('The ordinary recipe applies before effective holds', (
                'before any effective refusal or hold',
            )),
            ('Source delivery grants zero session adoption authority', (
                'zero session adoption authority',
            )),
            ('Source delivery grants zero affected-retry authority', (
                'zero affected-retry authority',
            )),
        )
        sections = []
        for name in ('writer--sol.md', 'writer--sonnet.md', 'writer--fable52.md'):
            with self.subTest(path=name):
                text = read('plugins/ship/agents/' + name)
                heading = '\n### Native file edits\n'
                section = re.split(r'\n#{1,3} ', text.partition(heading)[2], maxsplit=1)[0]
                sections.append(section)
                self.assertIn(heading, text, f'{name}: requires the Native file edits section')
                self.assertIn(
                    'After a method-only denial, apply the owner-decisions method-only rule: '
                    'one native Edit of the already-approved text, then a separate commit step.',
                    section,
                    f'{name}: requires the complete method-only denial rule in the recipe',
                )
                normalized = ' '.join(section.lower().replace('`', '').split())
                for message, phrases in requirements:
                    for phrase in phrases:
                        with self.subTest(requirement=message, phrase=phrase):
                            self.assertIn(phrase, normalized, f'{name}: {message}; missing {phrase!r}')
                first_step = re.search(r'(?m)^[ \t]*\d+[.)][ \t]+', section)
                self.assertIsNotNone(first_step, f'{name}: requires numbered native-file steps')
                warning = ' '.join(section[:first_step.start()].lower().replace('`', '').split())
                for phrase in requirements[4][1]:
                    with self.subTest(warning_phrase=phrase):
                        self.assertIn(
                            phrase, warning,
                            f'{name}: the complete refusal warning must precede the first numbered step',
                        )
        self.assertEqual(
            len(set(sections)), 1,
            'All three writers must carry identical Native file edits sections',
        )
