# Run chief and ship in BetterCoding

[BetterCoding](https://github.com/miguelrisero/bettercoding) runs coding agent sessions in isolated workspaces.
Each workspace has its own directory, Git worktrees, branches, agent sessions, and terminal.

## Install

Refer to the [BetterCoding README](https://github.com/miguelrisero/bettercoding#readme) for prerequisites.
To run it from source:

```bash
git clone https://github.com/miguelrisero/bettercoding
cd bettercoding
pnpm i
pnpm run dev
```

## Workspace layout

BetterCoding creates these items in each workspace directory:

- One Git worktree for each repository that you attach.
- A `.scratch/` directory, outside every repository checkout.
- A `CLAUDE.md` and an `AGENTS.md` with file hygiene rules and an import of the configuration of each repository.

The hygiene rules tell agents to keep every file inside the workspace and to put scratch work in `.scratch/`.

Set `BC_WORKTREE_BASE` to select the parent directory of the workspaces.
On Linux, the default is `/var/tmp/bettercoding`.

## Rules for chief and ship

1. Create one workspace for each task.
2. Start the `chief` or `ship` session from that workspace.
3. Give each chief lane its own worktree and branch inside the workspace.
4. Keep the chief board, done ledger, and run notes in `.scratch/`.
5. Keep extra worktrees inside the workspace directory.
6. Remove a lane worktree only after its pull request merges. The `chief` teardown script checks that the work is on the remote.

The chief uses the scratch directory of the workspace when one exists.
`.scratch/` is outside every repository checkout, so the board and ledger stay out of every commit.

When BetterCoding deletes a workspace, it deletes the directory with its worktrees and `.scratch/`.
Before you delete a workspace, confirm that every pull request is merged or closed.

## Search inside a workspace

A workspace root holds several repositories and has no Git repository of its own.
A session that starts in the workspace root gets an fff index of the full workspace directory.
A session that starts in a repository worktree gets an index of that worktree.
Refer to [setup-fff.md](setup-fff.md).

## Model routing

Set up Better Shunt once for each machine.
Every workspace session uses the same `~/.claude/settings.json`.
Refer to [setup-shunt.md](setup-shunt.md).
