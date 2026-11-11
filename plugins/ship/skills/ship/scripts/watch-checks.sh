#!/usr/bin/env bash
# Wait for the required checks on a PR. Exit 0 when all pass, 1 on a failure,
# 2 when no required check starts within the start timeout, 3 on the overall timeout,
# 4 when the base branch's required contexts cannot be determined.
# Usage: watch-checks.sh <PR URL or number> [start-timeout-seconds] [timeout-seconds]
# WATCH_CHECKS_IGNORE: exact context names, one per line; empty by default.
# Example: WATCH_CHECKS_IGNORE="Merge Queue Gate" watch-checks.sh 123
set -euo pipefail

pr="${1:?usage: watch-checks.sh <PR> [start-timeout] [timeout]}"
start_timeout="${2:-600}"
timeout="${3:-5400}"
interval=300
waited=0

if ! target="$(gh pr view "$pr" --json url,baseRefName --jq '[(.url | split("/")[3:5] | join("/")), (.baseRefName | @uri)] | @tsv')" || [ -z "$target" ]; then
  echo "cannot determine required contexts: PR base lookup failed"
  exit 4
fi
IFS=$'\t' read -r repo base <<<"$target"
if [ -z "$repo" ] || [ -z "$base" ]; then
  echo "cannot determine required contexts: PR base is missing"
  exit 4
fi
# Read both protection sources once; polling stays on GraphQL.
if ! classic="$(gh api "repos/$repo/branches/$base/protection/required_status_checks" --jq '.contexts[]' 2>/dev/null)"; then classic=; fi
if ! rules="$(gh api "repos/$repo/rules/branches/$base" --paginate --jq '.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context' 2>/dev/null)"; then rules=; fi
required="$(printf '%s\n' "$classic" "$rules" | sed '/^$/d' | sort -u)"
if [ -z "$required" ]; then
  echo "cannot determine required contexts for $repo base $base: protection APIs returned no contexts"
  exit 4
fi
required="$(while IFS= read -r name; do
  if ! grep -Fxq -- "$name" <<<"${WATCH_CHECKS_IGNORE:-}"; then printf '%s\n' "$name"; fi
done <<<"$required")"
[ -n "$required" ] || exit 0

while :; do
  rows="$(gh pr checks "$pr" --required --json bucket,name,link --jq '.[] | [.bucket, .name, .link] | @tsv' 2>/dev/null || true)"
  rows="$(while IFS=$'\t' read -r bucket name link; do
    if [ -n "$name" ] && grep -Fxq -- "$name" <<<"$required"; then
      printf '%s\t%s\t%s\n' "$bucket" "$name" "$link"
    fi
  done <<<"$rows")"
  if [ -z "$rows" ]; then
    if [ "$waited" -ge "$start_timeout" ]; then
      echo "no required checks started after ${waited}s"
      exit 2
    fi
  else
    reported="$(cut -f2 <<<"$rows")"
    while IFS= read -r name; do
      if ! grep -Fxq -- "$name" <<<"$reported"; then
        rows+=$'\n'"pending"$'\t'"$name"$'\t'
      fi
    done <<<"$required"
    buckets="$(cut -f1 <<<"$rows")"
    if grep -qxE 'fail|cancel' <<<"$buckets"; then
      printf '%s\n' "$rows"
      exit 1
    fi
    if ! grep -qvx pass <<<"$buckets"; then
      printf '%s\n' "$rows"
      exit 0
    fi
  fi
  if [ "$waited" -ge "$timeout" ]; then
    printf '%s\n' "$rows"
    echo "checks still pending after ${waited}s"
    exit 3
  fi
  sleep "$interval"
  waited=$((waited + interval))
done
