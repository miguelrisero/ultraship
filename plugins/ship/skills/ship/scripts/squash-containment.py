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


def valid_path(path):
    return (isinstance(path, str) and all(part not in ('', '.', '..') for part in path.split('/'))
            and '\0' not in path and not any(char.isspace() for char in path))


def configured_rule(pr):
    match = re.fullmatch(rf'https://github\.com/({REPO})/pull/[0-9]+', pr)
    if not match:
        raise ValueError(TREE_MISMATCH)
    config_file = Path(__file__).with_name('squash-containment.json')
    config = json.loads(config_file.read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('squash-containment.json must contain an object')
    for repo, rule in config.items():
        if (repo != repo.lower() or not re.fullmatch(REPO, repo)
                or not isinstance(rule, dict) or rule.keys() != {'paths', 'workflow', 'job', 'step'}
                or not isinstance(rule['paths'], list) or not all(map(valid_path, rule['paths']))
                or not valid_path(rule['workflow'])
                or not all(isinstance(rule[key], str) and rule[key].strip() for key in ('job', 'step'))):
            raise ValueError('invalid regenerated path rule in squash-containment.json')
    repo = match[1].lower()
    return repo, config.get(repo)


def regenerated_paths(allowed, parent, tree, squash_tree):
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
        if path not in allowed or status != b'M' or old_mode != b'100644' or new_mode != b'100644':
            raise ValueError(TREE_MISMATCH)
        paths.append(path)
    root = fsdecode(git('rev-parse', '--show-toplevel').removesuffix(b'\n'))
    for path in paths:
        if not git('-C', root, *DIFF_TREE, parent, tree, '--', path):
            raise ValueError(f'regenerated path {path} is unchanged in the clean merge')
    return paths


def github_object(endpoint, *fields):
    data = json.loads(run('gh', 'api', '-X', 'GET', endpoint, '--hostname', 'github.com', *fields))
    if not isinstance(data, dict):
        raise ValueError('expected a GitHub API object')
    return data


def positive_int(value):
    return type(value) is int and value > 0


def drift_job(repo, squash, rule):
    try:
        checks = github_object(
            f'repos/{repo}/commits/{squash}/check-runs',
            '-f', f'check_name={rule["job"]}', '-F', 'app_id=15368',
            '-f', 'filter=latest', '-F', 'per_page=100',
        )
        check_runs = checks['check_runs']
        total = checks['total_count']
        if not isinstance(check_runs, list) or type(total) is not int or total != len(check_runs):
            raise ValueError('incomplete check run list')
        bound = []
        for check in check_runs:
            job_id = check['id']
            if not positive_int(job_id):
                raise ValueError('invalid check run ID')
            job = github_object(f'repos/{repo}/actions/jobs/{job_id}')
            run_id = job['run_id']
            if job['id'] != job_id or not positive_int(run_id):
                raise ValueError('invalid Actions job identity')
            workflow_run = github_object(f'repos/{repo}/actions/runs/{run_id}')
            attempt = job.get('run_attempt')
            run_attempt = workflow_run.get('run_attempt')
            if (workflow_run.get('path') == rule['workflow'] and workflow_run.get('event') == 'push'
                    and job.get('head_sha') == workflow_run.get('head_sha') == squash
                    and positive_int(attempt) and positive_int(run_attempt) and attempt == run_attempt):
                bound.append(job)
        if len(bound) != 1:
            raise ValueError('expected one bound Actions job')
        job, = bound
        if job.get('status') != 'completed' or job.get('conclusion') != 'success':
            raise ValueError('Actions job did not complete successfully')
        steps = job['steps']
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            raise ValueError('invalid Actions job steps')
        matches = [step for step in steps if step.get('name') == rule['step']]
        if len(matches) != 1 or matches[0].get('conclusion') != 'success':
            raise ValueError('expected one successful Actions step')
        return job['id']
    except (subprocess.CalledProcessError, OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError('drift check evidence is missing, invalid or unsuccessful') from exc


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
        parents = git('rev-list', '--parents', '-n', '1', squash).decode().split()[1:]
        if len(parents) != 1:
            raise ValueError('squash commit must have exactly one parent')
        parent, = parents
        git('merge-base', '--is-ancestor', base, squash)
        tree = git('merge-tree', '--write-tree', '--no-messages', parent, author).strip()
        squash_tree = git('rev-parse', f'{squash}^{{tree}}').strip()
        paths = []
        suffix = ''
        if tree != squash_tree:
            repo, rule = configured_rule(pr)
            paths = regenerated_paths(rule['paths'] if rule else [], parent, tree, squash_tree)
        files = git('diff-tree', '-r', '--name-only', '-z', '--no-renames', '--no-relative',
                    '--ignore-submodules=none', parent, squash).count(b'\0')
        info = json.loads(run('gh', 'pr', 'view', pr, '--json', 'state,mergeCommit'))
        if not isinstance(info, dict) or info.get('state') != 'MERGED':
            raise ValueError('PR state must be MERGED')
        merge = info.get('mergeCommit')
        if not isinstance(merge, dict) or merge.get('oid') != squash:
            raise ValueError('PR mergeCommit does not match squash commit')
        if paths:
            suffix = f' drift_job={drift_job(repo, squash, rule)}'
            suffix += ''.join(f' regenerated={path}' for path in paths)
    except subprocess.CalledProcessError as exc:
        print(f'REFUSE {exc.cmd[0]} command failed (exit {exc.returncode})')
        return 1
    except (OSError, ValueError) as exc:
        print(f'REFUSE {str(exc)!r}')
        return 1
    print(f'PASS pr={pr} base={base} author_head={author} squash={squash} parent={parent} files={files}{suffix}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
