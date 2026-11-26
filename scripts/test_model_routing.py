"""Required review and verifier seats use Opus with their explicit effort."""
import importlib.util
from pathlib import Path
import tempfile
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
        self.assertEqual(sol[5].strip(), '`planner--opus`')
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
    def test_writer_and_planner_use_only_admitted_fallbacks(self):
        ship = ROOT / 'plugins/ship'
        for seat in ('writer--sonnet', 'planner--sonnet'):
            with self.subTest(seat=seat):
                self.assertFalse((ship / 'agents' / (seat + '.md')).exists())
        skill_dir = ship / 'skills/ship'
        roster = (skill_dir / 'references/roster.md').read_text()
        for seat, fallback in (('writer--sol', 'none'), ('planner--sol', '`planner--opus`'),
                               ('writer--fable52', '`writer--sol`')):
            with self.subTest(seat=seat):
                row, = (line for line in roster.splitlines() if line.startswith(f'| `ship:{seat}` |'))
                self.assertEqual(row.split('|')[-2].strip(), fallback)
                if seat == 'writer--fable52':
                    self.assertIn('only when the brief or the owner names Fable 5.2', row)
        opus = checks.frontmatter((ship / 'agents/planner--opus.md').read_text())
        self.assertEqual((opus['model'], opus['effort']), ('claude-opus-5-5', 'xhigh'))
        hold = 'If all admitted writer or planner seats are unavailable, retain the task as pending and report the missing seat.'
        self.assertIn(hold, roster)
        self.assertIn(hold, (skill_dir / 'SKILL.md').read_text())
        self.assertIn('Apply the [roster](../ship/references/roster.md) when the writer is unavailable.',
                      (ship / 'skills/babysit/SKILL.md').read_text())

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
        agents = ROOT / 'plugins/ship/agents'
        read_only = 'Read, Grep, Glob, LSP, WebFetch, WebSearch'
        for seat in ('reviewer--opus-panel', 'verifier--opus'):
            with self.subTest(seat=seat):
                path = agents / (seat + '.md')
                self.assertTrue(path.is_file(), seat)
                fields = checks.frontmatter(path.read_text())
                self.assertEqual(fields['name'], seat)
                self.assertEqual(fields['model'], 'claude-opus-5-5')
                self.assertEqual(fields['effort'], 'xhigh')
                self.assertEqual(checks.inspect_text(path.read_text(), path), [])
                self.assertEqual(fields['tools'], read_only)
        for seat in ('reviewer--fable', 'verifier--fable'):
            self.assertFalse((agents / (seat + '.md')).exists(), seat)
        roster = (ROOT / 'plugins/ship/skills/ship/references/roster.md').read_text()
        for seat, use, fallback in (
            ('reviewer--opus-panel', 'Design and final panels (required seat)', 'reviewer--astra'),
            ('verifier--opus', 'Billing and authorization', 'verifier--astra'),
            ('reviewer--opus', 'High panel, deep review, simplify', 'reviewer--sonnet'),
        ):
            self.assertIn(f'| `ship:{seat}` | `claude-opus-5-5` | xhigh | {use} | `{fallback}` |', roster)
        for fallback, primary in (('reviewer--astra', 'reviewer--opus-panel'),
                                  ('verifier--astra', 'verifier--opus')):
            fields = checks.frontmatter((agents / (fallback + '.md')).read_text())
            self.assertIn(f'ship:{primary}', fields['description'])
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

    def test_panel_routes_keep_three_seats_and_count_astra_once_on_fallback(self):
        panel_dir = ROOT / 'plugins/ship/skills/panel'
        panels = (panel_dir / 'references/panels.md').read_text()
        for tier, seats in (
            ('light', ('reviewer--luna', 'reviewer--astra', 'reviewer--sol')),
            ('design', ('reviewer--astra', 'reviewer--opus-panel', 'reviewer--luna')),
            ('high', ('reviewer--sol', 'reviewer--astra', 'reviewer--opus')),
            ('final', ('reviewer--sol', 'reviewer--opus-panel', 'reviewer--luna')),
        ):
            label = f'`{tier}`' + (' (default)' if tier == 'high' else '')
            routes = ', '.join(f'`{seat}`' for seat in seats)
            self.assertIn(f'| {label} | {routes} |', panels)
        self.assertIn('`reviewer--astra` takes the seat', panels)
        self.assertIn('the panel counts one Astra seat and is incomplete', panels)
        self.assertIn('Anthropic (`opus`, `opus-panel`, `sonnet`, `fable52`)', panels)
        skill = (panel_dir / 'SKILL.md').read_text()
        self.assertIn('Count one vote per model family.', skill)
        self.assertIn('A missing required seat makes the verdict `provisional`.', skill)

    def test_chief_calls_the_independent_opus_verifier(self):
        chief = ROOT / 'plugins/chief'
        for file in ('README.md', 'skills/run/SKILL.md', 'skills/run/references/landing.md'):
            text = (chief / file).read_text()
            self.assertIn('`ship:verifier--opus`', text, file)
            self.assertNotIn('`ship:verifier--fable`', text, file)
        landing = (chief / 'skills/run/references/landing.md').read_text()
        self.assertIn('independent adversarial verification lane, separate from the builder\'s panels', landing)
        self.assertIn('replay/idempotency, tenant isolation, and authorization cases', landing)
        self.assertIn('Supply authorized test boundaries.', landing)

    def test_chief_holds_verification_when_the_paired_native_route_is_missing(self):
        for plugin in ('chief', 'ship'):
            readme = (ROOT / f'plugins/{plugin}/README.md').read_text()
            self.assertIn('Upgrade Chief to `1.8.6` and Ship to `1.15.51` together', readme)
        run = ROOT / 'plugins/chief/skills/run'
        skill = (run / 'SKILL.md').read_text()
        self.assertIn('[verifier dispatch check](references/landing.md#verifier-dispatch-check)', skill)
        landing = (run / 'references/landing.md').read_text()
        check = landing.split('## Verifier dispatch check\n', 1)
        self.assertEqual(len(check), 2)
        check = check[1].split('\n## ', 1)[0]
        self.assertIn('Before dispatch, confirm that the current session lists the exact native route `ship:verifier--opus`.', check)
        self.assertIn('If the route is absent or cannot be confirmed, hold verification', check)
        self.assertIn('Report Ship `1.15.51` as the required plugin version', check)
        self.assertIn('Use the `ship:verifier--astra` fallback only when the exact Opus route is registered but unavailable.', check)

    def test_ledger_keeps_historical_seat_names_and_agent_ids(self):
        spec = importlib.util.spec_from_file_location(
            'ledger', ROOT / 'plugins/ship/skills/ship/scripts/ledger.py')
        ledger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ledger)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run.tsv'
            historical = ('1\tpanel-final\tship:reviewer--fable@r1\tsha\tpass\tevidence\n'
                          '2\tverify\tship:verifier--fable@v1\tsha\tpass\tevidence\n')
            path.write_text(historical)
            ledger.append(path, 'panel-final', 'ship:reviewer--opus-panel@r2', 'sha', 'pass', 'evidence')
            ledger.append(path, 'verify', 'ship:verifier--opus@v2', 'sha', 'pass', 'evidence')
            self.assertEqual([ledger.agent_key(row[2]) for row in ledger.rows(path)], [
                ('ship:reviewer--fable', 'r1'), ('ship:verifier--fable', 'v1'),
                ('ship:reviewer--opus-panel', 'r2'), ('ship:verifier--opus', 'v2'),
            ])
            self.assertTrue(path.read_text().startswith(historical))

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
                                   ('reviewer--fable52', 'reviewer--opus-panel', 'xhigh')):
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
