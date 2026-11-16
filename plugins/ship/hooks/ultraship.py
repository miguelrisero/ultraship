#!/usr/bin/env python3
"""Ultraship hooks. Usage: ultraship.py pre|subagent-stop|stop|compact < hook-input.json"""
import ast
import calendar
import fcntl
import fnmatch
import hashlib
import importlib.util
import json
import os
import posixpath
import re
import shlex
import stat
import sys
import time
import traceback
import unicodedata
import urllib.parse
import uuid
from pathlib import Path, PurePosixPath

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'ultraship'
RESEARCH_BUDGET = 40
ROW_REVIEW_PR = re.compile(r'https://github\.com/[\w.-]+/[\w.-]+/pull/\d+', re.ASCII)
ROW_REVIEW_MAX_AHEAD = 4 * 3600
PROTECTED_ROW = r'(?<![\w.-])tests/mutation(/|$)'
ROW_RECORD_FOLDERS = ('row-review', 'row-reanchor')
DISCOVERY = re.compile(r'^(Read|Grep|Glob|LSP|WebFetch|WebSearch|mcp__fff__\w+)$')
# ponytail: a command-string match, so a writer can still reach these through a script it writes,
# an alias or function, `eval`, or encoded text such as `$'\x70ush'` or base64.
# Upgrade path: run writers in a sandbox without push credentials.
# Quoted commit messages containing `git push` are denied by the nested token scan.
WRITER_BASH = re.compile(r"""(^|[;&|(`\s])(
    gh\s+(pr\s+(create|merge|ready|close|edit|comment|review)|release|workflow\s+run|repo\s+(create|delete|edit)) |
    (npm|pnpm|yarn|bun)\s+publish | cargo\s+publish | twine\s+upload | gem\s+push |
    terraform\s+(apply|destroy) | kubectl\s+(apply|delete|rollout) | helm\s+(install|upgrade|uninstall) |
    vercel(\s+\S+)*\s+--prod | vercel\s+deploy | wrangler\s+(deploy|publish) | fly(ctl)?\s+deploy | docker\s+push
)\b""", re.X)
# Git subcommands and executables that write refs on a remote.
REMOTE_WRITERS = {'push', 'send-pack', 'http-push'}
REMOTE_WRITER_NAMES = {f'git-{name}' for name in REMOTE_WRITERS}
# Commands that run their first non-option, non-assignment argument, and the options that take a value.
WRAPPERS = {'env': {'-u', '--unset', '-C', '--chdir', '-S', '--split-string'}, 'command': set(),
            'exec': {'-a'}, 'nice': {'-n', '--adjustment'}, 'nohup': set(),
            'timeout': {'-s', '--signal', '-k', '--kill-after'},
            'xargs': {'-a', '--arg-file', '-d', '--delimiter', '-E', '-e', '-I', '-i', '-L', '-l', '-n',
                      '--max-args', '-P', '--max-procs', '-s', '--max-chars'},
            'sudo': {'-u', '--user', '-g', '--group', '-h', '--host', '-p', '--prompt', '-C', '--close-from',
                     '-U', '--other-user', '-r', '--role', '-t', '--type', '-D', '--chdir', '-R', '--chroot',
                     '-T', '--command-timeout'}}


def alias_runs_writer(setting):
    """Whether a `-c` setting defines an alias that runs a shell command or names a remote writer."""
    key, _, value = setting.partition('=')
    return key.lower().startswith('alias.') and (
        value.lstrip().startswith('!') or any(word in value for word in REMOTE_WRITERS))
GH_METHOD = re.compile(r'^(?:--method(?:=(.*))?|-[ip]*X(.*))$')
GH_FIELD = re.compile(r'^(?:--(?:field|raw-field|input)(?:=.*)?|-[ip]*[fF].*)$')
HARNESS_PATH = re.compile(r'(^|/)\.claude/settings[^/]*\.json$')
# The shape names only plain git calls, so it never runs a file a denied script wrote.
GIT_COMMIT_SHAPE = (' Resend with this shape: check state with separate plain `git rev-parse HEAD` and '
                    '`git status --porcelain` calls, then run the plain `git add -- <paths> && git commit -m <message>` '
                    'call alone, with no interpreter heredoc in it.')
LEDGER_ROLES = re.compile(r'^(ship:)?(reviewer|triage|verifier)--')


# Only these public entry points qualify as file-editing data; modules also expose executable internals.
INERT_MEMBERS = {
    're': {'sub', 'compile', 'search', 'fullmatch', 'findall', 'escape'},
    'json': {'loads', 'dumps', 'load', 'dump'},
    'tomllib': {'loads'},
    'textwrap': {'dedent'},
    'difflib': {'unified_diff', 'SequenceMatcher'},
    'hashlib': {'sha256'},
    'collections': {'Counter', 'defaultdict', 'deque'},
    'itertools': {'chain', 'islice', 'product', 'permutations', 'combinations'},
    'string': {'ascii_letters', 'ascii_lowercase', 'ascii_uppercase', 'digits', 'hexdigits', 'punctuation'},
    'math': {'ceil', 'floor', 'sqrt', 'isfinite', 'isclose'},
    'pathlib': {'Path'},
}
# A `Path` may only read, test, delete or write its own literal path; its other methods rename, link or open files.
PATH_METHODS = {'read_text', 'read_bytes', 'exists', 'write_text', 'unlink'}
LOADABLE = re.compile(r'\.(?:py[cdiow]?|pth|so)(?:$|[^A-Za-z0-9])', re.I)
INERT_ATTRIBUTES = {
    'Path', 'read_text', 'read_bytes', 'write_text', 'exists', 'open', 'read', 'write', 'close', 'name', 'parent', 'with_suffix',
    'replace', 'split', 'rsplit', 'join', 'strip', 'lstrip', 'rstrip', 'splitlines', 'startswith', 'endswith',
    'find', 'index', 'count', 'lower', 'upper', 'encode', 'decode', 'append', 'extend', 'insert', 'pop', 'get',
    'items', 'keys', 'values', 'group', 'groups', 'sub', 'compile', 'search', 'fullmatch', 'findall', 'escape',
    'loads', 'dumps', 'load', 'dump', 'dedent', 'sha256', 'hexdigest', 'unlink',
}
ISOLATED_ATTRIBUTES = INERT_ATTRIBUTES | {'parents', 'chmod', 'mkdir'}
READ_ONLY_COMMANDS = {'sed', 'grep', 'head', 'tail', 'cat', 'wc', 'diff', 'echo', 'ls', 'true', 'date'}
READ_ONLY_STARTS = {'cat', 'grep', 'head', 'tail', 'ls', 'wc', 'diff', 'cd', 'git'}
REFLECTION = {'eval', 'exec', 'compile', 'getattr', 'setattr', 'delattr', 'globals', 'locals', 'vars', 'breakpoint',
              'help', 'input'}


def inert_python(body, isolated=False):
    """Whether Python only computes and edits files: literal paths normally, resolved paths in isolated mode."""
    try:
        tree = ast.parse(body)
    except (SyntaxError, ValueError):
        return False
    # Imports run before any statement can write a file, so the script never imports a module it wrote itself.
    leading = set()
    for statement in tree.body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            break
        leading.add(statement)
    modules = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in leading:
            return False
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in INERT_MEMBERS:
                    return False
                modules[alias.asname or alias.name] = alias.name
        if isinstance(node, ast.ImportFrom) and (
                node.level or node.module not in INERT_MEMBERS
                or any(alias.name not in INERT_MEMBERS[node.module] for alias in node.names)
                # `inert_paths` finds a `Path` by its name, so it must keep that name.
                or node.module == 'pathlib' and any(alias.asname not in (None, 'Path') for alias in node.names)):
            return False
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if (isinstance(child, ast.Name) and child.id in modules
                    and not (isinstance(parent, ast.Attribute) and parent.value is child)):
                return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and (node.id in REFLECTION or node.id.startswith('__')):
            return False
        if isinstance(node, ast.Attribute):
            if node.attr not in (ISOLATED_ATTRIBUTES if isolated else INERT_ATTRIBUTES):
                return False
            if (isinstance(node.value, ast.Name) and node.value.id in modules
                    and node.attr not in INERT_MEMBERS[modules[node.value.id]]):
                return False
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A dunder attribute path (`0.__globals__`, `[__x`) or a bare dunder name can reach reflection through
            # format fields; other text that mentions a dunder, such as `import __main__`, is file text.
            if protected_text(node.value):
                return False
        if isinstance(node, ast.Match):
            return False
    # The interpreter imports modules from the current folder (Python 3.13 imports `traceback` on any uncaught
    # error), so a write must name a literal path that Python cannot load.
    # A name keeps its literal only when nothing else in the script binds it.
    bound = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)]
    bound += [node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)]
    bound += [name for node in ast.walk(tree) if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names]
    bound += [node.name for node in ast.walk(tree) if isinstance(
        node, (ast.ExceptHandler, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name]
    bound += [(alias.asname or alias.name).split('.')[0] for node in ast.walk(tree)
              if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names]
    if isolated:
        return isolated_writes(tree, bound)
    literals, assigned = {}, {}
    for statement in tree.body:
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)):
            name = statement.targets[0].id
            value = statement.value
            text = value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None
            assigned.setdefault(name, []).append(text)
            literals[name] = text if bound.count(name) == 1 else None
    calls = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == 'open' and id(node) not in calls:
            return False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'open':
            if (any(isinstance(argument, ast.Starred) for argument in node.args)
                    or any(keyword.arg not in {'mode', 'encoding', 'newline', 'errors'} for keyword in node.keywords)):
                return False
            modes = [*node.args[1:2], *(keyword.value for keyword in node.keywords if keyword.arg == 'mode')]
            if not modes:
                continue
            if all(isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) <= set('rbt')
                   for mode in modes):
                continue
            target = node.args[0] if node.args else None
            # A name may hold several literal paths in turn, so a write through it needs every one to be writable.
            paths = ([target.value] if isinstance(target, ast.Constant) else
                     assigned.get(target.id) if isinstance(target, ast.Name)
                     and bound.count(target.id) == len(assigned.get(target.id, ())) else None)
            if not paths or not all(writable(path) for path in paths):
                return False
    return inert_paths(tree, literals, bound)


def git_read_argv(argv):
    """Return the refusal rule for a literal Git argv, or an empty string for a safe read."""
    if not argv or argv[0] != 'git':
        return 'literal git read argv'
    words, fsmonitor = argv[1:], False
    while words and words[0].startswith('-'):
        if len(words) < 2:
            return 'literal git read global options'
        option, value = words[:2]
        if option == '-c' and value == 'core.fsmonitor=false':
            fsmonitor = True
        elif option != '-C' or value.startswith('-'):
            return 'literal git read global options'
        words = words[2:]
    if not words:
        return 'literal git read subcommand'
    subcommand, arguments = words[0], words[1:]
    options = {
        'rev-parse': {'--verify', '--short', '--abbrev-ref', '--symbolic-full-name', '--show-toplevel', '--git-dir', '-q'},
        'branch': {'--show-current'},
        'diff': {'--cached', '--staged', '--name-only', '--name-status', '--numstat', '--stat', '-z',
                 '--no-ext-diff', '--no-textconv'},
        'show': set(),
        'status': {'--porcelain', '--short', '-s', '-z', '-b', '--branch'},
        'ls-files': {'-z', '-s', '--stage', '--cached'},
    }
    if subcommand not in options:
        return 'literal git read subcommand'
    if subcommand in {'rev-parse', 'diff', 'show', 'status', 'ls-files'} and not fsmonitor:
        return 'git read requires -c core.fsmonitor=false (fsmonitor rule)'
    separator = arguments.index('--') if '--' in arguments else len(arguments)
    option_words = arguments[:separator]
    positional = [word for word in option_words if not word.startswith('-')] + arguments[separator + 1:]
    if (any(word.startswith('-') and word not in options[subcommand] for word in option_words)
            or any(word.startswith('-') for word in positional)):
        return 'literal git read options: ' + next((
            word for word in arguments if word.startswith('-') and word != '--'
            and (word not in options[subcommand] or word in positional)), '--')
    if subcommand == 'branch' and arguments != ['--show-current']:
        return 'literal git read branch options'
    if subcommand == 'diff' and not (
            {'--name-only', '--name-status'} & set(option_words)
            or {'--numstat', '--stat'} & set(option_words) and '--no-textconv' in option_words):
        return 'literal git read diff output'
    if subcommand == 'show' and ('--' in arguments or not positional
                                 or any(':' not in word or word.startswith(':/') for word in positional)):
        return 'literal git read show object'
    return ''


def literal_git_read_python(body, reasons=None):
    """Whether a body uses subprocess only for checked literal Git reads and writes no file."""
    try:
        tree = ast.parse(body)
    except (SyntaxError, ValueError):
        return False
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    bound = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)]
    bound += [node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)]
    bound += [name for node in ast.walk(tree) if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names]
    bound += [node.name for node in ast.walk(tree) if isinstance(
        node, (ast.ExceptHandler, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name]
    bound += [(alias.asname or alias.name).split('.')[0] for node in ast.walk(tree)
              if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names]
    literals = {node.targets[0].id: node.value.value for node in tree.body
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and bound.count(node.targets[0].id) == 1 and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)}

    def word(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return literals.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = word(node.left), word(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    imports, calls, helpers = [], set(), {}
    for statement in tree.body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            break
        if isinstance(statement, ast.Import) and any(alias.name == 'subprocess' for alias in statement.names):
            if len(statement.names) != 1 or statement.names[0].asname:
                return False
            imports.append(statement)
    if len(imports) != 1 or bound.count('subprocess') != 1:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id != 'subprocess':
            continue
        attribute = parents.get(node)
        call = parents.get(attribute)
        if not (isinstance(attribute, ast.Attribute) and attribute.value is node
                and attribute.attr in {'check_output', 'run'} and isinstance(call, ast.Call) and call.func is attribute
                and len(call.args) == 1 and isinstance(call.args[0], ast.List)
                and all(k.arg == 'text' and isinstance(k.value, ast.Constant) and type(k.value.value) is bool
                        for k in call.keywords) and len(call.keywords) <= 1):
            return False
        calls.add(call)
    if not calls:
        return False
    for call in calls:
        elements = call.args[0].elts
        if not elements or not isinstance(elements[0], ast.Constant) or elements[0].value != 'git':
            return False
        owner = parents.get(call)
        helper = parents.get(owner)
        if isinstance(owner, ast.Return):
            if not (isinstance(helper, ast.FunctionDef) and helper in tree.body and helper.body == [owner]
                    and not helper.decorator_list and not helper.returns and not getattr(helper, 'type_params', [])
                    and not helper.args.posonlyargs and not helper.args.args and not helper.args.kwonlyargs
                    and not helper.args.defaults and not helper.args.kw_defaults and not helper.args.kwarg
                    and helper.args.vararg and not helper.args.vararg.annotation and bound.count(helper.name) == 1):
                return False
            helpers[helper.name] = helper
        else:
            helper = None
        starred = [node for node in elements if isinstance(node, ast.Starred)]
        if (helper or starred) and not (helper and len(starred) == 1 and elements[-1] is starred[0]
                            and isinstance(starred[0].value, ast.Name)
                            and starred[0].value.id == helper.args.vararg.arg):
            return False
        prefix = elements[:-1] if starred else elements
        # Global options and the subcommand remain literal; only -C may reference a fixed module string.
        cursor = 1
        while cursor < len(prefix) and isinstance(prefix[cursor], ast.Constant) and prefix[cursor].value in {'-C', '-c'}:
            if cursor + 1 >= len(prefix):
                return False
            value = prefix[cursor + 1]
            if not (isinstance(value, ast.Constant) or prefix[cursor].value == '-C' and isinstance(value, ast.Name)):
                return False
            cursor += 2
        if cursor < len(prefix) and not isinstance(prefix[cursor], ast.Constant):
            return False
        uses = []
        if helper:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Name) or node.id != helper.name:
                    continue
                use = parents.get(node)
                if not (isinstance(use, ast.Call) and use.func is node and not use.keywords
                        and not any(isinstance(arg, ast.Starred) for arg in use.args)):
                    return False
                uses.append(use)
        else:
            uses = [None]
        for use in uses:
            effective = prefix + (use.args if use is not None else [])
            if len(effective) <= cursor or not isinstance(effective[cursor], ast.Constant):
                return False
            argv = [word(node) for node in effective]
            if any(value is None for value in argv):
                return False
            index = 1
            while index < len(argv) and argv[index].startswith('-'):
                if (index + 1 >= len(argv) or not isinstance(effective[index], ast.Constant)
                        or not (isinstance(effective[index + 1], ast.Constant)
                                or argv[index] == '-C' and isinstance(effective[index + 1], ast.Name))):
                    return False
                index += 2
            if index >= len(effective) or not isinstance(effective[index], ast.Constant):
                return False
            reason = git_read_argv(argv)
            if reason:
                if reasons is not None:
                    reasons.append(reason)
                return False
        if helper and not uses:
            return False
    # Remove only the proved calls and helpers, then apply the existing inert checks to all remaining code.
    class RemoveReads(ast.NodeTransformer):
        def visit_Call(self, node):
            return ast.copy_location(ast.Constant(value=''), node) if node in calls or (
                isinstance(node.func, ast.Name) and node.func.id in helpers) else self.generic_visit(node)

    tree.body = [node for node in tree.body if node not in imports and node not in helpers.values()]
    tree = RemoveReads().visit(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and (node.attr in {'write', 'write_text', 'unlink', 'replace', 'chmod', 'mkdir'}
                                               or isinstance(node.ctx, (ast.Store, ast.Del))):
            return False
        if isinstance(node, ast.Call) and (getattr(node.func, 'id', None) == 'open'
                                          or getattr(node.func, 'attr', None) == 'open'):
            offset = 1 if isinstance(node.func, ast.Name) else 0
            modes = [*node.args[offset:offset + 1], *(k.value for k in node.keywords if k.arg == 'mode')]
            if any(not isinstance(mode, ast.Constant) or not isinstance(mode.value, str)
                   or not set(mode.value) <= set('rbt') for mode in modes):
                return False
    return inert_python(ast.unparse(tree))


def resolved_path(node, assigned, depth=0):
    if depth >= 16:
        return None
    resolve = lambda value: resolved_path(value, assigned, depth + 1)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in assigned:
        return resolve(assigned[node.id])
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'Path', 'str'}
            and len(node.args) == 1 and not node.keywords):
        path = resolve(node.args[0])
        return str(PurePosixPath(path)) if path is not None and node.func.id == 'Path' else path
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = resolve(node.left), resolve(node.right)
        if left is not None and right is not None:
            return str(PurePosixPath(left) / right)
    if isinstance(node, ast.Attribute) and node.attr == 'parent':
        path = resolve(node.value)
        if path is not None:
            return str(PurePosixPath(path).parent)
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and node.value.attr == 'parents' and isinstance(node.slice, ast.Constant)
            and type(node.slice.value) is int):
        path = resolve(node.value.value)
        if path is not None:
            try:
                return str(PurePosixPath(path).parents[node.slice.value])
            except IndexError:
                return None
    return None


def isolated_writes(tree, bound):
    path_imports = sum(alias.name == 'Path' and alias.asname in (None, 'Path')
                       for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == 'pathlib'
                       for alias in node.names)
    if bound.count('Path') != path_imports or 'str' in bound or 'open' in bound:
        return False
    assigned = {node.targets[0].id: node.value for node in tree.body
                if isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and bound.count(node.targets[0].id) == 1}
    calls = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            return False
        if isinstance(node, ast.Name) and node.id == 'open' and id(node) not in calls:
            return False
        # A method read off the class (`Path.open('t', 'w')`, `c.replace(src, dst)`) takes the path as its first
        # argument, so the class is usable only as the callee that builds a path.
        if ((isinstance(node, ast.Name) and node.id == 'Path' or isinstance(node, ast.Attribute) and node.attr == 'Path')
                and id(node) not in calls or isinstance(node, ast.Name) and node.id == 'type'):
            return False
        if isinstance(node, ast.Attribute) and node.attr in {
                'write_text', 'chmod', 'mkdir', 'unlink', 'open', 'replace'} and id(node) not in calls:
            return False
        if not isinstance(node, ast.Call):
            continue
        builtin_open = isinstance(node.func, ast.Name) and node.func.id == 'open'
        method = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if builtin_open or method == 'open':
            if (any(isinstance(argument, ast.Starred) for argument in node.args)
                    or any(keyword.arg not in {'mode', 'encoding', 'newline', 'errors'} for keyword in node.keywords)):
                return False
            # Called on the class (`Path.open`, an alias, `type(...)`), the first argument is the path, not the mode.
            if not builtin_open and len(node.args) > 1:
                return False
            offset = 1 if builtin_open else 0
            modes = [*node.args[offset:offset + 1],
                     *(keyword.value for keyword in node.keywords if keyword.arg == 'mode')]
            if all(isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) <= set('rbt')
                   for mode in modes):
                continue
            target = (node.args[0] if node.args else None) if builtin_open else node.func.value
            targets.append(target)
        elif method in {'write_text', 'chmod', 'mkdir', 'unlink'}:
            targets.append(node.func.value)
        elif method == 'replace':
            if node.keywords or any(isinstance(argument, ast.Starred) for argument in node.args):
                return False
            if len(node.args) == 1:
                targets.extend((node.func.value, node.args[0]))
    return all(writable(path := resolved_path(target, assigned)) and not protected_text(path) for target in targets)


def writable(path):
    """Whether an inert script may write `path`: a literal that Python cannot import.

    Python can import a module written moments earlier, also while it formats an exception, so no module file
    qualifies; writers edit those with the Edit tool."""
    return isinstance(path, str) and not LOADABLE.search(path)


def protected_text(text):
    return bool(re.search(r'^__|[.\[]__', text) or '.git/' in text or '.git\\' in text or text.endswith('.git'))


def inert_paths(tree, literals, bound):
    """Whether every `Path` is built from one literal and used only as the receiver of `PATH_METHODS`.

    A write needs a `writable` path, the same rule as `open`. A name may hold several paths in turn; a write through
    it needs every one of them to be writable."""
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def used(node, paths):
        attribute = parents.get(node)
        call = parents.get(attribute)
        if not (isinstance(attribute, ast.Attribute) and attribute.value is node and attribute.attr in PATH_METHODS
                and isinstance(call, ast.Call) and call.func is attribute):
            return False
        if attribute.attr != 'write_text':
            return True
        return (len(call.args) == 1 and not isinstance(call.args[0], ast.Starred)
                and all(keyword.arg in {'encoding', 'errors', 'newline'} for keyword in call.keywords)
                and all(writable(path) for path in paths))

    def literal_strings(node):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and all(
                isinstance(value, ast.Constant) and isinstance(value.value, str) for value in node.elts):
            return {value.value for value in node.elts}
        return None

    def loop_values(node, literal_only=False):
        loop = parents.get(node)
        while loop is not None and not isinstance(loop, ast.For):
            if isinstance(loop, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
                                 ast.comprehension, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return None
            loop = parents.get(loop)
        if loop is None:
            return None
        child = node
        while parents.get(child) is not loop:
            child = parents.get(child)
        if child not in loop.body:
            return None
        target = loop.target
        iterator = loop.iter
        items = (isinstance(iterator, ast.Call) and isinstance(iterator.func, ast.Attribute)
                 and iterator.func.attr == 'items')
        if items:
            if not isinstance(target, ast.Tuple) or len(target.elts) != 2:
                return None
            target = target.elts[0]
        if not isinstance(target, ast.Name) or target.id != node.id:
            return None
        targets = [child for statement in ast.walk(tree) if isinstance(statement, ast.For)
                   for child in ast.walk(statement.target) if isinstance(child, ast.Name) and child.id == node.id]
        if bound.count(node.id) != len(targets) or any(isinstance(child.ctx, ast.Load) for child in targets):
            return None
        for child in ast.walk(loop):
            if (isinstance(child, ast.Name) and child.id == node.id and child is not target
                    and not isinstance(child.ctx, ast.Load)
                    or isinstance(child, ast.arg) and child.arg == node.id
                    or isinstance(child, (ast.Global, ast.Nonlocal)) and node.id in child.names
                    or isinstance(child, (ast.ExceptHandler, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and child.name == node.id
                    or isinstance(child, (ast.Import, ast.ImportFrom)) and any(
                        (alias.asname or alias.name).split('.')[0] == node.id for alias in child.names)):
                return None
        values = literal_strings(iterator)
        if values is not None or literal_only:
            return values
        if isinstance(iterator, ast.Call):
            if (iterator.args or iterator.keywords or not isinstance(iterator.func, ast.Attribute)
                    or iterator.func.attr not in {'items', 'keys'}):
                return None
            iterator = iterator.func.value
        if not isinstance(iterator, ast.Name):
            return None
        return dict_keys(iterator.id)

    def key_values(node, depth=0):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name):
            values = loop_values(node, literal_only=True)
            return values if values and len(values) <= 256 else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and depth < 8:
            left, right = key_values(node.left, depth + 1), key_values(node.right, depth + 1)
            if left and right:
                values = set()
                for a in left:
                    for b in right:
                        value = a + b
                        if value not in values and len(values) == 256:
                            return None
                        values.add(value)
                return values
        return None

    def dict_keys(name):
        assignments = [statement for statement in tree.body if isinstance(statement, ast.Assign)
                       and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name)
                       and statement.targets[0].id == name and isinstance(statement.value, ast.Dict)]
        if len(assignments) != 1 or bound.count(name) != 1:
            return None
        assignment = assignments[0]
        keys = list(assignment.value.keys)
        for use in ast.walk(tree):
            if not isinstance(use, ast.Name) or use.id != name or use is assignment.targets[0]:
                continue
            parent = parents.get(use)
            if isinstance(parent, ast.Subscript) and parent.value is use and isinstance(parent.ctx, ast.Store):
                if not isinstance(parents.get(parent), ast.Assign):
                    return None
                keys.append(parent.slice)
            elif isinstance(parent, ast.For) and parent.iter is use:
                continue
            elif (isinstance(parent, ast.Attribute) and parent.value is use and parent.attr in {'items', 'keys'}
                  and isinstance(parents.get(parent), ast.Call)):
                call = parents[parent]
                owner = parents.get(call)
                if call.func is not parent or call.args or call.keywords or not isinstance(owner, ast.For) or owner.iter is not call:
                    return None
            else:
                return None
        values = set()
        for key in keys:
            found = key_values(key)
            if not found:
                return None
            values.update(found)
        return values

    def constructed(node):
        argument = node.args[0] if len(node.args) == 1 and not node.keywords else None
        path = (argument.value if isinstance(argument, ast.Constant) and isinstance(argument.value, str) else
                literals.get(argument.id) if isinstance(argument, ast.Name) else None)
        if path is not None:
            return [path]
        # Loop paths need statically known writable values because Python can load a file the script writes.
        values = loop_values(argument) if isinstance(argument, ast.Name) else None
        return list(values) if values and all(
            writable(value) and not protected_text(value) for value in values) else [None]

    imported = sum(alias.name == 'Path' for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module == 'pathlib' for alias in node.names)
    holders = {}
    for statement in ast.walk(tree):
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name) and isinstance(statement.value, ast.Call)):
            if statement not in tree.body and not (
                    len(statement.value.args) == 1 and isinstance(statement.value.args[0], ast.Name)
                    and loop_values(statement.value.args[0])
                    and constructed(statement.value) != [None]
                    and bound.count(statement.targets[0].id) == 1):
                continue
            holders.setdefault(statement.targets[0].id, []).append(statement)
    for node in ast.walk(tree):
        named = (node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None)
        if named != 'Path':
            continue
        call = parents.get(node)
        if not (isinstance(call, ast.Call) and call.func is node) or bound.count('Path') != imported:
            return False
        owner = parents.get(call)
        if (not call.keywords and call.args and isinstance(owner, ast.Attribute) and owner.attr == 'read_bytes'
                and all(isinstance(part, ast.Constant) and isinstance(part.value, str)
                        or isinstance(part, ast.Name) and isinstance(literals.get(part.id), str)
                        for part in call.args)):
            if not used(call, [None]):
                return False
            continue
        if call.keywords or len(call.args) != 1:
            return False
        if isinstance(owner, ast.Attribute):
            if not used(call, constructed(call)):
                return False
            continue
        name = (owner.targets[0].id if isinstance(owner, ast.Assign)
                and owner in holders.get(getattr(owner.targets[0], 'id', None), []) else None)
        # Every binding must construct a checked Path, so each load holds one of those paths.
        assignments = holders.get(name, [])
        if (not name or bound.count(name) != len(assignments)
                or not all(isinstance(assignment.value.func, (ast.Name, ast.Attribute))
                           and getattr(assignment.value.func, 'id', getattr(assignment.value.func, 'attr', None)) == 'Path'
                           for assignment in assignments)):
            return False
        paths = [path for assignment in assignments for path in constructed(assignment.value)]
        if not all(used(load, paths) for load in ast.walk(tree)
                   if isinstance(load, ast.Name) and load.id == name and isinstance(load.ctx, ast.Load)):
            return False
    return True


