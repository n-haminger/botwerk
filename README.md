# botwerk

A web-based platform for building multi-agent systems on Linux. Each agent maps 1:1 to a Linux user, using POSIX permissions for isolation. Supports Claude Code, Codex CLI, and Gemini CLI as AI backends.

<p align="center">
  <a href="https://github.com/n-haminger/botwerk/blob/main/LICENSE"><img src="https://img.shields.io/github/license/n-haminger/botwerk" alt="License" /></a>
  <a href="https://github.com/n-haminger/botwerk/releases"><img src="https://img.shields.io/github/v/release/n-haminger/botwerk?include_prereleases&label=release" alt="Release" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
</p>

## Key Features

- **Web UI** — SvelteKit frontend with agent chat, file explorer, web terminal, system status, admin tools
- **Linux user isolation** — each agent runs as a dedicated Linux user (`botwerk-<name>`), POSIX permissions enforce boundaries
- **Multi-agent hierarchy** — main agent, optional management agents, worker agents
- **Real-time streaming** — live WebSocket updates as CLIs produce output
- **Permission templates** — developer, ops, restricted — preconfigured access profiles
- **Cron jobs and webhooks** — in-process scheduler with timezone support, per-job overrides, quiet hours
- **Persistent memory** — plain Markdown files that survive across sessions
- **Background tasks** — delegate long-running work to autonomous background agents
- **Auth** — JWT with bcrypt, admin/user roles
- **Provider switching** — switch between Claude, Codex, and Gemini per agent or per session

## Requirements

- Ubuntu/Debian Linux (tested on 22.04+)
- Python 3.11+
- Node.js 18+ (for building the frontend)
- At least one authenticated provider CLI: `claude`, `codex`, or `gemini`
- A reverse proxy (nginx, Caddy, or Traefik) for TLS termination

## Quick Start

```bash
# Install
pip install git+https://github.com/n-haminger/botwerk.git

# Run initial setup (creates DB, admin user, configures WebUI)
botwerk setup

# Build the frontend
botwerk build-frontend

# Start the server
botwerk run
```

Then configure your reverse proxy to forward to `localhost:8080` (see [docs/reverse-proxy.md](docs/reverse-proxy.md)) and open your browser.

## Architecture Overview

```
                  ┌─────────────────────────────────┐
                  │         Reverse Proxy            │
                  │    (nginx / Caddy / Traefik)     │
                  └──────────────┬──────────────────┘
                                 │
                  ┌──────────────▼──────────────────┐
                  │     FastAPI + SvelteKit          │
                  │     (WebUI on :8080)             │
                  └──────────────┬──────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
   ┌──────────▼───┐  ┌──────────▼───┐  ┌───────────▼──┐
   │  Main Agent   │  │ Agent "ops"  │  │ Agent "dev"  │
   │  (botwerk)    │  │ (botwerk-ops)│  │ (botwerk-dev)│
   │  Linux user   │  │  Linux user  │  │  Linux user  │
   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
          │                  │                  │
          ▼                  ▼                  ▼
     CLI subprocess     CLI subprocess     CLI subprocess
   (claude/codex/gemini)
```

- **FastAPI** serves the REST API, WebSocket connections, and the built SvelteKit frontend
- **SQLite** (via SQLAlchemy) stores users, sessions, and agent metadata
- **Each agent** is a Linux user with its own home directory, workspace, and CLI subprocess
- **Agent Supervisor** manages agent lifecycle, inter-agent communication, and shared task hub

## Usage Examples

### Single developer agent

Default setup — one main agent with full workspace access:

```bash
botwerk setup    # creates admin user + main agent
botwerk run      # chat via browser
```

### Ops agent with restricted permissions

Add a worker agent that can only run specific commands:

```json
// agents.json
[{
  "name": "ops",
  "linux_user": true,
  "provider": "claude",
  "model": "sonnet"
}]
```

The `linux_user: true` flag creates a `botwerk-ops` Linux user with isolated filesystem access.

### Multi-agent setup

Run multiple agents with different providers and permission levels:

```json
[
  {
    "name": "researcher",
    "linux_user": true,
    "provider": "gemini",
    "model": "pro"
  },
  {
    "name": "coder",
    "linux_user": true,
    "provider": "claude",
    "model": "opus"
  }
]
```

Agents can communicate via the inter-agent bus. Delegate tasks between them from the web UI or let the main agent coordinate.

## CLI Commands

```bash
botwerk setup           # Interactive WebUI setup wizard
botwerk build-frontend  # Build SvelteKit frontend
botwerk run             # Start the server

botwerk stop            # Stop bot
botwerk restart         # Restart bot
botwerk status          # Runtime status
botwerk upgrade         # Upgrade and restart

botwerk service install # Install as systemd service
botwerk service logs    # View service logs

botwerk agents list     # List configured agents
botwerk agents add NAME # Add an agent
botwerk agents remove NAME
```

## Configuration

All configuration lives in `~/.botwerk/config/config.json`. Key sections:

```json
{
  "provider": "claude",
  "model": "opus",
  "user_timezone": "Europe/Berlin",
  "webui": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8080,
    "behind_proxy": true,
    "secret_key": "...",
    "frontend_dir": ""
  }
}
```

Agent definitions are in `~/.botwerk/agents.json`. Most config fields are hot-reloadable without restart.

For reverse proxy setup, see [docs/reverse-proxy.md](docs/reverse-proxy.md).

## Development

```bash
git clone https://github.com/n-haminger/botwerk.git
cd botwerk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Quality gates
pytest
ruff format .
ruff check .
mypy botwerk_bot
```

Frontend development:

```bash
cd frontend
npm install
npm run dev    # Dev server with hot reload
npm run build  # Production build
```

## Workspace Layout

```
~/.botwerk/
  config/config.json         # Bot configuration
  agents.json                # Agent registry
  sessions.json              # Chat session state
  cron_jobs.json             # Scheduled tasks
  webhooks.json              # Webhook definitions
  SHAREDMEMORY.md            # Shared knowledge across agents
  logs/agent.log
  workspace/
    memory_system/MAINMEMORY.md
    cron_tasks/ skills/ tools/
    tasks/                   # Per-task folders
    output_to_user/          # Generated deliverables
  agents/<name>/             # Per-agent workspaces (isolated)
```

## License

[MIT](LICENSE)
