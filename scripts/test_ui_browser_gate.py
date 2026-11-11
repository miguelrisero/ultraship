"""Instruction contracts only; these checks provide zero browser runtime evidence."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIP = ROOT / 'plugins/ship/skills/ship'


class UIBrowserGateTests(unittest.TestCase):
    def test_native_completion_requires_current_head_browser_proof(self):
        skill = (SHIP / 'SKILL.md').read_text()
        gate = skill.split('## Completion gate', 1)[1].split('## Proof after merge', 1)[0]
        for phrase in ('Every UI PR', 'current pushed head and matching preview',
                       'frontend/app/**', 'frontend design-package changes',
                       'marketing UI', 'Missing or failed browser evidence blocks merge',
                       'CI and review supply zero substitute browser evidence'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, gate)
        proof = skill.split('## Proof after merge', 1)[1].split('## Boundaries', 1)[0]
        self.assertIn('Mutation proof runs after merge', proof)
        self.assertIn('real-browser UI check runs before merge', proof)
        self.assertIn('applicable real-browser UI proof', proof)

    def test_pipeline_requires_safe_real_preview_interaction(self):
        pipeline = (SHIP / 'references/pipeline.md').read_text()
        gate = pipeline.split('### UI browser gate', 1)[1].split('## 11. Closing pass', 1)[0]
        for phrase in ('frontend/app/**', 'frontend design-package changes',
                       'frontend/website/**', 'existing Vercel preview route',
                       'serves that exact head', 'Refuse unsafe data isolation before login, seed, interaction, or capture',
                       'owned synthetic preview fixture', 'existing authorized preview authentication and seed path',
                       '/preview login', 'Vercel share preview', 'agent-browser', 'preview admin',
                       'exercise the changed interaction', 'Redact or recapture unsafe evidence',
                       'safe screenshot or access-restricted evidence link on the PR',
                       'credentials, customer or production data, session tokens, and sensitive browser state',
                       'screenshots, URLs, and logs', 'head or preview change reopens this gate',
                       'Missing or failed browser proof blocks merge', 'zero substitute evidence',
                       'grants zero additional permission', 'no simultaneous CoC plugin installation',
                       'source-contract checks establish zero actual browser execution'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, gate)
        self.assertLess(gate.index('Refuse unsafe data isolation'), gate.index('/preview login'))
        self.assertLess(gate.index('Inspect the image, URL'), gate.index('Publish only a safe screenshot'))
        babysit = pipeline.split('## 10. Babysit', 1)[1].split('### UI browser gate', 1)[0]
        self.assertIn('before the completion gate or any merge command', babysit)

    def test_local_route_requires_secret_handling_condition_and_bound_browser_proof(self):
        pipeline = (SHIP / 'references/pipeline.md').read_text()
        gate = pipeline.split('### UI browser gate', 1)[1].split('## 11. Closing pass', 1)[0]
        local = gate.split('**Conditional local route.**', 1)[1].split('**Shared requirements', 1)[0]
        for phrase in ('Use this route only when preview sign-in requires secret handling',
                       'only behavior faithfully reproduced by the local stack qualifies',
                       'Preview/deployment/config-dependent behavior still requires appropriate preview proof',
                       'Keep that scope held if preview proof is unavailable',
                       'Refuse unsafe data isolation before local setup, login, seed, interaction, or capture',
                       'Require a clean checkout at the exact current pushed head',
                       'Build and start the local server from that head',
                       'passwordless synthetic INTERNAL persona',
                       'database-bound refresh injection', 'isolated synthetic stack',
                       'Never use local tokens to authenticate to a preview or print their values',
                       'real Chromium through agent-browser or the existing e2e harness',
                       'same changed screen and exercise the changed interaction',
                       'reason preview sign-in requires secret handling, without secret values',
                       'local origin, build/server command and result, browser command and result, checked head',
                       'interaction result, and screenshot route'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, local)
        shared = gate.split('**Shared requirements', 1)[1]
        for phrase in ('safe screenshot or access-restricted evidence link on the PR',
                       'Require post-check head equality with the checked head',
                       'Require the local checkout to remain clean on the local route',
                       'Any head or preview change reopens this gate',
                       'If permission or safe isolation is unavailable', 'retain the merge hold'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, shared)
        self.assertIn('**Default preview route (steps 1–5).**', gate)
        self.assertIn('Never request, read, copy, or print preview credentials or session tokens to unblock this gate', gate)

    def test_completion_admits_only_the_conditional_local_route(self):
        skill = (SHIP / 'SKILL.md').read_text()
        gate = skill.split('## Completion gate', 1)[1].split('## Proof after merge', 1)[0]
        for phrase in ('default route requires the current pushed head and matching preview',
                       'Only when preview sign-in requires secret handling',
                       'qualified local real-browser evidence',
                       'same exact pushed head, Chromium interaction, synthetic isolation, safe screenshot evidence, and post-check head equality',
                       'Preview/deployment/config-dependent behavior retains its preview-proof hold'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, gate)


if __name__ == '__main__':
    unittest.main()