def outside_single_quotes(command):
    """The shell text outside single quotes, which are literal in every shell.

    A quote inside double quotes or after a backslash opens nothing, so its text stays."""
    kept, single, double, escaped = [], False, False, False
    for char in command:
        if single:
            single = char != "'"
            continue
        if escaped:
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == '"':
            double = not double
        elif char == "'" and not double:
            single = True
            continue
        kept.append(char)
    return ''.join(kept)


def read_only_shell(command):
    # Only literal read commands qualify; expansions and redirections can execute or create another program.
    # A backslash, a glob bracket or a quoted operator outside single quotes changes the words the shell runs.
    if re.search(r"[^\w \t\n./,:=@%+\-'\";&|]", outside_single_quotes(command)):
        return False
    # A quote may only wrap a whole word: the shell joins a quoted span with the text or span beside it, and the
    # non-POSIX lexer below does not. Without backslashes, each span ends at the next matching quote.
    for span in re.finditer(r"'[^']*'|\"[^\"]*\"", command):
        if (span.start() and command[span.start() - 1] not in ' \t\n;&|'
                or span.end() < len(command) and command[span.end()] not in ' \t\n;&|'):
            return False
    try:
        # Non-POSIX tokens keep their quotes, so only an unquoted operator separates commands.
        lexer = shlex.shlex(command, posix=False, punctuation_chars=';&|\n')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        lexer.commenters = ''
        tokens = list(lexer)
    except ValueError:
        return False
    parts, current = [], []
    for token in tokens:
        if token and all(char in ';&|\n' for char in token):
            if token not in {';', '&&', '||', '|', '\n'}:
                return False
            if current:
                parts.append(current)
                current = []
        else:
            try:
                word = shlex.split(token)
            except ValueError:
                return False
            if len(word) != 1:
                return False
            current.append(word[0])
    if current:
        parts.append(current)
    for words in parts:
        if words[0] not in READ_ONLY_COMMANDS:
            return False
        if words[0] == 'sed' and not (
                len(words) >= 3 and words[1] == '-n'
                and re.fullmatch(r'[0-9]+(?:,[0-9]+)?p', words[2])
                and all(not word.startswith('-') for word in words[3:])):
            return False
    return True


# Literal `cd` and `date` steps run no file, so they may lead a Python heredoc; the scan still reads them.
PYTHON_LEAD = r'(?:(?:cd +[\w./-]+|date(?: +[-+\w%:]+)*) +&& +)*'
# A writer may already run `git add` alone, so this lead adds no capability.
GIT_READ_LEAD = r'[ \t]*(?:(?:cd +[\w./-]+|date(?: +[-+\w%:]+)*|git +add +--(?: +[\w./-]+)+) +&& +)*'


def check_only_shell(command):
    """Whether every command only reads or syntax-checks files, so none runs a file the heredoc wrote.

    A script can build a push at run time, so a command that runs code (a test runner, `bash f.sh`) never follows."""
    segments = [part.strip() for part in re.split(r'&&|;|\n', command) if part.strip()]
    return read_only_shell(command) or all(
        read_only_shell(segment) or re.fullmatch(r'(?:ba|z)?sh +-n +[\w./][\w./-]*', segment) for segment in segments)


def python_writes(body, isolated=False):
    """Count write methods only in the modes that admit them."""
    methods = {'write_text', 'unlink'} | ({'chmod', 'mkdir', 'replace'} if isolated else set())
    return any(isinstance(node, ast.Attribute) and node.attr in methods
               or isinstance(node, ast.Call) and (
                   getattr(node.func, 'id', None) == 'open' or getattr(node.func, 'attr', None) == 'open') and not all(
                   isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) <= set('rbt')
                   for mode in [*node.args[(1 if isinstance(node.func, ast.Name) else 0):
                                          (2 if isinstance(node.func, ast.Name) else 1)],
                                *(k.value for k in node.keywords if k.arg == 'mode')])
               for node in ast.walk(ast.parse(body)))


def runs_heredoc_output(command):
    """Whether a Python heredoc that can write files is followed by a command that can run one.

    A script can build a push at run time (`'pu' + 'sh'`), so its text proves nothing about the files it writes."""
    lines = command.splitlines(keepends=True)
    match = ANY_PYTHON_HEREDOC.fullmatch(lines[0]) if lines else None
    if not match:
        return False
    delimiter = shlex.split(match['delimiter'])[0]
    for end in range(1, len(lines)):
        if (lines[end].lstrip('\t') if match['tabs'] else lines[end]).removesuffix('\n') == delimiter:
            body = ''.join(line.lstrip('\t') if match['tabs'] else line for line in lines[1:end])
            if literal_git_read_python(body):
                return False
            # The written files exist only after the script, so only a later or a background command can run them.
            if check_only_shell(''.join(lines[end + 1:])) and not re.search(r'(?<!&)&(?![&>])', match['lead']):
                return False
            literal = inert_python(body)
            # `-I` keeps the working folder off `sys.path`, so computed paths are inert there.
            if not literal and not ('I' in match['flags'] and inert_python(body, isolated=True)):
                return True
            # An inert script writes only through `open` with a write mode or a `Path` write method.
            return python_writes(body, isolated='I' in match['flags'] and not literal)
    return False


PYTHON_NAME = r'python(?:3(?:\.\d+)?t?)?'
PYTHON_STDIN = (PYTHON_NAME + r"(?P<flags>(?: +-[IB]+)*) +- +<<(?P<tabs>-?)[ \t]*"
                r"(?P<delimiter>'[_a-zA-Z0-9]+'|\"[_a-zA-Z0-9]+\"|\\[_a-zA-Z0-9]+|[_a-zA-Z0-9]+)[ \t]*\n$")
# Only literal `cd` and `date` steps and literal `PYTHON*` assignments (`PYTHONDONTWRITEBYTECODE=1`) may lead the
# interpreter; a `GIT_CONFIG_*` lead could alias a git read to a push.
PYTHON_HEREDOC = re.compile(rf"^(?P<lead>[ \t]*{PYTHON_LEAD}(?:PYTHON[A-Z0-9_]*=[\w./-]* +)*)" + PYTHON_STDIN)
# Any command may lead it here; the files it writes exist only after it runs.
ANY_PYTHON_HEREDOC = re.compile(r"^(?P<lead>.*?)" + PYTHON_STDIN)


def python_heredoc_shell(command, inert_only=False):
    # Only a literal Python stdin command establishes a non-shell script body.
    # Shell interpreters, ambiguous headers, and expandable bodies keep the full scan.
    # `inert_only` keeps every body that can run a process, because its strings can reach a publish command.
    lines = command.splitlines(keepends=True)
    match = ANY_PYTHON_HEREDOC.fullmatch(lines[0]) if lines else None
    if not match:
        return command
    delimiter = shlex.split(match['delimiter'])[0]
    for end in range(1, len(lines)):
        candidate = lines[end].lstrip('\t') if match['tabs'] else lines[end]
        if candidate.removesuffix('\n') == delimiter:
            remainder = ''.join(lines[end + 1:])
            body = ''.join(line.lstrip('\t') if match['tabs'] else line for line in lines[1:end])
            if (match['delimiter'][0] in '\'"\\' and 'I' in match['flags']
                    and re.fullmatch(GIT_READ_LEAD, match['lead']) and literal_git_read_python(body)):
                return lines[0] + remainder
            if not PYTHON_HEREDOC.fullmatch(lines[0]):
                return command
            # A quoted delimiter keeps the body away from the shell, so an inert script is only file text.
            # Only a `cd` or `date` may lead it and only a read-only remainder may follow it, because another command
            # could run the file it writes.
            # Resolved writes in isolated mode require an empty remainder, which cannot run a planted command.
            if (re.fullmatch(rf'[ \t]*{PYTHON_LEAD}', match['lead']) and match['delimiter'][0] in '\'"\\'
                    and (read_only_shell(remainder) and inert_python(body)
                         or not remainder.strip() and 'I' in match['flags'] and inert_python(body, isolated=True))):
                return lines[0] + remainder
            if inert_only:
                return command
            if 'push' in body or '\\\n' in body:
                return command
            # An unquoted delimiter lets the shell expand the body; a quoted one keeps f-strings and dicts as text.
            if match['delimiter'][0] not in '\'"\\' and any(c in body for c in '$`{}'):
                return command
            try:
                tree = ast.parse(body)
            except (SyntaxError, ValueError):
                return command
            body_lines = body.splitlines(keepends=True)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == 'git':
                    line = body_lines[node.lineno - 1]
                    body_lines[node.lineno - 1] = re.sub(r'^(\s*def )git(?=\s*\()',
                                                       r'\1_git_helper', line, count=1)
            if shell_git_push(''.join(body_lines)):
                return command
            # The remainder stays in the result, so the push scan reads it as shell.
            return lines[0] + remainder
    return command


def literal_ps_awk_filter(command):
    # Only a complete process-list filter with a bare print action supplies inert awk data. It may stand in a
    # command chain, but nothing may follow it in the same pipeline or as an awk argument.
    regex_literal = r'/(?:[^/\'"\\\r\n;&`$\{\}]|\$(?=[/)| ]))*/'
    comparison = (r'\$[0-9]+[ \t]*(?:==|!=|!~|~|>=|<=|>|<)[ \t]*'
                  rf'(?:"[\w ./-]*"|{regex_literal}|[0-9]+)')
    expression = rf'[() \t]*{comparison}(?:[() \t]*(?:&&|\|\|)[() \t]*{comparison})*[() \t]*\{{[ \t]*print[ \t]*\}}[ \t]*'

    def data(pipeline):
        prefix = command[:pipeline.start()]
        # Only plain words, quotes and quote-free `$(...)` may precede the filter; other shell grammar (nested
        # quotes in `${...}`, `case` patterns, comments, heredocs) changes where quotes open.
        plain = re.sub(r'\$\([^\'"()$`#<\\\n]*\)', '_', prefix)
        if re.search(r"#|<<|\$'|`|\$\{|[()]|\bcase\b", plain):
            return pipeline[0]
        quote, escaped = '', False
        for char in plain:
            if escaped:
                escaped = False
            elif char == '\\' and quote != "'":
                escaped = True
            elif char == quote:
                quote = ''
            elif not quote and char in '\'"':
                quote = char
        if quote or escaped or 'push' in pipeline[2] or not re.fullmatch(expression, pipeline[2]):
            return pipeline[0]
        return pipeline[1] + 'awk_filter_data'

    return re.sub(r"(?:^|(?<=[;&|(]))([ \t]*ps[ \t]+-eo[ \t]+[a-z]+(?:,[a-z]+)*[ \t]*\|[ \t]*awk[ \t]+)"
                  r"'([^'\r\n]*)'(?=[ \t]*(?:$|;|&&|\|\||\)))", data, command)


def cat_heredoc_data(command):
    # ponytail: PATH or link aliases can reach the written file; sandbox execution to enforce filesystem identity.
    delimiter = r'''('[A-Za-z_0-9]+'|"[A-Za-z_0-9]+")'''
    path = r'[\w./-]+'
    header = (rf'^[ \t]*(?:cd +{path} +&& +)?cat[ \t]+'
              rf'(?:<<(-?)[ \t]*{delimiter}[ \t]+>>?[ \t]*{path}'
              rf'|>>?[ \t]*{path}[ \t]+<<(-?)[ \t]*{delimiter})[ \t]*\n$')
    lines = command.splitlines(keepends=True)
    match = re.fullmatch(header, lines[0]) if lines else None
    if not match:
        return command
    end_marker = shlex.split(match[2] or match[4])[0]
    strip_tabs = match[1] or match[3]
    for end in range(1, len(lines)):
        candidate = lines[end].lstrip('\t') if strip_tabs else lines[end]
        if candidate.removesuffix('\n') == end_marker:
            remainder = ''.join(lines[end + 1:])
            ruff = (r'(?:ruff|/[\w./-]+/\.venv/bin/ruff)[ \t]+'
                    r'(?:check|format)(?:[ \t]+[A-Za-z0-9./_=\-]+)*')
            segments = [part.strip() for part in re.split(r'&&|;|\n', remainder) if part.strip()]
            if not read_only_shell(remainder) and not all(
                    read_only_shell(segment) or re.fullmatch(ruff, segment) for segment in segments):
                return command
            ruff_segments = [segment for segment in segments if re.fullmatch(ruff, segment)]
            for segment in ruff_segments:
                executable = Path(segment.split()[0])
                if executable.is_absolute() and (
                        Path(os.path.realpath(executable)).parent != Path(os.path.realpath(executable.parent))):
                    return command
            written = Path(re.search(r'>>?[ \t]*([\w./-]+)', lines[0])[1])
            folder = re.match(rf'^[ \t]*cd +({path}) +&& +', lines[0])
            if folder:
                written = Path(folder[1]) / written
            if ruff_segments:
                if not written.is_absolute():
                    return command
                for destination in (written, Path(os.path.realpath(written))):
                    if (destination.suffix not in {'.py', '.pyi'} or destination.name == 'setup.py'
                            or set(destination.parts) & {'..', '.venv', 'venv', 'env', 'site-packages', 'bin', 'Scripts',
                                                         '.git', 'node_modules', 'lib', 'lib64', 'Lib', 'dist-packages'}
                            or any(part.startswith('python') or Path(part).stem in {'sitecustomize', 'usercustomize'}
                                   for part in destination.parts)):
                        return command
            return re.sub(rf'<<-?[ \t]*{delimiter}', '', lines[0], count=1) + remainder
    return command


HEREDOC_READERS = {'cat', 'tee', 'grep', 'head', 'tail', 'wc'}


def data_reader_header(line):
    """Admit only literal data readers, their words, and literal output paths."""
    word = r'[\w./:@%+,=-]+'
    path = r'[\w./:@%+,-]+'
    argument = rf'(?:{word}|>>?[ \t]*{path})'
    delimiter = r"(?:'[A-Za-z0-9_]+'|\"[A-Za-z0-9_]+\"|\\?[A-Za-z0-9_]+)"
    operator = rf"(?:<<<[ \t]*(?:'[^'\n<]*'|{word})|<<-?[ \t]*{delimiter})"
    return re.fullmatch(rf'[ \t]*(?:cd +{path} +&& +)*(?:' + '|'.join(sorted(HEREDOC_READERS))
                        + rf')(?:[ \t]+{argument})*[ \t]*{operator}(?:[ \t]+{argument})*[ \t]*\n?', line) is not None


def literal_quotes_removed(line):
    """Mask literal quotes at their offsets; keep ambiguous shell text on the strict check."""
    kept, index = [], 0
    while index < len(line):
        char = line[index]
        if char == '\\':
            kept.append(line[index:index + 2])
            index += 2
        elif char in '#`' or (char == '$' and line[index + 1:index + 2] in ("'", '(', '[', '{')):
            return line
        elif char in '\'"':
            end = index + 1
            while end < len(line) and line[end] != char:
                end += 2 if char == '"' and line[end] == '\\' else 1
            if end >= len(line) or char == '"' and re.search(r"\$['(\[{]|`", line[index + 1:end]):
                return line
            kept.append(re.sub(r'[^\n\r\v\f\x1c-\x1e\x85  ]', ' ', line[index:end + 1]))
            index = end + 1
        else:
            kept.append(char)
            index += 1
    return ''.join(kept)


def process_heredoc_denial(command, readers=False):
    """Check Python stdin bodies and keep quoted commit messages as data."""
    lines = (command if readers else cat_heredoc_data(command)).splitlines(keepends=True)
    quoted_lines = literal_quotes_removed(''.join(lines)).splitlines(keepends=True)
    index = 0
    while index < len(lines):
        text = quoted_lines[index]
        operators = [match for match in re.finditer(r"(?<!<)<<(?P<tabs>-?)(?!<)[ \t]*"
                                                   r"(?P<delimiter>'[^'\n]+'|\"[^\"\n]+\"|\\?[^\s<>;&|()'\"`]+)",
                                                   lines[index]) if text[match.start():match.start() + 2] == '<<']
        if not operators:
            if readers and '<<' in text and not data_reader_header(lines[index]):
                return 'process-capable heredoc rule (heredoc reader not on the allowlist)'
            index += 1
            continue
        match = operators[0]
        prefix = lines[index][:match.start()]
        commit_lead = r'[ \t]*(?:cd +[\w./-]+ +&& +)?git +commit(?: +(?:-[a-zA-Z]|--[\w-]+))* +'
        message_data = index == 0 and re.match(commit_lead, prefix)
        if message_data and (len(operators) != 1
                             or not re.fullmatch(commit_lead + r'(?:-m +"\$\(cat[ \t]*|-F +- +)', prefix)
                             or lines[index][match.end():].strip()
                             or not re.fullmatch(r"'[A-Za-z0-9_]+'|\"[A-Za-z0-9_]+\"", match['delimiter'])):
            return 'process-capable heredoc rule (commit message heredoc must be the whole command)'
        interpreter = re.search(rf'(?<![\w.-])(?:[\w./-]*/)?{PYTHON_NAME}(?=[ \t<]|$)', lines[index])
        if message_data:
            pass
        elif interpreter or '$' in prefix or '`' in prefix:
            lead = lines[index][:interpreter.start()] if interpreter else prefix
            if index != 0 or not re.fullmatch(GIT_READ_LEAD, lead):
                return 'process-capable heredoc rule (interpreter heredoc must start the command)'
            header = re.fullmatch(re.escape(lead) + PYTHON_STDIN, lines[index])
            if len(operators) != 1 or not header:
                return 'process-capable heredoc rule (unsupported interpreter header)'
        else:
            if readers:
                if (len(operators) != 1 or not data_reader_header(lines[index])
                        or not data_reader_header(lines[index].replace('\\\n', ''))):
                    return 'process-capable heredoc rule (heredoc reader not on the allowlist)'
                delimiter = shlex.split(match['delimiter'])[0]
                end = index + 1
                while end < len(lines):
                    body_line = lines[end].lstrip('\t') if match['tabs'] else lines[end]
                    if body_line.removesuffix('\n') == delimiter:
                        break
                    if match['delimiter'][0] not in '\'"\\' and (
                            '$' in body_line or '`' in body_line or body_line.removesuffix('\n').endswith('\\')):
                        return 'process-capable heredoc rule (expandable data body)'
                    end += 1
                if end == len(lines):
                    return 'process-capable heredoc rule (unterminated body)'
                index = end + 1
                quoted_lines[index:] = literal_quotes_removed(''.join(lines[index:])).splitlines(keepends=True)
            else:
                index += 1
                # The legacy pass scans data bodies strictly; their quotes supply no shell-state evidence.
                quoted_lines = lines
            continue
        delimiter = shlex.split(match['delimiter'])[0]
        end = index + 1
        while end < len(lines) and (lines[end].lstrip('\t') if match['tabs'] else lines[end]).removesuffix('\n') != delimiter:
            end += 1
        if message_data:
            remainder = ''.join(lines[end + 1:])
            complete = remainder in (')"', ')"\n') if '-m' in prefix.split() else not remainder
            if end == len(lines) or not complete or any(
                    (line.lstrip('\t') if match['tabs'] else line).startswith(delimiter)
                    for line in lines[index + 1:end]):
                return 'process-capable heredoc rule (commit message heredoc must be the whole command)'
            return None
        if end == len(lines):
            return 'process-capable heredoc rule (unterminated body)'
        body = ''.join(line.lstrip('\t') if match['tabs'] else line for line in lines[index + 1:end])
        reasons = []
        literal_read = literal_git_read_python(body, reasons)
        if literal_read and not ('I' in header['flags'] and re.fullmatch(GIT_READ_LEAD, lead)
                                 and match['delimiter'][0] in '\'"\\'):
            return ('process-capable heredoc rule (literal git read needs -I, '
                    'a cd/date/git add lead and a quoted delimiter)')
        if not (inert_python(body) or literal_read or 'I' in header['flags'] and inert_python(body, isolated=True)):
            return 'process-capable heredoc rule' + (': ' + reasons[0] if reasons else '')
        if match['delimiter'][0] not in '\'"\\':
            return 'process-capable heredoc rule (Python heredoc needs a quoted delimiter)'
        index = end + 1
        quoted_lines[index:] = literal_quotes_removed(''.join(lines[index:])).splitlines(keepends=True)
    if readers and '\\\n' in command:
        return process_heredoc_denial(command.replace('\\\n', ''), readers=True)
    return None


def shell_raw_words(text):
    """Keep raw shell words and offsets; quotes and escapes never lose their identity."""
    words, index, parentheses, backtick = [], 0, [], False
    while index < len(text):
        if text[index].isspace():
            if text[index] == '\n':
                words.append(('\n', '\n', index, index + 1))
            index += 1
            continue
        if (text[index] == '#' and (not index or text[index - 1].isspace()
                                     or text[index - 1] in ';&|(<>' or backtick)):
            if backtick or parentheses:
                raise ValueError('comment inside command substitution')
            end = text.find('\n', index)
            index = len(text) if end < 0 else end
            continue
        start, quote = index, ''
        if text[index] in ';&|()<>`':
            if text[index] == '`':
                backtick = not backtick
            if text[index] == '(':
                before = text[index - 1] if index else ''
                array = before == '=' and bool(re.search(r'(?:^|[\s;&|()<>])[A-Za-z_]\w*=$', text[:index]))
                if before and not before.isspace() and before not in ';&|()<>$' and not array:
                    raise ValueError('word-internal shell group')
                parentheses.append(before if before in '$<>=' and before else '')
            elif text[index] == ')' and parentheses:
                substitution = parentheses.pop()
                after = text[index + 1:index + 2]
                if not substitution and after and not after.isspace() and after not in ';&|()<>':
                    raise ValueError('word suffix after shell group')
            index += 1
            words.append((text[start:index], text[start:index], start, index))
            continue
        while index < len(text):
            char = text[index]
            if not quote and text[index:index + 2] == "$'":
                raise ValueError('ANSI-C shell quote')
            if char == '\\' and quote != "'":
                index += 2
                if index > len(text):
                    raise ValueError('unfinished shell escape')
                continue
            if char == quote:
                quote = ''
            elif not quote and char in "'\"":
                quote = char
            elif not quote and (char.isspace() or char in ';&|()<>`'):
                break
            index += 1
        if quote:
            raise ValueError('unfinished shell quote')
        raw = text[start:index]
        values = shlex.split(raw, comments=False)
        if len(values) != 1:
            raise ValueError('ambiguous shell word')
        words.append((raw, values[0], start, index))
    return words


def shell_without_heredoc_bodies(command):
    """Keep headers and following shell commands, without interpreting data as shell words."""
    lines, kept, pending = command.splitlines(keepends=True), [], []
    if (lines and re.fullmatch(r'[ \t]*(?:cd +[\w./-]+ +&& +)?git +commit(?: +(?:-[a-zA-Z]|--[\w-]+))* +'
                              r'(?:-m +"\$\(cat[ \t]*|-F +- +)<<-?[ \t]*(?:\'[A-Za-z0-9_]+\'|"[A-Za-z0-9_]+")\n', lines[0])
            and not process_heredoc_denial(command)):
        return ''
    quoted_lines = literal_quotes_removed(command).splitlines(keepends=True)
    for index, line in enumerate(lines):
        if pending:
            delimiter, tabs, quoted = pending[0]
            if (line.lstrip('\t') if tabs else line).removesuffix('\n') == delimiter:
                pending.pop(0)
                if not pending:
                    quoted_lines[index + 1:] = literal_quotes_removed(''.join(lines[index + 1:])).splitlines(keepends=True)
            continue
        kept.append(line)
        for match in re.finditer(r"(?<!<)<<(?!<)(-?)[ \t]*('[^'\n]+'|\"[^\"\n]+\"|\\?[^\s<>;&|()'\"`]+)", line):
            if quoted_lines[index][match.start():match.start() + 2] == '<<':
                pending.append((shlex.split(match[2])[0], bool(match[1]), match[2][0] in '\'"\\'))
    return ''.join(kept)


