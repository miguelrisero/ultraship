#!/usr/bin/env python3
"""Verify an externally approved check set on a positively unprotected branch."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qsl, quote, urlsplit


class Uncertain(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Uncertain(reason)


def positive(value):
    return type(value) is int and value > 0


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON field')
        result[key] = value
    return result


def decode(text):
    return json.loads(text, object_pairs_hook=object_pairs)


def command(args):
    return subprocess.run(args, capture_output=True, text=True)


def api(endpoint, absent=False):
    result = command(['gh', 'api', '--include', endpoint])
    header, separator, body = result.stdout.replace('\r\n', '\n').partition('\n\n')
    require(separator, 'API response lacks structured headers')
    lines = header.splitlines()
    status = re.fullmatch(r'HTTP/\S+ ([0-9]{3})(?: .*)?', lines[0])
    require(status, 'malformed API status')
    status = int(status[1])
    headers = {}
    for line in lines[1:]:
        key, colon, value = line.partition(':')
        require(colon and key.lower() not in headers, 'ambiguous API headers')
        headers[key.lower()] = value.strip()
    payload = decode(body)
    if absent:
        require(status == 404 and result.returncode != 0 and isinstance(payload, dict)
                and payload.get('message') == 'Branch not protected'
                and payload.get('status') == '404'
                and payload.get('documentation_url') ==
                'https://docs.github.com/rest/branches/branch-protection#get-branch-protection'
                and 'link' not in headers, 'classic protection is uncertain')
    else:
        require(status == 200 and result.returncode == 0, 'API read failed')
    return payload, headers


def one(endpoint, absent=False):
    payload, headers = api(endpoint, absent)
    require('link' not in headers, 'unexpected pagination on a single object')
    require(isinstance(payload, dict), 'API object missing')
    return payload


def collection(endpoint, field=None):
    initial = urlsplit('https://api.github.com/' + endpoint)
    initial_query = dict(parse_qsl(initial.query, strict_parsing=True))
    seen = set()
    rows = []
    total = None
    current = endpoint
    while True:
        identity = urlsplit(current if current.startswith('https://') else 'https://api.github.com/' + current)
        require(identity.geturl() not in seen, 'cyclic pagination')
        seen.add(identity.geturl())
        payload, headers = api(current)
        if field:
            require(isinstance(payload, dict) and type(payload.get('total_count')) is int
                    and payload['total_count'] >= 0 and isinstance(payload.get(field), list),
                    'malformed collection')
            require(total is None or total == payload['total_count'], 'collection changed while paginating')
            total = payload['total_count']
            rows.extend(payload[field])
        else:
            require(isinstance(payload, list), 'malformed branch rules')
            rows.extend(payload)
        links = {}
        if 'link' in headers:
            for part in headers['link'].split(','):
                match = re.fullmatch(r'\s*<([^<>]+)>;\s*rel="(next|prev|first|last)"\s*', part)
                require(match and match[2] not in links, 'malformed pagination link')
                target = urlsplit(match[1])
                query_pairs = parse_qsl(target.query, strict_parsing=True)
                query = dict(query_pairs)
                require(target.scheme == 'https' and target.netloc == 'api.github.com'
                        and not target.fragment and target.path == initial.path
                        and len(query_pairs) == len(query)
                        and query.get('page', '').isdigit() and int(query['page']) > 0
                        and {key: value for key, value in query.items() if key != 'page'} == initial_query,
                        'pagination escaped its origin or endpoint')
                links[match[2]] = target
        if 'next' not in links:
            break
        target = links['next']
        page = int(dict(parse_qsl(identity.query)).get('page', '1'))
        require(int(dict(parse_qsl(target.query))['page']) == page + 1, 'pagination is incomplete')
        current = target.geturl()
    require(total is None or len(rows) == total, 'collection is incomplete')
    return rows


def policy_input(args):
    require(args, 'PR argument missing')
    pr = args[0]
    index = 1
    bounds = []
    while index < len(args) and not args[index].startswith('--'):
        require(len(bounds) < 2 and args[index].isdigit(), 'invalid polling bounds')
        bounds.append(int(args[index]))
        index += 1
    options = {}
    while index < len(args):
        require(index + 1 < len(args) and args[index] in ('--named-checks', '--approved-policy-sha256')
                and args[index] not in options, 'invalid named-check option')
        options[args[index]] = args[index + 1]
        index += 2
    require(set(options) == {'--named-checks', '--approved-policy-sha256'}, 'explicit policy and approved digest required')
    require(not os.environ.get('WATCH_CHECKS_IGNORE'), 'ignore settings are forbidden for named checks')
    require(Path(options['--named-checks']).is_absolute(), 'absolute external policy path required')
    path = Path(options['--named-checks']).resolve(strict=True)
    source = Path(__file__).resolve().parents[5]
    checkout = command(['git', 'rev-parse', '--show-toplevel'])
    roots = [source]
    if checkout.returncode == 0:
        roots.append(Path(checkout.stdout.strip()).resolve())
    require(all(not path.is_relative_to(root) for root in roots), 'policy must remain outside PR-controlled source')
    content = path.read_bytes()
    digest = options['--approved-policy-sha256']
    require(re.fullmatch(r'[0-9a-f]{64}', digest) and hashlib.sha256(content).hexdigest() == digest,
            'policy differs from externally approved digest')
    policy = decode(content)
    require(isinstance(policy, dict) and set(policy) ==
            {'schema_version', 'repository_id', 'pr', 'base', 'head', 'checks'}, 'unknown policy schema')
    require(type(policy['schema_version']) is int and policy['schema_version'] == 1,
            'unsupported schema version')
    require(positive(policy['repository_id']) and positive(policy['pr']), 'numeric repository and PR identity required')
    require(isinstance(policy['base'], str) and policy['base'] and not any(ord(c) < 32 for c in policy['base']),
            'base branch missing')
    require(isinstance(policy['head'], str) and re.fullmatch(r'[0-9a-f]{40}', policy['head']), 'full approved head required')
    require(isinstance(policy['checks'], list) and policy['checks'], 'nonempty approved check set required')
    seen = set()
    workflows = {}
    for item in policy['checks']:
        require(isinstance(item, dict) and set(item) ==
                {'workflow_id', 'workflow_path', 'workflow_blob_sha', 'check_name', 'app_id'}, 'unknown check schema')
        require(positive(item['workflow_id']) and positive(item['app_id']), 'numeric workflow and App identity required')
        require(isinstance(item['workflow_path'], str) and
                re.fullmatch(r'\.github/workflows/[^/]+\.ya?ml', item['workflow_path'])
                and not any(ord(c) < 32 for c in item['workflow_path']), 'invalid workflow path')
        require(isinstance(item['workflow_blob_sha'], str) and re.fullmatch(r'[0-9a-f]{40}', item['workflow_blob_sha']),
                'full workflow blob SHA required')
        require(isinstance(item['check_name'], str) and item['check_name']
                and not any(ord(c) < 32 for c in item['check_name']), 'exact check name required')
        identity = tuple(item[key] for key in sorted(item))
        require(identity not in seen, 'duplicate check tuple')
        seen.add(identity)
        workflow_identity = (item['workflow_path'], item['workflow_blob_sha'])
        require(item['workflow_id'] not in workflows or workflows[item['workflow_id']] == workflow_identity,
                'conflicting workflow identity')
        workflows[item['workflow_id']] = workflow_identity
    return pr, policy, digest, bounds[0] if bounds else 600, bounds[1] if len(bounds) == 2 else 5400


def pr_identity(pr, policy, expected_repo=None):
    result = command(['gh', 'pr', 'view', pr, '--json', 'url,number,headRefOid,baseRefName'])
    require(result.returncode == 0, 'PR lookup failed')
    value = decode(result.stdout)
    require(isinstance(value, dict), 'PR object missing')
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([0-9]+)', value.get('url', ''))
    require(match and int(match[2]) == policy['pr'] and type(value.get('number')) is int
            and value['number'] == policy['pr'] and value.get('baseRefName') == policy['base']
            and value.get('headRefOid') == policy['head'], 'PR differs from approved identity')
    repo = match[1]
    require(expected_repo is None or repo == expected_repo, 'PR repository changed')
    repository = one('repos/' + repo)
    require(type(repository.get('id')) is int and repository['id'] == policy['repository_id']
            and repository.get('full_name') == repo, 'repository differs from approved identity')
    return 'repos/' + repo


def protection(repo, policy):
    branch = repo + '/branches/' + quote(policy['base'], safe='')
    value = one(branch)
    require(value.get('name') == policy['base'] and value.get('protected') is False,
            'branch must explicitly report protected=false')
    one(branch + '/protection', absent=True)
    require(collection(repo + '/rules/branches/' + quote(policy['base'], safe='') + '?per_page=100') == [],
            'branch rules must be completely empty')


def run_matches(run, item, policy):
    require(isinstance(run, dict), 'malformed workflow run')
    if not (run.get('workflow_id') == item['workflow_id'] and run.get('path') == item['workflow_path']
            and run.get('event') == 'pull_request' and run.get('head_sha') == policy['head']
            and run.get('repository', {}).get('id') == policy['repository_id']
            and run.get('head_repository', {}).get('id') == policy['repository_id']):
        return False
    pulls = run.get('pull_requests')
    require(isinstance(pulls, list), 'PR association missing')
    return any(isinstance(pull, dict) and pull.get('number') == policy['pr']
               and pull.get('head', {}).get('sha') == policy['head']
               and pull.get('head', {}).get('repo', {}).get('id') == policy['repository_id']
               and pull.get('base', {}).get('ref') == policy['base']
               and pull.get('base', {}).get('repo', {}).get('id') == policy['repository_id'] for pull in pulls)


def latest(repo, item, policy):
    endpoint = (f'{repo}/actions/workflows/{item["workflow_id"]}/runs?event=pull_request'
                f'&head_sha={policy["head"]}&per_page=100')
    runs = collection(endpoint, 'workflow_runs')
    matches = [run for run in runs if run_matches(run, item, policy)]
    require(not runs or matches, 'runs lack approved PR association')
    if not matches:
        return None
    ids = set()
    for run in matches:
        require(positive(run.get('id')) and positive(run.get('run_number')) and positive(run.get('run_attempt')),
                'run identity missing')
        require(run['id'] not in ids, 'duplicate run mapping')
        ids.add(run['id'])
    numbers = [run['run_number'] for run in matches]
    require(len(numbers) == len(set(numbers)), 'ambiguous latest run')
    selected = max(matches, key=lambda run: run['run_number'])
    current = one(f'{repo}/actions/runs/{selected["id"]}')
    require(run_matches(current, item, policy) and current.get('id') == selected['id']
            and current.get('run_number') == selected['run_number']
            and current.get('run_attempt') == selected['run_attempt'], 'latest run or attempt changed')
    require(positive(current.get('check_suite_id')), 'check suite missing')
    return current


def state(value):
    status = value.get('status')
    conclusion = value.get('conclusion')
    if status == 'completed':
        require(conclusion in {'success', 'failure', 'cancelled', 'skipped', 'neutral', 'timed_out',
                               'action_required', 'stale', 'startup_failure'}, 'unknown conclusion')
        return 0 if conclusion == 'success' else 1
    require(status in {'queued', 'in_progress', 'waiting', 'requested', 'pending'} and conclusion is None,
            'unknown completion state')
    return 3


def evidence(repo, item, policy, run):
    outcome = state(run)
    if outcome:
        return outcome
    jobs = collection(f'{repo}/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs?per_page=100', 'jobs')
    require(all(isinstance(job, dict) for job in jobs), 'malformed job')
    matches = [job for job in jobs if job.get('name') == item['check_name']]
    require(len(matches) == 1, 'job mapping missing or ambiguous')
    job = matches[0]
    require(positive(job.get('id')) and job.get('run_id') == run['id']
            and job.get('run_attempt') == run['run_attempt'] and job.get('head_sha') == policy['head'],
            'job identity differs from run')
    url = job.get('check_run_url')
    require(isinstance(url, str), 'check run URL missing')
    match = re.fullmatch(r'https://api\.github\.com/' + re.escape(repo) + r'/check-runs/([1-9][0-9]*)', url)
    require(match, 'check run URL escaped repository or endpoint')
    check = one(f'{repo}/check-runs/{match[1]}')
    suite = one(f'{repo}/check-suites/{run["check_suite_id"]}')
    require(check.get('id') == int(match[1]) and check.get('name') == item['check_name']
            and check.get('head_sha') == policy['head'] and check.get('app', {}).get('id') == item['app_id']
            and check.get('check_suite', {}).get('id') == run['check_suite_id'], 'check run identity differs')
    require(suite.get('id') == run['check_suite_id'] and suite.get('head_sha') == policy['head']
            and suite.get('app', {}).get('id') == item['app_id'], 'check suite identity differs')
    outcomes = [state(job), state(check)]
    return 1 if 1 in outcomes else max(outcomes)


def main():
    pr, policy, digest, start_timeout, timeout = policy_input(sys.argv[1:])
    repo = pr_identity(pr, policy)
    protection(repo, policy)
    for item in policy['checks']:
        workflow = one(f'{repo}/actions/workflows/{item["workflow_id"]}')
        require(workflow.get('id') == item['workflow_id'] and workflow.get('path') == item['workflow_path']
                and workflow.get('state') == 'active', 'workflow identity differs')
        content = one(f'{repo}/contents/{quote(item["workflow_path"], safe="/")}?ref={policy["head"]}')
        require(content.get('type') == 'file' and content.get('path') == item['workflow_path']
                and content.get('sha') == item['workflow_blob_sha'], 'workflow content differs')
    waited = 0
    while True:
        observations = []
        outcomes = []
        for item in policy['checks']:
            run = latest(repo, item, policy)
            observations.append(run)
            outcomes.append(2 if run is None else evidence(repo, item, policy, run))
        if 1 in outcomes:
            print('named-checks: selected evidence concluded unsuccessfully')
            return 1
        if all(outcome == 0 for outcome in outcomes):
            protection(repo, policy)
            for item, run in zip(policy['checks'], observations):
                current = latest(repo, item, policy)
                require(current is not None and (current['id'], current['run_attempt']) ==
                        (run['id'], run['run_attempt']) and state(current) == 0,
                        'selected latest run or attempt changed before success')
            pr_identity(pr, policy, repo.removeprefix('repos/'))
            print(f'named-checks: success head={policy["head"]} policy_sha256={digest} '
                  + ' '.join(f'run={run["id"]} attempt={run["run_attempt"]}' for run in observations))
            return 0
        if all(outcome == 2 for outcome in outcomes) and waited >= start_timeout:
            print(f'named-checks: approved evidence has not started after {waited}s')
            return 2
        if waited >= timeout:
            print(f'named-checks: evidence remains pending after {waited}s')
            return 3
        subprocess.run(['sleep', '300'], check=True)
        waited += 300


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Uncertain, OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as error:
        print(f'named-checks: uncertainty: {error}')
        sys.exit(4)
