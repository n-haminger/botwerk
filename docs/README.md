# botwerk Docs

botwerk is a web-based platform for building multi-agent systems on Linux. The WebUI (FastAPI + SvelteKit) is the primary interface. Each agent maps to a Linux user with POSIX-level isolation.

## Documentation

- [Reverse Proxy Configuration](reverse-proxy.md) — nginx, Caddy, and Traefik examples

### Module docs

- [api](modules/api.md) — WebSocket and HTTP endpoints
- [orchestrator](modules/orchestrator.md) — routing core, flows, selectors
- [session](modules/session.md) — session isolation model
- [tasks](modules/tasks.md) — delegated background task system
- [background](modules/background.md) — background session observer
- [cron](modules/cron.md) — cron job execution
- [webhook](modules/webhook.md) — webhook HTTP server
- [heartbeat](modules/heartbeat.md) — proactive heartbeat checks
- [security](modules/security.md) — auth and permission model
- [text](modules/text.md) — text processing utilities
