#!/usr/bin/env python3
"""Preflight a frozen CoC decision for a version-only native row re-anchor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


MAX_BYTES = 64 * 1024
SHA256 = r'[0-9a-f]{64}'
OID = r'[0-9a-f]{40}'
PR = r'https://github\.com/bettergroupinc/(?!\.{1,2}/)[A-Za-z0-9_.-]+/pull/[1-9][0-9]*'
VERSION = r'([ \t]*version:[ \t]+)[0-9]+\.[0-9]+\.[0-9]+'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def matches(pattern):
    return lambda value: isinstance(value, str) and re.fullmatch(pattern, value) is not None


def text(value):
    return isinstance(value, str) and bool(value.strip()) and '\x00' not in value


def integer(minimum):
    return lambda value: type(value) is int and value >= minimum


def literal(expected):
    return lambda value: type(value) is type(expected) and value == expected


def path(value, *, absolute=False):
    return (isinstance(value, str) and not any(ord(c) < 32 or c == '\\' for c in value)
            and value == value.strip() and value.startswith('/') == absolute
            and not {'', '.', '..'}.intersection(value.removeprefix('/').split('/')))


def extent(value):
    return (isinstance(value, list) and len(value) == 2
            and all(integer(1)(number) for number in value) and value[0] <= value[1])


def record(value, schema, prefix='', optional=()):
    require(isinstance(value, dict), f'{prefix or "decision"}: object required')
    for field, check in schema.items():
        if field not in value and field in optional:
            continue
        require(field in value, f'{prefix}{field}: missing')
        require(check(value[field]), f'{prefix}{field}: invalid')
    require(not value.keys() - schema.keys(), f'{prefix or "decision"}: unknown field')
    return True


# The executable schema is the field inventory used by preflight.
DIAGNOSTIC = {
    'run_id': integer(1), 'job_id': integer(1), 'attempt': integer(1),
    'head': matches(OID), 'tested_commit': matches(OID), 'tested_tree': matches(OID),
    'row_id': matches(r'[A-Za-z0-9][A-Za-z0-9_.-]*'),
    'observed': integer(0), 'expected': integer(1),
}
CORRECTION = {
    'prior_path': lambda value: path(value, absolute=True) and value.endswith('.json'),
    'prior_sha256': matches(SHA256),
    'refusal': text, 'refusal_source': text, 'defect': text,
}
SCHEMA = {
    'schema_version': literal(1), 'authority': literal('coc-standing-grant'),
    'pr_url': matches(PR), 'lane': text,
    'writer': matches(r'writer--(?:sol|sonnet|fable52)'),
    'checkout': lambda value: path(value, absolute=True),
    'branch': text, 'base': matches(OID), 'head': matches(OID), 'head_tree': matches(OID),
    'rows_file': lambda value: path(value) and value.startswith('tests/mutation/') and value.endswith('.toml'),
    'row_id': DIAGNOSTIC['row_id'], 'base_row_extent': extent, 'head_row_extent': extent,
    'base_rows_blob': matches(OID), 'head_rows_blob': matches(OID),
    'subject': path, 'base_subject_blob': matches(OID), 'head_subject_blob': matches(OID),
    'test': text, 'claim': text,
    'old_before': matches(VERSION), 'old_after': matches(VERSION), 'new_unchanged': matches(VERSION),
    'diagnostic': lambda value: record(value, DIAGNOSTIC, 'diagnostic.'),
    'correction': lambda value: record(value, CORRECTION, 'correction.'),
}


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON field')
        result[key] = value
    return result


def invalid_constant(_):
    raise ValueError('invalid JSON constant')


def frozen_content(filename, workspace):
    source = Path(filename)
    require(path(filename, absolute=True) and source.suffix == '.json', 'absolute JSON decision path required')
    require(path(workspace, absolute=True), 'absolute CoC workspace path required')
    require(source.parent == Path(workspace) / '.scratch/coc/rows', 'decision is outside the CoC workspace rows directory')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open('/', flags)
    try:
        for part in source.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(source.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o444,
                'decision must be a regular file with mode 0444')
        data = file.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, 'decision exceeds 64 KiB')
    return data


def validate(data, filename, digest):
    record(data, SCHEMA, optional=('correction',))
    require(data['base'] != data['head'], 'base: must differ from the draft head')
    require(data['base_subject_blob'] != data['head_subject_blob'],
            'head_subject_blob: must differ from the base subject blob')
    if data['base_rows_blob'] == data['head_rows_blob']:
        require(data['head_row_extent'] == data['base_row_extent'],
                'head_row_extent: must match the base extent for the same row blob')
    diag = data['diagnostic']
    require(diag['tested_commit'] != data['base'], 'diagnostic.tested_commit: must differ from the base')
    for field, expected in [('head', data['head']), ('tested_tree', data['head_tree']), ('row_id', data['row_id'])]:
        require(diag[field] == expected, f'diagnostic.{field}: differs from the decision')
    require(diag['observed'] != diag['expected'], 'diagnostic.observed: no anchor count failure')
    before, after, mutant = (data[key] for key in ('old_before', 'old_after', 'new_unchanged'))
    require(before != after and re.fullmatch(VERSION, before)[1] == re.fullmatch(VERSION, after)[1],
            'old_after: must change only the version')
    require(mutant not in (before, after), 'new_unchanged: must differ from both anchors')
    if correction := data.get('correction'):
        require(correction['prior_path'] != filename, 'correction.prior_path: use a new decision file')
        require(correction['prior_sha256'] != digest, 'correction.prior_sha256: use a new digest')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('decision', help='absolute path to the frozen decision JSON')
    parser.add_argument('sha256', help='SHA-256 of the frozen decision')
    parser.add_argument('--coc-workspace', required=True, help='independently verified CoC workspace root')
    args = parser.parse_args()
    try:
        require(matches(SHA256)(args.sha256), 'full lowercase SHA-256 required')
        data = frozen_content(args.decision, args.coc_workspace)
        require(hashlib.sha256(data).hexdigest() == args.sha256, 'SHA-256 does not match')
        try:
            decision = json.loads(data.decode('utf-8'), object_pairs_hook=unique_fields,
                                  parse_constant=invalid_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            raise ValueError('invalid decision JSON') from error
        validate(decision, args.decision, args.sha256)
    except (OSError, RuntimeError):
        parser.exit(1, 'row decision: cannot read the frozen decision\n')
    except ValueError as error:
        parser.exit(1, f'row decision: {error}\n')
    print(f'row decision preflight passed: {args.sha256}; zero write or retry authority')


if __name__ == '__main__':
    main()
