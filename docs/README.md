# botwerk Docs

botwerk is a web-based platform for building multi-agent systems on Linux. The WebUI (FastAPI + SvelteKit) is the primary interface. Each agent maps to a Linux user with POSIX-level isolation.

## Documentation

- [Reverse Proxy Configuration](reverse-proxy.md) — nginx, Caddy, and Traefik examples

### Module docs

- [api](modules/api.md) — WebSocket and HTTP endpoints
- [cli](modules/cli.md) — provider wrappers, stream parsing, process control
- [cli_commands](modules/cli_commands.md) — CLI command implementations
- [config_reload](modules/config_reload.md) — runtime config reload
- [orchestrator](modules/orchestrator.md) — routing core, flows, selectors
- [session](modules/session.md) — session isolation model
- [tasks](modules/tasks.md) — delegated background task system
- [background](modules/background.md) — background session observer
- [cron](modules/cron.md) — cron job execution
- [webhook](modules/webhook.md) — webhook HTTP server
- [heartbeat](modules/heartbeat.md) — proactive heartbeat checks
- [workspace](modules/workspace.md) — home directory seeding and rules sync
- [skill_system](modules/skill_system.md) — cross-tool skill sync
- [supervisor](modules/supervisor.md) — agent supervisor lifecycle
- [security](modules/security.md) — auth and permission model
- [logging](modules/logging.md) — logging configuration
- [files](modules/files.md) — file handling and MIME detection
- [text](modules/text.md) — text processing utilities
