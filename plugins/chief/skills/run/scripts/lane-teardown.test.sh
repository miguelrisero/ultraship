#!/usr/bin/env bash
# Self-check for lane-teardown.sh. No network, no gh: exercises the on-remote path,
# the dirty / live / clone / unpushed refusals, and --abandoned. Run: bash lane-teardown.test.sh
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; T="$here/lane-teardown.sh"
tmp="$(mktemp -d)"; trap 'kill "${pid:-}" 2>/dev/null; rm -rf "$tmp"' EXIT
export GIT_CONFIG_GLOBAL="$tmp/gitconfig" GIT_CONFIG_NOSYSTEM=1
git config --file "$GIT_CONFIG_GLOBAL" user.email t@example.com; git config --file "$GIT_CONFIG_GLOBAL" user.name T
git config --file "$GIT_CONFIG_GLOBAL" init.defaultBranch main
git init -q --bare "$tmp/remote.git"; git init -q "$tmp/repo"
echo a > "$tmp/repo/f"; git -C "$tmp/repo" add f; git -C "$tmp/repo" commit -qm init
git -C "$tmp/repo" remote add origin "$tmp/remote.git"; git -C "$tmp/repo" push -q origin main
sha="$(git -C "$tmp/repo" rev-parse HEAD)"
mk() { git -C "$tmp/repo" worktree add -q --detach "$tmp/$1" "$sha"; }
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  PASS $1"; pass=$((pass+1)); else echo "  FAIL $1 (got $2 wanted $3)"; fail=$((fail+1)); fi; }
rc() { "$T" "$@" >/dev/null 2>&1; echo $?; }

mk pushed;                                   check "pushed + clean -> removed"      "$(rc "$tmp/pushed")" 0
[ -d "$tmp/pushed" ] && fail=$((fail+1)) || pass=$((pass+1))
mk dirty; echo x >> "$tmp/dirty/f";          check "dirty -> kept"                  "$(rc "$tmp/dirty")" 2
mk untracked; echo x > "$tmp/untracked/new"; check "untracked -> kept"              "$(rc "$tmp/untracked")" 2
mk unpushed; ( cd "$tmp/unpushed" && echo b > g && git add g && git commit -qm local )
                                             check "unpushed -> kept"               "$(rc "$tmp/unpushed")" 2
                                             check "unpushed + --abandoned -> removed" "$(rc "$tmp/unpushed" --abandoned)" 0
mk unpushed-dirty; ( cd "$tmp/unpushed-dirty" && echo b > g && git add g && git commit -qm local && echo c >> g )
                                             check "--abandoned never waives dirty" "$(rc "$tmp/unpushed-dirty" --abandoned)" 2
mk live; ( cd "$tmp/live" && exec sleep 60 ) & pid=$!; sleep 0.3
                                             check "process inside -> kept"         "$(rc "$tmp/live")" 2
git clone -q "$tmp/remote.git" "$tmp/clone";  check "clone -> kept"                  "$(rc "$tmp/clone")" 2
                                             check "main worktree -> kept"          "$(rc "$tmp/repo")" 2
                                             check "relative path -> usage error"   "$(rc relative/path)" 1
echo "passed=$pass failed=$fail"; [ "$fail" -eq 0 ]
