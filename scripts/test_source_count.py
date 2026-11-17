"""Exercise the source-count CLI against private synthetic Git repositories."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/ship/skills/ship/scripts/source-count.py'
SENTINEL = 'private-source-count-sentinel-7c31'


class SourceCountTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve()
        self.repo = self.directory / 'repo'
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT='0')
        self.init_repo(self.repo)
        self.subject = 'src/a.py'
        self.commit({self.subject: SENTINEL + '\n'})
        self.sha = self.git('rev-parse', 'HEAD')

    def init_repo(self, repo):
        repo.mkdir()
        self.git('init', '-b', 'main', repo=repo)
        self.git('config', 'user.name', 'Test Author', repo=repo)
        self.git('config', 'user.email', 'test@example.invalid', repo=repo)
        self.git('config', 'commit.gpgsign', 'false', repo=repo)

    def git(self, *args, repo=None):
        return subprocess.run(['git', '-C', str(repo or self.repo), *args], env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, check=True).stdout.strip()

    def commit(self, files):
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git('add', '--', *files)
        self.git('commit', '-m', 'Fixture commit')

    def arguments(self, **values):
        options = {'repo': str(self.repo), 'commit': self.sha,
                   'subject': self.subject, 'literal': SENTINEL}
        options.update(values)
        return [word for key, value in options.items() for word in ('--' + key, value)]

    def run_cli(self, args=None, env=None, **values):
        return subprocess.run([str(SCRIPT), *(self.arguments(**values) if args is None else args)],
                              cwd=self.directory, env=self.env if env is None else env,
                              stdin=subprocess.DEVNULL, capture_output=True)

    def assert_pass(self, result, count, commit=None, subject=None, literal=SENTINEL):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, b'')
        commit, subject = commit or self.sha, subject or self.subject
        needle = literal.encode('utf-8')
        expected = {'blob': self.git('rev-parse', f'{commit}:{subject}'), 'commit': commit,
                    'count': count, 'literal_bytes': len(needle),
                    'literal_sha256': hashlib.sha256(needle).hexdigest(),
                    'repo': str(self.repo), 'result': 'PASS', 'subject': subject}
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(result.stdout, (json.dumps(expected, sort_keys=True) + '\n').encode())
        self.assertNotIn(SENTINEL.encode(), result.stdout)

    def assert_refused(self, result, error):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, ('{"error": "' + error + '", "result": "REFUSED"}\n').encode())
        self.assertEqual(result.stderr, b'')
        self.assertNotIn(SENTINEL.encode(), result.stdout + result.stderr)

    def test_frozen_blob_ignores_later_commits_and_checkout(self):
        first = self.sha
        self.commit({self.subject: (SENTINEL + '\n') * 2})
        second = self.git('rev-parse', 'HEAD')
        (self.repo / self.subject).write_text((SENTINEL + '\n') * 3)
        self.assert_pass(self.run_cli(commit=first), 1, commit=first)
        self.assert_pass(self.run_cli(commit=second), 2, commit=second)

    def test_overlapping_matches(self):
        self.commit({self.subject: 'aaaa' + SENTINEL})
        self.sha = self.git('rev-parse', 'HEAD')
        self.assert_pass(self.run_cli(literal='aa'), 3, literal='aa')

    def test_replacement_objects_cannot_change_source(self):
        original = self.git('rev-parse', f'{self.sha}:{self.subject}')
        self.commit({'other.txt': (SENTINEL + '\n') * 4})
        replacement = self.git('rev-parse', 'HEAD:other.txt')
        self.git('replace', original, replacement)
        result = self.run_cli()
        self.git('replace', '-d', original)
        self.assert_pass(result, 1)

    def test_git_environment_cannot_select_another_repository(self):
        other = self.directory / 'other'
        self.init_repo(other)
        self.assert_pass(self.run_cli(env={**self.env, 'GIT_DIR': str(other / '.git'),
                                          'GIT_OBJECT_DIRECTORY': str(other / '.git/objects')}), 1)

    def test_partial_clone_never_fetches_missing_blob(self):
        self.git('config', 'uploadpack.allowFilter', 'true')
        partial = self.directory / 'partial'
        subprocess.run(['git', 'clone', '-q', '--filter=blob:none', '--no-checkout',
                        self.repo.as_uri(), str(partial)], env=self.env,
                       stdin=subprocess.DEVNULL, check=True)
        blob = self.git('rev-parse', f'{self.sha}:{self.subject}')
        missing = self.git('rev-list', '--objects', '--missing=print', self.sha, repo=partial)
        self.assertEqual([line for line in missing.splitlines() if line.startswith('?')],
                         ['?' + blob])
        self.assert_refused(self.run_cli(repo=str(partial)), 'git')
        missing = self.git('rev-list', '--objects', '--missing=print', self.sha, repo=partial)
        self.assertEqual([line for line in missing.splitlines() if line.startswith('?')],
                         ['?' + blob])

    def test_python_isolation_ignores_shadow_module(self):
        shadow = self.directory / 'shadow'
        shadow.mkdir()
        (shadow / 'json.py').write_text('raise SystemExit("' + SENTINEL + '")\n')
        self.assert_pass(self.run_cli(env={**self.env, 'PYTHONPATH': str(shadow)}), 1)

    def test_option_order_dash_value_unicode_and_executable_blob(self):
        literal = '-café'
        self.commit({self.subject: literal + SENTINEL})
        self.git('update-index', '--chmod=+x', self.subject)
        self.git('commit', '-m', 'Executable fixture')
        self.sha = self.git('rev-parse', 'HEAD')
        args = ['--literal', literal, '--subject', self.subject,
                '--commit', self.sha, '--repo', str(self.repo)]
        self.assert_pass(self.run_cli(args=args), 1, literal=literal)
        self.assert_pass(self.run_cli(literal='absent-literal'), 0, literal='absent-literal')

    def test_usage_refusals(self):
        args = self.arguments()
        cases = [args[:-2], ['--repo', str(self.repo), *args[2:6], '--repo', SENTINEL],
                 [*args[:6], '--unknown', SENTINEL], [*args[:6], '--literal=' + SENTINEL]]
        for case in cases:
            with self.subTest(args=case):
                self.assert_refused(self.run_cli(args=case), 'usage')

    def test_literal_refusals(self):
        for literal in ('', b'\xff'):
            with self.subTest(literal=literal):
                self.assert_refused(self.run_cli(literal=literal), 'literal')

    def test_subject_refusals(self):
        for subject in ('../x', '/x', 'src/./a.py', 'src//a.py', 'src/', '', '.'):
            with self.subTest(subject=subject):
                self.assert_refused(self.run_cli(subject=subject), 'subject')

    def test_protected_subject_refusals(self):
        for subject in ('tests/mutation/private.py', 'TESTS/MUTATION/private.py'):
            self.commit({subject: SENTINEL})
            sha = self.git('rev-parse', 'HEAD')
            self.assertTrue(self.git('cat-file', '-t', f'{sha}:{subject}') == 'blob')
            with self.subTest(subject=subject):
                self.assert_refused(self.run_cli(subject=subject, commit=sha), 'protected-subject')

    def test_sensitive_subject_refusals(self):
        for subject in ('.env', 'config/.env.local', 'certs/server.pem', 'keys/id.key',
                        'config/.GIT/a.py', 'config/.ENV.LOCAL', 'certs/SERVER.PEM', 'keys/ID.KEY'):
            with self.subTest(subject=subject):
                self.assert_refused(self.run_cli(subject=subject), 'sensitive-subject')

    def test_early_validation_precedes_git(self):
        for values, error in (({'literal': ''}, 'literal'), ({'subject': '../x'}, 'subject'),
                              ({'subject': 'tests/mutation/x'}, 'protected-subject'),
                              ({'subject': '.env'}, 'sensitive-subject')):
            with self.subTest(error=error):
                self.assert_refused(self.run_cli(repo='missing', **values), error)

    def test_repo_refusals(self):
        link = self.directory / 'link'
        link.symlink_to(self.repo, target_is_directory=True)
        plain = self.directory / 'plain'
        plain.mkdir()
        for repo in ('repo', str(link), str(self.repo / 'src'), str(plain)):
            with self.subTest(repo=repo):
                self.assert_refused(self.run_cli(repo=repo), 'repo')

    def test_commit_refusals(self):
        self.git('tag', '-a', 'fixture-tag', '-m', 'Fixture tag')
        tag = self.git('rev-parse', 'fixture-tag')
        for commit in (self.sha[:12], self.sha.upper(), 'main', tag, '0' * 40):
            with self.subTest(commit=commit):
                self.assert_refused(self.run_cli(commit=commit), 'commit')

    def test_non_regular_file_refusals(self):
        (self.repo / 'link.py').symlink_to(self.subject)
        self.git('add', '--', 'link.py')
        self.git('update-index', '--add', '--cacheinfo', f'160000,{self.sha},dependency')
        self.git('commit', '-m', 'Nonregular fixtures')
        sha = self.git('rev-parse', 'HEAD')
        for subject in ('missing.py', 'src', 'link.py', 'dependency'):
            with self.subTest(subject=subject):
                self.assert_refused(self.run_cli(subject=subject, commit=sha), 'not-regular-file')


if __name__ == '__main__':
    unittest.main()
