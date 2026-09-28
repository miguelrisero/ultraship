#!/usr/bin/env python3
"""Fail when a /goal block on stdin exceeds the 3,800-character budget."""
import sys

LIMIT = 3800
text = sys.stdin.read().strip()
print(f'{len(text)}/{LIMIT} characters')
sys.exit(0 if len(text) <= LIMIT else 1)
