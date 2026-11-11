#!/usr/bin/env python3
"""Check outgoing prose without changing payloads, permissions, or owner events."""
from html.parser import HTMLParser
import json
import re
import sys

# Short word-number fusions such as `deadline2026` or `by8November00`; hex digests and `b1a2c3d4e` task IDs pass.
GLUED = re.compile(r'[a-z]{3}[0-9]|[0-9][a-z]{3}')  # Uppercase IDs such as `HTTP429` and Slack channel IDs pass.
# Product and hardware names with a version number are words, not fusions.
GLUE_EXEMPT = re.compile(r'[0-9a-f]+|b[a-z0-9]{8}|(sha|md)[0-9]*sum|python[0-9.]*|(u?int|float|rtx|gtx|postgres|aarch|x86|utf|base)[0-9]+\w*', re.I)
HOLD_WORDS = re.compile(r'\b(preserv\w*|holds?|custody|custodian|admission|admits?|admitted|provenance|refusals?)\b', re.I)
# The harness addresses an in-session subagent by its agent ID and a background subagent's parent as `main`.
SUBAGENT = re.compile(r'main|a[0-9a-f]{16}')


class VisibleText(HTMLParser):
    BLOCKS = {'address', 'article', 'aside', 'blockquote', 'br', 'div', 'dl', 'dt', 'dd',
              'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
              'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre',
              'section', 'table', 'tr', 'ul'}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden, self.kinds = [], [], []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script', 'code', 'pre'):
            if not self.hidden and tag in ('code', 'pre'):
                self.parts.append(' ')
            self.hidden.append(tag)
        if self.hidden:
            return
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name') == 'output-kind':
            self.kinds.append(attrs.get('content'))
        if tag in self.BLOCKS:
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in self.BLOCKS:
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def glued(tokens):
    words = {re.sub(r"'s$", '', t.strip('.,;:()[]!?"\'*')) for t in tokens if not re.search(r'[_-]', t)}
    return {w for w in words if len(w) >= 7 and w.isalnum() and GLUED.search(w) and not GLUE_EXEMPT.fullmatch(w)}


def hold_wall(text):
    """Six or more hold words in a status message restate standing holds; a brief carries its restrictions."""
    if 'Owner helper request:' in text:
        return
    prose = re.sub(r'`[^`]*`', '', ''.join(VisibleText(text).parts))
    words = ' '.join(t for t in prose.split() if not re.search(r'https?://|/', t))
    if len(HOLD_WORDS.findall(words)) >= 6:
        raise ValueError('Keep any new hold in one line, drop restated standing holds, and send what changed and the next action.')


def check(text, kind='result'):
    plain = ''.join(VisibleText(text).parts)
    prose = re.sub(r'`[^`]*`', '', plain)
    tokens = [t for t in prose.split() if not re.search(r'https?://|/|`|^[0-9a-f]{12,}$', t)]
    long = [t for t in tokens if len(t) >= 22]
    errors = []
    if len(long) >= 3 or (tokens and len(long) / len(tokens) >= 0.08) or len(glued(tokens)) >= 2:
        errors.append('Separate glued words with spaces; remove compressed shorthand.')
    sentences = re.split(r'(?<=[.!?])\s+|\n+', prose)
    if any(len(s.split()) > 25 for s in sentences):
        errors.append('Write at most 25 words per sentence.')
    sections = ('Facts', 'Decision', 'Next') if kind == 'peer' else (
        ('What is wrong', 'Why now', 'Options', 'Recommendation', 'If no answer') if kind == 'decision' else ())
    for section in sections:
        if not re.search(r'^\s*(?:#{1,6}\s*)?' + re.escape(section) + r'\b', plain, re.M | re.I):
            errors.append('Missing section: ' + section)
    if errors:
        raise ValueError(' '.join(errors))