SHELL_INTERPRETERS = {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish', 'csh', 'tcsh', 'mksh', 'yash', 'rbash', 'ash'}
STRING_WRAPPERS = SHELL_INTERPRETERS | {'env', 'eval', 'watch', 'script', 'flock', 'su', 'trap'}


def read_only_argument_word(command, tokens, words, index):
    # These commands never run an argument word within read-only pipelines after a literal directory change.
    if not index or any(char in command for char in '$`<~'):
        return False
    try:
        original = shell_raw_words(command)
    except ValueError:
        return False
    if original != tokens or not original or any(token[0] in {'(', ')', '\n'} for token in original):
        return False
    null_redirects = set()
    for position, token in enumerate(original):
        if (token[0] == '>' and position and position + 1 < len(original)
                and original[position - 1][0] == '2' and original[position + 1][0] == '/dev/null'
                and original[position - 1][3] == token[2] and token[3] == original[position + 1][2]
                and (position == 1 or original[position - 2][3] < original[position - 1][2])):
            null_redirects.add(token[2])
    if command.count('>') != len(null_redirects):
        return False
    cursor = 0
    for token in original:
        if command[cursor:token[2]].strip():
            return False
        cursor = token[3]
    if command[cursor:].strip():
        return False
    cursor = 0
    if original[0][0] == 'cd':
        if (len(original) < 5 or original[2][0] != '&' or original[3][0] != '&'
                or original[2][3] != original[3][2]):
            return False
        path = original[1][0]
        if path.startswith('-') or any(char in path for char in "'\"\\$*?[{~^#"):
            return False
        cursor = 4
    pipelines = [[[]]]
    while cursor < len(original):
        token = original[cursor]
        if token[0] == '&':
            if (not pipelines[-1][-1] or cursor + 1 >= len(original)
                    or original[cursor + 1][0] != '&' or token[3] != original[cursor + 1][2]):
                return False
            pipelines.append([[]])
            cursor += 2
            continue
        if token[0] == ';':
            if not pipelines[-1][-1]:
                return False
            pipelines.append([[]])
        elif token[0] == '|':
            if not pipelines[-1][-1]:
                return False
            pipelines[-1].append([])
        else:
            pipelines[-1][-1].append(token)
        cursor += 1
    if not pipelines[-1][-1] or not any(pipeline[0] == words for pipeline in pipelines):
        return False
    options = {
        'grep': r'-(?:[nilrFEweCAB]|[nilrFEw]{2,})',
        'git': r'-(?:[nilrFEweCAB]|[nilrFEw]{2,})|--',
        'rg': r'-(?:[nilrFEweCABgt]|[nilFw]{2,})|--glob(?:=.*)?',
        'find': r'-(?:name|iname|type|path|maxdepth|mindepth|print|o)',
        'ls': r'-(?:[lah1]|[lah1]{2,})',
        'cat': r'(?!)',
        'head': r'-(?:n|[0-9]+)',
        'tail': r'-(?:n|[0-9]+)',
        'wc': r'-[lcwm]',
    }
    for pipeline in pipelines:
        git_grep = len(pipeline[0]) > 1 and pipeline[0][0][0] == 'git' and pipeline[0][1][0] == 'grep'
        if (pipeline[0][0][0] not in {'rg', 'grep', 'ls', 'cat', 'find'} and not git_grep
                or any(part[0][0] not in {'head', 'tail', 'wc'} for part in pipeline[1:])):
            return False
        for part in pipeline:
            if any(word[1].startswith('-') and not re.fullmatch(options[part[0][0]], word[1]) for word in part):
                return False
    for raw, value, start, end in original:
        if raw in {'|', '&', ';'} or start in null_redirects:
            continue
        if raw.startswith('='):
            return False
        quote, cursor, prefix_end = '', 0, len(raw)
        while cursor < len(raw):
            char = raw[cursor]
            if char == '!' and quote == '"':
                return False
            if char == '\\' and quote != "'":
                cursor += 2
                continue
            if char == quote:
                quote = ''
            elif not quote:
                if char in "'\"":
                    quote = char
                elif not (char.isascii() and char.isalnum() or char in '_./-*?,{}='):
                    return False
                elif char in '*?{' and prefix_end == len(raw):
                    prefix_end = cursor
            cursor += 1
        if prefix_end == len(raw) and not unresolved_shell_word(raw):
            continue
        try:
            prefix = ''.join(shlex.split(raw[:prefix_end]))
        except ValueError:
            return False
        if not prefix or prefix.startswith('-'):
            return False
        if prefix_end < len(raw) and not (
                (raw[0].isascii() and raw[0].isalnum() or raw[0] in '_./') and '/' in prefix):
            return False
    return True


def grep_data_token(tokens, index):
    start = index
    while start and tokens[start - 1][0] not in {';', '&', '|', '(', ')', '`', '\n'}:
        start -= 1
    while start < index and re.match(r'[A-Za-z_]\w*=', tokens[start][1]):
        start += 1
    if tokens[start][0] in {'grep', 'egrep', 'fgrep'}:
        return index > start
    if tokens[start][0] == 'rg':
        end = start + 1
        while end < len(tokens) and tokens[end][0] not in {';', '&', '|', '(', ')', '`', '\n'}:
            end += 1
        return index > start and not any(word[1].startswith('--pre') for word in tokens[start:end])
    if tokens[start][0] != 'git':
        return False
    cursor = start + 1
    values = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path'}
    while cursor < index:
        option = tokens[cursor][1]
        if option in values:
            cursor += 2
        elif len(option) > 2 and option.startswith(('-C', '-c')):
            cursor += 1
        elif option.partition('=')[0] in values and '=' in option:
            cursor += 1
        elif option in {'--no-pager', '--paginate', '-p'}:
            cursor += 1
        else:
            break
    return cursor < index and tokens[cursor][0] == 'grep'


def nested_shell_strings(tokens, text=None, include_env=True):
    """Keep the identity of each argument that a shell or string wrapper can execute."""
    if text is not None:
        for body in shell_substitution_bodies(text):
            yield ('', body, 0, len(text))
    for index, token in enumerate(tokens):
        name = os.path.basename(token[1])
        if name not in STRING_WRAPPERS or name == 'env' and not include_env:
            continue
        grep_data = grep_data_token(tokens, index)
        if grep_data:
            start, end = index, index + 1
            separators = {';', '&', '|', '(', ')', '`', '\n'}
            while start and tokens[start - 1][0] not in separators:
                start -= 1
            while end < len(tokens) and tokens[end][0] not in separators:
                end += 1
            command = start
            while command < index and re.match(r'[A-Za-z_]\w*=', tokens[command][1]):
                command += 1
            resolved = True
            for position in range(start, end):
                raw = tokens[position][0]
                if position <= command or position == index:
                    resolved = resolved and not unresolved_shell_word(raw)
                else:
                    spans = single_quoted_spans(raw)
                    resolved = resolved and '$' not in raw and '`' not in raw and spans is not None and not any(
                        span.startswith('=') for span, single in (spans or []) if not single)
            if resolved:
                continue
        try:
            arguments = []
            for argument in tokens[index + 1:]:
                if argument[0] in {';', '&', '|', '(', ')', '`', '\n'}:
                    break
                arguments.append(argument)
            if name in {'script', 'flock', 'su'}:
                def command_candidate(option):
                    prefix = option.partition('=')[0]
                    return (option.startswith('-') and not option.startswith('--') and 'c' in option) or (
                        prefix.startswith('--') and len(prefix) > 2 and (
                            '--command'.startswith(prefix) or name == 'su' and '--session-command'.startswith(prefix)))
                if not any(command_candidate(word[1]) for word in arguments):
                    continue
                value_options = {'script': {'-O', '-I', '-B', '-T', '-m', '--log-out', '--log-in', '--log-io',
                                             '--log-timing', '--logging-format'},
                                 'flock': {'-w', '-E', '--wait', '--timeout', '--conflict-exit-code'},
                                 'su': {'-s', '-g', '-G', '-w', '--shell', '--group', '--supp-group', '--whitelist-environment'}}
                flags = {'script': {'-q', '-f', '-e', '-a', '--quiet', '--flush', '--return', '--append'},
                         'flock': {'-s', '-x', '-u', '-n', '-o', '-F', '--shared', '--exclusive', '--unlock', '--nonblock', '--close', '--no-fork'},
                         'su': {'-', '-l', '-m', '-p', '--login', '--preserve-environment'}}
                cursor = 0
                while cursor < len(arguments):
                    option = arguments[cursor][1]
                    if option.startswith('-') and not option.startswith('--') and option != '-':
                        flag_letters = {'script': 'qfea', 'flock': 'sxunoF', 'su': 'lmp'}[name]
                        value_letters = {'script': 'OIBTm', 'flock': 'wE', 'su': 'sgGw'}[name]
                        offset = 1
                        while offset < len(option):
                            letter = option[offset]
                            if letter == 'c' or letter in value_letters:
                                if offset + 1 < len(option):
                                    if letter == 'c':
                                        word = arguments[cursor]
                                        yield (word[0][offset + 1:], option[offset + 1:], word[2] + offset + 1, word[3])
                                else:
                                    cursor += 1
                                    if cursor >= len(arguments):
                                        raise ValueError('missing wrapper option value')
                                    if letter == 'c':
                                        yield arguments[cursor]
                                break
                            if letter not in flag_letters:
                                raise ValueError('ambiguous command wrapper option')
                            offset += 1
                        cursor += 1
                        continue
                    command_option, separator, attached = option.partition('=')
                    code_option = command_candidate(option)
                    if code_option and not separator:
                        if cursor + 1 >= len(arguments):
                            raise ValueError('missing wrapper program')
                        yield arguments[cursor + 1]
                        cursor += 2
                        continue
                    if code_option and separator:
                        yield (arguments[cursor][0], attached, arguments[cursor][2], arguments[cursor][3])
                        cursor += 1
                        continue
                    if option in value_options[name]:
                        cursor += 2
                    elif option in flags[name] or not option.startswith('-'):
                        cursor += 1
                    else:
                        raise ValueError('ambiguous command wrapper option')
                continue
            if name == 'trap':
                cursor = int(bool(arguments and arguments[0][1] == '--'))
                if cursor < len(arguments):
                    yield arguments[cursor]
                continue
            if name in {'eval', 'watch'}:
                yield from arguments
                if arguments:
                    yield ('', ' '.join(word[1] for word in arguments), arguments[0][2], arguments[-1][3])
                continue
            for cursor, argument in enumerate(arguments):
                option = argument[1]
                code = (option in {'-S', '--split-string'} if name == 'env'
                        else bool(re.fullmatch(r'-[a-zA-Z]*c[a-zA-Z]*', option)))
                if code:
                    if cursor + 1 >= len(arguments):
                        raise ValueError('missing wrapper program')
                    operand = arguments[cursor + 1]
                    if name == 'env':
                        value = operand[1] + ' ' + shlex.join(word[1] for word in arguments[cursor + 2:])
                        yield (operand[0], value, operand[2], arguments[-1][3])
                    else:
                        yield from arguments[cursor + 1:]
                elif name == 'env' and option.startswith(('-S', '--split-string=')):
                    value = option[2:] if option.startswith('-S') else option.split('=', 1)[1]
                    if not value:
                        raise ValueError('missing env split string')
                    value += ' ' + shlex.join(word[1] for word in arguments[cursor + 1:])
                    yield (argument[0], value, argument[2], arguments[-1][3])
        except ValueError:
            if not grep_data:
                raise


def shell_line_continuations(text):
    """Join shell continuations while preserving literal single-quoted code."""
    kept, quote, index, comment = [], '', 0, False
    while index < len(text):
        char = text[index]
        before = kept[-1][-1:] if kept else ''
        if not quote and char == '#' and (not before or before.isspace() or before in ';&|(<>' ):
            comment = True
        if comment:
            kept.append(char)
            index += 1
            comment = char != '\n'
            continue
        if char == '\\' and quote != "'":
            if text[index:index + 2] == '\\\n':
                index += 2
                continue
            kept.append(text[index:index + 2])
            index += 2
            continue
        if char == quote:
            quote = ''
        elif not quote and char in "'\"":
            quote = char
        kept.append(char)
        index += 1
    return ''.join(kept)


def unresolved_shell_word(raw):
    """Keep expansion markers unresolved; quotes protect glob characters and leading equals."""
    if '$' in raw or '`' in raw or single_quoted_spans(raw) is None:
        return True
    quote, start, index = '', 0, 0
    while index < len(raw):
        char = raw[index]
        if char == '\\' and quote != "'":
            if index + 1 == len(raw) or not quote and raw[index + 1] in '*?[{':
                return True
            index += 2
            continue
        if char == quote:
            if quote == "'":
                start = index + 1
            quote = ''
        elif not quote:
            if char in "'\"":
                quote = char
            elif char in '*?[{' or char == '=' and index == start:
                return True
        index += 1
    return bool(quote)


def nested_work_exceeded(tokens, seen):
    return len(seen) > 64 or len(tokens) * sum(
        os.path.basename(token[1]) in STRING_WRAPPERS for token in tokens) > 50000


def shell_input_state(tokens, text, inherited=(False, False, False)):
    redirected = inherited[2] or any(token[0] == '<' for token in tokens)
    output_input = any(token[0] == '(' and token[2] > 0 and text[token[2] - 1] == '>' for token in tokens)
    piped = inherited[0] or redirected or output_input or any(token[1] == 'coproc' for token in tokens) or any(
        token[0] == '|'
        and not (index and tokens[index - 1][0] == '|' and tokens[index - 1][3] == token[2])
        and not (index + 1 < len(tokens) and tokens[index + 1][0] == '|' and tokens[index + 1][2] == token[3])
        for index, token in enumerate(tokens))
    directory = inherited[1] or any(token[1] in {'cd', 'pushd'} for token in tokens)
    return piped, directory, redirected


def python_program(arguments):
    """Return the program kind, flags, word index, and attached operand offset."""
    flags, cursor = '', 0
    while cursor < len(arguments):
        option = arguments[cursor]
        if option == '--':
            return ('script' if cursor + 1 < len(arguments) else 'stdin', flags, cursor + 1, 0)
        if option == '-' or not option.startswith('-'):
            return ('stdin' if option == '-' else 'script', flags, cursor, 0)
        if option == '--check-hash-based-pycs':
            cursor += 2
            continue
        if option.startswith('--check-hash-based-pycs='):
            cursor += 1
            continue
        if option.startswith('--'):
            return 'unknown', flags, cursor, 0
        offset = 1
        while offset < len(option):
            flag = option[offset]
            if flag in 'cm':
                attached = offset + 1 < len(option)
                return flag, flags, cursor if attached else cursor + 1, offset + 1 if attached else 0
            if flag in 'WX':
                if offset + 1 == len(option):
                    cursor += 1
                break
            if flag not in 'bBdEhiIOPqRsSuvVx':
                return 'unknown', flags, cursor, 0
            flags += flag
            offset += 1
        cursor += 1
    return 'stdin', flags, cursor, 0


def python_inline_denial(command):
    """Check every Python -c word, including wrapper arguments and nested shell strings."""
    shell = shell_line_continuations(shell_without_heredoc_bodies(command))
    pending = [(shell, (False, False, False))]
    seen = set()
    while pending:
        text, inherited = pending.pop()
        text = shell_line_continuations(text)
        identity = (text, inherited)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            tokens = shell_raw_words(text)
        except ValueError as error:
            return 'unparsed shell syntax rule: ' + str(error)
        if nested_work_exceeded(tokens, seen):
            return 'process-capable python -c rule (nesting limit)'
        segments, current = [], []
        for token in tokens:
            if token[0] in {';', '&', '|', '(', ')', '`', '\n'}:
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)
        for words in segments:
            for index, (raw, value, start, end) in enumerate(words):
                if grep_data_token(words, index):
                    continue
                if not re.fullmatch(PYTHON_NAME, os.path.basename(value)):
                    continue
                arguments = words[index + 1:]
                kind, flags, operand, offset = python_program([word[1] for word in arguments])
                if any(unresolved_shell_word(word[0]) for word in arguments[:operand + (kind != 'c')]):
                    return 'process-capable python -c rule'
                if kind != 'c':
                    if any(re.match(r'^-[bBdEhiIOPqRsSuvVx]*c', word[1]) for word in arguments):
                        return 'process-capable python -c rule'
                    continue
                if operand >= len(arguments):
                    return 'process-capable python -c rule'
                for code_word in [arguments[operand]]:
                    code_raw = code_word[0][offset:]
                    code = code_raw[1:-1]
                    literal = (len(code_raw) >= 2 and (
                        code_raw[0] == code_raw[-1] == "'" and "'" not in code
                        or code_raw[0] == code_raw[-1] == '"' and not any(char in code for char in '$`\\"')))
                    reasons = []
                    admitted = literal and (inert_python(code) or 'I' in flags and (
                        inert_python(code, isolated=True) or literal_git_read_python(code, reasons)))
                    if raw != value or re.search(r'[$`*?\[\]{}]', raw) or not admitted:
                        return 'process-capable python -c rule' + (': ' + reasons[0] if reasons else '')
                    rest = text[:start] + text[code_word[3]:]
                    isolated = 'I' in flags and not inert_python(code)
                    if python_writes(code, isolated=isolated) and (not check_only_shell(rest) or text != shell):
                        return 'python -c then run rule'
                    break
        state = shell_input_state(tokens, text, inherited)
        pending.extend((token[1], state) for token in nested_shell_strings(tokens, text))
    return None


# Each interpreter lists short inline-code/module flags, long flags, and code subcommands.
INLINE_INTERPRETERS = {
    'node': ('ep', {'--eval', '--print'}, set()),
    'nodejs': ('ep', {'--eval', '--print'}, set()),
    'perl': ('eEpMm', set(), set()),
    'ruby': ('e', set(), set()),
    'php': ('r', set(), set()),
    'pypy': ('cm', set(), set()),
    'pypy3': ('cm', set(), set()),
    'lua': ('e', set(), set()),
    'luajit': ('e', set(), set()),
    'deno': ('', set(), {'eval'}),
    'bun': ('ep', {'--eval', '--print'}, set()),
    'Rscript': ('e', set(), set()),
    'osascript': ('e', set(), set()),
}


def interpreter_name(value):
    base = os.path.basename(value)
    for name in INLINE_INTERPRETERS:
        if re.fullmatch(re.escape(name) + r'(?:\d+(?:\.\d+)*|(?:\.\d+)+)?', base):
            return name
    return 'python' if re.fullmatch(PYTHON_NAME, base) else None


def code_option(value):
    return bool(re.match(r'--(?:eval|print)(?:=|$)|-[ceEpr]|-[a-zA-Z]*[ceE]', value))


def stdin_program_path(value):
    path = os.path.normpath(re.sub(r'/+', '/', value))
    resolved = os.path.normpath(os.path.join(os.getcwd(), path))
    return (value == '-' or '..' in value.split('/') or path in {'dev', 'proc'}
            or path.startswith(('dev/', 'proc/')) or resolved in {'/dev', '/proc'}
            or resolved.startswith(('/dev/', '/proc/')))


def unsafe_script_path(value, base):
    path = os.path.realpath(os.path.join(base, value))
    return path in {'/proc', '/dev'} or path.startswith(('/proc/', '/dev/'))


def chdir_wrapper_present(command, env_directories):
    shell = shell_line_continuations(shell_without_heredoc_bodies(command))
    pending, seen = [shell], set()
    targets = []
    directory_change = split_string = False
    while pending:
        first_segment = not seen
        text = shell_line_continuations(pending.pop())
        if text in seen:
            continue
        seen.add(text)
        try:
            tokens = shell_raw_words(text)
            if nested_work_exceeded(tokens, seen):
                return True
            for index, token in enumerate(tokens):
                if token[0] in {';', '&', '|', '(', ')', '`', '\n'}:
                    first_segment = False
                name = os.path.basename(token[1])
                if token[1] in {'cd', 'pushd'}:
                    directory_change = True
                if name in {'chroot', 'nsenter', 'unshare', 'setpriv', 'runuser', 'su', 'systemd-run', 'doas'}:
                    if index + 1 < len(tokens):
                        return True
                if name not in {'env', 'sudo'}:
                    continue
                flags = {'env': {'-i', '--ignore-environment', '-0', '--null', '-v', '--debug'},
                         'sudo': {'-n', '--non-interactive', '-E', '--preserve-env', '-H', '--set-home',
                                  '-k', '-K', '-S', '-b', '--background'}}[name]
                values = {'env': {'-u', '--unset', '-S', '--split-string'},
                          'sudo': {'-u', '--user', '-g', '--group', '-p', '--prompt', '-h', '--host'}}[name]
                cursor = index + 1
                while cursor < len(tokens):
                    option = tokens[cursor][1]
                    if not option.startswith('-'):
                        if re.match(r'[A-Za-z_]\w*=', option):
                            cursor += 1
                            continue
                        break
                    if option == '--':
                        break
                    if name == 'env' and (option == '--chdir' or option.startswith(('-C', '--chdir='))):
                        separate = option in {'-C', '--chdir'}
                        if separate:
                            if cursor + 1 >= len(tokens):
                                return True
                            raw, target = tokens[cursor + 1][:2]
                        else:
                            offset = 2 if option.startswith('-C') else len('--chdir=')
                            raw, target = tokens[cursor][0], option[offset:]
                        if (not first_segment or unresolved_shell_word(raw) or not os.path.isabs(target)
                                or '..' in target.split('/') or not re.fullmatch(r'[\w./-]+', target)
                                or not os.path.isdir(target)):
                            return True
                        targets.append(target)
                        cursor += 2 if separate else 1
                    elif option in flags:
                        cursor += 1
                    elif option in values:
                        if name == 'env' and option in {'-S', '--split-string'}:
                            split_string = True
                            if cursor + 1 >= len(tokens):
                                return True
                            payload = tokens[cursor + 1][1]
                            if '\\' in payload or '$' in payload:
                                return True
                            pending.append('env ' + payload)
                        cursor += 2
                    elif '=' in option and option.partition('=')[0] in values:
                        if name == 'env' and option.startswith('--split-string='):
                            split_string = True
                            payload = option.partition('=')[2]
                            if '\\' in payload or '$' in payload:
                                return True
                            pending.append('env ' + payload)
                        cursor += 1
                    elif name == 'env' and option.startswith('-S') and len(option) > 2:
                        split_string = True
                        payload = option[2:]
                        if '\\' in payload or '$' in payload:
                            return True
                        pending.append('env ' + payload)
                        cursor += 1
                    else:
                        return True
            pending.extend(token[1] for token in nested_shell_strings(tokens, text))
        except ValueError:
            return True
    if targets:
        if len(targets) != 1 or directory_change or split_string:
            return True
        env_directories.extend(targets)
    return False


def safe_directory_state(command, cwd=None):
    """Prove one literal directory step stays outside device and process filesystems."""
    pending, seen, targets = [shell_without_heredoc_bodies(command)], set(), []
    while pending:
        text = shell_line_continuations(pending.pop())
        if text in seen:
            continue
        seen.add(text)
        if 'CDPATH' in text or 'cdable_vars' in text:
            return False
        try:
            tokens = shell_raw_words(text)
            if nested_work_exceeded(tokens, seen):
                return False
            for index, token in enumerate(tokens):
                if token[1] not in {'cd', 'pushd'}:
                    continue
                cursor = index + 1
                while cursor < len(tokens) and tokens[cursor][1] in {'-L', '-P', '-e', '-@'}:
                    cursor += 1
                if cursor >= len(tokens):
                    return False
                raw, target = tokens[cursor][:2]
                if (unresolved_shell_word(raw) or not target or target.startswith(('-', '~'))
                        or '..' in target.split('/') or not re.fullmatch(r'[\w./-]+', target)):
                    return False
                targets.append(target)
            pending.extend(token[1] for token in nested_shell_strings(tokens, text))
        except ValueError:
            return False
    if len(targets) != 1:
        return False
    base = os.path.realpath(cwd or os.getcwd())
    target = os.path.realpath(os.path.join(base, targets[0]))
    forbidden = lambda path: path in {'/proc', '/dev'} or path.startswith(('/proc/', '/dev/'))
    return target if not forbidden(base) and not forbidden(target) and os.path.isdir(target) else False


def shell_without_redirections(tokens):
    """Keep redirect targets and descriptor operators out of command and list positions."""
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        raw, _, _, end = token
        cursor += 1
        if (re.fullmatch(r'\d+|\{[A-Za-z_][A-Za-z0-9_]*}', raw)
                and cursor < len(tokens) and tokens[cursor][0] in {'<', '>'}
                and end == tokens[cursor][2]):
            continue
        if raw in {'<', '>'} or (raw == '&' and cursor < len(tokens)
                and tokens[cursor][0] == '>' and end == tokens[cursor][2]):
            while (cursor < len(tokens) and tokens[cursor][0] in {'<', '>', '&', '|'}
                   and tokens[cursor - 1][3] == tokens[cursor][2]):
                cursor += 1
            if cursor < len(tokens) and tokens[cursor][0] not in {';', '&', '|', '(', ')', '`', '\n'}:
                cursor += 1
            continue
        yield token


def shell_command_positions(tokens):
    """Resolve shell prefixes without treating ordinary argument words as commands."""
    positions, command_start, time_option = set(), True, False
    for raw, value, start, _ in shell_without_redirections(tokens):
        if raw in {';', '&', '|', '(', ')', '`', '\n'}:
            command_start, time_option = True, False
            continue
        if not command_start:
            continue
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', value, re.S):
            continue
        if time_option and value in {'-p', '--'}:
            time_option = False
            continue
        positions.add(start)
        command_start = value in {'command', 'builtin', 'exec', 'time', '!', 'if', 'elif',
                                  'while', 'until', 'then', 'do', 'else', '{'}
        time_option = value in {'command', 'builtin', 'exec', 'time'}
    return positions


def shell_defines_function(tokens, positions):
    return any(value == 'function' and start in positions or start in positions
               and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value)
               and index + 2 < len(tokens) and tokens[index + 1][0] == '('
               and tokens[index + 2][0] == ')'
               for index, (_, value, start, _) in enumerate(tokens))


def array_subscript_denial(words, arithmetic, tokens, groups, names_only=False):
    spans = []
    for raw, _, _, _ in words:
        parts, start, cursor, double = [], 0, 0, False
        while cursor < len(raw):
            char = raw[cursor]
            if char == '\\':
                cursor += 2
                continue
            if char == '"':
                double = not double
            elif char == "'" and not double:
                end = raw.find("'", cursor + 1)
                if end < 0:
                    parts = None
                    break
                parts.extend(((raw[start:cursor], False), (raw[cursor:end + 1], True)))
                start = cursor = end + 1
                continue
            cursor += 1
        spans.append(None if parts is None or double else parts + [(raw[start:], False)])
    printf_safe = (not any(value in {'alias', 'enable', 'hash', 'shopt', 'eval', 'trap', 'source'}
                           for _, value, _, _ in tokens)
                   and not any(value == '.' and start in shell_command_positions(tokens)
                               for _, value, start, _ in tokens)
                   and not shell_defines_function(tokens, shell_command_positions(tokens)))
    checked_words = [] if names_only else words
    legacy = any(parts is None or any('$[' in span for span, single in parts if not single) for parts in spans)
    expanded = lambda value: '$' in value or '`' in value
    unsafe_name = lambda value: '[' in value or expanded(value)
    for index, (raw, value, start, _) in enumerate(checked_words):
        parts = spans[index]
        if (start in arithmetic or legacy) and expanded(value):
            return 'array subscript evaluation rule (arithmetic)'
        printf_data = (printf_safe and index > 1 and words[0][0] == 'printf'
                       and words[1][1] and not words[1][1].startswith(('-', '$', '`'))
                       and not unresolved_shell_word(words[1][0])
                       and raw.startswith("'") and raw.endswith("'") and "'" not in raw[1:-1])
        if ((grep_data_token(words, index) or printf_data) and parts is not None
                and not any(any(char in span for char in '$`\\') for span, single in parts if not single)):
            continue
        # Bash can evaluate a stored subscript payload long after shell quote removal.
        if re.search(r'\[[^]]*(?:\$[({\[A-Za-z_]|\x60|[<>]\()', value):
            return 'array subscript evaluation rule (subscript payload)'
        raw_brackets, offset = [], 0
        for span, single in parts or [(raw, False)]:
            if not single:
                raw_brackets.extend(offset + match.start() for match in re.finditer(r'\[', span))
            offset += len(span)
        for text, brackets in ((raw, raw_brackets), (value, [match.start() for match in re.finditer(r'\[', value)])):
            for bracket in brackets:
                cursor, quote, depth = bracket + 1, '', 1
                while cursor < len(text):
                    char = text[cursor]
                    if char == '\\' and quote != "'":
                        cursor += 2
                        continue
                    if char == quote:
                        quote = ''
                    elif not quote and char in "'\"":
                        quote = char
                    elif not quote and char == '[':
                        depth += 1
                    elif not quote and char == ']':
                        depth -= 1
                        if depth == 0:
                            break
                    cursor += 1
                if re.search(r'\$[({\[A-Za-z_]|\x60|[<>]\(', text[bracket + 1:cursor]):
                    return 'array subscript evaluation rule (subscript payload)'
        offset = 0
        for span, single in parts or []:
            if not single:
                for arithmetic_text in re.finditer(r'\$\(\(|\$\[', span):
                    if expanded(raw[offset + arithmetic_text.end():]):
                        return 'array subscript evaluation rule (arithmetic)'
                for parameter in re.finditer(r'\$\{', span):
                    tail = raw[offset + parameter.end():]
                    braced = tail.partition('}')[0]
                    if any(char in braced for char in "\\'\"") or braced.count('[') > braced.count(']'):
                        braced = tail
                    if re.search(r':(?![-=?+])', braced) and expanded(tail):
                        return 'array subscript evaluation rule (arithmetic)'
            offset += len(span)
    if not names_only:
        return None

    names = {'printf', 'test', '[', '[[', 'declare', 'typeset', 'local', 'export', 'readonly', 'unset', 'read', 'wait', 'let'}
    for position, (raw, name, start, end) in enumerate(words):
        parts = spans[position]
        if (grep_data_token(words, position) and parts is not None
                and not any(any(char in span for char in '$`\\') for span, single in parts if not single)):
            continue
        unquoted = re.sub(r'''\\.|'[^']*'|"(?:\\.|[^"\\])*"''', '', raw)
        if (any(char in unquoted for char in '{,')
                and (unsafe_name(name) or any(token[2] == end for token in tokens))
                and any(piece in names for piece in re.split(r'[{,}]', name))):
            return 'array subscript evaluation rule (name)'
        if name not in names:
            continue
        operands = []
        arguments = words[position + 1:]
        if name == '[[':
            start = next(index for index, token in enumerate(tokens) if token[2] == start)
            end = start + 1
            while end < len(tokens):
                token = tokens[end]
                substitution = (token[0] == '`' or token[0] == '(' and end > 0
                                and tokens[end - 1][3] == token[2]
                                and (tokens[end - 1][0].endswith('$') or tokens[end - 1][0] in {'<', '>'}))
                if substitution and end in groups:
                    end = groups[end] + 1
                elif token[0] == ']]':
                    break
                else:
                    end += 1
            arguments = tokens[start + 1:end]
            for index, word in enumerate(arguments):
                if word[1] in {'-eq', '-ne', '-lt', '-le', '-gt', '-ge'}:
                    if any(expanded(token[1]) for token in arguments[max(0, index - 1):index] + arguments[index + 1:index + 2]):
                        return 'array subscript evaluation rule (arithmetic)'
        filtered, index = [], 0
        while index < len(arguments):
            if re.fullmatch(r'\d*[<>]+', arguments[index][0]):
                index += 2
            else:
                filtered.append(arguments[index][1])
                index += 1
        arguments = filtered
        if name == 'printf':
            index = 0
            while index < len(arguments):
                option = arguments[index]
                if option == '--' or not option.startswith('-'):
                    break
                if option == '-v':
                    index += 1
                    operands.extend(arguments[index:index + 1])
                elif option.startswith('-v'):
                    operands.append(option[2:])
                index += 1
        elif name in {'test', '[', '[['}:
            operands.extend(right for left, right in zip(arguments, arguments[1:]) if left == '-v')
        elif name in {'declare', 'typeset', 'local', 'export', 'readonly', 'unset'}:
            indirect, options = False, True
            for value in arguments:
                if options and value == '--':
                    options = False
                elif options and value.startswith(('-', '+')):
                    indirect = indirect or name in {'declare', 'typeset', 'local'} and any(char in value for char in 'in')
                else:
                    target, separator, assigned = value.partition('=')
                    operands.append(target.removesuffix('+'))
                    if indirect and separator:
                        operands.append(assigned)
        elif name in {'read', 'wait'}:
            index, options = 0, True
            while index < len(arguments):
                value = arguments[index]
                if options and value == '--':
                    options = False
                elif options and value.startswith('-'):
                    for offset, option in enumerate(value[1:], 2):
                        if option in ('adinNptu' if name == 'read' else 'p'):
                            operand = value[offset:]
                            if not operand:
                                index += 1
                                operand = arguments[index] if index < len(arguments) else ''
                            if option == ('a' if name == 'read' else 'p'):
                                operands.append(operand)
                            break
                elif name == 'read':
                    operands.append(value)
                index += 1
        elif name == 'let':
            if any(expanded(value) for value in arguments):
                return 'array subscript evaluation rule (arithmetic)'
            operands.extend(arguments)
        if any(unsafe_name(value) for value in operands):
            return 'array subscript evaluation rule (name)'
    return None


