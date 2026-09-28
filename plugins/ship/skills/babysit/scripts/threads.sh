#!/usr/bin/env bash
# List unresolved review threads on a PR as TSV: thread-id, author, path:line, first line of the first comment.
# Usage: threads.sh <PR number> [author-login]
set -euo pipefail

pr="${1:?usage: threads.sh <PR number> [author-login]}"
author="${2:-}"
repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
query='query($owner:String!,$name:String!,$pr:Int!,$after:String){repository(owner:$owner,name:$name){pullRequest(number:$pr){reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor}nodes{id isResolved path line comments(first:1){nodes{author{login}body}}}}}}}'

gh api graphql --paginate -F owner="${repo%/*}" -F name="${repo#*/}" -F pr="$pr" -f query="$query" \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.isResolved | not)
        | [.id, (.comments.nodes[0].author.login // "ghost"), "\(.path):\(.line // 0)",
           ((.comments.nodes[0].body // "") | split("\n")[0])] | @tsv' \
  | { if [ -n "$author" ]; then awk -F'\t' -v a="$author" '$2 == a || $2 == a"[bot]"'; else cat; fi; }
