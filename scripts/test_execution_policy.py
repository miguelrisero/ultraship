"""Agent-facing execution contracts; these checks never execute a test workload or signal a process."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


HOOK = Path(__file__).resolve().parents[1] / 'plugins/ship/hooks/ultraship.py'
spec = importlib.util.spec_from_file_location('execution_policy_hook', HOOK)
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text()


class ReviewerSearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.addCleanup(temporary.cleanup)
        self.root = str(Path(temporary.name).resolve())
        for directory in ('tests/mutation', 'pkg/tests/mutation', 'backend/api/tests/mutation', 'backend/tests/mutation',
                          'backend/api/tests/unit', 'src', 'tests/src', 'tests/unit',
                          'tests/mutation_helpers', 'home'):
            Path(self.root, directory).mkdir(parents=True, exist_ok=True)

    def decision(self, tool, arguments, agent='ship:reviewer--sol', **event):
        output = io.StringIO()
        with redirect_stdout(output):
            try:
                ultraship.pre({'agent_type': agent, 'tool_name': tool,
                               'tool_input': arguments, 'cwd': self.root, **event})
            except SystemExit as exc:
                self.assertEqual(exc.code, 0)
        return json.loads(output.getvalue())['hookSpecificOutput'] if output.getvalue() else {}

    def assert_denied(self, tool, arguments, agent='ship:reviewer--sol', **event):
        decision = self.decision(tool, arguments, agent, **event)
        self.assertEqual(decision.get('permissionDecision'), 'deny', (tool, arguments, agent))
        self.assertIn('reviewer', decision['permissionDecisionReason'].lower())

    def assert_protected(self, tool, arguments, **event):
        decision = self.decision(tool, arguments, **event)
        self.assertEqual(decision.get('permissionDecision'), 'deny', (tool, arguments))
        self.assertIn('cannot access explicit tests/mutation/', decision['permissionDecisionReason'])

    def assert_rule(self, tool, arguments, rule, **event):
        decision = self.decision(tool, arguments, **event)
        self.assertEqual(decision.get('permissionDecision'), 'deny', (tool, arguments))
        self.assertIn(rule, decision['permissionDecisionReason'])

    def assert_not_canonical(self, tool, arguments, **event):
        self.assert_rule(tool, arguments, 'exact absolute path', **event)

    def test_explicit_protected_paths_in_each_tool_argument(self):
        for protected in (self.root + '/tests/mutation/x.txt',
                          self.root + '/pkg/tests/mutation/x.txt', '**/tests/mutation/**',
                          'tests/mutation/', '!tests/mutation/**'):
            cases = [
                ('Read', {'file_path': protected}),
                ('LSP', {'operation': 'hover', 'filePath': protected}),
                ('LSP', {'operation': 'documentSymbol', 'filePath': protected}),
                ('Grep', {'path': protected, 'pattern': 'identifier'}),
                ('Grep', {'path': self.root + '/src', 'glob': protected, 'pattern': 'identifier'}),
                ('Glob', {'path': protected, 'pattern': '*.py'}),
                ('Glob', {'path': self.root + '/src', 'pattern': protected}),
            ]
            for agent in ('ship:reviewer--sol', 'reviewer--sol'):
                for tool, arguments in cases:
                    with self.subTest(path=protected, agent=agent, tool=tool, arguments=arguments):
                        self.assert_denied(tool, arguments, agent)

    def test_searches_require_directory_scope_even_after_empty_or_failed_results(self):
        cases = [('Grep', {'pattern': 'identifier'}),
                 ('Grep', {'pattern': 'identifier', 'glob': '*.py'}),
                 ('Glob', {'pattern': '**/*.py'})]
        for agent in ('ship:reviewer--sol', 'reviewer--sol'):
            for tool, arguments in cases:
                for result in (None, {'content': []}, {'is_error': True, 'content': 'synthetic error'}):
                    with self.subTest(agent=agent, tool=tool, arguments=arguments, result=result):
                        self.assert_denied(tool, arguments, agent, tool_response=result)

    def test_scoped_searches_and_near_matches_remain_available(self):
        for directory in (self.root + '/src', self.root + '/tests/mutation_helpers'):
            cases = [('Read', {'file_path': directory + '/x.txt'}),
                     ('LSP', {'operation': 'hover', 'filePath': directory + '/x.txt'}),
                     ('LSP', {'operation': 'documentSymbol', 'filePath': directory + '/x.txt'}),
                     ('Grep', {'path': directory, 'pattern': 'identifier'}),
                     ('Glob', {'path': directory, 'pattern': '**/*.py'})]
            for agent in ('ship:reviewer--sol', 'reviewer--sol'):
                for tool, arguments in cases:
                    with self.subTest(agent=agent, tool=tool, arguments=arguments):
                        self.assertEqual(self.decision(tool, arguments, agent), {})
        for tool, arguments in (
            ('Grep', {'path': self.root + '/src', 'glob': 'src/**/*.py', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/src', 'pattern': 'src/**/*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assertEqual(self.decision(tool, arguments), {})

    def test_dot_dotdot_and_repeated_slash_paths_are_not_canonical(self):
        for path in (self.root + '/tests//mutation/x.txt', self.root + '/tests/./mutation/x.txt',
                     self.root + '/tests/other/../mutation/x.txt', self.root + '/src/.', self.root + '/src/..',
                     self.root + '/src/', '//' + self.root[1:], 'src', './src', '../src', ''):
            for tool, arguments in (
                ('Read', {'file_path': path}),
                ('LSP', {'operation': 'hover', 'filePath': path}),
                ('Grep', {'path': path, 'pattern': 'identifier'}),
                ('Glob', {'path': path, 'pattern': '*.py'}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_not_canonical(tool, arguments)

    def test_malformed_reviewer_arguments_and_classifier_errors_fail_closed(self):
        for tool, field in (('Read', 'file_path'), ('LSP', 'filePath'),
                            ('Grep', 'path'), ('Grep', 'glob'), ('Glob', 'pattern')):
            for value in (None, 42, False, {}, ['src/']):
                with self.subTest(tool=tool, field=field, value=value):
                    self.assert_denied(tool, {field: value, 'path': self.root + '/src', 'operation': 'hover'}
                                       if field != 'path' else {field: value, 'operation': 'hover'})
        with patch.object(ultraship.re, 'search', side_effect=ValueError('synthetic classifier error')):
            self.assert_denied('Read', {'file_path': self.root + '/src/x.txt'})

    def test_root_home_and_current_directory_do_not_scope_searches(self):
        with patch.object(ultraship.Path, 'home', return_value=Path(self.root, 'home')):
            for directory in ('/', self.root + '/home', self.root):
                for tool, arguments in (
                    ('Grep', {'path': directory, 'pattern': 'identifier'}),
                    ('Glob', {'path': directory, 'pattern': '**/*.py'}),
                ):
                    with self.subTest(tool=tool, arguments=arguments):
                        self.assert_rule(tool, arguments, 'scope searches to an explicit path')

    def test_absolute_tilde_and_dotdot_globs_are_denied_before_any_walk(self):
        for glob in (self.root + '/src/**/*.py', '/etc/*', '!' + self.root + '/src/**', '~/**', '~',
                     '../backend/**', 'src/../../backend/**', '..', '{src,../backend}/**', '{/etc,src}/**',
                     'src/*.py ' + self.root + '/src/**'):
            for tool, arguments in (
                ('Grep', {'path': self.root + '/src', 'glob': glob, 'pattern': 'identifier'}),
                ('Glob', {'path': self.root + '/src', 'pattern': glob}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_rule(tool, arguments, 'globs relative to the search path')
        for glob in ('{a,b}/**/*.py', 'a..b/**', './**/*.py'):
            for tool, arguments in (
                ('Grep', {'path': self.root + '/src', 'glob': glob, 'pattern': 'identifier'}),
                ('Glob', {'path': self.root + '/src', 'pattern': glob}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assertEqual(self.decision(tool, arguments), {})

    def test_a_glob_never_scopes_a_search_and_a_path_does(self):
        for glob in ('src/**/*.py', 'src/./**/*.py', '*.py',
                     '**/src/*.py', '!src/**/*.py'):
            for tool, arguments in (
                ('Grep', {'glob': glob, 'pattern': 'identifier'}),
                ('Glob', {'pattern': glob}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    decision = self.decision(tool, arguments)
                    self.assertEqual(decision.get('permissionDecision'), 'deny')
                    self.assertIn('scope searches to an explicit path', decision['permissionDecisionReason'])
            for tool, arguments in (
                ('Grep', {'path': self.root + '/src', 'glob': glob, 'pattern': 'identifier'}),
                ('Glob', {'path': self.root + '/src', 'pattern': glob}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assertEqual(self.decision(tool, arguments), {})

    def test_every_mcp_tool_is_denied_for_reviewers(self):
        for tool, arguments in (
            ('mcp__fff__grep', {'query': 'src/ identifier'}),
            ('mcp__fff__multi_grep', {'patterns': ['identifier'], 'constraints': 'src/'}),
            ('mcp__fff__find_files', {'query': 'src/ identifier'}),
            ('mcp__fff__future_tool', {}),
            ('mcp__linear-server__list_issues', {}),
            ('mcp__patricia__read_file', {'path': 'tests/mutation/x.py'}),
        ):
            for agent in ('ship:reviewer--sol', 'reviewer--sol'):
                with self.subTest(tool=tool, agent=agent):
                    decision = self.decision(tool, arguments, agent)
                    self.assertEqual(decision.get('permissionDecision'), 'deny')
                    self.assertIn('Use Grep or Glob with an explicit path',
                                  decision['permissionDecisionReason'])

    def test_relative_paths_and_globs_are_denied_whatever_the_event_directory(self):
        for tool, arguments in (
            ('Read', {'file_path': '../mutation/x.txt'}),
            ('LSP', {'operation': 'hover', 'filePath': '../mutation/x.txt'}),
            ('Grep', {'path': '../mutation', 'pattern': 'identifier'}),
            ('Glob', {'path': '../unit', 'pattern': '*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_not_canonical(tool, arguments, cwd=self.root + '/tests/src')
        for tool, arguments in (
            ('Grep', {'path': self.root + '/tests/unit', 'glob': '../mutation/*.py', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/tests/unit', 'pattern': '../mutation/*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_rule(tool, arguments, 'globs relative to the search path',
                                 cwd=self.root + '/tests/src')

    def test_ancestors_of_home_or_cwd_do_not_scope_searches(self):
        with patch.object(ultraship.Path, 'home', return_value=Path(self.root, 'home')):
            for directory in ('/', str(Path(self.root).parent), self.root):
                for tool, arguments in (
                    ('Grep', {'path': directory, 'pattern': 'identifier'}),
                    ('Glob', {'path': directory, 'pattern': '**/*.py'}),
                ):
                    with self.subTest(tool=tool, arguments=arguments):
                        self.assert_rule(tool, arguments, 'scope searches to an explicit path',
                                         cwd=self.root + '/src')

    def test_a_search_root_with_a_protected_directory_is_denied_whatever_the_glob(self):
        for glob in ('tests/m*tion/**', 'tests/mut?tion/**', 'tests/[m]utation/**',
                     'tests/**/x.py', 'tests/{mutation,unit}/**',
                     'tests/test_search.py', 'backend/**/*.py'):
            for tool, arguments in (
                ('Grep', {'path': self.root + '/backend', 'glob': glob, 'pattern': 'identifier'}),
                ('Glob', {'path': self.root + '/backend', 'pattern': glob}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_protected(tool, arguments)
        for tool, arguments in (
            ('Grep', {'path': self.root + '/backend/api/tests', 'glob': '**/*.py', 'pattern': 'identifier'}),
            ('Grep', {'path': self.root + '/backend/api/tests', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/backend/api/tests', 'pattern': '**/*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_protected(tool, arguments)

    def test_a_canonical_path_to_a_bounded_directory_passes_for_every_reviewer_tool(self):
        directory = self.root + '/tests/unit'
        Path(directory, 'x.py').write_text('identifier = 1\n')
        for tool, arguments in (
            ('Read', {'file_path': directory + '/x.py'}),
            ('LSP', {'operation': 'hover', 'filePath': directory + '/x.py'}),
            ('LSP', {'operation': 'documentSymbol', 'filePath': directory + '/x.py'}),
            ('Grep', {'path': directory, 'glob': '**/*.py', 'pattern': 'identifier'}),
            ('Glob', {'path': directory, 'pattern': '**/*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assertEqual(self.decision(tool, arguments), {})

    def test_round_three_directory_scope_bypasses_are_denied(self):
        cases = (
            ('Grep', {'path': self.root + '/backend/api/tests', 'glob': '*.py',
                      'pattern': 'identifier'}, self.root),
            ('Grep', {'path': self.root + '/tests', 'glob': 'm{utation,odels}/**',
                      'pattern': 'identifier'}, self.root + '/src'),
            ('Glob', {'path': self.root + '/backend',
                      'pattern': 'te?ts/mutation/**'}, self.root),
            ('Glob', {'path': self.root + '/backend',
                      'pattern': 'tests/{mut,x}ation/**'}, self.root),
        )
        for tool, arguments, cwd in cases:
            with self.subTest(tool=tool, arguments=arguments, cwd=cwd):
                self.assert_protected(tool, arguments, cwd=cwd)

    def test_clean_search_roots_and_missing_roots_pass(self):
        for directory, glob in (('backend/api/tests/unit', '*.py'),
                                ('src', '**/*.py'), ('missing', '**/*.py')):
            for tool, arguments in (
                ('Grep', {'path': self.root + '/' + directory, 'glob': glob, 'pattern': 'identifier'}),
                ('Glob', {'path': self.root + '/' + directory, 'pattern': glob}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assertEqual(self.decision(tool, arguments), {})

    def test_walk_prunes_only_git_and_preserves_near_matches(self):
        for directory in ('.git/tests/mutation', 'node_modules/unit', 'tests/mutation_helpers'):
            Path(self.root, 'src', directory).mkdir(parents=True, exist_ok=True)
        scandir = ultraship.os.scandir
        visited = []

        def tracked_scandir(path):
            visited.append(path)
            return scandir(path)

        with patch.object(ultraship.os, 'scandir', side_effect=tracked_scandir):
            self.assertEqual(self.decision('Grep', {'path': self.root + '/src',
                                                   'glob': '**/*.py', 'pattern': 'identifier'}), {})
        self.assertIn(self.root + '/src/tests/mutation_helpers', visited)
        self.assertIn(self.root + '/src/node_modules/unit', visited)
        self.assertFalse(any('/.git' in path for path in visited))

    def test_node_modules_protected_directory_denies_the_search(self):
        Path(self.root, 'src/node_modules/vendor/tests/mutation').mkdir(parents=True)
        for tool, arguments in (
            ('Grep', {'path': self.root + '/src', 'glob': '**/*.py', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/src', 'pattern': '**/*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_denied(tool, arguments)

    def test_exclusion_globs_check_the_actual_path_scope(self):
        for tool, arguments in (
            ('Grep', {'path': self.root + '/backend/api/tests',
                      'glob': '!unit/**', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/backend/api/tests', 'pattern': '!unit/**'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_denied(tool, arguments)
        self.assertEqual(self.decision('Grep', {'path': self.root + '/src',
                                              'glob': '!unit/**', 'pattern': 'identifier'}), {})

    def test_resolved_paths_and_descendant_links_cannot_reach_protected_directories(self):
        protected = Path(self.root, 'tests/mutation')
        Path(self.root, 'protected-alias').symlink_to(protected, target_is_directory=True)
        Path(self.root, 'backend-alias').symlink_to(Path(self.root, 'backend'), target_is_directory=True)
        for tool, arguments in (
            ('Read', {'file_path': self.root + '/protected-alias/x.py'}),
            ('LSP', {'operation': 'documentSymbol', 'filePath': self.root + '/protected-alias/x.py'}),
            ('Grep', {'path': self.root + '/protected-alias', 'glob': '*.py', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/protected-alias', 'pattern': '**/*.py'}),
            ('Grep', {'path': self.root + '/backend-alias', 'glob': '**/*.py', 'pattern': 'identifier'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_not_canonical(tool, arguments)
        for target in (protected, Path(self.root, 'backend')):
            with self.subTest(target=target), tempfile.TemporaryDirectory(dir=self.root) as directory:
                Path(directory, 'alias').symlink_to(target, target_is_directory=True)
                self.assert_denied('Grep', {'path': directory, 'glob': '**/*.py', 'pattern': 'identifier'})
        protected_file = protected / 'x.py'
        protected_file.write_text('identifier = 1\n')
        Path(self.root, 'src/file-alias.py').symlink_to(protected_file)
        self.assert_denied('Grep', {'path': self.root + '/src', 'glob': '*.py', 'pattern': 'identifier'})

    def test_dotdot_after_a_link_is_not_canonical(self):
        Path(self.root, 'tests/mutation/subdir').mkdir()
        Path(self.root, 'link').symlink_to(Path(self.root, 'tests/mutation/subdir'), target_is_directory=True)
        for tool, arguments in (
            ('Read', {'file_path': self.root + '/link/../x.py'}),
            ('LSP', {'operation': 'documentSymbol', 'filePath': self.root + '/link/../x.py'}),
            ('Grep', {'path': self.root + '/link/..', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/link/..', 'pattern': '*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_not_canonical(tool, arguments)

    def test_a_path_through_a_directory_link_is_not_canonical(self):
        Path(self.root, 'src/a/b').mkdir(parents=True)
        Path(self.root, 'src/deep').symlink_to(Path(self.root, 'src/a/b'), target_is_directory=True)
        Path(self.root, 'other/t').mkdir(parents=True)
        Path(self.root, 'linked').mkdir()
        Path(self.root, 'linked/tests').symlink_to(Path(self.root, 'other/t'), target_is_directory=True)
        for path in (self.root + '/src/deep', self.root + '/src/deep/x.py',
                     self.root + '/linked/tests/x.py', self.root + '/linked/tests'):
            for tool, arguments in (
                ('Read', {'file_path': path}),
                ('LSP', {'operation': 'hover', 'filePath': path}),
                ('Grep', {'path': path, 'pattern': 'identifier'}),
                ('Glob', {'path': path, 'pattern': '*.py'}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_not_canonical(tool, arguments)

    def test_backslash_names_stay_literal_on_linux(self):
        Path(self.root, 'src/a\\b').symlink_to(Path(self.root, 'tests/mutation'), target_is_directory=True)
        for tool, arguments in (
            ('Read', {'file_path': self.root + '/src/a\\b/x.py'}),
            ('LSP', {'operation': 'hover', 'filePath': self.root + '/src/a\\b/x.py'}),
            ('Grep', {'path': self.root + '/src/a\\b', 'pattern': 'identifier'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_not_canonical(tool, arguments)
        for tool, arguments in (
            ('Grep', {'path': self.root + '/src', 'glob': 'a\\b/**', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/src', 'pattern': 'a\\b/**'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_protected(tool, arguments)
        self.assertEqual(self.decision('Read', {'file_path': self.root + r'/tests\mutation\x.txt'}), {})

    def test_lsp_allows_only_hover_and_document_symbol_on_a_safe_file(self):
        safe = self.root + '/src/x.py'
        for operation in ('hover', 'documentSymbol'):
            with self.subTest(operation=operation):
                self.assertEqual(self.decision('LSP', {'operation': operation, 'filePath': safe,
                                                      'line': 1, 'character': 1}), {})
        for operation in ('findReferences', 'goToDefinition', 'goToImplementation', 'workspaceSymbol',
                          'prepareCallHierarchy', 'incomingCalls', 'outgoingCalls', None):
            with self.subTest(operation=operation):
                arguments = {'filePath': safe, 'line': 1, 'character': 1}
                if operation:
                    arguments['operation'] = operation
                decision = self.decision('LSP', arguments)
                self.assertEqual(decision.get('permissionDecision'), 'deny')
                self.assertIn('hover and documentSymbol', decision['permissionDecisionReason'])
        self.assert_denied('LSP', {'operation': 'hover'})

    def test_a_safe_regular_file_search_root_passes_and_its_link_does_not(self):
        safe = Path(self.root, 'src/x.py')
        safe.write_text('identifier = 1\n')
        alias = Path(self.root, 'safe-file-alias.py')
        alias.symlink_to(safe)
        for tool, arguments in (
            ('Grep', {'path': str(safe), 'pattern': 'identifier'}),
            ('Glob', {'path': str(safe), 'pattern': '*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assertEqual(self.decision(tool, arguments), {})
                self.assert_not_canonical(tool, {**arguments, 'path': str(alias)})

    def test_a_walk_that_finds_tests_mutation_denies_a_brace_search(self):
        for tool, arguments in (
            ('Grep', {'path': self.root + '/tests', 'glob': 'm{utation,odels}/**', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/tests', 'pattern': 'm{utation,odels}/**'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                decision = self.decision(tool, arguments)
                self.assertEqual(decision.get('permissionDecision'), 'deny')
                self.assertIn('cannot access explicit tests/mutation/', decision['permissionDecisionReason'])

    def test_a_walk_that_finds_tests_mutation_denies_an_escaped_glob(self):
        self.assert_protected('Grep', {'path': self.root + '/backend/api', 'glob': r'tests/mut\ation/**',
                                       'pattern': 'identifier'})

    def test_a_link_named_tests_mutation_is_denied_by_its_typed_name(self):
        Path(self.root, 'linked/tests').mkdir(parents=True)
        Path(self.root, 'other/data').mkdir(parents=True)
        Path(self.root, 'other/data/x.py').write_text('identifier = 1\n')
        Path(self.root, 'linked/tests/mutation').symlink_to(Path(self.root, 'other/data'),
                                                            target_is_directory=True)
        for tool, arguments in (
            ('Grep', {'path': self.root + '/linked', 'glob': '*.py', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/linked/tests', 'pattern': 'mutation/*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_protected(tool, arguments)
        for tool, arguments in (
            ('Read', {'file_path': self.root + '/linked/tests/mutation/x.py'}),
            ('Grep', {'path': self.root + '/linked/tests/mutation', 'pattern': 'identifier'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_not_canonical(tool, arguments)

    def test_protected_names_are_matched_without_regard_to_case(self):
        Path(self.root, 'src/Tests/Mutation').mkdir(parents=True)
        for tool, arguments in (
            ('Read', {'file_path': self.root + '/tests/Mutation/x.py'}),
            ('LSP', {'operation': 'hover', 'filePath': self.root + '/TESTS/mutation/x.py'}),
            ('Grep', {'path': self.root + '/Tests/MUTATION', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/src', 'pattern': 'tests/MUTATION/**'}),
            ('Grep', {'path': self.root + '/src', 'glob': '*.py', 'pattern': 'identifier'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_protected(tool, arguments)
        self.assertEqual(self.decision('Read', {'file_path': self.root + '/tests/Mutation_helpers/x.py'}), {})

    def test_walk_scans_each_directory_once_even_through_links(self):
        Path(self.root, 'src/loop').symlink_to(Path(self.root, 'src'), target_is_directory=True)
        Path(self.root, 'src/twin').symlink_to(Path(self.root, 'src'), target_is_directory=True)
        scandir = ultraship.os.scandir
        scanned = []

        def tracked_scandir(path):
            scanned.append(path)
            return scandir(path)

        with patch.object(ultraship.os, 'scandir', side_effect=tracked_scandir):
            self.assertEqual(self.decision('Grep', {'path': self.root + '/src', 'glob': '*.py',
                                                   'pattern': 'identifier'}), {})
        self.assertEqual(scanned, [self.root + '/src'])

    def test_pre_hook_config_pins_timeout_block_and_matcher(self):
        import re

        first, entry = json.loads(read('plugins/ship/hooks/hooks.json'))['hooks']['PreToolUse'][:2]
        self.assertEqual(first['matcher'], 'Agent|Task|Bash|Edit|Write|NotebookEdit|WebSearch|mcp__bettercoding__(create_input|update_input|set_input_status)')
        self.assertEqual(entry['matcher'], '^(Read|Grep|Glob|LSP|WebFetch|mcp__fff__.*)$')
        self.assertNotIn('onFailure', first['hooks'][0])
        self.assertIn('ultraship.py" pre', first['hooks'][0]['command'])
        for tool in ('Read', 'Grep', 'Glob', 'LSP', 'WebFetch', 'mcp__fff__grep', 'mcp__linear-server__list_issues'):
            with self.subTest(first_entry=tool):
                self.assertIsNone(re.search(first['matcher'], tool))
        for tool in ('Agent', 'Task', 'Bash', 'Edit', 'Write', 'NotebookEdit', 'WebSearch', 'mcp__linear-server__list_issues'):
            with self.subTest(second_entry=tool):
                self.assertIsNone(re.search(entry['matcher'], tool))
        command = entry['hooks'][0]
        self.assertEqual(command['onFailure'], 'block')
        self.assertEqual(command['timeout'], 15)
        self.assertIn('ultraship.py" pre', command['command'])
        for tool in ('Read', 'Grep', 'Glob', 'LSP', 'WebFetch', 'mcp__fff__grep'):
            with self.subTest(tool=tool):
                self.assertTrue(re.fullmatch(entry['matcher'], tool))

    def test_walk_time_limit_is_checked_before_each_directory_is_read(self):
        arguments = {'path': self.root + '/missing', 'glob': '**/*.py', 'pattern': 'identifier'}
        for elapsed in (5.0, 5.001):
            clock = iter([0.0])
            with self.subTest(elapsed=elapsed):
                with patch.object(ultraship.time, 'monotonic', side_effect=lambda: next(clock, elapsed)):
                    decision = self.decision('Grep', arguments)
                if elapsed == 5.0:
                    self.assertEqual(decision, {})
                else:
                    self.assertEqual(decision.get('permissionDecision'), 'deny')
                    self.assertIn('narrow the search scope', decision['permissionDecisionReason'])

    def test_walk_time_limit_is_checked_inside_a_large_directory(self):
        import types

        top = self.root + '/src'
        real_scandir = ultraship.os.scandir

        def fake_scandir(path):
            if str(path) != top:
                return real_scandir(path)
            return [types.SimpleNamespace(name=f'f{index}.py', path=f'{top}/f{index}.py',
                                          is_symlink=lambda: False, is_dir=lambda follow_symlinks=True: False)
                    for index in range(count)]

        arguments = {'path': top, 'glob': '**/*.py', 'pattern': 'identifier'}
        for count, elapsed, denied in ((255, 5.001, False), (256, 5.0, False), (256, 5.001, True)):
            clock = iter([0.0, 0.0])
            with self.subTest(count=count, elapsed=elapsed):
                with patch.object(ultraship.os, 'scandir', side_effect=fake_scandir), \
                        patch.object(ultraship.time, 'monotonic', side_effect=lambda: next(clock, elapsed)):
                    decision = self.decision('Grep', arguments)
                if denied:
                    self.assertEqual(decision.get('permissionDecision'), 'deny')
                    self.assertIn('narrow the search scope', decision['permissionDecisionReason'])
                else:
                    self.assertEqual(decision, {})

    def test_surrounding_whitespace_is_not_canonical(self):
        for path in ('   ', ' ', ' ' + self.root + '/backend', self.root + '/backend\t', self.root + '/src\n',
                     '\N{ZERO WIDTH NO-BREAK SPACE}' + self.root + '/src',
                     self.root + '/src\N{ZERO WIDTH NO-BREAK SPACE}',
                     '\N{NO-BREAK SPACE}' + self.root + '/src'):
            for tool, arguments in (
                ('Read', {'file_path': path}),
                ('LSP', {'operation': 'hover', 'filePath': path}),
                ('Grep', {'path': path, 'pattern': 'identifier'}),
                ('Glob', {'path': path, 'pattern': '*.py'}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_not_canonical(tool, arguments)

    def test_a_non_normal_unicode_path_is_not_canonical_and_the_normal_form_passes(self):
        decomposed = self.root + '/src/cafe\N{COMBINING ACUTE ACCENT}/x.py'
        composed = self.root + '/src/caf\N{LATIN SMALL LETTER E WITH ACUTE}/x.py'
        for tool, arguments in (
            ('Read', {'file_path': decomposed}),
            ('LSP', {'operation': 'hover', 'filePath': decomposed}),
            ('Grep', {'path': decomposed, 'pattern': 'identifier'}),
            ('Glob', {'path': decomposed, 'pattern': '*.py'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_not_canonical(tool, arguments)
        self.assertEqual(self.decision('Read', {'file_path': composed}), {})

    def test_tilde_paths_are_not_canonical(self):
        for path in ('~', '~/', '~/backend', '~/.claude/CLAUDE.md', '~root/x'):
            for tool, arguments in (
                ('Read', {'file_path': path}),
                ('LSP', {'operation': 'hover', 'filePath': path}),
                ('Grep', {'path': path, 'pattern': 'identifier'}),
                ('Glob', {'path': path, 'pattern': '*.py'}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_not_canonical(tool, arguments)

    def test_session_transcripts_under_the_claude_projects_directory_are_denied(self):
        environment = patch.dict('os.environ', {'CLAUDE_CONFIG_DIR': ''})
        environment.start()
        self.addCleanup(environment.stop)
        projects = Path(self.root, 'home/.claude/projects/p')
        projects.mkdir(parents=True)
        Path(self.root, 'home/.claude/CLAUDE.md').write_text('rules\n')
        with patch.object(ultraship.Path, 'home', return_value=Path(self.root, 'home')):
            for path in (self.root + '/home/.claude/projects', str(projects), str(projects / 'session.jsonl'),
                         self.root + '/home/.CLAUDE/Projects/p'):
                for tool, arguments in (
                    ('Read', {'file_path': path}),
                    ('LSP', {'operation': 'hover', 'filePath': path}),
                    ('Grep', {'path': path, 'pattern': 'identifier'}),
                    ('Glob', {'path': path, 'pattern': '*.jsonl'}),
                ):
                    with self.subTest(tool=tool, arguments=arguments):
                        self.assert_rule(tool, arguments, 'session transcripts')
            for tool, arguments in (
                ('Grep', {'path': self.root + '/home/.claude', 'pattern': 'identifier'}),
                ('Glob', {'path': self.root + '/home/.claude', 'pattern': '**/*.jsonl'}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_rule(tool, arguments, 'session transcripts')
            self.assertEqual(self.decision('Read', {'file_path': self.root + '/home/.claude/CLAUDE.md'}), {})

    def test_web_fetch_urls_are_checked_for_the_protected_name_after_decoding(self):
        for url in ('https://example.com/o/r/blob/main/tests/mutation/rows.toml',
                    'https://example.com/o/r/blob/main/tests%2Fmutation%2Frows.toml',
                    'https://example.com/o/r/blob/main/tests%2fMUTATION',
                    'https://example.com/o/r/blob/main/tests%252Fmutation%252Frows.toml',
                    'https://example.com/raw?path=tests%2Fmutation'):
            with self.subTest(url=url):
                self.assert_protected('WebFetch', {'url': url, 'prompt': 'summarize'})
        for url in ('https://example.com/docs/tests/mutation_helpers/x', 'https://example.com/docs'):
            with self.subTest(url=url):
                self.assertEqual(self.decision('WebFetch', {'url': url, 'prompt': 'summarize'}), {})
        self.assert_denied('WebFetch', {'url': 42, 'prompt': 'summarize'})

    def admit(self, agent_id='agent-1', ahead=3600, body_agent=None, **record):
        folder = Path(self.root, 'state/row-review')
        folder.mkdir(parents=True, exist_ok=True)
        row = Path(self.root, 'tests/mutation/rows.toml')
        row.write_text('row')
        expires = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + ahead))
        fields = {'pr': 'https://github.com/o/r/pull/1', 'agent_id': body_agent or agent_id,
                  'row_files': [str(row)], 'expires_at': expires, **record}
        path = folder / (agent_id + '.json')
        path.write_text(json.dumps(fields))
        path.chmod(0o600)
        return path, row

    def admitted_decision(self, tool, arguments, agent_id='agent-1'):
        with patch.object(ultraship, 'STATE', Path(self.root, 'state')):
            return self.decision(tool, arguments, agent_id=agent_id)

    def assert_unadmitted(self, tool, arguments, unmet, agent_id='agent-1'):
        decision = self.admitted_decision(tool, arguments, agent_id)
        self.assertEqual(decision.get('permissionDecision'), 'deny', (tool, arguments))
        reason = decision['permissionDecisionReason']
        self.assertIn('cannot access explicit tests/mutation/', reason)
        self.assertIn(str(Path(self.root, 'state/row-review', agent_id + '.json')), reason)
        self.assertIn(unmet, reason)

    def test_a_valid_admission_record_admits_read_and_grep_of_the_exact_row_file(self):
        path, row = self.admit()
        for tool, arguments in (
            ('Read', {'file_path': str(row)}),
            ('Grep', {'path': str(row), 'pattern': 'row'}),
        ):
            with self.subTest(tool=tool):
                self.assertEqual(self.admitted_decision(tool, arguments), {})
        self.admit(ahead=4 * 3600 - 120)
        self.assertEqual(self.admitted_decision('Read', {'file_path': str(row)}), {})

    def test_a_missing_record_or_a_missing_agent_id_denies_the_row_read(self):
        missing = 'the record is missing or is a link'
        row = Path(self.root, 'tests/mutation/rows.toml')
        row.write_text('row')
        for tool, arguments in (
            ('Read', {'file_path': str(row)}),
            ('Grep', {'path': str(row), 'pattern': 'row'}),
        ):
            with self.subTest(tool=tool):
                self.assert_unadmitted(tool, arguments, missing)
        self.admit()
        self.assert_unadmitted('Read', {'file_path': str(row)}, missing, agent_id='agent-2')
        with patch.object(ultraship, 'STATE', Path(self.root, 'state')):
            decision = self.decision('Read', {'file_path': str(row)})
        self.assertEqual(decision.get('permissionDecision'), 'deny')
        self.assertIn('No admission record can match', decision['permissionDecisionReason'])

    def test_a_record_that_misses_a_condition_denies_the_read_by_that_condition(self):
        row = str(Path(self.root, 'tests/mutation/rows.toml'))
        other = Path(self.root, 'tests/mutation/other.toml')
        other.write_text('row')
        expiry = '`expires_at` is later than now and at most 4 hours ahead'
        expiry_text = '`expires_at` is a UTC time'
        pr = '`pr` is a GitHub pull request URL'
        files = '`row_files` lists canonical absolute paths'
        cases = {
            'expired': ({'ahead': -60}, expiry),
            'more than four hours ahead': ({'ahead': 5 * 3600}, expiry),
            'expiry is not a time': ({'expires_at': 'tomorrow'}, expiry_text),
            'expiry has no Z': ({'expires_at': '2099-01-01T00:00:00'}, expiry_text),
            'pr is an issue URL': ({'pr': 'https://github.com/o/r/issues/1'}, pr),
            'pr has a suffix': ({'pr': 'https://github.com/o/r/pull/1/files'}, pr),
            'pr is not a string': ({'pr': 7}, pr),
            'the record body names another agent': ({'body_agent': 'agent-2'}, '`agent_id` equals your agent ID'),
            'no row files': ({'row_files': []}, files),
            'row files is not a list': ({'row_files': row}, files),
            'a row file is outside tests/mutation': ({'row_files': [row, str(Path(self.root, 'src/x.py'))]}, files),
            'a row file is not canonical': ({'row_files': [row, str(other.parent) + '/./other.toml']}, files),
            'the path is not listed': ({'row_files': [str(other)]}, 'the path equals one `row_files` entry'),
            'record is over 64 KiB': ({'pad': 'x' * 70000}, 'regular file that you own'),
        }
        for name, (record, unmet) in cases.items():
            self.admit(**record)
            for tool, arguments in (
                ('Read', {'file_path': row}),
                ('Grep', {'path': row, 'pattern': 'row'}),
            ):
                with self.subTest(case=name, tool=tool):
                    self.assert_unadmitted(tool, arguments, unmet)

    def test_a_listed_row_file_that_does_not_exist_denies_the_read(self):
        gone = str(Path(self.root, 'tests/mutation/gone.toml'))
        self.admit(row_files=[gone])
        for tool, arguments in (
            ('Read', {'file_path': gone}),
            ('Grep', {'path': gone, 'pattern': 'row'}),
        ):
            with self.subTest(tool=tool):
                self.assert_unadmitted(tool, arguments, 'the listed row file is a regular file')

    def test_a_linked_writable_or_malformed_record_denies_the_read(self):
        arguments = {'file_path': str(Path(self.root, 'tests/mutation/rows.toml'))}
        for mode in (0o660, 0o606, 0o666):
            path, _ = self.admit()
            path.chmod(mode)
            with self.subTest(mode=oct(mode)):
                self.assert_unadmitted('Read', arguments, 'not group or world writable')
        path, _ = self.admit()
        real = path.with_name('real-record.json')
        path.rename(real)
        path.symlink_to(real)
        with self.subTest(case='link'):
            self.assert_unadmitted('Read', arguments, 'the record is missing or is a link')
        path.unlink()
        for name, text in (('array', '[]'), ('not json', 'not json'), ('empty', '')):
            path.write_text(text)
            path.chmod(0o600)
            with self.subTest(case=name):
                self.assert_unadmitted('Read', arguments, 'it is a JSON object')

    def test_a_valid_record_admits_nothing_beyond_read_and_grep_of_the_listed_file(self):
        path, row = self.admit()
        other = Path(self.root, 'tests/mutation/other.toml')
        other.write_text('row')
        for tool, arguments in (
            ('Glob', {'path': str(row), 'pattern': '*.toml'}),
            ('Glob', {'path': str(row.parent), 'pattern': '*.toml'}),
            ('LSP', {'operation': 'hover', 'filePath': str(row)}),
            ('Grep', {'path': str(row), 'glob': '*.toml', 'pattern': 'row'}),
            ('Grep', {'path': str(row), 'type': 'toml', 'pattern': 'row'}),
            ('Read', {'file_path': str(row), 'filePath': str(row)}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_unadmitted(tool, arguments, 'only Read of a listed row file')
        for tool, arguments in (
            ('Grep', {'path': str(row.parent), 'pattern': 'row'}),
            ('Read', {'file_path': str(other)}),
            ('Grep', {'path': str(other), 'pattern': 'row'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_unadmitted(tool, arguments, 'the path equals one `row_files` entry')

    def test_only_the_driver_and_the_main_session_write_admission_records(self):
        state = Path(self.root, 'state')
        (state / 'row-review').mkdir(parents=True)
        Path(self.root, 'src/records-link').symlink_to(state / 'row-review', target_is_directory=True)
        record = str(state / 'row-review/agent-1.json')
        with patch.object(ultraship, 'STATE', state):
            for agent in ('ship:writer--sol', 'writer--sonnet', 'ship:reviewer--sol', 'ship:researcher--luna'):
                for tool, arguments in (
                    ('Write', {'file_path': record, 'content': '{}'}),
                    ('Edit', {'file_path': record, 'old_string': 'a', 'new_string': 'b'}),
                    ('NotebookEdit', {'notebook_path': record, 'new_source': 'x'}),
                    ('Write', {'file_path': self.root + '/src/records-link/agent-1.json', 'content': '{}'}),
                    ('Write', {'file_path': 'state/row-review/agent-1.json', 'content': '{}'}),
                    ('Write', {'file_path': str(state / 'ROW-REVIEW/Agent-1.json'), 'content': '{}'}),
                ):
                    with self.subTest(agent=agent, tool=tool, arguments=arguments):
                        decision = self.decision(tool, arguments, agent)
                        self.assertEqual(decision.get('permissionDecision'), 'deny')
                        self.assertIn('admission records', decision['permissionDecisionReason'])
            for agent in (None, 'ship:driver', 'ship:driver--sol'):
                with self.subTest(agent=agent):
                    self.assertEqual(self.decision('Write', {'file_path': record, 'content': '{}'}, agent), {})

    def test_bash_naming_the_record_folder_is_denied_for_every_agent_except_the_driver(self):
        for command in ('ls ~/.local/state/ultraship/row-review', 'rm -f /x/ultraship/row-review/agent-1.json',
                        'ls /X/ULTRASHIP/ROW-REVIEW'):
            for agent in ('ship:writer--sol', 'ship:researcher--luna', 'ship:reviewer--sol', 'ship:planner--sol'):
                with self.subTest(command=command, agent=agent):
                    decision = self.decision('Bash', {'command': command}, agent)
                    self.assertEqual(decision.get('permissionDecision'), 'deny')
                    self.assertIn('custody rule', decision['permissionDecisionReason'])
            for agent in (None, 'ship:driver'):
                with self.subTest(command=command, agent=agent):
                    self.assertEqual(self.decision('Bash', {'command': command}, agent), {})

    def test_claude_data_copies_are_denied_but_claude_md_and_plugin_caches_stay_readable(self):
        home = Path(self.root, 'home')
        history = home / '.claude/file-history/s'
        history.mkdir(parents=True)
        (history / 'abc@v1').write_text('row')
        (home / '.claude/CLAUDE.md').write_text('rules')
        for kind in ('cache', 'marketplaces'):
            (home / '.claude/plugins' / kind / 'x').mkdir(parents=True)
            (home / '.claude/plugins' / kind / 'x/SKILL.md').write_text('skill')
        (home / '.claude/plugins/store').mkdir(parents=True)
        (home / '.claude/plugins/store/x.json').write_text('row')
        config = Path(self.root, 'config')
        (config / 'file-history').mkdir(parents=True)
        (config / 'file-history/abc@v1').write_text('row')
        (config / 'CLAUDE.md').write_text('rules')
        (config / 'plugins/cache/x').mkdir(parents=True)
        (config / 'plugins/cache/x/SKILL.md').write_text('skill')
        (config / 'plugins/store').mkdir(parents=True)
        (config / 'plugins/store/x.json').write_text('row')
        denied_home = (history, history / 'abc@v1', home / '.claude/file-history', home / '.claude/plugins',
                       home / '.claude/plugins/store', home / '.claude/plugins/store/x.json')
        allowed_home = (home / '.claude/CLAUDE.md', home / '.claude/plugins/cache/x/SKILL.md',
                        home / '.claude/plugins/marketplaces/x/SKILL.md', home / '.claude/plugins/cache/x')
        with patch.dict('os.environ', {'HOME': str(home), 'CLAUDE_CONFIG_DIR': ''}):
            for path in denied_home:
                for tool, arguments in (
                    ('Read', {'file_path': str(path)}),
                    ('Grep', {'path': str(path), 'pattern': 'row'}),
                ):
                    with self.subTest(tool=tool, arguments=arguments):
                        self.assert_rule(tool, arguments, 'Claude Code data')
            for path in allowed_home:
                tool, key = ('Grep', 'path') if path.is_dir() else ('Read', 'file_path')
                with self.subTest(path=str(path)):
                    self.assertEqual(self.decision(tool, {key: str(path), 'pattern': 'skill'}), {})
        with patch.dict('os.environ', {'HOME': str(home), 'CLAUDE_CONFIG_DIR': str(config)}):
            for path in (config / 'file-history/abc@v1', config / 'file-history', config, config / 'plugins/store/x.json',
                         history / 'abc@v1', home / '.claude/file-history', home / '.claude/plugins/store/x.json'):
                for tool, arguments in (
                    ('Read', {'file_path': str(path)}),
                    ('Grep', {'path': str(path), 'pattern': 'row'}),
                ):
                    with self.subTest(tool=tool, arguments=arguments):
                        self.assert_rule(tool, arguments, 'Claude Code data')
            for path in (config / 'CLAUDE.md', config / 'plugins/cache/x/SKILL.md', home / '.claude/CLAUDE.md'):
                with self.subTest(path=str(path)):
                    self.assertEqual(self.decision('Read', {'file_path': str(path)}), {})

    def test_a_path_with_a_git_segment_is_denied_and_the_walk_skips_git_folders(self):
        Path(self.root, 'src/.git/rr-cache').mkdir(parents=True)
        Path(self.root, 'src/.git/rr-cache/preimage').write_text('row')
        Path(self.root, 'src/.git/tests/mutation').mkdir(parents=True)
        for tool, arguments in (
            ('Read', {'file_path': self.root + '/src/.git/rr-cache/preimage'}),
            ('LSP', {'operation': 'hover', 'filePath': self.root + '/src/.git/rr-cache/preimage'}),
            ('Grep', {'path': self.root + '/src/.git', 'pattern': 'row'}),
            ('Glob', {'path': self.root + '/src/.git/rr-cache', 'pattern': '*'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_rule(tool, arguments, '`.git` paths')
        self.assertEqual(self.decision('Grep', {'path': self.root + '/src', 'pattern': 'row'}), {})

    def test_a_failure_inside_pre_blocks_only_reviewers(self):
        self.assertIn("'pre': guarded_pre", read('plugins/ship/hooks/ultraship.py'))
        for agent, blocked in (('ship:reviewer--sol', True), ('reviewer--opus', True), ('ship:researcher--luna', False),
                               ('ship:writer--sol', False), (None, False)):
            output = io.StringIO()
            with self.subTest(agent=agent), patch.object(ultraship, 'pre', side_effect=RuntimeError('synthetic')), \
                    patch.object(ultraship.traceback, 'print_exc') as printed:
                with redirect_stdout(output):
                    try:
                        ultraship.guarded_pre({'agent_type': agent, 'tool_name': 'Read', 'tool_input': {'file_path': '/x'}})
                    except SystemExit as exc:
                        self.assertEqual(exc.code, 0)
                printed.assert_called_once()
                if blocked:
                    decision = json.loads(output.getvalue())['hookSpecificOutput']
                    self.assertEqual(decision['permissionDecision'], 'deny')
                    self.assertIn('hook fails', decision['permissionDecisionReason'])
                else:
                    self.assertEqual(output.getvalue(), '')

    def test_a_link_path_without_dotdot_is_not_canonical_and_names_a_safe_real_path(self):
        Path(self.root, 'src-link').symlink_to(Path(self.root, 'src'), target_is_directory=True)
        Path(self.root, 'mutation-link').symlink_to(Path(self.root, 'tests/mutation'), target_is_directory=True)
        for path in (self.root + '/src-link', self.root + '/src-link/x.py'):
            for tool, arguments in (
                ('Read', {'file_path': path}),
                ('LSP', {'operation': 'hover', 'filePath': path}),
                ('Grep', {'path': path, 'pattern': 'identifier'}),
                ('Glob', {'path': path, 'pattern': '*.py'}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assert_not_canonical(tool, arguments)
        self.assert_rule('Read', {'file_path': self.root + '/src-link/x.py'}, 'The real path is ' + self.root + '/src/x.py')
        decision = self.decision('Read', {'file_path': self.root + '/mutation-link/x.py'})
        self.assertEqual(decision.get('permissionDecision'), 'deny')
        self.assertNotIn('real path', decision['permissionDecisionReason'])
        self.assert_rule('Read', {'file_path': self.root + '/src/cafe\N{COMBINING ACUTE ACCENT}/x.py'}, 'NFC')

    def test_escaped_and_brace_globs_pass_in_a_folder_without_tests_mutation(self):
        for glob in (r'tests/mut\ation/**', 'tests/m{utation,odels}/**'):
            for tool, arguments in (
                ('Grep', {'path': self.root + '/src', 'glob': glob, 'pattern': 'identifier'}),
                ('Glob', {'path': self.root + '/src', 'pattern': glob}),
            ):
                with self.subTest(tool=tool, arguments=arguments):
                    self.assertEqual(self.decision(tool, arguments), {})
        for tool, arguments in (
            ('Grep', {'path': self.root + '/src', 'glob': 'tests/mutation/**', 'pattern': 'identifier'}),
            ('Glob', {'path': self.root + '/src', 'pattern': 'tests/mutation/**'}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assert_protected(tool, arguments)

    def test_a_dot_segment_or_backslash_hidden_in_a_web_fetch_url_is_denied(self):
        base = 'https://example.com/o/r/blob/main/'
        for url in (base + 'tests/%2e/mutation/rows.toml',
                    base + 'tests/%2E/mutation/rows.toml',
                    base + 'tests/x/%2e%2e/mutation/rows.toml',
                    base + 'tests/%252e/mutation/rows.toml',
                    base + 'tests%5Cmutation%5Crows.toml',
                    base + 'tests' + chr(92) + 'mutation' + chr(92) + 'rows.toml'):
            with self.subTest(url=url):
                self.assert_protected('WebFetch', {'url': url, 'prompt': 'summarize'})
        url = base + 'tests/x/mutation_helpers.toml'
        self.assertEqual(self.decision('WebFetch', {'url': url, 'prompt': 'summarize'}), {})

    def test_walk_bound_accepts_limit_and_denies_one_more_directory(self):
        import types

        top = self.root + '/src/wide'
        inodes = {}
        real_stat, real_scandir = ultraship.os.stat, ultraship.os.scandir

        def fake_stat(path, *args, **kwargs):
            if not str(path).startswith(top):
                return real_stat(path, *args, **kwargs)
            return types.SimpleNamespace(st_mode=ultraship.stat.S_IFDIR, st_dev=1,
                                         st_ino=inodes.setdefault(str(path), len(inodes)))

        def fake_scandir(path):
            if not str(path).startswith(top):
                return real_scandir(path)
            if str(path) != top:
                return []
            return [types.SimpleNamespace(name=f'd{index}', path=f'{top}/d{index}',
                                          is_symlink=lambda: False, is_dir=lambda follow_symlinks=True: True)
                    for index in range(count - 1)]

        arguments = {'path': top, 'glob': '**/*.py', 'pattern': 'identifier'}
        for count in (20000, 20001):
            with self.subTest(count=count), patch.multiple(ultraship.os, stat=fake_stat, scandir=fake_scandir):
                with patch.object(ultraship.time, 'monotonic', return_value=0.0):
                    decision = self.decision('Grep', arguments)
                if count == 20000:
                    self.assertEqual(decision, {})
                else:
                    self.assertEqual(decision.get('permissionDecision'), 'deny')
                    self.assertIn('narrow the search scope', decision['permissionDecisionReason'])

    def test_walk_errors_fail_closed(self):
        with patch.object(ultraship.os, 'scandir', side_effect=PermissionError('synthetic inaccessible scope')):
            decision = self.decision('Grep', {'path': self.root + '/src', 'pattern': 'identifier'})
        self.assertEqual(decision.get('permissionDecision'), 'deny')
        self.assertIn('search scope validation fails', decision['permissionDecisionReason'])

    def test_every_reviewer_suffix_uses_the_shared_role_boundary(self):
        suffixes = [path.stem for path in (ROOT / 'plugins/ship/agents').glob('reviewer--*.md')]
        self.assertTrue(suffixes)
        for suffix in suffixes:
            for prefix in ('', 'ship:'):
                with self.subTest(agent=prefix + suffix):
                    self.assert_denied('Grep', {'pattern': 'identifier'}, prefix + suffix)

    def test_other_roles_and_existing_denials_keep_their_decisions(self):
        for agent in ('ship:writer--sol', 'ship:researcher--luna', 'Explore'):
            with tempfile.TemporaryDirectory(dir=ROOT.parent) as state, patch.object(ultraship, 'STATE', Path(state)):
                self.assertEqual(self.decision('Grep', {'pattern': 'identifier'}, agent), {})
        decision = self.decision('Bash', {'command': 'git push origin HEAD'}, 'ship:writer--sol')
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('Writers never push', decision['permissionDecisionReason'])
        decision = self.decision('Agent', {'subagent_type': 'ship:reviewer--sol', 'model': 'opus'})
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('ship agents pin their own model.', decision['permissionDecisionReason'])
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as state, patch.object(ultraship, 'STATE', Path(state)):
            for _ in range(40):
                self.assertEqual(self.decision('Grep', {'pattern': 'identifier'}, 'ship:researcher--luna'), {})
            decision = self.decision('Grep', {'pattern': 'identifier'}, 'ship:researcher--luna')
            self.assertEqual(decision['permissionDecision'], 'deny')
            self.assertIn('Research budget of 40 discovery calls is spent.', decision['permissionDecisionReason'])

    def test_dispatch_contract_covers_replacements_and_failed_searches(self):
        for path in ('plugins/ship/skills/review/SKILL.md',
                     'plugins/ship/skills/panel/SKILL.md',
                     'plugins/ship/skills/ship/references/pipeline.md'):
            text = read(path)
            with self.subTest(path=path):
                for requirement in (
                    'Every initial, verification, and replacement brief lists permitted paths and exclusions.',
                    'Scope every search call to the permitted paths.',
                    'Exclude `tests/mutation/`, generated and vendored content, and any other brief exclusions.',
                    'Reviewers use Grep, Glob, and Read with exact absolute paths.',
                    'Reviewers use LSP hover and documentSymbol on one file only.',
                    'Reviewers use no MCP (`mcp__`) tools.',
                    'Reviewers search only directories that contain no `tests/mutation/` directory.',
                    'Report a failed or empty scoped search to the coordinator; never widen the search scope.',
                    'An explicit repository-root path does not authorize broader discovery.',
                ):
                    self.assertIn(requirement, text)


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

    def test_each_writer_carries_the_same_scoped_native_file_recipe(self):
        import re

        requirements = (
            ('Native Read requires ordinary-content authority before any effective refusal', (
                'native read', 'authorized ordinary content', 'before any effective refusal',
            )),
            ('Native Edit requires an absolute path and one unique exact replacement', (
                'native edit', 'absolute path', 'replace_all=false', 'one unique exact match',
            )),
            ('Uncertain authority, scope or match requires stopping and reporting to the driver', (
                'if authority, scope or match is uncertain, stop the operation and report it to the driver',
            )),
            ('Protected content retains its grants and review without added access', (
                'protected content', 'exact existing grants', 'independent review', 'zero protected access',
            )),
            ('An effective refusal blocks equivalent operations and substitute actors', (
                'effective refusal', 'blocks equivalent native reads', 'native edits',
                'alternate execution', 'substitute actors',
            )),
            ('The recipe requires verification of the exact brief scope', (
                "verify the brief's exact file scope",
            )),
            ('The recipe requires applicable operation authority', (
                'applicable operation authority',
            )),
            ('The ordinary recipe applies before effective holds', (
                'before any effective refusal or hold',
            )),
            ('Source delivery grants zero session adoption authority', (
                'zero session adoption authority',
            )),
            ('Source delivery grants zero affected-retry authority', (
                'zero affected-retry authority',
            )),
        )
        sections = []
        for name in ('writer--sol.md', 'writer--sonnet.md', 'writer--fable52.md'):
            with self.subTest(path=name):
                text = read('plugins/ship/agents/' + name)
                heading = '\n### Native file edits\n'
                section = re.split(r'\n#{1,3} ', text.partition(heading)[2], maxsplit=1)[0]
                sections.append(section)
                self.assertIn(heading, text, f'{name}: requires the Native file edits section')
                self.assertIn(
                    'After a method-only denial, apply the owner-decisions method-only rule: '
                    'one native Edit of the already-approved text, then a separate commit step.',
                    section,
                    f'{name}: requires the complete method-only denial rule in the recipe',
                )
                normalized = ' '.join(section.lower().replace('`', '').split())
                for message, phrases in requirements:
                    for phrase in phrases:
                        with self.subTest(requirement=message, phrase=phrase):
                            self.assertIn(phrase, normalized, f'{name}: {message}; missing {phrase!r}')
                first_step = re.search(r'(?m)^[ \t]*\d+[.)][ \t]+', section)
                self.assertIsNotNone(first_step, f'{name}: requires numbered native-file steps')
                warning = ' '.join(section[:first_step.start()].lower().replace('`', '').split())
                for phrase in requirements[4][1]:
                    with self.subTest(warning_phrase=phrase):
                        self.assertIn(
                            phrase, warning,
                            f'{name}: the complete refusal warning must precede the first numbered step',
                        )
        self.assertEqual(
            len(set(sections)), 1,
            'All three writers must carry identical Native file edits sections',
        )
