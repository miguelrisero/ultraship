# Set up Better Shunt

The `chief` and `ship` plugins assign each role to a model.
Claude models run native in Claude Code.
The other models reach Claude Code through [Better Shunt](https://github.com/miguelrisero/better-shunt), a local LLM gateway.

| Model ID | Provider | Path |
|---|---|---|
| `claude-opus-5-5`, `claude-fable-5-1`, `claude-sonnet-5-5` | Anthropic | shunt passthrough |
| `gpt-6.1-sol`, `gpt-6-luna`, `gpt-6-astra` | ChatGPT login (Codex) | shunt `responses` adapter |
| `kimi-k3` | Kimi coding API | shunt `anthropic` adapter |

shunt selects the route from the `model` field of each request.
It sends an unmapped `claude-*` ID to Anthropic with the credential of the caller.

An automated installer can do all of these steps.
DevPod's `ai-routing enable` is one example.
This guide gives the manual procedure.

## Prerequisites

- Claude Code. The `resolvedModel` check in [Verification](#verification) needs version 2.1.174 or later.
- The Codex CLI (`codex`), for the ChatGPT login.
- `curl` and `jq`, for the tests.
- A ChatGPT plan that includes the GPT models you route.
- A Kimi coding plan and API key, for `kimi-k3`.
- For a source build: `git` and a Rust toolchain.

Skip a provider that you do not use.
Remove its routes from the configuration too.

## Install shunt

### Option A: prebuilt release (Linux x86_64)

1. Download the binary and install it:

   ```bash
   mkdir -p ~/.local/bin
   curl -fL -o ~/.local/bin/shunt \
     https://github.com/miguelrisero/better-shunt/releases/download/v0.49.1-better.1/better-shunt-linux-x86_64
   ```

2. Check the SHA-256 digest:

   ```bash
   echo "80252ffa3aaaf9d3c0d31c8b94dd0c573d20735f08749eb2f9179217309b02a6  $HOME/.local/bin/shunt" | sha256sum -c -
   ```

3. Make the binary executable:

   ```bash
   chmod +x ~/.local/bin/shunt
   ```

4. Make sure that `~/.local/bin` is on your `PATH`.

The digest applies to release `v0.49.1-better.1` only.
For a later release, read the digest on the [releases page](https://github.com/miguelrisero/better-shunt/releases).

### Option B: source build

Use this option on macOS, on ARM, or for an unreleased commit.

```bash
git clone https://github.com/miguelrisero/better-shunt
cd better-shunt
cargo build --release --locked
install -m 0755 target/release/shunt ~/.local/bin/shunt
```

> Verify: the release builds are tested on Linux x86_64 only. Test a macOS or ARM build before daily use.

## Providers and secrets

Keep every secret in a file with mode `0600`.
Do not put a secret in `shunt.toml`, in a URL, or in a shell history.

### Codex (ChatGPT login)

1. Sign in with the Codex CLI:

   ```bash
   codex login
   ```

2. Confirm that `~/.codex/auth.json` exists.

shunt reads this login for every route with `auth = "chatgpt_oauth"`.

### Kimi

1. Create an API key for the Kimi coding API.

A 1M context on Kimi needs a plan tier that includes it.
Refer to the [Kimi model page](https://www.kimi.com/code/docs/en/kimi-code/models.html).

### The environment file

1. Create the file with mode `0600`:

   ```bash
   mkdir -p ~/.config/ultraship
   install -m 0600 /dev/null ~/.config/ultraship/env
   ```

2. Put these lines in `~/.config/ultraship/env` with an editor:

   ```bash
   KIMI_CODING_API_KEY=<Kimi API key>
   ```

The file name is a convention of this guide.
shunt reads the keys from the environment of its process.

## Configure shunt

Write `~/.config/shunt/shunt.toml`:

```toml
[server]
bind = "127.0.0.1:3001"
default_provider = "anthropic"

[providers.anthropic]
kind = "anthropic"
base_url = "https://api.anthropic.com"
auth = "passthrough"

[providers.codex]
kind = "responses"
base_url = "https://chatgpt.com/backend-api"
auth = "chatgpt_oauth"

[providers.kimi_subscription]
kind = "anthropic"
base_url = "https://api.kimi.com/coding"
auth = "api_key"
api_key_env = "KIMI_CODING_API_KEY"
api_key_header = "bearer"

[[routes]]
model = "gpt-6-astra"
provider = "codex"
upstream_model = "gpt-6-astra"

[[routes]]
model = "gpt-6.1-sol"
provider = "codex"
upstream_model = "gpt-6.1-sol"

[[routes]]
model = "gpt-6-luna"
provider = "codex"
upstream_model = "gpt-6-luna"

[[routes]]
model = "kimi-k3"
provider = "kimi_subscription"
upstream_model = "k3"
```

> Verify: `gpt-6.1-sol` needs a ChatGPT plan that includes it. Run the test in [Verification](#verification) before you use the Sol agents.

Check the file:

```bash
shunt check --config ~/.config/shunt/shunt.toml
```

shunt reloads the file when it changes.
Config strings also accept `${VAR}` and `${file:/abs/path}` secret references.

### Model IDs and the `[1m]` suffix

The `[1m]` suffix is a client hint.
It tells Claude Code to use a 1M-token context budget for the model.
Claude Code removes the suffix before it sends the request, and shunt removes it too.

Use these IDs in the Claude Code picker:

| Picker ID | Label |
|---|---|
| `claude-fable-5-1[1m]` | Claude Fable 5.1 (1M) |
| `claude-opus-5-5[1m]` | Claude Opus 5.5 (1M) |
| `claude-sonnet-5-5[1m]` | Claude Sonnet 5.5 (1M) |
| `haiku` | Claude Haiku (200k) |
| `gpt-6-astra[1m]` | GPT-6 Astra (1M) |
| `gpt-6.1-sol[1m]` | GPT-6.1 Sol (1M) |
| `gpt-6-luna[1m]` | GPT-6 Luna (1M) |
| `kimi-k3[1m]` | Kimi K3 (1M) |

Obey these rules:

- Put `[1m]` on native Claude IDs. Behind a custom base URL, a native ID without it gets a 200K budget.
- Keep per-model settings keys bare, for example `claude-opus-5-5`.
- Use bare IDs in agent `model:` frontmatter, as the plugins do.
- Offer `[1m]` only where the upstream accepts a large context.

A `[1m]` label sets the client budget only.
The upstream window can be smaller:

- The ChatGPT subscription advertises a 272K default and an 872K maximum.
- Kimi gives 1M on some plan tiers only.

> Verify: `claude-sonnet-5-5[1m]` gets a 1M window on your Anthropic plan.

## Effort

The Claude Code `/effort` command sends `output_config.effort`.
shunt maps it to `reasoning.effort` on the Codex routes.
The value `max` passes through on the `gpt-5.6` and `gpt-6` families.

The Kimi documentation maps `medium` to high and `xhigh` to max.

## Start the gateway

1. Load the secrets into the shell:

   ```bash
   set -a; . ~/.config/ultraship/env; set +a
   export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,$NO_PROXY}"
   ```

2. Start shunt:

   ```bash
   RUST_LOG=shunt=info shunt run --config ~/.config/shunt/shunt.toml
   ```

Run shunt under a supervisor for daily use, for example a systemd user unit or launchd agent.

## Point Claude Code at the gateway

1. Remove `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from your shell profile. The passthrough then sends your Claude login.
2. Merge this block into `~/.claude/settings.json`:

   ```json
   {
     "env": {
       "ANTHROPIC_BASE_URL": "http://127.0.0.1:3001",
       "ENABLE_TOOL_SEARCH": "true",
       "NO_PROXY": "127.0.0.1,localhost",
       "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000"
     },
     "autoCompactWindow": 600000,
     "modelPicker": {
       "replaceBuiltInOptions": true,
       "options": [
         { "model": "claude-fable-5-1[1m]", "label": "Claude Fable 5.1 (1M)" },
         { "model": "claude-opus-5-5[1m]", "label": "Claude Opus 5.5 (1M)" },
         { "model": "claude-sonnet-5-5[1m]", "label": "Claude Sonnet 5.5 (1M)" },
         { "model": "haiku", "label": "Claude Haiku (200k)" },
         { "model": "gpt-6-astra[1m]", "label": "GPT-6 Astra (1M)" },
         { "model": "gpt-6.1-sol[1m]", "label": "GPT-6.1 Sol (1M)" },
         { "model": "gpt-6-luna[1m]", "label": "GPT-6 Luna (1M)" },
         { "model": "kimi-k3[1m]", "label": "Kimi K3 (1M)" }
       ]
     },
     "modelSettings": {
       "gpt-6-astra": { "effortLevel": "high" },
       "gpt-6.1-sol": { "effortLevel": "high" },
       "gpt-6-luna": { "effortLevel": "high" },
       "kimi-k3": { "effortLevel": "high" }
     }
   }
   ```

3. Do not set `CLAUDE_CODE_DISABLE_1M_CONTEXT`. It removes the 1M budget from every model.
4. Restart Claude Code.

These settings have these effects:

- `ANTHROPIC_BASE_URL` sends every request to shunt.
- `ENABLE_TOOL_SEARCH` keeps tool search active behind a custom base URL.
- `CLAUDE_CODE_MAX_CONTEXT_TOKENS` sets the budget for a non-Claude ID without `[1m]`.
- `modelPicker.options` lists the routed models in `/model`. Claude Code discovers only `claude` and `anthropic` IDs by itself.

To resume a session on a 1M native model, use the full ID:

```bash
claude --continue --model 'claude-opus-5-5[1m]'
```

### Per-agent routing

A plugin agent selects its model in the `model:` frontmatter.
Invoke the agent by its `subagent_type`.
Do not give a per-call `model` override.

## Verification

1. List the routes:

   ```bash
   curl -s http://127.0.0.1:3001/routes | jq -r '.data[].model'
   ```

2. Send one request per routed model:

   ```bash
   for m in gpt-6-astra gpt-6.1-sol gpt-6-luna kimi-k3; do printf '%s: ' "$m"; curl -s -D - -o /dev/null -X POST http://127.0.0.1:3001/v1/messages -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' -d "{\"model\":\"$m\",\"max_tokens\":16,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" | grep -iE '^(HTTP|x-gateway-upstream)' | tr -d '\r' | tr '\n' ' '; echo; done
   ```

   Each line must show HTTP status 200 and an `x-gateway-upstream` header.

3. Test one route through Claude Code:

   ```bash
   claude -p --model gpt-6.1-sol 'Reply with the word ok.'
   ```

4. Test a native model:

   ```bash
   claude -p --model 'claude-opus-5-5[1m]' 'Reply with the word ok.'
   ```

5. Show the model that Claude Code resolved:

   ```bash
   claude -p --model 'kimi-k3[1m]' --output-format stream-json --verbose 'Reply with the word ok.' | grep -o '"resolvedModel":"[^"]*"' | head -1
   ```

6. Open Claude Code and run `/model`. Every entry from `modelPicker.options` must appear.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `ChatGPT auth not found; run codex login` | shunt cannot read the ChatGPT login. | Run `codex login`, then retry. |
| HTTP 401 on `kimi-k3` | The Kimi key is missing or wrong. | Load the env file before `shunt run`. |
| HTTP 429 with `rate_limit_kind` | The provider quota is used up. | Read `rate_limit_kind`. Wait for the reset, or select a different model. |
| `config check failed` at start | `shunt.toml` has an error. | Run `shunt check --config ~/.config/shunt/shunt.toml`. |
| Tool search is inactive | Claude Code turns it off behind a custom base URL. | Set `ENABLE_TOOL_SEARCH=true` in `settings.json`. |
| Effort stays at `medium` | The model has no effort setting. | Set `modelSettings.<bare ID>.effortLevel`, or run `/effort`. |
| A native model shows a 200K window | The ID has no `[1m]` suffix. | Select `claude-opus-5-5[1m]` or `claude-fable-5-1[1m]`. |
| A routed model goes to Anthropic | The ID has no route. | Compare the ID with `GET /routes`. |

The `x-gateway-upstream` response header names the upstream that served a request.
The [shunt documentation](https://shunt.sh) has more troubleshooting cases.

## Updating

1. Download the new release binary and its digest from the [releases page](https://github.com/miguelrisero/better-shunt/releases).
2. Check the digest with `sha256sum -c`.
3. Replace `~/.local/bin/shunt` and restart shunt.
4. Run `shunt check --config ~/.config/shunt/shunt.toml`.
5. Run the tests in [Verification](#verification).

For a source build, run `git pull` and repeat the build steps.

Keep the old shunt binary until the tests pass.
