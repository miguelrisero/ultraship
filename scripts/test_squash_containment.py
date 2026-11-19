"""Squash containment requires PR linkage and a clean merge with limited differences."""
import json
import os
from pathlib import Path
from shutil import copyfile
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIP = ROOT / 'plugins/ship'
SCRIPT = SHIP / 'skills/ship/scripts/squash-containment.py'
PR = 'https://github.com/example/repo/pull/1'
WORKFLOW = '.github/workflows/ci.yml'
JOB = 'Contract drift'
STEP = 'Fail on drift'
CONTRACT_PATHS = (
    SHIP / 'skills/ship/SKILL.md',
    *(SHIP / f'agents/{name}.md' for name in (
        'driver', 'driver--sol', 'reviewer--sol', 'reviewer--opus',
        'writer--sol', 'writer--sonnet', 'writer--fable52',
    )),
)
BODY = '''Apply this rule to every requirement in this file that a commit contain the author head or a commit that the author head contains.
A single-parent squash commit meets that requirement only when it contains the recorded base and all conditions below hold.
1. GitHub links the squash commit to the PR: the PR state is `MERGED` and its `mergeCommit` equals that commit.
2. The squash tree equals the exact tree from a successful merge of the author head into the squash parent, except for the listed paths below.
The checker uses `git merge-tree --write-tree` with the squash parent first and the author head second.
Require this check even when the squash parent already contains the author's changes.
The `files` field counts the paths that differ between the squash parent and the squash commit.
A path that `squash-containment.json` lists for the PR's repository may differ from that merge only when every other path matches exactly.
Such a path stays a non-executable regular file, and the author head must change it from its merge base with the squash parent.
A merge conflict may touch only such paths; the checker then treats each conflicted path as regenerated.
The squash commit also needs one passing push run of the configured drift check job and step from GitHub Actions.
The `PASS` line names the drift job as `drift_job=<id>` and each such path as `regenerated=<path>`; with no listed path, the exact tree rule stays.
The driver runs `python3 "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/squash-containment.py" <PR URL> <base SHA> <author head SHA> <squash SHA>` in a checkout that holds all four commits.
Accept only a recorded `PASS` line that names the same PR URL, recorded base, author head and squash commit.
Refuse the squash commit when any condition fails or the evidence is missing, stale or ambiguous.
Every other commit keeps the containment requirement unchanged.
'''


