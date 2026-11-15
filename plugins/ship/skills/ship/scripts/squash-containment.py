#!/usr/bin/env python3
"""Verify a PR-linked squash commit against each author-head file patch."""
import json
import os
import subprocess
import sys

DIFF = ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
        '--binary', '--full-index']


def run(*args, input=None):
    return subprocess.run(args, input=input, capture_output=True, check=True).stdout


def git(*args):
    return run('git', '--literal-pathspecs', *args)


def paths(revisions):
    return set(git(*DIFF, '--name-only', '-z', *revisions, '--').split(b'\0')) - {b''}


def patch_id(revisions, path):
    patch = git(*DIFF, *revisions, '--', os.fsdecode(path))
    rows = run('git', 'patch-id', '--stable', input=patch).splitlines()
    if len(rows) != 1 or len(rows[0].split()) != 2:
        raise ValueError(f'missing or ambiguous patch ID for {os.fsdecode(path)!r}')
    return rows[0].split()[0]


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
            if patch_id(left, path) != patch_id(right, path):
                raise ValueError(f'patch IDs differ for {os.fsdecode(path)!r}')
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
