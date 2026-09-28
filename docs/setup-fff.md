# Set up fff

[fff](https://github.com/dmtrKovalenko/fff) is a fast file and content search engine.
Its MCP server, `fff-mcp`, gives agents indexed search tools.
The `chief` and `ship` agents search many files, so fff saves time and tokens on large repositories.

## Install

Use one of these methods.

### Install script (Linux and macOS)

```bash
curl -L https://dmtrkovalenko.dev/install-fff-mcp.sh | bash
```

The script puts the binary in `~/.local/bin/fff-mcp`.
Set `FFF_MCP_INSTALL_DIR` to select a different directory.
The script prints the registration command for each agent CLI that it finds.

### Homebrew

```bash
brew install dmtrKovalenko/fff/fff-mcp
```

The binary is `$(brew --prefix)/bin/fff-mcp`.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/dmtrKovalenko/fff/main/install-mcp.ps1 | iex
```

## Register with Claude Code

1. Register the server for your user. Use the path of your install method.

   Install script:

   ```bash
   claude mcp add --scope user fff -- "$HOME/.local/bin/fff-mcp"
   ```

   Homebrew:

   ```bash
   claude mcp add --scope user fff -- "$(brew --prefix)/bin/fff-mcp"
   ```

2. Check the server:

   ```bash
   fff-mcp --healthcheck
   claude mcp list
   ```

   `claude mcp list` must show `fff` as connected.

3. Add this line to your user or project `CLAUDE.md`:

   ```text
   For any file search or grep in the current git-indexed directory, use fff tools.
   ```

4. Restart Claude Code.

> Verify: these commands come from the fff README, install script, and source. Test them on your machine.

For Codex, the install script prints this command:

```bash
codex mcp add fff -- "$HOME/.local/bin/fff-mcp"
```

## How agents use fff

The server gives three tools:

| Tool in Claude Code | Use |
|---|---|
| `mcp__fff__find_files` | Fuzzy search on file names and paths. |
| `mcp__fff__grep` | Search file contents for a bare identifier. |
| `mcp__fff__multi_grep` | Search file contents for any of several literal patterns. |

Give agents these rules:

- Keep `find_files` queries to one or two terms. Each extra word narrows the result.
- Use `grep` for identifiers, for example `ActorAuth`. It is a literal search.
- Use `multi_grep` for several literal strings. Do not escape special characters.
- Put a constraint before the query to filter files, for example `*.rs query` or `src/ query`.

### What fff indexes

Claude Code starts `fff-mcp` in the session directory.
The server finds the Git root of that directory and indexes it.
Outside a Git repository, it indexes the session directory.

- fff refuses to index your home directory. Set `FFF_ENABLE_HOME_SCAN=1` to permit it.
- fff refuses to index the filesystem root. Set `FFF_ENABLE_ROOT_SCAN=1` to permit it.
- fff stops after one hour without a request. Set `--idle-timeout-secs` to change this.

A chief lane can run in a different worktree from the session directory.
The fff index does not include that worktree.
The lane agent then uses the fallback below.

## Fallback to `rg`

Agents use ripgrep in these cases:

- `fff-mcp` is not installed or does not connect.
- The target files are outside the indexed directory, for example another lane worktree.
- The search needs a regular expression.

The Claude Code `Grep` and `Glob` tools cover most fallback searches.
In a shell, use `rg` with an explicit path:

```bash
rg -n 'pattern' /absolute/path/to/worktree
rg --files /absolute/path/to/worktree | rg 'name'
```

## Update

Run the install script again, or use Homebrew:

```bash
brew upgrade fff-mcp
```

Restart Claude Code after the update.
