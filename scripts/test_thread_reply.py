"""Thread ownership checks and the Bash boundary for review-thread writes."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

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
SENTINEL_FILE = 'should-never-exist'
SENTINEL = f'$(echo x > {SENTINEL_FILE})'

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
    'gh api graphql -f query=\'query($id:ID!){node(id:$id){id}}\' -F id="$THREAD"',
    "gh api graphql --paginate -f query='query($endCursor:String){viewer{repositories(first:10,after:$endCursor){nodes{name}}}}'",
    'gh api repos/o/r/issues/7/comments -f body=hello',
    'gh api graphql -f "query=query{viewer{login}}"',
    'gh api graphql -f query=query{viewer{login}}',
    'bash -c \'gh api graphql -f "query=query{viewer{login}}"\'',
    'gh api repos/{owner}/{repo}/issues/7/comments -f body=hello',
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
    'gh 2>|/dev/null api repos/o/r/pulls/7/comments --input reply.json',
    'gh >| /dev/null api repos/o/r/pulls/7/comments -f body=x',
    'gh api repos/o/r/pulls/7/comments >| out -f body=x',
    'gh >| x api repos/o/r/pulls/7/comments -f body=x',
    'gh 2>|/dev/null api repos/o/r/pulls/7/comments -f body=x',
    'gh api repos/o/r/pulls/7/comments -f body=x >',
    r'true x\>|gh api repos/o/r/pulls/7/comments -f body=x',
    r'true x\>&gh api repos/o/r/pulls/7/comments -f body=x',
    r'true x\<&gh api repos/o/r/pulls/7/comments -f body=x',
    r"tmux new 'true x\>|gh api repos/o/r/pulls/7/comments -f body=x'",
    r'true \\>|gh api repos/o/r/pulls/7/comments -f body=x',
    r'''S=/home/u/ws/.scratch; for i in $(seq 1 60); do h=$(gh pr view 7 --json headRefOid -q .headRefOid 2>/dev/null); if [ "${h:0:12}" = "abc123abc123" ]; then r=$(gh run list --branch b --workflow ci --limit 5 --json databaseId,headSha -q ".[] | select(.headSha==\"$h\") | .databaseId" | head -1); if [ -n "$r" ]; then j=$(gh run view $r --json jobs -q '.jobs[] | select(.name | test("guard")) | "\(.databaseId) \(.status) \(.conclusion)"' 2>/dev/null); case "$j" in *completed*) id=${j%% *}; gh api repos/o/r/actions/jobs/$id/logs > $S/guard.log 2>&1; echo "head=$h"; exit 0;; esac; fi; fi; sleep 90; done''',
    'gh api repos/o/r/pulls/7/comments --jq .[].id',
    'gh pr comment 7 --body-file notes-[0-9].md',
    'gh pr review 7 --approve --body-file r*.md',
    "gh alias set pv 'pr view' && gh pv 7 --jq .[].x",
    'gh $SUB view 7 --jq .[].x',
    'gh {run,api} view 7',
    '/usr/bin/[g]h api repos/o/r/pulls/7/comments -f body=x gh run view 7',
    'echo x | xargs -I run gh run view 7 --jq .[].x',
    "tmux new 'echo `gh api repos/o/r/pulls/7/comments -f body=x`'",
    'bash -c "`gh api repos/o/r/pulls/7/comments --jq .[0].body`"',
    r'echo `echo \`gh api repos/o/r/pulls/7/comments -f body=x\``',
    'gh pr view `echo 7` "x',
    "cat > /home/u/ws/x.md <<'EOF'\ngh api repos/o/r/pulls/7/comments -f body=x\nEOF\ngh pr view 7",
    "cat > /home/u/ws/x.md <<'EOF'\nresolveReviewThread\nEOF\ngh pr view 7",
    "bash -c '`gh pr view 7 --json body --jq .body`'",
    "bash <<'EOF'\necho `gh api repos/o/r/pulls/7/comments -f body=x`\nEOF",
    "cat <<'EOF' | bash\ngh pr view `gh api repos/o/r/pulls/7/comments -f body=x`\nEOF",
    "echo \"\ncat <<'EOF'\n\"; gh api repos/o/r/pulls/7/comments -f body=x\nEOF",
    "cat > /home/u/ws/x.md <<'EOF'\nfoo\\\nEOF\ngh api repos/o/r/pulls/7/comments -f body=x\nEOF",
    "cat > /home/u/ws/x.md <<'EOF'\ngh\\\nEOF\ngh api repos/o/r/pulls/7/comments -f body=x\nEOF",
    "cat <<<'EOF' /home/u/ws/x\nbash -c x\nEOF\ngh pr view 7",
    "cat <<<'EOF'\nbash -c x\nEOF\ngh pr view 7",
)

ADMIT = (
    "gh api graphql -f query='query($owner:String!,$name:String!){repository(owner:$owner,name:$name){id}}' -F owner=o -F name=r",
    "gh api graphql -f 'query=query($id:ID!){node(id:$id){id}}' -F id=PRRT_x",
    "gh api graphql -f query='query{viewer{login}}'",
    "gh api graphql -f query='query{viewer{login}}' && gh api https://api.github.com/user",
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
    'gh api repos/o/r/pulls/7 >| out.json',
    'gh pr view 7 >| out.txt',
    'gh api repos/o/r/pulls/7 | head',
    'gh pr ready https://github.com/o/r/pull/7',
    'gh pr create --title "fix(ship): refuse gh api writes" --body-file body.md',
)

# Two real push checks that read `gh api` once inside a quoted `$(...)`.
QUOTED_READ_PUSHES = (
    "set -euo pipefail\nroot=/w\nw=\"$root/wt/a-pdf-filename\"\ns=\"$root/.scratch/a-pdf-filename\"\napproved=https://github.com/miguelrisero/shunt.git\nbase=e22b65642a4135a90f2abe564528952fe020ca1d\nexport LC_ALL=C\ntest \"$(cat \"$s/upstream-push-preflight.exit\")\" = 0\ntest ! -s \"$s/upstream-push-preflight.stderr\"\ntest \"$(cat \"$s/upstream-push-preflight.stdout\")\" = \"$(printf 'To %s\\n*\\tHEAD:refs/heads/fix/responses-untitled-document-filename\\t[new branch]\\nDone' \"$approved\")\"\ntest \"$(cat \"$s/upstream-push-preflight.command\")\" = 'LC_ALL=C git -C /w/wt/a-pdf-filename -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git push --dry-run --porcelain origin HEAD:refs/heads/fix/responses-untitled-document-filename'\nendpoint=$(git -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git remote get-url --push --all origin 2>/dev/null && printf END)\ntest \"$endpoint\" = \"$(printf '%s\\nEND' \"$approved\")\"\ngit -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git remote get-url --push --all origin\ntest \"$(git -C \"$w\" rev-parse --show-toplevel)\" = \"$w\"\ntest \"$(git -C \"$w\" rev-parse HEAD)\" = ceb993337fe1cd408610fe942e6b0802fd6175bb\ntest \"$(git -C \"$w\" branch --show-current)\" = fix/responses-untitled-document-filename\ntest -z \"$(git -C \"$w\" status --porcelain=v1)\"\ntest -z \"$(git -C \"$w\" rev-parse --abbrev-ref '@{u}' 2>/dev/null || :)\"\ntest \"$(git -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git ls-remote --symref \"$approved\" HEAD refs/heads/fix/responses-untitled-document-filename)\" = \"$(printf 'ref: refs/heads/main\\tHEAD\\n%s\\tHEAD' \"$base\")\"\ntest \"$(gh api repos/pleaseai/shunt/branches/main --jq .commit.sha)\" = \"$base\"\ngit -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git push origin HEAD:refs/heads/fix/responses-untitled-document-filename\ngit -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git ls-remote --exit-code \"$approved\" refs/heads/fix/responses-untitled-document-filename | tee \"$s/upstream-push-ref.txt\"\ntest \"$(cat \"$s/upstream-push-ref.txt\")\" = \"$(printf 'ceb993337fe1cd408610fe942e6b0802fd6175bb\\trefs/heads/fix/responses-untitled-document-filename')\"",
    "set -euo pipefail\nroot=/w\nw=\"$root/wt/e-cache-ttl\"\ns=\"$root/.scratch/e-cache-ttl\"\napproved=https://github.com/miguelrisero/shunt.git\nbase=e22b65642a4135a90f2abe564528952fe020ca1d\nexport LC_ALL=C\ntest \"$(cat \"$s/upstream-push-preflight.exit\")\" = 0\ntest ! -s \"$s/upstream-push-preflight.stderr\"\ntest \"$(cat \"$s/upstream-push-preflight.stdout\")\" = \"$(printf 'To %s\\n*\\tHEAD:refs/heads/feat/metrics-anthropic-cache-ttl-writes\\t[new branch]\\nDone' \"$approved\")\"\ntest \"$(cat \"$s/upstream-push-preflight.command\")\" = 'LC_ALL=C git -C /w/wt/e-cache-ttl -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git push --dry-run --porcelain origin HEAD:refs/heads/feat/metrics-anthropic-cache-ttl-writes'\nendpoint=$(git -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git remote get-url --push --all origin 2>/dev/null && printf END)\ntest \"$endpoint\" = \"$(printf '%s\\nEND' \"$approved\")\"\ngit -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git remote get-url --push --all origin\ntest \"$(git -C \"$w\" rev-parse --show-toplevel)\" = \"$w\"\ntest \"$(git -C \"$w\" rev-parse HEAD 'HEAD^{tree}')\" = \"$(printf '57c2a9debe55e43db4a5c0ef78cfe52d95ad3313\\n0fe40cf2bae042e0a48508a25b19eaef229d269a')\"\ntest \"$(git -C \"$w\" branch --show-current)\" = feat/metrics-anthropic-cache-ttl-writes\ntest -z \"$(git -C \"$w\" status --porcelain=v1)\"\ntest -z \"$(git -C \"$w\" rev-parse --abbrev-ref '@{u}' 2>/dev/null || :)\"\ntest \"$(git -C \"$w\" -c remote.origin.pushurl=https://github.com/miguelrisero/shunt.git ls-remote --symref \"$approved\" HEAD refs/heads/feat/metrics-anthropic-cache-ttl-writes)\" = \"$(printf 'ref: refs/heads/main\\tHEAD\\n%s\\tHEAD' \"$base\")\"\ntest \"$(gh api repos/pleaseai/shunt/branches/main --jq .commit.sha)\" = \"$base\"",
)


class HelperTests(unittest.TestCase):
    def lookup(self, repository='o/r', number=7):
        return {'data': {'node': {'__typename': 'PullRequestReviewThread', 'pullRequest': {
            'number': number, 'repository': {'nameWithOwner': repository}}}}}

    def call(self, query, body=None, after=None):
        words = PREFIX + ['-f', 'query=' + query, '-f', 'id=' + THREAD]
        return (words + (['-f', 'body=' + body] if body is not None else [])
                + (['-f', 'after=' + after] if after is not None else []))

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
            result = subprocess.run(arguments, text=True, capture_output=True, cwd=directory,
                                    env={**os.environ, 'PATH': directory, 'GH_TEST_LOG': str(log),
                                         'GH_TEST_RESPONSES': str(canned)})
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            self.assertFalse((folder / SENTINEL_FILE).exists())
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

    def test_sentinel_substitution_creates_the_file_under_the_harness_path(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['/bin/sh', '-c', 'x=' + SENTINEL], cwd=directory,
                                    env={**os.environ, 'PATH': directory})
            self.assertEqual(result.returncode, 0)
            self.assertTrue((Path(directory) / SENTINEL_FILE).exists())

    def test_read_preserves_complete_bodies_and_attribution(self):
        query = 'query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{author{login}url body}}}}}'
        body = ('<details><summary>Finding</summary>\n\nAction: preserve café 日本語.\n'
                '```sh\nprintf `literal` ' + SENTINEL + '\n```\n'
                '{"looks": "like JSON"}\n</details>\n')
        nodes = [
            {'author': {'login': 'reviewer'}, 'url': COMMENT, 'body': body},
            {'author': None, 'url': PR + '#discussion_r124', 'body': 'Second\ncomment\n'},
            {'author': {'login': 'other'}, 'url': PR.upper() + '?x=1', 'body': ''},
        ]
        page = {'data': {'node': {'comments': {
            'pageInfo': {'hasNextPage': False, 'endCursor': None}, 'nodes': nodes}}}}
        result, calls = self.run_helper([(self.lookup(), 0), (page, 0)], action='read')
        expected = {'thread': THREAD, 'comments': [
            {'author': 'reviewer', 'url': COMMENT, 'body': body},
            {'author': 'ghost', 'url': PR + '#discussion_r124', 'body': 'Second\ncomment\n'},
            {'author': 'other', 'url': PR.upper() + '?x=1', 'body': ''},
        ]}
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout, json.dumps(expected, ensure_ascii=False) + '\n')
        self.assertEqual(calls, [self.call(LOOKUP), self.call(query)])

    def test_read_paginates_in_order_with_exact_cursor_arguments(self):
        query = 'query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{author{login}url body}}}}}'
        nodes = [{'author': {'login': login}, 'url': PR + '#discussion_' + login, 'body': login}
                 for login in ('first', 'second')]
        pages = [{'data': {'node': {'comments': {
            'pageInfo': {'hasNextPage': more, 'endCursor': cursor}, 'nodes': [node]}}}}
            for node, more, cursor in zip(nodes, (True, False), ('cursor=+/café', None))]
        result, calls = self.run_helper([(self.lookup(), 0)] + [(page, 0) for page in pages], action='read')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), {'thread': THREAD, 'comments': [
            {'author': 'first', 'url': PR + '#discussion_first', 'body': 'first'},
            {'author': 'second', 'url': PR + '#discussion_second', 'body': 'second'}]})
        self.assertEqual(calls, [self.call(LOOKUP), self.call(query), self.call(query, after='cursor=+/café')])

    def test_read_refuses_unknown_or_foreign_ownership_before_comment_access(self):
        cases = [self.lookup('foreign/repository'), self.lookup(number=8),
                 {'data': {'node': None}}, {'data': {'node': {'__typename': 'Issue'}}},
                 {'errors': [], **self.lookup()}, [], 'bad json', self.lookup(number='7')]
        for response, code in [(value, 0) for value in cases] + [('failed lookup', 1)]:
            with self.subTest(response=response, code=code):
                result, calls = self.run_helper([(response, code)], action='read')
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(result.stderr.startswith('refused: '), result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(calls, [self.call(LOOKUP)])

    def test_read_invalid_arguments_make_zero_calls(self):
        for arguments in ({'pr': PR + '/'}, {'pr': PR + '\n'}, {'pr': PR.replace('/7', '/0')},
                          {'pr': 'http://github.com/o/r/pull/7'}, {'thread': 'PRRT_'},
                          {'thread': 'PRRC_x'}):
            with self.subTest(arguments=arguments):
                result, calls = self.run_helper([], action='read', **arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(result.stderr.startswith('refused: '), result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(calls, [])

    def test_read_page_failures_keep_stdout_empty_even_after_valid_pages(self):
        query = 'query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{author{login}url body}}}}}'
        comment = {'author': {'login': 'reviewer'}, 'url': COMMENT, 'body': 'Complete\nbody'}
        connection = {'pageInfo': {'hasNextPage': False, 'endCursor': None}, 'nodes': [comment]}
        bad_connections = [
            None, [], {}, {'nodes': [comment]},
            {**connection, 'pageInfo': None}, {**connection, 'pageInfo': []},
            {**connection, 'pageInfo': {}},
            {**connection, 'pageInfo': {'hasNextPage': False}},
            *[{**connection, 'pageInfo': {'hasNextPage': False, 'endCursor': value}}
              for value in ('', 1, [], {})],
            *[{**connection, 'pageInfo': {'hasNextPage': value}} for value in (None, 0, 1, 'false', [], {})],
            {'pageInfo': connection['pageInfo']},
            *[{**connection, 'nodes': value} for value in (None, {}, 'comments', 1)],
            *[{**connection, 'nodes': [value]} for value in (None, [], 'comment', {})],
            *[{**connection, 'nodes': [{**comment, field: value}]}
              for field in ('body', 'url') for value in (None, 1, [], {})],
            *[{**connection, 'nodes': [{key: value for key, value in comment.items() if key != field}]}
              for field in ('author', 'url', 'body')],
            *[{**connection, 'nodes': [{**comment, 'author': value}]}
              for value in ({}, [], 'author', {'login': None}, {'login': 1}, {'login': ''})],
            *[{**connection, 'nodes': [{**comment, 'url': url}]} for url in (
                'https://github.com/foreign/repository/pull/7#discussion_r1',
                PR.replace('/7', '/8') + '#discussion_r1', PR + '0#discussion_r1',
                'http://github.com/o/r/pull/7', 'x' + COMMENT)],
            {**connection, 'pageInfo': {'hasNextPage': True}},
            *[{**connection, 'pageInfo': {'hasNextPage': True, 'endCursor': value}}
              for value in (None, '', 1, [], {})],
        ]
        responses = [('failed page', 1), ('invalid json', 0), ([], 0),
                     ({'errors': [], 'data': {'node': {'comments': connection}}}, 0),
                     ({}, 0), ({'data': None}, 0), ({'data': {}}, 0)]
        responses += [({'data': {'node': node}}, 0) for node in
                      (None, [], 'node', {'__typename': 'Issue'})]
        responses += [({'data': {'node': {'comments': value}}}, 0) for value in bad_connections]
        first = {'data': {'node': {'comments': {
            **connection, 'pageInfo': {'hasNextPage': True, 'endCursor': 'cursor1'}}}}}
        for response in responses:
            for later_page in (False, True):
                with self.subTest(response=response, later_page=later_page):
                    prefix = [(self.lookup(), 0)] + ([(first, 0)] if later_page else [])
                    result, calls = self.run_helper(prefix + [response], action='read')
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertTrue(result.stderr.startswith('failed: '), result.stderr)
                    self.assertEqual(result.stdout, '')
                    expected = [self.call(LOOKUP), self.call(query)]
                    if later_page:
                        expected.append(self.call(query, after='cursor1'))
                    self.assertEqual(calls, expected)

    def test_read_repeated_cursor_fails_before_another_request(self):
        query = 'query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{author{login}url body}}}}}'
        page = {'data': {'node': {'comments': {
            'pageInfo': {'hasNextPage': True, 'endCursor': 'same'},
            'nodes': [{'author': None, 'url': COMMENT, 'body': 'Pending\ncontent'}]}}}}
        result, calls = self.run_helper([(self.lookup(), 0), (page, 0), (page, 0)], action='read')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(result.stderr.startswith('failed: '), result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(calls, [self.call(LOOKUP), self.call(query), self.call(query, after='same')])

    def test_read_empty_thread_and_cursor_cycles_fail_without_mutations(self):
        query = 'query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{author{login}url body}}}}}'
        empty = {'data': {'node': {'comments': {
            'pageInfo': {'hasNextPage': False, 'endCursor': None}, 'nodes': []}}}}
        page = lambda cursor: {'data': {'node': {'comments': {
            'pageInfo': {'hasNextPage': True, 'endCursor': cursor}, 'nodes': []}}}}
        for pages, cursors in (([empty], [None]), ([page('one'), empty], [None, 'one']),
                               ([page('one'), page('two'), page('one')], [None, 'one', 'two'])):
            with self.subTest(pages=pages):
                result, calls = self.run_helper([(self.lookup(), 0)] + [(value, 0) for value in pages], action='read')
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(result.stderr.startswith('failed: '), result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(calls, [self.call(LOOKUP)] + [self.call(query, after=cursor) for cursor in cursors])


page_spec = importlib.util.spec_from_file_location('thread_page_helper', HELPER)
page_helper = importlib.util.module_from_spec(page_spec)
page_spec.loader.exec_module(page_helper)
PAGE_QUERY = ('query($owner:String!,$name:String!,$pr:Int!,$after:String){'
              'repository(owner:$owner,name:$name){nameWithOwner pullRequest(number:$pr){number '
              'reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor}'
              'nodes{id isResolved isOutdated path line comments(first:1){nodes{author{login}url body}}}}}}}')


class ThreadPageTests(unittest.TestCase):
    def response(self):
        return {'data': {'repository': {'nameWithOwner': 'o/r', 'pullRequest': {
            'number': 7, 'reviewThreads': {'pageInfo': {'hasNextPage': False, 'endCursor': None},
            'nodes': [{'id': 'PRRT_example', 'isResolved': False, 'isOutdated': False,
                       'path': 'example.py', 'line': 3, 'comments': {'nodes': [
                           {'author': {'login': 'reviewer'}, 'url': COMMENT, 'body': 'First\nFull preview'}]}}]}}}}}

    def invoke(self, arguments, outputs, clock=None):
        children = []
        def spawn(vector, **options):
            child = Mock(pid=123456, returncode=0, stdout=io.StringIO(), stderr=io.StringIO())
            child.communicate.return_value = (outputs[len(children)].encode('utf-8'), b'')
            children.append(child)
            return child
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(page_helper, 'Popen', side_effect=spawn) as popen, \
                patch.object(page_helper, 'monotonic', side_effect=clock or (lambda: 0)), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = page_helper.main(['page', *arguments])
        return code, stdout.getvalue(), stderr.getvalue(), popen, children

    def test_page_uses_fixed_vectors_and_sanitized_environment(self):
        root = str(ROOT.resolve())
        response = self.response()
        nodes = response['data']['repository']['pullRequest']['reviewThreads']['nodes']
        resolved = copy.deepcopy(nodes[0])
        resolved.update(id='PRRT_resolved', isResolved=True, isOutdated=True, line=None)
        resolved['comments']['nodes'][0]['author'] = None
        nodes.append(resolved)
        cursor = '@cursor/+==;$(echo inert)'
        with patch.dict(os.environ, {'GH_REPO': 'other/repo', 'GH_HOST': 'other.invalid',
                                     'GIT_DIR': '/inert/git', 'GIT_CONFIG_COUNT': '1'}):
            code, out, err, popen, children = self.invoke(
                ['7', cursor], [root + '\n', 'https://github.com/o/r.git\n', json.dumps(response)])
        self.assertEqual((code, err), (0, ''))
        result = json.loads(out)
        self.assertEqual(result, {'repository': 'o/r', 'number': 7,
                                 'pageInfo': {'hasNextPage': False, 'endCursor': None},
                                 'threads': [
                                     {'id': 'PRRT_example', 'isResolved': False, 'isOutdated': False,
                                      'path': 'example.py', 'line': 3, 'comments': [
                                          {'author': 'reviewer', 'url': COMMENT, 'body': 'First\nFull preview'}]},
                                     {'id': 'PRRT_resolved', 'isResolved': True, 'isOutdated': True,
                                      'path': 'example.py', 'line': None, 'comments': [
                                          {'author': 'ghost', 'url': COMMENT, 'body': 'First\nFull preview'}]}]})
        vectors = [call.args[0] for call in popen.call_args_list]
        self.assertEqual(vectors, [
            ['git', 'rev-parse', '--show-toplevel'],
            ['git', 'config', '--local', '--get-all', 'remote.origin.url'],
            ['gh', 'api', '--hostname', 'github.com', 'graphql', '-f', 'query=' + PAGE_QUERY,
             '-f', 'owner=o', '-f', 'name=r', '-F', 'pr=7', '-f', 'after=' + cursor]])
        for call in popen.call_args_list:
            self.assertIs(call.kwargs['shell'], False)
            self.assertNotIn('text', call.kwargs)
            self.assertNotIn('encoding', call.kwargs)
            self.assertNotIn('start_new_session', call.kwargs)
            self.assertNotIn('process_group', call.kwargs)
            self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)
            self.assertFalse(set(call.kwargs['env']) & {'GH_REPO', 'GH_HOST'})
            self.assertFalse(any(key.startswith('GIT_') for key in call.kwargs['env']))
        self.assertEqual(popen.call_args_list[0].kwargs['cwd'], Path.cwd().resolve())
        self.assertEqual([call.kwargs['cwd'] for call in popen.call_args_list[1:]], [ROOT.resolve()] * 2)
        for child in children:
            child.terminate.assert_not_called()
            child.kill.assert_not_called()

    def test_page_rejects_inputs_before_starting_children(self):
        for arguments in ([], ['0'], ['-1'], ['01'], ['1.0'], ['2147483648'], ['99999999999'],
                          ['7', ''], ['7', '\x00'], ['7', 'cursor', 'extra'],
                          ['--host', 'example.invalid'], ['--query', 'query{viewer{login}}']):
            with self.subTest(arguments=arguments):
                code, out, err, popen, _ = self.invoke(arguments, [])
                self.assertEqual((code, out), (1, ''))
                self.assertTrue(err.startswith('failed: '))
                popen.assert_not_called()

    def test_page_validates_local_origin_before_github_access(self):
        root = str(ROOT.resolve()) + '\n'
        for origin in ('', 'https://github.com/o/r\nhttps://github.com/o/other\n',
                       'git@github.com:o/r.git\n', 'https://user:secret@github.com/o/r\n',
                       'https://example.invalid/o/r\n', 'https://github.com/o/r?token=secret\n'):
            with self.subTest(origin=origin):
                code, out, err, popen, _ = self.invoke(['7'], [root, origin])
                self.assertEqual((code, out, popen.call_count), (1, '', 2))
                self.assertNotIn('secret', err)
        for root_text in ('', 'relative/path\n', '/one\n/two\n'):
            with self.subTest(root=root_text):
                code, out, _, popen, _ = self.invoke(['7'], [root_text])
                self.assertEqual((code, out, popen.call_count), (1, '', 1))

    def test_page_accepts_boundary_pr_and_progressing_cursor(self):
        response = self.response()
        pull = response['data']['repository']['pullRequest']
        pull['number'] = 2147483647
        pull['reviewThreads']['nodes'][0]['comments']['nodes'][0]['url'] = (
            'https://github.com/o/r/pull/2147483647#discussion_r123')
        pull['reviewThreads']['pageInfo'] = {'hasNextPage': True, 'endCursor': 'next/+=='}
        code, out, err, popen, _ = self.invoke(['2147483647'], [
            str(ROOT.resolve()) + '\n', 'https://github.com/o/r\n', json.dumps(response)])
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['pageInfo'], {'hasNextPage': True, 'endCursor': 'next/+=='})
        self.assertEqual(popen.call_args.args[0][-2:], ['-F', 'pr=2147483647'])

    def test_page_malformed_response_emits_zero_partial_threads(self):
        cases = [None, [], {}, {'errors': []}, {'data': None}]
        base = self.response()
        for repository in ('other/repo', None, 1):
            value = copy.deepcopy(base)
            value['data']['repository']['nameWithOwner'] = repository
            cases.append(value)
        for number in (8, '7', True):
            value = copy.deepcopy(base)
            value['data']['repository']['pullRequest']['number'] = number
            cases.append(value)
        for page in ({}, None, {'hasNextPage': 1, 'endCursor': None},
                     {'hasNextPage': True, 'endCursor': None}, {'hasNextPage': True, 'endCursor': 'same'},
                     {'hasNextPage': False, 'endCursor': ''}, {'hasNextPage': False, 'endCursor': 1}):
            value = copy.deepcopy(base)
            value['data']['repository']['pullRequest']['reviewThreads']['pageInfo'] = page
            cases.append(value)
        for key, bad in (('id', 'other'), ('id', None), ('isResolved', 1), ('isOutdated', None),
                         ('path', ''), ('line', True), ('line', 0), ('comments', {})):
            value = copy.deepcopy(base)
            nodes = value['data']['repository']['pullRequest']['reviewThreads']['nodes']
            invalid = copy.deepcopy(nodes[0])
            invalid['id'] = 'PRRT_second'
            invalid[key] = bad
            nodes.append(invalid)
            cases.append(value)
        for field, bad in (('author', {}), ('author', {'login': ''}), ('body', None),
                           ('url', 'https://github.com/foreign/repo/pull/7#discussion_r1')):
            value = copy.deepcopy(base)
            value['data']['repository']['pullRequest']['reviewThreads']['nodes'][0]['comments']['nodes'][0][field] = bad
            cases.append(value)
        for bad in (None, {}, 'threads'):
            value = copy.deepcopy(base)
            value['data']['repository']['pullRequest']['reviewThreads']['nodes'] = bad
            cases.append(value)
        value = copy.deepcopy(base)
        nodes = value['data']['repository']['pullRequest']['reviewThreads']['nodes']
        nodes.append(copy.deepcopy(nodes[0]))
        cases.append(value)
        for response in cases:
            with self.subTest(response=response):
                code, out, err, _, _ = self.invoke(['7', 'same'], [
                    str(ROOT.resolve()) + '\n', 'https://github.com/o/r\n', json.dumps(response)])
                self.assertEqual((code, out), (1, ''))
                self.assertTrue(err.startswith('failed: '))

    def test_page_shared_deadline_reduces_each_child_timeout(self):
        now = [0]
        calls = []
        outputs = [str(ROOT.resolve()) + '\n', 'https://github.com/o/r\n', json.dumps(self.response())]
        def spawn(vector, **options):
            child = Mock(pid=123456, returncode=0, stdout=io.StringIO(), stderr=io.StringIO())
            index = len(calls)
            def communicate(timeout):
                calls.append(timeout)
                now[0] += 4
                return outputs[index].encode('utf-8'), b''
            child.communicate.side_effect = communicate
            return child
        with patch.object(page_helper, 'Popen', side_effect=spawn), \
                patch.object(page_helper, 'monotonic', side_effect=lambda: now[0]):
            page_helper.thread_page(['7'])
        self.assertEqual(calls, [29, 25, 21])

    def lifecycle(self, term_latency=0, term_error=False, wait_exit=False, identity=True, start=0):
        now, events = [start], []
        child = Mock(pid=123456, returncode=None, stdout=io.StringIO(), stderr=io.StringIO())
        process = object.__new__(page_helper.PageProcess)
        process.work_deadline, process.transport_deadline, process.deadline = 30, 29, 40
        process.overhead = 0
        process.child, process.pid, process.reaped = child, child.pid, False
        def terminate():
            events.append(('TERM', now[0]))
            now[0] += term_latency
            if term_error:
                raise OSError('synthetic TERM failure')
        def wait(timeout):
            events.append(('wait', now[0], timeout))
            if wait_exit or any(event[0] == 'KILL' for event in events):
                child.returncode = 0
                return 0
            now[0] += timeout
            raise subprocess.TimeoutExpired('synthetic', timeout)
        child.terminate.side_effect = terminate
        child.kill.side_effect = lambda: events.append(('KILL', now[0]))
        child.wait.side_effect = wait
        state = None if identity else Mock(si_pid=123457)
        with patch.object(page_helper, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(page_helper.os, 'waitid', return_value=state):
            try:
                process.cleanup(child, 123456)
                error = None
            except ValueError as caught:
                error = str(caught)
        return events, error, child

    def test_lifecycle_preserves_full_post_term_grace_and_bounded_reap(self):
        events, error, _ = self.lifecycle(term_latency=0.5, start=29)
        self.assertIsNone(error)
        self.assertEqual(events, [('TERM', 29), ('wait', 29.5, 5), ('KILL', 34.5), ('wait', 34.5, 5)])

    def test_lifecycle_insufficient_reserve_and_term_failure_never_kill(self):
        for options in ({'term_latency': 1, 'start': 30}, {'term_error': True, 'start': 25}, {'start': 40}):
            with self.subTest(options=options):
                events, error, child = self.lifecycle(**options)
                self.assertIn('unsettled', error)
                self.assertFalse(any(event[0] in ('KILL', 'wait') for event in events))
                child.kill.assert_not_called()

    def test_lifecycle_early_exit_and_uncertain_identity_never_signal(self):
        events, error, child = self.lifecycle(wait_exit=True, start=25)
        self.assertIsNone(error)
        self.assertEqual(events, [('TERM', 25), ('wait', 25, 5)])
        child.kill.assert_not_called()
        events, error, child = self.lifecycle(identity=False, start=25)
        self.assertIn('uncertain', error)
        self.assertEqual(events, [])
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_page_work_timeout_cleans_only_owned_child_and_emits_zero_stdout(self):
        now, events = [0], []
        child = Mock(pid=123456, returncode=None, stdout=io.StringIO(), stderr=io.StringIO())
        def communicate(timeout):
            now[0] += timeout
            raise subprocess.TimeoutExpired('synthetic', timeout)
        def wait(timeout):
            events.append(('wait', now[0], timeout))
            if now[0] < 34:
                now[0] += timeout
                raise subprocess.TimeoutExpired('synthetic', timeout)
            child.returncode = -9
            return -9
        child.communicate.side_effect = communicate
        child.wait.side_effect = wait
        child.terminate.side_effect = lambda: events.append(('TERM', now[0]))
        child.kill.side_effect = lambda: events.append(('KILL', now[0]))
        out, err = io.StringIO(), io.StringIO()
        with patch.object(page_helper, 'Popen', return_value=child), \
                patch.object(page_helper, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(page_helper.os, 'waitid', return_value=None), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = page_helper.main(['page', '7'])
        self.assertEqual((code, out.getvalue()), (1, ''))
        self.assertEqual(events, [('TERM', 29), ('wait', 29, 5), ('KILL', 34), ('wait', 34, 5)])
        self.assertTrue(err.getvalue().startswith('failed: '))

    def test_page_empty_final_page_and_total_expiry(self):
        response = self.response()
        response['data']['repository']['pullRequest']['reviewThreads']['nodes'] = []
        outputs = [str(ROOT.resolve()) + '\n', 'https://github.com/o/r\n', json.dumps(response)]
        code, out, err, _, _ = self.invoke(['7'], outputs)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['threads'], [])
        real_dumps = json.dumps
        now = [0]
        def serialize(value, **options):
            result = real_dumps(value, **options)
            now[0] = 40
            return result
        with patch.object(page_helper.json, 'dumps', side_effect=serialize):
            code, out, err, _, _ = self.invoke(['7'], outputs, clock=lambda: now[0])
        self.assertEqual((code, out, err), (1, '', 'failed: thread page unavailable.\n'))

    def test_page_exhausted_work_reserve_starts_zero_children(self):
        with patch.object(page_helper, 'monotonic', side_effect=[0, 30]), \
                patch.object(page_helper, 'Popen') as popen:
            process = page_helper.PageProcess()
            with self.assertRaisesRegex(ValueError, 'work budget'):
                process.run(['git', 'rev-parse', '--show-toplevel'], ROOT)
        popen.assert_not_called()

    def test_page_cleanup_errors_keep_owned_child_and_fixed_unsettled_output(self):
        for failure in ('term', 'kill', 'wait', 'reap_timeout', 'identity', 'observation', 'cached', 'stream', 'reserve'):
            with self.subTest(failure=failure):
                now, processes, events = [0], [], []
                child = Mock(pid=123456, returncode=None, stdout=io.StringIO(), stderr=io.StringIO())
                def communicate(timeout):
                    if failure == 'stream':
                        child.returncode = 0
                        child.stdout = Mock()
                        child.stdout.close.side_effect = OSError('private stream error')
                        return (str(ROOT.resolve()) + '\n').encode('utf-8'), b''
                    now[0] += timeout
                    if failure == 'cached':
                        child.returncode = 0
                    raise subprocess.TimeoutExpired('synthetic', timeout)
                def terminate():
                    events.append('TERM')
                    if failure == 'term':
                        raise OSError('private TERM error')
                    if failure == 'reserve':
                        now[0] += 2
                def wait(timeout):
                    if failure == 'wait':
                        raise OSError('private wait error')
                    now[0] += timeout
                    raise subprocess.TimeoutExpired('synthetic', timeout)
                def kill():
                    events.append('KILL')
                    if failure == 'kill':
                        raise OSError('private KILL error')
                child.communicate.side_effect = communicate
                child.terminate.side_effect = terminate
                child.kill.side_effect = kill
                child.wait.side_effect = wait
                original = page_helper.PageProcess.__init__
                def initialize(process):
                    original(process)
                    processes.append(process)
                state = Mock(si_pid=123457) if failure == 'identity' else None
                cleanup_errors = []
                original_cleanup = page_helper.PageProcess.cleanup
                def cleanup(owner, process, pid):
                    try:
                        return original_cleanup(owner, process, pid)
                    except page_helper.CleanupUnsettled as error:
                        cleanup_errors.append(error)
                        raise
                out, err = io.StringIO(), io.StringIO()
                with patch.object(page_helper.PageProcess, '__init__', initialize), \
                        patch.object(page_helper.PageProcess, 'cleanup', cleanup), \
                        patch.object(page_helper, 'Popen', return_value=child), \
                        patch.object(page_helper, 'monotonic', side_effect=lambda: now[0]), \
                        patch.object(page_helper.os, 'waitid', return_value=state,
                                     side_effect=OSError('private observation error')
                                     if failure == 'observation' else None), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = page_helper.main(['page', '7'])
                self.assertEqual((code, out.getvalue(), err.getvalue()), (
                    1, '', 'failed: thread page unavailable. Cleanup unsettled.\n'))
                self.assertIs(processes[0].child, child)
                self.assertEqual(processes[0].pid, 123456)
                self.assertEqual(processes[0].reaped, failure == 'stream')
                self.assertEqual(len(cleanup_errors), 0 if failure == 'stream' else 1)
                if cleanup_errors:
                    self.assertIsInstance(cleanup_errors[0], page_helper.CleanupUnsettled)
                if failure in ('term', 'wait', 'identity', 'observation', 'cached', 'stream', 'reserve'):
                    child.kill.assert_not_called()
                if failure in ('identity', 'observation', 'cached', 'stream'):
                    child.terminate.assert_not_called()
                self.assertLessEqual(now[0], 40)

    def test_cleanup_completed_child_requires_verified_reap(self):
        process = object.__new__(page_helper.PageProcess)
        child = Mock(pid=123456, returncode=None)
        process.child, process.pid, process.reaped = child, child.pid, False
        process.deadline = 40
        process.overhead = 0
        def wait(timeout):
            child.returncode = 0
            return 0
        child.wait.side_effect = wait
        with patch.object(page_helper, 'monotonic', return_value=0), \
                patch.object(page_helper.os, 'waitid', return_value=Mock(si_pid=123456)):
            process.cleanup(child, child.pid)
        self.assertTrue(process.reaped)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()
        process.reaped = False
        with self.assertRaises(page_helper.CleanupUnsettled):
            process.cleanup(child, child.pid)
        self.assertFalse(process.reaped)

    def test_cleanup_rechecks_identity_before_escalation(self):
        now = [25]
        process = object.__new__(page_helper.PageProcess)
        child = Mock(pid=123456, returncode=None)
        process.child, process.pid, process.reaped = child, child.pid, False
        process.deadline, process.transport_deadline = 40, 29
        process.overhead = 0
        def wait(timeout):
            now[0] += timeout
            child.pid = 123457
            raise subprocess.TimeoutExpired('synthetic', timeout)
        child.wait.side_effect = wait
        with patch.object(page_helper, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(page_helper.os, 'waitid', return_value=None):
            with self.assertRaises(page_helper.CleanupUnsettled):
                process.cleanup(child, 123456)
        child.terminate.assert_called_once()
        child.kill.assert_not_called()
        self.assertIs(process.child, child)
        self.assertEqual(process.pid, 123456)

    def test_page_transport_failures_hide_child_output(self):
        for failure in ('spawn', 'exit', 'json', 'encoding'):
            children = []
            outputs = [(str(ROOT.resolve()) + '\n').encode(), b'https://github.com/o/r\n',
                       b'\xff' if failure == 'encoding' else b'private malformed payload']
            def spawn(vector, **options):
                if failure == 'spawn':
                    raise OSError('private spawn error')
                child = Mock(pid=123456, returncode=1 if failure == 'exit' else 0,
                             stdout=io.BytesIO(), stderr=io.BytesIO())
                child.communicate.return_value = (outputs[len(children)], b'private stderr')
                children.append(child)
                return child
            out, err = io.StringIO(), io.StringIO()
            with patch.object(page_helper, 'monotonic', return_value=0), \
                    patch.object(page_helper, 'Popen', side_effect=spawn) as popen, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = page_helper.main(['page', '7'])
            self.assertEqual((code, out.getvalue()), (1, ''))
            self.assertEqual(err.getvalue(), 'failed: thread page unavailable.\n')
            self.assertEqual(popen.call_count, 3 if failure in ('json', 'encoding') else 1)
            for child in children:
                child.terminate.assert_not_called()
                child.kill.assert_not_called()

    def test_page_identity_capability_blocks_child_start(self):
        for capability in (None, 'unavailable'):
            with self.subTest(capability=capability), \
                    patch.object(page_helper.os, 'waitid', capability):
                code, out, err, popen, _ = self.invoke(['7'], [])
                self.assertEqual((code, out, err), (
                    1, '', 'failed: thread page unavailable. Cleanup unsettled.\n'))
                popen.assert_not_called()

    def test_page_empty_progress_and_nonexistent_root_fail_closed(self):
        response = self.response()
        connection = response['data']['repository']['pullRequest']['reviewThreads']
        connection['nodes'] = []
        connection['pageInfo'] = {'hasNextPage': True, 'endCursor': 'next'}
        code, out, err, _, _ = self.invoke(['7'], [
            str(ROOT.resolve()) + '\n', 'https://github.com/o/r\n', json.dumps(response)])
        self.assertEqual((code, out, err), (1, '', 'failed: thread page unavailable.\n'))
        with tempfile.TemporaryDirectory() as directory:
            absent = str(Path(directory) / 'absent')
            code, out, err, popen, _ = self.invoke(['7'], [absent + '\n'])
        self.assertEqual((code, out, err, popen.call_count), (
            1, '', 'failed: thread page unavailable.\n', 1))

    def test_cleanup_primary_error_survives_secondary_stream_error(self):
        now = [0]
        process = page_helper.PageProcess
        instances = []
        child = Mock(pid=123456, returncode=None, stdout=Mock(), stderr=Mock())
        child.stdout.close.side_effect = OSError('secondary close error')
        child.terminate.side_effect = OSError('primary TERM error')
        def communicate(timeout):
            now[0] += timeout
            raise subprocess.TimeoutExpired('synthetic', timeout)
        child.communicate.side_effect = communicate
        original = process.__init__
        def initialize(instance):
            original(instance)
            instances.append(instance)
        with patch.object(page_helper, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(page_helper, 'Popen', return_value=child), \
                patch.object(page_helper.os, 'waitid', return_value=None), \
                patch.object(process, '__init__', initialize):
            owner = process()
            with self.assertRaisesRegex(page_helper.CleanupUnsettled, 'child cleanup failed'):
                owner.run(['git', 'rev-parse', '--show-toplevel'], ROOT)
        self.assertIs(instances[0].child, child)
        self.assertFalse(instances[0].reaped)
        child.kill.assert_not_called()

    def test_transport_overhead_below_and_above_allowance(self):
        for latency, expected_unsettled in ((0.125, False), (0.5, True)):
            with self.subTest(latency=latency):
                now, events, owners = [0], [], []
                child = Mock(pid=123456, returncode=None, stdout=io.BytesIO(), stderr=io.BytesIO())
                def spawn(vector, **options):
                    now[0] += latency
                    return child
                def communicate(timeout):
                    now[0] += timeout + latency
                    raise subprocess.TimeoutExpired('synthetic', timeout)
                def terminate():
                    events.append(('TERM', now[0]))
                    now[0] += latency
                def wait(timeout):
                    events.append(('wait', now[0], timeout))
                    if any(event[0] == 'KILL' for event in events):
                        child.returncode = -9
                        return -9
                    now[0] += timeout
                    raise subprocess.TimeoutExpired('synthetic', timeout)
                child.communicate.side_effect = communicate
                child.terminate.side_effect = terminate
                child.wait.side_effect = wait
                child.kill.side_effect = lambda: events.append(('KILL', now[0]))
                original = page_helper.PageProcess.__init__
                def initialize(owner):
                    original(owner)
                    owners.append(owner)
                out, err = io.StringIO(), io.StringIO()
                with patch.object(page_helper.PageProcess, '__init__', initialize), \
                        patch.object(page_helper, 'monotonic', side_effect=lambda: now[0]), \
                        patch.object(page_helper, 'Popen', side_effect=spawn), \
                        patch.object(page_helper.os, 'waitid', return_value=None), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = page_helper.main(['page', '7'])
                self.assertEqual((code, out.getvalue()), (1, ''))
                self.assertEqual(err.getvalue(), 'failed: thread page unavailable.'
                                 + (' Cleanup unsettled.' if expected_unsettled else '') + '\n')
                self.assertIs(owners[0].child, child)
                self.assertLessEqual(now[0], 40)
                if expected_unsettled:
                    child.kill.assert_not_called()
                    self.assertFalse(owners[0].reaped)
                else:
                    self.assertEqual(events, [('TERM', 29.125), ('wait', 29.25, 5),
                                              ('KILL', 34.25), ('wait', 34.25, 5)])
                    self.assertTrue(owners[0].reaped)

    def test_page_synthetic_git_and_gh_path_stubs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            script = f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
vector = sys.argv[1:]
with Path(os.environ['PAGE_LOG']).open('a') as stream:
    stream.write(json.dumps({'program': Path(sys.argv[0]).name, 'vector': vector,
                             'cwd': os.getcwd(), 'keys': sorted(os.environ)}) + '\\n')
if Path(sys.argv[0]).name == 'git':
    if vector == ['rev-parse', '--show-toplevel']:
        print(os.environ['PAGE_ROOT'])
    elif vector == ['config', '--local', '--get-all', 'remote.origin.url']:
        print('https://github.com/o/r.git')
    else:
        sys.exit(9)
else:
    print(os.environ['PAGE_RESPONSE'])
    sys.exit(int(os.environ['PAGE_EXIT']))
'''
            for name in ('git', 'gh'):
                path = folder / name
                path.write_text(script)
                path.chmod(0o700)
            for status in ('0', '1'):
                log = folder / ('calls-' + status)
                stdout, stderr = io.StringIO(), io.StringIO()
                environment = {**os.environ, 'PATH': directory, 'PAGE_ROOT': str(folder),
                               'PAGE_LOG': str(log), 'PAGE_RESPONSE': json.dumps(self.response()),
                               'PAGE_EXIT': status, 'GH_REPO': 'foreign/repo',
                               'GH_HOST': 'other.invalid', 'GIT_DIR': '/inert/git'}
                protocol_overhead = property(lambda process: 0, lambda process, value: None)
                with patch.dict(os.environ, environment, clear=True), \
                        patch.object(page_helper.Path, 'cwd', return_value=folder), \
                        patch.object(page_helper.PageProcess, 'overhead', protocol_overhead, create=True), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = page_helper.main(['page', '7', 'opaque/+=='])
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual([call['program'] for call in calls], ['git', 'git', 'gh'])
                for call in calls:
                    self.assertEqual(call['cwd'], str(folder.resolve()))
                    self.assertFalse(set(call['keys']) & {'GH_HOST', 'GH_REPO'})
                    self.assertFalse(any(key.startswith('GIT_') for key in call['keys']))
                self.assertEqual(calls[-1]['vector'], [
                    'api', '--hostname', 'github.com', 'graphql', '-f', 'query=' + PAGE_QUERY,
                    '-f', 'owner=o', '-f', 'name=r', '-F', 'pr=7', '-f', 'after=opaque/+=='])
                if status == '0':
                    self.assertEqual((code, stderr.getvalue()), (0, ''))
                    self.assertEqual(json.loads(stdout.getvalue())['threads'][0]['id'], 'PRRT_example')
                else:
                    self.assertEqual((code, stdout.getvalue()), (1, ''))
                    self.assertEqual(stderr.getvalue(), 'failed: thread page unavailable.\n')


class HookTests(unittest.TestCase):
    def decision(self, command, agent_type, cwd=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre({'agent_type': agent_type, 'cwd': cwd, 'tool_name': 'Bash',
                               'tool_input': {'command': command}})
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        return json.loads(text)['hookSpecificOutput'] if text else {}

    def test_documented_read_command_is_admitted_for_main_and_driver(self):
        command = 'python3 "${CLAUDE_SKILL_DIR}/scripts/thread_reply.py" read https://github.com/o/r/pull/7 PRRT_kwDOabc'
        for agent_type in ('ship:driver', ''):
            with self.subTest(agent_type=agent_type):
                self.assertEqual(self.decision(command, agent_type), {})

    def test_fixed_page_action_is_admitted_for_main_and_driver(self):
        for cursor in ('', ' cursor/+==', " '@cursor/+=='"):
            command = 'python3 "${CLAUDE_SKILL_DIR}/scripts/thread_reply.py" page 7' + cursor
            for caller in ('', 'ship:driver'):
                with self.subTest(cursor=cursor, caller=caller):
                    self.assertEqual(self.decision(command, caller), {})

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

    def test_literal_pr_comment_body_is_data_for_main_and_driver(self):
        bodies = (
            r"$'§9 summary for `example`\n\nThe sample text names GIT_CONFIG_COUNT and --config-env.'",
            "'Summary\nExample: gh pr view 7\nA literal \" mark'",
            '"Summary\nA literal \\" mark"',
        )
        for body in bodies:
            command = f'gh pr comment {PR} --body {body}'
            for caller in ('', 'ship:driver', 'ship:writer--sol'):
                with self.subTest(body=body, caller=caller):
                    result = self.decision(command, caller)
                    if caller == 'ship:writer--sol':
                        self.assertEqual(result.get('permissionDecision'), 'deny')
                    else:
                        self.assertEqual(result, {})

    def test_pr_comment_mask_requires_one_complete_literal_invocation(self):
        prefix = f'gh pr comment {PR} --body '
        commands = (
            prefix + '"$BODY"',
            prefix + "$'unfinished",
            prefix + "'first'$'second'",
            prefix + "$'\\n'",
            prefix + "'Summary' > output.txt",
            prefix + "'Summary' --edit-last",
            'env ' + prefix + "'Summary'",
            prefix.replace(PR, '$PR') + "'Summary'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(ultraship.pr_comment_body_removed(command), command)

    def test_pr_comment_preserves_config_and_thread_denials(self):
        command = f"gh pr comment {PR} --body 'Summary'"
        cases = (
            ('GIT_CONFIG_COUNT=2 ' + command, 'git config from the command line'),
            (command + '\ngit --config-env=core.pager=PAGER status', 'git config from the command line'),
            (command + ' && gh api repos/o/r/pulls/7/comments/123/replies -f body=sample',
             'raw review-thread mutation'),
        )
        for shell, rule in cases:
            for caller in ('', 'ship:driver'):
                with self.subTest(shell=shell, caller=caller):
                    result = self.decision(shell, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(f' Rule: {rule}.', result['permissionDecisionReason'])

    def test_quoted_gh_api_read_counts_once(self):
        commands = QUOTED_READ_PUSHES + ('test "$(gh api repos/o/r/branches/main --jq .commit.sha)" = abc',)
        for command in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command[:60], caller=caller):
                    self.assertEqual(self.decision(command, caller), {})

    def test_quoted_gh_api_write_stays_refused(self):
        command = 'test "$(gh api -X POST repos/o/r/issues/7/comments -f body=x)" = abc'
        for caller in ('', 'ship:driver', 'ship:writer--sol'):
            with self.subTest(caller=caller):
                self.assertEqual(self.decision(command, caller).get('permissionDecision'), 'deny')

    def test_quoted_grep_pattern_in_pipeline_is_data(self):
        command = '''cd /repo && grep -nE 'gh [^"]+' docs/notes.md | head -n 5'''
        nested_write = 'test "$(gh api -X POST repos/o/r/pulls/7/comments -f body=x)" = abc'
        for caller in ('', 'ship:driver', 'ship:writer--sol'):
            with self.subTest(caller=caller):
                self.assertEqual(self.decision(command, caller), {})
                result = self.decision(command + ' && ' + nested_write, caller)
                self.assertEqual(result.get('permissionDecision'), 'deny')
                rule = ('writer GitHub read-only rule' if caller == 'ship:writer--sol'
                        else 'REST review-comment write or opaque endpoint.')
                self.assertIn(' Rule: ' + rule, result['permissionDecisionReason'])
        expanded = 'grep -nE "$(gh pr create --title x)" docs/notes.md | head -n 5'
        result = self.decision(expanded, 'ship:writer--sol')
        self.assertEqual(result.get('permissionDecision'), 'deny')
        self.assertIn('Writers never push', result['permissionDecisionReason'])

    def test_writer_quoted_grep_end_anchor_is_data(self):
        command = '''cd /repo && grep -nE 'gh [^"]+$' docs/notes.md | head -n 5'''
        self.assertIsNone(ultraship.writer_gh_denial_main(command))
        self.assertIsNone(ultraship.writer_gh_denial(command))
        self.assertEqual(self.decision(command, 'ship:writer--sol'), {})

    def test_static_graphql_read_documents(self):
        documents = (
            '{repository(owner:"o",name:"r"){pullRequests(first:5){nodes{number files(first:10){nodes{path}}}}}}',
            'query ReadViewer {viewer{login}}',
            'query mutation {viewer{login}}',
            'query Read($id:ID! = "x") @skip(if:false) {node(id:$id){id}}',
            '{field(value:"} mutation \\" text"){id}}',
            '{field(value:"""} mutation"""){id}}',
            '{viewer{# mutation }\nlogin}}',
            chr(0xFEFF) + ',query Read {viewer{login}}',
            '{field(value:"tab	x")}',
        )
        for document in documents:
            command = "gh api graphql -f query='" + document + "' --jq '.data.repository'"
            for caller in ('', 'ship:driver'):
                with self.subTest(document=document, caller=caller):
                    self.assertEqual(self.decision(command, caller), {})
            with self.subTest(document=document, caller='writer'):
                self.assertEqual(self.decision(command, 'ship:writer--sol').get('permissionDecision'), 'deny')

    def test_graphql_scalar_variables_keep_unsafe_inputs_refused(self):
        read = "gh api graphql -f query='query($id:ID!){node(id:$id){id}}'"
        commands = (
            ("gh api graphql -f query='mutation($id:ID!){deleteIssue(input:{issueId:$id}){clientMutationId}}' -F id=x",
             'gh api write outside the helper'),
            ("gh api graphql -f query='query{viewer{login}} mutation{deleteIssue(input:{issueId:\"x\"}){clientMutationId}}' -F id=x",
             'gh api write outside the helper'),
            (read + " -f query='query{viewer{id}}' -F id=x", 'gh api write outside the helper'),
            ("gh api graphql -F query=@query.graphql -F id=x", 'opaque GraphQL query'),
            (read + ' --input payload.json -F id=x', 'opaque GraphQL query'),
            (read + ' -F id=@identifier.txt', 'gh api write outside the helper'),
            (read + ' -F id="$ID"', 'gh api write outside the helper'),
            (read + ' -F id=$(cat identifier.txt)', 'review-thread guard parse failure'),
            (read + ' -F id=x -F id=y', 'gh api write outside the helper'),
            (read + " -F 'id[]=x'", 'gh api write outside the helper'),
            (read + " -F 'id[value]=x'", 'gh api write outside the helper'),
            (read + ' -F undeclared=x', 'gh api write outside the helper'),
        )
        for command, reason in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    result = self.decision(command, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(' Rule: ' + reason + '.', result['permissionDecisionReason'])

    def test_executable_arguments_keep_shell_runner_refusals(self):
        commands = (
            "bash -c 'gh pr view 7'",
            "eval 'gh pr view 7'",
            "source /dev/stdin <<<'gh pr view 7'",
            "watch -n 60 'gh pr view 7'",
            "python3 /repo/scripts/record.py append \"$(bash -c 'gh pr view 7')\"",
        )
        for command in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    result = self.decision(command, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(' Rule: shell runner names gh.', result['permissionDecisionReason'])

    def test_literal_git_grep_end_anchor_is_data(self):
        command = "git -C /work/example grep -n -E '^.{121,}$' abc123 -- src/example.py"
        for search in (command, command.replace('src/example.py', 'src/api/example.py')):
            for caller in ('', 'ship:driver', 'ship:writer--sol'):
                with self.subTest(search=search, caller=caller):
                    self.assertEqual(self.decision(search, caller), {})

    def test_git_grep_end_anchor_keeps_config_and_ansi_quote_refusals(self):
        search = "git -C /work/example grep -n -E '^.{121,}$' abc123 -- src/api/example.py"
        commands = (
            'GIT_CONFIG_COUNT=2 ' + search,
            search.replace(' grep ', ' --config-env=core.pager=PAGER grep '),
            search + "; printf '%s' $'api'",
        )
        for command in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    result = self.decision(command, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(' Rule: git config from the command line.', result['permissionDecisionReason'])

    def test_actual_ansi_quotes_keep_the_caller_refusal(self):
        commands = (
            "printf '%s' $'api'",
            "printf '%s' $'gh'",
            "printf '%s' $'api' && grep -v '^$' /repo/notes.txt",
            "grep -v '^$' /repo/notes.txt; printf '%s' $'api'",
            "grep -nE 'gh [^\"]+$' /repo/notes.txt; printf '%s' $'api'",
        )
        for command in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    result = self.decision(command, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(' Rule: git config from the command line.', result['permissionDecisionReason'])

    def test_git_count_pipeline_treats_grep_anchor_as_data(self):
        command = r'''echo "files: $(git ls-tree -r --name-only abc123 -- src/api/ | grep -c '\.toml$')"'''
        refused = (
            ('GIT_CONFIG_COUNT=2; ' + command, 'git config from the command line'),
            (command + "; printf '%s' $'api'", 'git config from the command line'),
            (command + '; echo "$(printf \'%s\' $\'api\')"', 'git config from the command line'),
            (command + '; echo "$(gh api repos/o/r/pulls/7/comments -f body=x)"', 'REST review-comment write'),
        )
        for caller in ('', 'ship:driver'):
            self.assertEqual(self.decision(command, caller), {})
            self.assertEqual(self.decision('cd /work/example && ' + command, caller), {})
            for shell, rule in refused:
                with self.subTest(caller=caller, rule=rule):
                    result = self.decision(shell, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(rule, result['permissionDecisionReason'])

    def test_git_count_pipeline_requires_a_complete_literal_pipeline(self):
        command = r'''echo "$(git ls-tree -r --name-only abc123 -- src/api/ | grep -c '\.toml$')"'''
        other_shapes = (
            command.replace(' | ', ' >| '),
            command.replace(' | ', ' || '),
            command.replace('abc123', '$TREE'),
            command.replace('git ls-tree -r --name-only abc123 -- src/api/', 'printf api'),
            command.replace("')", "' example.txt)"),
            command.replace('$(', r'\$('),
            'echo $(' + command,
            command.removesuffix('"'),
        )
        for caller in ('', 'ship:driver'):
            self.assertEqual(self.decision(command, caller), {})
            for shell in other_shapes:
                with self.subTest(caller=caller, shell=shell):
                    result = self.decision(shell, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(' Rule: git config from the command line.', result['permissionDecisionReason'])

    def test_graphql_read_route_refuses_other_documents_and_options(self):
        documents = ('mutation{createIssue{ id }}', 'subscription{events{id}}',
                     'fragment F on User {login}', 'query{viewer{login}} query{viewer{id}}',
                     '{viewer{login}} # comment\nmutation{createIssue{id}}',
                     '{viewer{login}', 'Query{viewer{login}}', '', '{}', '{viewer(login:`x`)}',
                     '{viewer(value:1e)}', '{viewer(value:"bad\\z")}', '{viewer([)]}',
                     r'{a(s: """x\""")}', '{a(s: """")}', 'query R($a:Int {viewer{login}}')
        commands = ["gh api graphql -f query='" + document + "'" for document in documents]
        read = "gh api graphql -f query='{viewer{login}}'"
        commands.extend(read + option for option in (
            ' -f extra=x', ' -F extra=x', ' -X POST', ' --method POST', ' -H Accept:x', ' --input /tmp/x/body.json',
            ' --hostname github.com', ' --paginate', ' --slurp', ' --cache 1h', ' -p x', ' --'))
        commands.extend((read.replace('api graphql', 'api /graphql'),
                         read.replace('api graphql', "api 'graphql'"),
                         "gh api graphql -fquery='{viewer{login}}'",
                         "gh api graphql --raw-field=query='{viewer{login}}'",
                         read + ' && gh api repos/o/r/issues/7/comments -f body=x'))
        for command in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    self.assertEqual(self.decision(command, caller).get('permissionDecision'), 'deny')

    def test_data_arguments_allow_literal_runner_words_and_apostrophes(self):
        commands = (
            '''printf '%s\\n' "$(date -u +%FT%TZ) the lane's gh read waits" >> /tmp/x/notes.md''',
            '''R=/tmp/x/notes.md; printf '%s\\n' "$(date -u +%FT%TZ) the lane's gh read waits" >> "$R"''',
            "printf '%s\\n' 'the bash check before gh pr view' >> /tmp/x/notes.md",
            "printf '%s\\t%s\\n' run 'relay via sh then gh' >> /tmp/x/notes.md",
            "echo 'watch the gh queue'", 'ps -eo pid,ppid,args | grep -w gh | grep -v bash',
        )
        for command in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    self.assertEqual(self.decision(command, caller), {})

    def test_data_arguments_preserve_execution_and_syntax_refusals(self):
        write = 'gh api repos/o/r/issues/7/comments -f body=x'
        commands = (
            "printf '%s\\n' '" + write + "' | bash",
            "printf '%s\\n' '" + write + "' | at now",
            "printf '%s\\n' \"$(" + write + ')\"',
            "printf -v result '%s' 'bash before gh'",
            "grep --filter x bash gh /tmp/x/notes.md > /tmp/x/result",
            "env printf '%s' 'bash before gh'",
            "printf '%s' \"the lane's " + write + '\"',
            'printf "%s" "unterminated gh',
            'printf "%s" "`gh pr view 7`"',
            "printf '%s' 'bash before gh' | sh",
            '''printf '%s\\n' 'bash -c "gh pr close 7"' | at now''',
            '''printf '%s\\n' "$(sh -c 'gh pr view 7')"''',
            '''echo "$(bash -c "gh $(echo a)pi repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123")"''',
            '''printf '%s\\n' "$(sh -c 'g''h pr view 7')"''',
            '''printf '%s\\n' x > "$(sh -c 'gh pr view 7')"''',
            '''printf $f 'bash -c "gh pr view 7"' ''',
            'ps -eo pid,args | grep -w gh | grep -v bash *',
            '''echo(){ sh -c "$1"; }; echo 'gh pr close 7' ''',
            '''X=1; printf '%s\\n' 'bash -c "gh pr view 7"' | sh''',
            "PATH=/tmp/x; printf '%s\\n' 'the bash check before gh'",
        )
        for command in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    self.assertEqual(self.decision(command, caller).get('permissionDecision'), 'deny')

    def test_hidden_redirect_with_immediate_backtick_stays_refused(self):
        command = "gh '>`' api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123"
        self.assertEqual(self.decision(command, '').get('permissionDecision'), 'deny')

    def test_hidden_redirect_with_backtick_target_stays_refused(self):
        command = "gh '>x`y' api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123"
        self.assertEqual(self.decision(command, '').get('permissionDecision'), 'deny')

    def test_git_shell_aliases_stay_refused(self):
        commands = (
            "git -c alias.x='!gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123' x",
            'git -c "alias.x=!gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123" x',
            "git -calias.x='!gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123' x",
            'git --config-env=alias.x=V x',
            'git --config-env alias.x=V x',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command, '').get('permissionDecision'), 'deny')

    def test_git_config_key_assignment_stays_refused(self):
        self.assertEqual(self.decision('GIT_CONFIG_KEY_0=alias.x git log -1', '').get('permissionDecision'), 'deny')
        self.assertEqual(self.decision('GIT_CONFIG_KEY_1=include.path git log -1', '').get('permissionDecision'), 'deny')

    def test_git_config_value_assignment_stays_refused(self):
        self.assertEqual(self.decision("GIT_CONFIG_VALUE_0='!echo hi' git log -1", '').get('permissionDecision'), 'deny')

    def test_git_config_parameters_stay_refused(self):
        self.assertEqual(self.decision("GIT_CONFIG_PARAMETERS='alias.x=!echo hi' git log -1", '').get('permissionDecision'), 'deny')

    def test_quoted_shell_alias_word_stays_refused(self):
        command = "printf '%s' 'alias.x=!gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123'"
        self.assertIsNotNone(ultraship.review_thread_denial(command))
        self.assertEqual(self.decision(command, '').get('permissionDecision'), 'deny')

    def test_git_config_count_stays_refused(self):
        command = "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0='!gh api repos/o/r/pulls/7/comments -f body=x' git x"
        self.assertEqual(self.decision(command, '').get('permissionDecision'), 'deny')

    def test_config_assignment_after_separator_stays_refused(self):
        self.assertEqual(self.decision('true;GIT_CONFIG_KEY_0=alias.x git x', '').get('permissionDecision'), 'deny')

    def test_config_assignment_inside_group_stays_refused(self):
        self.assertEqual(self.decision('(GIT_CONFIG_GLOBAL=/tmp/x git status)', '').get('permissionDecision'), 'deny')

    def test_nonallowlisted_config_count_stays_refused(self):
        self.assertEqual(self.decision('GIT_CONFIG_COUNT=2 git status', '').get('permissionDecision'), 'deny')

    def test_global_config_path_stays_refused(self):
        self.assertEqual(self.decision('GIT_CONFIG_GLOBAL=/tmp/x git status', '').get('permissionDecision'), 'deny')

    def test_exported_config_key_stays_refused(self):
        self.assertEqual(self.decision('export GIT_CONFIG_KEY_0', '').get('permissionDecision'), 'deny')

    def test_declared_config_key_stays_refused(self):
        self.assertEqual(self.decision('declare -x GIT_CONFIG_KEY_0=alias.x', '').get('permissionDecision'), 'deny')

    def test_git_config_export_stays_refused(self):
        self.assertEqual(self.decision('export GIT_CONFIG_PARAMETERS', '').get('permissionDecision'), 'deny')

    def test_special_shell_quote_stays_refused(self):
        command = r"$'\x67h' api repos/o/r/pulls/7/comments -f body=x"
        self.assertEqual(self.decision(command, '').get('permissionDecision'), 'deny')

    def test_existing_literal_config_forms_stay_admitted(self):
        for command in ('git -c alias.lg=log lg',
                        'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=cat git log -1',
                        '/usr/bin/bash -c \'W=/w/wt; git -c core.fsmonitor=false -C "$W" rev-parse HEAD; git -C $W status --short\''):
            with self.subTest(command=command):
                self.assertEqual(self.decision(command, ''), {})

    def test_git_directory_option_stays_admitted(self):
        self.assertEqual(self.decision('git -C /tmp/x status', ''), {})

    def test_git_literal_pager_stays_admitted(self):
        self.assertEqual(self.decision('git -c core.pager=cat log -1', ''), {})

    def test_git_pager_config_env_stays_refused(self):
        for caller in ('', 'ship:driver'):
            with self.subTest(caller=caller):
                result = self.decision('git --config-env=core.pager=PAGER log -1', caller)
                self.assertEqual(result.get('permissionDecision'), 'deny')
                self.assertIn('git config from the command line', result['permissionDecisionReason'])

    def test_writer_admits_literal_commit_abbreviation_override(self):
        command = ('git -C /abs/lane -c core.abbrev=40 commit --only '
                   '-m "fix(mcp): pull editable skill versions" -- src/example.py')
        self.assertEqual(self.decision(command, 'ship:writer--sol'), {})
        commands = (
            ('git -C /abs/lane config --local core.abbrev 40', 'git stored config write rule'),
            ('git -C /abs/lane -c core.abbrev=40 status', 'git config value rule'),
            (command.replace('core.abbrev=40', 'core.editor=cat'), 'git config value rule'),
            (command.replace('core.abbrev=40', 'core.abbrev=12'), 'git config value rule'),
            (command + ' && git push origin HEAD', 'git remote writer rule (push)'),
        )
        for command, rule in commands:
            with self.subTest(command=command):
                result = self.decision(command, 'ship:writer--sol')
                self.assertEqual(result.get('permissionDecision'), 'deny')
                self.assertIn(rule, result['permissionDecisionReason'])

    def test_driver_count_and_shell_options_stay_admitted(self):
        for command in ("grep -c 'FAIL backend' f.log", "jq -c '.[]' f.json", "timeout 60 bash -c 'echo hi'"):
            with self.subTest(command=command):
                self.assertEqual(self.decision(command, ''), {})

    def assert_round_one_refused(self, command):
        self.assertEqual(self.decision(command, '').get('permissionDecision'), 'deny', command)

    def test_round_one_slice_heredoc_continuation(self):
        self.assert_round_one_refused("cat <<EOF\nE\\\nOF\ngh api -X DELETE repos/o/r/pulls/comments/123\nEOF")

    def test_round_one_slice_xargs_find(self):
        self.assert_round_one_refused("printf '%s\\n' '-maxdepth 0 -exec gh api -X DELETE repos/o/r/pulls/comments/123 ;' | xargs find")

    def test_round_one_slice_editor(self):
        self.assert_round_one_refused("GIT_EDITOR='gh api -X DELETE repos/o/r/pulls/comments/123 #' git config --local --edit")

    def test_round_one_c_stdbuf(self):
        self.assert_round_one_refused("echo 'gh api -X DELETE repos/o/r/pulls/comments/123' | stdbuf -oL bash")

    def test_round_one_c_noglob(self):
        self.assert_round_one_refused("echo 'gh api -X DELETE repos/o/r/pulls/comments/123' | noglob bash")

    def test_round_one_c_nocorrect(self):
        self.assert_round_one_refused("echo 'gh api -X DELETE repos/o/r/pulls/comments/123' | nocorrect bash")

    def test_round_one_c_dash(self):
        self.assert_round_one_refused("echo 'gh api -X DELETE repos/o/r/pulls/comments/123' | - bash")

    def test_round_one_c_flock(self):
        self.assert_round_one_refused("echo 'gh api -X DELETE repos/o/r/pulls/comments/123' | flock /tmp/x bash")

    def test_round_one_c_assignment(self):
        self.assert_round_one_refused("echo 'gh api -X DELETE repos/o/r/pulls/comments/123' | X+=1 bash")

    def test_round_one_c_env_assignment(self):
        self.assert_round_one_refused("echo 'gh api -X DELETE repos/o/r/pulls/comments/123' | env X+=1 bash")

    def test_round_one_c_xargs_xargs(self):
        self.assert_round_one_refused("echo gh api -X DELETE repos/o/r/pulls/comments/123 | xargs xargs")

    def test_round_one_c_xargs_stdbuf(self):
        self.assert_round_one_refused("echo gh api -X DELETE repos/o/r/pulls/comments/123 | xargs stdbuf -oL")

    def test_round_one_deep_parameter_single_quote(self):
        self.assert_round_one_refused("echo ${x:-'}'};gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123;echo '\\'")

    def test_round_one_deep_parameter_double_quote(self):
        self.assert_round_one_refused("echo \"${x:-\"}\"}\";gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123;echo '\"\\'")

    def test_round_one_deep_heredoc_continuation(self):
        self.assert_round_one_refused("cat <<EOF\nEO\\\nF\ngh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123\nEOF")

    def test_round_one_deep_quoted_heredoc_group(self):
        self.assert_round_one_refused("cat <<'EOF'; (true\nEOF\n)\ngh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123\nEOF")

    def test_round_one_deep_delimiter_continuation(self):
        self.assert_round_one_refused("cat <<E\\\nOF\n$(gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123)\nEOF")

    def test_round_one_deep_stdbuf_xargs(self):
        self.assert_round_one_refused("echo -f body=x -F in_reply_to=123 | stdbuf -oL xargs gh api repos/o/r/pulls/7/comments")

    def test_round_one_deep_assignment_xargs(self):
        self.assert_round_one_refused("echo -f body=x -F in_reply_to=123 | A+=1 xargs gh api repos/o/r/pulls/7/comments")

    def test_round_one_deep_stdbuf_shell(self):
        self.assert_round_one_refused("echo 'gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123' | stdbuf -oL sh")

    def test_round_one_deep_python_pipe(self):
        self.assert_round_one_refused("echo 'import os; os.system(\"gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123\")' | python3")

    def test_round_one_deep_perl_xargs(self):
        self.assert_round_one_refused("printf '%s' 'system \"gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123\"' | xargs -0 perl -e")

    def test_round_one_deep_saved_shell(self):
        self.assert_round_one_refused("echo 'gh api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123' > /tmp/x.sh; bash /tmp/x.sh")

    def test_round_one_deep_zsh_redirect(self):
        self.assert_round_one_refused("gh >! api repos/o/r/pulls/7/comments -f body=x -F in_reply_to=123")

    def test_round_one_b_heredoc_group(self):
        self.assert_round_one_refused("cat <<EOF; (true\nEOF\n)\ngh api repos/o/r/issues/1/comments -f body=x\nEOF")

    def test_round_one_b_delimiter_continuation(self):
        self.assert_round_one_refused("cat <<EO\\\nF\n$(gh api repos/o/r/issues/1/comments -f body=x)\nEOF")

    def test_round_one_b_heredoc_carriage_return(self):
        self.assert_round_one_refused("cat <<EOF\r\nEOF\r\ngh api repos/o/r/issues/1/comments -f body=x\nEOF")

    def test_round_one_b_comment_carriage_return(self):
        self.assert_round_one_refused("true\r#;gh api repos/o/r/issues/1/comments -f body=x")

    def test_round_one_b_perl_heredoc(self):
        self.assert_round_one_refused("perl <<'EOF'\n`gh api repos/o/r/issues/1/comments -f body=x`\nEOF")

    def test_round_one_b_python_fstring(self):
        self.assert_round_one_refused("python3 - <<'EOF'\nimport os; os.system(f\"gh api repos/o/r/issues/1/comments -f body=x\")\nEOF")

    def test_round_one_b_saved_group(self):
        self.assert_round_one_refused("cat > x.sh <<'EOF'\ngh api repos/o/r/issues/1/comments -f body=x\nEOF\n(bash x.sh)")

    def test_round_one_b_saved_backticks(self):
        self.assert_round_one_refused("cat > x.sh <<EOF\n\\`gh api repos/o/r/issues/1/comments -f body=x\\`\nEOF\nbash x.sh")

    def test_base_pr_ready_decision(self):
        self.assertIsNone(ultraship.review_thread_denial('gh pr ready https://github.com/o/r/pull/7'))

    def test_pr_body_file_edit_keeps_role_limits(self):
        for path in ('.scratch/pr-body.md', "'.scratch/resolveReviewThread.md'", '.scratch/comments/123/replies.md'):
            command = 'gh pr edit 7 --body-file ' + path
            for caller in ('', 'ship:driver'):
                with self.subTest(path=path, caller=caller):
                    self.assertEqual(self.decision(command, caller), {})
            result = self.decision(command, 'ship:writer--sol')
            self.assertEqual(result.get('permissionDecision'), 'deny')
            self.assertIn('Writers never push', result['permissionDecisionReason'])

    def test_top_level_pr_comment_with_literal_body_file_keeps_role_limits(self):
        command = 'gh pr comment 7 --body-file .scratch/reconciliation.md'
        for caller in ('', 'ship:driver'):
            with self.subTest(caller=caller):
                self.assertEqual(self.decision(command, caller), {})
        result = self.decision(command, 'ship:writer--sol')
        self.assertEqual(result.get('permissionDecision'), 'deny')
        self.assertIn('Writers never push', result['permissionDecisionReason'])

    def test_pr_body_file_edit_keeps_compound_thread_writes_refused(self):
        edit = 'gh pr edit 7 --body-file .scratch/resolveReviewThread.md'
        commands = (
            (edit + " && gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:\"PRRT_x\"}){thread{id}}}'",
             'raw review-thread mutation'),
            (edit + '; gh api repos/o/r/pulls/7/comments -f body=done -F in_reply_to=123',
             'REST review-comment write or opaque endpoint'),
        )
        for command, rule in commands:
            for caller in ('', 'ship:driver'):
                with self.subTest(command=command, caller=caller):
                    result = self.decision(command, caller)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn(' Rule: ' + rule + '.', result['permissionDecisionReason'])

    def test_pr_create_admits_quoted_heredoc_text_in_title(self):
        command = "gh pr create --title 'docs: describe <<BODY' --body-file body.md"
        for caller in ('', 'ship:driver'):
            with self.subTest(caller=caller):
                self.assertEqual(self.decision(command, caller), {})

    def test_guard_exception_denies_every_caller(self):
        with patch.object(ultraship, 'review_thread_denial', create=True, side_effect=ValueError('bad parse')):
            for agent_type in ('', 'ship:driver', 'ship:writer--sol'):
                with self.subTest(agent_type=agent_type):
                    result = self.decision('echo hello', agent_type)
                    self.assertEqual(result.get('permissionDecision'), 'deny')
                    self.assertIn('review-thread guard exception: ValueError', result['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
