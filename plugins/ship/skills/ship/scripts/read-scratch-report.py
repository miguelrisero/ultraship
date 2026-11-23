#!/usr/bin/env python3
"""Print a bounded text excerpt from a local scratch report."""

import os
import re
import stat
import sys

MAX_BYTES = 1024 * 1024
MAX_CHARS = 5000
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY
DATA_IMAGE_LINE = re.compile(r"^.*data:image/.*\n?", re.IGNORECASE | re.MULTILINE)
TERMINAL_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class Refusal(Exception):
    pass


def read_report(path: str) -> str:
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise Refusal("expected a relative report path")

    directory = os.open(".scratch", DIRECTORY_FLAGS)
    try:
        for part in parts[:-1]:
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], FILE_FLAGS, dir_fd=directory)
    finally:
        os.close(directory)

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Refusal("expected a regular file")
        if info.st_uid != os.geteuid():
            raise Refusal("expected a file owned by the current user")
        if info.st_nlink != 1:
            raise Refusal("expected exactly one file link")
        if info.st_size > MAX_BYTES:
            raise Refusal("report exceeds 1 MiB")

        data = bytearray()
        while len(data) <= MAX_BYTES:
            chunk = os.read(fd, MAX_BYTES + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise Refusal("report exceeds 1 MiB")
    finally:
        os.close(fd)

    text = DATA_IMAGE_LINE.sub("", data.decode("utf-8", errors="replace"))
    return TERMINAL_CONTROL.sub(lambda match: f"\\x{ord(match[0]):02x}", text)[:MAX_CHARS]


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise Refusal("expected one report path")
        excerpt = read_report(sys.argv[1])
    except Refusal as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("Refused: cannot open or read the scratch report", file=sys.stderr)
        return 1

    sys.stdout.buffer.write(excerpt.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
