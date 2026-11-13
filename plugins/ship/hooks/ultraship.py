#!/usr/bin/env python3
"""Ultraship hooks. Usage: ultraship.py pre|subagent-stop|stop|compact < hook-input.json"""
import ast
import fcntl
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shlex
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'ultraship'
RESEARCH_BUDGET = 40
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
            if not inert_python(body):
                return True
            # An inert script writes only through `open` with a write mode or a `Path` write method.
            return python_writes(body, isolated='I' in match['flags'] and not inert_python(body))
    return False


PYTHON_STDIN = (r"(?:python|python3(?:\.\d+)?)(?P<flags>(?: +-[IB]+)*) +- +<<(?P<tabs>-?)[ \t]*"
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


def process_heredoc_denial(command, readers=False):
    """Check Python stdin bodies and keep quoted commit messages as data."""
    lines = (command if readers else cat_heredoc_data(command)).splitlines(keepends=True)
    index = 0
    while index < len(lines):
        operators = list(re.finditer(r"(?<!<)<<(?P<tabs>-?)(?!<)[ \t]*"
                                    r"(?P<delimiter>'[^'\n]+'|\"[^\"\n]+\"|\\?[^\s<>;&|()'\"`]+)", lines[index]))
        if not operators:
            if readers and '<<' in lines[index] and not data_reader_header(lines[index]):
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
        interpreter = re.search(r'(?<![\w.-])(?:[\w./-]*/)?python(?:3(?:\.\d+)?)?(?=[ \t<]|$)', lines[index])
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
            else:
                index += 1
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
    for line in lines:
        if pending:
            delimiter, tabs, quoted = pending[0]
            if (line.lstrip('\t') if tabs else line).removesuffix('\n') == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        for match in re.finditer(r"(?<!<)<<(?!<)(-?)[ \t]*('[^'\n]+'|\"[^\"\n]+\"|\\?[^\s<>;&|()'\"`]+)", line):
            pending.append((shlex.split(match[2])[0], bool(match[1]), match[2][0] in '\'"\\'))
    return ''.join(kept)


SHELL_INTERPRETERS = {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish', 'csh', 'tcsh', 'mksh', 'yash', 'rbash', 'ash'}
STRING_WRAPPERS = SHELL_INTERPRETERS | {'env', 'eval', 'watch', 'script', 'flock', 'su'}


def nested_shell_strings(tokens):
    """Keep the identity of each argument that a shell or string wrapper can execute."""
    for index, token in enumerate(tokens):
        name = os.path.basename(token[1])
        if name not in STRING_WRAPPERS:
            continue
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
    """Treat expansion markers conservatively; single quotes protect only glob characters."""
    spans = single_quoted_spans(raw)
    return '$' in raw or '`' in raw or spans is None or any(
        re.search(r'[*?\[{]|^=', span) for span, single in spans if not single)


def nested_work_exceeded(tokens, seen):
    return len(seen) > 64 or len(tokens) * sum(
        os.path.basename(token[1]) in STRING_WRAPPERS for token in tokens) > 50000


def shell_input_state(tokens, inherited=(False, False, False)):
    redirected = inherited[2] or any(token[0] == '<' for token in tokens)
    piped = inherited[0] or redirected or any(token[1] == 'coproc' for token in tokens) or any(
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
        except ValueError:
            return 'process-capable python -c rule'
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
                if not re.fullmatch(r'python(?:3(?:\.\d+)?)?', os.path.basename(value)):
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
        state = shell_input_state(tokens, inherited)
        pending.extend((token[1], state) for token in nested_shell_strings(tokens))
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
    return 'python' if re.fullmatch(r'python(?:3(?:\.\d+)?)?', base) else None


def code_option(value):
    return bool(re.match(r'--(?:eval|print)(?:=|$)|-[ceEpr]|-[a-zA-Z]*[ceE]', value))


def stdin_program_path(value):
    path = os.path.normpath(re.sub(r'/+', '/', value))
    resolved = os.path.normpath(os.path.join(os.getcwd(), path))
    return (value == '-' or '..' in value.split('/') or path in {'dev', 'proc'}
            or path.startswith(('dev/', 'proc/')) or resolved in {'/dev', '/proc'}
            or resolved.startswith(('/dev/', '/proc/')))


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
                if (unresolved_shell_word(raw) or not target or target.startswith(('-', '~', '/'))
                        or '..' in target.split('/') or not re.fullmatch(r'[\w./-]+', target)):
                    return False
                targets.append(target)
            pending.extend(token[1] for token in nested_shell_strings(tokens))
        except ValueError:
            return False
    if len(targets) != 1:
        return False
    base = os.path.realpath(cwd or os.getcwd())
    target = os.path.realpath(os.path.join(base, targets[0]))
    forbidden = lambda path: path in {'/proc', '/dev'} or path.startswith(('/proc/', '/dev/'))
    return not forbidden(base) and not forbidden(target) and os.path.isdir(target)


def inline_interpreter_denial(command, cwd=None):
    safe_directory = safe_directory_state(command, cwd)
    shell = literal_variables(shell_without_heredoc_bodies(command))
    lines = command.splitlines(keepends=True)
    if lines and ANY_PYTHON_HEREDOC.fullmatch(lines[0]) and not process_heredoc_denial(command):
        shell = shell[len(lines[0]):]
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
        except ValueError:
            return 'inline interpreter code rule (unresolved command word)'
        if nested_work_exceeded(tokens, seen):
            return 'inline interpreter code rule (nesting limit)'
        nested = list(nested_shell_strings(tokens))
        input_tokens = shell_raw_words(shell_line_continuations(shell))
        state = shell_input_state(tokens, shell_input_state(input_tokens, inherited))
        piped_input, directory, redirected = state
        relative_program_denied = piped_input or directory and not safe_directory
        if re.search(r'(?:\$\([^\n]*\)|`[^`\n]*`)[ \t]+(?:-[ceEpr]\b|--(?:eval|print)\b|-[a-zA-Z]*[ce]\b)', text):
            return 'inline interpreter code rule (unresolved command word)'
        segments, words, piped = [], [], False
        for token in tokens:
            raw = token[0]
            if raw in {';', '&', '|', '(', ')', '`', '\n'}:
                if words:
                    segments.append((words, piped))
                    words = []
                if raw != '\n':
                    piped = raw == '|'
            else:
                words.append(token)
        segments.append((words, piped))
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
        for words, piped in segments:
            first = next((word for word in words if not re.match(r'[A-Za-z_]\w*=', word[1])), None)
            if (piped_input and first and first[0] != '[' and first[1] != '$?'
                    and unresolved_shell_word(first[0])):
                return 'inline interpreter code rule (unresolved command word)'
            for index, (raw, value, start, end) in enumerate(words):
                arguments = [word[1] for word in words[index + 1:]]
                unresolved = raw != '[' and value != '$?' and start not in shell_programs and unresolved_shell_word(raw)
                names = '|'.join(re.escape(name) for name in (*INLINE_INTERPRETERS, 'python'))
                joined_code = unresolved_shell_word(raw) and bool(re.search(
                    rf'{names}|--(?:eval|print)|(?:^|[^\w])(?:-[ceEpr]|eval|run|repl)(?:$|[^\w])', raw))
                if joined_code or unresolved and (any(code_option(argument) for argument in arguments)
                                                   or arguments[:1] and arguments[0] in {'eval', 'run', 'repl'}):
                    return 'inline interpreter code rule (unresolved command word)'
                if first and first[0] in {'grep', 'egrep', 'fgrep'} and start > first[2]:
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
                    if (not script or script.startswith('-') or stdin_program_path(script)
                            or (relative_program_denied or piped) and not os.path.isabs(script)
                            or not re.fullmatch(r'[\w./:@%+,-]+', words[index + 1][0])):
                        return ('inline interpreter code rule (program from a pipe)' if piped_input or stdin_program_path(script)
                                or (relative_program_denied or piped) and script and not os.path.isabs(script)
                                else f'inline interpreter code rule ({name})')
                elif not arguments or any(stdin_program_path(argument) for argument in arguments):
                    return 'inline interpreter code rule (program from a pipe)'
                else:
                    kind, flags, operand, offset = python_program(arguments)
                    if (kind == 'script' and operand < len(arguments) and (relative_program_denied or piped)
                            and not os.path.isabs(arguments[operand])):
                        return 'inline interpreter code rule (program from a pipe)'
                    if (piped_input or piped) and (kind not in {'c', 'm', 'script'} or operand >= len(arguments)
                                        or 'i' in flags or any(word[1].startswith('PYTHONINSPECT=') for word in words)):
                        return 'inline interpreter code rule (program from a pipe)'
        pending.extend((token[1], state) for token in nested)
    return None


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
        except ValueError:
            # The text cannot be split, so `git` with a writer word or any expansion or escape denies.
            if re.search(r'\bgit\b', text) and (
                    re.search(r'\b(?:push|send-pack|http-push)\b', text.translate(str.maketrans('', '', '$`*?[]{},')))
                    or re.search(r'[$`\\]', text)):
                return 'git unparseable writer or expansion rule'
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


# ponytail: this text guard misses credential-backed writes via env clearing, git -c, pushurl, direct ssh, token HTTP, existing gh aliases and extensions, Bash writes to gh configuration, glob `?` and writer-created file names, and files written then run; auto mode classifies env-based push refusal as blocked traffic redirection, so the upgrade path is an isolated read-only credential (owner Input a464c49b).
def writer_gh_denial(command, depth=0):
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
    except ValueError:
        return reason
    for token in tokens:
        if any(char.isspace() or char in ';&|()' for char in token):
            nested = writer_gh_denial(token, depth + 1)
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


def pre(data):
    tool, tin = data.get('tool_name', ''), data.get('tool_input') or {}
    if tool in ('Agent', 'Task') and str(tin.get('subagent_type', '')).startswith('ship:') and tin.get('model'):
        deny('ship agents pin their own model. Remove the `model` field and call the scoped agent '
             'or the next agent in its fallback chain.')
    if role(data, 'writer'):
        if tool in ('mcp__bettercoding__create_input', 'mcp__bettercoding__update_input',
                    'mcp__bettercoding__set_input_status'):
            deny('Writers return owner decision needs to the driver. Only the driver maintains Inputs.')
        if tool == 'Bash':
            publication_reason = ('Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; '
                                  'commit grants permit local base-branch merges into their own lane branch. '
                                  'Return this step to your driver; the driver may run it.')
            try:
                command = tin.get('command', '')
                if any(char.isspace() and char not in ' \t\n' for char in command):
                    deny(publication_reason + ' Rule: line separator rule.')
                reason = process_heredoc_denial(command)
                if reason:
                    deny(publication_reason + ' Rule: ' + reason + '.')
                # Publish words inside an inert heredoc are file text; every executable part keeps the scan.
                file_text_removed = python_heredoc_shell(cat_heredoc_data(command), inert_only=True)
                reason = git_push(command)
                if reason:
                    deny(publication_reason + ' Rule: ' + reason + '.')
                match = WRITER_BASH.search(file_text_removed)
                if match:
                    deny(publication_reason + ' Rule: WRITER_BASH ' + repr(match[2].strip()) + '.')
                reason = writer_gh_denial(file_text_removed)
                if reason:
                    deny(publication_reason + ' Rule: writer GitHub read-only rule: ' + reason)
                reason = process_heredoc_denial(command, readers=True)
                if reason:
                    deny(publication_reason + ' Rule: ' + reason + '.')
                reason = python_inline_denial(command)
                if reason:
                    deny(publication_reason + ' Rule: ' + reason + '.')
                reason = inline_interpreter_denial(command, data.get('cwd'))
                if reason:
                    deny(publication_reason + ' Rule: ' + reason + '.')
            except Exception:
                deny(publication_reason + ' Rule: classifier exception.')
        target = tin.get('file_path') or tin.get('notebook_path') or ''
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
    if role(data, 'researcher') and DISCOVERY.match(tool):
        counter = STATE / 'budget' / re.sub(r'[^\w.-]', '_', data.get('agent_id') or 'unknown')
        counter.parent.mkdir(parents=True, exist_ok=True)
        used = int(counter.read_text() or 0) if counter.exists() else 0
        if used >= RESEARCH_BUDGET:
            deny(f'Research budget of {RESEARCH_BUDGET} discovery calls is spent. Return your answer '
                 'with the evidence you have and list what stays unconfirmed.')
        counter.write_text(str(used + 1))


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


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    handler = {'pre': pre, 'subagent-stop': subagent_stop, 'stop': stop, 'compact': compact}.get(mode)
    if not handler:
        sys.exit(__doc__)
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    handler(payload)
