#!/usr/bin/env python3
"""Read Prelint decisions and check the evidence for a top-level disposition."""
import hashlib
import json
import re
import subprocess
import sys

PR_URL = re.compile(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)')
BADGE_ROOT = 'https://app.prelint.com/review-badges/'
DECISION_HEADING = f'## <img align="right" src="{BADGE_ROOT}ship-with-changes.svg" alt="Ship with changes"> '
DISPOSITIONS = {'real', 'false-positive', 'duplicate', 'already-fixed', 'pending'}


def github(endpoint, *options):
    result = subprocess.run(['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                             endpoint, *options], check=True, capture_output=True,
                            stdin=subprocess.DEVNULL, encoding='utf-8', timeout=30)
    return json.loads(result.stdout)


def same_url(value, expected):
    return isinstance(value, str) and value.isascii() and value.lower() == expected.lower()


def positive_id(value):
    return type(value) is int and value > 0


def is_prelint(comment):
    user = comment.get('user')
    app = comment.get('performed_via_github_app')
    return (isinstance(user, dict) and user.get('login') == 'prelint[bot]' and user.get('type') == 'Bot'
            and type(user.get('id')) is int and user['id'] == 260255511
            and isinstance(app, dict) and type(app.get('id')) is int and app['id'] == 2822344)


def inspect(pr_url, preflight):
    match = PR_URL.fullmatch(pr_url)
    if not match or match[1].split('/')[1] in ('.', '..'):
        raise ValueError('invalid PR URL')
    repo, number = match.groups()
    issue = f'repos/{repo}/issues/{number}'
    if preflight:
        source_id, body_sha256, expected_head, disposition = preflight
        if (not re.fullmatch(r'[1-9][0-9]*', source_id) or not re.fullmatch(r'[0-9a-f]{64}', body_sha256)
                or not re.fullmatch(r'[0-9a-f]{40}', expected_head) or disposition not in DISPOSITIONS):
            raise ValueError('invalid disposition evidence')
        actor = github('user')['id']
        if not positive_id(actor):
            raise ValueError('invalid account identity')
    pages = github(issue + '/comments?per_page=100', '--paginate', '--slurp')
    if not isinstance(pages, list) or not pages or any(not isinstance(page, list) for page in pages):
        raise ValueError('invalid conversation pages')

    decisions, comments, unfamiliar = {}, {}, []
    for page in pages:
        for comment in page:
            cid, url, body = comment['id'], comment['html_url'], comment['body']
            if (not positive_id(cid) or cid in comments or not isinstance(body, str)
                    or not same_url(comment['issue_url'], 'https://api.github.com/' + issue)
                    or not same_url(url, f'{pr_url}#issuecomment-{cid}')):
                raise ValueError('invalid conversation comment')
            comments[cid] = comment
            if not is_prelint(comment):
                continue
            heading = body.partition('\n')[0]
            if heading.startswith(DECISION_HEADING) and heading[len(DECISION_HEADING):].strip():
                decisions[cid] = {'id': cid, 'url': url, 'body': body,
                                  'body_sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
                                  'reviewed_head': None}
            elif heading.startswith('## ') and BADGE_ROOT in heading:
                unfamiliar.append(url)

    pull = github(f'repos/{repo}/pulls/{number}')
    head = pull['head']['sha']
    if (type(pull['number']) is not int or str(pull['number']) != number
            or not same_url(pull['html_url'], pr_url) or pull['state'] != 'open'
            or not re.fullmatch(r'[0-9a-f]{40}', head)):
        raise ValueError('open PR identity and head required')
    if not preflight:
        return {'pr_url': pr_url, 'observed_pr_head': head, 'decisions': list(decisions.values()),
                'unfamiliar_badges': unfamiliar}

    source = decisions.get(int(source_id))
    if head != expected_head or source is None or source['body_sha256'] != body_sha256:
        raise ValueError('disposition evidence has changed')
    reference_line = (f'Prelint disposition for {source["url"]} | body SHA-256 {body_sha256}'
                      f' | evidence head {expected_head} | {disposition}')
    posted = [c['html_url'] for c in comments.values()
              if isinstance(c.get('user'), dict) and type(c['user'].get('id')) is int
              and c['user']['id'] == actor and c['body'].partition('\n')[0].removesuffix('\r') == reference_line]
    return {'pr_url': pr_url, 'observed_pr_head': head, 'source_url': source['url'],
            'reference_line': reference_line, 'existing_dispositions': posted}


def main(args):
    if not ((len(args) == 2 and args[0] == 'collect') or (len(args) == 6 and args[0] == 'preflight')):
        print('usage: prelint_decisions.py collect <PR URL> | '
              'preflight <PR URL> <comment ID> <body SHA256> <expected PR head> <disposition>', file=sys.stderr)
        return 2
    try:
        output = inspect(args[1], args[2:])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
        print('Prelint evidence unavailable or changed. Leave the advisory disposition pending.', file=sys.stderr)
        return 1
    print(json.dumps(output))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