class ContractTests(unittest.TestCase):
    def test_shipped_config_lists_only_the_two_patricia_paths(self):
        config = json.loads(SCRIPT.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(config, {'bettergroupinc/patricia-monorepo': {
            'paths': ['backend/api/openapi.json', 'frontend/packages/api-types/src/generated/api.ts'],
            'workflow': '.github/workflows/ci.yml',
            'job': 'contract · openapi → api-types drift',
            'step': 'Fail on contract drift',
        }})

    def test_each_contract_carries_the_exact_body_once(self):
        for path in CONTRACT_PATHS:
            with self.subTest(path=path):
                text = path.read_text()
                self.assertEqual(text.count('Squash-merge containment\n'), 1)
                section = text.split('Squash-merge containment\n\n', 1)[1].split('\n\n', 1)[0]
                self.assertEqual(section + '\n', BODY)
                self.assertEqual(text.count(BODY), 1)


class SquashContainmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.repo = self.directory / 'repo'
        self.repo.mkdir()
        self.env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0'}
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):
            self.env.pop(key, None)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test Author')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.commit({'alpha.txt': 'alpha\n', 'beta.txt': 'beta\n'})
        self.base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-b', 'feature')
        self.commit({'alpha.txt': 'alpha feature\n', 'added file.txt': 'new\n'})
        self.commit({'beta.txt': 'beta feature\n'})
        self.author = self.git('rev-parse', 'HEAD')
        self.git('checkout', 'main')
        self.commit({'unrelated.txt': 'main advances\n'})
        self.parent = self.git('rev-parse', 'HEAD')
        self.git('merge', '--squash', 'feature')
        self.git('commit', '-m', 'Squash feature')
        self.squash = self.git('rev-parse', 'HEAD')
        binary = self.directory / 'bin'
        binary.mkdir()
        gh = binary / 'gh'
        self.gh_calls = self.directory / 'gh-calls'
        gh.write_text(f'#!{sys.executable}\n' + '''import json
import os
import sys

args = sys.argv[1:]
with open(os.environ['GH_CALLS'], 'a') as log:
    print(json.dumps(args), file=log)
if args[:2] == ['pr', 'view']:
    print(os.environ['GH_PR'])
else:
    assert args[:3] == ['api', '-X', 'GET']
    assert args[4:6] == ['--hostname', 'github.com']
    reply = json.loads(os.environ['GH_API'])[args[3]]
    assert args[6:] == reply.get('fields', [])
    print(json.dumps(reply['body']))
''')
        gh.chmod(0o755)
        self.env['PATH'] = f'{binary}{os.pathsep}{self.env["PATH"]}'

    def git(self, *args, input=None):
        return subprocess.run(['git', *args], cwd=self.repo, env=self.env, input=input,
                              capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, files):
        for name, text in files.items():
            (self.repo / name).write_text(text)
        self.git('add', '--', *files)
        self.git('commit', '-m', 'Fixture commit')

    def check(self, squash=None, linked=None, state='MERGED', base=None, author=None,
              script=SCRIPT, pr=PR, cwd=None, api=None):
        squash = self.squash if squash is None else squash
        info = {'state': state, 'mergeCommit': {'oid': linked or squash}}
        self.gh_calls.write_text('')
        return subprocess.run(
            [sys.executable, str(script), pr, base or self.base, author or self.author, squash],
            cwd=cwd or self.repo, env={**self.env, 'GH_PR': json.dumps(info),
                                      'GH_API': json.dumps(api or {}), 'GH_CALLS': str(self.gh_calls)},
            capture_output=True, text=True,
        )

    def drift_replies(self, squash, *candidates):
        ids = range(101, 101 + len(candidates))
        replies = {
            f'repos/example/repo/commits/{squash}/check-runs': {
                'fields': ['-f', f'check_name={JOB}', '-F', 'app_id=15368',
                           '-f', 'filter=all', '-F', 'per_page=100'],
                'body': {'total_count': len(ids), 'check_runs': [{'id': job_id} for job_id in ids]},
            },
        }
        for job_id, (job, run) in zip(ids, candidates, strict=True):
            run_id = job_id + 100
            replies[f'repos/example/repo/actions/jobs/{job_id}'] = {'body': {
                'id': job_id, 'run_id': run_id, 'head_sha': squash, 'run_attempt': 1,
                'status': 'completed', 'conclusion': 'success',
                'steps': [{'name': STEP, 'conclusion': 'success'}], **job,
            }}
            replies[f'repos/example/repo/actions/runs/{run_id}'] = {'body': {
                'path': WORKFLOW, 'event': 'push', 'head_sha': squash, 'run_attempt': 1, **run,
            }}
        return replies

    def rule(self, *paths):
        return {'paths': list(paths), 'workflow': WORKFLOW, 'job': JOB, 'step': STEP}

    def script_with_config(self, config):
        script = self.directory / SCRIPT.name
        copyfile(SCRIPT, script)
        script.with_suffix('.json').write_text(json.dumps(config), encoding='utf-8')
        return script

    def regenerated_squash(self, extra=None, executable=False, binary=False, keep_parent=False,
                           mixed_conflict=False, path='generated.txt'):
        self.git('checkout', '-b', 'generated-main', self.base)
        lines = ''.join(f'line {number}\n' for number in range(30))
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        files = {path: lines}
        if binary:
            files['.gitattributes'] = f'{path} binary -merge\n'
        self.commit(files)
        if executable:
            self.git('update-index', '--chmod=+x', path)
            self.git('commit', '-m', 'Executable fixture')
            (self.repo / path).chmod(0o755)
        base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-b', 'generated-feature')
        self.commit({path: lines.replace('line 5\n', 'feature line\n'), 'alpha.txt': 'feature alpha\n'})
        author = self.git('rev-parse', 'HEAD')
        self.git('checkout', 'generated-main')
        main_text = lines.replace('line 25\n', 'main line\n')
        files = {path: main_text}
        if mixed_conflict:
            files['alpha.txt'] = 'main alpha\n'
        self.commit(files)
        parent = self.git('rev-parse', 'HEAD')
        if binary:
            merge = subprocess.run(
                ['git', 'merge-tree', '--write-tree', parent, author],
                cwd=self.repo, env=self.env, capture_output=True,
            )
            self.assertEqual(merge.returncode, 1, merge.stdout + merge.stderr)
            self.git('checkout', author, '--', 'alpha.txt')
        else:
            self.git('merge', '--squash', 'generated-feature')
        self.commit({path: main_text if keep_parent else 'regenerated output\n', **(extra or {})})
        return base, author, parent, self.git('rev-parse', 'HEAD')

    def test_regenerated_path_passes_and_uses_the_repository_root(self):
        base, author, parent, squash = self.regenerated_squash()
        subdir = self.repo / 'subdir'
        subdir.mkdir()
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        pr = 'https://github.com/Example/Repo/pull/1'
        api = self.drift_replies(squash, ({}, {'event': 'pull_request'}), ({}, {}))
        result = self.check(base=base, author=author, squash=squash, script=script, pr=pr,
                            cwd=subdir, api=api)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={pr} base={base} author_head={author} '
                         f'squash={squash} parent={parent} files=2 drift_job=102 '
                         'regenerated=generated.txt\n')

    def test_missing_or_unusable_drift_evidence_refuses(self):
        base, author, _, squash = self.regenerated_squash()
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        cases = {
            'missing check': (),
            'failed job': (({'conclusion': 'failure'}, {}),),
            'incomplete job': (({'status': 'in_progress'}, {}),),
            'missing drift step': (({'steps': [{'name': 'Other step', 'conclusion': 'success'}]}, {}),),
            'skipped step': (({'steps': [{'name': STEP, 'conclusion': 'skipped'}]}, {}),),
            'duplicate step': (({'steps': [{'name': STEP, 'conclusion': 'success'}] * 2}, {}),),
            'wrong workflow': (({}, {'path': '.github/workflows/other.yml'}),),
            'pull request event': (({}, {'event': 'pull_request'}),),
            'wrong job SHA': (({'head_sha': author}, {}),),
            'wrong run SHA': (({}, {'head_sha': author}),),
            'old attempt': (({}, {'run_attempt': 2}),),
            'two bound runs': (({}, {}), ({}, {})),
        }
        for label, candidates in cases.items():
            with self.subTest(label=label):
                api = self.drift_replies(squash, *candidates)
                result = self.check(base=base, author=author, squash=squash, script=script, api=api)
                self.assert_refuse(result, 'drift check')
        self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script),
                           'drift check')

    def test_incomplete_drift_check_list_refuses(self):
        base, author, _, squash = self.regenerated_squash()
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        api = self.drift_replies(squash, ({}, {}))
        api[f'repos/example/repo/commits/{squash}/check-runs']['body']['total_count'] = 2
        result = self.check(base=base, author=author, squash=squash, script=script, api=api)
        self.assert_refuse(result, 'drift check')

    def test_regenerated_path_with_a_hand_written_difference_refuses(self):
        base, author, _, squash = self.regenerated_squash({'alpha.txt': 'different alpha\n'})
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script),
                           'squash tree differs')
        self.assertEqual(self.gh_calls.read_text(), '')

    def test_listed_path_unchanged_in_author_head_refuses(self):
        self.commit({'unrelated.txt': 'regenerated output\n'})
        squash = self.git('commit-tree', 'HEAD^{tree}', '-p', self.parent, '-m', 'Regenerated squash')
        script = self.script_with_config({'example/repo': self.rule('unrelated.txt')})
        result = self.check(squash=squash, script=script)
        self.assert_refuse(result, 'regenerated path unrelated.txt is unchanged in the author head')
        self.assertEqual(self.gh_calls.read_text(), '')

    def test_listed_binary_conflict_passes_with_drift_evidence(self):
        base, author, parent, squash = self.regenerated_squash(binary=True)
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        api = self.drift_replies(squash, ({}, {}))
        result = self.check(base=base, author=author, squash=squash, script=script, api=api)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={PR} base={base} author_head={author} '
                         f'squash={squash} parent={parent} files=2 drift_job=101 '
                         'regenerated=generated.txt\n')

    def test_listed_binary_conflict_passes_from_a_subdirectory(self):
        path = 'nested/generated.txt'
        base, author, parent, squash = self.regenerated_squash(binary=True, path=path)
        script = self.script_with_config({'example/repo': self.rule(path)})
        api = self.drift_replies(squash, ({}, {}))
        result = self.check(base=base, author=author, squash=squash, script=script,
                            cwd=self.repo / 'nested', api=api)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={PR} base={base} author_head={author} '
                         f'squash={squash} parent={parent} files=2 drift_job=101 regenerated={path}\n')

    def test_listed_binary_conflict_needs_drift_evidence_even_when_trees_match(self):
        base, author, _, squash = self.regenerated_squash(binary=True, keep_parent=True)
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        result = self.check(base=base, author=author, squash=squash, script=script,
                            api=self.drift_replies(squash))
        self.assert_refuse(result, 'drift check')
        result = self.check(base=base, author=author, squash=squash, script=script,
                            api=self.drift_replies(squash, ({}, {})))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.endswith(' files=1 drift_job=101 regenerated=generated.txt\n'))

    def test_unlisted_binary_conflict_refuses_before_github_calls(self):
        base, author, _, squash = self.regenerated_squash(binary=True)
        script = self.script_with_config({'example/repo': self.rule('alpha.txt')})
        result = self.check(base=base, author=author, squash=squash, script=script)
        self.assert_refuse(result, 'git command failed (exit 1)')
        self.assertEqual(self.gh_calls.read_text(), '')

    def test_mixed_listed_and_unlisted_conflicts_refuse(self):
        base, author, _, squash = self.regenerated_squash(binary=True, mixed_conflict=True)
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        result = self.check(base=base, author=author, squash=squash, script=script)
        self.assert_refuse(result, 'git command failed (exit 1)')
        self.assertEqual(self.gh_calls.read_text(), '')

    def test_regeneration_with_an_added_empty_subtree_refuses(self):
        base, author, parent, squash = self.regenerated_squash()
        blank = self.git('mktree', input='')
        entries = self.git('ls-tree', squash)
        tree = self.git('mktree', input=f'{entries}\n040000 tree {blank}\tempty\n')
        squash = self.git('commit-tree', tree, '-p', parent, '-m', 'Squash with empty subtree')
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        api = self.drift_replies(squash, ({}, {}))
        result = self.check(base=base, author=author, squash=squash, script=script, api=api)
        self.assert_refuse(result, 'squash tree differs')
        self.assertEqual(self.gh_calls.read_text(), '')

    def test_regeneration_with_two_merge_bases_refuses(self):
        base, feature, main, regenerated = self.regenerated_squash()
        main_tree = f'{main}^{{tree}}'
        author = self.git('commit-tree', main_tree, '-p', feature, '-p', main,
                          '-m', 'Feature merges main')
        parent = self.git('commit-tree', main_tree, '-p', main, '-p', feature,
                          '-m', 'Main merges feature')
        self.assertEqual(set(self.git('merge-base', '--all', parent, author).split()), {feature, main})
        squash = self.git('commit-tree', f'{regenerated}^{{tree}}', '-p', parent, '-m', 'Criss-cross squash')
        script = self.script_with_config({'example/repo': self.rule('alpha.txt', 'generated.txt')})
        api = self.drift_replies(squash, ({}, {}))
        result = self.check(base=base, author=author, squash=squash, script=script, api=api)
        self.assert_refuse(result, 'exactly one merge base')
        self.assertEqual(self.gh_calls.read_text(), '')

    def test_regenerated_path_requires_a_config_entry_for_the_pr_repository(self):
        base, author, _, squash = self.regenerated_squash()
        for config in ({'other/repo': self.rule('generated.txt')}, {'example/repo': self.rule()}):
            with self.subTest(config=config):
                result = self.check(base=base, author=author, squash=squash,
                                    script=self.script_with_config(config))
                self.assert_refuse(result, 'squash tree differs')
                self.assertEqual(result.stdout,
                                 "REFUSE 'squash tree differs from the clean merge of the author head'\n")

    def test_regenerated_path_requires_a_full_github_pr_url(self):
        base, author, _, squash = self.regenerated_squash()
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script,
                                      pr=PR + '/files'), 'squash tree differs')

    def test_config_validation_applies_only_to_differing_trees(self):
        base, author, _, squash = self.regenerated_squash()
        rule = self.rule('generated.txt')
        cases = [rule['paths'], {**rule, 'extra': True}]
        cases += [{**rule, 'paths': paths} for paths in (
            'generated.txt', ['generated.txt', None], ['generated.txt', ''],
            ['generated.txt', 'with space.txt'],
        )]
        for key in rule:
            cases += [{k: v for k, v in rule.items() if k != key}, {**rule, key: False}]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                script = self.script_with_config({'example/repo': invalid})
                self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script),
                                   'invalid regenerated path rule')
                self.assertEqual(self.gh_calls.read_text(), '')
                result = self.check(script=script)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = self.gh_calls.read_text().splitlines()
                self.assertEqual([json.loads(call)[:2] for call in calls], [['pr', 'view']])
                self.assertEqual(result.stdout, self.check().stdout)

    def test_regenerated_executable_path_refuses_even_when_mode_matches(self):
        base, author, _, squash = self.regenerated_squash(executable=True)
        script = self.script_with_config({'example/repo': self.rule('generated.txt')})
        api = self.drift_replies(squash, ({}, {}))
        self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script, api=api),
                           'squash tree differs')
        self.assertEqual(self.gh_calls.read_text(), '')

    def test_listed_path_mode_change_or_deletion_refuses(self):
        script = self.script_with_config({'example/repo': self.rule('alpha.txt')})
        self.git('update-index', '--chmod=+x', 'alpha.txt')
        tree = self.git('write-tree')
        squash = self.git('commit-tree', tree, '-p', self.parent, '-m', 'Executable squash')
        self.assert_refuse(self.check(squash=squash, script=script), 'squash tree differs')
        self.git('rm', 'alpha.txt', '-f')
        tree = self.git('write-tree')
        squash = self.git('commit-tree', tree, '-p', self.parent, '-m', 'Deleted path squash')
        self.assert_refuse(self.check(squash=squash, script=script), 'squash tree differs')

    def test_multiple_regenerated_paths_pass_in_diff_tree_order(self):
        base, author, parent, squash = self.regenerated_squash({'alpha.txt': 'regenerated alpha\n'})
        script = self.script_with_config({'example/repo': self.rule('generated.txt', 'alpha.txt')})
        api = self.drift_replies(squash, ({}, {}))
        result = self.check(base=base, author=author, squash=squash, script=script, api=api)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={PR} base={base} author_head={author} '
                         f'squash={squash} parent={parent} files=2 drift_job=101 '
                         'regenerated=alpha.txt regenerated=generated.txt\n')

    def assert_refuse(self, result, reason):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(result.stdout.startswith('REFUSE '), result.stdout)
        self.assertIn(reason, result.stdout)
        self.assertNotIn('PASS', result.stdout)

    def test_linked_equal_squash_records_full_commit_identities(self):
        result = self.check(base=self.base[:12], author=self.author[:12], squash=self.squash[:12],
                            linked=self.squash)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={PR} base={self.base} author_head={self.author} '
                         f'squash={self.squash} parent={self.parent} files=3\n')

    def test_unlinked_squash_refuses(self):
        self.assert_refuse(self.check(linked=self.parent), 'mergeCommit')

    def test_different_content_with_the_same_files_refuses(self):
        self.commit({'alpha.txt': 'different feature\n'})
        squash = self.git('commit-tree', 'HEAD^{tree}', '-p', self.parent, '-m', 'Different squash')
        self.assert_refuse(self.check(squash=squash), 'squash tree differs')

    def test_whitespace_difference_refuses(self):
        self.commit({'alpha.txt': 'alpha feature \n'})
        squash = self.git('commit-tree', 'HEAD^{tree}', '-p', self.parent, '-m', 'Whitespace squash')
        self.assert_refuse(self.check(squash=squash), 'squash tree differs')

    def test_file_mode_difference_refuses(self):
        self.git('update-index', '--chmod=+x', 'alpha.txt')
        tree = self.git('write-tree')
        squash = self.git('commit-tree', tree, '-p', self.parent, '-m', 'Executable squash')
        self.assert_refuse(self.check(squash=squash), 'squash tree differs')

    def test_main_edits_far_from_feature_hunk_allow_shifted_line_numbers(self):
        self.git('checkout', '-b', 'shifted-main', self.base)
        lines = ''.join(f'line {number}\n' for number in range(30))
        self.commit({'long.txt': lines})
        base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-b', 'shifted-feature')
        self.commit({'long.txt': lines.replace('line 25\n', 'feature line\n')})
        author = self.git('rev-parse', 'HEAD')
        self.git('checkout', 'shifted-main')
        self.commit({'long.txt': 'main prefix\n' + lines})
        self.git('merge', '--squash', 'shifted-feature')
        self.git('commit', '-m', 'Shifted squash')
        result = self.check(base=base, author=author, squash=self.git('rev-parse', 'HEAD'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith('PASS '), result.stdout)

    def test_advanced_base_and_parent_compose_with_nearby_author_edit(self):
        self.git('checkout', '-b', 'adjacent-main', self.base)
        original = 'top\nauthor old\nkeep 1\nbase old\nkeep 2\nparent old\nbottom\n'
        self.commit({'adjacent.txt': original})
        self.git('checkout', '-b', 'adjacent-feature')
        self.commit({'adjacent.txt': original.replace('author old', 'author new')})
        author = self.git('rev-parse', 'HEAD')
        self.git('checkout', 'adjacent-main')
        base_text = original.replace('base old', 'base new')
        self.commit({'adjacent.txt': base_text})
        base = self.git('rev-parse', 'HEAD')
        parent_text = base_text.replace('parent old', 'parent new')
        self.commit({'adjacent.txt': parent_text})
        parent = self.git('rev-parse', 'HEAD')
        self.git('merge', '--squash', 'adjacent-feature')
        self.git('commit', '-m', 'Adjacent squash')
        squash = self.git('rev-parse', 'HEAD')
        result = self.check(base=base, author=author, squash=squash)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={PR} base={base} author_head={author} '
                         f'squash={squash} parent={parent} files=1\n')

        merged_text = parent_text.replace('author old', 'author new')
        self.assertEqual((self.repo / 'adjacent.txt').read_text(), merged_text)
        self.commit({'adjacent.txt': merged_text.replace('parent new', 'unexplained edit')})
        wrong = self.git('commit-tree', 'HEAD^{tree}', '-p', parent, '-m', 'Wrong adjacent squash')
        self.assert_refuse(self.check(base=base, author=author, squash=wrong), 'squash tree differs')

    def test_identical_hunk_at_a_different_location_refuses(self):
        self.git('checkout', '-b', 'repeated-main', self.base)
        lines = ['same\n'] * 40
        self.commit({'repeated.txt': ''.join(lines)})
        base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-b', 'repeated-feature')
        lines[7] = 'changed\n'
        self.commit({'repeated.txt': ''.join(lines)})
        author = self.git('rev-parse', 'HEAD')
        self.git('checkout', 'repeated-main')
        lines[7], lines[27] = 'same\n', 'changed\n'
        self.commit({'repeated.txt': ''.join(lines)})
        squash = self.git('rev-parse', 'HEAD')
        self.assert_refuse(self.check(base=base, author=author, squash=squash), 'squash tree differs')

    def test_ignored_submodule_pointer_difference_refuses(self):
        self.git('checkout', '-b', 'gitlink-main', self.base)
        self.git('update-index', '--add', '--cacheinfo', f'160000,{self.base},dependency')
        self.git('commit', '-m', 'Base gitlink')
        base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-b', 'gitlink-feature')
        self.git('update-index', '--cacheinfo', f'160000,{self.author},dependency')
        self.commit({'alpha.txt': 'alpha gitlink feature\n'})
        author = self.git('rev-parse', 'HEAD')
        self.git('checkout', 'gitlink-main')
        self.git('config', 'diff.ignoreSubmodules', 'all')
        self.git('merge', '--squash', 'gitlink-feature')
        self.git('commit', '-m', 'Gitlink squash')
        equal = self.check(base=base, author=author, squash=self.git('rev-parse', 'HEAD'))
        self.assertEqual(equal.returncode, 0, equal.stdout + equal.stderr)
        self.assertTrue(equal.stdout.endswith(' files=2\n'), equal.stdout)
        self.git('update-index', '--cacheinfo', f'160000,{self.base},dependency')
        tree = self.git('write-tree')
        squash = self.git('commit-tree', tree, '-p', base, '-m', 'Omitted gitlink')
        self.assert_refuse(self.check(base=base, author=author, squash=squash), 'squash tree differs')

    def test_extra_changed_file_refuses(self):
        self.commit({'extra.txt': 'extra\n'})
        squash = self.git('commit-tree', 'HEAD^{tree}', '-p', self.parent, '-m', 'Extra squash')
        self.assert_refuse(self.check(squash=squash), 'squash tree differs')

    def test_conflicting_merge_refuses(self):
        self.git('checkout', '-b', 'conflicting-main', self.parent)
        self.commit({'alpha.txt': 'alpha main\n'})
        parent = self.git('rev-parse', 'HEAD')
        squash = self.git('commit-tree', f'{self.squash}^{{tree}}', '-p', parent, '-m', 'Resolved squash')
        self.assert_refuse(self.check(squash=squash), 'git command failed (exit 1)')

    def test_two_parent_commit_refuses(self):
        merge = self.git('commit-tree', 'HEAD^{tree}', '-p', self.parent, '-p', self.author, '-m', 'Merge')
        self.assert_refuse(self.check(squash=merge), 'exactly one parent')

    def test_open_pr_refuses(self):
        self.assert_refuse(self.check(state='OPEN'), 'state must be MERGED')

    def test_base_outside_squash_history_refuses(self):
        self.assert_refuse(self.check(base=self.author), 'git command failed')

    def test_missing_commit_refuses(self):
        self.assert_refuse(self.check(author='missing-commit'), 'git command failed')

    def test_empty_diff_that_omits_author_changes_refuses(self):
        empty = self.git('commit-tree', f'{self.parent}^{{tree}}', '-p', self.parent, '-m', 'Empty')
        self.assert_refuse(self.check(squash=empty), 'squash tree differs')

    def test_author_changes_already_in_parent_still_require_exact_tree(self):
        parent = self.squash
        empty = self.git('commit-tree', f'{parent}^{{tree}}', '-p', parent, '-m', 'Empty squash')
        result = self.check(squash=empty)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={PR} base={self.base} author_head={self.author} '
                         f'squash={empty} parent={parent} files=0\n')

        self.commit({'extra.txt': 'extra\n'})
        wrong = self.git('rev-parse', 'HEAD')
        self.assert_refuse(self.check(squash=wrong), 'squash tree differs')

    def test_wrong_argument_count_exits_two(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.repo,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('usage:', result.stderr)
        self.assertNotIn('PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