def arithmetic_end(text, start, closing):
    """Match arithmetic delimiters without ending at a nested parenthesis or bracket."""
    cursor, depth, quote = start, [], ''
    while cursor < len(text):
        char = text[cursor]
        if char == '\\' and quote != "'":
            cursor += 2
            continue
        if char == quote:
            quote = ''
        elif not quote and char in "'\"":
            quote = char
        elif not quote:
            if not depth and text.startswith(closing, cursor):
                return cursor
            if char in '([':
                depth.append(')' if char == '(' else ']')
            elif depth and char == depth[-1]:
                depth.pop()
        cursor += 1
    return len(text)


def parameter_quote_mode(text, start):
    parameter = re.match(r'[!#]?(?:[A-Za-z_][A-Za-z0-9_]*|[0-9@*?#$!_-])(?:\[[^]]*\])?', text[start:])
    tail = text[start + parameter.end():] if parameter else text[start:]
    if re.match(r':?[-+=?]', tail):
        return 'word'
    if tail.startswith(('#', '%')):
        return 'pattern'
    if not tail or tail.startswith('}') or re.match(r':(?![-+=?])', tail):
        return 'arithmetic'
    return 'other'


def shell_substitution_bodies(text, arithmetic_quotes=False):
    """Keep substitution quote state separate from the surrounding shell word."""
    frames, quote, cursor, word_start = [], '', 0, True
    while cursor < len(text):
        char = text[cursor]
        context = frames[-1][0] if frames else ''
        double_operand = context == '}' and frames[-1][2] == '"'
        operand_mode = parameter_quote_mode(text, frames[-1][1]) if double_operand else ''
        if double_operand and char == "'" and operand_mode == 'other':
            raise ValueError('shell substitution boundary')
        if arithmetic_quotes and char == "'" and (
                context in {'))', ']'} and frames[-1][2] == '"'
                or double_operand and (operand_mode == 'arithmetic' or re.fullmatch(
                    r'[!#]?(?:[A-Za-z_][A-Za-z0-9_]*|[0-9@*?#$!_-])\[[^]]*',
                    text[frames[-1][1]:cursor]))):
            raise ValueError('shell substitution boundary')
        if (not quote and context == ')' and word_start
                and re.match(r'case(?=$|[\s;&|()])', text[cursor:])):
            raise ValueError('shell substitution boundary')
        if not quote and context not in {'}', '))', ']'} and char == '#' and word_start:
            end = text.find('\n', cursor)
            comment = text[cursor:len(text) if end < 0 else end]
            if context == '`':
                comment = comment.partition('`')[0]
            if any(marker in comment for marker in ('$(', '`', '${')):
                raise ValueError('shell comment substitution')
            cursor = len(text) if end < 0 else end + 1
            word_start = True
            continue
        if char == '\\' and quote != "'":
            cursor += 2
            word_start = False
            continue
        if quote == "'":
            if char == quote:
                quote = ''
        elif char == '`' and context == '`':
            _, start, quote, _ = frames.pop()
            yield text[start:cursor]
        elif text.startswith(('$((', '${', '$['), cursor):
            opening = 3 if text.startswith('$((', cursor) else 2
            closing = '))' if opening == 3 else '}' if text.startswith('${', cursor) else ']'
            frames.append((closing, cursor + opening, quote, 1))
            quote = ''
            cursor += opening
            word_start = False
            continue
        elif text.startswith('$(', cursor):
            frames.append((')', cursor + 2, quote, 1))
            quote = ''
            cursor += 2
            word_start = True
            continue
        elif char == '`':
            frames.append(('`', cursor + 1, quote, 1))
            quote = ''
            cursor += 1
            word_start = True
            continue
        elif char == quote:
            quote = ''
        elif char in "'\"" and not quote and not (char == "'" and double_operand and operand_mode == 'word'):
            quote = char
        elif not quote and frames:
            closing, start, outer_quote, depth = frames[-1]
            if char == '(' and closing in {')', '))'}:
                frames[-1] = (closing, start, outer_quote, depth + 1)
            elif char == ')' and closing == '))' and depth > 1:
                frames[-1] = (closing, start, outer_quote, depth - 1)
            elif char == '[' and closing == ']':
                frames[-1] = (closing, start, outer_quote, depth + 1)
            elif text.startswith(closing, cursor):
                if depth == 1:
                    frames.pop()
                    if closing == ')':
                        yield text[start:cursor]
                    quote = outer_quote
                    cursor += len(closing)
                    word_start = closing == ')'
                    continue
                frames[-1] = (closing, start, outer_quote, depth - 1)
        word_start = not quote and char in ' \t\n;&|()'
        cursor += 1
    for closing, start, _, _ in frames:
        if closing in {')', '`'}:
            yield text[start:]


def shell_brace_text(raw):
    """Keep bare braces separate from parameter expansion braces."""
    while '${' in raw:
        reduced = re.sub(r'\$\{[^{}]*\}', '', raw)
        if reduced == raw:
            break
        raw = reduced
    return re.sub(r'''\\.|'[^']*'|"(?:\\.|[^"\\])*"''', '', raw)


def runtime_name_denial(text, tokens, arithmetic, groups, commands):
    """Refuse unresolved values where Bash recursively evaluates names or arithmetic."""
    reason = 'array subscript evaluation rule ('
    identifier = r'[A-Za-z_][A-Za-z0-9_]*'
    regions = []
    for index, token in enumerate(tokens):
        if token[2] in arithmetic:
            regions.append((token[2], token[3]))
    merged = []
    for start, end in regions:
        if merged and not text[merged[-1][1]:start].strip():
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    regions = merged
    # Token gaps contain comments; preserve offsets while discarding their inert text.
    source = [' ' if char != '\n' else '\n' for char in text]
    for _, _, start, end in tokens:
        source[start:end] = text[start:end]
    text = ''.join(source)
    quote, cursor, parameters = '', 0, []
    while cursor < len(text):
        if parameters and cursor == parameters[-1][0]:
            _, quote, _ = parameters.pop()
            cursor += 1
            continue
        char = text[cursor]
        if char == '\\' and quote != "'":
            cursor += 2
            continue
        double_operand = bool(parameters and parameters[-1][1] == '"' and parameters[-1][2] == 'word')
        if char == quote:
            quote = ''
        elif char in "'\"" and not quote and not (char == "'" and double_operand):
            quote = char
        elif quote != "'" and text.startswith(('$((', '$['), cursor):
            opening = 3 if text.startswith('$((', cursor) else 2
            closing = '))' if opening == 3 else ']'
            end = arithmetic_end(text, cursor + opening, closing)
            regions.append((cursor + opening, end))
        elif quote != "'" and text.startswith('${', cursor):
            start, end, inner_quote, brackets, braces = cursor + 2, cursor + 2, '', 0, 1
            mode = parameter_quote_mode(text, start)
            literal_single = (quote == '"' or double_operand) and mode == 'word'
            while end < len(text):
                current = text[end]
                if current == '\\' and inner_quote != "'":
                    end += 2
                    continue
                if current == inner_quote:
                    inner_quote = ''
                elif (current in "'\"" and not inner_quote
                      and not (current == "'" and literal_single)):
                    inner_quote = current
                elif not inner_quote:
                    if current == '[':
                        brackets += 1
                    elif current == ']':
                        brackets -= 1
                    elif text.startswith('${', end):
                        braces += 1
                        end += 1
                    elif current == '}' and brackets == 0:
                        braces -= 1
                        if braces == 0:
                            break
                end += 1
            body = text[start:end]
            if body.startswith('!') and not re.fullmatch(rf'!{identifier}(?:[*@]|\[[*@]\])', body):
                return reason + 'indirect)'
            parameter = re.match(rf'[!#]?{identifier}', body)
            if parameter:
                offset = parameter.end()
                if body[offset:offset + 1] == '[':
                    close = body.rfind(']')
                    subscript = body[offset + 1:close if close >= 0 else len(body)]
                    if re.search(r'\$|`|[<>]\(', subscript):
                        return reason + 'subscript payload)'
                    if subscript.strip() not in {'@', '*'}:
                        regions.append((start + offset + 1, start + (close if close >= 0 else len(body))))
                    offset = close + 1 if close >= 0 else len(body)
                if body[offset:offset + 1] == ':' and body[offset + 1:offset + 2] not in {'-', '=', '?', '+'}:
                    regions.append((start + offset + 1, end))
            parameters.append((end, '"' if quote == '"' or double_operand else quote, mode))
            quote = ''
            cursor = start - 1
        cursor += 1
    for raw, _, start, _ in tokens:
        match = re.match(rf'{identifier}\[(.*?)\](?:\+?=)', raw)
        if match and match[1].strip() not in {'@', '*'}:
            regions.append((start + match.start(1), start + match.end(1)))
    for opening, closing in groups.items():
        if tokens[opening][0] != '(' or not opening:
            continue
        if not re.fullmatch(rf'{identifier}=', tokens[opening - 1][1]):
            continue
        for raw, _, start, _ in tokens[opening + 1:closing]:
            match = re.match(r'\[([^]]*)\]=', raw)
            if match:
                regions.append((start + match.start(1), start + match.end(1)))
    name_commands = {'printf', 'test', '[', '[[', 'declare', 'typeset', 'local', 'export',
                     'readonly', 'unset', 'read', 'wait', 'let', 'mapfile', 'readarray', 'getopts'}
    attributes = {}
    for words in commands:
        if words and words[0][1].startswith('-') and any(
                tokens[closing][3] <= words[0][2] and not text[tokens[closing][3]:words[0][2]].strip()
                and opening > 0 and tokens[opening - 1][0] == '$'
                for opening, closing in groups.items()):
            return reason + 'name)'
        for index, (raw, value, start, end) in enumerate(words):
            for name, (attribute, declared_end) in attributes.items():
                read_removed = re.sub(rf'\$(?:{name}(?![A-Za-z0-9_])|\{{{name}\}})', '', value)
                if start > declared_end and re.search(rf'(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])', read_removed):
                    literal = rf'{re.escape(name)}=' + (r'[0-9]+' if attribute == 'i' else identifier)
                    if not re.fullmatch(literal, value):
                        return reason + 'attribute)'
            unquoted = re.sub(r'''\\.|'[^']*'|"(?:\\.|[^"\\])*"''', '', raw)
            if (shell_brace_text(raw).startswith('{') and re.search(r'[,]|\.\.', shell_brace_text(raw))
                    and all(re.fullmatch(rf'{identifier}=.*', word[1], re.S) for word in words[:index])
                    and not re.match(rf'{identifier}=', value)):
                return reason + 'name)'
            arguments = words[index + 1:]
            if start in arithmetic or any(left <= start < right for left, right in regions):
                continue
            if value not in name_commands:
                command_start = 0
                while command_start < index and re.fullmatch(rf'{identifier}=.*', words[command_start][1], re.S):
                    command_start += 1
                while command_start < index and words[command_start][1] in {
                        'command', 'builtin', '!', 'time', 'exec', 'if', 'elif', 'while',
                        'until', 'then', 'do', 'else', '{'}:
                    wrapper = words[command_start][1]
                    command_start += 1
                    if wrapper in {'command', 'time'} and command_start < index and words[command_start][1] == '-p':
                        command_start += 1
                    if command_start < index and words[command_start][1] == '--':
                        command_start += 1
                prefix = command_start == index
                if (prefix and not re.match(rf'{identifier}=', value)
                        and any(char in raw for char in '$`') and any(
                        word[1].startswith('-') or any(char in word[1] for char in '$`[') for word in arguments)):
                    return reason + 'name)'
                continue
            if any(re.search(r'\{[^}]*?(?:,|\.\.)', shell_brace_text(word[0]))
                   and any(char in word[1] for char in '-$`') for word in arguments):
                return reason + 'name)'
            if value in {'printf', 'test', '[', 'wait'}:
                candidates, first = arguments, 0
                if value == 'printf':
                    first, ended_options = 0, False
                    while first < len(arguments) and arguments[first][1].startswith('-'):
                        if any(char in arguments[first][1] for char in '$`'):
                            return reason + 'name)'
                        if arguments[first][1] == '--':
                            ended_options = True
                            first += 1
                            break
                        if arguments[first][1] == '-v':
                            first += 1
                        first += 1
                    candidates = [] if ended_options else arguments[first:first + 1]
                for position, argument in enumerate(candidates, first):
                    arg_raw, arg_value, _, _ = argument
                    outside_quotes = re.sub(r'''\\.|'[^']*'|"(?:\\.|[^"\\])*"''', '', arg_raw)
                    if value == 'printf':
                        if arg_value.startswith(('$', '`')) or any(char in outside_quotes for char in '*?['):
                            return reason + 'name)'
                        continue
                    if (re.search(r'\$[@*]|\[[@*]\]', arg_raw)
                            or any(char in outside_quotes for char in '$`')
                            or any(char in arg_value for char in '$`') and position + 1 < len(arguments)
                            and any(char in arguments[position + 1][1] for char in '$`[')):
                        return reason + 'name)'
            if value == 'let':
                regions.extend((word[2], word[3]) for word in arguments)
            elif value in {'declare', 'typeset', 'local'}:
                attribute = ''
                for arg_raw, argument, arg_start, arg_end in arguments:
                    if argument.startswith('-'):
                        if any(char in argument for char in '$`'):
                            return reason + 'attribute)'
                        attribute = 'i' if 'i' in argument else 'n' if 'n' in argument else attribute
                    elif re.match(rf'{identifier}=\(', argument):
                        for subscript in re.finditer(r'\[([^]]*)\]=', arg_raw):
                            regions.append((arg_start + subscript.start(1), arg_start + subscript.end(1)))
                    elif attribute:
                        target = argument.partition('=')[0]
                        if re.fullmatch(identifier, target):
                            attributes[target] = (attribute, arg_end)
                        if attribute == 'i' and '=' in argument:
                            regions.append((arg_start + arg_raw.find('=') + 1, arg_end))
            elif value in {'mapfile', 'readarray'}:
                operand, options = 0, True
                while operand < len(arguments):
                    argument = arguments[operand][1]
                    if options and argument == '--':
                        options = False
                    elif options and argument.startswith('-'):
                        for offset, option in enumerate(argument[1:], 2):
                            if option == 'C':
                                return reason + 'name)'
                            if option in 'dnOsuc':
                                if offset == len(argument):
                                    operand += 1
                                break
                    elif any(char in argument for char in '$`['):
                        return reason + 'name)'
                    operand += 1
            elif value == 'getopts' and len(arguments) > 1 and any(char in arguments[1][1] for char in '$`['):
                return reason + 'name)'
            elif value == '[[':
                token_index = next(i for i, word in enumerate(tokens) if word[2] == start)
                end_index = token_index + 1
                while end_index < len(tokens):
                    token = tokens[end_index]
                    substitution = (token[0] == '`' or token[0] == '(' and end_index > 0
                                    and tokens[end_index - 1][3] == token[2]
                                    and tokens[end_index - 1][0].endswith('$'))
                    if substitution and end_index in groups:
                        end_index = groups[end_index] + 1
                    elif token[0] == ']]':
                        break
                    else:
                        end_index += 1
                for position in range(token_index + 1, end_index):
                    if tokens[position][1] in {'-eq', '-ne', '-lt', '-le', '-gt', '-ge'}:
                        for neighbor in (position - 1, position + 1):
                            if neighbor < len(tokens):
                                word = tokens[neighbor]
                                if word[0] in {')', '`'} or neighbor in groups:
                                    return reason + 'arithmetic)'
                                regions.append((word[2], word[3]))
    numeric, assignments, numeric_scopes = set(), {}, {}
    control_words = []
    false_closer = False
    for words in commands:
        if words:
            previous = next((token for token in reversed(tokens) if token[2] < words[0][2]), None)
            if previous is not None and previous[0] not in {';', '&', '|', '(', ')', '`', '\n'}:
                continue
        time_prefix = False
        for index, word in enumerate(words):
            if re.fullmatch(rf'{identifier}=.*', word[1], re.S):
                break
            if word[0] != word[1]:
                break
            if time_prefix and word[0] in {'-p', '--'}:
                continue
            time_prefix = word[0] == 'time'
            if (index and word[0] in {'fi', 'done', 'esac'}
                    and any(words[index - 1][3] <= token[2] < word[2] for token in tokens)):
                false_closer = True
            control_words.append(word)
            if word[0] not in {'then', 'do', 'else', '{', '!', 'if', 'elif', 'time'}:
                break
    open_kinds = []
    for raw, _, start, end in sorted(control_words, key=lambda word: word[2]):
        before = next((token for token in reversed(tokens) if token[2] < start), ('',))
        after = next((token for token in tokens if token[2] >= end), ('',))
        if (raw in {'if', 'while', 'until', 'case', 'for', 'select', 'fi', 'done', 'esac'}
                and 'case' in open_kinds and after[0] in {'|', ')'}
                and not (raw == 'esac' and open_kinds[-1] == 'case' and before[0] not in {'|', '('})):
            false_closer = True
        if raw in {'if', 'while', 'until', 'case', 'for', 'select'}:
            open_kinds.append(raw)
        elif raw in {'fi', 'done'} and open_kinds and open_kinds[-1] == 'case':
            false_closer = True
        elif open_kinds and raw == {'if': 'fi', 'case': 'esac'}.get(open_kinds[-1], 'done'):
            open_kinds.pop()
    loop_ends, loop_stack = {}, []
    for raw, _, start, end in sorted(control_words, key=lambda word: word[2]):
        if raw in {'for', 'while', 'until', 'select'}:
            loop_stack.append(start)
        elif raw == 'done' and loop_stack:
            loop_ends[loop_stack.pop()] = end
    loop_starts = {start for raw, _, start, _ in control_words if raw == 'for'}
    loop_headers = []

    list_tokens = list(shell_without_redirections(tokens))

    def conditional_before(position):
        stack = []
        for raw, _, start, _ in sorted(control_words, key=lambda word: word[2]):
            if start >= position:
                break
            if raw in {'if', 'while', 'until', 'case', 'for', 'select'}:
                stack.append(raw)
            elif stack and raw == {'if': 'fi', 'case': 'esac'}.get(stack[-1], 'done'):
                stack.pop()
        if any(kind in {'if', 'while', 'until', 'case'} for kind in stack):
            return True
        before = []
        for token in list_tokens:
            if token[2] >= position:
                break
            if token[0] == '\n' and before and before[-1][0] in {'&', '|'}:
                continue
            before.append(token)
        boundary = max((index for index, token in enumerate(before) if token[0] in {';', '\n'}), default=-1)
        return (any(token[0] == '|' for token in before[boundary + 1:])
                or any(left[0] == right[0] == '&' and left[3] == right[2]
                       for left, right in zip(before[boundary + 1:], before[boundary + 2:])))

    def parallel_after(position):
        following = next((token for token in list_tokens if token[2] >= position), None)
        return following is not None and following[0] in {'|', '&'}

    for loop in re.finditer(r'\bfor\s*\(\(([^;]*);', text):
        if loop.start() not in loop_starts:
            continue
        opening = next((index for index, token in enumerate(tokens)
                        if token[0] == '(' and loop.start() < token[2] < loop.start(1)), None)
        if opening not in groups:
            continue
        header_end = tokens[groups[opening]][3]
        loop_headers.append((loop.start(1), header_end))
        scope_end = loop_ends.get(loop.start(), header_end)
        terms = loop[1].split(',')
        if all(re.fullmatch(rf'\s*{identifier}\s*=\s*[0-9]+\s*', term) for term in terms):
            for term in re.finditer(rf'({identifier})\s*=', loop[1]):
                numeric_scopes.setdefault(term[1], []).append((loop.start(1), scope_end))
                before = text[:loop.start(1) + term.start()]
                if (scope_end > header_end and not conditional_before(loop.start())
                        and not parallel_after(scope_end)
                        and not re.search(r'\b(?:for|select|function)\b|[({]', text[:loop.start()])
                        and not re.search(rf'(?<![A-Za-z0-9_]){term[1]}(?![A-Za-z0-9_])', before)):
                    numeric.add(term[1])
    for start, end in regions:
        match = re.match(rf'\s*({identifier})\s*=\s*[0-9]+(?=\s*(?:[,;)]|$))', text[start:end])
        if match:
            position = start + match.start(1)
            before = text[:position]
            region_close = max((tokens[closing][3] for opening, closing in groups.items()
                                if tokens[opening][2] < start < tokens[closing][3]), default=end)
            if (conditional_before(position) or parallel_after(region_close)
                    or any(left <= position < right for left, right in loop_headers)):
                continue
            if not re.search(rf'(?<![A-Za-z0-9_]){match[1]}(?![A-Za-z0-9_])', before):
                if re.search(r'(?:^|[;\n])\s*(?:for\s*)?\(\(\s*$', before):
                    numeric.add(match[1])
    for match in re.finditer(rf'(?<![A-Za-z0-9_])({identifier})=(?:[0-9]+|"?\$\(\([\s\S]*?\)\)"?)(?=\s*(?:[;\n]|$))', text):
        name, start, end = match[1], match.start(), match.end()
        assignments[start] = name
        before = text[:start]
        if (not re.search(rf'(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])', before)
                and re.search(r'(?:^|[;\n])\s*$', before)
                and not conditional_before(start) and not parallel_after(end)
                and not re.search(r'&&|\|\||[|({]|\b(?:if|while|until|case|for|select|function)\b', before)):
            numeric.add(name)
    destination_operands = set()
    for words in commands:
        for index, word in enumerate(words):
            if word[1] not in {'printf', 'read'}:
                continue
            for raw, value, start, _ in words[index + 1:]:
                if not value.startswith('-'):
                    break
                if value == '--':
                    break
                if (word[1] == 'printf' and value.startswith('-v') and len(value) > 2
                        or word[1] == 'read' and re.match(r'-[^adinNptu]*a.+', value)):
                    destination_operands.add(start)
    declaration_operands = {word[2] for words in commands for index, word in enumerate(words)
                            if any(previous[1] in {'declare', 'typeset', 'local', 'export', 'readonly'}
                                   for previous in words[:index])}
    code_operands = {word[2] for words in commands for index, word in enumerate(words)
                     if any(previous[1] in {'eval', 'trap'} for previous in words[:index])}
    command_positions = shell_command_positions(tokens)
    function_definition = shell_defines_function(tokens, command_positions)
    plain_code = {word[2] for words in commands for index, word in enumerate(words)
                  if word[0] == word[1] and word[1] in {'eval', 'trap'}
                  and all(previous[0] in {'then', 'do', 'else', '{', '!', 'if', 'elif'}
                          or re.fullmatch(rf'{identifier}=.*', previous[1], re.S)
                          for previous in words[:index])}
    if (false_closer or function_definition or any(value == 'source' or value == '.' and start in command_positions
                                   or value in {'eval', 'trap'} and start not in plain_code
                                   for _, value, start, _ in tokens)):
        numeric.clear()
        numeric_scopes.clear()
    for words in commands:
        for index, word in enumerate(words):
            if word[2] not in command_positions or word[1] not in {'eval', 'trap'}:
                continue
            numeric_scopes.clear()
            arguments = words[index + 1:]
            if word[1] == 'trap':
                if arguments and arguments[0][1] == '--':
                    arguments = arguments[1:]
                arguments = arguments[:1]
            if any(not (raw.startswith("'") and raw.endswith("'") and "'" not in raw[1:-1])
                   for raw, _, _, _ in arguments):
                numeric.clear()
            else:
                for _, code, _, _ in arguments:
                    code_tokens = shell_raw_words(code)
                    code_positions = shell_command_positions(code_tokens)
                    if (re.search(r'\(\s*\)', code)
                            or shell_defines_function(code_tokens, code_positions)
                            or any(code_value in {'source', 'eval', 'trap', 'function', '.'}
                                   for _, code_value, _, _ in code_tokens)):
                        numeric.clear()
    for name in numeric | numeric_scopes.keys():
        for raw, value, start, end in tokens:
            if assignments.get(start) == name and name in numeric:
                continue
            chars = list(raw)
            for left, right in regions:
                for position in range(max(left, start), min(right, end)):
                    if name in numeric or any(a <= position < b for a, b in numeric_scopes[name]):
                        chars[position - start] = ' '
            remaining = re.sub(rf'\$(?:{name}(?![A-Za-z0-9_])|\{{{name}\}})', '', ''.join(chars))
            name_operand = (value == name or start in code_operands or start in destination_operands
                            or start in declaration_operands and value.startswith((name + '=', name + '+=', name + '[')))
            if name_operand and ''.join(chars).strip():
                remaining = re.sub(rf'\$(?:{name}(?![A-Za-z0-9_])|\{{{name}\}})', '', value)
                if start in destination_operands:
                    remaining = re.sub(r'^-(?:v|[^adinNptu]*a)', '', remaining)
            else:
                remaining = re.sub(r'''(?:'[^']*'|"(?:\\.|[^"\\])*")''', '', remaining)
            if (name in remaining if start in code_operands else
                    re.search(rf'(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])', remaining)):
                numeric.discard(name)
                numeric_scopes.pop(name, None)
                break
    for start, end in regions:
        expression = text[start:end]
        for match in re.finditer(rf'(?<![A-Za-z0-9_#]){identifier}', expression):
            if (match[0] in numeric or any(left <= start + match.start() < right
                    for left, right in numeric_scopes.get(match[0], []))
                    or re.match(r'\s*=(?!=)', text[start + match.end():end])):
                continue
            return reason + 'arithmetic)'
    return None


