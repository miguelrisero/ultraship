"""Replay synthetic driver wait events through the registered Ship hooks."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1] / 'plugins' / 'ship'


class DriverPendingWaitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = temporary.name
        self.env = {'PATH': os.defpath, 'HOME': root, 'XDG_STATE_HOME': root,
                    'CLAUDE_CONFIG_DIR': root, 'CLAUDE_PLUGIN_ROOT': str(PLUGIN)}
        self.driver = {'session_id': '00000000-0000-4000-8000-000000000001', 'cwd': root,
                       'agent_type': 'ship:driver--sol', 'agent_id': 'driver-one'}
        self.hooks = json.loads((PLUGIN / 'hooks' / 'hooks.json').read_text())['hooks']
        script = Path(root) / 'skills' / 'run' / 'scripts' / 'watchers.py'
        command = (f'python3 {shlex.quote(str(script))} wait --repo example/repo --pr 17 '
                   '--interval 300 --max-seconds 900')
        self.task = {'id': 'bciwait01', 'type': 'local_bash', 'status': 'running',
                     'description': 'Wait for CI', 'command': command}

    def dispatch(self, event, agent, **fields):
        payload = {**self.driver, 'agent_id': agent, 'hook_event_name': event, **fields}
        results = []
        for group in self.hooks.get(event, []):
            matcher = group.get('matcher', '*')
            if matcher != '*' and not re.fullmatch(matcher, payload.get('tool_name', '')):
                continue
            for hook in group['hooks']:
                command = shlex.split(hook['command'].replace('${CLAUDE_PLUGIN_ROOT}', str(PLUGIN)))
                self.assertEqual(command[0], 'python3')
                result = subprocess.run([sys.executable, *command[1:]], input=json.dumps(payload),
                                        text=True, capture_output=True, env=self.env, cwd=self.driver['cwd'],
                                        check=True)
                if result.stdout.strip():
                    results.append(json.loads(result.stdout))
        return results

    def start_wait(self, agent='driver-one'):
        self.dispatch('PostToolUse', agent, tool_name='Bash', tool_use_id='toolu_ci_wait',
                      tool_input={'command': self.task['command'], 'description': self.task['description'],
                                  'run_in_background': True},
                      tool_response={'stdout': '', 'stderr': '', 'interrupted': False,
                                     'backgroundTaskId': self.task['id']})

    def stop(self, *, agent='driver-one', **task_fields):
        results = self.dispatch('SubagentStop', agent, stop_hook_active=False,
                                background_tasks=[{**self.task, **task_fields}])
        return [result['reason'] for result in results if result.get('decision') == 'block']

    def test_stop_blocks_with_the_drivers_exact_pending_wait(self):
        self.start_wait()
        reasons = self.stop()
        self.assertTrue(reasons, 'Ship allowed the driver to stop with its CI wait pending')
        self.assertTrue(any(self.task['id'] in reason for reason in reasons), reasons)

    def test_stop_allows_the_drivers_terminal_wait(self):
        self.start_wait()
        self.assertEqual(self.stop(status='completed'), [])

    def test_stop_allows_another_drivers_pending_wait(self):
        self.start_wait(agent='driver-two')
        self.assertEqual(self.stop(), [])

    def test_stop_allows_a_different_task_with_the_same_command(self):
        self.start_wait()
        self.assertEqual(self.stop(id='bciwait02'), [])

    def test_stop_allows_an_unbound_pending_wait(self):
        self.assertEqual(self.stop(), [])


if __name__ == '__main__':
    unittest.main()
