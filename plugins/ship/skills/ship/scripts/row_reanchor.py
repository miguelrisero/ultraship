#!/usr/bin/env python3
"""Derive a row's paired fields while preserving its whole-file mutant hunks."""
import argparse
import difflib
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


def row_statements(text, row_id):
    """Scan complete statements so string contents never become table headers."""
    source = lines(text)
    rows, current, index, nested = [], None, 0, False
    while index < len(source):
        start = index
        if not source[index].strip() or source[index].lstrip().startswith('#'):
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
                rows.append(current)
            elif re.match(r'\[\[?\s*row\.', stripped) and current is not None:
                nested = True
                current.append((start, index, statement, {}))
            else:
                current = None
        elif current is not None:
            current.append((start, index, statement, {} if nested else parsed))
    matching = [row for row in rows if any(item[3].get('id') == row_id for item in row)]
    require(len(matching) == 1, 'row ID must match exactly once')
    selected = matching[0]
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
    return values, fields


def opcodes(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


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


def run(args):
    row_file = Path(args.row_file)
    require(row_file.is_absolute() and stat.S_ISREG(row_file.lstat().st_mode)
            and row_file.resolve() == row_file, 'row file must be absolute, regular and canonical without links')

    def git(*words):
        return subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(row_file.parent), *words],
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    root = Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve()
    relative = row_file.relative_to(root).as_posix()
    subject = PurePosixPath(args.subject)
    require(not subject.is_absolute() and args.subject == subject.as_posix()
            and '..' not in subject.parts and subject.parts, 'subject must be repository-relative')
    base_sha = git('rev-parse', '--verify', '--end-of-options', args.base + '^{commit}').decode().strip()
    head_sha = git('rev-parse', '--verify', '--end-of-options', args.head + '^{commit}').decode().strip()
    require(head_sha == git('rev-parse', 'HEAD').decode().strip(), 'head must equal HEAD')

    def blob(sha, path):
        return git('cat-file', 'blob', sha + ':' + path)

    original = row_file.read_bytes()
    require(original == blob(head_sha, relative), 'working row file differs from head')
    text = original.decode('utf-8')
    base_values, base_fields = row_statements(blob(base_sha, relative).decode('utf-8'), args.row_id)
    head_values, head_fields = row_statements(text, args.row_id)
    require(base_values['file'] == head_values['file'] == args.subject, 'subject mismatch')
    require([field[2] for key, field in base_fields.items() if key not in ('old', 'new')]
            == [field[2] for key, field in head_fields.items() if key not in ('old', 'new')], 'frozen row statements differ')

    def subject_text(sha):
        return blob(sha, args.subject).decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')

    base, head = subject_text(base_sha), subject_text(head_sha)
    old, new, count = derive(base_values['old'], base_values['new'], base, head)
    source = lines(text)
    replacements = []
    for key, value in (('old', old), ('new', new)):
        start, end, statement = head_fields[key]
        prefix = re.match(r'''[ \t]*(?:KEY|"KEY"|'KEY')[ \t]*=[ \t]*'''.replace('KEY', key), statement)
        require(prefix is not None, 'unsupported key prefix')
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
    _, edited_fields = row_statements(edited_text, args.row_id)

    def without_pair(value, fields):
        kept = lines(value)
        for start, end, _ in sorted((fields['old'], fields['new']), reverse=True):
            del kept[start:end]
        return ''.join(kept)

    require(without_pair(text, head_fields) == without_pair(edited_text, edited_fields),
            'bytes outside paired statements differ')
    result = edited_text.encode('utf-8')
    require(row_file.read_bytes() == original, 'row file changed during derivation')
    staged = row_file.with_name('.row-reanchor-' + uuid.uuid4().hex)
    created = False
    try:
        descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IMODE(row_file.stat().st_mode))
        created = True
        with os.fdopen(descriptor, 'wb') as handle:
            os.fchmod(handle.fileno(), stat.S_IMODE(row_file.stat().st_mode))
            handle.write(result)
            handle.flush()
            os.fsync(handle.fileno())
        require(staged.read_bytes() == result, 'staged write read-back differs')
        require(row_file.read_bytes() == original, 'row file changed during staged write')
        os.replace(staged, row_file)
    finally:
        if created and staged.exists():
            staged.unlink()
    require(row_file.read_bytes() == result, 'write read-back differs')
    print('PASS')
    print('row_file=' + str(row_file))
    print('row_id=' + args.row_id)
    print('subject=' + args.subject)
    print('base=' + base_sha)
    print('head=' + head_sha)
    print('base_span_lines=' + str(len(lines(base_values['old']))))
    print('head_span_lines=' + str(len(lines(old))))
    print('head_old_count=' + str(head.count(old)))
    print('hunk_count=' + str(count))
    print('tomllib=PASS')
    print('changed_statements=' + str(sum(statement != head_fields[key][2]
          for key, (_, _, statement) in zip(('old', 'new'), replacements))))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('invalid arguments')


def main():
    try:
        parser = Parser(allow_abbrev=False, add_help=False)
        for name in ('row-file', 'row-id', 'subject', 'base', 'head'):
            parser.add_argument('--' + name, required=True)
        run(parser.parse_args())
        return 0
    except Refused as error:
        print('REFUSED: ' + str(error))
    except Exception as error:
        print('REFUSED: ' + type(error).__name__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
