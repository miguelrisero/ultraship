#!/usr/bin/env python3
"""Check outgoing prose without changing payloads, permissions, or owner events."""
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import hmac
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

# Short word-number fusions such as `deadline2026` or `by8November00`; hex digests and `b1a2c3d4e` task IDs pass.
GLUED = re.compile(r'[a-z]{3}[0-9]|[0-9][a-z]{3}')  # Uppercase IDs such as `HTTP429` and Slack channel IDs pass.
# Product and hardware names with a version number are words, not fusions.
GLUE_EXEMPT = re.compile(r'[0-9a-f]+|b[a-z0-9]{8}|(sha|md)[0-9]*sum|python[0-9.]*|(u?int|float|rtx|gtx|postgres|aarch|x86|utf|base)[0-9]+\w*', re.I)
HOLD_WORDS = re.compile(r'\b(preserv\w*|holds?|custody|custodian|admission|admits?|admitted|provenance|refusals?)\b', re.I)
# The harness addresses an in-session subagent by its agent ID and a background subagent's parent as `main`.
SUBAGENT = re.compile(r'main|a[0-9a-f]{16}')
RECEIPT_MARKER = re.compile(r'<!-- ultraship-receipt:[0-9a-f]{32} -->')
PEER_TEMPLATE = """<Outcome in one sentence, and what it means for the recipient.>
Facts
- <Verified fact with its source: PR number, run ID or UTC time.>
Decision
- <The action you take or ask for, within existing authority.>
Next
- <Accountable owner> will <action> by <YYYY-MM-DDTHH:MMZ>.
<Every line: one point per sentence, at most 25 words each, with a space between words.>"""
INPUT_TEMPLATE = '''Use exactly one output-kind meta tag: decision or result.
Decision:
<meta name="output-kind" content="decision">
<h2>What is wrong</h2><p>...</p>
<h2>Why now</h2><p>...</p>
<h2>Options A to C with effects</h2><p>A: ... B: ... C: ...</p>
<h2>Recommendation</h2><p>...</p>
<h2>If no answer</h2><p>...</p>
Result alternative:
<meta name="output-kind" content="result"><p>...</p>
Write at most 25 words per sentence.'''


class FindingsError(ValueError):
    def __init__(self, findings, formatting_only=False):
        self.findings = findings
        self.formatting_only = formatting_only
        super().__init__(' '.join(findings))


class FormatError(FindingsError):
    def __init__(self, findings):
        super().__init__(findings, True)


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


def peer_text(text):
    # A peer reads SendMessage text as plain text; main's HTML parse decoded references once.
    return html.unescape(RECEIPT_MARKER.sub('', text))


def hold_wall(text):
    """Six or more hold words in a status message restate standing holds; a brief carries its restrictions."""
    if 'Owner helper request:' in text:
        return
    # Main's HTML view joins a word that a tag splits; the split view also reads text after a stray `<`.
    for view in (re.sub(r'[<>]', ' ', peer_text(text)), ''.join(VisibleText(text).parts)):
        prose = re.sub(r'`[^`]*`', '', view)
        words = ' '.join(t for t in prose.split() if not re.search(r'https?://|/', t))
        if len(HOLD_WORDS.findall(words)) >= 6:
            raise ValueError('Keep any new hold in one line, drop restated standing holds, and send what changed and the next action.')


def check(text, kind='result'):
    visible = ''.join(VisibleText(text).parts)
    plain = peer_text(text) if kind == 'peer' else visible
    # A peer reads plain text; main's HTML view of the raw text keeps every word and sentence refusal main made.
    views = (plain, visible) if kind == 'peer' else (plain,)
    shorthand = long_sentence = False
    for index, view in enumerate(views):
        prose = re.sub(r'`[^`]*`', '', view)
        token_prose = re.sub(r'[<>]', ' ', prose) if kind == 'peer' and index == 0 else prose
        tokens = [t for t in token_prose.split() if not re.search(r'https?://|/|`|^[0-9a-f]{12,}$', t)]
        long = [t for t in tokens if len(t) >= 22]
        shorthand |= len(long) >= 3 or bool(tokens and len(long) / len(tokens) >= 0.08) or len(glued(tokens)) >= 2
        long_sentence |= any(len(s.split()) > 25 for s in re.split(r'(?<=[.!?])\s+|\n+', prose))
    errors = []
    if shorthand:
        errors.append('Separate glued words with spaces; remove compressed shorthand.')
    if long_sentence:
        errors.append('Write at most 25 words per sentence.')
    sections = ('Facts', 'Decision', 'Next') if kind == 'peer' else (
        ('What is wrong', 'Why now', 'Options', 'Recommendation', 'If no answer') if kind == 'decision' else ())
    for section in sections:
        if not re.search(r'^\s*(?:#{1,6}\s*)?' + re.escape(section) + r'\b', plain, re.M | re.I):
            errors.append('Missing section: ' + section)
    if errors:
        raise FormatError(errors)


