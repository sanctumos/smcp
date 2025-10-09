## Puppetry Plugin Integration Audit

Date: 2025-10-09
Branch: `cursor/audit-puppetry-plugin-integration-and-document-8676`

### Executive summary
- **No in-repo `puppetry` plugin code was found.** The plugin system is dynamic and discovers plugins from a directory (default `smcp/plugins` or `MCP_PLUGINS_DIR`). The only in-repo plugins are `botfather` and `devops`.
- Integration is implemented in `smcp/mcp_server.py` via discovery, command extraction from CLI `--help`, dynamic tool registration with FastMCP, and subprocess-based execution.
- To integrate a Puppetry plugin today, place a `cli.py` under a `puppetry/` directory in the plugin path (or set `MCP_PLUGINS_DIR`) and ensure the CLI `--help` output conforms to the expected format so commands can be detected.

### Where is the Puppetry plugin?
- Searched the repository for `puppetry`/`puppet`/`puppeteer` and found no code or docs referencing an in-repo plugin by that name.
- Likely scenarios:
  - The Puppetry plugin is intended to be provided externally (via `MCP_PLUGINS_DIR`).
  - Or it has not yet been added to this branch/repo.

### Integration flow (as implemented)
The plugin system integration lives in `smcp/mcp_server.py` and follows this flow:

- **Discovery (`discover_plugins`)**
  - Scans plugin directory for subfolders containing a `cli.py`.
  - Directory is chosen in this order:
    - `MCP_PLUGINS_DIR` environment variable (absolute preferred for external plugins).
    - A test-friendly path built from `Path(__file__) / "../plugins"` (used by unit tests to mock path behavior).
    - Runtime default: `Path(__file__).parent / "plugins"` (i.e., `smcp/plugins`).
  - Populates a `plugin_registry` mapping plugin name → `{ path: cli.py, commands: {} }`.

- **Help extraction (`get_plugin_help`)**
  - Runs `[sys.executable, cli_path, "--help"]` and returns `stdout`.
  - Failures are logged; returns empty string on error.

- **Command detection and tool registration (`register_plugin_tools` → `create_tool_from_plugin`)**
  - Parses the CLI help and looks for a section starting with `Available commands:`.
  - Every subsequent indented line (two spaces) until a blank line or `Examples` is treated as a command name.
  - For each command, registers a FastMCP tool named `"{plugin}.{command}"` using the module-global `server` instance.
  - Tool annotations are set with `destructiveHint=True`, `readOnlyHint=False` by default.
  - Input schema:
    - Some known commands have hard-coded JSON schema properties (e.g., `botfather.click-button`, `devops.deploy`).
    - Unknown commands default to an empty schema; clients can still pass arguments, but they won’t be described in the tool metadata.

- **Execution (`execute_plugin_tool`)**
  - When a tool is called, the server spawns the plugin CLI with `[python, cli.py, <command>, ...args]` using `asyncio.create_subprocess_exec`.
  - Arguments are mapped as `--key value`. Boolean `True` becomes a flag `--key`; `False` omits the flag.
  - `stdout` is returned as the `result` (wrapped in `TextContent`); non-zero exit returns an `error` with `stderr`.
  - Metrics increment counters for total/success/error tool calls.

- **Endpoints and server**
  - Server is a `FastMCP` instance with SSE at `/sse` and JSON-RPC message endpoint at `/messages/`.
  - A built-in `health` tool returns current metrics and discovered plugin names.

### Contract the Puppetry plugin must satisfy
To be auto-discovered and usable:

- **Directory structure**
  - If placing in-repo: `smcp/plugins/puppetry/cli.py`
  - If external: Set `MCP_PLUGINS_DIR=/path/to/plugins` and create `/path/to/plugins/puppetry/cli.py`.

- **CLI interface requirements**
  - `python cli.py --help` must print a block like:
    ```
    Available commands:
      command-one    Short description
      command-two    Short description

    Examples:
      python cli.py command-one --foo bar
    ```
  - Each command must be invocable as: `python cli.py <command> [--key value ...]`.
  - The command should print a single JSON object to stdout, e.g. `{ "result": "..." }` or `{ "error": "..." }`, and return a non-zero exit code on error.

