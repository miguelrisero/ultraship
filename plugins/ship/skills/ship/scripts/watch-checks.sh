#!/usr/bin/env bash
# Wait for the required checks on a PR. Exit 0 when all pass, 1 on a failure,
# 2 when no required check starts within the start timeout, 3 on the overall timeout.
# Usage: watch-checks.sh <PR URL or number> [start-timeout-seconds] [timeout-seconds]
set -euo pipefail

pr="${1:?usage: watch-checks.sh <PR> [start-timeout] [timeout]}"
start_timeout="${2:-600}"
timeout="${3:-5400}"
interval=300
waited=0

while :; do
  # An empty list means CI has not started, not that CI is green.
  rows="$(gh pr checks "$pr" --required --json bucket,name,link --jq '.[] | [.bucket, .name, .link] | @tsv' 2>/dev/null || true)"
  buckets="$(cut -f1 <<<"$rows")"
  if [ -z "$buckets" ]; then
    if [ "$waited" -ge "$start_timeout" ]; then
      echo "no required checks started after ${waited}s"
      exit 2
    fi
  elif ! grep -qx pending <<<"$buckets"; then
    printf '%s\n' "$rows"
    if grep -qxE 'fail|cancel' <<<"$buckets"; then exit 1; fi
    exit 0
  fi
  if [ "$waited" -ge "$timeout" ]; then
    echo "checks still pending after ${waited}s"
    exit 3
  fi
  sleep "$interval"
  waited=$((waited + interval))
done
