"""Agent-facing execution contracts; these checks never execute a test workload or signal a process."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text()


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