- **Arguments and schema**
  - If your commands need parameters, you can accept them via standard argparse flags (e.g., `--selector`, `--timeout`), the server will forward them.
  - Note: The server currently hard-codes JSON schemas for a few known commands; others are registered with empty schemas. If rich schema is desired for Puppetry commands, the server would need to learn those commands (see recommendations) or the CLI could expose a machine-readable schema flag in the future.

### Tests and docs coverage
- Unit tests (`tests/unit/test_mcp_server.py`) validate:
  - Discovery via `MCP_PLUGINS_DIR` and default paths; missing or empty directories; missing `cli.py`.
  - `get_plugin_help` behavior on success, failure, and timeout.
  - Tool execution (success, failure, invalid name, nonexistent plugin, exception).
  - Tool registration parses `Available commands:` and registers tools accordingly.
- Integration/E2E tests (`tests/integration/test_mcp_protocol.py`, `tests/e2e/test_mcp_workflow.py`) validate:
  - SSE connectivity, initialize/initialized flow, tool listing, calling the `health` tool, concurrent requests.
  - Optional: attempts to invoke a plugin tool if present; otherwise accept structured errors.
- Documentation (`docs/api-reference.md`, `docs/getting-started.md`, `docs/plugin-development-guide.md`) references `botfather` and `devops` plugins. No references to a Puppetry plugin exist yet.

### Gaps, risks, and observations
- **No in-repo Puppetry plugin:** Must be supplied externally or added under `smcp/plugins/`.
- **Command detection is help-text fragile:** Registration depends on the `Available commands:` format and two-space indentation. Divergence breaks discovery of commands.
- **Schema is partially hard-coded:** Only certain known commands get parameter schemas. Puppetry commands would default to empty schemas, limiting client UX and validation.
- **No execution timeout:** `execute_plugin_tool` does not set a timeout for the subprocess; a hung Puppetry command could stall a request indefinitely.
- **Global mutable server/registry:** Uses a global `server` and `plugin_registry`. Calling registration multiple times may cause duplicate tool registrations if not guarded.
- **`Path(__file__) / "../plugins"` quirk:** Intentional for tests (mocking `Path.__truediv__`) but non-standard and could be brittle outside test conditions.
- **All tools marked `destructiveHint=True`:** Likely too aggressive; read-only Puppetry commands should be marked non-destructive to aid policy engines and clients.
- **Argument mapping booleans:** Only `True` emits a `--key`; `False` is omitted. If a Puppetry command needs explicit `--no-...` flags, the mapping may need enhancement.

### Recommendations for Puppetry integration
- **Provide the plugin now** via one of:
  - Add `smcp/plugins/puppetry/cli.py`, or
  - Distribute externally and set `MCP_PLUGINS_DIR` to a directory containing `puppetry/cli.py`.
- **Stabilize command discovery:** Consider a machine-readable export (e.g., `cli.py --mcp-commands-json`) to list commands and argument schemas, instead of parsing help text.
- **Dynamic schema support:** Extend `create_tool_from_plugin` to ingest schemas from the plugin (if provided) so clients see accurate parameters for Puppetry commands.
- **Execution timeout:** Add a configurable timeout (env var) for subprocess execution to avoid hung commands.
- **Tool annotations by command type:** Allow the plugin to tag commands as destructive/read-only to improve safety hints.
- ** idempotency and duplicate registration guard:** No-op re-registration or clear and re-register on startup.

### How to wire up a Puppetry plugin today (example)
1) Create a CLI at `puppetry/cli.py` under your plugin directory. Ensure `--help` prints an `Available commands:` block and each command prints a single JSON object and appropriate exit code.

2) Point the server at your plugin directory and run:
```bash
export MCP_PLUGINS_DIR=/absolute/path/to/your/plugins
python smcp/mcp_server.py --port 8000
```

3) List tools and call a Puppetry tool via MCP JSON-RPC on `POST /messages/` or via your MCP client.

If you want richer parameter schemas and better UX, plan to add a schema export in the CLI and extend the server to consume it.

### References
- Core integration code: `smcp/mcp_server.py`
- In-repo plugins (examples): `smcp/plugins/botfather/cli.py`, `smcp/plugins/devops/cli.py`
- Tests: `tests/unit/test_mcp_server.py`, `tests/integration/test_mcp_protocol.py`, `tests/e2e/test_mcp_workflow.py`
- Docs: `docs/api-reference.md`, `docs/getting-started.md`, `docs/plugin-development-guide.md`
