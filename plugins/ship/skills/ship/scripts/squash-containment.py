#!/usr/bin/env python3
"""Verify that a PR-linked squash matches the exact clean merge tree."""
import json
import subprocess
import sys


def run(*args):
    return subprocess.run(args, capture_output=True, check=True).stdout


def git(*args):
    return run('git', '--literal-pathspecs', *args)


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
        tree = git('merge-tree', '--write-tree', '--no-messages', parent, author).strip()
        if tree != git('rev-parse', f'{squash}^{{tree}}').strip():
            raise ValueError('squash tree differs from the clean merge of the author head')
        files = git('diff-tree', '-r', '--name-only', '-z', '--no-renames', '--no-relative',
                    '--ignore-submodules=none', parent, squash).count(b'\0')
    except subprocess.CalledProcessError as exc:
        print(f'REFUSE {exc.cmd[0]} command failed (exit {exc.returncode})')
        return 1
    except (OSError, ValueError) as exc:
        print(f'REFUSE {str(exc)!r}')
        return 1
    print(f'PASS pr={pr} base={base} author_head={author} squash={squash} parent={parent} files={files}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
