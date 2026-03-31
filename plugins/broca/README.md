# Broca SMCP plugin

MCP tools for [Sanctum Broca](https://github.com/sanctumos/broca). Each tool runs Broca’s own CLIs (`python -m cli.*`) in a subprocess with a configured working directory and Python — **no duplicate business logic inside SMCP**.

## How configuration works (two layers)

| Layer | What it is | Typical file / mechanism |
|--------|------------|---------------------------|
| **SMCP / Letta process** | Environment variables **present when the Broca plugin spawns subprocesses** | Shell `export`, or an **`env.smcp`** file **`source`d** by your `run-smcp-stdio-for-letta.sh` (or equivalent) before `python smcp_stdio.py` |
| **Broca instance directory** | The agent’s Broca tree: `sanctum.db`, `settings.json`, and usually **`.env`** | Whatever directory you set as **`BROCA_ROOT`** |

The plugin sets subprocess **`cwd`** to **`BROCA_ROOT`** and **`PYTHONPATH`** to **`BROCA_SRC`**. Broca CLIs then open `sanctum.db` and config relative to that directory.

**Not hardcoded:** Paths are **only** what you put in the environment. Changing instances means changing **`BROCA_ROOT`** / **`BROCA_PYTHON`** / **`BROCA_SRC`** (or using a different `env.smcp` per agent). You can use symlinks for the **plugin directory** under `MCP_PLUGINS_DIR` if you want, but instance selection is **always** via these env vars, not via symlink magic.

---

## Environment variables (reference)

### Required for correct operation (set on the SMCP host)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| **`BROCA_ROOT`** | Strongly recommended | SMCP process cwd | **Broca instance root**: directory containing `sanctum.db`, `settings.json`, and usually `.env`. Every `python -m cli.*` runs with this as **`cwd`**. |
| **`BROCA_PYTHON`** | Strongly recommended | `sys.executable` (SMCP’s Python) | Interpreter that has **Broca’s dependencies** (`aiogram`, `aiosqlite`, etc.). On production hosts this should be the **Broca venv** `python`, not the bare SMCP interpreter. |
| **`BROCA_SRC`** | Optional | Same as **`BROCA_ROOT`** | Directory added to **`PYTHONPATH`** so `import cli` works. Use when the **code** lives elsewhere (e.g. shared checkout) while **`BROCA_ROOT`** is only instance state. For a normal “full clone per agent”, **`BROCA_SRC=$BROCA_ROOT`**. |

### SMCP-wide (not Broca-specific, but you need them for plugins to load)

| Variable | Description |
|----------|-------------|
| **`MCP_PLUGINS_DIR`** | Directory containing plugin folders (each with `cli.py`). Must include the **`broca`** plugin folder (copy, mount, or symlink). |

### Broca instance `.env` (under `BROCA_ROOT`)

These are read by Broca code when subprocesses run with `cwd=BROCA_ROOT`. Some CLIs call `load_dotenv()`; others rely on **`os.environ`**. **Safest:** export anything critical for **all** tools in the same shell / `env.smcp` as well, especially if a CLI does not load `.env` itself.

| Variable | Used for |
|----------|-----------|
| **`ENABLE_OUTBOUND_TOOL`** | **`true` / `1` / `yes`**: allow **`send_outbound`** / `cli.outbound` to **write audit row + deliver**. If unset/false, real sends return `outbound_disabled`. **`dry_run=yes`** (SMCP: `dry_run` = `yes`) still resolves the platform profile **without** this flag. |
| **`TELEGRAM_BOT_TOKEN`** | Telegram delivery for **`send_outbound`** (short-lived bot session; does not start a second poller). Same token as the Telegram bot plugin. |
| Other Broca `.env` keys | Whatever your instance already needs (Letta, etc.); unchanged by this plugin. |

---

## Example: `env.smcp` fragment

Adjust paths to your host. This pattern matches Rico-style SMCP on Sanctum ([`rico-smcp-223`](https://github.com/sanctumos/sanctum/blob/main/docs/rico-smcp-223.md) in the Sanctum workspace — filename may differ on your clone).

```bash
# After sourcing shared Letta/env (e.g. ~/sanctum/env.letta)
export MCP_PLUGINS_DIR=/home/USER/sanctum/agents/rico/smcp/plugins

# Broca instance this agent should administer
export BROCA_ROOT=/home/USER/sanctum/agents/rico/broca
export BROCA_SRC=/home/USER/sanctum/agents/rico/broca
export BROCA_PYTHON=/home/USER/sanctum/venv/bin/python

# Optional: outbound real sends (also can live only in $BROCA_ROOT/.env)
# export ENABLE_OUTBOUND_TOOL=true
```

Use **`BROCA_SRC`** different from **`BROCA_ROOT`** only if the **code** is a shared checkout and **`BROCA_ROOT`** is a thinner instance dir (advanced).

---

## Verifying from a shell

On the **SMCP host**, with the same exports you use for Letta:

```bash
export BROCA_ROOT=/path/to/broca/instance
export BROCA_PYTHON=/path/to/venv/bin/python
export BROCA_SRC=/path/to/broca/instance   # or checkout root
cd /path/to/smcp
python3 plugins/broca/cli.py --describe | head
```

Smoke the instance:

```bash
cd "$BROCA_ROOT"
$PYTHON -m cli.settings get --json
```

(Or rely on the plugin’s `broca__settings_get` once Letta attaches tools.)

---

## SMCP tool names

Tools register as **`broca__<command>`**, e.g. `broca__queue_list`, `broca__send_outbound`. Full list: run **`python plugins/broca/cli.py --describe`** (JSON).

### SMCP boolean caveat

SMCP only adds CLI flags for boolean tool args when they are **true**. Tools that need a clear **false** use a **string** instead (e.g. `settings_set_debug` uses **`state`**: `enabled` / `disabled`; **`send_outbound`** uses **`dry_run`**: `yes` / `no`).

---

## Safety

- **`queue_flush` / `queue_delete`** map to Broca **`qtool`** — destructive when `scope=all` or when deleting specific **`item_id`**.
- **`send_outbound`** delivers live messages when **`ENABLE_OUTBOUND_TOOL`** is on and **`dry_run=no`**.

---

## See also

- Broca planning: [broca-3.1-smcp-cli-plugins-planning.md](https://github.com/sanctumos/broca/blob/broca-3.1/docs/broca-3.1-smcp-cli-plugins-planning.md)  
- Outbound semantics: [broca-3.1-outbound-mcp-planning.md](https://github.com/sanctumos/broca/blob/broca-3.1/docs/broca-3.1-outbound-mcp-planning.md)