def outgoing(event):
    findings, formatting_only = [], True

    def collect(function, *args):
        nonlocal formatting_only
        try:
            function(*args)
        except FormatError as exc:
            findings.extend(exc.findings)
        except Exception as exc:
            findings.append(str(exc))
            formatting_only = False

    def inspect():
        tool, args = event.get('tool_name', ''), event.get('tool_input') or {}
        if tool == 'SendMessage':
            text = args.get('message') or args.get('content') or ''
            if text:  # Native subscriptions and lifecycle controls can have no prose body.
                collect(check, text, 'peer')
                if not SUBAGENT.fullmatch(str(args.get('to', '')).strip()):  # A brief to a child carries its restrictions.
                    collect(hold_wall, text)
        elif tool.endswith(('create_input', 'update_input')):
            content = args.get('content')
            if content is None:  # Metadata-only writes carry no new owner text.
                return
            if isinstance(content, str):
                content = json.loads(content)
            body = content.get('html', '')
            kinds = VisibleText(body).kinds
            valid_kind = len(kinds) == 1 and kinds[0] in ('decision', 'result')
            if not valid_kind:
                findings.append('Input HTML requires one explicit output-kind classification: decision or result.')
            collect(check, content.get('title', ''))
            collect(check, body, kinds[0] if valid_kind else 'result')

    collect(inspect)
    if findings:
        if formatting_only:
            raise FormatError(findings)
        raise FindingsError(findings)


