#!/usr/bin/env python3
"""Derive a row's paired fields while preserving its whole-file mutant hunks."""
import argparse
from collections import Counter
from contextlib import contextmanager
import difflib
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tomllib
import uuid


class Refused(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def lines(text):
    parts = text.split('\n')
    return [part + '\n' for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def basic(value):
    short = {'\b': '\\b', '\t': '\\t', '\n': '\\n', '\f': '\\f', '\r': '\\r',
             '\\': '\\\\', '"': '\\"'}
    encoded = '"' + ''.join(short.get(char, '\\u%04X' % ord(char) if ord(char) < 32 or ord(char) == 127
                                    else char) for char in value) + '"'
    require(tomllib.loads('value = ' + encoded)['value'] == value, 'string round-trip')
    return encoded


def scan_rows(text):
    """Scan complete statements so string contents never become table headers."""
    source = lines(text)
    rows, split_rows, standalone_blanks = [], set(), set()
    current, index, nested = None, 0, False
    while index < len(source):
        start = index
        if not source[index].strip() or source[index].lstrip().startswith('#'):
            if not source[index].strip(' \t\r\n'):
                standalone_blanks.add(index)
            index += 1
            continue
        while True:
            index += 1
            statement = ''.join(source[start:index])
            try:
                parsed = tomllib.loads(statement)
                break
            except tomllib.TOMLDecodeError:
                require(index < len(source), 'incomplete TOML statement')
        stripped = statement.lstrip()
        if stripped.startswith('['):
            if re.fullmatch(r'\[\[\s*row\s*\]\]\s*(?:#[^\n]*)?\n?', stripped):
                current, nested = [], False
                rows.append((start, current))
            elif parsed.get('row') == [{}]:
                current = None
                rows.append((start, []))
            elif isinstance(parsed.get('row'), dict) and parsed['row']:
                if current is not None:
                    nested = True
                    current.append((start, index, statement, {}))
                elif rows:
                    split_rows.add(rows[-1][0])
            else:
                current = None
        elif current is not None:
            current.append((start, index, statement, {} if nested else parsed))
    return rows, split_rows, standalone_blanks


def row_statements(text, row_id):
    rows, split_rows, _ = scan_rows(text)
    matching = [(start, row) for start, row in rows if any(item[3].get('id') == row_id for item in row)]
    require(len(matching) == 1, 'row ID must match exactly once')
    first, selected = matching[0]
    require(first not in split_rows, 'row table is not contiguous')
    values, fields = {}, {}
    for start, end, statement, parsed in selected:
        if not parsed:
            fields['nested:' + str(start)] = (start, end, statement)
            continue
        require(len(parsed) == 1, 'one key per row statement')
        key = next(iter(parsed))
        require(key not in values, 'duplicate row key')
        values.update(parsed)
        fields[key] = (start, end, statement)
    require(all(key in values for key in ('id', 'claim', 'file', 'old', 'new', 'test')), 'required row keys')
    require(isinstance(values['old'], str) and isinstance(values['new'], str)
            and values['old'] and values['old'] != values['new'], 'invalid base pair')
    require(type(values.get('expect', 1)) is int and values.get('expect', 1) == 1, 'expect must be 1')
    return values, fields, (first + 1, selected[-1][1])


def scanned_extents(rows, split_rows):
    extents = {}
    for start, row in rows:
        for _, _, _, parsed in row:
            if 'id' in parsed:
                row_id = parsed['id']
                require(row_id not in extents, 'row ID must match exactly once')
                require(start not in split_rows, 'row table is not contiguous')
                extents[row_id] = (start, row[-1][1])
    return extents


def opcodes(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def separator_lines(rows, blanks):
    separators = blanks.copy()
    for start, row in rows:
        if row:
            separators.difference_update(range(start, row[-1][1]))
    return separators


def mask_rows(source, extents, restored_ids, separators):
    starts = {start: (key, end) for key, (start, end) in extents.items() if key in restored_ids}
    masked, index = [], 0
    while index < len(source):
        if index in starts:
            key, index = starts[index]
            masked.append(((key,), False))
        else:
            masked.append((source[index], index in separators))
            index += 1
    return masked


def is_row(item):
    return isinstance(item[0], tuple)


def restoration_items(base, head):
    def alignment(items):
        # Keep separators on the same side of a row when repeated blanks align.
        keys, following_row = [], None
        for item in reversed(items):
            keys.append((item, following_row if item[1] else None))
            if not item[1]:
                following_row = item[0] if is_row(item) else None
        return keys[::-1]

    for tag, i1, i2, j1, j2 in opcodes(alignment(base), alignment(head)):
        base_chunk, head_chunk = base[i1:i2], head[j1:j2]
        kept = [(item, not is_row(item)) for item in head_chunk]
        if tag != 'equal':
            require(not any(map(is_row, head_chunk)), 'restored row moved')
        if tag == 'equal' or not any(map(is_row, base_chunk)):
            yield from kept
            continue
        fixed = [index for index, item in enumerate(base_chunk) if not is_row(item) and not item[1]]
        added = [(item, False) for item in base_chunk]
        if fixed:
            first, last = fixed[0], fixed[-1]
            require(not any(map(is_row, base_chunk[first:last + 1])), 'restored row position is ambiguous')
            yield from added[:first] + kept + added[last + 1:]
        else:
            require(all(item[1] for item in head_chunk), 'restored row position is ambiguous')
            yield from added + kept


def restoration_position(expected_items, actual, row_id):
    expected = list(expected_items)
    if [item for item, _ in expected] != actual:
        return None
    head_count = 0
    for item, from_head in expected:
        if item[0] == (row_id,):
            return head_count
        head_count += from_head
    return None


def restoration_check(base_text, start_text, restored_text, row_id):
    b, h, f = map(lines, (base_text, start_text, restored_text))
    b_rows, b_split, b_blanks = scan_rows(base_text)
    h_rows, h_split, h_blanks = scan_rows(start_text)
    f_rows, f_split, f_blanks = scan_rows(restored_text)
    eb = scanned_extents(b_rows, b_split)
    eh, ef = scanned_extents(h_rows, h_split), scanned_extents(f_rows, f_split)
    for text, extents in ((base_text, eb), (start_text, eh), (restored_text, ef)):
        parsed_rows = tomllib.loads(text).get('row', [])
        require(isinstance(parsed_rows, list) and all(isinstance(row, dict) for row in parsed_rows)
                and Counter(row['id'] for row in parsed_rows if 'id' in row) == Counter(extents.keys()),
                'row ID must match exactly once')

    def row_lines(source, extents, key):
        return source[slice(*extents[key])] if key in extents else None

    require(row_id in eb, 'row missing at the merge base')
    require(row_id in ef, 'row missing at the restoration commit')
    restored = row_lines(f, ef, row_id)
    require(restored == row_lines(b, eb, row_id), 'restored row differs from the merge base')
    require(restored != row_lines(h, eh, row_id), 'restoration commit leaves the row unchanged')

    restored_ids = [key for key in ef if key in eb
                    and row_lines(f, ef, key) == row_lines(b, eb, key)
                    and row_lines(f, ef, key) != row_lines(h, eh, key)]

    def outside_rows(source, rows, extents, blanks):
        omitted = blanks.copy()
        # Only blank separators outside row tables may return with a row.
        for start, row in rows:
            if row:
                omitted.difference_update(range(start, row[-1][1]))
        for key in restored_ids:
            if key in extents:
                omitted.update(range(*extents[key]))
        return [line for index, line in enumerate(source) if index not in omitted]

    require(outside_rows(f, f_rows, ef, f_blanks) == outside_rows(h, h_rows, eh, h_blanks),
            'restoration changed bytes outside restored rows')

    base = mask_rows(b, eb, restored_ids, separator_lines(b_rows, b_blanks))
    head = mask_rows(h, eh, restored_ids, separator_lines(h_rows, h_blanks))
    final = mask_rows(f, ef, restored_ids, separator_lines(f_rows, f_blanks))
    insert_after = restoration_position(restoration_items(base, head), final, row_id)
    require(insert_after is not None, 'restoration changed bytes outside restored rows')

    def line_range(extents):
        if row_id in extents:
            start, end = extents[row_id]
            return [start + 1, end]
        return None

    return {'restoration_lines': line_range(ef), 'starting_lines': line_range(eh),
            'insert_after': insert_after,
            'restored_rows': len(restored_ids), 'restoration_base_equal': True,
            'restoration_outside_equal': True}


def hunks(before, after):
    a, b = lines(before), lines(after)
    return [(tag, a[i:j], b[k:l]) for tag, i, j, k, l in opcodes(a, b) if tag != 'equal']


def derive(old, new, base, head):
    require(base.count(old) == 1, 'base old count must be 1')
    a, b = lines(old), lines(new)
    edits = [op for op in opcodes(a, b) if op[0] != 'equal']
    require(edits, 'missing mutant hunk')
    offsets = [0]
    for line in a:
        offsets.append(offsets[-1] + len(line))
    anchors = []
    for number, (_, i, j, k, l) in enumerate(edits):
        start, end = i, j
        if i == j:
            require(a, 'insertion needs an adjacent equal line')
            start, end = (i - 1, j) if i else (i, i + 1)
        if number == 0:
            start = 0
        if number == len(edits) - 1:
            end = len(a)
        require(not anchors or offsets[start] >= anchors[-1][1], 'overlapping anchors')
        anchor = ''.join(a[start:end])
        require(anchor, 'empty anchor')
        replacement = ''.join(a[start:i] + b[k:l] + a[j:end])
        anchors.append((offsets[start], offsets[end], anchor, replacement))
    origin = base.index(old)
    previous = origin
    for start, end, anchor, _ in anchors:
        require(base.find(anchor, previous) == origin + start, 'anchor is not the first occurrence on main')
        previous = origin + end
    require(base.count(anchors[0][2]) == 1 and head.count(anchors[0][2]) == 1, 'anchor 1 must be unique')
    base_lines, head_lines = lines(base), lines(head)
    equal_blocks = [op for op in opcodes(base_lines, head_lines) if op[0] == 'equal']
    base_offsets, head_offsets = [0], [0]
    for source, positions in ((base_lines, base_offsets), (head_lines, head_offsets)):
        for line in source:
            positions.append(positions[-1] + len(line))
    located, cursor = [], 0
    for left, right, anchor, replacement in anchors:
        start = head.find(anchor, cursor)
        require(start >= 0, 'edit site missing at head')
        cursor = start + len(anchor)
        require(any(base_offsets[i] <= origin + left and origin + right <= base_offsets[j]
                    and start == head_offsets[k] + origin + left - base_offsets[i]
                    and cursor <= head_offsets[l] for _, i, j, k, l in equal_blocks),
                'anchor does not map to its base equal block')
        located.append((start, cursor, replacement))
    start, end = located[0][0], located[-1][1]
    head_old = head[start:end]
    head_new = head_old
    for left, right, replacement in reversed(located):
        head_new = head_new[:left - start] + replacement + head_new[right - start:]
    require(head.count(head_old) == 1, 'head old count must be 1')
    require(hunks(base, base.replace(old, new, 1)) == hunks(head, head.replace(head_old, head_new, 1)),
            'whole-file mutant hunks differ')
    return head_old, head_new, len(edits)


@contextmanager
def staged_bytes(path, data, mode):
    staged = path.with_name('.row-reanchor-' + uuid.uuid4().hex)
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        require(staged.read_bytes() == data, 'staged write read-back differs')
        yield staged
    finally:
        staged.unlink(missing_ok=True)


@contextmanager
def record_lock(path):
    try:
        path.parent.mkdir(mode=0o700)
    except FileExistsError:
        require(path.parent.is_dir() and not path.parent.is_symlink(), 'invalid record directory')
    else:
        path.parent.chmod(0o700)

    # Keep a separate inode so replacing the record never replaces the lock.
    lock = path.with_suffix('.lock')
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, 'r+b') as handle:
        metadata = os.fstat(handle.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1, 'invalid authorization record lock')
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def merge_record(path, identity, entry, check_before_replace):
    rows = {}
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        pass
    else:
        require(stat.S_ISREG(metadata.st_mode), 'invalid authorization record file')
        prior = json.loads(path.read_bytes())
        require(isinstance(prior, dict), 'invalid authorization record')
        if all(prior.get(key) == value for key, value in identity.items()):
            require(prior.get('schema') == 1 and isinstance(prior.get('rows'), list),
                    'invalid authorization record')
            rows = {(row['row_file'], row['row_id']): row for row in prior['rows']}
    rows[entry['row_file'], entry['row_id']] = entry
    data = (json.dumps({'schema': 1, **identity, 'rows': list(rows.values())}) + '\n').encode('utf-8')
    with staged_bytes(path, data, 0o600) as record_stage:
        check_before_replace('staged write')
        os.replace(record_stage, path)


def run(args):
    row_file = Path(args.row_file)
    require(row_file.is_absolute() and stat.S_ISREG(row_file.lstat().st_mode)
            and row_file.resolve() == row_file, 'row file must be absolute, regular and canonical without links')

    def git(operation, *words, not_ancestor=None):
        try:
            return subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(row_file.parent), *words],
                                  check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        except subprocess.CalledProcessError as error:
            if not_ancestor is not None and error.returncode == 1:
                raise Refused(not_ancestor) from None
            raise Refused(f'{operation} (Git exit {error.returncode})') from None

    def commit_sha(operation, ref):
        return git(operation, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()

    root = Path(git('find worktree root', 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    relative = row_file.relative_to(root).as_posix()
    subject = PurePosixPath(args.subject)
    require(not subject.is_absolute() and args.subject == subject.as_posix()
            and '..' not in subject.parts and subject.parts, 'subject must be repository-relative')
    lane = git('read lane branch', 'branch', '--show-current').decode().rstrip('\n')
    require(lane, 'lane branch required')
    base_sha = commit_sha('resolve base commit', args.base)
    head_sha = commit_sha('resolve head commit', args.head)
    require(head_sha == git('read HEAD', 'rev-parse', 'HEAD').decode().strip(), 'head must equal HEAD')
    record = Path(git('find record path', 'rev-parse', '--path-format=absolute', '--git-path',
                      'ship/row-auth.json').decode().rstrip('\n'))

    def blob(operation, sha, path):
        return git(operation, 'cat-file', 'blob', sha + ':' + path)

    original = row_file.read_bytes()
    require(original == blob('read head row blob', head_sha, relative), 'working row file differs from head')
    text = original.decode('utf-8')
    base_text = blob('read base row blob', base_sha, relative).decode('utf-8')
    restoration_fields = {}
    if args.restoration is not None:
        restoration = commit_sha('resolve restoration commit', args.restoration)
        git('check restoration ancestry', 'merge-base', '--is-ancestor', restoration, head_sha,
            not_ancestor='restoration must be HEAD or an ancestor of HEAD')
        parents = git('read restoration parents', 'rev-list', '--parents', '-n', '1', restoration).decode().split()
        require(len(parents) == 2, 'restoration must have exactly one parent')
        restoration_parent = parents[1]
        git('check base ancestry', 'merge-base', '--is-ancestor', base_sha, restoration_parent,
            not_ancestor='merge base must be an ancestor of the restoration parent')
        reason = 'restoration commit must change only the row file'
        changes = git('read restoration diff', 'diff-tree', '-r', '--raw', '--no-commit-id', '--no-renames', '-z',
                      restoration_parent, restoration).split(b'\0')
        path = relative.encode('utf-8')
        require(len(changes) == 3 and changes[1] == path and changes[2] == b'', reason)
        old_mode, mode, _, _, status = changes[0].split()
        base_entry = git('read base row entry', 'ls-tree', '--full-tree', '-z', base_sha, '--', ':(literal)' + relative)
        require(mode in (b'100644', b'100755') and base_entry.startswith(mode + b' blob ')
                and base_entry.endswith(b'\t' + path + b'\0')
                and (status, old_mode) in ((b'A', b':000000'), (b'M', b':' + mode)), reason)
        start_text = '' if status == b'A' else blob('read restoration parent row blob', restoration_parent,
                                                   relative).decode('utf-8')
        restored_text = blob('read restoration row blob', restoration, relative).decode('utf-8')
        restoration_fields = {'restoration': restoration, 'restoration_parent': restoration_parent,
                              **restoration_check(base_text, start_text, restored_text, args.row_id)}
    base_values, base_fields, base_extent = row_statements(base_text, args.row_id)
    head_values, head_fields, _ = row_statements(text, args.row_id)
    require(base_values['file'] == head_values['file'] == args.subject, 'subject mismatch')
    require([field[2] for key, field in base_fields.items() if key not in ('old', 'new')]
            == [field[2] for key, field in head_fields.items() if key not in ('old', 'new')], 'frozen row statements differ')

    def subject_text(operation, sha):
        return blob(operation, sha, args.subject).decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')

    base = subject_text('read base subject blob', base_sha)
    head = subject_text('read head subject blob', head_sha)
    old, new, count = derive(base_values['old'], base_values['new'], base, head)
    source = lines(text)
    replacements = []
    for key, value in (('old', old), ('new', new)):
        start, end, statement = head_fields[key]
        prefix = re.match(r'''[ \t]*(?:KEY|"KEY"|'KEY')[ \t]*=[ \t]*'''.replace('KEY', key), statement)
        require(prefix is not None, 'unsupported key prefix')
        if head_values[key] == value:
            continue
        ending = '\r\n' if statement.endswith('\r\n') else '\n' if statement.endswith('\n') else ''
        replacements.append((start, end, prefix[0] + basic(value) + ending))
    edited = source[:]
    for start, end, statement in sorted(replacements, reverse=True):
        edited[start:end] = [statement]
    edited_text = ''.join(edited)
    before, after = tomllib.loads(text), tomllib.loads(edited_text)
    targets = [row for row in after['row'] if row.get('id') == args.row_id]
    require(len(targets) == 1 and targets[0]['old'] == old and targets[0]['new'] == new, 'edited pair mismatch')
    targets[0]['old'], targets[0]['new'] = head_values['old'], head_values['new']
    require(before == after, 'other TOML values differ')
    _, edited_fields, edited_extent = row_statements(edited_text, args.row_id)

    def without_pair(value, fields):
        kept = lines(value)
        for start, end, _ in sorted((fields['old'], fields['new']), reverse=True):
            del kept[start:end]
        return ''.join(kept)

    require(without_pair(text, head_fields) == without_pair(edited_text, edited_fields),
            'bytes outside paired statements differ')
    result = edited_text.encode('utf-8')
    entry = {'row_file': relative, 'row_id': args.row_id, 'subject': args.subject,
             'expected_count': head_values.get('expect', 1), 'head_old_count': head.count(old),
             'hunk_count': count, 'mutant_unchanged': True, 'changed_statements': len(replacements),
             'base_lines': base_extent, 'lines': edited_extent, **restoration_fields}
    identity = {'lane': lane, 'base': base_sha, 'head': head_sha}

    def check_worktree(phase):
        require(git('recheck lane branch', 'branch', '--show-current').decode().rstrip('\n') == lane,
                'lane branch changed during ' + phase)
        require(git('recheck HEAD', 'rev-parse', 'HEAD').decode().strip() == head_sha,
                'HEAD changed during ' + phase)
        require(row_file.read_bytes() == original, 'row file changed during ' + phase)

    with record_lock(record):
        check_worktree('derivation')
        if replacements:
            mode = stat.S_IMODE(row_file.stat().st_mode)
            with staged_bytes(row_file, result, mode) as stage:
                check_worktree('staged write')
                os.replace(stage, row_file)
            record_output = 'none'
        else:
            merge_record(record, identity, entry, check_worktree)
            record_output = str(record)
    print('PASS')
    for key, value in {'schema': 1, **identity, **entry, 'base_span_lines': len(lines(base_values['old'])),
                       'head_span_lines': len(lines(old)), 'tomllib': 'PASS', 'record': record_output}.items():
        print(key + '=' + (value if isinstance(value, str) and value.isprintable() else json.dumps(value)))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('invalid arguments')


def main():
    try:
        parser = Parser(allow_abbrev=False, add_help=False)
        for name in ('row-file', 'row-id', 'subject', 'base', 'head'):
            parser.add_argument('--' + name, required=True)
        parser.add_argument('--restoration')
        run(parser.parse_args())
        return 0
    except Refused as error:
        print('REFUSED: ' + str(error))
    except Exception as error:
        print('REFUSED: ' + type(error).__name__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
