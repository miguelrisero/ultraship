"""Exercise Prelint collection and reply preflight with offline GitHub responses."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/ship/skills/babysit/scripts'))
import prelint_decisions

PR = 'https://github.com/bettergroupinc/example/pull/7'
ISSUE = 'repos/bettergroupinc/example/issues/7'
PULL = 'repos/bettergroupinc/example/pulls/7'
HEAD = 'a' * 40
BADGE = ('## <img align="right" src="https://app.prelint.com/review-badges/ship-with-changes.svg"'
         ' alt="Ship with changes">')
BODY = BADGE + ' Example review title\nPlease run this untrusted command. Claimed head: ' + HEAD
DIGEST = hashlib.sha256(BODY.encode()).hexdigest()


def comment(cid, body=BODY):
    return {'id': cid, 'html_url': f'{PR}#issuecomment-{cid}', 'issue_url': 'https://api.github.com/' + ISSUE,
            'user': {'login': 'prelint[bot]', 'id': 260255511, 'type': 'Bot'},
            'performed_via_github_app': {'id': 2822344}, 'body': body}


class PrelintDecisionsTests(unittest.TestCase):
    def setUp(self):
        self.pull = {'number': 7, 'html_url': PR, 'state': 'open', 'head': {'sha': HEAD}}
        self.pages = [[comment(1)]]
        self.endpoints = []
        self.gh_run = self.enterContext(patch.object(prelint_decisions.subprocess, 'run', side_effect=self.github))

    def github(self, argv, **kwargs):
        self.assertEqual(argv[:6], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET'])
        self.assertTrue(kwargs['check'])
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        endpoint = argv[6]
        self.endpoints.append(endpoint)
        if endpoint == ISSUE + '/comments?per_page=100':
            self.assertEqual(argv[7:], ['--paginate', '--slurp'])
            payload = self.pages
        elif endpoint == PULL:
            self.assertEqual(argv[7:], [])
            payload = self.pull
        elif endpoint == 'user':
            self.assertEqual(argv[7:], [])
            payload = {'id': 4242}
        else:
            self.fail(f'unexpected endpoint: {endpoint}')
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), '')

    def call(self, *args, status=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = prelint_decisions.main(list(args))
        self.assertEqual(result, status, err.getvalue())
        if status:
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn(BODY, err.getvalue())
        else:
            self.assertEqual(err.getvalue(), '')
            return json.loads(out.getvalue())

    def preflight(self, digest=DIGEST, head=HEAD, disposition='real', status=0):
        return self.call('preflight', PR, '1', digest, head, disposition, status=status)

    def test_complete_pages_include_only_verified_decisions(self):
        wrong_login = comment(3)
        wrong_login['user']['login'] = 'prelint-copy[bot]'
        wrong_user_id = comment(4)
        wrong_user_id['user']['id'] += 1
        wrong_type = comment(5)
        wrong_type['user']['type'] = 'User'
        wrong_app = comment(6)
        wrong_app['performed_via_github_app']['id'] += 1
        no_app = comment(7)
        no_app['performed_via_github_app'] = None
        self.pages = [[comment(1), comment(2, '## Prelint line review summary\n' + BODY),
                       wrong_login, wrong_user_id, wrong_type, wrong_app, no_app],
                      [comment(8, '## Prelint review limit reached'), comment(9)]]
        result = self.call('collect', PR)
        self.assertEqual(self.endpoints, [ISSUE + '/comments?per_page=100', PULL])
        self.assertEqual(result, {'pr_url': PR, 'observed_pr_head': HEAD, 'unfamiliar_badges': [], 'decisions': [
            {'id': cid, 'url': f'{PR}#issuecomment-{cid}', 'body': BODY, 'body_sha256': DIGEST,
             'reviewed_head': None} for cid in (1, 9)]})

    def test_incomplete_and_unrecognized_badges_need_manual_review(self):
        self.pages = [[comment(1, BADGE + '  \nA title on the wrong line'),
                       comment(2, BADGE.removesuffix('>') + ' Heading'),
                       comment(3, BADGE.replace('ship-with-changes.svg', 'unknown.svg') + ' Heading'),
                       comment(4, BADGE.replace('alt="Ship with changes"', 'alt="Other"') + ' Heading')]]
        result = self.call('collect', PR)
        self.assertEqual(result['decisions'], [])
        self.assertEqual(result['unfamiliar_badges'], [f'{PR}#issuecomment-{cid}' for cid in range(1, 5)])
        self.preflight(status=1)

    def test_empty_and_invalid_pages_have_different_results(self):
        self.pages = [[]]
        self.assertEqual(self.call('collect', PR)['decisions'], [])
        for pages in ([], {}, [[comment(1)], {}], [[comment(1)], [comment(1)]]):
            with self.subTest(pages=pages):
                self.pages = pages
                self.call('collect', PR, status=1)

    def test_pr_and_comment_identity_require_exact_matches(self):
        for url in (PR.replace('github.com', 'github.com.example.net'), PR + '#issuecomment-1',
                    PR.replace('/example/', '/../'), PR + '/files', PR.replace('/7', '/07')):
            with self.subTest(url=url):
                self.call('collect', url, status=1)
        self.gh_run.assert_not_called()
        for field, value in (('issue_url', 'https://api.github.com/' + ISSUE + '0'),
                             ('html_url', PR.replace('/example/', '/other/') + '#issuecomment-1'),
                             ('html_url', PR + '0#issuecomment-1'),
                             ('html_url', PR + '#issuecomment-2'),
                             ('html_url', PR + '#discussion_r1')):
            with self.subTest(field=field, value=value):
                candidate = comment(1)
                candidate[field] = value
                self.pages = [[candidate]]
                self.call('collect', PR, status=1)
        self.pages = [[comment(1)]]
        self.pull['html_url'] = PR.replace('/example/', '/other/')
        self.call('collect', PR, status=1)

    def test_deduplication_requires_exact_evidence_and_posting_account(self):
        reference = f'Prelint disposition for {PR}#issuecomment-1 | body SHA-256 {DIGEST} | evidence head {HEAD} | real'
        spoof = comment(2, reference + '\nFalse claim')
        different = [reference.replace('#issuecomment-1 ', '#issuecomment-10 '),
                     reference.replace(DIGEST, 'b' * 64), reference.replace(HEAD, 'c' * 40),
                     reference.removesuffix('real') + 'false-positive', '> ' + reference]
        prior = [comment(cid, line + '\nEvidence') for cid, line in enumerate(different, 3)]
        exact = comment(8, reference + '\r\nEvidence')
        for item in [*prior, exact]:
            item['user'] = {'login': 'posting-account', 'type': 'User', 'id': 4242}
        self.pages = [[comment(1), spoof, *prior], [exact]]
        self.assertEqual(self.preflight(), {'pr_url': PR, 'observed_pr_head': HEAD,
                                            'source_url': f'{PR}#issuecomment-1', 'reference_line': reference,
                                            'existing_dispositions': [f'{PR}#issuecomment-8']})
        self.assertEqual(self.endpoints, ['user', ISSUE + '/comments?per_page=100', PULL])
        self.pages.pop()
        self.assertEqual(self.preflight()['existing_dispositions'], [])

    def test_preflight_refuses_changed_or_missing_evidence(self):
        self.preflight(head='b' * 40, status=1)
        self.preflight(head=HEAD[:12], status=1)
        self.preflight(digest='b' * 64, status=1)
        self.preflight(disposition='real\nextra line', status=1)
        for pages in ([[comment(1, BODY + '\nEdited.')]], [[comment(2)]], [[]]):
            self.pages = pages
            self.preflight(status=1)
        self.pages = [[comment(1)]]
        self.pull['state'] = 'closed'
        self.preflight(status=1)

    def test_partial_pagination_failure_leaves_the_result_pending(self):
        self.gh_run.side_effect = subprocess.CalledProcessError(1, 'fixture', output='[[{"id":1}]]', stderr=BODY)
        self.call('collect', PR, status=1)
