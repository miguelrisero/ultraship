#!/usr/bin/env python3
"""Ultraship hooks. Usage: ultraship.py pre|subagent-stop|stop|compact < hook-input.json"""
import ast
import fcntl
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
HARNESS_PATH = re.compile(r'(^|/)\.claude/settings[^/]*\.json$')
LEDGER_ROLES = re.compile(r'^(ship:)?(reviewer|triage|verifier)--')


def python_heredoc_shell(command):
    # Only a literal Python stdin command establishes a non-shell script body.
    # Shell interpreters, ambiguous headers, and expandable bodies keep the full scan.
    header = re.compile(r"^[ \t]*(?:python|python3(?:\.\d+)?) +- +<<(-?)[ \t]*"
                        r"('[_a-zA-Z0-9]+'|\"[_a-zA-Z0-9]+\"|\\[_a-zA-Z0-9]+|[_a-zA-Z0-9]+)"
                        r"[ \t]*\n$")
    lines = command.splitlines(keepends=True)
    match = header.fullmatch(lines[0]) if lines else None
    if not match:
        return command
    delimiter = shlex.split(match[2])[0]
    for end in range(1, len(lines)):
        candidate = lines[end].lstrip('\t') if match[1] else lines[end]
        if candidate.removesuffix('\n') == delimiter:
            body = ''.join(line.lstrip('\t') if match[1] else line for line in lines[1:end])
            if 'push' in body or '\\\n' in body:
                return command
            if any(c in body for c in '$`{}'):
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
            return lines[0] + ''.join(lines[end + 1:])
    return command


def literal_ps_awk_filter(command):
    # Only a complete process-list filter with a bare print action supplies inert awk data.
    pipeline = re.fullmatch(r"[ \t]*ps[ \t]+-eo[ \t]+pid,args[ \t]*\|[ \t]*awk[ \t]+'([^'\r\n]*)'[ \t]*", command)
    if not pipeline:
        return command
    comparison = r'\$[0-9]+[ \t]*(?:==|!=|!~|~|>=|<=|>|<)[ \t]*(?:"[\w ./-]*"|/[\w .^$*+-]+/|[0-9]+)'
    expression = rf'[() \t]*{comparison}(?:[() \t]*(?:&&|\|\|)[() \t]*{comparison})*[() \t]*\{{[ \t]*print[ \t]*\}}[ \t]*'
    if 'push' in pipeline[1] or not re.fullmatch(expression, pipeline[1]):
        return command
    return command[:pipeline.start(1)] + 'awk_filter_data' + command[pipeline.end(1):]


def git_push(command):
    return shell_git_push(literal_ps_awk_filter(python_heredoc_shell(command)))


# One left-to-right scan: a single-quoted span, a standalone `"$NAME"` word, or another double-quoted span.
SHELL_QUOTES = re.compile(r'''(?<!\$)'[^']*'|(?<![^\s;&|()])"\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})"(?![^\s;&|()])|"[^"]*"''')


def quoted_variable(command, token):
    """Whether `command` references the variable `token` names only as standalone `"$NAME"` words.

    Other quotes must be inert literals, and the command must hold no escape, comment, heredoc or backtick, so shlex
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
    return (name in found and re.search(r'[\\`\'"#]|<<', rest) is None
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
            if re.search(r'\bgit\b', text) and re.search(r'\bpush\b', text):
                return True
            continue
        # An expansion or glob can assemble the executable (`$'git' $'push'`), so with any
        # `push` spelling it denies. Exclude only the literal receipt key `pushed:` before
        # normalization; brace lists must retain the conservative substring check.
        # A rare false denial remains, for example `echo $X; git stash push`.
        expansion = str.maketrans('', '', '$`*?[]{},')
        if (any(set(token) & set('$`*?[{') for token in tokens)
                and any('push' in re.sub(r'(?<!\w)pushed(?=\s*:)', '', token).translate(expansion)
                        for token in tokens)):
            return True
        expect_subcommand = skip_value = folder_value = False
        # Only a `git` that starts a command reads its own arguments; `eval git -C "$W"` or `watch git ...`
        # re-reads them, where a quoted value can split again.
        command_start = git_command = True
        for token in tokens:
            if any(char.isspace() for char in token):
                pending.append(token)
            if folder_value and git_command and quoted_variable(command, token):
                skip_value = folder_value = False
                continue
            # An expansion, glob, quoting form, or redirection before the subcommand can hide it,
            # so it denies. Writers write `git -C . status 2>&1`, never `git $'push'` or `git {push,}`.
            if expect_subcommand and set(token) & set('(`<>${*?['):
                return True
            if skip_value:
                skip_value = folder_value = False
                continue
            if expect_subcommand:
                if token in values:
                    skip_value = True
                    folder_value = token in folders
                    continue
                if token == 'push':
                    return True
                # Options and other non-word tokens stay pending; a plain word is the subcommand.
                if re.fullmatch(r'[a-z][a-z0-9-]*', token):
                    expect_subcommand = False
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


def pre(data):
    tool, tin = data.get('tool_name', ''), data.get('tool_input') or {}
    if tool in ('Agent', 'Task') and str(tin.get('subagent_type', '')).startswith('ship:') and tin.get('model'):
        deny('ship agents pin their own model. Remove the `model` field and call the scoped agent '
             'or the next agent in its fallback chain.')
    if role(data, 'writer'):
        if tool in ('mcp__bettercoding__create_input', 'mcp__bettercoding__update_input',
                    'mcp__bettercoding__set_input_status'):
            deny('Writers return owner decision needs to the driver. Only the driver maintains Inputs.')
        if tool == 'Bash' and (git_push(tin.get('command', ''))
                               or WRITER_BASH.search(tin.get('command', ''))):
            deny('Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; '
                 'commit grants permit local base-branch merges into their own lane branch.')
        target = tin.get('file_path') or tin.get('notebook_path') or ''
        if tool in ('Edit', 'Write', 'NotebookEdit') and (
                HARNESS_PATH.search(target) or target.startswith(str(Path.home() / '.claude') + '/')):
            deny('Writers do not edit harness configuration.')
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
            raise ValueError(f'Review results have no unused ledger row: {agent}')


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
