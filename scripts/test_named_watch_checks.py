"""Exercise the explicit named-check gate through its public shell entry point.

Policy tests protect external approval and fail on payload-trusted approval.
Evidence tests protect complete identity and fail on successful unrelated checks.
Selection tests protect freshness and fail on stale-success fallback.
Recheck tests protect receipt validity and fail on head, protection or rerun races.
The required-context tests cannot exercise this opt-in contract. Stubbed GitHub
responses control each observation; a stubbed sleep advances only the poll count.
No production-only testing seam or live GitHub request is used.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / 'plugins/ship/skills/ship/scripts/watch-checks.sh'
HEAD = 'a' * 40
BLOB = 'b' * 40
REPO = 'repos/example/repo'
BRANCH = f'{REPO}/branches/main'
RULES = f'{REPO}/rules/branches/main?per_page=100'
RUNS = f'{REPO}/actions/workflows/23/runs?event=pull_request&head_sha={HEAD}&per_page=100'
RUN = f'{REPO}/actions/runs/41'
JOBS = f'{RUN}/attempts/2/jobs?per_page=100'
CHECK = f'{REPO}/check-runs/61'
SUITE = f'{REPO}/check-suites/51'
WORKFLOW = f'{REPO}/actions/workflows/23'
CONTENT = f'{REPO}/contents/.github/workflows/validate.yml?ref={HEAD}'


def response(body, status=200, link=None):
    return {'status': status, 'body': body, 'link': link}


def fixture():
    policy = {
        'schema_version': 1, 'repository_id': 17, 'pr': 7, 'base': 'main',
        'head': HEAD, 'checks': [{
            'workflow_id': 23, 'workflow_path': '.github/workflows/validate.yml',
            'workflow_blob_sha': BLOB, 'check_name': 'validate', 'app_id': 31,
        }],
    }
    pr = {'url': 'https://github.com/example/repo/pull/7', 'number': 7,
          'headRefOid': HEAD, 'baseRefName': 'main'}
    run = {
        'id': 41, 'workflow_id': 23, 'path': '.github/workflows/validate.yml',
        'run_number': 9, 'run_attempt': 2, 'event': 'pull_request',
        'head_sha': HEAD, 'repository': {'id': 17}, 'head_repository': {'id': 17},
        'pull_requests': [{'number': 7, 'head': {'sha': HEAD, 'repo': {'id': 17}},
                           'base': {'ref': 'main', 'repo': {'id': 17}}}],
        'check_suite_id': 51, 'status': 'completed', 'conclusion': 'success',
        'created_at': '2026-11-17T10:00:00Z',
    }
    job = {'id': 71, 'run_id': 41, 'run_attempt': 2, 'head_sha': HEAD,
           'name': 'validate', 'status': 'completed', 'conclusion': 'success',
           'check_run_url': f'https://api.github.com/{CHECK}'}
    check = {'id': 61, 'name': 'validate', 'head_sha': HEAD, 'app': {'id': 31},
             'check_suite': {'id': 51}, 'status': 'completed', 'conclusion': 'success'}
    api = {
        REPO: [response({'id': 17, 'full_name': 'example/repo'})],
        BRANCH: [response({'name': 'main', 'protected': False})],
        f'{BRANCH}/protection': [response({
            'message': 'Branch not protected',
            'documentation_url': 'https://docs.github.com/rest/branches/branch-protection#get-branch-protection',
            'status': '404'}, 404)],
        RULES: [response([])],
        WORKFLOW: [response({'id': 23, 'path': '.github/workflows/validate.yml', 'state': 'active'})],
        CONTENT: [response({'type': 'file', 'path': '.github/workflows/validate.yml', 'sha': BLOB})],
        RUNS: [response({'total_count': 1, 'workflow_runs': [run]})],
        RUN: [response(run)],
        JOBS: [response({'total_count': 1, 'jobs': [job]})],
        CHECK: [response(check)],
        SUITE: [response({'id': 51, 'head_sha': HEAD, 'app': {'id': 31}})],
    }
    return policy, {'pr': [pr], 'api': api}


GH_STUB = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(__file__).parent
fixture = json.loads((root / 'responses.json').read_text())
counts_file = root / 'counts.json'
counts = json.loads(counts_file.read_text()) if counts_file.exists() else {}
args = sys.argv[1:]
if args[:2] == ['pr', 'view']:
    key = 'pr'
    values = fixture['pr']
    if '--jq' in args:
        print('example/repo\\tmain')
        sys.exit(0)
elif args and args[0] == 'api':
    endpoints = [arg for arg in args[1:] if arg.startswith(('repos/', 'https://'))]
    if len(endpoints) != 1:
        sys.exit('unexpected API arguments')
    with (root / 'requests.jsonl').open('a') as requests:
        requests.write(json.dumps(endpoints[0]) + '\\n')
    key = endpoints[0].removeprefix('https://api.github.com/')
    if key.endswith('/protection/required_status_checks'):
        print('gh: Branch not protected (HTTP 404)', file=sys.stderr)
        sys.exit(1)
    if key == 'repos/example/repo/rules/branches/main':
        sys.exit(0)
    if key not in fixture['api']:
        sys.exit('unexpected endpoint: ' + key)
    values = fixture['api'][key]
else:
    sys.exit('unexpected gh call: ' + repr(args))
index = counts.get(key, 0)
counts[key] = index + 1
counts_file.write_text(json.dumps(counts))
value = values[min(index, len(values) - 1)]
if key == 'pr':
    print(json.dumps(value))
    sys.exit(0)
if 'raw' in value:
    print(value['raw'])
    sys.exit(1)
status = value['status']
if '--include' in args or '-i' in args:
    print('HTTP/2 ' + str(status))
    print('Content-Type: application/json')
    if value.get('link'):
        print('Link: ' + value['link'])
    print()
print(json.dumps(value['body']))
sys.exit(0 if status == 200 else 1)
'''


class NamedWatchChecksTests(unittest.TestCase):
    def watch(self, policy=None, data=None, digest=None, ignore='', bounds=('0', '0'), option=True,
              policy_in_source=False):
        default_policy, default_data = fixture()
        policy = default_policy if policy is None else policy
        data = default_data if data is None else data
        scratch = ROOT.parent / '.scratch'
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as tmp, tempfile.TemporaryDirectory(
                dir=ROOT if policy_in_source else tmp) as policy_tmp:
            directory = Path(tmp)
            (directory / 'gh').write_text(GH_STUB)
            (directory / 'gh').chmod(0o755)
            (directory / 'sleep').write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "${0%/*}/sleeps"\n')
            (directory / 'sleep').chmod(0o755)
            (directory / 'responses.json').write_text(json.dumps(data))
            policy_path = Path(policy_tmp) / 'approved.json'
            policy_bytes = json.dumps(policy).encode()
            policy_path.write_bytes(policy_bytes)
            approved = hashlib.sha256(policy_bytes).hexdigest() if digest is None else digest
            args = ['bash', str(WATCH), 'https://github.com/example/repo/pull/7', *bounds]
            if option:
                args += ['--named-checks', str(policy_path), '--approved-policy-sha256', approved]
            env = {**os.environ, 'PATH': f'{directory}{os.pathsep}{os.environ["PATH"]}',
                   'WATCH_CHECKS_IGNORE': ignore, 'PYTHONDONTWRITEBYTECODE': '1'}
            boot_path = Path('/proc/sys/kernel/random/boot_id')
            boot = boot_path.read_text().strip()
            with (directory / 'stdout').open('w+') as stdout, (directory / 'stderr').open('w+') as stderr:
                process = subprocess.Popen(args, env=env, stdout=stdout, stderr=stderr,
                                           text=True, start_new_session=True)

                def owned_identity():
                    fields = Path(f'/proc/{process.pid}/stat').read_text().rsplit(')', 1)[1].split()
                    self.assertEqual(boot_path.read_text().strip(), boot)
                    self.assertEqual(tuple(map(int, fields[1:4])),
                                     (os.getpid(), process.pid, process.pid))
                    return fields[19]

                start = owned_identity()
                deadline = time.monotonic() + 10
                try:
                    # WNOWAIT retains the leader identity even when Bash exits before its descendants.
                    while os.waitid(os.P_PID, process.pid,
                                    os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(args, 10)
                        time.sleep(min(0.01, remaining))
                finally:
                    try:
                        self.assertEqual(owned_identity(), start)
                        os.killpg(process.pid, signal.SIGTERM)
                        time.sleep(5)
                        self.assertEqual(owned_identity(), start)
                        try:
                            os.killpg(process.pid, 0)
                        except ProcessLookupError:
                            pass
                        else:
                            self.assertEqual(owned_identity(), start)
                            os.killpg(process.pid, signal.SIGKILL)
                    finally:
                        process.wait()
                stdout.seek(0)
                stderr.seek(0)
                result = subprocess.CompletedProcess(args, process.returncode, stdout.read(), stderr.read())
            counts_path = directory / 'counts.json'
            result.calls = json.loads(counts_path.read_text()) if counts_path.exists() else {}
            requests_path = directory / 'requests.jsonl'
            result.requests = [json.loads(line) for line in requests_path.read_text().splitlines()] if requests_path.exists() else []
            sleeps_path = directory / 'sleeps'
            result.sleeps = sleeps_path.read_text().splitlines() if sleeps_path.exists() else []
            return result

    def outcome(self, expected, **kwargs):
        result = self.watch(**kwargs)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertIn('named-checks:', result.stdout + result.stderr)
        return result

    def test_complete_evidence_succeeds_and_rechecks_identity(self):
        result = self.outcome(0)
        for endpoint in ('pr', BRANCH, f'{BRANCH}/protection', RULES, RUNS, RUN):
            self.assertGreaterEqual(result.calls.get(endpoint, 0), 2, endpoint)
        self.assertIn(HEAD, result.stdout)
        self.assertIn('41', result.stdout)
        self.assertIn('2', result.stdout)

    def test_blank_and_duplicate_continuation_fields_refuse_before_request(self):
        for endpoint in (RULES, RUNS, JOBS):
            for extra in ('&page=', '&per_page=', '&unexpected='):
                with self.subTest(endpoint=endpoint, extra=extra):
                    _, data = fixture()
                    continuation = f'https://api.github.com/{endpoint}&page=2{extra}'
                    successful_page = copy.deepcopy(data['api'][endpoint][0])
                    data['api'][continuation.removeprefix('https://api.github.com/')] = [successful_page]
                    data['api'][endpoint][0]['link'] = f'<{continuation}>; rel="next"'
                    result = self.outcome(4, data=data)
                    self.assertNotIn(continuation, result.requests)

    def test_malformed_extra_job_cannot_hide_beside_approved_success(self):
        _, valid = fixture()
        extra = copy.deepcopy(valid['api'][JOBS][0]['body']['jobs'][0])
        extra.update(id=72, name='other', check_run_url=f'https://api.github.com/{REPO}/check-runs/62')
        valid['api'][JOBS][0]['body'] = {
            'total_count': 2, 'jobs': [valid['api'][JOBS][0]['body']['jobs'][0], extra]}
        self.outcome(0, data=valid)
        mutations = [('name', None), ('name', ''), ('name', 7), ('name', 'other\n'),
                     ('id', 72.0), ('id', True), ('id', 71), ('run_id', 41.0),
                     ('run_attempt', True), ('head_sha', 'c' * 40),
                     ('check_run_url', None), ('check_run_url', f'https://api.github.com/{CHECK}')]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                _, data = fixture()
                malformed = copy.deepcopy(extra)
                malformed[key] = value
                data['api'][JOBS][0]['body'] = {
                    'total_count': 2, 'jobs': [data['api'][JOBS][0]['body']['jobs'][0], malformed]}
                self.outcome(4, data=data)
        for missing in ('name', 'id', 'run_id', 'run_attempt', 'head_sha', 'check_run_url'):
            with self.subTest(missing=missing):
                _, data = fixture()
                malformed = copy.deepcopy(extra)
                del malformed[missing]
                data['api'][JOBS][0]['body'] = {
                    'total_count': 2, 'jobs': [data['api'][JOBS][0]['body']['jobs'][0], malformed]}
                self.outcome(4, data=data)

    def test_source_controlled_policy_is_refused_before_api_reads(self):
        result = self.outcome(4, policy_in_source=True)
        self.assertIn('outside PR-controlled source', result.stdout)
        self.assertEqual(result.requests, [])

    def test_canonical_numeric_repository_pagination_is_bound_to_verified_id(self):
        for endpoint, field in ((RULES, None), (RUNS, 'workflow_runs'), (JOBS, 'jobs')):
            for repository_id, expected in ((17, 0), (99, 4)):
                with self.subTest(endpoint=endpoint, repository_id=repository_id):
                    _, data = fixture()
                    canonical = endpoint.replace(REPO, f'repositories/{repository_id}', 1) + '&page=2'
                    final_page = copy.deepcopy(data['api'][endpoint][0])
                    empty_page = [] if field is None else {'total_count': 1, field: []}
                    data['api'][endpoint] = [response(empty_page,
                        link=f'<https://api.github.com/{canonical}>; rel="next"')]
                    data['api'][canonical] = [final_page]
                    result = self.outcome(expected, data=data)
                    if expected == 4:
                        self.assertNotIn(f'https://api.github.com/{canonical}', result.requests)

    def test_numeric_api_identities_require_positive_integers(self):
        targets = [('pr', ('number',)), (REPO, ('id',)), (WORKFLOW, ('id',)),
                   (CHECK, ('id',)), (CHECK, ('app', 'id')), (CHECK, ('check_suite', 'id')),
                   (SUITE, ('id',)), (SUITE, ('app', 'id')),
                   (JOBS, ('jobs', 0, 'id')), (JOBS, ('jobs', 0, 'run_id')),
                   (JOBS, ('jobs', 0, 'run_attempt'))]
        run_paths = [('id',), ('workflow_id',), ('run_number',), ('run_attempt',),
                     ('check_suite_id',), ('repository', 'id'), ('head_repository', 'id'),
                     ('pull_requests', 0, 'number'), ('pull_requests', 0, 'head', 'repo', 'id'),
                     ('pull_requests', 0, 'base', 'repo', 'id')]
        targets += [(RUN, path) for path in run_paths]
        targets += [(RUNS, ('workflow_runs', 0, *path)) for path in run_paths]
        for endpoint, path in targets:
            for kind in ('float', 'boolean'):
                with self.subTest(endpoint=endpoint, path=path, kind=kind):
                    _, data = fixture()
                    # Isolate each API observation from fixture objects shared by other responses.
                    data = json.loads(json.dumps(data))
                    target = data['pr'][0] if endpoint == 'pr' else data['api'][endpoint][0]['body']
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = float(target[path[-1]]) if kind == 'float' else True
                    self.outcome(4, data=data)

    def test_malformed_newer_run_never_falls_back_to_older_success(self):
        for missing in ('workflow_id', 'run_attempt', 'repository', 'pull_requests'):
            with self.subTest(missing=missing):
                _, data = fixture()
                newer = copy.deepcopy(data['api'][RUN][0]['body'])
                newer.update(id=42, run_number=10, status='completed', conclusion='failure')
                del newer[missing]
                data['api'][RUNS][0]['body'] = {
                    'total_count': 2, 'workflow_runs': [newer, data['api'][RUN][0]['body']]}
                self.outcome(4, data=data)

    def test_incomplete_and_contradictory_page_metadata_refuses(self):
        for endpoint in (RULES, RUNS, JOBS):
            for pages in ({'last': 2}, {'first': 2}, {'prev': 1},
                          {'next': 2, 'last': 1}, {'next': 3}):
                with self.subTest(endpoint=endpoint, pages=pages):
                    _, data = fixture()
                    data['api'][endpoint][0]['link'] = ', '.join(
                        f'<https://api.github.com/{endpoint}&page={page}>; rel="{relation}"'
                        for relation, page in pages.items())
                    final_page = copy.deepcopy(data['api'][endpoint][0])
                    final_page['link'] = None
                    for page in set(pages.values()):
                        data['api'][endpoint + f'&page={page}'] = [final_page]
                    result = self.outcome(4, data=data)
                    self.assertFalse(any('&page=' in request for request in result.requests))
        _, data = fixture()
        second = RULES + '&page=2'
        data['api'][RULES] = [response([], link=(
            f'<https://api.github.com/{second}>; rel="next", '
            f'<https://api.github.com/{RULES}&page=3>; rel="last"'))]
        data['api'][second] = [response([])]
        result = self.outcome(4, data=data)
        self.assertIn(f'https://api.github.com/{second}', result.requests)

    def test_boolean_equal_to_one_cannot_supply_api_identity(self):
        policy, data = fixture()
        policy.update(repository_id=1, pr=1)
        policy['checks'][0].update(workflow_id=1, app_id=1)

        def one_ids(value):
            if isinstance(value, dict):
                return {key: (1 if key in {'id', 'number', 'workflow_id', 'run_id', 'run_attempt',
                                           'run_number', 'check_suite_id'} else
                              'https://api.github.com/repos/example/repo/check-runs/1'
                              if key == 'check_run_url' else one_ids(item)) for key, item in value.items()}
            if isinstance(value, list):
                return [one_ids(item) for item in value]
            return value

        data = one_ids(data)
        data['pr'][0]['url'] = 'https://github.com/example/repo/pull/1'
        data['api'] = {re.sub(r'/(?=\d)[0-9]+(?=/|\?|$)', '/1', endpoint): responses
                       for endpoint, responses in data['api'].items()}
        self.outcome(0, policy=policy, data=data)
        targets = [('pr', ('number',)), (REPO, ('id',)),
                   (f'{REPO}/actions/workflows/1', ('id',)),
                   (f'{REPO}/check-runs/1', ('id',)),
                   (f'{REPO}/check-runs/1', ('app', 'id')),
                   (f'{REPO}/check-runs/1', ('check_suite', 'id')),
                   (f'{REPO}/check-suites/1', ('id',)),
                   (f'{REPO}/check-suites/1', ('app', 'id'))]
        for key in ('id', 'run_id', 'run_attempt'):
            targets.append((f'{REPO}/actions/runs/1/attempts/1/jobs?per_page=100', ('jobs', 0, key)))
        for path in [('id',), ('workflow_id',), ('run_number',), ('run_attempt',), ('check_suite_id',),
                     ('repository', 'id'), ('head_repository', 'id'), ('pull_requests', 0, 'number'),
                     ('pull_requests', 0, 'head', 'repo', 'id'), ('pull_requests', 0, 'base', 'repo', 'id')]:
            targets.append((f'{REPO}/actions/runs/1', path))
            targets.append((RUNS.replace('/23/', '/1/'), ('workflow_runs', 0, *path)))
        for endpoint, path in targets:
            with self.subTest(endpoint=endpoint, path=path):
                altered = copy.deepcopy(data)
                target = altered['pr'][0] if endpoint == 'pr' else altered['api'][endpoint][0]['body']
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = True
                self.outcome(4, policy=policy, data=altered)

    def test_absent_option_keeps_default_required_context_route(self):
        result = self.watch(option=False)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn('required contexts', result.stdout)
        self.assertEqual(result.calls, {})

    def test_policy_schema_and_external_digest_refuse_uncertainty(self):
        mutations = [
            ('schema_version', 2), ('schema_version', True), ('checks', []),
            ('repository_id', '17'), ('repository_id', True), ('pr', 8),
            ('base', 'other'), ('head', 'a' * 7), ('head', 'c' * 40),
            ('ignore', ['validate']), ('approved', True),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                policy, _ = fixture()
                policy[key] = value
                self.outcome(4, policy=policy)
        self.outcome(4, digest='0' * 64)
        self.outcome(4, digest='')
        self.outcome(4, ignore='validate')

    def test_tuple_schema_rejects_missing_invalid_and_duplicate_bindings(self):
        for key, value in [('workflow_id', '23'), ('app_id', True),
                           ('workflow_path', '../validate.yml'), ('workflow_blob_sha', 'b' * 7),
                           ('check_name', ''), ('ignore', True)]:
            with self.subTest(key=key):
                policy, _ = fixture()
                policy['checks'][0][key] = value
                self.outcome(4, policy=policy)
        policy, _ = fixture()
        policy['checks'].append(copy.deepcopy(policy['checks'][0]))
        self.outcome(4, policy=policy)
        for key in fixture()[0]['checks'][0]:
            with self.subTest(missing=key):
                policy, _ = fixture()
                del policy['checks'][0][key]
                self.outcome(4, policy=policy)

    def test_every_policy_tuple_is_required(self):
        policy, data = fixture()
        second = copy.deepcopy(policy['checks'][0])
        second['check_name'] = 'security'
        policy['checks'].append(second)
        self.outcome(4, policy=policy, data=data)
        job = copy.deepcopy(data['api'][JOBS][0]['body']['jobs'][0])
        job.update(id=72, name='security', check_run_url=f'https://api.github.com/{REPO}/check-runs/62')
        data['api'][JOBS][0]['body'] = {'total_count': 2, 'jobs': [data['api'][JOBS][0]['body']['jobs'][0], job]}
        check = copy.deepcopy(data['api'][CHECK][0]['body'])
        check.update(id=62, name='security')
        data['api'][f'{REPO}/check-runs/62'] = [response(check)]
        self.outcome(0, policy=policy, data=data)

    def test_positive_unprotected_evidence_is_mandatory(self):
        for branch in ({}, {'protected': True}, {'protected': 'false'}, {'protected': 0}):
            with self.subTest(branch=branch):
                _, data = fixture()
                data['api'][BRANCH] = [response(branch)]
                self.outcome(4, data=data)
        for classic in [response({}, 404), response({'message': 'Not Found'}, 404),
                        response({'message': 'Branch not protected'}, 403),
                        response({'message': 'Branch not protected'}, 200),
                        {'raw': 'gh: Branch not protected (HTTP 404)'},
                        response({'message': 'Required status checks not enabled'}, 404)]:
            with self.subTest(classic=classic):
                _, data = fixture()
                data['api'][f'{BRANCH}/protection'] = [classic]
                self.outcome(4, data=data)
        for rules in ([{'type': 'required_status_checks'}], [{'type': 'unfamiliar'}], {}, None):
            with self.subTest(rules=rules):
                _, data = fixture()
                data['api'][RULES] = [response(rules)]
                self.outcome(4, data=data)

    def test_api_errors_and_malformed_evidence_fail_closed(self):
        for endpoint in fixture()[1]['api']:
            for bad in (response({'message': 'Forbidden'}, 403), response({}, 502), {'raw': 'not JSON'}):
                with self.subTest(endpoint=endpoint, bad=bad):
                    _, data = fixture()
                    data['api'][endpoint] = [bad]
                    self.outcome(4, data=data)

    def test_workflow_repository_and_check_identities_are_exact(self):
        cases = [(REPO, 'id', 99), (WORKFLOW, 'id', 99), (WORKFLOW, 'path', '.github/workflows/other.yml'),
                 (CONTENT, 'sha', 'c' * 40), (CONTENT, 'type', 'dir'),
                 (CHECK, 'head_sha', 'c' * 40), (CHECK, 'name', 'other'),
                 (CHECK, 'app', {'id': 99}), (CHECK, 'check_suite', {'id': 99}),
                 (SUITE, 'head_sha', 'c' * 40), (SUITE, 'app', {'id': 99})]
        for endpoint, key, value in cases:
            with self.subTest(endpoint=endpoint, key=key):
                _, data = fixture()
                data['api'][endpoint][0]['body'][key] = value
                self.outcome(4, data=data)
        for url in ('https://example.com/check-runs/61', f'https://api.github.com/{REPO}/actions/runs/61',
                    'https://api.github.com/repos/other/repo/check-runs/61'):
            with self.subTest(url=url):
                _, data = fixture()
                data['api'][JOBS][0]['body']['jobs'][0]['check_run_url'] = url
                self.outcome(4, data=data)

    def test_run_filter_never_accepts_other_pr_head_event_or_fork(self):
        cases = [('head_sha', 'c' * 40), ('event', 'push'), ('workflow_id', 99),
                 ('path', '.github/workflows/other.yml'), ('repository', {'id': 99}),
                 ('head_repository', {'id': 99}), ('pull_requests', []),
                 ('pull_requests', [{'number': 8}])]
        for key, value in cases:
            with self.subTest(key=key):
                _, data = fixture()
                data['api'][RUNS][0]['body']['workflow_runs'][0][key] = value
                self.outcome(4, data=data)

    def test_latest_run_wins_even_when_an_older_run_succeeds(self):
        for status, conclusion, expected in [('queued', None, 3), ('completed', 'failure', 1)]:
            with self.subTest(status=status):
                _, data = fixture()
                newer = copy.deepcopy(data['api'][RUN][0]['body'])
                newer.update(id=42, run_number=10, created_at='2026-11-17T11:00:00Z',
                             status=status, conclusion=conclusion)
                data['api'][RUNS][0]['body']['workflow_runs'].insert(0, newer)
                data['api'][RUNS][0]['body']['total_count'] = 2
                data['api'][f'{REPO}/actions/runs/42'] = [response(newer)]
                self.outcome(expected, data=data)

    def test_latest_attempt_and_job_mapping_are_mandatory(self):
        for key, value in [('run_attempt', 1), ('run_id', 99), ('head_sha', 'c' * 40)]:
            with self.subTest(key=key):
                _, data = fixture()
                data['api'][JOBS][0]['body']['jobs'][0][key] = value
                self.outcome(4, data=data)
        _, data = fixture()
        jobs = data['api'][JOBS][0]['body']
        jobs['jobs'].append(copy.deepcopy(jobs['jobs'][0]))
        jobs['total_count'] = 2
        self.outcome(4, data=data)
        _, data = fixture()
        data['api'][JOBS][0]['body'] = {'total_count': 0, 'jobs': []}
        self.outcome(4, data=data)

    def test_only_completed_success_counts_for_workflow_job_and_check(self):
        for endpoint in (RUN, JOBS, CHECK):
            for conclusion in ('failure', 'cancelled', 'skipped', 'neutral', 'timed_out', 'action_required'):
                with self.subTest(endpoint=endpoint, conclusion=conclusion):
                    _, data = fixture()
                    body = data['api'][endpoint][0]['body']
                    target = body['jobs'][0] if endpoint == JOBS else body
                    target['conclusion'] = conclusion
                    self.outcome(1, data=data)
            _, data = fixture()
            body = data['api'][endpoint][0]['body']
            target = body['jobs'][0] if endpoint == JOBS else body
            target.update(status='in_progress', conclusion=None)
            self.outcome(3, data=data)

    def test_complete_pagination_collects_all_runs_and_jobs(self):
        for endpoint, field in ((RUNS, 'workflow_runs'), (JOBS, 'jobs')):
            with self.subTest(endpoint=endpoint):
                _, data = fixture()
                original = data['api'][endpoint][0]['body']
                next_page = endpoint + '&page=2'
                data['api'][endpoint] = [response({'total_count': 1, field: []}, link=f'<https://api.github.com/{next_page}>; rel="next"')]
                data['api'][next_page] = [response(original)]
                self.outcome(0, data=data)
        _, data = fixture()
        next_page = RULES + '&page=2'
        data['api'][RULES] = [response([], link=f'<https://api.github.com/{next_page}>; rel="next"')]
        data['api'][next_page] = [response([])]
        self.outcome(0, data=data)
        data['api'][next_page] = [response([{'type': 'unfamiliar'}])]
        self.outcome(4, data=data)

    def test_partial_foreign_cyclic_and_malformed_pagination_refuses(self):
        for endpoint in (RULES, RUNS, JOBS):
            for continuation in ('https://evil.example/api?page=2',
                                 f'https://api.github.com/{REPO}/issues?page=2',
                                 f'https://api.github.com/{endpoint}',
                                 f'https://api.github.com/{endpoint}&head_sha=wrong&page=2'):
                with self.subTest(endpoint=endpoint, continuation=continuation):
                    _, data = fixture()
                    forbidden_key = continuation.removeprefix('https://api.github.com/')
                    successful_page = copy.deepcopy(data['api'][endpoint][0])
                    if forbidden_key == endpoint:
                        data['api'][endpoint].append(successful_page)
                    else:
                        data['api'][forbidden_key] = [successful_page]
                    data['api'][endpoint][0]['link'] = f'<{continuation}>; rel="next"'
                    result = self.outcome(4, data=data)
                    self.assertNotIn(continuation, result.requests)
                    if forbidden_key == endpoint:
                        self.assertEqual(result.calls.get(endpoint), 1)
                    else:
                        self.assertEqual(result.calls.get(forbidden_key, 0), 0)
            _, data = fixture()
            data['api'][endpoint][0]['link'] = 'unparseable'
            self.outcome(4, data=data)
        _, data = fixture()
        data['api'][RUNS][0]['body']['total_count'] = 2
        self.outcome(4, data=data)
        _, data = fixture()
        data['api'][JOBS][0]['body']['total_count'] = 2
        self.outcome(4, data=data)

    def test_final_rechecks_invalidate_changed_head_protection_and_attempt(self):
        _, data = fixture()
        data['pr'].append({**data['pr'][0], 'headRefOid': 'c' * 40})
        self.outcome(4, data=data)
        for endpoint, changed in [(BRANCH, {'name': 'main', 'protected': True}),
                                  (RULES, [{'type': 'required_status_checks'}]),
                                  (RUN, {**fixture()[1]['api'][RUN][0]['body'], 'run_attempt': 3})]:
            with self.subTest(endpoint=endpoint):
                _, data = fixture()
                data['api'][endpoint].append(response(changed))
                self.outcome(4, data=data)
        _, data = fixture()
        newer = copy.deepcopy(data['api'][RUN][0]['body'])
        newer.update(id=42, run_number=10, status='queued', conclusion=None,
                     created_at='2026-11-17T11:00:00Z')
        data['api'][RUNS].append(response({'total_count': 2, 'workflow_runs': [newer, data['api'][RUN][0]['body']]}))
        self.outcome(4, data=data)

    def test_fixed_poll_bounds_preserve_start_and_overall_outcomes(self):
        _, data = fixture()
        data['api'][RUNS][0]['body'] = {'total_count': 0, 'workflow_runs': []}
        self.outcome(2, data=data)
        result = self.outcome(2, data=data, bounds=())
        self.assertEqual(result.sleeps, ['300'] * 2)
        _, data = fixture()
        data['api'][RUN][0]['body'].update(status='in_progress', conclusion=None)
        result = self.outcome(3, data=data, bounds=())
        self.assertEqual(result.sleeps, ['300'] * 18)


if __name__ == '__main__':
    unittest.main()
