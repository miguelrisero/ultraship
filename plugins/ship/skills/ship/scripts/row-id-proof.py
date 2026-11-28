#!/usr/bin/env python3
"""Find a row file and subject in a driver-verified CI receipt."""
import argparse
import hashlib
import json
import os
import re
import stat
import unicodedata


MAX_BYTES = 8 * 1024 * 1024
REPOSITORY = r'[A-Za-z0-9-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+'
ROW_ID = r'[A-Za-z0-9][A-Za-z0-9_.-]*'
OID = r'[0-9a-f]{40}'
FIELDS = {'schema', 'repository', 'pr', 'row_id', 'row_file', 'subject', 'base', 'head'}
ENDPOINT = {'commit', 'tree', 'blob', 'count'}
REFUSAL = 'row ID proof: lookup refused\n'


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(1, REFUSAL)


def require(condition):
    if not condition:
        raise ValueError


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def relative_path(value):
    return (isinstance(value, str) and value == value.strip() and value == unicodedata.normalize('NFC', value)
            and not re.search(r'[\x00-\x1f\x7f\ud800-\udfff\\]', value)
            and not {'', '.', '..'}.intersection(value.split('/')))


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def receipt_bytes(path):
    require(not re.search(r'/(?:tests/mutation|\.git)(?:/|$)', path, re.I))
    *parents, name = path[1:].split('/')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open('/', flags)
    try:
        for part in parents:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        parent = os.fstat(directory)
        require(parent.st_uid == os.getuid() and not parent.st_mode & 0o022)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o022 and info.st_size <= MAX_BYTES)
            data = stream.read(MAX_BYTES + 1)
    finally:
        os.close(directory)
    require(len(data) <= MAX_BYTES)
    return data


def validate_endpoint(record, commit, *, head=False):
    require(isinstance(record, dict) and record.keys() == ENDPOINT | ({'active_count'} if head else set()))
    require(record['commit'] == commit and matches(OID, record['tree']))
    count = record['count']
    require(type(count) is int and count >= 0)
    blob = record['blob']
    if head:
        active = record['active_count']
        require(matches(OID, blob) and count == 1 and type(active) is int and active == 1)
    else:
        require(matches(OID, blob) or (blob is None and count == 0))


def lookup(args):
    require(args.receipt.startswith('/') and relative_path(args.receipt[1:]))
    require(matches(r'[0-9a-f]{64}', args.sha256))
    require(matches(REPOSITORY, args.repository) and matches(ROW_ID, args.row_id))
    require(matches(OID, args.base) and matches(OID, args.head))
    pr_prefix = f'https://github.com/{args.repository}/pull/'
    require(args.pr_url.startswith(pr_prefix) and matches(r'[1-9][0-9]*', args.pr_url[len(pr_prefix):]))
    data = receipt_bytes(args.receipt)
    require(hashlib.sha256(data).hexdigest() == args.sha256)
    records = json.loads(data.decode('utf-8'), object_pairs_hook=unique_fields)
    require(isinstance(records, list))
    by_id, trees, blobs, counts = {}, {}, {}, {}
    for record in records:
        require(isinstance(record, dict) and record.keys() == FIELDS)
        require(record['schema'] == 'row-id-proof/v1' and record['repository'] == args.repository)
        pr = record['pr']
        require(type(pr) is int and pr > 0 and args.pr_url == f'{pr_prefix}{pr}')
        row_id = record['row_id']
        require(matches(ROW_ID, row_id) and row_id not in by_id)
        require(relative_path(record['row_file']) and relative_path(record['subject']))
        for side, commit in (('base', args.base), ('head', args.head)):
            endpoint = record[side]
            validate_endpoint(endpoint, commit, head=side == 'head')
            tree, blob = endpoint['tree'], endpoint['blob']
            require(trees.setdefault(commit, tree) == tree)
            require(blobs.setdefault((tree, record['row_file']), blob) == blob)
            if blob is not None:
                count = endpoint['count']
                require(counts.setdefault((blob, row_id), count) == count)
        by_id[row_id] = record
    require(args.row_id in by_id)
    match = by_id[args.row_id]
    return {'row_file': match['row_file'], 'subject': match['subject']}


def main():
    parser = Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--receipt', required=True)
    for field in ('sha256', 'repository', 'pr-url', 'base', 'head', 'row-id'):
        parser.add_argument('--' + field, required=True)
    args = parser.parse_args()
    try:
        result = lookup(args)
    except (OSError, ValueError, RecursionError):
        parser.exit(1, REFUSAL)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
