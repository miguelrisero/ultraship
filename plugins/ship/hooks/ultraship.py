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
import tempfile
import time
import uuid
from pathlib import Path

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
PATH_METHODS = {'read_text', 'exists', 'write_text', 'unlink'}
LOADABLE = re.compile(r'\.(?:py[cdiow]?|pth|so)(?:$|[^A-Za-z0-9])', re.I)
INERT_ATTRIBUTES = {
    'Path', 'read_text', 'write_text', 'exists', 'open', 'read', 'write', 'close', 'name', 'parent', 'with_suffix',
    'replace', 'split', 'rsplit', 'join', 'strip', 'lstrip', 'rstrip', 'splitlines', 'startswith', 'endswith',
    'find', 'index', 'count', 'lower', 'upper', 'encode', 'decode', 'append', 'extend', 'insert', 'pop', 'get',
    'items', 'keys', 'values', 'group', 'groups', 'sub', 'compile', 'search', 'fullmatch', 'findall', 'escape',
    'loads', 'dumps', 'load', 'dump', 'dedent', 'sha256', 'hexdigest', 'unlink',
}
READ_ONLY_COMMANDS = {'sed', 'grep', 'head', 'tail', 'cat', 'wc', 'diff', 'echo', 'ls', 'true', 'date'}
READ_ONLY_STARTS = {'cat', 'grep', 'head', 'tail', 'ls', 'wc', 'diff', 'cd', 'git'}
REFLECTION = {'eval', 'exec', 'compile', 'getattr', 'setattr', 'delattr', 'globals', 'locals', 'vars', 'breakpoint',
              'help', 'input'}


def inert_python(body):
    """Whether a Python script can only compute and read or write files, so its words are file text, not commands."""
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
            if node.attr not in INERT_ATTRIBUTES:
                return False
            if (isinstance(node.value, ast.Name) and node.value.id in modules
                    and node.attr not in INERT_MEMBERS[modules[node.value.id]]):
                return False
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A dunder attribute path (`0.__globals__`, `[__x`) or a bare dunder name can reach reflection through
            # format fields; other text that mentions a dunder, such as `import __main__`, is file text.
            if re.search(r'^__|[.\[]__', node.value) or '.git/' in node.value or '.git\\' in node.value or node.value.endswith('.git'):
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


def writable(path):
    """Whether an inert script may write `path`: a literal that Python cannot import.

    Python can import a module written moments earlier, also while it formats an exception, so no module file
    qualifies; writers edit those with the Edit tool."""
    return isinstance(path, str) and not LOADABLE.search(path)


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

    def constructed(node):
        argument = node.args[0] if len(node.args) == 1 and not node.keywords else None
        return (argument.value if isinstance(argument, ast.Constant) and isinstance(argument.value, str) else
                literals.get(argument.id) if isinstance(argument, ast.Name) else None)

    imported = sum(alias.name == 'Path' for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module == 'pathlib' for alias in node.names)
    holders = {}
    for statement in tree.body:
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name) and isinstance(statement.value, ast.Call)):
            holders.setdefault(statement.targets[0].id, []).append(statement)
    for node in ast.walk(tree):
        named = (node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None)
        if named != 'Path':
            continue
        call = parents.get(node)
        if not (isinstance(call, ast.Call) and call.func is node) or bound.count('Path') != imported:
            return False
        if call.keywords or len(call.args) != 1:
            return False
        owner = parents.get(call)
        if isinstance(owner, ast.Attribute):
            if not used(call, [constructed(call)]):
                return False
            continue
        name = (owner.targets[0].id if isinstance(owner, ast.Assign)
                and owner in holders.get(getattr(owner.targets[0], 'id', None), []) else None)
        # Every binding of the name must be a top-level `name = Path(...)`, so each load holds one of those paths.
        assignments = holders.get(name, [])
        if (not name or bound.count(name) != len(assignments)
                or not all(isinstance(assignment.value.func, (ast.Name, ast.Attribute))
                           and getattr(assignment.value.func, 'id', getattr(assignment.value.func, 'attr', None)) == 'Path'
                           for assignment in assignments)):
            return False
        paths = [constructed(assignment.value) for assignment in assignments]
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


