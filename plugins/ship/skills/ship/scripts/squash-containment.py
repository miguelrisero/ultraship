#!/usr/bin/env python3
"""Verify a PR-linked squash with exact file diffs and a clean-merge tree."""
import json
import os
import re
import subprocess
import sys

DIFF = ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
        '--binary', '--full-index', '--ignore-submodules=none']


def run(*args, input=None):
    return subprocess.run(args, input=input, capture_output=True, check=True).stdout


def git(*args):
    return run('git', '--literal-pathspecs', *args)


def paths(revisions):
    return set(git(*DIFF, '--name-only', '-z', *revisions, '--').split(b'\0')) - {b''}


def file_diff(revisions, path):
    path = os.fsdecode(path)
    raw = git('diff', '--no-ext-diff', '--no-renames', '--ignore-submodules=none', '--raw', '-z',
              *revisions, '--', path).split(b'\0')
    fields = raw[0].split()
    if len(raw) != 3 or raw[1] != os.fsencode(path) or len(fields) != 5:
        raise ValueError(f'missing or ambiguous file modes for {path!r}')
    patch = git(*DIFF, *revisions, '--', path)
    if not patch:
        raise ValueError(f'empty file diff for {path!r}')
    lines = []
    header = True
    for line in patch.split(b'\n'):
        if line.startswith((b'@@', b'GIT binary patch')):
            header = False
        if header and line.startswith(b'index '):
            continue
        lines.append(re.sub(rb'^@@ -[0-9]+(?:,[0-9]+)? \+[0-9]+(?:,[0-9]+)? @@', b'@@ @@', line))
    return fields[:2], b'\n'.join(lines)


def main(args):
    if len(args) != 4:
        print('usage: squash-containment.py <pr-url> <base> <author-head> <squash>', file=sys.stderr)
        return 2
    pr, *revisions = args
    try:
        if any(char.isspace() for char in pr):
            raise ValueError('PR URL contains whitespace')
        base, author, squash = [
            git('rev-parse', '--verify', '--end-of-options', f'{sha}^{{commit}}').decode().strip()
            for sha in revisions
        ]
        info = json.loads(run('gh', 'pr', 'view', pr, '--json', 'state,mergeCommit'))
        if not isinstance(info, dict) or info.get('state') != 'MERGED':
            raise ValueError('PR state must be MERGED')
        merge = info.get('mergeCommit')
        if not isinstance(merge, dict) or merge.get('oid') != squash:
            raise ValueError('PR mergeCommit does not match squash commit')
        parents = git('rev-list', '--parents', '-n', '1', squash).decode().split()[1:]
        if len(parents) != 1:
            raise ValueError('squash commit must have exactly one parent')
        parent, = parents
        git('merge-base', '--is-ancestor', base, squash)
        left, right = [f'{base}...{author}'], [parent, squash]
        changed = paths(left)
        if not changed or changed != paths(right):
            raise ValueError('changed file sets must be equal and non-empty')
        for path in sorted(changed):
            if file_diff(left, path) != file_diff(right, path):
                raise ValueError(f'file diffs differ for {os.fsdecode(path)!r}')
        tree = git('merge-tree', '--write-tree', '--no-messages', parent, author).partition(b'\n')[0]
        if tree != git('rev-parse', f'{squash}^{{tree}}').strip():
            raise ValueError('squash tree differs from the clean merge of the author head')
    except subprocess.CalledProcessError as exc:
        print(f'REFUSE {exc.cmd[0]} command failed (exit {exc.returncode})')
        return 1
    except (OSError, ValueError) as exc:
        print(f'REFUSE {str(exc)!r}')
        return 1
    print(f'PASS pr={pr} base={base} author_head={author} squash={squash} parent={parent} files={len(changed)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
