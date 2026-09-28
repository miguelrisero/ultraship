#!/usr/bin/env bash
set -uo pipefail

# Chief lane teardown — remove ONE lane worktree once its work is safely on GitHub.
#
# Usage: lane-teardown.sh <absolute lane worktree> [--abandoned]
#
# Exit 0  REMOVED <path>            the worktree is gone and the parent repo pruned
# Exit 2  KEPT <path> — <reason>    nothing changed; the reason names the failed guard
# Exit 1  usage error
#
# Why this is a script and not a sentence: the skill has said "tear down when the lane
# leaves the board" since 2026-07 and lanes still left 60G of merged checkouts behind on one
# box (2026-09-10). A prose step gets skipped; a command with an exit code gets run.
#
# Guards, all required (each fails toward KEPT):
#   linked   `.git` is a file. A `.git` directory is a clone; its history lives nowhere else.
#   idle     no process has its cwd or executable inside the worktree.
#   clean    `git status --porcelain` is empty; untracked files count.
#   landed   every commit on HEAD is on a remote branch, OR the branch's PR is MERGED and
#            HEAD is that PR's final head or an ancestor of it (squash merges delete the
#            branch, so the first test fails for most finished lanes). `--abandoned` waives
#            only this guard, for a lane the board explicitly closed without a PR; it never
#            waives clean or idle.
#   remove   `git worktree remove` WITHOUT --force through the parent repo: git re-checks
#            dirty and locked state at the instant of deletion.

wt="${1:-}"; mode="${2:-}"
[ -n "$wt" ] || { echo "usage: $0 <absolute lane worktree> [--abandoned]" >&2; exit 1; }
case "$mode" in ""|--abandoned) ;; *) echo "usage: $0 <absolute lane worktree> [--abandoned]" >&2; exit 1 ;; esac
case "$wt" in /*) ;; *) echo "usage: worktree path must be absolute" >&2; exit 1 ;; esac

keep() { echo "KEPT $wt — $1"; exit 2; }

[ -d "$wt" ] || keep "not a directory"
[ -d "$wt/.git" ] && keep "a clone, not a linked worktree; never removed here"
[ -f "$wt/.git" ] || keep "not a git worktree"

# idle: match the path itself or anything under it, not a sibling with the same prefix.
real="$(readlink -f "$wt")"
# Command substitution, not `if pipeline`: under pipefail an early-exiting grep
# makes the whole pipeline "fail" and the guard would silently pass.
if [ -n "$(for p in /proc/[0-9]*; do readlink "$p/cwd" "$p/exe" 2>/dev/null; done \
           | grep -m1 "^$real\(/\|$\)")" ]; then
  keep "a process still lives in it"
fi

common="$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || keep "git cannot read it"
parent="${common%/.git}"
[ "$parent" != "$common" ] && [ -d "$parent" ] || keep "parent repo not resolvable"
[ "$(readlink -f "$parent")" != "$real" ] || keep "this is the main worktree"

[ -z "$(git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null)" ] || keep "dirty tree (commit, push, or stash it first)"

head="$(git -C "$wt" rev-parse HEAD 2>/dev/null)" || keep "no HEAD"
evidence=""
if [ "$mode" = "--abandoned" ]; then
  evidence="abandoned by the board"
else
  git -C "$wt" fetch --prune --quiet origin 2>/dev/null || true
  if [ -n "$(git -C "$wt" branch -r --contains "$head" 2>/dev/null)" ]; then
    evidence="every commit is on a remote branch"
  else
    br="$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    slug="$(git -C "$wt" remote get-url origin 2>/dev/null | sed -E 's#^(https://github.com/|git@github.com:)##; s#\.git$##')"
    if [ -n "$br" ] && [ -n "$slug" ] && command -v gh >/dev/null 2>&1; then
      out="$(timeout 30 gh pr list -R "$slug" --head "$br" --state merged --limit 1 \
               --json number,headRefOid --jq '.[0] | select(.headRefOid != null) | "\(.number)\t\(.headRefOid)"' 2>/dev/null)"
      num="${out%%$'\t'*}"; oid="${out#*$'\t'}"
      if [ -n "$out" ] && { [ "$oid" = "$head" ] || git -C "$wt" merge-base --is-ancestor "$head" "$oid" 2>/dev/null; }; then
        evidence="PR #$num merged (head $oid)"
      fi
    fi
    [ -n "$evidence" ] || keep "commits on HEAD are on no remote branch and no merged PR contains them (pass --abandoned only for a lane the board closed without a PR)"
  fi
fi

git -C "$parent" worktree remove "$wt" >/dev/null 2>&1 || keep "git refused worktree remove"
git -C "$parent" worktree prune >/dev/null 2>&1 || true
echo "REMOVED $wt — $evidence"