# Lowercase zsh 5.9 special parameters: `${(ko)parameters[(R)*special*]}` with every module loaded.
ZSH_SPECIAL_PARAMETERS = frozenset((
    '_ aliases argv builtins cdpath commands dirstack dis_aliases dis_builtins dis_functions '
    'dis_functions_source dis_galiases dis_patchars dis_reswords dis_saliases epochtime errnos fignore '
    'fpath funcfiletrace funcsourcetrace funcstack functions functions_source functrace galiases '
    'histchars history historywords jobdirs jobstates jobtexts keymaps langinfo mailpath manpath mapfile '
    'module_path modules nameddirs options parameters patchars path pipestatus prompt psvar reswords '
    'saliases status sysparams termcap terminfo userdirs usergroups watch widgets zcurses_attrs '
    'zcurses_colors zcurses_keycodes zcurses_windows zsh_eval_context zsh_scheduled_events').split())
TEST_SHAPE_COMMANDS = frozenset((
    '[', 'test', 'cd', 'chmod', 'date', 'df', 'cat', 'head', 'tail', 'tr', 'wc', 'read', 'printf', 'echo',
    'exit', 'true', 'false', 'set'))
TEST_SHAPE_PLAIN = re.compile(r'[A-Za-z0-9_./%:+=,@-]+')
TEST_SHAPE_DOLLAR = re.compile(
    r'''\$(?:[?#]|[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*(?:(?:%%?|##?)[^$`(){}'"\\]*)?\})''')
TEST_SHAPE_PATH = re.compile(r'/[A-Za-z0-9_./@%+,-]*')
TEST_SHAPE_ASSIGNMENT = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=')
TEST_SHAPE_SET = re.compile(r'[-+][euxo]+|pipefail|errexit|nounset|xtrace')
TEST_SHAPE_NAME_DENIED = re.compile(r'functions|aliases|builtins|reswords|commands|options|parameters|bash_|env', re.I)
TEST_SHAPE_REDEFINE = re.compile(r'alias|function|disable|enable|hash|builtin', re.I)
TEST_SHAPE_OPERATORS = frozenset({';', '&', '|', '(', ')', '`', '\n', '<', '>'})


def test_shape_name(name):
    return bool(re.fullmatch(r'[a-z_][a-z0-9_]*', name) and name not in ZSH_SPECIAL_PARAMETERS
                and not TEST_SHAPE_NAME_DENIED.search(name))


def test_shape_word(raw, group=False):
    """True when a raw word is plain text, quotes and allowed `$` forms; `group` lets a final `$` open `$(`."""
    index = 0
    while index < len(raw):
        match = TEST_SHAPE_PLAIN.match(raw, index)
        if match:
            index = match.end()
        elif raw[index] == "'":
            index = raw.find("'", index + 1) + 1
            if not index:
                return False
        elif raw[index] == '"':
            index += 1
            while index < len(raw) and raw[index] != '"':
                if raw[index] in '\\`':
                    return False
                if raw[index] != '$':
                    index += 1
                    continue
                match = TEST_SHAPE_DOLLAR.match(raw, index)
                if match:
                    index = match.end()
                    continue
                if not raw.startswith('$(', index) or raw.startswith('$((', index):
                    return False
                depth, index = 0, index + 1
                while index < len(raw) and raw[index] != '"':
                    depth += (raw[index] == '(') - (raw[index] == ')')
                    index += 1
                    if not depth:
                        break
                if depth:
                    return False
            if index >= len(raw):
                return False
            index += 1
        elif raw[index] == '$':
            match = TEST_SHAPE_DOLLAR.match(raw, index)
            if match:
                index = match.end()
            elif group and index == len(raw) - 1:
                index += 1
            else:
                return False
        else:
            return False
    return True


def test_operand_shape(tokens, groups):
    """End offset of the longest whole-segment prefix whose `[` and `test` operands count as data."""
    count, boundary = len(tokens), 0

    def touching(index):
        return index + 1 < count and tokens[index][3] == tokens[index + 1][2]

    def word_end(index):
        """Index after the word at `index` and its `$(...)` group; None when the word fails the shape."""
        group = tokens[index][0].endswith('$') and touching(index) and tokens[index + 1][0] == '('
        if not test_shape_word(tokens[index][0], group):
            return None
        if not group:
            return index + 1
        closing = groups.get(index + 1)
        if closing is None or touching(index + 1) and tokens[index + 2][0] == '(':
            return None
        if closing + 1 < count and touching(closing) and tokens[closing + 1][0] not in TEST_SHAPE_OPERATORS:
            return None
        return closing + 1

    def fresh():
        return {'command': None, 'args': [], 'assigned': False, 'position': True,
                'bracket': False, 'closed': False, 'fi': False}

    def complete(segment):
        args = segment['args']
        if segment['bracket'] and not segment['closed']:
            return False
        if segment['command'] == 'printf':
            return not args or args[0].lstrip('"\'')[:1] not in {'-', '$'}
        if segment['command'] == 'read':
            return all(word == '-r' or test_shape_name(word) for word in args)
        if segment['command'] == 'set':
            return all(TEST_SHAPE_SET.fullmatch(word) for word in args)
        return True

    segment, index, descriptor = fresh(), 0, False
    while index < count:
        raw = tokens[index][0]
        if raw in {';', '\n', '|', '&'}:
            separator = tokens[index][2]
            if raw == '&' or raw == '|' and touching(index) and tokens[index + 1][0] in {'|', '&'}:
                if not (touching(index) and tokens[index + 1][0] == raw):
                    return boundary
                index += 1
            if not complete(segment):
                return boundary
            boundary = separator
            segment, index = fresh(), index + 1
        elif raw in {'(', ')', '`'}:
            return boundary
        elif raw in {'<', '>'}:
            end = index + 1 + (raw == '>' and touching(index) and tokens[index + 1][0] == '>')
            follows = end < count and touching(end - 1)
            if descriptor and end == index + 1 and follows and tokens[end][0] == '&':
                if not (end + 1 < count and touching(end) and tokens[end + 1][0] == '1'):
                    return boundary
                index, descriptor = end + 2, False
                continue
            if end >= count or tokens[end][0] in TEST_SHAPE_OPERATORS:
                return boundary
            descriptor = False
            index = word_end(end)
            if index is None:
                return boundary
        elif raw == '2' and touching(index) and tokens[index + 1][0] == '>':
            descriptor, index = True, index + 1
        elif segment['fi'] or segment['closed']:
            return boundary
        elif segment['position']:
            assignment = TEST_SHAPE_ASSIGNMENT.match(raw)
            if not segment['assigned'] and raw in {'if', 'then', 'elif', 'else', '!'}:
                index += 1
            elif not segment['assigned'] and raw == 'fi':
                segment['fi'], segment['position'] = True, False
                index += 1
            elif assignment:
                if not test_shape_name(assignment.group(1)):
                    return boundary
                index = word_end(index)
                if index is None:
                    return boundary
                segment['assigned'] = True
            elif segment['assigned'] or raw not in TEST_SHAPE_COMMANDS and not TEST_SHAPE_PATH.fullmatch(raw):
                return boundary
            else:
                segment['command'], segment['position'] = raw, False
                segment['bracket'] = raw == '['
                index += 1
        elif raw == ']' and segment['bracket']:
            segment['closed'] = True
            index += 1
        else:
            segment['args'].append(raw)
            index = word_end(index)
            if index is None:
                return boundary
    return tokens[-1][3] if tokens and complete(segment) else boundary


UNPROVEN_DIRECTORY_LABEL = ('inline interpreter code rule (program from a pipe)'
                            ': relative script after an unproven directory change')


def shell_changes_paths(tokens):
    if not tokens:
        return False
    name = tokens[0][0]
    if name in {'cd', 'pushd'}:
        return (len(tokens) != 2 or unresolved_shell_word(tokens[1][0])
                or not re.fullmatch(r'[\w./-]+', tokens[1][1]))
    if name == 'set':
        return any(unresolved_shell_word(token[0]) or not re.fullmatch(r'[-+\w]+', token[0])
                   for token in tokens[1:])
    if name in {'echo', 'printf', 'cat', 'head', 'tail', 'wc', 'grep'}:
        return any(token[0] in {'<', '>'} for token in tokens)
    return name != 'true' or len(tokens) != 1


def inline_interpreter_denial(command, cwd=None):
    env_directories = []
    chdir_wrapper = chdir_wrapper_present(command, env_directories)
    safe_directory = not chdir_wrapper and safe_directory_state(command, cwd)
    bases = [os.path.realpath(cwd or os.getcwd())]
    if safe_directory:
        bases.append(safe_directory)
    bases.extend(os.path.realpath(target) for target in env_directories)
    safe_base = all(base not in {'/proc', '/dev'} and not base.startswith(('/proc/', '/dev/'))
                    for base in bases)
    shell = literal_variables(shell_without_heredoc_bodies(command))
    lines = command.splitlines(keepends=True)
    if lines and ANY_PYTHON_HEREDOC.fullmatch(lines[0]) and not process_heredoc_denial(command):
        shell = shell[len(lines[0]):]
    pending = [(shell, (False, False, False), False)]
    seen = set()
    subscript_reason = None
    runtime_reason = None
    path_reason = None
    substitutions = []
    while pending or substitutions:
        if not pending:
            if subscript_reason:
                return subscript_reason
            pending, substitutions = substitutions, []
        text, inherited, inherited_paths = pending.pop()
        top_level = not seen
        text = shell_line_continuations(text)
        identity = (text, inherited, inherited_paths)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            tokens = shell_raw_words(text)
        except ValueError as error:
            return 'unparsed shell syntax rule: ' + str(error)
        if nested_work_exceeded(tokens, seen):
            return 'inline interpreter code rule (nesting limit)'
        nested = list(nested_shell_strings(tokens))
        bodies = list(shell_substitution_bodies(text))
        shell_nested = list(nested_shell_strings(tokens, include_env=False))
        nested_paths = bool(shell_nested or bodies
                            or any(token[0] == '`' or token[1] in {'eval', 'trap', 'coproc'}
                            or (token[0] == '(' and index > 0 and tokens[index - 1][0] in {'<', '>'}
                                and tokens[index - 1][3] == token[2]) for index, token in enumerate(tokens)))
        input_tokens = shell_raw_words(shell_line_continuations(shell))
        state = shell_input_state(tokens, text, shell_input_state(input_tokens, shell_line_continuations(shell), inherited))
        piped_input, directory, redirected = state
        if re.search(r'(?:\$\([^\n]*\)|`[^`\n]*`)[ \t]+(?:-[ceEpr]\b|--(?:eval|print)\b|-[a-zA-Z]*[ce]\b)', text):
            return 'inline interpreter code rule (unresolved command word)'
        arithmetic, stack = set(), []
        for index, (raw, value, start, end) in enumerate(tokens):
            if raw == '(':
                adjacent = (index + 1 < len(tokens) and tokens[index + 1][0] == '('
                            and end == tokens[index + 1][2])
                substitution = (index > 0 and tokens[index - 1][0].endswith('$')
                                and tokens[index - 1][3] == start)
                stack.append(adjacent or bool(stack and stack[-1] and not substitution))
            elif raw == ')':
                if stack:
                    stack.pop()
            elif stack and stack[-1]:
                arithmetic.add(start)
        try:
            groups, openings, backtick = {}, [], None
            for index, token in enumerate(tokens):
                if token[0] == '`':
                    if backtick is None:
                        backtick = index
                    else:
                        groups[backtick] = index
                        backtick = None
                elif token[0] == '(':
                    openings.append(index)
                elif token[0] == ')' and openings:
                    groups[openings.pop()] = index
            commands, ranges = [], [(0, len(tokens))]
            while ranges:
                cursor, end = ranges.pop()
                command_words = []
                while cursor < end:
                    token = tokens[cursor]
                    raw = token[0]
                    substitution = (cursor + 1 < end and tokens[cursor + 1][0] == '('
                                    and token[3] == tokens[cursor + 1][2]
                                    and (raw.endswith('$') or raw in {'<', '>'}))
                    opening = cursor + 1 if substitution else cursor if raw == '`' else None
                    if opening is not None:
                        closing = groups[opening]
                        ranges.append((opening + 1, closing))
                        if substitution and raw.endswith('$') and raw != '$':
                            command_words.append(token)
                        cursor = closing + 1
                        continue
                    redirect = raw in {'<', '>'} or (raw == '&' and cursor + 1 < end
                                and tokens[cursor + 1][0] == '>' and token[3] == tokens[cursor + 1][2])
                    if redirect:
                        if (command_words and command_words[-1][3] == token[2]
                                and re.fullmatch(r'\d+|\{[A-Za-z_][A-Za-z0-9_]*}', command_words[-1][0])):
                            command_words.pop()
                        cursor += 1
                        while (cursor < end and tokens[cursor][0] in {'<', '>', '&', '|'}
                               and tokens[cursor - 1][3] == tokens[cursor][2]):
                            cursor += 1
                        target_group = (cursor < end and (tokens[cursor][0] == '`' or
                            cursor + 1 < end and tokens[cursor + 1][0] == '('
                            and tokens[cursor][3] == tokens[cursor + 1][2]
                            and (tokens[cursor][0].endswith('$') or tokens[cursor][0] in {'<', '>'})))
                        if (cursor < end and not target_group
                                and tokens[cursor][0] not in {';', '|', '&', '(', ')', '`', '\n'}):
                            cursor += 1
                        continue
                    if raw in {';', '|', '&', '(', ')', '`', '\n'}:
                        commands.append(command_words)
                        command_words = []
                    else:
                        command_words.append(token)
                    cursor += 1
                commands.append(command_words)
            for command_words in commands:
                if subscript_reason is None:
                    subscript_reason = array_subscript_denial(command_words, arithmetic, tokens, groups, names_only=True)
            if runtime_reason is None:
                runtime_reason = runtime_name_denial(text, tokens, arithmetic, groups, commands)
        except Exception:
            if subscript_reason is None:
                subscript_reason = 'array subscript evaluation rule (parse error)'
        command_positions = shell_command_positions(tokens)
        limit = (test_operand_shape(tokens, groups)
                 if top_level and not TEST_SHAPE_REDEFINE.search(command) else 0)
        segments, words, piped, pipe_groups = [], [], False, []
        runtime_paths = inherited_paths or nested_paths or shell_defines_function(tokens, command_positions) or any(
            token[1] in {'while', 'until', 'for', 'select'} and token[2] in command_positions for token in tokens)
        for index, token in enumerate(tokens):
            raw = token[0]
            if raw == '{' and token[2] in command_positions:
                pipe_groups.append(piped or any(pipe_groups))
            elif raw == '}' and token[2] in command_positions and pipe_groups:
                pipe_groups.pop()
            previous = tokens[index - 1] if index else None
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            before = previous is not None and previous[3] == token[2]
            after = following is not None and token[3] == following[2]
            if raw == '&':
                if before and previous[0] == '|':
                    continue
                if before and previous[0] in {'<', '>'} or after and following[0] == '>':
                    words.append(token)
                    continue
                if not (before and previous[0] == '&' or after and following[0] == '&'):
                    runtime_paths = True
            if raw in {';', '&', '|', '(', ')', '`', '\n'}:
                if words:
                    segments.append((words, piped or any(pipe_groups)))
                    words = []
                if raw == '(':
                    pipe_groups.append(piped or any(pipe_groups))
                elif raw == ')' and pipe_groups:
                    pipe_groups.pop()
                if raw != '\n':
                    piped = (raw == '|' and not (before and previous[0] == '|')
                             and not (after and following[0] == '|')
                             or raw == '(' and token[2] > 0 and text[token[2] - 1] == '>')
            else:
                words.append(token)
        segments.append((words, piped or any(pipe_groups)))
        changing_segments = [shell_changes_paths(words) for words, _ in segments]
        segments = [(words, piped, runtime_paths or any(changing_segments[:index])
                     or any(changing_segments[index + 1:])) for index, (words, piped) in enumerate(segments)]
        shell_programs = set()
        for index, token in enumerate(tokens):
            if os.path.basename(token[1]) not in SHELL_INTERPRETERS:
                continue
            cursor = index + 1
            while cursor < len(tokens):
                option = tokens[cursor][1]
                if option in {'-o', '+o', '-O', '+O'}:
                    cursor += 2
                    continue
                if re.fullmatch(r'-[a-zA-Z]*c[a-zA-Z]*', option):
                    if cursor + 1 < len(tokens):
                        shell_programs.add(tokens[cursor + 1][2])
                    break
                if option.startswith('-') and option != '--':
                    cursor += 1
                    continue
                break
        for words, piped, paths_changed in segments:
            if subscript_reason is None:
                try:
                    subscript_reason = (array_subscript_denial(words, arithmetic, tokens, groups)
                                        or array_subscript_denial(words, arithmetic, tokens, groups, names_only=True))
                except Exception:
                    subscript_reason = 'array subscript evaluation rule (parse error)'
            reads_pipe = inherited[0] or piped or any(word[0] == '<' for word in words)
            unproven_directory = chdir_wrapper or directory and not safe_directory
            segment_relative_denied = redirected or not safe_base or unproven_directory or reads_pipe
            directory_only = unproven_directory and safe_base and not reads_pipe
            prefix_end = next((index for index, word in enumerate(words)
                               if not re.match(r'[A-Za-z_][A-Za-z0-9_]*=', word[1])), len(words))
            first = words[prefix_end] if prefix_end < len(words) else None
            neutral_prefix = prefix_end > 0 and not any(
                interpreter_name(word[1]) or os.path.basename(word[1]) in STRING_WRAPPERS for word in words)
            path_part = r'(?:\$(?:PATH|\{PATH\})|\$(?:HOME|\{HOME\})(?:/[\w./@%+,-]*)?|/[\w./@%+,-]*)'
            if (piped_input and first and first[0] != '[' and first[1] != '$?'
                    and unresolved_shell_word(first[0])):
                return 'inline interpreter code rule (unresolved command word)'
            test_operands, test_commands, closing = set(), set(), None
            if words and words[-1][3] <= limit:
                reserved_prefix = True
                for _, value, start, _ in words:
                    if closing is not None:
                        if closing and value == closing:
                            closing = None
                        else:
                            test_operands.add(start)
                    elif (reserved_prefix and start in command_positions
                          and not any(tokens[left][2] < start < tokens[right][2]
                                      for left, right in groups.items())):
                        closing = {'[': ']', '[[': ']]', 'test': ''}.get(value)
                        if closing is not None:
                            test_commands.add(start)
                    reserved_prefix = reserved_prefix and value in {
                        'if', 'elif', 'while', 'until', 'then', 'do', 'else', '!', '{'}
            for index, (raw, value, start, end) in enumerate(words):
                arguments = [word[1] for word in words[index + 1:]]
                neutral = neutral_prefix and index < prefix_end and bool(re.fullmatch(
                    rf'[A-Za-z_][A-Za-z0-9_]*=("?){path_part}(?::{path_part})*\1', raw))
                unresolved = (not neutral and raw != '[' and value != '$?' and start not in shell_programs
                              and start not in test_commands
                              and unresolved_shell_word(raw))
                names = '|'.join(re.escape(name) for name in (*INLINE_INTERPRETERS, 'python'))
                joined_code = (not neutral and unresolved_shell_word(raw) and bool(re.search(
                    rf'{names}|--(?:eval|print)|(?:^|[^\w])(?:-[ceEpr]|eval|run|repl)(?:$|[^\w])', raw))
                               and not read_only_argument_word(command, tokens, words, index))
                if start not in test_operands and (joined_code or unresolved and (
                        any(code_option(argument) for argument in arguments)
                        or arguments[:1] and arguments[0] in {'eval', 'run', 'repl'})):
                    return 'inline interpreter code rule (unresolved command word)'
                if grep_data_token(words, index):
                    continue
                name = interpreter_name(value)
                if not name:
                    continue
                segment_text = text[words[0][2]:words[-1][3]]
                if redirected or any(word[0] == '<' for word in words) or re.search(r'[<>][ \t]*\(|=\(', text[end:]):
                    return 'inline interpreter code rule (program from a pipe)'
                if not arguments and not piped:
                    if piped_input or any(token[0] in {'<', '|', '('} or token[0] == '{'
                                          for token in input_tokens + tokens):
                        return 'inline interpreter code rule (program from a pipe)'
                    continue
                if name != 'python':
                    short, long, subcommands = INLINE_INTERPRETERS[name]
                    if (name == 'deno' and arguments[:1] and arguments[0] in {'eval', 'repl', 'run'}
                            or any(argument in subcommands or argument.split('=', 1)[0] in long
                                   or argument.startswith('-') and not argument.startswith('--')
                                   and bool(set(argument[1:]) & set(short)) for argument in arguments[:1])):
                        return f'inline interpreter code rule ({name})'
                    if arguments == ['--version']:
                        continue
                    script = arguments[0] if arguments else ''
                    unsafe_script = any(unsafe_script_path(script, base) for base in bases)
                    if (not script or script.startswith('-') or stdin_program_path(script) or unsafe_script
                            or (segment_relative_denied or piped) and not os.path.isabs(script)
                            or not re.fullmatch(r'[\w./:@%+,-]+', words[index + 1][0])):
                        if (script and not script.startswith('-') and not os.path.isabs(script)
                                and directory_only and not unsafe_script and not stdin_program_path(script)
                                and re.fullmatch(r'[\w./:@%+,-]+', words[index + 1][0])):
                            return UNPROVEN_DIRECTORY_LABEL
                        return ('inline interpreter code rule (program from a pipe)' if piped_input or stdin_program_path(script) or unsafe_script
                                or (segment_relative_denied or piped) and script and not os.path.isabs(script)
                                else f'inline interpreter code rule ({name})')
                    if paths_changed and path_reason is None:
                        path_reason = 'inline interpreter code rule (program from a pipe)'
                elif not arguments or any(stdin_program_path(argument) for argument in arguments):
                    return 'inline interpreter code rule (program from a pipe)'
                else:
                    kind, flags, operand, offset = python_program(arguments)
                    if kind == 'script' and operand < len(arguments):
                        script = arguments[operand]
                        unsafe_script = any(unsafe_script_path(script, base) for base in bases)
                        if (segment_relative_denied or piped) and not os.path.isabs(script) or unsafe_script:
                            if not os.path.isabs(script) and directory_only and not unsafe_script:
                                return UNPROVEN_DIRECTORY_LABEL
                            return 'inline interpreter code rule (program from a pipe)'
                    if (piped_input or piped) and (kind not in {'c', 'm', 'script'} or operand >= len(arguments)
                                        or 'i' in flags or any(word[1].startswith('PYTHONINSPECT=') for word in words)):
                        return 'inline interpreter code rule (program from a pipe)'
                    if (paths_changed and kind == 'script' and operand < len(arguments)
                            and path_reason is None):
                        path_reason = 'inline interpreter code rule (program from a pipe)'
        for token in nested:
            preceding_paths = next((changed for words, _, changed in segments
                                    if words and words[0][2] <= token[2] < words[-1][3]), inherited_paths)
            pending.append((token[1], state, True if token in shell_nested else preceding_paths))
        substitutions.extend((body, state, True) for body in bodies)
    return subscript_reason or runtime_reason or path_reason


def git_push(command):
    reduced = literal_variables(literal_ps_awk_filter(python_heredoc_shell(cat_heredoc_data(command))))
    try:
        shlex.split(reduced.replace('\\\n', ''), comments=False, posix=True)
    except ValueError:
        # A reduction that leaves unbalanced quotes misread the shell, so the original command is scanned.
        reduced = command
    return ('heredoc-then-run rule' if runs_heredoc_output(command) else shell_git_push(reduced))


SAFE_VALUE = r'[\w./@%+:,-]+'
ASSIGNMENT = rf'([A-Za-z_]\w*)=(["\']?)({SAFE_VALUE})\2'
# Commands that cannot assign a shell variable, so a literal assignment keeps its value for the whole script.
# Only read-only commands qualify; `tar`, `zip`, `xargs`, `find -exec` and `sed e` can launch other code.
LITERAL_STARTS = {'git', 'ls', 'cat', 'grep', 'rg', 'head', 'tail', 'wc', 'test'}
SET_OPTIONS = r'(?:\s+(?:[-+][euxo]+|pipefail|errexit|nounset|xtrace))*'
# The shell itself sets these (`cd` sets `PWD`), so a literal assignment does not fix their value.
SHELL_SET = re.compile(r'(?:PWD|OLDPWD|DIRSTACK|REPLY|MAPFILE|OPTARG|OPTIND|FUNCNAME|COPROC|MATCH|MBEGIN|MEND'
                       r'|(?:BASH|ZSH|COMP_|READLINE_|HIST)\w*)')


def single_quoted_spans(text):
    """Split shell text into `(span, single_quoted)` pairs, or return None for an unbalanced quote."""
    spans, start, double, index = [], 0, False, 0
    while index < len(text):
        if text[index] == '"':
            double = not double
        elif text[index] == "'" and not double:
            end = text.find("'", index + 1)
            if end < 0:
                return None
            spans += [(text[start:index], False), (text[index:end + 1], True)]
            start = index = end + 1
            continue
        index += 1
    return None if double else spans + [(text[start:], False)]


def literal_variables(command):
    """Replace `$NAME` and `${NAME}` with the value of a leading literal assignment such as `W=/repo/wt;`.

    An unquoted variable word-splits (`W='. push'` turns `git -C $W status` into a push), so its value must be known.
    It is known when the script, or the single-quoted script of a whole-command `bash -c`, starts with
    `NAME=value` statements joined by `;` or `&&`, nothing later mentions NAME except as `$NAME` or `${NAME}`, and no later command can
    assign a variable. Single-quoted text keeps `$NAME`, because a nested shell reads it without the value.
    """
    wrapped = re.fullmatch(r"(\s*(?:\S*/)?(?:ba|z)?sh +-l?c +')([^']*)('\s*)", command)
    head, script, tail = wrapped.groups() if wrapped else ('', command, '')
    if re.search(r'\$[(\'"$]|[`\\#]|[<>]\(|<<|IFS|\b(?:eval|exec|source|alias)\b', script):
        return command
    values, start = {}, 0
    for statement in re.split(r'(?<=[;\n])|(?<=&&)', script):
        body = re.sub(r'(?:;|\n|&&)$', '', statement).strip()
        if body and not re.fullmatch(rf'set{SET_OPTIONS}|(?:export\s+)?{ASSIGNMENT}(?:\s+{ASSIGNMENT})*', body):
            break
        for name, _, value in re.findall(ASSIGNMENT, body):
            values.setdefault(name, set()).add(value)
        start += len(statement)
    # zsh sets many lowercase names itself (`argv`, `dirstack`, `jobtexts`), so only uppercase names qualify.
    names = {name for name, found in values.items() if re.fullmatch(r'[A-Z][A-Z0-9_]*', name)
             and not SHELL_SET.fullmatch(name) and len(found) == 1 and 'push' not in next(iter(found)).lower()}
    rest = script[start:]
    spans = single_quoted_spans(rest)
    if not names or spans is None:
        return command
    # Single-quoted spans are literal here, so only the text outside them names or assigns this shell's variables.
    outside = ''.join("''" if single else span for span, single in spans)
    for name in names:
        for found in re.finditer(rf'(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])', outside):
            before, after = outside[:found.start()], outside[found.end():]
            # zsh reads `$W[1]` and `$W:s/x/y/` as a subscript and a modifier, so only a whole value qualifies.
            if not (before.endswith('$') and not after.startswith(('[', ':'))
                    or before.endswith('${') and after.startswith('}') and not after[1:].startswith(('[', ':'))):
                return command
    checked = re.sub(r'\d*[<>]\|?&?\d*-?', ' ', re.sub(r'\$\{([A-Za-z_]\w*)\}', r'$\1', outside))
    for segment in re.split(r'[;&|\n(){}]+', checked):
        words = re.sub(rf'^\s*(?:{ASSIGNMENT}(?:\s+|$))*', '', segment).split()
        if not words:
            continue
        if os.path.basename(words[0]) not in LITERAL_STARTS:
            return command

    def expand(use):
        name = use[1] or use[2]
        return next(iter(values[name])) if name in names else use[0]

    expanded = ''.join(span if single else re.sub(r'\$(?:([A-Za-z_]\w*)(?!\w)|\{([A-Za-z_]\w*)\})', expand, span)
                       for span, single in spans)
    return head + script[:start] + expanded + tail


