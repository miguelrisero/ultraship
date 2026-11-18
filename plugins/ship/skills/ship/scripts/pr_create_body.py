#!/usr/bin/env python3
"""Send a literal Markdown body to gh through one confined scratch descriptor."""
from contextlib import ExitStack
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


def open_scratch(stack, cwd):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def keep(fd):
        stack.callback(os.close, fd)
        return fd

    directories = [keep(os.open('/', flags))]
    for part in cwd.parts[1:]:
        directories.append(keep(os.open(part, flags, dir_fd=directories[-1])))
    if not os.path.samestat(os.fstat(directories[-1]), os.stat('.')):
        raise ValueError('the working directory changed')
    for directory in reversed(directories):
        try:
            scratch = keep(os.open('.scratch', flags, dir_fd=directory))
        except FileNotFoundError:
            continue
        status = os.fstat(scratch)
        if status.st_uid != os.getuid() or status.st_mode & 0o022:
            raise ValueError('the scratch directory requires owner control')
        return scratch
    raise ValueError('the working directory requires a caller scratch directory')


def create_pr(name, repo, head, title, body):
    if not re.fullmatch(r'pr-body-[A-Za-z0-9_-]+\.md', name):
        raise ValueError('invalid scratch body name')
    if (not re.fullmatch(r'github\.com/(?:bettergroupinc|miguelrisero)/[A-Za-z0-9_.-]+', repo)
            or repo.rsplit('/', 1)[1] in {'.', '..'}):
        raise ValueError('invalid repository identity')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', head):
        raise ValueError('invalid head branch')
    if not re.fullmatch(r'[^\x00-\x1f\x7f]+', title):
        raise ValueError('invalid title')
    with ExitStack() as stack:
        scratch = open_scratch(stack, Path.cwd())
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=scratch)
        with os.fdopen(fd, 'w+b') as handle:
            status = os.fstat(fd)
            if (not stat.S_ISREG(status.st_mode) or status.st_uid != os.getuid()
                    or status.st_mode & 0o077 or status.st_nlink != 1 or status.st_size != 0):
                raise ValueError('the scratch body requires a fresh private file')
            # Drop the name before copying Markdown. The open descriptor keeps the file alive.
            os.unlink(name, dir_fd=scratch)
            if os.fstat(fd).st_nlink != 0:
                raise ValueError('the scratch body acquired another link')
            shutil.copyfileobj(body, handle)
            handle.flush()
            handle.seek(0)
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('GIT_') and key not in ('GH_REPO', 'GH_HOST')}
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
            env['GH_PROMPT_DISABLED'] = '1'
            return subprocess.run(['gh', 'pr', 'create', '--repo', repo, '--head', head, '--title', title,
                                   '--body-file', '-'], stdin=handle, env=env).returncode


def main():
    if len(sys.argv) != 5:
        print('usage: pr_create_body.py <fresh body name> <repository> <head branch> <title>', file=sys.stderr)
        return 2
    try:
        return create_pr(*sys.argv[1:], sys.stdin.buffer)
    except (OSError, ValueError):
        print('refused: PR body helper could not safely prepare or start the PR command.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
