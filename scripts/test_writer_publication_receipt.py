"""Writer admission distinguishes a local publication receipt from executable push spellings."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

HOOK = Path(__file__).resolve().parents[1] / 'plugins/ship/hooks/ultraship.py'


class WriterPublicationReceiptTests(unittest.TestCase):
    def admission(self, command):
        # Pass the command as inert hook input. Never execute the proposed shell command.
        result = subprocess.run([sys.executable, str(HOOK), 'pre'], input=json.dumps({
            'agent_type': 'ship:writer--sol', 'tool_name': 'Bash', 'tool_input': {'command': command}}),
            capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_local_python_receipt_with_false_publication_field_is_admitted(self):
        command = """python3 -I - <<'PY'
from pathlib import Path
import subprocess, json
committed = subprocess.check_output(['git', 'diff', 'HEAD^', 'HEAD'])
assert subprocess.check_output(['git', 'status', '--porcelain']) == b''
receipt = {'byte_count': len(committed), 'pushed': False}
Path('receipt.json').write_text(json.dumps(receipt) + '\\n')
PY"""
        self.assertEqual(self.admission(command), {})

    def test_real_remote_operations_remain_denied_beside_a_local_receipt(self):
        for command in ('{git,push} origin HEAD', "$'git' {status,push} origin HEAD",
                        'git p{ush,ull} origin HEAD', 'git push{ed,} origin HEAD',
                        'git push origin HEAD', 'git -C "$PWD" push origin HEAD',
                        "$'git' p{u,}sh origin HEAD", 'gh pr merge 3 --squash',
                        'python3 -c "receipt = {\'pushed\': False}"; git push origin HEAD'):
            with self.subTest(command=command):
                result = self.admission(command)
                self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')