def now():
    return datetime.now(timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def store_dir():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'ultraship' / 'text-lint'


def receipt_key():
    store = store_dir()
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = os.open(store, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Serialize initialization so a racing reader never sees the new key before its bytes exist.
        fcntl.flock(directory, fcntl.LOCK_EX)
        try:
            fd = os.open(store / 'key', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(os.urandom(32))
            except BaseException:
                (store / 'key').unlink()
                raise
        fd = os.open(store / 'key', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise OSError('Receipt key is not a regular file.')
            key = source.read(33)
        if len(key) != 32:
            raise OSError('Receipt key must contain 32 bytes.')
        return key
    finally:
        os.close(directory)


def input_identity(event):
    tool, original = event.get('tool_name', ''), event.get('tool_input', {})
    args = dict(original) if isinstance(original, dict) else original
    recipient = None
    if isinstance(args, dict):
        if tool == 'SendMessage':
            recipient = args.get('to')
            for field in ('message', 'content', 'summary'):
                args.pop(field, None)
        elif isinstance(tool, str) and tool.endswith(('create_input', 'update_input')):
            recipient = args.get('input_id') or args.get('workspace_id')
            content = args.get('content')
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except ValueError:
                    pass
            if isinstance(content, dict):
                content = dict(content)
                content.pop('html', None)
                content.pop('title', None)
                args['content'] = content
    return {
        'tool_name': tool,
        'recipient': str(recipient)[:200] if recipient is not None else None,
        'input_sha256': hashlib.sha256(canonical(original)).hexdigest(),
        'fields_sha256': hashlib.sha256(canonical(args)).hexdigest(),
    }


def signature(receipt, key):
    return hmac.new(key, canonical({k: v for k, v in receipt.items() if k != 'mac'}), hashlib.sha256).hexdigest()


def pending_path(identity):
    key = hashlib.sha256(canonical([identity.get(field) for field in
                                   ('session_id', 'agent_id', 'tool_name', 'recipient')])).hexdigest()
    return store_dir() / 'pending' / key


def clear_pending(receipt):
    path = pending_path(receipt)
    try:
        if json.loads(path.read_text())['id'] == receipt['id']:
            path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass


def prune_receipts(directory):
    timestamp = now().timestamp()
    receipts = []
    for path in directory.glob('*.json'):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if re.fullmatch(r'[0-9a-f]{32}', path.stem) and stat.S_ISREG(info.st_mode):
            receipts.append((info.st_mtime, path))
    remaining = len(receipts)
    young = 0
    for modified, path in sorted(receipts):
        if modified >= timestamp - 24 * 3600:
            young += 1
        elif modified < timestamp - 7 * 24 * 3600 or remaining > 2000:
            path.unlink(missing_ok=True)
            path.with_suffix('.consumed').unlink(missing_ok=True)
            remaining -= 1
    for path in (store_dir() / 'pending').glob('*'):
        try:
            if path.lstat().st_mtime < timestamp - 7 * 24 * 3600:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
    return young


def pending_entry(identity):
    path = pending_path(identity)
    try:
        entry = json.loads(path.read_text())
        receipt_id = entry['id']
        if entry['state'] not in ('open', 'spent') or not re.fullmatch(r'[0-9a-f]{32}', receipt_id):
            raise ValueError('Invalid pending receipt entry.')
        receipt_path = store_dir() / 'receipts' / (receipt_id + '.json')
        receipt = json.loads(receipt_path.read_bytes())
        created = datetime.fromisoformat(receipt['created_at'].replace('Z', '+00:00'))
        if timedelta(0) <= now() - created < timedelta(hours=24):
            if receipt_path.with_suffix('.consumed').exists():
                entry['state'] = 'spent'
            return entry
    except (OSError, ValueError, KeyError, TypeError):
        pass
    path.unlink(missing_ok=True)
    return None


def check_pending(event):
    args = event.get('tool_input') or {}
    tool = event.get('tool_name', '')
    if tool == 'SendMessage':
        prose = args.get('message') or args.get('content')
    elif tool.endswith(('create_input', 'update_input')):
        content = args.get('content') or {}
        if isinstance(content, str):
            content = json.loads(content)
        prose = content.get('html') or content.get('title')
    else:
        return
    session = event.get('session_id')
    if not prose or not isinstance(session, str) or not session:
        return
    entry = pending_entry({'session_id': session, 'agent_id': event.get('agent_id'), **input_identity(event)})
    if entry and entry['state'] == 'open':
        receipt_id = entry['id']
        path = store_dir() / 'receipts' / (receipt_id + '.consumed')
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        except OSError:
            raise ValueError('A formatting-only refusal to this recipient is pending. Cite its receipt `'
                             + receipt_id + '` with `<!-- ultraship-receipt:' + receipt_id + ' -->` in this message.') from None
        else:
            os.close(fd)
        raise ValueError('Receipt `' + receipt_id + '` is now spent. '
                         'Its message stays refused. Later messages need no citation.')


def write_receipt(event, findings, formatting_only, parent, resend_refused=False):
    key = receipt_key()
    directory = store_dir() / 'receipts'
    directory.mkdir(mode=0o700, exist_ok=True)
    if prune_receipts(directory) >= 2000:
        raise OSError('Receipt store contains 2000 receipts younger than 24 hours.')
    session = event.get('session_id')
    identity = input_identity(event)
    entry = None if resend_refused else pending_entry({'session_id': session, 'agent_id': event.get('agent_id'), **identity})
    spent = entry is not None and entry['state'] == 'spent'
    receipt = {
        'id': uuid.uuid4().hex,
        'session_id': event.get('session_id'),
        'tool_use_id': event.get('tool_use_id'),
        'agent_id': event.get('agent_id'),
        **identity,
        'findings': [finding[:500] for finding in findings],
        'formatting_only': formatting_only,
        'resend_allowed': formatting_only and parent is None and not spent and isinstance(session, str) and bool(session),
        'parent': parent,
        'created_at': now().isoformat().replace('+00:00', 'Z'),
    }
    receipt['mac'] = signature(receipt, key)
    body = canonical(receipt)
    if len(body) > 16 * 1024:
        raise OSError('Receipt exceeds 16 KiB.')
    fd, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(body)
        os.replace(temporary, directory / (receipt['id'] + '.json'))
    finally:
        Path(temporary).unlink(missing_ok=True)
    if receipt['resend_allowed'] or resend_refused:
        pending = pending_path(receipt)
        pending.parent.mkdir(mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=pending.parent)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump({'id': receipt['id'], 'state': 'spent' if resend_refused else 'open'}, output)
            os.replace(temporary, pending)
        finally:
            Path(temporary).unlink(missing_ok=True)
    prune_receipts(directory)
    return receipt


def citation(event):
    tool, args = event.get('tool_name', ''), event.get('tool_input') or {}
    if not isinstance(args, dict):
        return None
    if tool == 'SendMessage':
        fields = [args.get(name, '') for name in ('message', 'content', 'summary')]
    elif tool in ('Agent', 'Task'):
        fields = [args.get('prompt', '')]
    elif tool.endswith(('create_input', 'update_input')):
        content = args.get('content') or {}
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except ValueError:
                content = {'html': content}
        fields = [content.get(name, '') for name in ('html', 'title')] if isinstance(content, dict) else []
    else:
        return None
    text = '\n'.join(field for field in fields if isinstance(field, str))
    markers = re.findall(r'<!-- ultraship-receipt:([0-9a-f]{32}) -->', text)
    if 'ultraship-receipt' not in text:
        return None
    if len(markers) != 1 or text.count('ultraship-receipt') != 1:
        raise ValueError('Invalid receipt citation: require exactly one well-formed marker.')
    return markers[0]


def consume_receipt(receipt_id, event):
    try:
        path = store_dir() / 'receipts' / (receipt_id + '.json')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024:
                raise ValueError('Receipt must be a regular file of at most 16 KiB.')
            body = source.read(16 * 1024 + 1)
        if len(body) > 16 * 1024:
            raise ValueError('Receipt exceeds 16 KiB.')
        receipt = json.loads(body)
        if not isinstance(receipt, dict) or not isinstance(receipt.get('mac'), str):
            raise ValueError('Invalid receipt body.')
        if not hmac.compare_digest(receipt['mac'], signature(receipt, receipt_key())):
            raise ValueError('Invalid receipt mac.')
        if receipt.get('id') != receipt_id or receipt.get('resend_allowed') is not True:
            raise ValueError('Receipt does not permit a resend.')
        if not event.get('session_id') or receipt.get('session_id') != event['session_id']:
            raise ValueError('Receipt session differs or is absent.')
        if receipt.get('agent_id') != event.get('agent_id'):
            raise ValueError('Receipt sender differs.')
        identity = input_identity(event)
        if any(receipt.get(field) != identity[field] for field in ('tool_name', 'recipient', 'fields_sha256')):
            raise ValueError('Receipt tool, recipient or non-prose fields differ.')
        created = datetime.fromisoformat(receipt['created_at'].replace('Z', '+00:00'))
        if created.tzinfo is None or now() - created > timedelta(hours=24):
            raise ValueError('Receipt expires after 24 hours.')
        if created > now():
            raise ValueError('Receipt creation is in the future.')
        try:
            fd = os.open(path.with_suffix('.consumed'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise ValueError('Receipt is consumed.') from None
        os.close(fd)
        return receipt
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError('Invalid receipt citation: ' + str(exc)) from None


def hook(event, parse_error=None):
    parent, consumed = None, None
    try:
        if parse_error is not None:
            raise parse_error
        parent = citation(event)
        if parent:
            consumed = consume_receipt(parent, event)
        if event.get('tool_name') not in ('Agent', 'Task'):
            if not parent:
                check_pending(event)
            outgoing(event)
        if consumed:
            clear_pending(consumed)
        return
    except Exception as exc:
        findings = exc.findings if isinstance(exc, FindingsError) else [str(exc)]
        formatting_only = isinstance(exc, FindingsError) and exc.formatting_only
    reason = 'Output contract: ' + ' '.join(findings)
    try:
        receipt = write_receipt(event, findings, formatting_only, parent, resend_refused=consumed is not None)
    except Exception:
        reason += ' No receipt was written, so no resend of this message is allowed in any form.'
    else:
        if receipt['resend_allowed']:
            template = INPUT_TEMPLATE
            if event.get('tool_name') == 'SendMessage':
                template = PEER_TEMPLATE
            reason += (' You may resend once with the same action, recipient, scope and content, changed only in format.'
                       + ' Resend with this shape:\n' + template)
        else:
            reason += ' This refusal is not formatting-only, so no resend of this message is allowed in any form.' if not formatting_only else ''
            if parent:
                reason += ' Its receipt is used and no further resend of this message is allowed.'
        reason += ' Receipt: `' + receipt['id'] + '`.'
        if receipt['resend_allowed']:
            reason += ' To resend, put `<!-- ultraship-receipt:' + receipt['id'] + ' -->` in the resent prose.'
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))


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
            event = json.load(sys.stdin)
            if not isinstance(event, dict):
                raise ValueError('Hook event must be an object.')
        except Exception as exc:
            hook({}, parse_error=exc)
        else:
            hook(event)
    else:
        check(sys.stdin.read(), sys.argv[1] if len(sys.argv) > 1 else 'result')