def outgoing(event):
    tool, args = event.get('tool_name', ''), event.get('tool_input') or {}
    if tool == 'SendMessage':
        text = args.get('message') or args.get('content') or ''
        if text:  # Native subscriptions and lifecycle controls can have no prose body.
            check(text, 'peer')
            if not SUBAGENT.fullmatch(str(args.get('to', '')).strip()):  # A brief to a child carries its restrictions.
                hold_wall(text)
    elif tool.endswith(('create_input', 'update_input')):
        content = args.get('content')
        if content is None:  # Metadata-only writes carry no new owner text.
            return
        if isinstance(content, str):
            content = json.loads(content)
        body = content.get('html', '')
        kinds = VisibleText(body).kinds
        if len(kinds) != 1 or kinds[0] not in ('decision', 'result'):
            raise ValueError('Input HTML requires one explicit output-kind classification: decision or result.')
        check(content.get('title', ''))
        check(body, kinds[0])


def self_test():
    peer = 'The review passes. The driver can continue.\nFacts: The checks pass.\nDecision: Continue.\nNext: The driver resumes at 2026-10-31T12:00:00Z.'
    decision = '<meta name="output-kind" content="decision"><h2>What is wrong</h2><p>The release waits.</p><h2>Why now</h2><p>The deadline approaches.</p><h2>Options A to C</h2><p>A: Hold. B: Release. C: Defer.</p><h2>Recommendation</h2><p>Choose A.</p><h2>If no answer</h2><p>Keep the hold.</p>'
    check(peer, 'peer')
    for tool in ('mcp__bettercoding__create_input', 'mcp__bettercoding__update_input'):
        outgoing({'tool_name': tool, 'tool_input': {'content': {'html': decision, 'contract': {'choices': [], 'allow_text': True}}}})
        outgoing({'tool_name': tool, 'tool_input': {'request_answer': True, 'content': {'html': '<meta name="output-kind" content="result"><p>The release completes.</p>', 'contract': {'choices': [{'id': 'ok', 'label': 'Useful'}], 'allow_text': True}}}})
    outgoing({'tool_name': 'SendMessage', 'tool_input': {'to': 'peer'}})
    check('https://example.test/averylongsourceidentifier /absolute/long-source-path `averylongloadbearingidentifier` ' + 'a' * 40)
    check(' '.join(['z' * 22] + ['word'] * 12))  # One long token in 13 stays below 8%.
    check('Run python3 on template0 at 18:00 UTC; task b7re019f0 uses sha256sum on rtx4090 and float32 hosts.')
    hold_wall('Tests pass with zero failures and zero skips. The receipt is in the board. Authority is unchanged.')
    hold_wall('The owner put a hold on PR 7190. The hold covers the deploy. The refusal stands. Keep the hold.')
    hold_wall('Owner helper request: retained. Preserve holds, custody, admission, provenance and every refusal.')
    check('Route C08JQ4K3XLM and C07RTZ2PWNB after HTTP429 and RFC3339 checks.')
    hold_wall('Preserve every hold at `https://x.test/hold/custody/admission/provenance/refusal`.')
    wall = peer.replace('The checks pass.', 'Preserve every hold. Custody stays. Admission waits. Preserve the refusal.')
    outgoing({'tool_name': 'SendMessage', 'tool_input': {'to': 'a' + '0' * 16, 'message': wall}})
    try:
        outgoing({'tool_name': 'SendMessage', 'tool_input': {'to': 'peer', 'message': wall}})
    except ValueError:
        pass
    else:
        raise AssertionError('lint accepted a restated-hold wall')
    for text, kind in [('Newglobaldiskpolicyacceptedtoday', 'result'),
                       ('Send the deadline2026 note by8November00 today.', 'result'),
                       ("Send the deadline2026 note by the by8November00's end.", 'result'),
                       (' '.join(['z' * 22] + ['word'] * 11), 'result'),
                       (' '.join(['word'] * 26) + '.', 'result'),
                       (peer.replace('Facts:', 'Evidence:'), 'peer'),
                       (decision.replace('Recommendation', 'Advice'), 'decision')]:
        try:
            check(text, kind)
        except ValueError:
            continue
        raise AssertionError('lint accepted invalid ' + kind)


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
    elif sys.argv[1:] == ['hook']:
        try:
            outgoing(json.load(sys.stdin))
        except (ValueError, TypeError, AttributeError) as exc:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny', 'permissionDecisionReason': 'Output contract: ' + str(exc)}}))
    else:
        check(sys.stdin.read(), sys.argv[1] if len(sys.argv) > 1 else 'result')
