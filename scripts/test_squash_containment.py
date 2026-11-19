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
2. The squash tree equals the exact tree from a successful merge of the author head into the squash parent.
The checker uses `git merge-tree --write-tree` with the squash parent first and the author head second.
Require this check even when the squash parent already contains the author's changes.
The `files` field counts the paths that differ between the squash parent and the squash commit.
A path that `squash-containment.json` lists for the PR's repository may differ from that merge only when every other path matches exactly.
Such a path keeps its file mode, and the merge must change it from the squash parent.
The `PASS` line names each such path as `regenerated=<path>`; with no listed path, the exact tree rule stays.
The driver runs `python3 "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/squash-containment.py" <PR URL> <base SHA> <author head SHA> <squash SHA>` in a checkout that holds all four commits.
Accept only a recorded `PASS` line that names the same PR URL, recorded base, author head and squash commit.
Refuse the squash commit when any condition fails or the evidence is missing, stale or ambiguous.
Every other commit keeps the containment requirement unchanged.
'''


class ContractTests(unittest.TestCase):
    def test_shipped_config_lists_only_the_two_patricia_paths(self):
        config = json.loads(SCRIPT.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(config, {'bettergroupinc/patricia-monorepo': [
            'backend/api/openapi.json', 'frontend/packages/api-types/src/generated/api.ts',
        ]})

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
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$GH_JSON"\n')
        gh.chmod(0o755)
        self.env['PATH'] = f'{binary}{os.pathsep}{self.env["PATH"]}'

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, files):
        for name, text in files.items():
            (self.repo / name).write_text(text)
        self.git('add', '--', *files)
        self.git('commit', '-m', 'Fixture commit')

    def check(self, squash=None, linked=None, state='MERGED', base=None, author=None,
              script=SCRIPT, pr=PR, cwd=None):
        squash = squash or self.squash
        info = {'state': state, 'mergeCommit': {'oid': linked or squash}}
        return subprocess.run(
            [sys.executable, str(script), pr, base or self.base, author or self.author, squash],
            cwd=cwd or self.repo, env={**self.env, 'GH_JSON': json.dumps(info)},
            capture_output=True, text=True,
        )

    def script_with_config(self, config):
        script = self.directory / SCRIPT.name
        copyfile(SCRIPT, script)
        script.with_suffix('.json').write_text(json.dumps(config), encoding='utf-8')
        return script

    def regenerated_squash(self, extra=None):
        self.git('checkout', '-b', 'generated-main', self.base)
        lines = ''.join(f'line {number}\n' for number in range(30))
        self.commit({'generated.txt': lines})
        base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-b', 'generated-feature')
        self.commit({'generated.txt': lines.replace('line 5\n', 'feature line\n'),
                     'alpha.txt': 'feature alpha\n'})
        author = self.git('rev-parse', 'HEAD')
        self.git('checkout', 'generated-main')
        self.commit({'generated.txt': lines.replace('line 25\n', 'main line\n')})
        parent = self.git('rev-parse', 'HEAD')
        self.git('merge', '--squash', 'generated-feature')
        self.commit({'generated.txt': 'regenerated output\n', **(extra or {})})
        return base, author, parent, self.git('rev-parse', 'HEAD')

    def test_regenerated_path_passes_and_uses_the_repository_root(self):
        base, author, parent, squash = self.regenerated_squash()
        subdir = self.repo / 'subdir'
        subdir.mkdir()
        script = self.script_with_config({'example/repo': ['generated.txt']})
        pr = 'https://github.com/Example/Repo/pull/1'
        result = self.check(base=base, author=author, squash=squash, script=script, pr=pr, cwd=subdir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={pr} base={base} author_head={author} '
                         f'squash={squash} parent={parent} files=2 regenerated=generated.txt\n')

    def test_regenerated_path_with_a_hand_written_difference_refuses(self):
        base, author, _, squash = self.regenerated_squash({'alpha.txt': 'different alpha\n'})
        script = self.script_with_config({'example/repo': ['generated.txt']})
        self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script),
                           'squash tree differs')

    def test_listed_path_unchanged_in_clean_merge_refuses(self):
        self.commit({'unrelated.txt': 'regenerated output\n'})
        squash = self.git('commit-tree', 'HEAD^{tree}', '-p', self.parent, '-m', 'Regenerated squash')
        script = self.script_with_config({'example/repo': ['unrelated.txt']})
        result = self.check(squash=squash, script=script)
        self.assert_refuse(result, 'regenerated')
        self.assertIn('unrelated.txt', result.stdout)

    def test_regenerated_path_requires_a_config_entry_for_the_pr_repository(self):
        base, author, _, squash = self.regenerated_squash()
        for config in ({'other/repo': ['generated.txt']}, {'example/repo': []}):
            with self.subTest(config=config):
                result = self.check(base=base, author=author, squash=squash,
                                    script=self.script_with_config(config))
                self.assert_refuse(result, 'squash tree differs')
                self.assertEqual(result.stdout,
                                 "REFUSE 'squash tree differs from the clean merge of the author head'\n")

    def test_regenerated_path_requires_a_full_github_pr_url(self):
        base, author, _, squash = self.regenerated_squash()
        script = self.script_with_config({'example/repo': ['generated.txt']})
        self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script,
                                      pr=PR + '/files'), 'squash tree differs')

    def test_config_validation_applies_only_to_differing_trees(self):
        base, author, _, squash = self.regenerated_squash()
        for paths in ('generated.txt', ['generated.txt', None], ['generated.txt', ''],
                      ['generated.txt', 'with space.txt']):
            with self.subTest(paths=paths):
                script = self.script_with_config({'example/repo': paths})
                self.assert_refuse(self.check(base=base, author=author, squash=squash, script=script),
                                   'invalid regenerated paths')
                self.assertEqual(self.check(script=script).stdout, self.check().stdout)

    def test_listed_path_mode_change_or_deletion_refuses(self):
        script = self.script_with_config({'example/repo': ['alpha.txt']})
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
        script = self.script_with_config({'example/repo': ['generated.txt', 'alpha.txt']})
        result = self.check(base=base, author=author, squash=squash, script=script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f'PASS pr={PR} base={base} author_head={author} '
                         f'squash={squash} parent={parent} files=2 '
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
