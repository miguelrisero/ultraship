#!/usr/bin/env python3
"""Take thread IDs only from threads.sh output for the same PR; never build or guess one."""
import json
import os
from pathlib import Path
import re
from subprocess import Popen
import subprocess
import sys
from time import monotonic

LOOKUP = 'query($id:ID!){node(id:$id){__typename ... on PullRequestReviewThread{pullRequest{number repository{nameWithOwner}}}}}'
REPLY = 'mutation($id:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$body}){comment{url}}}'
RESOLVE = 'mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}'
COMMENTS = 'query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread{comments(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{author{login}url body}}}}}'


THREAD_PAGE = 'query($owner:String!,$name:String!,$pr:Int!,$after:String){repository(owner:$owner,name:$name){nameWithOwner pullRequest(number:$pr){number reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{id isResolved isOutdated path line comments(first:1){nodes{author{login}url body}}}}}}}'


class CleanupUnsettled(ValueError):
    def __init__(self, detail):
        super().__init__('cleanup unsettled: ' + detail)


class PageProcess:
    def __init__(self):
        started = monotonic()
        self.work_deadline = started + 30
        self.deadline = started + 40
        self.child, self.pid, self.reaped = None, None, False
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.startswith('GIT_') and key not in ('GH_REPO', 'GH_HOST')}

    def reap(self, child, deadline):
        remaining = min(deadline, self.deadline) - monotonic()
        if remaining <= 0:
            raise CleanupUnsettled('reaping budget exhausted')
        result = child.wait(timeout=remaining)
        if type(result) is not int or child.returncode != result:
            raise CleanupUnsettled('child reaping is uncertain')
        self.reaped = True

    def live(self, child, pid):
        # An unreaped direct child retains its PID; WNOWAIT preserves that ownership until signaling.
        if (self.child is not child or self.pid != pid or child.pid != pid
                or type(pid) is not int or pid <= 0 or pid == os.getpid()):
            raise CleanupUnsettled('child identity is uncertain')
        if self.reaped:
            return False
        if child.returncode is not None:
            raise CleanupUnsettled('child reaping is unverified')
        state = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if state is not None:
            if state.si_pid != pid:
                raise CleanupUnsettled('child identity is uncertain')
            self.reap(child, min(monotonic() + 5, self.deadline))
            return False
        return True

    def cleanup(self, child, pid):
        try:
            if not self.live(child, pid):
                return
            if monotonic() >= self.deadline:
                raise CleanupUnsettled('cleanup reserve exhausted')
            child.terminate()
            grace = monotonic() + 5
            if grace + 5 > self.deadline:
                raise CleanupUnsettled('cleanup reserve exhausted after TERM')
            try:
                self.reap(child, grace)
                return
            except subprocess.TimeoutExpired:
                pass
            if monotonic() < grace:
                raise CleanupUnsettled('TERM grace incomplete')
            if not self.live(child, pid):
                return
            remaining = min(5, self.deadline - monotonic())
            if remaining <= 0:
                raise CleanupUnsettled('reaping budget exhausted')
            reap_deadline = min(monotonic() + remaining, self.deadline)
            child.kill()
            self.reap(child, reap_deadline)
        except CleanupUnsettled:
            raise
        except (OSError, subprocess.SubprocessError, ValueError):
            raise CleanupUnsettled('child cleanup failed') from None

    def run(self, arguments, cwd):
        if self.child is not None and not self.reaped:
            raise CleanupUnsettled('previous child remains owned')
        remaining = self.work_deadline - monotonic()
        if remaining <= 0 or self.deadline - monotonic() <= 10:
            raise ValueError('thread page work budget exhausted')
        child = Popen(arguments, cwd=cwd, env=self.environment, stdin=subprocess.DEVNULL,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
        self.child, self.pid, self.reaped = child, child.pid, False
        try:
            remaining = self.work_deadline - monotonic()
            if remaining <= 0:
                raise ValueError('thread page work budget exhausted')
            try:
                stdout, _ = child.communicate(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise ValueError('thread page work budget exhausted') from None
            if type(child.returncode) is not int:
                raise CleanupUnsettled('child reaping is unverified')
            self.reaped = True
            if child.returncode:
                raise ValueError('thread page command failed')
            if monotonic() >= self.work_deadline:
                raise ValueError('thread page work budget exhausted')
            return stdout
        finally:
            cleanup_error = None
            try:
                self.cleanup(child, self.pid)
            except CleanupUnsettled as error:
                cleanup_error = error
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        cleanup_error = cleanup_error or CleanupUnsettled('stream cleanup failed')
            if cleanup_error is not None:
                raise cleanup_error from None


def thread_page(arguments):
    if len(arguments) not in (1, 2) or not re.fullmatch(r'[1-9][0-9]{0,9}', arguments[0]):
        raise ValueError('usage: thread_reply.py page <PR number> [cursor]')
    number = int(arguments[0])
    if number > 2147483647:
        raise ValueError('invalid PR number')
    after = arguments[1] if len(arguments) == 2 else None
    if after is not None and (not after or '\x00' in after):
        raise ValueError('invalid page cursor')
    process = PageProcess()
    root_text = process.run(['git', 'rev-parse', '--show-toplevel'], Path.cwd().resolve())
    roots = root_text.splitlines()
    if len(roots) != 1 or not Path(roots[0]).is_absolute():
        raise ValueError('invalid local repository')
    root = Path(roots[0]).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('invalid local repository')
    origins = process.run(['git', 'config', '--local', '--get-all', 'remote.origin.url'], root).splitlines()
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+?)(?:\.git)?',
                         origins[0]) if len(origins) == 1 else None
    if not match or match[2] in ('.', '..'):
        raise ValueError('invalid local origin identity')
    repository = match[1] + '/' + match[2]
    vector = ['gh', 'api', '--hostname', 'github.com', 'graphql', '-f', 'query=' + THREAD_PAGE,
              '-f', 'owner=' + match[1], '-f', 'name=' + match[2], '-F', 'pr=' + str(number)]
    if after is not None:
        vector += ['-f', 'after=' + after]
    response = json.loads(process.run(vector, root))
    if not isinstance(response, dict) or 'errors' in response:
        raise ValueError('GitHub response has errors')
    repo = response['data']['repository']
    pull = repo['pullRequest']
    if (not isinstance(repo['nameWithOwner'], str) or repo['nameWithOwner'].casefold() != repository.casefold()
            or type(pull['number']) is not int or pull['number'] != number):
        raise ValueError('page belongs to another repository or PR')
    connection = pull['reviewThreads']
    page, nodes = connection['pageInfo'], connection['nodes']
    if type(page['hasNextPage']) is not bool or not isinstance(nodes, list):
        raise ValueError('invalid threads page')
    cursor = page['endCursor']
    if cursor is not None and (not isinstance(cursor, str) or not cursor or '\x00' in cursor):
        raise ValueError('invalid threads cursor')
    if page['hasNextPage'] and (cursor is None or cursor == after or not nodes):
        raise ValueError('thread page makes no progress')
    threads, ids = [], set()
    for node in nodes:
        thread = node['id']
        if not isinstance(thread, str) or not re.fullmatch(r'PRRT_[A-Za-z0-9_-]+', thread) or thread in ids:
            raise ValueError('invalid thread ID')
        ids.add(thread)
        if type(node['isResolved']) is not bool or type(node['isOutdated']) is not bool:
            raise ValueError('invalid thread status')
        if (not isinstance(node['path'], str) or not node['path'] or type(node['line']) not in (int, type(None))
                or node['line'] is not None and node['line'] <= 0):
            raise ValueError('invalid thread location')
        comments = node['comments']['nodes']
        if not isinstance(comments, list) or len(comments) != 1:
            raise ValueError('invalid thread preview')
        comment = comments[0]
        author = 'ghost' if comment['author'] is None else comment['author']['login']
        if (not isinstance(author, str) or not author or not isinstance(comment['body'], str)
                or not belongs_to_pr(comment['url'], repository, number)):
            raise ValueError('invalid thread preview')
        threads.append({'id': thread, 'isResolved': node['isResolved'], 'isOutdated': node['isOutdated'],
                        'path': node['path'], 'line': node['line'],
                        'comments': [{'author': author, 'url': comment['url'], 'body': comment['body']}]})
    result = json.dumps({'repository': repository, 'number': number,
                         'pageInfo': {'hasNextPage': page['hasNextPage'], 'endCursor': cursor},
                         'threads': threads}, ensure_ascii=False)
    if monotonic() >= process.deadline:
        raise ValueError('thread page total budget exhausted')
    return result


