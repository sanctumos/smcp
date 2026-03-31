# Broca SMCP plugin

MCP tools for [Sanctum Broca](https://github.com/sanctumos/broca) administration. Each tool runs Broca’s own CLIs (`python -m cli.*`) in a configured working directory — no duplicate business logic.

## Requirements

- A Broca **instance directory** containing `sanctum.db` and (for in-tree layout) the `cli/` package.
- Python interpreter with Broca dependencies (**`BROCA_PYTHON`**, usually the Broca venv).

## Environment

| Variable | Description |
|----------|-------------|
| **`BROCA_ROOT`** | Working directory for CLI runs (agent instance root: `sanctum.db`, `.env`, `settings.json`). Default: current directory. |
| **`BROCA_SRC`** | Directory on `PYTHONPATH` containing the `cli` package (Broca repo root). Default: same as `BROCA_ROOT` (typical full clone per agent). |
| **`BROCA_PYTHON`** | Python executable. Default: `sys.executable` of the SMCP process (often **wrong** — set to Broca’s venv `python`). |
| **`ENABLE_OUTBOUND_TOOL`** | On the **Broca instance** (e.g. in `.env`), must be `true` for real sends (DB audit + delivery). **`dry_run=yes`** can resolve the platform profile without this flag. |

Outbound uses the same Telegram token as the bot plugin; CLI sends via a short-lived aiogram session so it does not start a second poller.

## SMCP tool names

Tools are registered as `broca__<command>`, e.g. `broca__queue_list`, `broca__user_get`.

## Safety

Destructive operations (`queue_flush` / `queue_delete` with `scope=all` or `scope=single` and `item_id`) map to Broca `qtool` — use with care.

`settings_set_debug` takes a string **`state`** (`enabled` / `disabled` and common synonyms), not a bare boolean: SMCP only forwards `true` booleans as CLI flags, so `false` would be omitted.

## See also

Broca planning: [broca-3.1-smcp-cli-plugins-planning.md](https://github.com/sanctumos/broca/blob/broca-3.1/docs/broca-3.1-smcp-cli-plugins-planning.md)