def check_only_shell(command):
    """Whether every command only reads or syntax-checks files, so none runs a file the heredoc wrote.

    A script can build a push at run time, so a command that runs code (a test runner, `bash f.sh`) never follows."""
    segments = [part.strip() for part in re.split(r'&&|;|\n', command) if part.strip()]
    return read_only_shell(command) or all(
        read_only_shell(segment) or re.fullmatch(r'(?:ba|z)?sh +-n +[\w./][\w./-]*', segment) for segment in segments)


# Attributes a proof script reads besides `INERT_ATTRIBUTES`; none reaches a module such as `pathlib.os`.
TEXT_SCRIPT_ATTRIBUTES = INERT_ATTRIBUTES | {'read_bytes', 'chmod', 'parse', 'literal_eval', 'walk', 'body',
                                             'targets', 'id', 'value', 'Assign', 'Name'}


def starts_no_process(tree):
    """Whether a Python script can start no process and calls no `git` helper, so its `git(` text is only text.

    Names, imports and attributes come from allowlists, because `pathlib.os` or `Path.parser.os` reach `os`.
    Every write needs literal `writable` paths, because Python imports a module the script wrote (`difflib.py`)."""
    stores = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)]
    stores += [node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)]
    stores += [name for node in ast.walk(tree) if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names]
    stores += [node.name for node in ast.walk(tree) if isinstance(
        node, (ast.ExceptHandler, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name]
    stores += [(alias.asname or alias.name).split('.')[0] for node in ast.walk(tree)
               if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names]
    top = {}
    for statement in tree.body:
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)):
            top.setdefault(statement.targets[0].id, []).append(statement.value)

    def paths(node, seen=()):
        """Every literal path `node` may hold (`'a'`, `Path('a')`, `base / 'b'`), or None."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'Path' and len(node.args) == 1
                and not node.keywords):
            return paths(node.args[0], seen)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = paths(node.left, seen), paths(node.right, seen)
            return [f'{a}/{b}' for a in left for b in right] if left and right else None
        if (isinstance(node, ast.Name) and node.id not in seen and node.id in top
                and stores.count(node.id) == len(top[node.id])):
            found = [paths(value, (*seen, node.id)) for value in top[node.id]]
            return [path for group in found for path in group] if all(found) else None
        return None

    def reads(call, index):
        modes = [*call.args[index:index + 1], *(keyword.value for keyword in call.keywords if keyword.arg == 'mode')]
        return all(isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) <= set('rbt')
                   for mode in modes)

    calls = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        # An alias (`o = open`, `w = p.write_text`) writes through a name the checks below never see.
        if (getattr(node, 'id', None) == 'open' or getattr(node, 'attr', None) in {'open', 'write_text', 'replace'}) \
                and id(node) not in calls:
            return False
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None)
            attribute = node.func.attr if isinstance(node.func, ast.Attribute) else None
            # A starred or `**` argument hides the path and the mode.
            if (name == 'open' or attribute in {'open', 'write_text', 'replace'}) and (
                    any(isinstance(argument, ast.Starred) for argument in node.args)
                    or any(keyword.arg is None for keyword in node.keywords)):
                return False
            # `Path.replace(target)` renames a file onto `target`; `str.replace` takes two arguments.
            renamed = attribute == 'replace' and (len(node.args) + len(node.keywords) == 1)
            target = (node.args[0] if name == 'open' and node.args and not reads(node, 1) else
                      node.func.value if attribute == 'write_text' or attribute == 'open' and not reads(node, 0)
                      else (node.args or [keyword.value for keyword in node.keywords])[0] if renamed else None)
            if name == 'open' and not node.args or target is not None and not all(
                    writable(path) for path in paths(target) or [None]):
                return False
        if isinstance(node, ast.Import) and any(alias.name not in {*INERT_MEMBERS, 'ast'} for alias in node.names):
            return False
        if isinstance(node, ast.ImportFrom) and (node.level or node.module not in INERT_MEMBERS or any(
                alias.name not in INERT_MEMBERS[node.module] for alias in node.names)):
            return False
        if isinstance(node, ast.Name) and (node.id in REFLECTION or node.id.startswith('__') or node.id == 'git'):
            return False
        if isinstance(node, ast.Attribute) and node.attr not in TEXT_SCRIPT_ATTRIBUTES:
            return False
    return True


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
            # The written files exist only after the script, so only a later or a background command can run them.
            if check_only_shell(''.join(lines[end + 1:])) and not re.search(r'(?<!&)&(?![&>])', match['lead']):
                return False
            if not inert_python(body):
                return True
            # An inert script writes only through `open` with a write mode or a `Path` write method.
            return any(isinstance(node, ast.Attribute) and node.attr in {'write_text', 'unlink'}
                       or isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'open' and not all(
                           isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) <= set('rbt')
                           for mode in [*node.args[1:2], *(k.value for k in node.keywords if k.arg == 'mode')])
                       for node in ast.walk(ast.parse(body)))
    return False


PYTHON_STDIN = (r"(?:python|python3(?:\.\d+)?)(?: +-I)? +- +<<(?P<tabs>-?)[ \t]*"
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
    match = PYTHON_HEREDOC.fullmatch(lines[0]) if lines else None
    if not match:
        return command
    delimiter = shlex.split(match['delimiter'])[0]
    for end in range(1, len(lines)):
        candidate = lines[end].lstrip('\t') if match['tabs'] else lines[end]
        if candidate.removesuffix('\n') == delimiter:
            remainder = ''.join(lines[end + 1:])
            body = ''.join(line.lstrip('\t') if match['tabs'] else line for line in lines[1:end])
            # A quoted delimiter keeps the body away from the shell, so an inert script is only file text.
            # Only a `cd` or `date` may lead it and only a read-only remainder may follow it, because another command
            # could run the file it writes.
            if (re.fullmatch(rf'[ \t]*{PYTHON_LEAD}', match['lead']) and read_only_shell(remainder)
                    and match['delimiter'][0] in '\'"\\' and inert_python(body)):
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
            scanned = ''.join(body_lines)
            # A script that can start no process runs `git(` only as a call, so in its strings `git("status")` is text.
            # A script that can start one may hand zsh `git(|) push`, a glob that runs git.
            if starts_no_process(tree):
                scanned = re.sub(r'\bgit\(', 'git_(', scanned)
            if shell_git_push(scanned):
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


def git_push(command):
    reduced = literal_variables(literal_ps_awk_filter(python_heredoc_shell(cat_heredoc_data(command))))
    try:
        shlex.split(reduced.replace('\\\n', ''), comments=False, posix=True)
    except ValueError:
        # A reduction that leaves unbalanced quotes misread the shell, so the original command is scanned.
        reduced = command
    return runs_heredoc_output(command) or shell_git_push(reduced)


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


def shell_git_push(command):
    """Scan Git commands and shell-wrapper strings without regex backtracking."""
    values = {'-C', '-c', '--git-dir', '--work-tree', '--namespace',
              '--config-env', '--super-prefix', '--attr-source', '--shallow-file'}
    folders = {'-C', '--git-dir', '--work-tree'}
    pending = [command]
    while pending:
        text = pending.pop().replace('\\' + '\n', '')
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
                return True
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
        plain = plain and all(part.split()[0] in READ_ONLY_STARTS
                              for part in re.split(r'[;&|\n]+', words) if part.strip())
        if plain:
            spelled = re.search(r'(?<![A-Za-z0-9_])(?:push|send-pack)(?![A-Za-z0-9_])',
                                re.sub(r'(?<!\w)push(?:ed|es)(?=\s*:)', '', words))
        else:
            spelled = any(word in re.sub(r'(?<!\w)push(?:ed|es)(?=\s*:)', '', token).translate(expansion)
                          for token in tokens for word in ('push', 'send-pack'))
        if any(set(token) & set('$`*?[{') for token in tokens) and spelled:
            return True
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
                return True
            # An alias that runs a shell command (`!sh`) or a remote writer turns any subcommand into a push.
            if expect_subcommand and (
                    value_option == '-c' and alias_runs_writer(token)
                    or token.startswith('-c') and token != '-c' and alias_runs_writer(token[2:])
                    or value_option == '--config-env' and token.lower().startswith('alias.')
                    or token.lower().startswith('--config-env=alias.')):
                return True
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
                    return True
                # Options and other non-word tokens stay pending; a plain word is the subcommand.
                if re.fullmatch(r'[a-z][a-z0-9-]*', token):
                    expect_subcommand = False
            # `git-push` runs a push. A glob or an expansion in the command word (`git-pu*`, `$G-push`) can match it;
            # in an argument it is only a file name (`ls g*`).
            base = os.path.basename(re.sub(r'\$(?:[A-Za-z_]\w*|\{[^}]*\})', '*', token))
            if base in REMOTE_WRITER_NAMES or command_word and set(base) & set('*?[') and base.strip('*?') and any(
                    fnmatch.fnmatchcase(name, base) for name in REMOTE_WRITER_NAMES):
                return True
            if command_word and base in WRAPPERS:
                wrapper, wrapper_value = base, False
            # Git reads `GIT_CONFIG_*` from the environment, so a value that spells a remote writer can alias one,
            # and a key or parameter list that defines an alias can, whatever the value.
            if re.match(r'GIT_\w*=', token) and any(word in token for word in REMOTE_WRITERS):
                return True
            if (re.match(r'GIT_CONFIG_(?:KEY_\w*|PARAMETERS)=', token)
                    and (re.search(r'alias', token, re.I) or set(token) & set('$`\\'))):
                return True
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
        # Publish words inside an inert heredoc are file text; every executable part keeps the scan.
        file_text_removed = python_heredoc_shell(cat_heredoc_data(tin.get('command', '')), inert_only=True)
        if tool == 'Bash' and (git_push(tin.get('command', ''))
                               or WRITER_BASH.search(file_text_removed)):
            deny('Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; '
                 'commit grants permit local base-branch merges into their own lane branch. '
                 'Return this step to your driver; the driver may run it.')
        if tool == 'Bash':
            reason = writer_gh_denial(file_text_removed)
            if reason:
                deny(reason)
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
        result = {'id': str(uuid.uuid4())}
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
            regular = i < end and row[1] not in ('run-start', 'run-end', 'account-result')
            if ((explicit or regular) and row[2] == agent and row[4] != 'owed'
                    and int(row[0]) >= int(epoch) - 5 and json.dumps(identity) not in used):
                receipts[result_id] = identity
                break
        else:
            raise ValueError(f'Review results have no unused ledger row: {agent}; pending result {result["id"]}')


def stop(data):
    path = owed_file(data)
    if data.get('stop_hook_active'):
        return
    try:
        try:
            path.stat()
        except FileNotFoundError:
            return
        with path.open('r+') as pending:
            fcntl.flock(pending, fcntl.LOCK_EX)
            owed = [line.split('\t') for line in pending.read().splitlines() if line]
            if not owed:
                return
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
                with tempfile.NamedTemporaryFile(mode='w', dir=STATE, prefix='accounted.',
                                                 delete=False) as saved:
                    json.dump(receipts, saved)
                    saved.flush()
                    os.fsync(saved.fileno())
                os.replace(saved.name, receipt_path)
                directory = os.open(STATE, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            # Clear only after every result has a successful accounting row.
            # Keep this inode so concurrent SubagentStop writers share the lock.
            pending.seek(0)
            pending.truncate()
    except Exception as exc:
        print(json.dumps({'decision': 'block', 'reason':
              f'Pending review evidence retained at {path}: {exc}. '
              'Resolve ledger access (set SHIP_LEDGER_DIR to an absolute permitted directory if needed). '
              'Record each result with `ledger.py append <step> <agent> <sha> <verdict> [note]` in its open run. '
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
