# SMCP

[![License: AGPLv3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0) [![Docs License: CC BY-SA 4.0](https://img.shields.io/badge/Docs%20License-CC%20BY--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-sa/4.0/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-Protocol%20Compliant-green.svg)](https://modelcontextprotocol.io/)
[![SanctumOS](https://img.shields.io/badge/SanctumOS-Core%20Module-blue.svg)](https://sanctumos.org)

**Sanctum Letta MCP Server: a plugin-based Model Context Protocol server**

SMCP is a plugin-based Model Context Protocol (MCP) server for the [Letta](https://www.letta.com/)
agentic AI framework. It gives AI clients a clean, discoverable path to external tools through a
plug-and-play plugin architecture, and it speaks the base MCP protocol over both **SSE** (for
remote/HTTP clients like Letta) and **STDIO** (for local clients). SMCP is a SanctumOS core module,
maintained by the Sanctum team.

> **Fork note:** This is the **Sanctum** edition (`sanctumos/smcp`). An Animus-branded fork lives at
> `AnimusUNO/smcp`; the two track each other but carry their own branding.

## 🚀 Features

- **Plugin architecture** — drop a CLI plugin in a directory and its commands become MCP tools; no core changes required
- **MCP protocol compliant** — full support for the Model Context Protocol specification
- **Two transports** — bidirectional **SSE** (`smcp.py`) for Letta and remote clients, and **STDIO** (`smcp_stdio.py`) for local clients
- **Auto-discovery** — plugins are discovered at startup via a `--describe` contract (with `--help` scraping as a fallback)
- **Schema-aware arguments** — booleans and other typed args are rendered onto plugin argv per each plugin's declared schema
- **Optional API-key authentication** — shared-secret auth for the HTTP/SSE transport, fail-closed on external binds
- **Session attach governor** — expose a curated, profile-scoped subset of tools to a session (`sanctum__tools`)
- **Configurable plugin timeouts** and **subprocess cleanup** on client disconnect/cancel
- **Health monitoring & structured logging**

## 🔧 Branches

Day-to-day work and experimental site-specific plugins land on **`dev`**; **`master`** stays aligned
with what is stable for public/production use. Merge or cherry-pick from `dev` to `master` when ready.

```bash
git fetch origin && git checkout dev && git pull origin dev
```

## 📖 Documentation

- **[🚀 Getting Started Guide](docs/getting-started.md)** — complete setup in a few minutes
- **[🔌 Plugin Development](docs/plugin-development-guide.md)** — build your first plugin
- **[📋 Examples](docs/examples.md)** — copy-paste working code
- **[🚀 Deployment Guide](docs/deployment-guide.md)** — systemd, Docker, reverse proxy
- **[🔧 API Reference](docs/api-reference.md)** — endpoints, methods, configuration
- **[🔗 Letta MCP Connection Guide](docs/Letta-MCP-Connection-Guide.md)** — connect Letta clients to SMCP
- **[🚨 Troubleshooting](docs/troubleshooting.md)** — common issues and fixes

## 📦 Installation

### Prerequisites

- Python 3.8 or higher
- pip

### Quick Start

```bash
# Clone the repository
git clone https://github.com/sanctumos/smcp.git
cd smcp

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server (SSE transport)
python smcp.py
```

The server starts on `http://localhost:8000` by default, bound to **localhost only** for security.

For local STDIO clients, run the STDIO transport instead:

```bash
python smcp_stdio.py
```

### Security & network binding

By default the server binds to `127.0.0.1` (localhost only). This is the recommended setting.

```bash
python smcp.py --host 127.0.0.1     # localhost-only (explicit)
python smcp.py --allow-external     # allow external connections (see auth below)
python smcp.py --port 9000          # custom port
python smcp.py --host 0.0.0.0 --port 8000
```

#### API-key authentication (HTTP/SSE transport)

The HTTP/SSE transport supports shared-secret authentication. Configure a key and clients must
present it as `Authorization: Bearer <key>` (or `X-API-Key: <key>`):

```bash
export MCP_API_KEY="your-long-random-secret"
python smcp.py --allow-external
```

Key rules:

- **Fail closed:** `--allow-external` (binding `0.0.0.0`) **refuses to start** without
  `MCP_API_KEY`/`MCP_API_KEYS`, unless you explicitly set `MCP_AUTH_DISABLED=1` to run open
  (not recommended).
- **Localhost stays easy:** a default `python smcp.py` on `127.0.0.1` needs no key. Loopback clients
  bypass the key by default even when one is set; pass `--require-auth` (or
  `MCP_AUTH_ALLOW_LOOPBACK=0`) to require it locally too.
- Requests without a valid key get `401 Unauthorized` (`WWW-Authenticate: Bearer`).
- The STDIO transport has no network surface and is unaffected.

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_PORT` | `8000` | Port for the MCP server |
| `MCP_HOST` | `127.0.0.1` | Host to bind to (default: localhost-only for security) |
| `MCP_PLUGINS_DIR` | `plugins/` (next to `smcp.py`) | Directory containing plugins |
| `MCP_API_KEY` | — | Accepted API key for the HTTP/SSE transport (`Authorization: Bearer <key>` or `X-API-Key: <key>`) |
| `MCP_API_KEYS` | — | Comma-separated list of accepted keys (for rotation / multiple clients). Merged with `MCP_API_KEY`. |
| `MCP_AUTH_DISABLED` | `0` | Explicit escape hatch: `1` disables auth **and** the external-bind guard (logged loudly). |
| `MCP_AUTH_ALLOW_LOOPBACK` | `1` | When `1`, loopback (`127.0.0.1`/`::1`) clients skip the key check. Set `0` (or use `--require-auth`) to require the key even locally. |
| `MCP_PLUGIN_TIMEOUT` | — (none) | Seconds before a plugin subprocess is terminated. Unset / `0` / negative means **no timeout**. Overridden by `--plugin-timeout`. |
| `SMCP_ATTACH_PROFILE` | *(from profile config, else `full`)* | Session attach governor profile name (must exist in loaded profile config). |
| `SMCP_PROFILES` | *(unset)* | JSON profile config file or directory of `*.json` profile files. Product-specific allowlists live here — see `docs/examples/governor-profiles.json`. |
| `SMCP_ADMIN_PREFIX` | *(unset)* | Optional generic `admin` profile: attach all catalog tools matching this prefix (e.g. `tasks__`). |
| `LETTA_SERVER_URL` | — | If set with `LETTA_SERVER_PASSWORD`, SMCP loads agent env vars (secrets) from the Letta API at startup. If unset, SMCP tries `~/.letta/.env`; default URL is `http://127.0.0.1:8284`. |
| `LETTA_SERVER_PASSWORD` | — | Bearer token for the Letta API (or use `LETTA_API_KEY`). Required for loading env vars. |
| `LETTA_AGENT_ID` | — | Optional. If set, only this agent's env vars are loaded; otherwise all agents' vars are merged. |


### Command-line arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--allow-external` | off | Allow external connections (default: localhost only) |
| `--require-auth` | off | Require the API key even for loopback clients (`MCP_AUTH_ALLOW_LOOPBACK=0`) |
| `--host` | `127.0.0.1` | Host to bind to |
| `--port` | `8000` | Port to run on |
| `--plugin-timeout` | none | Seconds before a plugin subprocess is terminated (`0`/negative = no timeout) |

## 🔌 Plugin Development

See the [Plugin Development Guide](docs/plugin-development-guide.md) for the full walkthrough. In short,
each plugin is a directory with a `cli.py` that exposes commands and (recommended) a `--describe`
command returning JSON metadata:

```
plugins/
└── your_plugin/
    ├── __init__.py
    ├── cli.py          # command interface (required)
    └── README.md       # plugin docs (recommended)
```

Every command a plugin exposes becomes an MCP tool named `your_plugin.command`. Point
`MCP_PLUGINS_DIR` at any directory (symlinks supported) to load plugins from a central location.

### Bundled demo plugins (working examples)

- **demo_math**: `calculate`, `format_bytes`, `coin_flip` — typed tools, JSON out, `--describe` for MCP schemas (no network)
- **demo_text**: `echo`, `word_count`, `slugify`, `hash_preview` — string utilities agents can chain in one session

```bash
python plugins/demo_math/cli.py --describe
python plugins/demo_math/cli.py calculate --operation add --a 2 --b 3
python plugins/demo_text/cli.py word_count --text "hello world"
```

## 🔗 MCP Protocol Integration

### Endpoints

- **SSE Endpoint**: `GET /sse` — server-sent events for real-time communication
- **Message Endpoint**: `POST /messages/` — JSON-RPC 2.0 message handling

### Example client integration

```python
import httpx

async def connect_to_mcp():
    base_url = "http://localhost:8000"
    async with httpx.AsyncClient() as client:
        # Initialize
        await client.post(f"{base_url}/messages/", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "my-client", "version": "1.0.0"},
            },
        })
        # List tools
        tools = (await client.post(f"{base_url}/messages/", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })).json()["result"]["tools"]
        # Call a tool
        return (await client.post(f"{base_url}/messages/", json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "health", "arguments": {}},
        })).json()["result"]
```

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -v

# By category
python -m pytest tests/unit/ -v
python -m pytest tests/integration/ -v
python -m pytest tests/e2e/ -v

# With coverage (project floor is 90%)
python -m pytest tests/ --cov=. --cov-report=term-missing
```

## 📊 Monitoring

### Health check

```bash
curl -X POST http://localhost:8000/messages/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"health","arguments":{}}}'
```

### Logging

Logs are written to the console and to a rotating file at `logs/mcp_server.log` (10 MB × 5 backups).
See the [API Reference](docs/api-reference.md#logging) for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes
4. Push to the branch and open a Pull Request against `dev`

## 📄 License

This project uses dual licensing:

- **Code**: GNU Affero General Public License v3.0 (AGPLv3) — see [LICENSE](LICENSE).
- **Documentation & Data**: Creative Commons Attribution-ShareAlike 4.0 International (CC-BY-SA 4.0) — see [LICENSE-DOCS](LICENSE-DOCS).

**Important**: AGPLv3 is a copyleft license. If you modify and distribute this software (including
running it over a network), you must make your source code available under the same license.

## 🙏 Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io/) for the protocol specification
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) for the base MCP library
- The Letta team for the agentic framework SMCP integrates with
- The Sanctum team for SanctumOS

## 📞 Support

- **Author**: Mark Rizzn Hopkins
- **Website**: https://sanctumos.org
- **Issues**: https://github.com/sanctumos/smcp/issues

---

**Part of SanctumOS** — a comprehensive AI framework for modern applications.
