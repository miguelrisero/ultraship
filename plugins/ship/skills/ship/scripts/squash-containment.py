#!/usr/bin/env python3
"""Verify that a PR-linked squash matches the clean merge except for configured regenerated paths."""
import json
from os import fsdecode
from pathlib import Path
import re
import subprocess
import sys


def run(*args):
    return subprocess.run(args, capture_output=True, check=True).stdout


def git(*args):
    return run('git', '--literal-pathspecs', *args)


REPO = r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+'
DIFF_TREE = ('diff-tree', '--raw', '-r', '-z', '--no-renames', '--no-relative',
             '--ignore-submodules=none')
TREE_MISMATCH = 'squash tree differs from the clean merge of the author head'


def configured_paths(pr):
    match = re.fullmatch(rf'https://github\.com/({REPO})/pull/[0-9]+', pr)
    if not match:
        return []
    config_file = Path(__file__).with_name('squash-containment.json')
    config = json.loads(config_file.read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('squash-containment.json must contain an object')
    for repo, paths in config.items():
        if repo != repo.lower() or not re.fullmatch(REPO, repo) or not isinstance(paths, list) or any(
            not isinstance(path, str) or any(part in ('', '.', '..') for part in path.split('/'))
            or '\0' in path or any(char.isspace() for char in path) for path in paths
        ):
            raise ValueError('invalid regenerated paths in squash-containment.json')
    return config.get(match[1].lower(), [])


def regenerated_suffix(pr, parent, tree, squash_tree):
    allowed = configured_paths(pr)
    if not allowed:
        raise ValueError(TREE_MISMATCH)
    raw = git(*DIFF_TREE, tree, squash_tree)
    if not raw:
        raise ValueError(TREE_MISMATCH)
    fields = iter(raw[:-1].split(b'\0'))
    paths = []
    for header, name in zip(fields, fields, strict=True):
        old_mode, new_mode, _, _, status = header[1:].split()
        path = fsdecode(name)
        if path not in allowed or status != b'M' or old_mode != new_mode:
            raise ValueError(TREE_MISMATCH)
        paths.append(path)
    root = fsdecode(git('rev-parse', '--show-toplevel').removesuffix(b'\n'))
    for path in paths:
        if not git('-C', root, *DIFF_TREE, parent, tree, '--', path):
            raise ValueError(f'regenerated path {path} is unchanged in the clean merge')
    return ''.join(f' regenerated={path}' for path in paths)


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
        squash_tree = git('rev-parse', f'{squash}^{{tree}}').strip()
        regenerated = regenerated_suffix(pr, parent, tree, squash_tree) if tree != squash_tree else ''
        files = git('diff-tree', '-r', '--name-only', '-z', '--no-renames', '--no-relative',
                    '--ignore-submodules=none', parent, squash).count(b'\0')
    except subprocess.CalledProcessError as exc:
        print(f'REFUSE {exc.cmd[0]} command failed (exit {exc.returncode})')
        return 1
    except (OSError, ValueError) as exc:
        print(f'REFUSE {str(exc)!r}')
        return 1
    print(f'PASS pr={pr} base={base} author_head={author} squash={squash} parent={parent} files={files}{regenerated}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
