"""Thread ownership checks and the Bash boundary for review-thread writes."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'plugins/ship/skills/babysit/scripts/thread_reply.py'
spec = importlib.util.spec_from_file_location('ultraship_thread_reply', ROOT / 'plugins/ship/hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)

LOOKUP = 'query($id:ID!){node(id:$id){__typename ... on PullRequestReviewThread{pullRequest{number repository{nameWithOwner}}}}}'
REPLY = 'mutation($id:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$body}){comment{url}}}'
RESOLVE = 'mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}'
PR = 'https://github.com/o/r/pull/7'
THREAD = 'PRRT_kwDOabc'
COMMENT = PR + '#discussion_r123'
PREFIX = ['api', '--hostname', 'github.com', 'graphql']

REFUSE = (
    "gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -F id=PRRT_kwDOabc",
    'gh api graphql -f query=\'mutation{addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:"PRRT_x",body:"done"}){comment{url}}}\'',
    'gh api graphql -f query=\'mutation{unresolveReviewThread(input:{threadId:"PRRT_x"}){thread{id}}}\'',
    'gh api graphql -f query=\'mutation{addPullRequestReviewComment(input:{pullRequestReviewId:"PRR_x",inReplyTo:"PRRC_y",body:"b"}){comment{id}}}\'',
    "for id in PRRT_a PRRT_b; do gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -F id=$id; done",
    'gh api -X POST repos/o/r/pulls/7/comments/123/replies -f body=done',
    'gh api repos/o/r/pulls/7/comments -f body=done -F in_reply_to=123',
    'gh api --method POST repos/{owner}/{repo}/pulls/7/comments --input reply.json',
    'gh api graphql -F query=@mutation.graphql -F id=PRRT_x',
    'gh api graphql -f query="$Q" -F id=PRRT_x',
    'gh api graphql --input body.json',
    'gh api graphql -f query="$(cat q.graphql)"',
    'Q=\'mutation{resolveReviewThread(input:{threadId:"PRRT_x"}){thread{id}}}\'; gh api graphql -f query="$Q"',
    'bash -c "gh api graphql -F query=@q.graphql"',
    'gh api https://api.github.com/graphql -F query=@q.graphql',
    'curl -s -H "Authorization: bearer $T" https://api.github.com/graphql -d @body.json',
    'curl -X POST https://api.github.com/repos/o/r/pulls/7/comments/1/replies -d \'{"body":"x"}\'',
    'gh api "$ENDPOINT" -X POST -f body=x',
    'gh api graphql -f \'query=mutation{resolveReview\'\'Thread(input:{threadId:"PRRT_x"}){thread{id}}}\'',
    'echo PRRT_x | xargs -I{} gh api graphql -f query=\'mutation{resolveReviewThread(input:{threadId:"{}"}){thread{id}}}\'',
    'python3 - <<\'EOF\'\nimport subprocess\nsubprocess.run([\'gh\', \'api\', \'graphql\', \'-f\', \'query=mutation{resolveReviewThread(input:{threadId:"PRRT_x"}){thread{id}}}\'])\nEOF',
    'gh api graphql -f query="query($id:ID!){node(id:$id){id}}"',
    'gh api graphql -f query=query\\{viewer{login}}',
    'gh api repos/o/r/pulls/7/comments --method=PATCH -f body=x',
    'gh api "repos/o/r/pulls/${NUMBER}suffix/comments" -X POST -f body=x',
    'gh api -X POST -f body=x',
    'gh api graphql -f query=\'query{viewer{login}}',
    "gh api 'graphql?x=1' --input body.json",
    "gh api 'repos/o/r/pulls/7/comments?x=1' -F in_reply_to=123 -f body=done",
    "gh api 'graphql#x' -F query=@q.graphql",
    'gh api GRAPHQL -F query=@q.graphql',
    'gh api https://api.github.com:443/graphql -F query=@q.graphql',
    'gh api https://API.GITHUB.COM/graphql -F query=@q.graphql',
    'gh api repos/o/r/pul%6cs/7/comments -f body=x -F in_reply_to=1',
    'gh api REPOS/O/R/PULLS/7/COMMENTS -f body=x -F in_reply_to=1',
    'gh api repos/o/r//pulls//7//comments -f body=x',
    'gh api repos/o/r/issues/../pulls/7/comments -f body=x',
    'gh api https://example.com/repos/o/r/issues/1/comments -f body=x',
    'RESOURCE=pulls; gh api "repos/o/r/${RESOURCE}/7/comments" -f body=done -F in_reply_to=123',
    'gh api repos/$OWNER/${REPO}/issues/7/comments -f body=hello',
    'echo `gh api graphql -F query=@q.graphql`',
    '`gh api repos/o/r/pulls/7/comments -f body=x`',
    'curl -X POST https://api.github.com/repos/o/r/pul%6cs/7/comments -d @b.json',
    "git commit -m 'fix: x' && gh api graphql -F query=@q.graphql",
    'gh api repos/{owner}/{repo}/{branch}/comments -f body=x',
    'gh api repos/o/r/pull?/7/comments -f body=done -F in_reply_to=123',
    'gh api repos/o/r/pulls/*/comments -f body=x',
    'gh api repos/o/r/[p]ulls/7/comments -f body=x',
    'gh ap? repos/o/r/pulls/7/comments -f body=x',
    'cd /repo && curl -s https://api.github.com/graphql -d @body.json',
    'U=https://api.github.com; curl $U/graphql -d @body.json',
    'curl $(echo https://api.github.com)/graphql -d @body.json',
    'gh api https://api.github.com/user && curl -d @body.json "$G/graphql"',
    'gh pr view 7; curl https://api.github.com/graphql -d @body.json',
    'curl -X POST https://api.github.com/repos/o/r/pulls/7/comments -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" --data-binary @reply.json -H gh api',
    "gh api -iH 'Accept: application/vnd.github+json' graphql --input body.json",
    'gh api -iX POST repos/o/r/pulls/7/comments -f body=x',
    'gh api -XPOST repos/o/r/pulls/7/comments -f body=x',
    'gh api repos/o/r/pulls/7/comments -fbody=x',
    'gh api repos/o/r/issues/7/comments extra -f body=x',
    "gh api -H 'Accept: x' -Z graphql --input body.json",
    'gh api --unknown-option graphql --input body.json',
    "env -S 'curl https://api.github.com/graphql -d @body.json'",
    "gh api -i repos/o/r/pulls/7/comments $'-f' body=x",
    'gh api -i repos/o/r/pulls/7/comments $"-f" body=x',
    'gh api repos/o/r/pulls/7/comments {-f,body=x}',
    'F=-f; gh api repos/o/r/pulls/7/comments $F body=x',
    'gh api repos/o/r/pulls/7/comments "$F" body=x',
    'gh api $ARGS',
    'gh api "$F" repos/o/r/pulls/7/comments',
    'gh api repos/o/r/pulls/7/comments ${F:--f} body=x',
    "gh api -i graphql $'-F' query=@q.graphql",
    'gh api graphql {-F,query=@q.graphql}',
    'gh api -iXPOST repos/o/r/pulls/7/comments',
    'gh api -X=POST repos/o/r/pulls/7/comments',
    'echo -f body=x | xargs gh api repos/o/r/pulls/7/comments',
    'xargs -a args.txt gh api repos/o/r/pulls/7/comments',
    'find . -name x -exec gh api repos/o/r/pulls/7/comments {} +',
    'bash -c \'gh "api" repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123\'',
    'sh -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    "HOME='repos/o/r/pulls/7/comments'; gh api ~ -f body=x -F in_reply_to=123",
    'gh api repos/o/r/pulls/comments/5 -X PATCH -f body=x',
    'gh api repos/o/r/issues/7/comments -f body=x',
    'gh api -X DELETE repos/o/r/pulls/comments/5',
    "echo 'gh api repos/o/r/pulls/7/comments' | bash",
    'S=\'gh api repos/o/r/pulls/7/comments\'; bash -c "$S"',
    "bash -c 'gh pr view 7'",
    "gh api graphql -f query='query{viewer{login}}'",
    'gh api graphql -f query=\'query($id:ID!){node(id:$id){id}}\' -F id="$THREAD"',
    "gh api graphql -f query='query($owner:String!,$name:String!){repository(owner:$owner,name:$name){id}}' -F owner=o -F name=r",
    "gh api graphql --paginate -f query='query($endCursor:String){viewer{repositories(first:10,after:$endCursor){nodes{name}}}}'",
    'gh api repos/o/r/issues/7/comments -f body=hello',
    'gh api graphql -f "query=query{viewer{login}}"',
    'gh api graphql -f query=query{viewer{login}}',
    "gh api graphql -f 'query=query($id:ID!){node(id:$id){id}}' -F id=PRRT_x",
    'bash -c \'gh api graphql -f "query=query{viewer{login}}"\'',
    'gh api repos/{owner}/{repo}/issues/7/comments -f body=hello',
    "gh api graphql -f query='query{viewer{login}}' && gh api https://api.github.com/user",
    'gh api repos/o/r/issues/7/comments -f body="$BODY"',
    'bash -o posix -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'bash -O extglob -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'bash +e -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'bash --rcfile x -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'sh -s <<<\'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'bash /dev/stdin <<<\'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    '. /dev/stdin <<<\'gh api repos/o/r/pulls/7/comments -f body=x\'',
    'bash -x scripts/check.sh \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    "source <(echo 'gh api repos/o/r/pulls/7/comments -f body=x')",
    'watch -n 60 \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'su -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\' miguel',
    r'command eval g\"h\" api repos/o/r/pulls/7/comments -f body=x',
    r'if eval g\"h\" api repos/o/r/pulls/7/comments -f body=x; then :; fi',
    r'time eval g\"h\" api repos/o/r/pulls/7/comments -f body=x',
    'exec . /dev/stdin <<<\'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'find . -name x && gh pr view 7',
    "watch -n 60 'query= gh api repos/o/r/pulls/7/comments --input reply.json'",
    "su -c 'query=1 gh api repos/o/r/pulls/7/comments -f body=x' miguel",
    'gh "api -X POST repos/o/r/pulls/7/comments -f body=x"',
    r'watch -n 60 g\"h\" api repos/o/r/pulls/7/comments -f body=x',
    r'ssh host g\"h\" api repos/o/r/pulls/7/comments -f body=x',
    'script -qc \'g"h" api repos/o/r/pulls/7/comments -f body=x\' /dev/null',
    'runuser -u miguel -- sh -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'env -S \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'gh "$SUB" repos/o/r/pulls/7/comments',
    r'sudo -s g\"h\" api repos/o/r/pulls/7/comments -f body=x',
    'env --split \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'env --split-str=\'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'tmux new-session -d \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'timeout 60 flock /tmp/x -c \'g"h" api repos/o/r/pulls/7/comments -f body=x\'',
    'echo api repos/o/r/pulls/7/comments -f body=x | xargs gh',
    r'gh api repos/o/r/pulls/7; sudo -s g\"h\" api repos/o/r/pulls/7/comments -f body=x',
    'gh pr create --title "fix(ship): refuse gh api writes" --body-file body.md',
    "env --split-string='gh api repos/o/r/pulls/7/comments --input reply.json'",
    "env -S'gh api repos/o/r/pulls/7/comments --input reply.json'",
    "env -iS'gh api repos/o/r/pulls/7/comments --input reply.json'",
    'gh 2>/dev/null api repos/o/r/pulls/7/comments --input reply.json',
    'gh 2> /dev/null api repos/o/r/pulls/7/comments --input reply.json',
    'gh >/dev/null api repos/o/r/pulls/7/comments -f body=x',
    'gh </dev/null api repos/o/r/pulls/7/comments -f body=x',
    'gh 2>&1 api repos/o/r/pulls/7/comments -f body=x',
    'gh &>x api repos/o/r/pulls/7/comments -f body=x',
    'gh api repos/o/r/pulls/7/comments 2>&1 -f body=x',
    'gh api repos/o/r/pulls/7/comments >&2 -f body=x',
    "tmux new 'gh 2>/dev/null api repos/o/r/pulls/7/comments -f body=x'",
)

ADMIT = (
    'python3 /abs/plugins/ship/skills/babysit/scripts/thread_reply.py reply https://github.com/o/r/pull/7 PRRT_kwDOabc /abs/.scratch/reply.md',
    'python3 "${CLAUDE_SKILL_DIR}/scripts/thread_reply.py" resolve https://github.com/o/r/pull/7 PRRT_kwDOabc',
    'bash "${CLAUDE_SKILL_DIR}/scripts/threads.sh" 7',
    'gh pr view https://github.com/o/r/pull/7 --json headRefOid',
    'gh pr checks 7 --required',
    'gh api repos/o/r/pulls/7/comments',
    "gh api repos/o/r/pulls/7/comments --jq '.[] | .in_reply_to_id'",
    'gh pr comment 7 --body /better-review',
    'grep -n resolveReviewThread plugins/ship/skills/babysit/SKILL.md',
    'curl -s https://api.linear.app/graphql -H "Authorization: $LINEAR" -d @q.json',
    "git commit -m 'fix(ship): guard thread replies'",
    'gh api repos/o/r/pulls/7/comments -X GET -f per_page=100',
    'gh api repos/o/r/pulls/7/comments -X HEAD',
    "git commit -m 'fix(ship): guard resolveReviewThread calls'",
    "git commit -q -m 'subject' -m 'body names addPullRequestReviewThreadReply'",
    "gh api 'repos/o/r/pulls/7/comments?per_page=100'",
    'gh api https://api.github.com/repos/o/r/pulls/7/comments',
    'gh pr view 7 --json body --jq \'.body | test("`")\'',
    'cd /repo && gh api https://api.github.com/repos/o/r/pulls/7/comments',
    'gh api https://api.github.com/repos/o/r/pulls/7/comments | head -5',
    "gh api 'repos/o/r/pulls/7/comments?per_page=100' --jq '.[].id'",
    'gh pr list --search "is:open author:*"',
    'env GH_TOKEN="$TOKEN" gh api https://api.github.com/repos/o/r/pulls/7/comments',
    'gh api -i repos/o/r/pulls/7/comments',
    "gh api -H 'Accept: application/vnd.github+json' repos/o/r/pulls/7/comments --paginate",
    "gh api -iH 'Accept: application/vnd.github+json' repos/o/r/pulls/7/comments",
    'gh api "repos/o/r/pulls/$PR/comments" --jq \'.[].id\'',
    'gh api -X GET search/issues -fq=value',
    "gh api -X GET search/issues -fq='is:open author:x'",
    'gh api repos/o/r/pulls/7/comments | xargs echo',
    "bash -c 'echo hi'",
    'bash scripts/threads.sh 7 && gh pr view 7',
    'gh api ~',
    'gh api -X GET search/issues -f q=x',
    'bash -n plugins/ship/skills/babysit/scripts/threads.sh',
    'eval "echo hi"',
    'sudo -n true && gh pr view 7',
    'timeout 60 gh pr checks 7 --watch',
    'env --unset=X gh api repos/o/r/pulls/7',
    'gh run watch 123 --exit-status',
    'gh "pr" view 7',
    'watch -n 60 date',
    "env -S 'echo hi'",
    'ssh host uptime',
    "curl -s https://api.linear.app/graphql -d 'route through api'",
    'gh api repos/o/r/pulls/7 2>/dev/null',
    'gh pr view 7 2>&1 | head',
    'gh api repos/o/r/pulls/7 > out.json',
    'gh pr checks 7 &> checks.txt',
)


class HelperTests(unittest.TestCase):
    def lookup(self, repository='o/r', number=7):
        return {'data': {'node': {'__typename': 'PullRequestReviewThread', 'pullRequest': {
            'number': number, 'repository': {'nameWithOwner': repository}}}}}

    def call(self, query, body=None):
        words = PREFIX + ['-f', 'query=' + query, '-f', 'id=' + THREAD]
        return words + (['-f', 'body=' + body] if body is not None else [])

    def run_helper(self, responses, action='reply', pr=PR, thread=THREAD, body='@done\nEvidence: café'):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            stub = folder / 'gh'
            stub.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
log = Path(os.environ['GH_TEST_LOG'])
with log.open('a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
responses = Path(os.environ['GH_TEST_RESPONSES'])
queue = json.loads(responses.read_text())
response = queue.pop(0)
responses.write_text(json.dumps(queue))
print(response['stdout'])
sys.exit(response['code'])
''')
            stub.chmod(0o700)
            log = folder / 'calls.jsonl'
            canned = folder / 'responses.json'
            canned.write_text(json.dumps([{'stdout': value if isinstance(value, str) else json.dumps(value),
                                          'code': code} for value, code in responses]))
            body_file = folder / 'body.txt'
            body_file.write_text(body, encoding='utf-8')
            arguments = [sys.executable, str(HELPER), action, pr, thread]
            if action == 'reply':
                arguments.append(str(body_file))
            result = subprocess.run(arguments, text=True, capture_output=True,
                                    env={**os.environ, 'PATH': directory, 'GH_TEST_LOG': str(log),
                                         'GH_TEST_RESPONSES': str(canned)})
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_reply_checks_ownership_before_sending_raw_body(self):
        body = '@done\nEvidence: café'
        result, calls = self.run_helper([(self.lookup(), 0), ({'data': {
            'addPullRequestReviewThreadReply': {'comment': {'url': COMMENT}}}}, 0)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout, COMMENT + '\n')
        self.assertEqual(calls, [self.call(LOOKUP), self.call(REPLY, body)])

    def test_resolve_checks_ownership_before_resolving(self):
        result, calls = self.run_helper([(self.lookup(), 0), ({'data': {
            'resolveReviewThread': {'thread': {'isResolved': True}}}}, 0)], action='resolve')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout, 'resolved ' + THREAD + '\n')
        self.assertEqual(calls, [self.call(LOOKUP), self.call(RESOLVE)])

    def test_lookup_refusals_never_send_a_mutation(self):
        cases = {
            'repository': (self.lookup('other/repo'), 0),
            'number': (self.lookup(number=8), 0),
            'exit': ('lookup failed', 1),
            'errors': ({'errors': [{'message': 'denied'}], **self.lookup()}, 0),
            'null': ({'data': {'node': None}}, 0),
            'type': ({'data': {'node': {'__typename': 'Issue'}}}, 0),
            'repository missing': ({'data': {'node': {'__typename': 'PullRequestReviewThread',
                                                      'pullRequest': {'number': 7}}}}, 0),
            'json': ('invalid json', 0),
            'shape': ([], 0),
            'number type': (self.lookup(number='7'), 0),
        }
        for name, response in cases.items():
            with self.subTest(case=name):
                result, calls = self.run_helper([response])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(result.stderr.startswith('refused: '), result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(calls, [self.call(LOOKUP)])

    def test_invalid_arguments_make_zero_calls(self):
        cases = [{'pr': pr} for pr in (PR + '/', PR + '?x=1', 'http://github.com/o/r/pull/7',
                                       PR.replace('/7', '/0'), 'x' + PR, PR + '\n')]
        cases += [{'thread': 'PRRT_'}, {'thread': 'PRRC_x'}, {'body': ' \n\t'}]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result, calls = self.run_helper([], **arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(result.stderr.startswith('refused: '), result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(calls, [])

    def test_bad_mutation_results_fail(self):
        for response in ({'data': {'addPullRequestReviewThreadReply': {'comment': {'url': url}}}}
                         for url in ('https://github.com/other/repo/pull/7#discussion_r1', PR + '0#discussion_r1')):
            with self.subTest(response=response):
                result, calls = self.run_helper([(self.lookup(), 0), (response, 0)])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(result.stderr.strip())
                self.assertEqual(result.stdout, '')
                self.assertEqual(calls, [self.call(LOOKUP), self.call(REPLY, '@done\nEvidence: café')])
        for action, query in (('reply', REPLY), ('resolve', RESOLVE)):
            for response in (('failed', 1), ('bad json', 0), ({'errors': []}, 0),
                             ({'data': {'resolveReviewThread': {'thread': {'isResolved': False}}}}, 0)):
                with self.subTest(action=action, response=response):
                    result, calls = self.run_helper([(self.lookup(), 0), response], action=action)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertTrue(result.stderr.strip())
                    self.assertEqual(result.stdout, '')
                    self.assertEqual(calls, [self.call(LOOKUP), self.call(query, '@done\nEvidence: café'
                                                                                  if action == 'reply' else None)])

    def test_repository_names_compare_case_insensitively(self):
        result, calls = self.run_helper([(self.lookup('O/R'), 0), ({'data': {
            'addPullRequestReviewThreadReply': {'comment': {'url': 'https://github.com/O/R/pull/7#discussion_r123'}}}}, 0)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(calls, [self.call(LOOKUP), self.call(REPLY, '@done\nEvidence: café')])


class HookTests(unittest.TestCase):
    def decision(self, command, agent_type):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre({'agent_type': agent_type, 'tool_name': 'Bash', 'tool_input': {'command': command}})
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        return json.loads(text)['hookSpecificOutput'] if text else {}

    def test_refuse_forms_for_every_caller(self):
        for agent_type in ('', 'ship:driver', 'ship:writer--sol'):
            for command in REFUSE:
                with self.subTest(agent_type=agent_type, command=command):
                    result = self.decision(command, agent_type)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    if agent_type != 'ship:writer--sol':
                        self.assertTrue(result['permissionDecisionReason'].startswith(
                            'Ship replies to and resolves review threads only through '))
                        self.assertIn(' Rule: ', result['permissionDecisionReason'])

    def test_admit_forms_for_main_and_driver(self):
        for agent_type in ('', 'ship:driver'):
            for command in ADMIT:
                with self.subTest(agent_type=agent_type, command=command):
                    self.assertEqual(self.decision(command, agent_type), {})

    def test_guard_exception_denies_every_caller(self):
        with patch.object(ultraship, 'review_thread_denial', create=True, side_effect=ValueError('bad parse')):
            for agent_type in ('', 'ship:driver', 'ship:writer--sol'):
                with self.subTest(agent_type=agent_type):
                    result = self.decision('echo hello', agent_type)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn('review-thread guard parse failure', result['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
