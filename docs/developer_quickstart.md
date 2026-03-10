# Developer Quickstart

Fast onboarding path for contributors and junior devs.

## 1) Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional for full runtime validation:

- install/auth at least one provider CLI (`claude`, `codex`, `gemini`)
- set up a messaging transport:
  - **Telegram**: bot token from @BotFather + user ID (`allowed_user_ids`)
  - **Matrix**: account on any homeserver (homeserver URL, user ID, password, `allowed_users`)
- for Telegram group support, also set `allowed_group_ids`

## 2) Run the bot

```bash
botwerk
```

First run starts onboarding and writes config to `~/.botwerk/config/config.json`.

Primary runtime files/directories:

- `~/.botwerk/sessions.json`
- `~/.botwerk/named_sessions.json`
- `~/.botwerk/tasks.json`
- `~/.botwerk/chat_activity.json`
- `~/.botwerk/cron_jobs.json`
- `~/.botwerk/webhooks.json`
- `~/.botwerk/startup_state.json`
- `~/.botwerk/inflight_turns.json`
- `~/.botwerk/SHAREDMEMORY.md`
- `~/.botwerk/agents.json`
- `~/.botwerk/agents/`
- `~/.botwerk/workspace/`
- `~/.botwerk/logs/agent.log`

## 3) Quality gates

```bash
pytest
ruff format .
ruff check .
mypy botwerk_bot
```

Expected: zero warnings, zero errors.

## 4) Core mental model

```text
Telegram / Matrix / API input
  -> ingress layer (TelegramBot / MatrixBot / ApiServer)
  -> orchestrator flow
  -> provider CLI subprocess
  -> response delivery (transport-specific)

background/async results
  -> Envelope adapters
  -> MessageBus
  -> optional session injection
  -> transport delivery (Telegram or Matrix)
```

## 5) Read order in code

Entry + command layer:

- `botwerk_bot/__main__.py`
- `botwerk_bot/cli_commands/`

Runtime hot path:

- `botwerk_bot/multiagent/supervisor.py`
- `botwerk_bot/bot/app.py`
- `botwerk_bot/bot/startup.py`
- `botwerk_bot/orchestrator/core.py`
- `botwerk_bot/orchestrator/lifecycle.py`
- `botwerk_bot/orchestrator/flows.py`

Delivery/task/session core:

- `botwerk_bot/bus/`
- `botwerk_bot/session/manager.py`
- `botwerk_bot/tasks/hub.py`
- `botwerk_bot/tasks/registry.py`

Provider/API/workspace core:

- `botwerk_bot/cli/service.py` + provider wrappers
- `botwerk_bot/api/server.py`
- `botwerk_bot/workspace/init.py`
- `botwerk_bot/workspace/rules_selector.py`
- `botwerk_bot/workspace/skill_sync.py`

## 6) Common debug paths

If command behavior is wrong:

1. `botwerk_bot/__main__.py`
2. `botwerk_bot/cli_commands/*`

If Telegram routing is wrong:

1. `botwerk_bot/bot/middleware.py`
2. `botwerk_bot/bot/app.py`
3. `botwerk_bot/orchestrator/commands.py`
4. `botwerk_bot/orchestrator/flows.py`

If Matrix routing is wrong:

1. `botwerk_bot/matrix/bot.py`
2. `botwerk_bot/matrix/transport.py`
3. `botwerk_bot/orchestrator/flows.py`

If background results look wrong:

1. `botwerk_bot/bus/adapters.py`
2. `botwerk_bot/bus/bus.py`
3. `botwerk_bot/bus/telegram_transport.py` (or `botwerk_bot/matrix/transport.py`)

If tasks are wrong:

1. `botwerk_bot/tasks/hub.py`
2. `botwerk_bot/tasks/registry.py`
3. `botwerk_bot/multiagent/internal_api.py`
4. `botwerk_bot/_home_defaults/workspace/tools/task_tools/*.py`

If API is wrong:

1. `botwerk_bot/api/server.py`
2. `botwerk_bot/orchestrator/lifecycle.py` (API startup wiring)
3. `botwerk_bot/files/*` (allowed roots, MIME, prompt building)

## 7) Behavior details to remember

- `/stop` and `/stop_all` are pre-routing abort paths in middleware/bot.
- `/new` resets only active provider bucket for the active `SessionKey`.
- session identity is topic-aware: `SessionKey(chat_id, topic_id)`.
- `/model` inside a topic updates only that topic session (not global config).
- task tools now support permanent single-task removal via `delete_task.py` (`/tasks/delete`).
- task routing is topic-aware via `thread_id` and `BOTWERK_TOPIC_ID`.
- API auth accepts optional `channel_id` for per-channel session isolation.
- startup recovery uses `inflight_turns.json` + recovered named sessions.
- auth allowlists (`allowed_user_ids`, `allowed_group_ids`) are hot-reloadable.

Continue with `docs/system_overview.md` and `docs/architecture.md` for complete runtime detail.