# One left-to-right scan: a single-quoted span, a standalone `"$NAME"` word, or another double-quoted span.
SHELL_QUOTES = re.compile(r'''(?<!\$)'[^']*'|(?<![^\s;&|()])"\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})"(?![^\s;&|()])|"[^"]*"''')


def quoted_variable(command, token):
    """Whether `command` references the variable `token` names only as standalone `"$NAME"` words.

    Other quotes must be inert literals, and the command must hold no escape, comment, heredoc, backtick, `${`
    expansion, array assignment, subscript or arithmetic, so shlex
    and the shell split it the same way and no nested shell or `eval` can re-read the quoted value as code.
    """
    # A double-quoted variable cannot word-split, so it can name a folder (`git -C "$W" status`). Any other
    # reference (`$W`, `x"$W"`, `"x $W"`, `${W:-x}`, `'git -C "$W"'`) could split into `. push`, so it refuses.
    match = re.fullmatch(r'\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})', token)
    if not match:
        return False
    name = match.group(1) or match.group(2)
    found = []

    def plain(quoted):
        variable = quoted.group(1) or quoted.group(2)
        if variable:
            found.append(variable)
            return ' '
        # A literal is inert when it holds no expansion and nothing shlex would read as a separator or an
        # assignment once it drops the quotes (`';'`, `'X=1'`).
        text = quoted.group(0)
        unsafe = r'[$`";&|()=]' if text[0] == "'" else r'[$`\\\';&|()=]'
        return '"' if re.search(unsafe, text[1:-1]) else '_'

    rest = SHELL_QUOTES.sub(plain, command)
    # `${E:-:;git ...}` and `a=(git ...)` hold a `;` or `(` that shlex reads as a command start and the shell does not.
    # Arithmetic (`((...))`, `$[...]`, a `a[...]=` subscript) evaluates the quoted value as an expression, and an
    # array subscript there runs commands. Only the standalone `[` and `]` words of a test command stay.
    brackets = re.sub(r'(?<![^\s;&|()])[][](?![^\s;&|()])', ' ', rest)
    # Any `(` other than `$(` can open a word list (`@(...)`, `a=(...)`, zsh `for x (...)`) that keeps separators as
    # text, so only command substitution stays.
    return (name in found and re.search(r'[\\`\'"#[\]\n]|<<|\$\{|\(\(|(?<!\$)\(', brackets) is None
            and re.search(rf'\$(?:{name}\b|\{{{name}\b)', rest) is None)


def git_read_words(words):
    """Whether shell words after `git` are `-C <path>`, then `ls-files`, `ls-tree` or `grep` with only listed options."""
    while words[:1] == ['-C'] and len(words) > 1 and re.fullmatch(r'[\w./-]+', words[1]):
        words = words[2:]
    return bool(words) and words[0] in {'ls-files', 'ls-tree', 'grep'} and all(
        # A word after the subcommand is a pattern or path, whatever it holds, unless it is an option.
        re.fullmatch(r'-[nilwEFvz]+|-[ABC][0-9]*|--|(?!-).*', word, re.S) for word in words[1:])


def literal_search_shell(command):
    """Recognize one literal cd/find/grep/ls chain without granting any process or write option."""
    text = command.removesuffix('\n')
    if not text or '\n' in text:
        return False
    spans = single_quoted_spans(text)
    if spans is None:
        return False
    outside = ''.join('_' if quoted else span for span, quoted in spans)
    if re.search(r'[$`\\"()<>;|!{}#~]', outside):
        return False
    tokens = list(re.finditer(r"'[^']*'|[^\s']+", text))
    segments, current, end = [], [], 0
    for token in tokens:
        if text[end:token.start()].strip() or end and token.start() == end:
            return False
        raw = token[0]
        if raw == '&&':
            if text[token.start() - 1:token.start()] != ' ' or text[token.end():token.end() + 1] != ' ' or not current:
                return False
            segments.append(current)
            current = []
        else:
            if '&' in raw and not raw.startswith("'"):
                return False
            current.append(raw)
        end = token.end()
    if not current:
        return False
    segments.append(current)
    plain = lambda word: re.fullmatch(r'[\w./:@%+,-]+', word) is not None
    path = lambda word: plain(word) and not word.startswith('-')
    value = lambda word: plain(word) or len(word) >= 2 and word[0] == word[-1] == "'"
    for words in segments:
        command, arguments = words[0], words[1:]
        if command == 'cd':
            if len(arguments) != 1 or not path(arguments[0]):
                return False
        elif command == 'find':
            cursor = 0
            while cursor < len(arguments) and path(arguments[cursor]):
                cursor += 1
            if not cursor:
                return False
            while cursor < len(arguments):
                if (arguments[cursor] not in {'-name', '-iname', '-path', '-ipath', '-type', '-maxdepth', '-mindepth'}
                        or cursor + 1 >= len(arguments) or not value(arguments[cursor + 1])):
                    return False
                cursor += 2
        elif command == 'grep':
            cursor = 0
            while cursor < len(arguments) and arguments[cursor].startswith('-'):
                option = arguments[cursor]
                if option in {'-A', '-B', '-C', '-m'}:
                    cursor += 1
                    if cursor == len(arguments) or not arguments[cursor].isdigit():
                        return False
                elif not re.fullmatch(r'-[nEFiwlLcrRHhsvqox]+', option):
                    return False
                cursor += 1
            if (cursor + 1 >= len(arguments) or not value(arguments[cursor])
                    or arguments[cursor].startswith("'-")
                    or not all(path(word) for word in arguments[cursor + 1:])):
                return False
        elif command == 'ls':
            cursor = 0
            while cursor < len(arguments) and arguments[cursor].startswith('-'):
                if not re.fullmatch(r'-[laAhdtrS1R]+', arguments[cursor]):
                    return False
                cursor += 1
            if cursor == len(arguments) or not all(
                    not word.startswith('-') and re.fullmatch(r'[\w./:@%+,*?-]+', word)
                    for word in arguments[cursor:]):
                return False
        else:
            return False
    return True


def shell_git_push(command):
    """Scan Git commands and shell-wrapper strings without regex backtracking."""
    values = {'-C', '-c', '--git-dir', '--work-tree', '--namespace',
              '--config-env', '--super-prefix', '--attr-source', '--shallow-file'}
    folders = {'-C', '--git-dir', '--work-tree'}
    pending = [command]
    seen = set()
    while pending:
        text = pending.pop().replace('\\' + '\n', '')
        if text in seen:
            continue
        seen.add(text)
        try:
            lexer = shlex.shlex(text, posix=True, punctuation_chars='();<>|&`')
            lexer.whitespace_split = True
            lexer.commenters = ''
            tokens = list(lexer)
        except ValueError as error:
            # The text cannot be split, so `git` with a writer word or any expansion or escape denies.
            if re.search(r'\bgit\b', text) and (
                    re.search(r'\b(?:push|send-pack|http-push)\b', text.translate(str.maketrans('', '', '$`*?[]{},')))
                    or re.search(r'[$`\\]', text)):
                return 'unparsed shell syntax rule: ' + str(error)
            continue
        # An expansion or glob can assemble the executable (`$'git' $'push'`), so with any
        # `push` spelling it denies. Exclude only the literal receipt keys `pushed:` and `pushes:` before
        # normalization; brace lists must retain the conservative substring check.
        # A rare false denial remains, for example `echo $X; git stash push`.
        # Plain `$NAME` expansions under the default IFS cannot slice or split a word, so only a whole `push`
        # word can become the subcommand; `$S/prepush-results.txt` is a path.
        plain = ('IFS' not in text
                 and not re.search(r'[`*?[{\\]|\$', re.sub(r'\$(?:[A-Za-z_]\w*|\{[A-Za-z_]\w*\})', '', text)))
        expansion = str.maketrans('', '', '$`*?[]{},')
        # Delete each expansion and quote first, so `"$G"push` reads `push` while `$S/prepush` does not.
        words = re.sub(r'["\']', '', re.sub(r'\$(?:[A-Za-z_]\w*|\{[A-Za-z_]\w*\})', '', text))
        # Many builtins assign a variable from their arguments (`printf -v`, zsh `print -v`), so the relaxation
        # holds only when every command starts with a command that cannot assign one.
        read_only_starts = all(part.split()[0] in READ_ONLY_STARTS
                               for part in re.split(r'[;&|\n]+', words) if part.strip())
        plain = plain and read_only_starts
        # Single quotes keep a glob literal, so a quoted pathspec (`git ls-files '*pre-push*'`) is file text when
        # every command is a plain read. Every quoted word must be a pathspec or plain text, and no newline, process
        # substitution, redirect, other quote, glob or expansion may remain. Commands are checked on the shell's own
        # words, so a quoted word never reads as a command or subcommand plus options. Git may take only `-C`, then
        # `ls-files`, `ls-tree` or `grep` with listed options, so no argument picks a pager or helper; configured
        # helpers apply to the same reads without a glob, so this exception adds none.
        unquoted = re.sub(r"(?<![^\s;&|])'(?:(?!-)[\w./:!*?@%+,^~-]*|(?![- ])[\w ./:@%+,^~-]*)'(?![^\s;&|])", '_', text)
        segments, current = [], []
        for token in tokens:
            if token and set(token) <= set(';&|'):
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)
        literal_globs = (read_only_starts and '\n' not in text and not re.search(r'[*?[\]{}$`\\()<>\'"]', unquoted)
                         and all(not segment or segment[0] in READ_ONLY_STARTS and (
                             segment[0] != 'git' or git_read_words(segment[1:])) for segment in segments))
        if plain:
            spelled = re.search(r'(?<![A-Za-z0-9_])(?:push|send-pack)(?![A-Za-z0-9_])',
                                re.sub(r'(?<!\w)push(?:ed|es)(?=\s*:)', '', words))
        else:
            spelled = any(word in re.sub(r'(?<!\w)push(?:ed|es)(?=\s*:)', '', token).translate(expansion)
                          for token in tokens for word in ('push', 'send-pack'))
        literal_search = literal_search_shell(text)
        if not (literal_globs or literal_search) and any(set(token) & set('$`*?[{') for token in tokens) and spelled:
            return 'git writer expansion or glob rule'
        expect_subcommand = skip_value = folder_value = False
        # Only a `git` that starts a command reads its own arguments; `eval git -C "$W"` or `watch git ...`
        # re-reads them, where a quoted value can split again.
        command_start = git_command = True
        wrapper, wrapper_value, value_option = None, False, None
        for token in tokens:
            # A wrapper (`env`, `nohup`, `xargs`, `sudo`) runs its first non-option argument as the command word.
            command_word = command_start
            if set(token) & set(';&|()'):
                wrapper = None
            elif wrapper and not command_start:
                if wrapper_value:
                    wrapper_value = False
                elif token.startswith('-'):
                    wrapper_value = token in WRAPPERS[wrapper]
                elif not (re.match(r'[A-Za-z_]\w*=', token)
                          or wrapper == 'timeout' and re.fullmatch(r'[\d.]+[smhd]?', token)):
                    command_word, wrapper = True, None
            if any(char.isspace() for char in token):
                pending.append(token)
                if re.match(r'[A-Za-z_]\w*=', token):
                    pending.append(token.split('=', 1)[1])
            # A separator ends the `git` command, so a later command's `-C "$X"` is never read as git's folder.
            # shlex glues `);` into one token, and a newline gives none, so the remainder check refuses newlines.
            if set(token) & set(';&|()'):
                git_command = False
            if folder_value and git_command and quoted_variable(command, token):
                skip_value = folder_value = False
                value_option = None
                continue
            # An expansion, glob, quoting form, or redirection before the subcommand can hide it,
            # so it denies. Writers write `git -C . status 2>&1`, never `git $'push'` or `git {push,}`.
            if expect_subcommand and set(token) & set('(`<>${*?['):
                return 'git hidden subcommand rule'
            # An alias that runs a shell command (`!sh`) or a remote writer turns any subcommand into a push.
            if expect_subcommand and (
                    value_option == '-c' and alias_runs_writer(token)
                    or token.startswith('-c') and token != '-c' and alias_runs_writer(token[2:])
                    or value_option == '--config-env' and token.lower().startswith('alias.')
                    or token.lower().startswith('--config-env=alias.')):
                return 'git configured alias writer rule'
            if skip_value:
                skip_value = folder_value = False
                value_option = None
                continue
            if expect_subcommand:
                if token in values:
                    skip_value = True
                    folder_value = token in folders
                    value_option = token
                    continue
                if token in REMOTE_WRITERS:
                    return f'git remote writer rule ({token})'
                # Options and other non-word tokens stay pending; a plain word is the subcommand.
                if re.fullmatch(r'[a-z][a-z0-9-]*', token):
                    expect_subcommand = False
            # `git-push` runs a push. A glob or an expansion in the command word (`git-pu*`, `$G-push`) can match it;
            # in an argument it is only a file name (`ls g*`).
            base = os.path.basename(re.sub(r'\$(?:[A-Za-z_]\w*|\{[^}]*\})', '*', token))
            if base in REMOTE_WRITER_NAMES or command_word and set(base) & set('*?[') and base.strip('*?') and any(
                    fnmatch.fnmatchcase(name, base) for name in REMOTE_WRITER_NAMES):
                return 'git remote writer executable rule'
            if command_word and base in WRAPPERS:
                wrapper, wrapper_value = base, False
            # Git reads `GIT_CONFIG_*` from the environment, so a value that spells a remote writer can alias one,
            # and a key or parameter list that defines an alias can, whatever the value.
            if re.match(r'GIT_\w*=', token) and any(word in token for word in REMOTE_WRITERS):
                return 'git writer environment rule'
            if (re.match(r'GIT_CONFIG_(?:KEY_\w*|PARAMETERS)=', token)
                    and (re.search(r'alias', token, re.I) or set(token) & set('$`\\'))):
                return 'git alias environment rule'
            if os.path.basename(token) == 'git':
                expect_subcommand = True
                git_command = command_start
            command_start = (not token.strip(';&|(') or command_start and re.match(r'[A-Za-z_]\w*=', token) is not None)
    return False


def role(data, name):
    return re.match(rf'^(ship:)?{name}--', data.get('agent_type') or '') is not None


def git_commit_step(command):
    """Whether the whole shell text after the first heredoc is one line of plain `git add` and `git commit` steps."""
    lines = command.splitlines(keepends=True)
    # Only a whole known header counts; a quoted delimiter keeps backslash-newline literal, so a physical line ends the body.
    match = re.fullmatch(rf"(?:cd(?: --)? [\w./-]+ && )?(?:/usr/bin/)?{PYTHON_NAME}(?: -[IB]+)* - "
                         r"<<(-?)(['\"])([_a-zA-Z0-9]+)\2[ \t]*\n?", lines[0]) if lines else None
    if not match:
        return False
    for end in range(1, len(lines)):
        line = lines[end].removesuffix('\n')
        if (line.lstrip('\t') if match[1] else line) == match[3]:
            tail = ''.join(lines[end + 1:]).strip()
            # Single-quoted text is inert, so only the shell outside it must be plain words joined by `&&`.
            bare = re.sub(r"'[^']*'", "''", tail)
            steps = bare.split('&&')
            return ('\n' not in tail and not re.search(r"""[;|&()<>$`\\"'#=]""", ''.join(steps).replace("''", ''))
                    and all(re.fullmatch(r'\s*git\s+(add|commit)(\s+\S+)*\s*', step) for step in steps))
    return False


def deny(reason):
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))
    sys.exit(0)