def graphql(query, thread, body=None, after=None):
    arguments = ['gh', 'api', '--hostname', 'github.com', 'graphql', '-f', 'query=' + query, '-f', 'id=' + thread]
    if body is not None:
        arguments += ['-f', 'body=' + body]
    if after is not None:
        arguments += ['-f', 'after=' + after]
    result = subprocess.run(arguments, text=True, capture_output=True)
    if result.returncode:
        raise ValueError('GitHub request failed')
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or 'errors' in response:
        raise ValueError('GitHub response has errors')
    return response['data']


def belongs_to_pr(url, repository, number):
    return isinstance(url, str) and re.match(
        r'https://github\.com/' + re.escape(repository) + r'/pull/' + str(number) + r'(?=$|[#/?])',
        url, re.IGNORECASE)


def read_comments(thread, repository, number):
    comments = []
    after = None
    cursors = set()
    while True:
        connection = graphql(COMMENTS, thread, after=after)['node']['comments']
        page = connection['pageInfo']
        nodes = connection['nodes']
        if type(page['hasNextPage']) is not bool or not isinstance(nodes, list):
            raise ValueError('invalid comments page')
        for comment in nodes:
            author = 'ghost' if comment['author'] is None else comment['author']['login']
            if not isinstance(author, str) or not author or not isinstance(comment['body'], str):
                raise ValueError('invalid comment')
            if not belongs_to_pr(comment['url'], repository, number):
                raise ValueError('comment URL does not belong to this PR')
            comments.append({'author': author, 'url': comment['url'], 'body': comment['body']})
        after = page['endCursor']
        if after is not None and (not isinstance(after, str) or not after):
            raise ValueError('invalid comments cursor')
        if not page['hasNextPage']:
            break
        if after is None or after in cursors:
            raise ValueError('invalid comments cursor')
        cursors.add(after)
    if not comments:
        raise ValueError('thread has no comments')
    return comments


def main(arguments):
    if arguments and arguments[0] == 'page':
        try:
            output = thread_page(arguments[1:])
        except CleanupUnsettled:
            print('failed: thread page unavailable. Cleanup unsettled.', file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            print('failed: thread page unavailable.', file=sys.stderr)
            return 1
        print(output)
        return 0
    try:
        if not arguments or arguments[0] not in ('reply', 'resolve', 'read'):
            raise ValueError('usage: thread_reply.py reply <PR URL> <thread ID> <body file> | resolve <PR URL> <thread ID> | read <PR URL> <thread ID>')
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
        if action == 'read':
            comments = read_comments(thread, repository, number)
            print(json.dumps({'thread': thread, 'comments': comments}, ensure_ascii=False))
            return 0
        response = graphql(REPLY if action == 'reply' else RESOLVE, thread, body)
        if action == 'reply':
            url = response['addPullRequestReviewThreadReply']['comment']['url']
            if not belongs_to_pr(url, repository, number):
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
