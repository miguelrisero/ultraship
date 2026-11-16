#!/usr/bin/env python3
"""Take thread IDs only from threads.sh output for the same PR; never build or guess one."""
import json
from pathlib import Path
import re
import subprocess
import sys

LOOKUP = 'query($id:ID!){node(id:$id){__typename ... on PullRequestReviewThread{pullRequest{number repository{nameWithOwner}}}}}'
REPLY = 'mutation($id:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$body}){comment{url}}}'
RESOLVE = 'mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}'


def graphql(query, thread, body=None):
    arguments = ['gh', 'api', '--hostname', 'github.com', 'graphql', '-f', 'query=' + query, '-f', 'id=' + thread]
    if body is not None:
        arguments += ['-f', 'body=' + body]
    result = subprocess.run(arguments, text=True, capture_output=True)
    if result.returncode:
        raise ValueError('GitHub request failed')
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or 'errors' in response:
        raise ValueError('GitHub response has errors')
    return response['data']


def main(arguments):
    try:
        if not arguments or arguments[0] not in ('reply', 'resolve'):
            raise ValueError('usage: thread_reply.py reply <PR URL> <thread ID> <body file> | resolve <PR URL> <thread ID>')
        action = arguments[0]
        if len(arguments) != (4 if action == 'reply' else 3):
            raise ValueError('wrong number of arguments')
        pr, thread = arguments[1:3]
        match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)', pr)
        if not match:
            raise ValueError('invalid PR URL')
        if not re.fullmatch(r'PRRT_[A-Za-z0-9_-]+', thread):
            raise ValueError('invalid thread ID')
        body = Path(arguments[3]).read_text(encoding='utf-8') if action == 'reply' else None
        if body is not None and not body.strip():
            raise ValueError('empty reply body')
        repository = match[1] + '/' + match[2]
        number = int(match[3])
        node = graphql(LOOKUP, thread)['node']
        if node['__typename'] != 'PullRequestReviewThread':
            raise ValueError('node is not a review thread')
        pull = node['pullRequest']
        if (pull['repository']['nameWithOwner'].casefold() != repository.casefold()
                or type(pull['number']) is not int or pull['number'] != number):
            raise ValueError('thread belongs to another repository or PR')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print('refused: ' + str(error), file=sys.stderr)
        return 2
    try:
        response = graphql(REPLY if action == 'reply' else RESOLVE, thread, body)
        if action == 'reply':
            url = response['addPullRequestReviewThreadReply']['comment']['url']
            if not isinstance(url, str) or not re.match(
                    r'https://github\.com/' + re.escape(repository) + r'/pull/' + str(number) + r'(?=$|[#/?])',
                    url, re.IGNORECASE):
                raise ValueError('reply URL does not belong to this PR')
            print(url)
        else:
            if response['resolveReviewThread']['thread']['isResolved'] is not True:
                raise ValueError('thread remains unresolved')
            print('resolved ' + thread)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print('failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
