#!/usr/bin/env python3
"""Append validated retirement records without reading the row file."""
import json
import os
from pathlib import Path
import stat
import sys
import tomllib


def basic(value):
    return '"' + ''.join(
        '\\' + char if char in '\\"' else
        f'\\u{ord(char):04X}' if ord(char) < 0x20 or ord(char) == 0x7F else char
        for char in value
    ) + '"'


def canonical_regular_file(path):
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        return False
    metadata = os.lstat(path)
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def main(args):
    if len(args) != 1:
        print('usage: retire-rows.py <record-file>', file=sys.stderr)
        return 2
    try:
        record_path = Path(args[0])
        if (('tests', 'mutation') in zip(record_path.parts, record_path.parts[1:])
                or not canonical_regular_file(args[0])):
            raise ValueError('record_file must be a canonical single-link regular file outside tests/mutation')
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if not isinstance(record, dict) or set(record) != {'row_file', 'rows'}:
            raise ValueError('record must contain exactly row_file and rows')
        if not isinstance(record['row_file'], str):
            raise ValueError('row_file must be a string')
        path = Path(record['row_file'])
        if (not path.is_absolute() or path.suffix != '.toml'
                or ('tests', 'mutation') not in zip(path.parts, path.parts[1:])):
            raise ValueError('row_file must be an absolute tests/mutation .toml path')
        if not canonical_regular_file(record['row_file']):
            raise ValueError('row_file must be an existing regular file, not a symlink')
        rows = record['rows']
        if not isinstance(rows, list) or not rows:
            raise ValueError('rows must be a nonempty list')
        ids = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {'id', 'reason'}
                    or any(not isinstance(value, str) or not value for value in row.values())):
                raise ValueError('each row must contain exactly nonempty id and reason strings')
            if row['id'] in ids:
                raise ValueError('row ids must be unique')
            ids.add(row['id'])
        text = ''.join('\n[[retired]]\nid = ' + basic(row['id'])
                       + '\nreason = ' + basic(row['reason']) + '\n' for row in rows)
        if tomllib.loads(text) != {'retired': rows}:
            raise ValueError('appended text does not preserve retirement records')
        text.encode('utf-8')
        with path.open('a', encoding='utf-8') as output:
            output.write(text)
    except (OSError, ValueError) as exc:
        print(f'REFUSE {exc}', file=sys.stderr)
        return 2
    print(f'appended {len(rows)} [[retired]] tables to {record["row_file"]}: '
          + ', '.join(row['id'] for row in rows))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
