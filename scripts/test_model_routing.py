"""Required review and verifier seats use Opus with their explicit effort."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_plugins', ROOT / 'scripts/check-plugins.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class ImportantPlanningContractTests(unittest.TestCase):
    ship = ROOT / 'plugins/ship'

    def setUp(self):
        pipeline = (self.ship / 'skills/ship/references/pipeline.md').read_text()
        self.plan = pipeline.split('## 2. Plan and premises\n', 1)[1].split('## 3. Slices\n', 1)[0]
        self.pipeline = pipeline
        self.gate = self.plan.partition('### Important planning\n')[2]

    def test_important_planning_starts_with_fable_then_follows_the_sol_chain(self):
        roster = (self.ship / 'skills/ship/references/roster.md').read_text().splitlines()
        start = next(i for i, line in enumerate(roster) if line.startswith('| `ship:planner--'))
        first, sol = (line.split('|') for line in roster[start:start + 2])
        self.assertEqual((first[1].strip(), first[5].strip(), sol[1].strip()),
                         ('`ship:planner--fable52`', '`planner--sol`', '`ship:planner--sol`'))
        self.assertEqual(first[2].strip(), '`claude-fable-5-2`')
        self.assertEqual(first[3].strip(), 'xhigh')
        self.assertEqual(sol[5].strip(), '`planner--opus`, `planner--sonnet`')
        sol_chain = [seat.strip(' `') for seat in sol[5].split(',')]
        for seat in sol_chain:
            self.assertTrue((self.ship / 'agents' / (seat + '.md')).is_file(), seat)
        self.assertIn('Continue through the `planner--sol` fallback chain in roster order.', self.gate)
        self.assertIn('Dispatch `ship:planner--fable52` first for important planning.', self.gate)
        self.assertIn('If Fable is unavailable, use `ship:planner--sol` next.', self.gate)
        self.assertIn('Use `ship:planner--sol` for routine full-mode planning.', self.plan)
        skill = (self.ship / 'skills/ship/SKILL.md').read_text()
        self.assertIn('Start important planning in either mode with `ship:planner--fable52`.', skill)
        goal = (self.ship / 'skills/ship/references/goal.md').read_text()
        self.assertIn('Start important planning with ship:planner--fable52 and apply the Ship important planning gate.', goal)

    def test_driver_runs_refutation_before_fresh_confirmation_on_the_important_route(self):
        self.assertRegex(self.gate, r'(?s)Dispatch one independent `ship:reviewer--astra`.*'
                                    r'Start a fresh `ship:reviewer--opus` Agent')
        self.assertIn('Use this route only for important planning', self.gate)
        self.assertIn('Light mode runs steps 1, 3, 5, 7, 9, 10, and 12.', self.pipeline)
        self.assertIn('Keep routine work on its existing route', self.plan)
        self.assertIn('Apply the [important planning gate](#important-planning) in either mode', self.pipeline)
        skill = (self.ship / 'skills/ship/SKILL.md').read_text()
        self.assertIn('references/pipeline.md#important-planning', skill)
        completion = skill.split('## Completion gate\n', 1)[1].split('### Explicit checks', 1)[0]
        self.assertIn('Require both [important planning](references/pipeline.md#important-planning) results', completion)
        planner = (self.ship / 'agents/planner--sol.md').read_text()
        self.assertIn('#important-planning', planner)
        self.assertNotIn('Agent', checks.frontmatter(planner)['tools'])
        for seat in ('reviewer--astra', 'reviewer--opus'):
            with self.subTest(seat=seat):
                reviewer = (self.ship / 'agents' / (seat + '.md')).read_text()
                self.assertEqual(checks.frontmatter(reviewer)['tools'], 'Read, Grep, Glob, LSP, WebFetch, WebSearch')

    def test_confirmation_uses_only_frozen_evidence_and_keeps_material_conflicts_pending(self):
        for requirement in (
            'Give the refuter the draft, evidence locations, constraints, and falsifiers',
            'Skip any seat whose pinned model authored the plan or served in the other round',
            'Do not resume any earlier agent',
            'Omit earlier verdicts, review transcripts, and coordinator conclusions',
            'Keep the refute findings and the disposition record out of the confirmation brief and its readable files',
            'Confirm the exact final plan against its evidence and falsifiers',
            'Keep the plan pending if either round is missing, blocked, incomplete, or stale',
            'Keep unresolved material contradictions pending',
            'Record a passing `plan` row only after both rounds qualify',
            'Repeat both rounds if the plan or its evidence changes after confirmation',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.plan)

    def test_rework_stops_after_one_additional_attempt(self):
        self.assertRegex(self.gate, r'(?s)Allow one rework attempt after the initial attempt\..*'
                                    r'Persist the rework count.*'
                                    r'On exhaustion, keep the plan and dependent slices pending')
        self.assertIn('Apply this limit to every return to planning or refutation', self.gate)

    def test_design_panel_keeps_a_frozen_plan_on_both_routes(self):
        ordinary = self.plan.split('### Important planning\n', 1)[0]
        self.assertIn('Require prior confirmation only when the important planning gate applies.\n'
                      'Run `ship:panel design` on the frozen plan before step 3 for design-heavy work.', ordinary)

    def test_outside_commit_evidence_stays_bound_until_dependent_work(self):
        for requirement in (
            'Record the source identity, exact readable snapshot path, and SHA256 of each item',
            'Use the same manifest in both rounds',
            'Include the evidence manifest SHA256 in both briefs and both review records',
            'Recompute the plan, manifest, and snapshot digests before each review dispatch and before accepting its verdict',
            'Verify the plan digest and all evidence digests before each dependent dispatch',
            'Match the recomputed digests to the confirmation record for the final plan',
            'Keep dependent work pending on missing, unreadable, or mismatched evidence',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.gate)

    def test_both_rounds_preserve_dispatch_and_action_gates(self):
        for requirement in (
            'helper standing request', 'permitted paths and exclusions', 'security review triage',
            'Leave `model` unset', 'existing roster fallback chains', 'execution admission',
            'owner decisions', 'zero authority for implementation or publication',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.plan)


class ModelRoutingTests(unittest.TestCase):
    def test_astra_and_luna_reviewer_names_pin_their_declared_models(self):
        for seat, model in (('reviewer--astra', 'gpt-6.2-astra'),
                            ('verifier--astra', 'gpt-6.2-astra'),
                            ('reviewer--luna', 'gpt-6-luna')):
            with self.subTest(seat=seat):
                path = ROOT / 'plugins/ship/agents' / (seat + '.md')
                fields = checks.frontmatter(path.read_text())
                self.assertEqual(fields['name'], seat)
                self.assertEqual(fields['model'], model)
                self.assertEqual(checks.inspect_text(path.read_text(), path), [])

    def test_required_seats_keep_read_only_tools_effort_and_fallbacks(self):
        for seat in ('reviewer--fable', 'verifier--fable'):
            path = ROOT / 'plugins/ship/agents' / (seat + '.md')
            fields = checks.frontmatter(path.read_text())
            self.assertEqual(fields['model'], 'claude-opus-5-5')
            self.assertEqual(fields['effort'], 'xhigh')
            self.assertEqual(checks.inspect_text(path.read_text(), path), [])
            self.assertNotIn('Bash', fields['tools'])
            self.assertNotIn('Edit', fields['tools'])
        roster = (ROOT / 'plugins/ship/skills/ship/references/roster.md').read_text()
        self.assertIn('| `ship:reviewer--fable` | `claude-opus-5-5` | xhigh |', roster)
        self.assertIn('| `ship:verifier--fable` | `claude-opus-5-5` | xhigh |', roster)
        panels = (ROOT / 'plugins/ship/skills/panel/references/panels.md').read_text()
        self.assertIn('`reviewer--fable`, `reviewer--luna`', panels)
        self.assertIn('`reviewer--astra` takes the seat', panels)
        for path in (ROOT / 'plugins/ship/agents').glob('*.md'):
            if path.stem.endswith('--fable52'):
                continue
            self.assertNotIn('claude-fable-', checks.frontmatter(path.read_text()).get('model', ''))
        for seat in ('driver--sol', 'planner--sol', 'reviewer--sol', 'triage--sol', 'writer--sol'):
            with self.subTest(seat=seat):
                path = ROOT / 'plugins/ship/agents' / (seat + '.md')
                sol = checks.frontmatter(path.read_text())
                self.assertEqual((sol['model'], sol['effort']), ('gpt-6.2-sol', 'xhigh'))
                self.assertEqual(checks.inspect_text(path.read_text(), path), [])
        driver = checks.frontmatter((ROOT / 'plugins/ship/agents/driver.md').read_text())
        self.assertEqual((driver['model'], driver['effort']), ('claude-opus-5-5', 'xhigh'))
        low = checks.frontmatter((ROOT / 'plugins/ship/agents/driver--sol.md').read_text())
        self.assertEqual((low['model'], low['effort']), ('gpt-6.2-sol', 'xhigh'))
        self.assertIn('low', low['description'])
        for path in (ROOT / 'plugins/ship/agents').glob('*.md'):
            self.assertNotEqual(checks.frontmatter(path.read_text()).get('model', 'inherit'), 'inherit', path.name)
        self.assertEqual(checks.check('HEAD'), [])

    def test_sol_validator_requires_explicit_xhigh_and_rejects_retired_models(self):
        cases = (
            ('gpt-6.2-sol', 'xhigh', []),
            ('gpt-6.2-sol', None, ['gpt-6.2-sol agents require explicit xhigh effort']),
            ('gpt-6.1-sol', 'high', ['unsupported model: gpt-6.1-sol']),
            ('gpt-6-astra', None, ['unsupported model: gpt-6-astra']),
            ('kimi-k3', None, ['unsupported model: kimi-k3']),
            ('unknown-model', 'xhigh', ['unsupported model: unknown-model']),
        )
        cases += tuple(
            ('gpt-6.2-sol', effort, ['gpt-6.2-sol agents require explicit xhigh effort'])
            for effort in ('low', 'medium', 'high', 'max')
        )
        cases += tuple(
            ('gpt-6.1-sol', effort, ['unsupported model: gpt-6.1-sol'])
            for effort in ('low', 'medium', 'xhigh', 'max')
        )
        for model, effort, errors in cases:
            with self.subTest(model=model, effort=effort):
                effort_field = '' if effort is None else f'effort: {effort}\n'
                text = f'---\nname: test\ndescription: Routing contract.\nmodel: {model}\n{effort_field}---\n'
                self.assertEqual(checks.inspect_text(text, Path('agents/test.md')), errors)

    def test_fable52_seats_pin_fable_and_copy_their_base_seat_body(self):
        for seat, base, effort in (('planner--fable52', 'planner--sol', 'xhigh'),
                                   ('writer--fable52', 'writer--sol', 'high'),
                                   ('reviewer--fable52', 'reviewer--fable', 'xhigh')):
            with self.subTest(seat=seat):
                path = ROOT / 'plugins/ship/agents' / (seat + '.md')
                text = path.read_text()
                fields = checks.frontmatter(text)
                self.assertEqual((fields['name'], fields['model'], fields['effort']), (seat, 'claude-fable-5-2', effort))
                self.assertEqual(checks.inspect_text(text, path), [])
                base_text = (ROOT / 'plugins/ship/agents' / (base + '.md')).read_text()
                body = text.split('\n---\n', 1)[1]
                base_body = base_text.split('\n---\n', 1)[1]
                self.assertEqual(body, base_body)
                if seat == 'planner--fable52':
                    route = '[important planning](../skills/ship/references/pipeline.md#important-planning) route'
                    self.assertIn(f"If the coordinator's brief names the {route}, return a draft for that route.", body)
                    self.assertEqual(fields['tools'], checks.frontmatter(base_text)['tools'])
                    self.assertNotIn('Agent', fields['tools'].split(', '))
                if seat == 'writer--fable52':
                    self.assertEqual(fields['disallowedTools'], checks.frontmatter(base_text)['disallowedTools'])
        reviewer = checks.frontmatter((ROOT / 'plugins/ship/agents/reviewer--fable52.md').read_text())
        self.assertNotIn('Bash', reviewer['tools'])
        self.assertNotIn('Edit', reviewer['tools'])