def load_ledger():
    path = Path(__file__).resolve().parents[1] / 'skills/ship/scripts/ledger.py'
    spec = importlib.util.spec_from_file_location('ledger', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ponytail: this text guard misses credential-backed writes via env clearing, direct ssh, token HTTP, existing gh aliases and extensions, Bash writes to gh configuration, command words built from variables or bracket globs, bare repository configuration via `-C`, writer-created file names, and files written then run; upgrade to an isolated read-only credential.
COMMIT_MESSAGE = re.compile(r"""((?:^|\s)(?:-[A-Za-z]*m|--message)(?:\s+|=))(?:'[^']*'|"[^$`\\"]*")+(?=\s|$)""")


def commit_message_removed(command):
    """Blank each quoted -m/--message value of a plain `git add`/`git commit` chain; return other commands unchanged."""
    bare = COMMIT_MESSAGE.sub(r"\1''", command)
    words = re.sub(r"'[^']*'|" r'"[^$`\\"]*"', "''", command)
    steps = words.split('&&')
    if re.fullmatch(r'\s*cd\s+\S+\s*', steps[0]):
        steps = steps[1:]
    if (not steps or re.search(r"""[\n;|&()<>$`\\"'#]""", words.replace('&&', '').replace("''", ''))
            or re.search(r'\s(?:-[A-Za-z]*[ect]|--[ert])', words)
            or not all(re.fullmatch(r'\s*git\s+(?:-C\s+\S+\s+)?(?:add|commit)(?:\s+\S+)*\s*', step)
                       for step in steps)):
        return command
    return bare


# Exact pairs preserve the existing admitted config and environment cases.
WRITER_VALUE_ALLOWLIST = {
    ('push.default', 'current'), ('core.pager', 'cat'), ('alias.lg', 'log'),
    ('color.ui', 'never'), ('core.fsmonitor', 'false'),
    ('remote.origin.url', 'https://github.com/o/gh-tools.git'),
    ('GIT_OPTIONAL_LOCKS', '0'), ('GIT_CONFIG_COUNT', '1'),
    ('GIT_CONFIG_KEY_0', 'core.pager'), ('GIT_CONFIG_VALUE_0', 'cat'),
}


def writer_git_control_path(path):
    """Whether a literal or resolved path reaches Git state or external configuration."""
    path = os.path.expanduser(path)
    for candidate in (os.path.abspath(path), os.path.realpath(path)):
        if re.search(r'/(?:\.git(?:/|$)|\.gitconfig(?:/|$)|\.config/git(?:/|$)|[^/]+\.git/(?:config(?:/|$)|hooks(?:/|$)))',
                     candidate, re.I):
            return True
    return False


WRITER_GIT_PATH_COMMAND_ALLOWLIST = set()


def writer_git_component_pattern(component):
    """Match brace alternatives without constructing expanded command words."""
    pattern, depth = '', 0
    for char in component:
        if char == '{':
            pattern += '(?:'
            depth += 1
        elif char == '}' and depth:
            pattern += ')'
            depth -= 1
        elif char == ',' and depth:
            pattern += '|'
        else:
            pattern += re.escape(char)
    return not depth and re.fullmatch(pattern, '.git') is not None


def writer_git_file_denial(command, cwd=None):
    """Refuse Git path pieces independently of the program that receives them."""
    if command in WRITER_GIT_PATH_COMMAND_ALLOWLIST:
        return None
    words = shell_raw_words(shell_without_heredoc_bodies(commit_message_removed(command)))
    for raw, value, _, _ in words:
        active = shell_brace_text(raw)
        if any('/' in piece.partition('{')[2] for piece in active.split('}')[:-1]):
            return 'git control path brace slash rule'
        for part in value.split('='):
            part = re.sub(r'^-[a-z]+', '', part, flags=re.I)
            if re.search(r'(?<![a-z0-9_-])\.git(?![a-z0-9_-])', part, re.I):
                return 'git control path component rule'
            for piece in re.split(r'''[\s,'"]+''', part):
                if piece and writer_git_control_path(os.path.join(cwd or os.getcwd(), os.path.expanduser(piece))):
                    return 'git control path resolved rule'
            for component in part.casefold().split('/'):
                if active and component.startswith('.') and fnmatch.fnmatchcase('.git', component):
                    return 'git control path glob rule'
                if '{' in active and ',' in active and writer_git_component_pattern(component):
                    return 'git control path brace rule'
    return None


def writer_git_config_read(words):
    """Admit only config read modes, location selectors and their literal operands."""
    modes = {'--get', '--get-all', '--get-regexp', '--get-urlmatch', '--list', '-l',
             '--get-color', '--get-colorbool', '--show-origin', '--show-scope', '--name-only', '-z', '--null',
             '--includes', '--no-includes', '--global', '--local', '--system', '--worktree'}
    values = {'--file', '-f', '--blob', '--type', '--default'}
    operands, read_mode, skip = [], False, False
    for word in words:
        if skip:
            skip = False
            continue
        if word in values:
            skip = True
        elif word in modes:
            read_mode = read_mode or word.startswith('--get') or word in {'--list', '-l'}
        elif word.startswith('-'):
            if not any(word.startswith(option + '=') for option in values):
                return False
        else:
            operands.append(word)
    return not skip and (read_mode or len(operands) == 1 or operands[:1] in (['get'], ['list'])) and not any(
        word in {'set', 'unset', 'rename-section', 'remove-section', 'edit'} for word in operands[:1])


def writer_trigger_text(command):
    """Keep shell quote joining and attached quoted operands visible to trigger checks."""
    return re.sub(r'''['"\\]''', '', command) + '\n' + re.sub(r'''['"\\]''', ' ', command)


def writer_repository_selector(option, value):
    return option == '--work-tree' and value == '.'


def writer_gh_denial_main(command, depth=0):
    if depth == 0:
        command = commit_message_removed(command)
    command = cat_heredoc_data(command).replace('\\\n', '')
    unquoted = re.sub(r'''['"\\]''', '', command)
    if not re.search(r'\bgh\b', unquoted):
        return None
    if depth >= 4:
        return 'Writers cannot run deeply nested GitHub commands.'
    reason = 'Writers may run only read-only gh commands.'
    reads = {'pr': ('view', 'list', 'checks', 'diff', 'status'),
             'issue': ('view', 'list', 'status'), 'run': ('view', 'list', 'watch'),
             'repo': ('view',), 'workflow': ('view', 'list')}
    if any(marker in command for marker in ('$(', '<(', '>(', '`')):
        return reason
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|\n()')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        lexer.commenters = ''
        tokens = list(lexer)
    except ValueError as error:
        return 'unparsed shell syntax rule: ' + str(error)
    for token in tokens:
        if any(char.isspace() or char in ';&|()' for char in token):
            nested = writer_gh_denial_main(token, depth + 1)
            if nested:
                return nested
    segments, segment = [], []
    for index, token in enumerate(tokens):
        redirect = (token == '&' and (segment and segment[-1].endswith(('<', '>'))
                    or index + 1 < len(tokens) and tokens[index + 1].startswith('>')))
        if token and all(char in ';&|\n()' for char in token) and not redirect:
            segments.append(segment)
            segment = []
        else:
            segment.append(token)
    segments.append(segment)
    for words in segments:
        if not any(re.search(r'\bgh\b', word) for word in words):
            continue
        if 'api' in words and any(word.strip('/') == 'graphql' for word in words) and any(
                GH_FIELD.fullmatch(word) for word in words):
            return 'writers cannot send GraphQL requests; use a REST GET with the query in the path'
        exempt = False
        for word in words:
            if any(char in word for char in '$`'):
                return reason
            if exempt:
                exempt = False
                continue
            if word in ('-q', '--jq', '-t', '--template', '-H', '--header'):
                exempt = True
                continue
            if any(char in word for char in '*[{'):
                return reason
        for index, word in enumerate(words):
            if os.path.basename(word) != 'gh':
                continue
            if any(os.path.basename(previous) in ('xargs', 'parallel') for previous in words[:index]):
                return reason
            arguments = words[index + 1:]
            cursor = 0
            if arguments in (['--version'], ['--help']):
                continue
            if not arguments or arguments[0].startswith('-'):
                return reason
            group = arguments[cursor]
            if group in ('search', 'version', 'help'):
                continue
            if group != 'api':
                cursor += 1
                if group not in reads or cursor == len(arguments) or arguments[cursor] not in reads[group]:
                    return reason
                continue
            arguments = arguments[cursor:]
            methods, fields, endpoints = [], False, []
            cursor = 1
            while cursor < len(arguments):
                argument = arguments[cursor]
                method = GH_METHOD.fullmatch(argument)
                if method:
                    value = method[1] if argument.startswith('--') else method[2]
                    if value is None or value == '':
                        cursor += 1
                        value = arguments[cursor] if cursor < len(arguments) else ''
                    methods.append(value.removeprefix('=').upper())
                elif GH_FIELD.fullmatch(argument):
                    fields = True
                    if argument in ('-f', '-F', '--field', '--raw-field', '--input'):
                        cursor += 1
                elif argument in ('-H', '--header', '-q', '--jq', '-t', '--template', '--hostname', '--cache',
                                  '-p', '--preview'):
                    cursor += 1
                elif not argument.startswith('-'):
                    endpoints.append(argument.strip('/'))
                cursor += 1
            if fields and 'graphql' in endpoints:
                return 'writers cannot send GraphQL requests; use a REST GET with the query in the path'
            if any(method not in ('GET', 'HEAD') for method in methods) or (
                    fields and (not methods or any(method != 'GET' for method in methods))):
                return 'Writers cannot send mutating GitHub API requests; use a REST GET.'
    return None


def writer_gh_denial(command, depth=0):
    if depth == 0:
        command = commit_message_removed(command)
    command = cat_heredoc_data(command).replace('\\\n', '')
    unquoted = writer_trigger_text(command)
    if not re.search(r'\bgh\b|GIT_|\b(?:EDITOR|VISUAL|PAGER)\b|\bgit\b|ext::|-[iv0]*S|--s', unquoted):
        return None
    if depth >= 4:
        return 'Writers cannot run deeply nested GitHub commands.'
    reason = 'Writers may run only read-only gh commands.'
    if re.search(r'\*\(e:', command):
        return 'zsh executable glob qualifier rule'
    reads = {'pr': ('view', 'list', 'checks', 'diff', 'status'),
             'issue': ('view', 'list', 'status'), 'run': ('view', 'list', 'watch'),
             'repo': ('view',), 'workflow': ('view', 'list')}
    if re.search(r'\bgh\b', unquoted) and any(marker in command for marker in ('$(', '<(', '>(', '`')):
        return reason
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|\n()')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        lexer.commenters = ''
        tokens = list(lexer)
    except ValueError as error:
        return 'unparsed shell syntax rule: ' + str(error)
    quoted_tokens = [False] * len(tokens)
    if re.search(r'\bgh\b', unquoted):
        try:
            raw_tokens = shell_raw_words(command)
        except ValueError:
            return reason
        tokens = [value for _, value, _, _ in raw_tokens]
        quoted_tokens = [bool(re.fullmatch(r"'[^']*'", raw, re.S)) for raw, _, _, _ in raw_tokens]
    segments, segment, quoted_segments, quoted_segment = [], [], [], []
    for index, token in enumerate(tokens):
        redirect = (token == '&' and (segment and segment[-1].endswith(('<', '>'))
                    or index + 1 < len(tokens) and tokens[index + 1].startswith('>')))
        if token and all(char in ';&|\n()' for char in token) and not redirect:
            segments.append(segment)
            quoted_segments.append(quoted_segment)
            segment, quoted_segment = [], []
        else:
            segment.append(token)
            quoted_segment.append(quoted_tokens[index])
    segments.append(segment)
    quoted_segments.append(quoted_segment)
    for words, quoted in zip(segments, quoted_segments):
        # Resolve only known wrappers; a command argument named gh grants no data exemption.
        command_index, wrapper, skip = None, None, False
        for index, word in enumerate(words):
            if skip:
                skip = False
                continue
            if re.match(r'[A-Za-z_]\w*\+?=', word):
                continue
            if wrapper and word.startswith('-'):
                skip = word in WRAPPERS[wrapper]
                continue
            if wrapper == 'timeout' and re.fullmatch(r'[\d.]+[smhd]?', word):
                continue
            base = os.path.basename(word)
            if base in WRAPPERS:
                wrapper = base
                continue
            command_index = index
            break
        if command_index is not None:
            direct_git = re.fullmatch(r'git-([a-z][a-z0-9-]*)', os.path.basename(words[command_index]))
            if direct_git:
                words = words[:command_index] + ['git', direct_git[1]] + words[command_index + 1:]
                quoted = quoted[:command_index] + [False, False] + quoted[command_index + 1:]
        gh_index = (command_index if command_index is not None
                    and os.path.basename(words[command_index]) == 'gh' else None)
        if 'api' in words and any(word.strip('/') == 'graphql' for word in words) and any(
                GH_FIELD.fullmatch(word) for word in words):
            return 'writers cannot send GraphQL requests; use a REST GET with the query in the path'
        data = set()
        if gh_index is not None:
            for index in range(gh_index + 1, len(words)):
                if index in data:
                    continue
                if words[index] in ('-f', '-F', '--field', '--raw-field', '-q', '--jq',
                                    '-t', '--template', '-H', '--header'):
                    data.add(index + 1)
                elif re.match(r'--(?:field|raw-field|jq|template|header)=|-[fFqtH].+', words[index]):
                    data.add(index)
        git_subcommand, git_value = None, None
        env_command = any(os.path.basename(word) == 'env' for word in words)
        for index, word in enumerate(words):
            if index in data and ('-X' in word or '--method' in word):
                return 'gh field method option rule'
            if index in data:
                if '\n' in word:
                    return 'gh multiline data value rule'
                if '$' in word or '`' in word or not quoted[index] and any(char in word for char in '*[{'):
                    return reason
                continue
            if any(char.isspace() or char in ';&|()' for char in word):
                nested = writer_gh_denial(word, depth + 1)
                if nested:
                    return nested
            if re.fullmatch(r'GIT_\w*|EDITOR|VISUAL|PAGER', word):
                return 'git guarded environment name rule'
            assignment = re.match(r'(GIT_\w*|EDITOR|VISUAL|PAGER)(\+?=)(.*)\Z', word, re.S)
            if assignment and (assignment[2] != '=' or (assignment[1], assignment[3]) not in WRITER_VALUE_ALLOWLIST):
                return 'git editor/config environment rule'
            if 'ext::' in word:
                return 'git external transport rule'
            if index != gh_index and any(os.path.basename(part.lstrip('!')) == 'gh'
                                         for part in re.split(r'[=<>]', word)):
                return 'hidden gh word-part rule'
            if git_value:
                if git_value == '-c' and tuple(word.split('=', 1)) not in WRITER_VALUE_ALLOWLIST:
                    return 'git config value rule'
                if git_value in {'--git-dir', '--work-tree'} and not writer_repository_selector(git_value, word):
                    return 'git repository selector rule'
                git_value = None
                continue
            if os.path.basename(word) == 'git':
                git_subcommand = ''
                continue
            if git_subcommand is not None:
                if word.startswith(('--template', '--separate-git-dir')):
                    return 'git template or separate directory rule'
                if git_subcommand == '' and word.startswith(('--git-dir=', '--work-tree=')):
                    option, _, value = word.partition('=')
                    if not writer_repository_selector(option, value):
                        return 'git repository selector rule'
                    continue
                if word.startswith(('--config-env', '--exec-path')):
                    return 'git config/exec path option rule'
                if git_subcommand in ('', 'clone') and (word.startswith('-c') or word == '--config'
                                                          or word.startswith('--config=')):
                    if word in ('-c', '--config'):
                        git_value = '-c'
                    else:
                        setting = word.partition('=')[2] if word.startswith('--') else word[2:]
                        if tuple(setting.split('=', 1)) not in WRITER_VALUE_ALLOWLIST:
                            return 'git config value rule'
                    continue
                if git_subcommand == '' and word == '--git-dir':
                    return 'git repository selector rule'
                if git_subcommand == '' and word in {'-C', '--work-tree', '--namespace',
                                                      '--super-prefix', '--attr-source', '--shallow-file'}:
                    git_value = word
                    continue
                if git_subcommand == '' and not word.startswith('-'):
                    git_subcommand = word
                    if word == 'config' and not writer_git_config_read(words[index + 1:]):
                        return 'git stored config write rule'
                    continue
                # Editor flags are defense in depth beside the config and environment rules.
                if git_subcommand and (
                        word == '--edit' or git_subcommand not in {'grep', 'ls-files', 'clean'}
                        and re.fullmatch(r'-[A-Za-z]*e[A-Za-z]*', word)
                        or word.startswith(('--fixup=amend:', '--fixup=reword:'))):
                    return 'git editor option rule'
            nested_word = word
            if env_command:
                split_option, separator, split_value = word.partition('=')
                split_short = re.match(r'-[iv0]*S(.*)\Z', word, re.S)
                split_long = len(split_option) > 2 and '--split-string'.startswith(split_option)
                if split_short or split_long:
                    split_text = (split_short[1] if split_short else split_value) if split_short or separator else ''
                    if not split_text and index + 1 < len(words):
                        split_text = words[index + 1]
                    if any(char in split_text for char in '\\$#'):
                        return 'env split string escape rule'
            if any(os.path.basename(previous) in SHELL_INTERPRETERS for previous in words[:index]):
                shell_code = re.match(r'-[a-zA-Z]*c(.+)\Z', word, re.S)
                if shell_code:
                    nested_word = shell_code[1]
            if env_command:
                split = re.match(r'-[iv0]*S(.*)\Z', word, re.S)
                option, separator, value = word.partition('=')
                if split:
                    nested_word = split[1]
                elif separator and len(option) > 2 and '--split-string'.startswith(option):
                    nested_word = value
            if nested_word != word or any(char.isspace() or char in ';&|()' for char in nested_word):
                nested = writer_gh_denial(nested_word, depth + 1)
                if nested:
                    return nested
        if not any(re.search(r'\bgh\b', word) for word in words):
            continue
        for index, word in enumerate(words):
            if any(char in word for char in '$`'):
                return reason
            if index not in data and any(char in word for char in '*[{'):
                return reason
        for index, word in enumerate(words):
            if os.path.basename(word) != 'gh':
                continue
            if any(os.path.basename(previous) in ('xargs', 'parallel') for previous in words[:index]):
                return reason
            arguments = words[index + 1:]
            cursor = 0
            if arguments in (['--version'], ['--help']):
                continue
            if not arguments or arguments[0].startswith('-'):
                return reason
            group = arguments[cursor]
            if group in ('search', 'version', 'help'):
                continue
            if group != 'api':
                cursor += 1
                if group not in reads or cursor == len(arguments) or arguments[cursor] not in reads[group]:
                    return reason
                continue
            arguments = arguments[cursor:]
            methods, fields, endpoints = [], False, []
            cursor = 1
            while cursor < len(arguments):
                argument = arguments[cursor]
                method = GH_METHOD.fullmatch(argument)
                if method:
                    value = method[1] if argument.startswith('--') else method[2]
                    if value is None or value == '':
                        cursor += 1
                        value = arguments[cursor] if cursor < len(arguments) else ''
                    methods.append(value.removeprefix('=').upper())
                elif GH_FIELD.fullmatch(argument):
                    fields = True
                    if argument in ('-f', '-F', '--field', '--raw-field', '--input'):
                        cursor += 1
                elif argument in ('-H', '--header', '-q', '--jq', '-t', '--template', '--hostname', '--cache',
                                  '-p', '--preview'):
                    cursor += 1
                elif not argument.startswith('-'):
                    endpoints.append(argument.strip('/'))
                cursor += 1
            if fields and 'graphql' in endpoints:
                return 'writers cannot send GraphQL requests; use a REST GET with the query in the path'
            if any(method not in ('GET', 'HEAD') for method in methods) or (
                    fields and (not methods or any(method != 'GET' for method in methods))):
                return 'Writers cannot send mutating GitHub API requests; use a REST GET.'
    return None


# shortcut: script files run by path, gh aliases and extensions, command words built from variables or globs, opaque non-gh URLs, files written by Write/Edit then run, interpreter scripts such as python3 -c or node -e that run gh, and shell runners that build gh from escapes or expansions escape this scan; upgrade to a GitHub token the driver cannot use for review-thread writes.
def review_thread_denial(command):
    if read_only_shell(command) or literal_search_shell(command):
        return None
    if '$' not in command and re.fullmatch(
            r"git commit(?: +-[A-Za-z]+| +--[a-z-]+)*(?: +-m +'[^']*'(?: +-[A-Za-z]+| +--[a-z-]+)*)+ *", command):
        return None
    command = command.replace('\\\n', '')
    normalized = re.sub(r'''['"\\]''', '', command).casefold()
    if re.search(r'\bgh\b', normalized) and '`' in outside_single_quotes(command):
        return 'review-thread guard parse failure'
    if (any(name in normalized for name in ('addpullrequestreviewthreadreply', 'addpullrequestreviewcomment',
                                            'resolvereviewthread'))
            or re.search(r'comments/\S*/replies', normalized)):
        return 'raw review-thread mutation'
    command = cat_heredoc_data(command)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|\n()')
        lexer.whitespace = ' \t\r'
        lexer.whitespace_split = True
        lexer.commenters = ''
        tokens = list(lexer)
    except ValueError as error:
        return 'unparsed shell syntax rule: ' + str(error) if re.search(r'\bgh\b', normalized) else None
    names_gh = any(os.path.basename(re.sub(r'^[A-Za-z_]\w*=', '', word).lstrip('!')) == 'gh'
                   for word in re.split(r'[\s;&|()<>`]+', normalized))
    if names_gh:
        seen_gh = False
        for index, token in enumerate(tokens):
            if token and all(char in ';&|\n()' for char in token):
                seen_gh = False
                continue
            if os.path.basename(token) == 'gh':
                seen_gh = True
            if seen_gh:
                continue
            shell = os.path.basename(token) in ('bash', 'sh', 'zsh', 'dash', 'ksh', 'ash', 'mksh', 'busybox')
            shell = shell or token in ('eval', 'source', '.')
            if os.path.basename(token) in ('watch', 'ssh', 'su', 'script', 'runuser'):
                return 'shell runner names gh'
            if os.path.basename(token) == 'env':
                for later in tokens[index + 1:]:
                    if later and all(char in ';&|\n()' for char in later):
                        break
                    split_option = later.split('=', 1)[0]
                    if (later.startswith(('-S', '--split-string'))
                            or len(split_option) >= 3 and '--split-string'.startswith(split_option)
                            or later.startswith('-') and not later.startswith('--') and 'S' in later):
                        return 'shell runner names gh'
            if shell and not (index + 1 < len(tokens) and tokens[index + 1].endswith('.sh')
                              and not tokens[index + 1].startswith(('/dev/', '/proc/'))):
                return 'shell runner names gh'
    # Keep quote boundaries: GraphQL variables are literal only inside a single-quoted query value.
    pattern = r'''(?:'[^']*'|"(?:\\.|[^"\\])*"|\\.|(?<=(?<!\\)[<>])&|&(?=>)|(?<=(?<!\\)>)\||[^\s'"\\;&|()])+|(?:[;\n()]|(?<!(?<!\\)>)\||(?<!(?<!\\)[<>])&(?!>))+'''
    segments, words = [], []
    for match in re.finditer(pattern, command):
        raw = match[0]
        if all(char in ';&|\n()' for char in raw):
            segments.append(words)
            words = []
            continue
        value = shlex.split(raw)[0]
        words.append((value, raw))
        if (any(re.sub(r'^-[A-Za-z]*S', '', re.split(r'[/=]', token)[-1]).lstrip('!').casefold() == 'gh'
                for token in re.split(r'[\s;&|()<>`]+', re.sub(r'''['"\\]''', '', value)))
                and value != raw):
            reason = review_thread_denial(value)
            if reason:
                return reason
    segments.append(words)
    for words in segments:
        command_words, skip_target = [], False
        for value, raw in words:
            if skip_target:
                skip_target = False
                continue
            redirect = re.match(r'^[0-9]*(?:&>>?|>\||[<>]+&?)', raw)
            if redirect:
                skip_target = redirect.end() == len(raw)
                continue
            command_words.append((value, raw))
        if skip_target and names_gh:
            return 'review-thread guard parse failure'
        words = command_words
        for index, (value, _) in enumerate(words[:-1]):
            if os.path.basename(value) == 'gh':
                subcommand, raw_subcommand = words[index + 1]
                if (any(char.isspace() for char in subcommand)
                        or re.search(r'[$`~*?\[{]', outside_single_quotes(raw_subcommand))):
                    return 'review-thread guard parse failure'
        if any(os.path.basename(value) == 'gh' for value, _ in words) and any(
                re.search(r'[*?\[]|\{[^}]*?(?:,|\.\.)[^}]*\}',
                          re.sub(r'''('([^']*)'|"(?:\\.|[^"\\])*")''', '', raw))
                or re.search(r'''\$['"]''', outside_single_quotes(raw))
                for _, raw in words):
            return 'review-thread guard parse failure'
        calls = [index for index, (value, _) in enumerate(words)
                 if os.path.basename(value) == 'gh' and index + 1 < len(words) and words[index + 1][0] == 'api']
        text = re.sub(r'''['"\\]''', '', ' '.join(raw for _, raw in words))
        for hidden_pattern in (r'[0-9]*(?:&>>?|>\||[<>]+&?)[^\s;&|()]*|[^\s;&|()<>]+',
                               r'[0-9]*(?:&>>?|>\||[<>]+&?)[^\s;&|()`]*|[^\s;&|()<>`]+'):
            hidden_words, skip_target = [], False
            for token in re.findall(hidden_pattern, text):
                if skip_target:
                    skip_target = False
                    continue
                redirect = re.match(r'^[0-9]*(?:&>>?|>\||[<>]+&?)', token)
                if redirect:
                    skip_target = redirect.end() == len(token)
                    continue
                hidden_words.append(token)
            hidden_calls = sum(re.sub(r'^-[A-Za-z]*S', '', re.split(r'[/=]', word)[-1]).lstrip('!').casefold() == 'gh'
                               and hidden_words[index + 1].casefold() == 'api'
                               for index, word in enumerate(hidden_words[:-1]))
            if hidden_calls > len(calls):
                return 'review-thread guard parse failure'
        text = text.casefold()
        for index, (value, raw) in enumerate(words):
            if (os.path.basename(value) == 'gh' or os.path.basename(re.sub(r'''['"\\]''', '', raw)) == 'gh') and any(
                    os.path.basename(previous) in ('xargs', 'parallel')
                    or previous in ('-exec', '-execdir', '-ok', '-okdir') for previous, _ in words[:index]):
                return 'review-thread guard parse failure'
        if ('api.github.com' in normalized and any(marker in normalized for marker in ('graphql', 'pulls', '%'))
                and any(marker in text for marker in ('api.github.com', 'graphql', 'pulls', '%'))):
            first = 0
            while first < len(words) and re.match(r'[A-Za-z_]\w*=', words[first][0]):
                first += 1
            if first < len(words) and os.path.basename(words[first][0]) == 'env':
                first += 1
                while first < len(words) and re.match(r'[A-Za-z_]\w*=', words[first][0]):
                    first += 1
            if (first + 1 >= len(words) or os.path.basename(words[first][0]) != 'gh'
                    or words[first + 1][0] != 'api'):
                return 'GitHub API outside gh'
        for index in calls:
            if any(os.path.basename(value) in ('xargs', 'parallel') or value in ('-exec', '-execdir', '-ok', '-okdir')
                   for value, _ in words[:index]):
                return 'review-thread guard parse failure'
            endpoint, fields, methods, query, inputs = None, False, [], None, False
            arguments = words[index + 2:]
            if any('$' in re.sub(r'''('([^']*)'|"(?:\\.|[^"\\])*")''', '', raw)
                   for _, raw in arguments):
                return 'review-thread guard parse failure'
            cursor, parsed, options = 0, True, True
            expanded_values = set()
            value_options = {'-H', '-X', '-f', '-F', '-q', '-t', '-p', '--method', '--field', '--raw-field',
                             '--input', '--header', '--jq', '--template', '--hostname', '--cache', '--preview'}
            switches = {'--include', '--paginate', '--slurp', '--silent', '--verbose'}
            while cursor < len(arguments):
                value, raw = arguments[cursor]
                option, attached = None, None
                if options and value == '--':
                    options = False
                    cursor += 1
                    continue
                if options and value.startswith('--'):
                    option = value.split('=', 1)[0]
                    if '=' in value:
                        attached = value.split('=', 1)[1]
                        prefix = option + '='
                elif options and value.startswith('-') and value != '-':
                    letter = 1
                    while letter < len(value):
                        if value[letter] == 'i':
                            letter += 1
                            if value[letter:letter + 1] == '=':
                                break
                            continue
                        option = '-' + value[letter]
                        prefix = value[:letter + 1]
                        attached = value[letter + 1:].removeprefix('=') or None
                        break
                if option in value_options:
                    if attached is not None:
                        option_value = attached
                        option_raw = raw.removeprefix(prefix) if raw.startswith(prefix) else raw
                        option_raw = option_raw.removeprefix('=')
                    else:
                        cursor += 1
                        if cursor >= len(arguments):
                            parsed = False
                            break
                        option_value, option_raw = arguments[cursor]
                    expanded_values.add(cursor)
                    if option in ('-X', '--method'):
                        methods.append(option_value.upper())
                    elif option in ('-f', '-F', '--field', '--raw-field', '--input'):
                        fields = True
                        inputs = inputs or option == '--input'
                        if option_value.startswith('query='):
                            query_value = option_value[6:]
                            single = re.fullmatch(r"query='[^']*'|'query=[^']*'", option_raw) is not None
                            query = bool(query_value) and not query_value.startswith('@') and (
                                single or not any(char in option_raw for char in '$`\\'))
                elif options and (value in switches or option is None and value.startswith('-i')):
                    pass
                elif options and value.startswith('-') or endpoint is not None:
                    parsed = False
                else:
                    endpoint = value
                    if value and value[0] not in '$-':
                        expanded_values.add(cursor)
                cursor += 1
            if not parsed:
                if any(re.match(r'-(?!-)[^\s]*[fFX]', value)
                       or value.startswith(('--field', '--raw-field', '--input', '--method'))
                       or '$' in outside_single_quotes(raw) for value, raw in arguments):
                    return 'review-thread guard parse failure'
                continue
            if any('$' in outside_single_quotes(raw) and position not in expanded_values
                   for position, (_, raw) in enumerate(arguments)):
                return 'review-thread guard parse failure'
            raw_endpoint = endpoint or ''
            full_url = '://' in raw_endpoint
            host = None
            if full_url:
                parsed = urllib.parse.urlsplit(raw_endpoint)
                path, host = parsed.path, parsed.netloc.lower().removesuffix('.')
            else:
                path = re.split(r'[?#]', raw_endpoint, maxsplit=1)[0]
            while True:
                decoded = urllib.parse.unquote(path)
                if decoded == path:
                    break
                path = decoded
            route = posixpath.normpath('/' + path).strip('/').casefold()
            if (route == 'graphql' or route.endswith('/graphql')) and (inputs or query is not True):
                return 'opaque GraphQL query'
            write = any(method not in ('GET', 'HEAD') for method in methods) or fields and 'GET' not in methods
            visible = endpoint is not None and not any(char in raw_endpoint for char in '$`%')
            if any(placeholder not in ('{owner}', '{repo}')
                   for placeholder in re.findall(r'\{[^}]*\}', raw_endpoint)):
                visible = False
            if write and (not visible or full_url and host != 'api.github.com'
                          or re.search(r'(?:^|/)pulls/[^/]+/comments(?:/|$)', route)):
                return 'REST review-comment write or opaque endpoint'
            method = methods[-1] if methods else ('POST' if fields else 'GET')
            if method not in ('GET', 'HEAD'):
                return 'gh api write outside the helper'
    return None


def thread_command_config(command):
    normalized = re.sub(r'''['"\\]''', '', command.replace('\\\n', ''))
    for match in re.finditer(r'[^\s;&|(){}]+', normalized):
        word = match[0]
        if 'git_config' in word.casefold() and tuple(word.split('=', 1)) not in WRITER_VALUE_ALLOWLIST:
            return True
    return False


RECEIPT_CUSTODY = ('Only the text_lint hook reads or writes refusal receipts (custody rule). '
                   'Report the blocked scope to the driver.')
RECEIPT_CUSTODY_FAILED = ('The ship hook could not check refusal-receipt custody, so it denies this call. '
                          'Report the blocked scope to the driver.')
PRE_FAILED = ('The ship hook failed, so it denies every tool call. Its traceback is on stderr. '
              'Report the blocked scope to the driver.')
PRE_INPUT_INVALID = ('The ship hook could not read its input as a JSON object, so it denies this call. '
                     'Report the blocked scope to the driver.')


def receipt_custody(data, read_search=False):
    tool, tin = data.get('tool_name', ''), data.get('tool_input') or {}
    if read_search and tool not in ('Read', 'Grep', 'Glob', 'LSP') and not tool.startswith('mcp__fff__'):
        return
    state_root = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    receipt_store = state_root / 'ultraship' / 'text-lint'

    def normalized(value):
        value = value.casefold().translate(str.maketrans('', '', "\"'\\"))
        return re.sub(r'/\.(?=/|$)', '', re.sub(r'/+', '/', value))

    def resolved(value):
        path = os.path.join(data.get('cwd') or os.getcwd(), os.path.expanduser(value))
        return {normalized(os.path.abspath(path)), normalized(os.path.realpath(path))}

    receipt_paths = resolved(str(receipt_store))
    state_paths = resolved(str(state_root))

    def receipt_text(value):
        value = normalized(value)
        return any(path in value for path in receipt_paths) or 'ultraship' + '/text-lint' in value

    def receipt_path(value, ancestors=False, state_only=False):
        if not isinstance(value, str) or not value:
            return False
        return any(candidate == store or candidate.startswith(store + '/')
                   or (ancestors and store.startswith(candidate.rstrip('/') + '/')
                       and (not state_only or any(candidate == root or candidate.startswith(root + '/')
                                                  for root in state_paths)))
                   for candidate in resolved(value) for store in receipt_paths)

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    if read_search:
        try:
            paths = [tin.get(field) for field in ('file_path', 'filePath', 'path', 'notebook_path')]
            if tool == 'Glob' and isinstance(tin.get('pattern'), str):
                paths.append(re.split(r'[*?\[{]', tin['pattern'], maxsplit=1)[0] or '.')
            if tool in ('Grep', 'Glob') and not tin.get('path'):
                paths.append(data.get('cwd') or os.getcwd())
            if any(receipt_text(value) for value in strings(tin)) or any(receipt_path(path, ancestors=True) for path in paths):
                deny(RECEIPT_CUSTODY)
        except Exception:
            deny(RECEIPT_CUSTODY)
        return
    if tool in ('Edit', 'Write', 'NotebookEdit') and receipt_path(tin.get('file_path') or tin.get('notebook_path')):
        deny(RECEIPT_CUSTODY)
    # shortcut: runtime path construction and rebuilt shell expansion escape Bash checks; upgrade to isolated state access.
    if tool == 'Bash':
        raw = str(tin.get('command', ''))
        command = normalized(raw)
        raw_words = [word.translate(str.maketrans('', '', "\"'\\"))
                     for word in re.split(r'[\s;&|<>()]+', raw) if word]
        words = [re.sub(r'^\$(?:\{(HOME|XDG_STATE_HOME)\}|(HOME|XDG_STATE_HOME)(?=/|$))',
                        lambda match: os.environ.get(match[1] or match[2], ''), word)
                 for word in raw_words]

        def glob_prefix(word):
            for pattern in resolved(word):
                segments = pattern.split('/')
                for store in receipt_paths:
                    store_segments = store.split('/')
                    if len(segments) >= len(store_segments) and all(
                            fnmatch.fnmatchcase(segment, pattern_segment)
                            for segment, pattern_segment in zip(store_segments, segments)):
                        return True
            return False

        if (receipt_text(raw)
                or any(receipt_path(word, ancestors=True, state_only=True) for word in words)
                or any(glob_prefix(word) for word in words if any(char in word for char in '*?['))
                or (('.local/state' in command or 'xdg_state_home' in command)
                    and (re.search(r'\b(?:cd|pushd)\b', command) or 'text' in command
                         or any(char in raw for char in '*?[]{}$`')))
                or any(any(char in word for char in '*?[{$`')
                       and (re.search(r'\.local/(s(?:t|[*?\[{$]|$)|[*?\[{$]|$)', word.casefold())
                            or 'xdg_state' in word.casefold() or 'text-lint' in word.casefold())
                       for word in raw_words)
                or re.search(r'text_lint(\.py)?\s+hook\b', command)
                or ('text_lint' in command and any(token in command for token in
                    ('import', 'run_path', 'import_module', '__import__', 'spec_from_file_location', 'exec(')))
                or receipt_path(data.get('cwd') or os.getcwd(), ancestors=True, state_only=True)):
            deny(RECEIPT_CUSTODY)


def canonical_row_path(value):
    if (not isinstance(value, str) or not value.startswith('/')
            or re.search(r'\A[\s\N{ZERO WIDTH NO-BREAK SPACE}]|[\s\N{ZERO WIDTH NO-BREAK SPACE}]\Z', value)
            or unicodedata.normalize('NFC', value) != value):
        return False
    parts = value[1:].split('/') if value != '/' else []
    return not {'', '.', '..'} & set(parts) and os.path.realpath(value) == value


def protected_row_path(value):
    return canonical_row_path(value) and bool(re.search(PROTECTED_ROW, value, re.I))


def regular_file(path):
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def row_record(data, folder, workspace_fallback=False):
    """Read the driver's bounded, private admission record for this agent."""
    agent_id = data.get('agent_id')
    if not isinstance(agent_id, str) or not agent_id:
        return None, 'No admission record can match because the hook payload has no agent_id.'
    record = STATE / folder / (re.sub(r'[^\w.-]', '_', agent_id) + '.json')
    workspace_record = False
    if workspace_fallback and not os.path.lexists(record):
        cwd = Path(os.path.realpath(data.get('cwd') or os.getcwd()))
        for workspace in (cwd, *cwd.parents):
            if (workspace / '.scratch').is_dir():
                candidate = workspace / '.scratch/ultraship' / folder / record.name
                if os.path.lexists(candidate):
                    record, workspace_record = candidate, True
                break
    unmet = f'Admission record {record} must exist and meet this condition: '
    if workspace_record:
        try:
            if (os.path.realpath(record.parent) != os.path.abspath(record.parent)
                    or os.stat(record.parent).st_uid != os.getuid()):
                return None, unmet + 'the record parent has no symlink components and belongs to your UID.'
        except OSError:
            return None, unmet + 'the record parent must exist and belong to your UID.'
    try:
        # O_NONBLOCK keeps a named pipe from hanging the hook.
        descriptor = os.open(record, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None, unmet + 'the record is missing or is a link.'
    with os.fdopen(descriptor, 'rb') as handle:
        status = os.fstat(descriptor)
        if (not stat.S_ISREG(status.st_mode) or status.st_uid != os.getuid()
                or status.st_mode & 0o022 or status.st_size > 65536):
            return None, unmet + 'it is a regular file that you own, not group or world writable, at most 64 KiB.'
        try:
            fields = json.loads(handle.read(65537))
        except Exception:
            fields = None
    if not isinstance(fields, dict):
        return None, unmet + 'it is a JSON object.'
    if not isinstance(fields.get('pr'), str) or not ROW_REVIEW_PR.fullmatch(fields['pr']):
        return None, unmet + '`pr` is a GitHub pull request URL.'
    if fields.get('agent_id') != agent_id:
        return None, unmet + '`agent_id` equals your agent ID.'
    expires = fields.get('expires_at')
    try:
        if not isinstance(expires, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', expires, re.ASCII):
            raise ValueError(expires)
        deadline = calendar.timegm(time.strptime(expires, '%Y-%m-%dT%H:%M:%SZ'))
    except ValueError:
        return None, unmet + '`expires_at` is a UTC time `YYYY-MM-DDTHH:MM:SSZ`.'
    now = time.time()
    if not now < deadline <= now + ROW_REVIEW_MAX_AHEAD:
        return None, unmet + '`expires_at` is later than now and at most 4 hours ahead.'
    return fields, unmet


def row_reanchor_gate(data, command):
    tool = str(Path(__file__).resolve().parents[1] / 'skills/ship/scripts/row_reanchor.py')
    form = ('python3 -I ' + tool + ' --row-file <abs> --row-id <id> --subject <rel> --base <ref> --head <ref>')
    reason = 'Row re-anchor gate requires exactly `' + form + '` and a matching driver-written row-reanchor admission record. '
    word = r'[A-Za-z0-9_./:@+,-]+'
    match = re.fullmatch(r'python3 -I (' + word + r') --row-file (' + word + r') --row-id (' + word
                         + r') --subject (' + word + r') --base (' + word + r') --head (' + word + ')', command)
    if not role(data, 'writer') or not match or match[1] != tool:
        deny(reason)
    fields, unmet = row_record(data, 'row-reanchor')
    if fields is None:
        deny(reason + unmet)
    target = fields.get('row_file')
    if not protected_row_path(target) or target != match[2] or fields.get('row_id') != match[3]:
        deny(reason + unmet + '`row_file` and `row_id` match the canonical protected path and row ID.')
    if not regular_file(target) or match[4].startswith('/') or '..' in match[4].split('/'):
        deny(reason + unmet + 'the row file is regular and the subject is repository-relative.')


def pre(data):
    tool, tin = data.get('tool_name', ''), data.get('tool_input') or {}
    try:
        receipt_custody(data)
    except Exception:
        traceback.print_exc()
        deny(RECEIPT_CUSTODY_FAILED)
    if tool in ('Agent', 'Task') and str(tin.get('subagent_type', '')).startswith('ship:') and tin.get('model'):
        deny('ship agents pin their own model. Remove the `model` field and call the scoped agent '
             'or the next agent in its fallback chain.')
    agent_type = data.get('agent_type') or ''
    if agent_type and not re.match(r'^(ship:)?driver(--|$)', agent_type):
        if tool in ('Edit', 'Write', 'NotebookEdit'):
            written = tin.get('file_path') or tin.get('notebook_path')
            if isinstance(written, str) and written:
                written = os.path.join(data.get('cwd') or os.getcwd(), os.path.expanduser(written))
                for folder in ROW_RECORD_FOLDERS:
                    records = os.path.realpath(STATE / folder).casefold()
                    for path in (os.path.abspath(written).casefold(), os.path.realpath(written).casefold()):
                        if (path == records or path.startswith(records + '/')
                                or re.search(r'/\.scratch/ultraship/' + folder + r'(?:/|$)', path)):
                            deny('Only the driver and the main session write ' + folder + ' admission records. '
                                 'Report the blocked scope to the driver.')
        # shortcut: Bash matches state and workspace paths as text, so a path built from pieces slips past it.
        # Upgrade path: record folders that non-driver agents cannot reach.
        if tool == 'Bash':
            folded_command = str(tin.get('command', '')).casefold()
            for folder in ROW_RECORD_FOLDERS:
                if 'ultraship/' + folder in folded_command:
                    deny('Only the driver and the main session touch ' + folder + ' admission records (custody rule). '
                         'Report the blocked scope to the driver.')
    if tool == 'Bash':
        command = str(tin.get('command', ''))
        # shortcut: substitutions or variables can build option names; upgrade to driver-only record folders and a tool-side record check.
        trigger = command.translate(str.maketrans('', '', "'\"\\")).casefold()
        if '--row-file' in trigger or '--row-id' in trigger or 'row_reanchor' in trigger and '--row-' in trigger:
            row_reanchor_gate(data, command)
    if role(data, 'writer'):
        if tool in ('mcp__bettercoding__create_input', 'mcp__bettercoding__update_input',
                    'mcp__bettercoding__set_input_status'):
            deny('Writers return owner decision needs to the driver. Only the driver maintains Inputs.')
        if tool == 'Bash':
            publication_reason = ('Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; '
                                  'commit grants permit local base-branch merges into their own lane branch. '
                                  'Return this step to your driver; the driver may run it.')
            classifier_reason = ('This operation remains denied. Report the rule and blocked scope to the parent. '
                                 'Native Edit grants zero alternate command form or actor for a denied operation. '
                                 'Require actual cause resolution and fresh applicable disposition for affected sessions before any attempt. '
                                 'Never replay a denied command, equivalent, or substitute actor.')
            try:
                command = tin.get('command', '')
                if any(char.isspace() and char not in ' \t\n' for char in command):
                    deny(classifier_reason + ' Rule: line separator rule.')
                reason = process_heredoc_denial(command)
                if reason:
                    deny(classifier_reason + ' Rule: ' + reason + '.'
                         + (GIT_COMMIT_SHAPE if git_commit_step(command) else ''))
                # Publish words inside an inert heredoc are file text; every executable part keeps the scan.
                file_text_removed = python_heredoc_shell(cat_heredoc_data(command), inert_only=True)
                reason = git_push(command)
                if reason:
                    denial_reason = classifier_reason if reason == 'heredoc-then-run rule' else publication_reason
                    deny(denial_reason + ' Rule: ' + reason + '.')
                match = WRITER_BASH.search(file_text_removed)
                if match:
                    deny(publication_reason + ' Rule: WRITER_BASH ' + repr(match[2].strip()) + '.')
                reason = writer_gh_denial_main(file_text_removed)
                if reason:
                    deny(publication_reason + ' Rule: writer GitHub read-only rule: ' + reason)
                names_gh = re.search(r'\bgh\b', writer_trigger_text(file_text_removed))
                github_reason = writer_gh_denial(file_text_removed)
                if names_gh and github_reason:
                    deny(publication_reason + ' Rule: writer GitHub read-only rule: ' + github_reason)
                reason = process_heredoc_denial(command, readers=True)
                if reason:
                    deny(classifier_reason + ' Rule: ' + reason + '.'
                         + (GIT_COMMIT_SHAPE if git_commit_step(command) else ''))
                try:
                    list(shell_substitution_bodies(shell_without_heredoc_bodies(command)))
                except ValueError as error:
                    if str(error) == 'shell comment substitution':
                        deny(classifier_reason + ' Rule: inline interpreter code rule (comment).')
                    if str(error) == 'shell substitution boundary':
                        deny(classifier_reason + ' Rule: inline interpreter code rule (substitution boundary).')
                    raise
                reason = python_inline_denial(command)
                if reason:
                    deny(classifier_reason + ' Rule: ' + reason + '.')
                reason = inline_interpreter_denial(command, data.get('cwd'))
                if reason:
                    deny(classifier_reason + ' Rule: ' + reason + '.')
                try:
                    list(shell_substitution_bodies(shell_without_heredoc_bodies(command), arithmetic_quotes=True))
                except ValueError as error:
                    if str(error) == 'shell substitution boundary':
                        deny(classifier_reason + ' Rule: inline interpreter code rule (substitution boundary).')
                    raise
                reason = writer_git_file_denial(command, data.get('cwd'))
                if reason:
                    deny(publication_reason + ' Rule: ' + reason)
                if not names_gh and github_reason:
                    deny(publication_reason + ' Rule: writer GitHub read-only rule: ' + github_reason)
            except Exception:
                deny(classifier_reason + ' Rule: classifier exception.')
        target = tin.get('file_path') or tin.get('notebook_path') or ''
        if tool in ('Edit', 'Write', 'NotebookEdit') and writer_git_control_path(
                os.path.join(data.get('cwd') or os.getcwd(), os.path.expanduser(target))):
            deny('Writers do not edit Git configuration or hooks. Return this step to your driver. Rule: git control file write rule.')
        if tool in ('Edit', 'Write', 'NotebookEdit') and (
                HARNESS_PATH.search(target) or target.startswith(str(Path.home() / '.claude') + '/')):
            deny('Writers do not edit harness configuration.')
        if tool in ('Edit', 'Write', 'NotebookEdit'):
            gh_paths = [Path.home() / '.config/gh']
            if os.environ.get('GH_CONFIG_DIR'):
                gh_paths.append(Path(os.environ['GH_CONFIG_DIR']))
            if os.environ.get('XDG_CONFIG_HOME'):
                gh_paths.append(Path(os.environ['XDG_CONFIG_HOME']) / 'gh')
            destination = Path(target).expanduser()
            if not destination.is_absolute():
                destination = Path(data.get('cwd') or Path.cwd()) / destination
            destination = destination.resolve()
            if any(destination.is_relative_to(path.expanduser().resolve()) for path in gh_paths):
                deny('Writers do not edit GitHub CLI configuration.')
    if tool == 'Bash':
        try:
            command = tin.get('command', '')
            reason = review_thread_denial(command)
            if reason is None:
                separated = re.sub(r'''['"\\]''', ' ', command).casefold()
                normalized = re.sub(r'''['"\\]''', '', command.replace('\\\n', '')).casefold()
                if re.search(r'\bgh\b', separated) and not re.search(r'\bgh\b', normalized):
                    reason = 'quote-joined gh word'
                elif (re.search(r'(?<!<)<<(?!<)', command) and '\\\n' in command
                      and (re.search(r'\bgh\b', separated) or re.search(r'\bgh\b', normalized))):
                    reason = 'heredoc with line continuation'
                elif (thread_command_config(command) or '--config-env' in command
                      or "$'" in command and (re.search(r'\b(?:gh|api)\b', separated)
                                             or re.search(r'\b(?:gh|api)\b', normalized))):
                    reason = 'git config from the command line'
        except Exception:
            reason = 'review-thread guard parse failure'
        if reason:
            deny("Ship replies to and resolves review threads only through `skills/babysit/scripts/thread_reply.py`, "
                 "which first checks that the thread belongs to the PR's own repository and number. Rule: " + reason + '.')
    if role(data, 'researcher') and DISCOVERY.match(tool):
        counter = STATE / 'budget' / re.sub(r'[^\w.-]', '_', data.get('agent_id') or 'unknown')
        counter.parent.mkdir(parents=True, exist_ok=True)
        used = int(counter.read_text() or 0) if counter.exists() else 0
        if used >= RESEARCH_BUDGET:
            deny(f'Research budget of {RESEARCH_BUDGET} discovery calls is spent. Return your answer '
                 'with the evidence you have and list what stays unconfirmed.')
        counter.write_text(str(used + 1))
    if LEDGER_ROLES.match(data.get('agent_type') or '') and (
            tool in ('Read', 'Grep', 'Glob', 'LSP', 'WebFetch') or tool.startswith('mcp__')):
        if tool.startswith('mcp__'):
            deny('Reviewers cannot use mcp__ tools. Use Grep or Glob with an explicit path.')
        try:
            protected = PROTECTED_ROW
            blocked = 'Reviewers cannot access explicit tests/mutation/ paths. Report the blocked scope to the coordinator.'
            if tool == 'WebFetch':
                url = tin.get('url')
                if not isinstance(url, str):
                    deny('Reviewers require a string url.')
                # A WHATWG parser trims C0 controls and spaces at both ends and drops tabs and newlines anywhere.
                url = re.sub(r'[\t\n\r]', '', url).strip(''.join(map(chr, range(33))))
                raw = url
                # A WHATWG parser finds a host after `https:`, `https:/` or `https:///`; urlsplit finds none.
                if not re.match(r'(?i)https?://[^/\\?#]', raw):
                    deny('Reviewers require an http(s) URL with exactly two slashes before its host.')
                while urllib.parse.unquote(url) != url:
                    url = urllib.parse.unquote(url)
                # A `.` segment decoded from `%2e` is removed by the URL parser, and servers read `\` as `/`.
                url = url.replace('\\', '/')
                # GitHub addresses blobs, commits and diffs by ID with no path, so no path rule can see a protected row.
                # Check every reading of the host a fetcher might take; IDNA maps fullwidth forms and `。` to ASCII.
                for text in (raw, raw.replace('\\', '/'), url):
                    host = urllib.parse.unquote(urllib.parse.urlsplit(text).hostname or '')
                    if not host:
                        deny('Reviewers require a URL with a host.')
                    host = unicodedata.normalize('NFKC', host).replace('\u3002', '.').lower().rstrip('.')
                    if not host.isascii():
                        deny('Reviewers cannot fetch a URL whose host is not plain ASCII.')
                    if re.search(r'(^|\.)(github\.com|githubusercontent\.com)$', host):
                        deny('Reviewers cannot fetch GitHub URLs. Read the local worktree at the frozen SHA.')
                if any(re.search(protected, text, re.IGNORECASE)
                       for text in (url, posixpath.normpath(urllib.parse.urlsplit(url).path))):
                    deny(blocked)
                return
            unscoped = ('Reviewers must scope searches to an explicit path. '
                        'Report failed or empty searches; never widen the scope.')
            private = ('Reviewers cannot read Claude Code data under the Claude config folder (~/.claude), such as '
                       'session transcripts and file history. Only CLAUDE.md, plugins/cache and plugins/marketplaces stay readable. '
                       'Report the blocked scope to the coordinator.')

            def normalize(value):
                return os.path.realpath(value)

            home = normalize(str(Path.home()))
            cwd = normalize(data.get('cwd') or str(Path.cwd()))
            claude_dirs = {normalize(str(Path.home() / '.claude'))}
            if os.environ.get('CLAUDE_CONFIG_DIR'):
                claude_dirs.add(normalize(os.environ['CLAUDE_CONFIG_DIR']))

            def claude_data(path):
                # Checkpoints, transcripts and saved results hold copies of protected rows under other names.
                for claude in claude_dirs:
                    lowered = claude.casefold()
                    if path.casefold() != lowered and not path.casefold().startswith(lowered + '/'):
                        continue
                    readable = path == claude + '/CLAUDE.md' or any(
                        path == f'{claude}/plugins/{kind}' or path.startswith(f'{claude}/plugins/{kind}/')
                        for kind in ('cache', 'marketplaces'))
                    if not readable:
                        return True
                return False

            paths, globs = [], []
            fields = {'file_path': paths, 'filePath': paths, 'path': paths, 'glob': globs}
            if tool == 'Glob':
                fields['pattern'] = globs
            for field, values in fields.items():
                if field in tin:
                    if not isinstance(tin[field], str):
                        deny('Reviewers require string paths and globs.')
                    values.append(tin[field])
            for path in paths:
                if not canonical_row_path(path):
                    deny('Reviewers must pass an exact absolute path: no `~`, `.` or `..` segment, repeated or '
                         'trailing `/`, symlink, surrounding whitespace, or Unicode that is not in NFC form. '
                         'Report the blocked scope to the coordinator.')
            if any('.git' in path.casefold().split('/') for path in paths):
                deny('Reviewers cannot access `.git` paths. Report the blocked scope to the coordinator.')
            if any(claude_data(path) for path in paths):
                deny(private)

            def row_admission():
                """Return the unmet condition, or None when the driver admitted this exact row-file read."""
                fields, unmet = row_record(data, 'row-review', workspace_fallback=True)
                if fields is None:
                    return unmet
                target = tin.get('file_path') if tool == 'Read' else tin.get('path') if tool == 'Grep' else None
                if paths != [target] or 'glob' in tin or 'type' in tin:
                    return unmet + ('only Read of a listed row file, or Grep with a listed row file as `path` '
                                    'and no `glob` or `type`, can be admitted.')
                files = fields.get('row_files')
                if (not isinstance(files, list) or not files
                        or any(not protected_row_path(item) for item in files)):
                    return unmet + '`row_files` lists canonical absolute paths that contain tests/mutation.'
                if target not in files:
                    return unmet + 'the path equals one `row_files` entry.'
                if not regular_file(target):
                    return unmet + 'the listed row file is a regular file.'
                return None

            admitted = False
            # The typed name counts: a case-insensitive file system can hide the protected directory.
            if any(re.search(protected, path, re.IGNORECASE) for path in paths):
                unmet = row_admission()
                if unmet:
                    deny(blocked + ' ' + unmet)
                admitted = True
            base = tin['path'] if tool in ('Grep', 'Glob') and 'path' in tin else cwd
            for glob in globs:
                for token in glob.split():
                    if re.search(r'(?:^|[{,!])[/~]|(?:^|[/{,!])\.\.(?:$|[/},])', token):
                        deny('Reviewers must pass globs relative to the search path: '
                             'no absolute or `~` glob and no `..` segment.')
                    if re.search(protected, posixpath.normpath(posixpath.join(base, token.lstrip('!'))), re.IGNORECASE):
                        deny(blocked)
            if tool == 'LSP' and (tin.get('operation') not in ('hover', 'documentSymbol') or 'filePath' not in tin):
                deny('Reviewers may use LSP hover and documentSymbol on one explicit file only. '
                     'Use Grep or Glob with an explicit path for other lookups.')
            if tool in ('Grep', 'Glob'):
                def bounded(resolved):
                    return not any(posixpath.commonpath((resolved, target)) == resolved
                                   for target in ('/', home, cwd))

                if 'path' not in tin or not bounded(tin['path']):
                    deny(unscoped)
                roots = [tin['path']]

                deadline = time.monotonic() + 5
                seen = set()
                while roots:
                    if time.monotonic() > deadline:
                        deny('Reviewers must narrow the search scope: directory walk exceeds 5 seconds.')
                    directory = roots.pop()
                    if not admitted and re.search(protected, directory, re.IGNORECASE):
                        deny(blocked)
                    if claude_data(directory):
                        deny(private)
                    try:
                        status = os.stat(directory)
                    except (FileNotFoundError, NotADirectoryError):
                        continue
                    identity = (status.st_dev, status.st_ino)
                    if not stat.S_ISDIR(status.st_mode) or identity in seen:
                        continue
                    seen.add(identity)
                    if len(seen) > 20000:
                        deny('Reviewers must narrow the search scope: directory walk exceeds 20000 directories.')
                    entries = []
                    try:
                        for entry in os.scandir(directory):
                            entries.append(entry)
                            if len(entries) % 256 == 0 and time.monotonic() > deadline:
                                deny('Reviewers must narrow the search scope: directory walk exceeds 5 seconds.')
                    except FileNotFoundError:
                        continue
                    if posixpath.basename(directory).casefold() == 'tests' and any(
                            entry.name.casefold() == 'mutation' for entry in entries):
                        deny(blocked)
                    for entry in entries:
                        if entry.name == '.git':
                            continue
                        if entry.is_symlink():
                            target = os.path.realpath(entry.path)
                            if not bounded(target):
                                deny(unscoped)
                            roots.append(target)
                        elif entry.is_dir(follow_symlinks=False):
                            roots.append(entry.path)
        except Exception:
            deny('Reviewers cannot proceed when search scope validation fails. Report the blocked scope to the coordinator.')
    receipt_custody(data, read_search=True)


def owed_file(data):
    return STATE / 'owed' / (re.sub(r'[^\w.-]', '_', data.get('session_id') or 'unknown') + '.tsv')


def run_identity(index, row):
    return [index, hashlib.sha256(json.dumps(row).encode()).hexdigest()]


def subagent_stop(data):
    if LEDGER_ROLES.match(data.get('agent_type') or ''):
        path = owed_file(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        cwd = data.get('cwd') or os.getcwd()
        result = {'id': str(uuid.uuid4()), 'v': 2}
        for key in ('agent_id', 'agent_transcript_path'):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                result[key] = value
        try:
            ledger = load_ledger()
            home = ledger.ledger_path(cwd).resolve()
            history = ledger.rows(home)
            # Read the ledger once, so the open-run check and the run identity share one snapshot.
            marks = [i for i, row in enumerate(history) if row[1] in ('run-start', 'run-end')]
            if not marks or history[marks[-1]][1] != 'run-start':
                return
            result.update(ledger=str(home), run=run_identity(marks[-1], history[marks[-1]]))
        except Exception:
            # Always retain the notification, including when ledger access fails.
            pass
        with path.open('a') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(f"{int(time.time())}\t{data['agent_type']}\t{cwd}\t{json.dumps(result)}\n")


def account(ledger, cwd, notifications, receipts, session):
    histories, occurrences = {}, {}
    for owed in notifications:
        epoch, agent, _ = owed[:3]
        if len(owed) == 4:
            result = json.loads(owed[3])
        else:
            line = '\t'.join(owed)
            ordinal = occurrences.get(line, 0)
            occurrences[line] = ordinal + 1
            result = {'id': 'legacy:' + hashlib.sha256(
                json.dumps([session, line, ordinal]).encode()).hexdigest()}
        result_id = json.dumps([session, cwd, result['id']])
        if 'ledger' in result and result['run'] is None:
            continue
        # Recorded results keep their ledger across branch changes. Only legacy results resolve the current branch.
        home = Path(result['ledger']) if 'ledger' in result else ledger.ledger_path(cwd).resolve()
        if not home.is_absolute() or home.resolve() != home:
            raise ValueError('Recorded ledger must be an absolute path without symlinks')
        if home not in histories:
            histories[home] = ledger.rows(home)
        history = histories[home]
        starts = [i for i, row in enumerate(history) if row[1] == 'run-start']
        if 'ledger' in result:
            candidates = [i for i in starts if run_identity(i, history[i]) == result['run']]
        else:
            # Legacy notifications have no run identity: accept only one time-containing run.
            candidates = []
            for pos, start in enumerate(starts):
                end = starts[pos + 1] if pos + 1 < len(starts) else len(history)
                closed = next((r for r in history[start + 1:end] if r[1] == 'run-end'), None)
                if int(history[start][0]) <= int(epoch) and (closed is None or int(epoch) <= int(closed[0])):
                    candidates.append(start)
        if len(candidates) != 1:
            raise ValueError(f'No unambiguous ship run in {cwd} for pending result {result["id"]}; restore the intended run')
        start = candidates[0]
        end = next((i for i in starts if i > start), len(history))
        end = next((i for i in range(start + 1, end) if history[i][1] == 'run-end'), end)
        if result_id in receipts:
            saved = receipts[result_id]
            if saved[0] != str(home) or saved[1] != run_identity(start, history[start]):
                raise ValueError('Accounting receipt names a different ledger or run')
            index = saved[2][0]
            if not 0 <= index < len(history) or saved[2] != run_identity(index, history[index]):
                raise ValueError('Accounting receipt row is missing or differs; restore the ledger evidence')
            if not start < index < end and not ledger.accounting_row(history[index], result_id, result['run']):
                raise ValueError('Accounting receipt row belongs to another run')
            continue
        used = {json.dumps(value) for value in receipts.values()}
        # Reserve an exact-result record before consuming an interchangeable ordinary review row.
        candidates = sorted(range(start + 1, len(history)), key=lambda i:
                            not ledger.accounting_row(history[i], result_id, run_identity(start, history[start])))
        for i in candidates:
            row = history[i]
            identity = [str(home), run_identity(start, history[start]), run_identity(i, row)]
            explicit = ledger.accounting_row(row, result_id, run_identity(start, history[start]))
            regular = i < end and row[1] not in ledger.MARKS
            kind, ident = ledger.agent_key(row[2])
            # A row binds only to the result whose agent ID it names. Records written before
            # ID binding (no 'v') also accept a row without an ID, so in-flight runs still clear.
            owner = (kind, ident) == (agent, result.get('agent_id')) or (
                result.get('v') != 2 and kind == agent and ident is None)
            if (((explicit and kind == agent) or (regular and owner))
                    and row[4] != 'owed' and int(row[0]) >= int(epoch) - 5 and json.dumps(identity) not in used):
                receipts[result_id] = identity
                break
        else:
            named = agent + (f'@{result["agent_id"]}' if result.get('agent_id') else '')
            raise ValueError(f'Review results have no unused ledger row for agent {named}; pending result {result["id"]}')


def stop(data):
    path = owed_file(data)
    if data.get('stop_hook_active'):
        return
    try:
        reminder = path.with_suffix('.stop-state')
        try:
            path.stat()
        except FileNotFoundError:
            reminder.unlink(missing_ok=True)
            return
        with path.open('r+') as pending:
            fcntl.flock(pending, fcntl.LOCK_EX)
            owed = [line.split('\t') for line in pending.read().splitlines() if line]
            if not owed:
                reminder.unlink(missing_ok=True)
                return
            try:
                ledger = load_ledger()
                receipt_path = STATE / 'accounted.json'
                # ponytail: one hook-state receipt lock serializes Stops; shard by ledger
                # if concurrent Stop throughput matters. This never locks a legacy home.
                with (STATE / 'accounted.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    try:
                        receipts = json.loads(receipt_path.read_text())
                    except FileNotFoundError:
                        receipts = {}
                    for cwd in {o[2] for o in owed}:
                        account(ledger, cwd, [o for o in owed if o[2] == cwd], receipts, str(path))
                    ledger.publish(receipt_path, receipts)
            except Exception as accounting_error:
                try:
                    canonical = [row[:3] + [json.loads(row[3])] if len(row) == 4 else row for row in owed]
                except ValueError:
                    canonical = owed
                fingerprint = hashlib.sha256(json.dumps(sorted(
                    json.dumps(row, sort_keys=True) for row in canonical)).encode()).hexdigest()
                try:
                    try:
                        previous = reminder.read_text()
                    except FileNotFoundError:
                        previous = None
                    if previous == fingerprint:
                        return
                    reminder.write_text(fingerprint)
                except OSError as reminder_error:
                    raise ValueError(f'{accounting_error}; Stop reminder unavailable: {reminder_error}') from accounting_error
                raise
            # Clear only after every result has a successful accounting row.
            # Keep this inode so concurrent SubagentStop writers share the lock.
            reminder.unlink(missing_ok=True)
            pending.seek(0)
            pending.truncate()
    except Exception as exc:
        print(json.dumps({'decision': 'block', 'reason':
              f'Pending review evidence retained at {path}: {exc}. '
              'Resolve ledger access (set SHIP_LEDGER_DIR to an absolute permitted directory if needed). '
              'Record each result with `ledger.py append <step> <agent> <sha> <verdict> [note]` in its open run, '
              'Read every retained result and use its exact agent identity, including @agent_id when present. '
              'For a recorded result in a closed or earlier-branch run, use '
              f'`ledger.py account {path} <result-id> <step> <agent> <sha> <verdict> <evidence>`; '
              'this appends bookkeeping without reopening the run. Never invent review evidence.'}))


def compact(data):
    lines = ['Context was compacted. Re-establish state from disk before you continue: run git status and '
             'git diff --stat, re-read the active plan and run board, and never guess dropped state.']
    try:
        ledger = load_ledger()
        path = ledger.ledger_path(data.get('cwd') or '.')
        run = ledger.open_run(path)
        pending = owed_file(data)
        if pending.exists() and pending.stat().st_size:
            lines.append(f'Pending review evidence remains at {pending}. '
                         'Account each result with ledger.py before declaring the run complete.')
    except Exception as exc:
        lines.append(f'Ledger resolution failed: {exc}. Pending review evidence remains at {owed_file(data)}. '
                     'Restore ledger access or set SHIP_LEDGER_DIR to an absolute permitted directory before continuing.')
        run = None
    if run:
        lines.append(f'Open ship run: {run[0][5]} (mode {run[0][2]}). Ledger: {path}. '
                     f'Gaps: {" ".join(ledger.gaps(run)) or "none"}. The run note names the board path.')
    print('\n'.join(lines))


def guarded_pre(data):
    """Deny every tool for every caller when `pre` raises an exception."""
    try:
        pre(data)
    except Exception:
        traceback.print_exc()
        try:
            receipt_custody(data, read_search=True)
        except Exception:
            tool = data.get('tool_name') if isinstance(data, dict) else ''
            if isinstance(tool, str) and (tool in ('Read', 'Grep', 'Glob', 'LSP') or tool.startswith('mcp__fff__')):
                deny(RECEIPT_CUSTODY)
        deny(PRE_FAILED)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    handler = {'pre': guarded_pre, 'subagent-stop': subagent_stop, 'stop': stop, 'compact': compact}.get(mode)
    if not handler:
        sys.exit(__doc__)
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        if mode == 'pre':
            deny(PRE_INPUT_INVALID)
        payload = {}
    if mode == 'pre' and not isinstance(payload, dict):
        deny(PRE_INPUT_INVALID)
    handler(payload)
