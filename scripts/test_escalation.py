"""A refused Bash call escalates to the lane's manager, who may approve and run the exact command once."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / 'plugins/ship/hooks'
TEMP = Path(tempfile.mkdtemp(prefix='escalation-test-'))
os.environ['XDG_STATE_HOME'] = str(TEMP / 'state')
os.environ['ULTRASHIP_COC_DIR'] = str(TEMP / 'coc')
spec = importlib.util.spec_from_file_location('ultraship_escalation_hook', HOOKS / 'ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)
escalation = ultraship.load_escalation()

WRITE = 'gh api repos/o/r/issues/7/comments -f body=x'
CLI = 'python3 ' + str(HOOKS / 'escalation.py')


def git(cwd, *args):
    subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args],
                   check=True, capture_output=True)


class EscalationTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEMP / 'state', ignore_errors=True)
        self.lane = TEMP / 'lane'
        shutil.rmtree(self.lane, ignore_errors=True)
        self.lane.mkdir()
        (TEMP / 'coc').mkdir(exist_ok=True)
        git(self.lane, 'init', '-q')
        git(self.lane, 'commit', '-q', '--allow-empty', '-m', 'base')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)

    def decision(self, command, session='S1', agent_id=None, agent_type=None, cwd=None, tool='Bash', tool_input=None):
        data = {'session_id': session, 'tool_name': tool, 'cwd': str(cwd or self.lane),
                'tool_input': tool_input or {'command': command}}
        if agent_id:
            data.update(agent_id=agent_id, agent_type=agent_type or 'ship:driver')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre(data)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        return json.loads(text)['hookSpecificOutput'] if text else {}

    def escalate(self, command=WRITE, agent_type='ship:driver'):
        result = self.decision(command, agent_id='a1', agent_type=agent_type)
        self.assertEqual(result.get('permissionDecision'), 'deny', result)
        match = re.search(r'Escalated to (.+?) as ([0-9a-f]{32}); stop this step and wait\.$',
                          result['permissionDecisionReason'])
        self.assertTrue(match, result['permissionDecisionReason'])
        return match[1], match[2]

    def approve(self, identifier, session='S1', agent_id=None, cwd=None):
        return self.decision(f"{CLI} approve {identifier} --reason 'reviewed the exact command'",
                             session=session, agent_id=agent_id, cwd=cwd or TEMP)

    def run_approved(self, command=WRITE, session='S1'):
        return self.decision(f"cd '{self.lane}' && {command}", session=session, cwd=TEMP)

    def test_refusal_writes_a_record_that_names_the_manager(self):
        manager, identifier = self.escalate()
        self.assertEqual(manager, 'the parent main session S1')
        entry = escalation.get(identifier)
        head = subprocess.run(['git', '-C', str(self.lane), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        self.assertEqual((entry['command'], entry['cwd'], entry['head']), (WRITE, os.path.realpath(self.lane), head))
        self.assertEqual(entry['actor'], {'session_id': 'S1', 'agent_id': 'a1', 'agent_type': 'ship:driver'})
        self.assertEqual(entry['manager'], {'kind': 'parent', 'session_id': 'S1'})
        self.assertRegex(entry['sha256'], r'^[0-9a-f]{64}$')
        main = self.decision(WRITE)['permissionDecisionReason']
        self.assertRegex(main, r'Escalated to the CoC as [0-9a-f]{32}; stop this step and wait\.$')

    def test_approved_command_runs_once(self):
        _, identifier = self.escalate()
        self.assertEqual(self.approve(identifier), {})
        self.assertEqual(self.run_approved(), {})
        self.assertEqual(self.run_approved().get('permissionDecision'), 'deny')

    def test_one_byte_difference_refuses(self):
        _, identifier = self.escalate()
        self.assertEqual(self.approve(identifier), {})
        self.assertEqual(self.run_approved(WRITE + 'y').get('permissionDecision'), 'deny')
        self.assertEqual(self.run_approved(), {})

    def test_other_session_expired_approval_and_moved_head_refuse(self):
        _, identifier = self.escalate()
        self.assertEqual(self.approve(identifier), {})
        self.assertEqual(self.run_approved(session='S2').get('permissionDecision'), 'deny')
        with patch('time.time', return_value=time.time() + escalation.TTL + 1):
            self.assertEqual(self.run_approved().get('permissionDecision'), 'deny')
        git(self.lane, 'commit', '-q', '--allow-empty', '-m', 'moved')
        self.assertEqual(self.run_approved().get('permissionDecision'), 'deny')

    def test_absolute_hold_refuses_even_with_an_approval(self):
        command = 'git push --force origin HEAD:refs/heads/x'
        _, identifier = self.escalate(command, agent_type='ship:writer--sol')
        refused = self.approve(identifier)
        self.assertEqual(refused.get('permissionDecision'), 'deny')
        self.assertIn('absolute hold (destructive git)', refused['permissionDecisionReason'])
        # A signed approval the hook would never write still cannot run the command.
        entry = escalation.get(identifier)
        now = int(time.time())
        escalation.write_new(escalation.store() / (identifier + '.decision.json'), escalation.sign({
            'id': identifier, 'decision': 'approve', 'reason': 'x', 'sha256': entry['sha256'], 'cwd': entry['cwd'],
            'head': entry['head'], 'approver': 'S1', 'time': now, 'expires': now + escalation.TTL}))
        result = self.run_approved(command)
        self.assertEqual(result.get('permissionDecision'), 'deny')
        self.assertIn('absolute hold (destructive git)', result['permissionDecisionReason'])

    def test_absolute_hold_classes(self):
        for command, name in (
            ('cat .env', 'secret read'), ('gh auth token', 'secret read'), ('echo "$GITHUB_TOKEN"', 'secret read'),
            ('vercel deploy --prod', 'production write'), ('neonctl branches delete b', 'production write'),
            ('git reset --hard origin/main', 'destructive git'), ('git clean -fdx', 'destructive git'),
            ('git branch -D old', 'destructive git'), ('git push origin --delete x', 'destructive git'),
            ('git push origin +HEAD:main', 'destructive git'), ('git update-ref -d refs/heads/x', 'destructive git'),
            ('gh api -X PUT repos/o/r/branches/main/protection', 'owner-only setting'),
            ('gh secret set API_KEY', 'owner-only setting'),
            ('echo x > ~/.local/state/ultraship/escalations/a.json', 'escalation or receipt store write'),
        ):
            with self.subTest(command=command):
                self.assertEqual(ultraship.absolute_hold(command), name)
        for command in ('git push origin HEAD:refs/heads/x', 'git push -u origin feat/x', 'git status',
                        'cat .env.example', 'gh pr view 7', 'git branch -d merged'):
            with self.subTest(command=command):
                self.assertIsNone(ultraship.absolute_hold(command))

    def test_lane_cannot_approve(self):
        _, identifier = self.escalate()
        self.assertEqual(self.approve(identifier, agent_id='a2').get('permissionDecision'), 'deny')
        self.assertEqual(self.approve(identifier, session='S2').get('permissionDecision'), 'deny')
        self.assertIsNone(escalation.decision(identifier))
        # A main-session record goes to the CoC: its own session and a session outside the CoC folder refuse.
        identifier = re.search(r'as ([0-9a-f]{32});', self.decision(WRITE)['permissionDecisionReason'])[1]
        self.assertEqual(self.approve(identifier).get('permissionDecision'), 'deny')
        self.assertEqual(self.approve(identifier, session='C', cwd=TEMP / 'coc'), {})

    def test_lane_cannot_write_approval_files(self):
        target = escalation.store() / ('0' * 32 + '.decision.json')
        for tool, tool_input in (('Write', {'file_path': str(target), 'content': '{}'}),
                                 ('Edit', {'file_path': str(target), 'old_string': 'a', 'new_string': 'b'})):
            with self.subTest(tool=tool):
                self.assertEqual(self.decision('', agent_id='a1', tool=tool, tool_input=tool_input)
                                 .get('permissionDecision'), 'deny')
        for command in (f'echo x > {target}', 'echo x > ~/.local/state/ultraship/escalations/x.json',
                        f'python3 -c "import sys; sys.path.insert(0, {str(HOOKS)!r}); import escalation"'):
            with self.subTest(command=command):
                self.assertEqual(self.decision(command, agent_id='a1').get('permissionDecision'), 'deny')

    def test_plain_push_is_not_refused(self):
        for agent_id in (None, 'a1'):
            with self.subTest(agent_id=agent_id):
                self.assertEqual(self.decision('git push origin HEAD:refs/heads/x', agent_id=agent_id), {})

    def test_subagent_stop_surfaces_pending_ids(self):
        _, identifier = self.escalate()
        for active, expected in ((False, True), (True, False)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                ultraship.subagent_stop({'session_id': 'S1', 'agent_id': 'a1', 'agent_type': 'ship:driver',
                                         'cwd': str(self.lane), 'stop_hook_active': active})
            with self.subTest(active=active):
                self.assertEqual(identifier in output.getvalue(), expected)

    def test_cli_prints_but_never_writes_a_decision(self):
        _, identifier = self.escalate()
        env = dict(os.environ)
        listed = subprocess.run(['python3', str(HOOKS / 'escalation.py'), 'list'], capture_output=True, text=True, env=env)
        self.assertIn(identifier, listed.stdout)
        refused = subprocess.run(['python3', str(HOOKS / 'escalation.py'), 'approve', identifier, '--reason', 'x'],
                                 capture_output=True, text=True, env=env)
        self.assertEqual(refused.returncode, 1)
        self.assertIsNone(escalation.decision(identifier))


if __name__ == '__main__':
    unittest.main()
