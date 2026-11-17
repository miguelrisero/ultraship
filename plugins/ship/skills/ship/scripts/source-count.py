#!/usr/bin/env -S python3 -I
"""Count overlapping literal bytes in a regular file at a frozen Git commit."""
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import subprocess
import sys

PROTECTED_ROW = r'(?<![\w.-])tests/mutation(/|$)'


class Refused(Exception):
    pass


def git(repo, *args):
    try:
        return subprocess.run(
            ['git', '--no-replace-objects', '--literal-pathspecs', '-C', repo, *args],
            stdin=subprocess.DEVNULL, capture_output=True, check=True,
            env={key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        raise Refused('git') from None


def count(args):
    options = {'--repo', '--commit', '--subject', '--literal'}
    if len(args) != 8 or set(args[::2]) != options:
        raise Refused('usage')
    values = dict(zip(args[::2], args[1::2]))
    repo, commit, subject = (values[key] for key in ('--repo', '--commit', '--subject'))
    try:
        needle = os.fsencode(values['--literal'])
        needle.decode('utf-8', errors='strict')
    except UnicodeError:
        raise Refused('literal') from None
    if not needle:
        raise Refused('literal')
    path = PurePosixPath(subject)
    if (not subject or path.is_absolute() or path.as_posix() != subject
            or any(part in ('', '.', '..') for part in subject.split('/'))):
        raise Refused('subject')
    if re.search(PROTECTED_ROW, subject, re.I):
        raise Refused('protected-subject')
    parts = [part.lower() for part in path.parts]
    name = parts[-1]
    if '.git' in parts or name == '.env' or name.startswith('.env.') or name.endswith(('.pem', '.key')):
        raise Refused('sensitive-subject')
    try:
        if (not os.path.isabs(repo) or os.path.realpath(repo) != repo or not os.path.isdir(repo)
                or git(repo, 'rev-parse', '--show-toplevel') != os.fsencode(repo) + b'\n'):
            raise Refused('repo')
    except (OSError, ValueError, Refused):
        raise Refused('repo') from None
    if not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise Refused('commit')
    try:
        if git(repo, 'rev-parse', '--verify', '--end-of-options', commit + '^{commit}') != commit.encode() + b'\n':
            raise Refused('commit')
    except Refused:
        raise Refused('commit') from None
    records = git(repo, 'ls-tree', '-z', commit, '--', subject).split(b'\0')
    if len(records) != 2 or records[-1] != b'':
        raise Refused('not-regular-file')
    metadata, separator, entry_path = records[0].partition(b'\t')
    fields = metadata.split(b' ')
    if (not separator or entry_path != os.fsencode(subject) or len(fields) != 3
            or fields[0] not in (b'100644', b'100755') or fields[1] != b'blob'):
        raise Refused('not-regular-file')
    blob = fields[2].decode('ascii')
    content = git(repo, 'cat-file', 'blob', blob)
    total, index = 0, content.find(needle)
    while index != -1:
        total += 1
        index = content.find(needle, index + 1)
    return {'blob': blob, 'commit': commit, 'count': total, 'literal_bytes': len(needle),
            'literal_sha256': hashlib.sha256(needle).hexdigest(), 'repo': repo,
            'result': 'PASS', 'subject': subject}


def main(args):
    try:
        result = count(args)
    except Refused as exc:
        result = {'error': str(exc), 'result': 'REFUSED'}
    except Exception:
        result = {'error': 'internal', 'result': 'REFUSED'}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['result'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
