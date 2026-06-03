# AGENTS.md — using audio-transcriber from a coding agent

This repo ships a **headless transcription pipeline** you can drive two ways:

1. **As a CLI** — run shell commands (`python -m cli ...`). Works in any agent
   that has a terminal/shell tool (Hermes, Codex, Claude Code, Antigravity).
2. **As an MCP server** — typed tools over stdio (`python -m cli.mcp_server`).
   Registration snippets for all four agents are below.

Pipeline: **transcribe → extract tasks → generate protocol → send to a task
backend** (Linear / Glide / Trello). Cloud STT (AssemblyAI / Deepgram / Gladia /
Speechmatics); KZ+RU+EN code-switching; OpenRouter for tasks + protocol.

For repo *development* conventions (invariants, test/lint contract, module map)
see **`CLAUDE.md`** — this file is only about *consuming the tool*.

---

## 1. CLI (shell)

Invoke `python -m cli <command>` from the repo root. Structured output with
`--json`; errors go to stderr with non-zero exit codes (0 ok, 2 usage, 3 config,
4 transcribe, 5 LLM, 6 backend, 130 cancelled).

| Command | Purpose |
|---|---|
| `transcribe <audio> [--provider --language ru\|kk\|en\|mixed\|auto --diarize --hotwords --denoise --json --save]` | Audio → transcript |
| `extract-tasks (--transcript F \| --stdin) [--backend --container-id --model --json]` | Transcript → tasks |
| `protocol (--transcript F \| --stdin) [--model --speakers --meeting-date --json]` | Transcript → 5-block MoM |
| `list-containers --backend linear\|glide\|trello [--json]` | Discover a `--container-id` |
| `send --backend X --container-id Y (--tasks F \| --stdin) [--retry-failed --json]` | Tasks → backend |
| `pipeline <audio> [--backend --container-id --send ...]` | All of the above, one JSON object |

Examples:

```bash
# one-shot: audio → transcript + tasks + protocol (+ optional send)
python -m cli pipeline meeting.m4a --provider AssemblyAI --language mixed \
       --send --backend trello --container-id <listId>

# piping between steps
python -m cli transcribe meeting.m4a --json
echo "<transcript text>" | python -m cli extract-tasks --stdin --backend trello --json
```

## 2. MCP server (typed tools)

```bash
pip install -r requirements-mcp.txt        # one-time: installs `mcp`
python -m cli.mcp_server                    # speaks JSON-RPC over stdio
```

Tools exposed: `transcribe_audio`, `extract_tasks`, `generate_protocol`,
`list_containers`, `send_tasks`. Tool arguments are the *what* (audio path,
language, backend); **secrets are never tool arguments** — the server reads them
from env / `config.json` (see §3).

### Registration per agent

Run from the **repo root** (`cwd`) so the `cli` package + pipeline modules import;
use the Python interpreter that has `requirements-mcp.txt` installed.

**Claude Code** — `.mcp.json` (repo root) or `claude mcp add`:

```json
{
  "mcpServers": {
    "audio-transcriber": {
      "command": "python",
      "args": ["-m", "cli.mcp_server"],
      "cwd": "/path/to/audio-transcriber",
      "env": { "AUDIO_TRANSCRIBER_API_KEY": "…", "AUDIO_TRANSCRIBER_OPENROUTER_API_KEY": "…" }
    }
  }
}
```

**OpenAI Codex CLI** — `~/.codex/config.toml`:

```toml
[mcp_servers.audio-transcriber]
command = "python"
args = ["-m", "cli.mcp_server"]
cwd = "/path/to/audio-transcriber"
env = { AUDIO_TRANSCRIBER_API_KEY = "…", AUDIO_TRANSCRIBER_OPENROUTER_API_KEY = "…" }
```

**Hermes Agent** — `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  audio-transcriber:
    command: python
    args: ["-m", "cli.mcp_server"]
    cwd: /path/to/audio-transcriber
    env:
      AUDIO_TRANSCRIBER_API_KEY: "…"
      AUDIO_TRANSCRIBER_OPENROUTER_API_KEY: "…"
```

**Google Antigravity** — `mcp_config.json`:

```json
{
  "mcpServers": {
    "audio-transcriber": {
      "command": "python",
      "args": ["-m", "cli.mcp_server"],
      "cwd": "/path/to/audio-transcriber",
      "env": { "AUDIO_TRANSCRIBER_API_KEY": "…", "AUDIO_TRANSCRIBER_OPENROUTER_API_KEY": "…" }
    }
  }
}
```

### Hermes — native skill (it does not read AGENTS.md)

Hermes discovers capabilities via **skills**, not AGENTS.md. A ready skill lives at
`integrations/hermes/skills/audio-transcriber/`. Install it — it auto-registers as
the `/audio-transcriber` slash command and shows in the Hermes Desktop **Skills**
pane (same `~/.hermes` config across CLI / TUI / Desktop / Gateway):

```bash
# macOS / Linux
cp -r integrations/hermes/skills/audio-transcriber ~/.hermes/skills/productivity/
# Windows (PowerShell)
Copy-Item -Recurse integrations\hermes\skills\audio-transcriber "$env:USERPROFILE\.hermes\skills\productivity\"
```

The skill is MCP-first (uses the tools above) with a `python -m cli` fallback, and
declares its required env vars so Hermes prompts for them on first use.

## 3. Secrets & config

Resolution precedence (both CLI and MCP): **flag (CLI only) > env > `config.json`**.
The agent host often has no `config.json`, so pass secrets via env:

| Env var | Used for |
|---|---|
| `AUDIO_TRANSCRIBER_API_KEY` | STT provider key (for the active `--provider`) |
| `AUDIO_TRANSCRIBER_PROVIDER` | Default STT provider (else `AssemblyAI`) |
| `AUDIO_TRANSCRIBER_OPENROUTER_API_KEY` | OpenRouter (tasks + protocol) |
| `AUDIO_TRANSCRIBER_LINEAR_API_KEY` / `_TRELLO_API_KEY` / `_TRELLO_TOKEN` / `_GLIDE_API_KEY` | Task backends |

The MCP server speaks JSON-RPC on stdout — never print to it. Transcription
progress is discarded; diagnostics go to `logs/faulthandler-mcp.log`.
