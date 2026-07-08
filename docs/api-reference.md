# API Reference

Complete API reference for the Sanctum Letta MCP Server.

## Overview

The Sanctum Letta MCP Server implements the Model Context Protocol (MCP) specification using Server-Sent Events (SSE) for real-time communication and HTTP POST for request/response handling.

## Endpoints

### SSE Endpoint

**URL**: `GET /sse`  
**Description**: Establishes a persistent Server-Sent Events connection for real-time server-to-client communication.

**Headers**:
- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `Connection: keep-alive`

**Response**: Continuous SSE stream with JSON-RPC 2.0 messages.

**Example**:
```bash
curl -N http://localhost:8000/sse
```

### Message Endpoint

**URL**: `POST /messages/`  
**Description**: Handles JSON-RPC 2.0 requests from clients.

**Headers**:
- `Content-Type: application/json`

**Request Body**: JSON-RPC 2.0 message

**Response**: JSON-RPC 2.0 response

**Example**:
```bash
curl -X POST http://localhost:8000/messages/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## MCP Protocol

### Message Format

All messages follow the JSON-RPC 2.0 specification:

```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "method": "method-name",
  "params": {
    // Method-specific parameters
  }
}
```

### Response Format

```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "result": {
    // Method-specific result
  }
}
```

### Error Format

```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "error": {
    "code": -32601,
    "message": "Method not found",
    "data": {
      // Additional error information
    }
  }
}
```

## Core Methods

### Initialize

**Method**: `initialize`  
**Description**: Initializes the MCP connection and negotiates protocol version.

**Request**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "tools": {},
      "resources": {},
      "prompts": {}
    },
    "clientInfo": {
      "name": "client-name",
      "version": "1.0.0"
    }
  }
}
```

**Response**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "tools": {
        "listChanged": true
      },
      "resources": {
        "listChanged": true
      },
      "prompts": {
        "listChanged": true
      }
    },
    "serverInfo": {
      "name": "sanctum-letta-mcp",
      "version": "3.0.3"
    }
  }
}
```

### Initialized

**Method**: `initialized`  
**Description**: Notification that client has completed initialization.

**Request**:
```json
{
  "jsonrpc": "2.0",
  "method": "initialized",
  "params": {}
}
```

**Response**: No response (notification)

### Tools List

**Method**: `tools/list`  
**Description**: Lists all available tools.

**Request**:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list"
}
```

**Response**:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "health",
        "description": "Check server health and plugin status",
        "inputSchema": {
          "type": "object",
          "properties": {},
          "required": []
        }
      },
      {
        "name": "demo_math.calculate",
        "description": "Perform a basic arithmetic operation",
        "inputSchema": {
          "type": "object",
          "properties": {
            "operation": {
              "type": "string",
              "description": "add, subtract, multiply, or divide"
            },
            "a": {"type": "number", "description": "First operand"},
            "b": {"type": "number", "description": "Second operand"}
          },
          "required": ["operation", "a", "b"]
        }
      }
    ]
  }
}
```

### Tools Call

**Method**: `tools/call`  
**Description**: Executes a tool with the provided arguments.

**Request**:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "health",
    "arguments": {}
  }
}
```

**Response**:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"status\":\"healthy\",\"plugins\":2,\"plugin_names\":[\"demo_math\",\"demo_text\"]}"
      }
    ]
  }
}
```

### Tool result contract (success vs. error)

Tool execution returns a machine-distinguishable success/failure result so callers can branch programmatically instead of string-matching (issue #53).

- **Success**: `result.isError` is `false` (or absent) and `result.content` carries the plugin's output.
- **Failure**: `result.isError` is `true`, `result.content[0].text` holds a human-readable message, and `result.structuredContent.error` carries a stable `code` and `message`.

**Error response**:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{ "type": "text", "text": "Plugin 'nope' not found" }],
    "isError": true,
    "structuredContent": { "error": { "code": "plugin_not_found", "message": "Plugin 'nope' not found" } }
  }
}
```

**Error codes** (condition → `code`):

| Condition | `code` |
|-----------|--------|
| Malformed tool name (not `plugin__command` / `plugin.command`) | `invalid_tool_name` |
| Unknown plugin | `plugin_not_found` |
| Plugin exited nonzero (structured `{"error": ...}` JSON or raw stdout preserved in `message`) | `plugin_error` |
| Plugin execution exceeded the configured timeout | `timeout` |
| Unexpected internal failure | `internal_error` |

A plugin that prints `{"error": "..."}` and exits nonzero has that message surfaced as the `plugin_error` `message` (preserving the #42 round-trip behavior).

## Error Codes

### Standard JSON-RPC 2.0 Errors

| Code | Message | Description |
|------|---------|-------------|
| -32700 | Parse error | Invalid JSON received |
| -32600 | Invalid Request | JSON-RPC request is invalid |
| -32601 | Method not found | Method does not exist |
| -32602 | Invalid params | Invalid method parameters |
| -32603 | Internal error | Internal JSON-RPC error |

### MCP-Specific Errors

| Code | Message | Description |
|------|---------|-------------|
| -32000 | Connection closed | Connection was closed |
| -32001 | Tool not found | Requested tool does not exist |
| -32002 | Tool execution failed | Tool execution encountered an error |
| -32003 | Invalid tool arguments | Tool arguments are invalid |

## Plugin Tool Schema

### Tool Definition

Each plugin tool follows this schema:

```json
{
  "name": "plugin.command",
  "description": "Tool description",
  "inputSchema": {
    "type": "object",
    "properties": {
      "parameter-name": {
        "type": "string|number|boolean",
        "description": "Parameter description",
        "default": "default-value"
      }
    },
    "required": ["required-parameter"]
  }
}
```

### Tool Response

Tool responses are wrapped in content blocks:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Tool execution result"
    }
  ]
}
```

## Plugin Architecture

### Plugin Discovery

The server discovers plugins by scanning the plugin directory (default: `plugins/`, next to `smcp.py`) for subdirectories containing a `cli.py` file. Each plugin directory represents a plugin namespace.

### Plugin Directory Structure

```
plugins/
├── demo_math/
│   ├── __init__.py
│   └── cli.py
├── demo_text/
│   ├── __init__.py
│   └── cli.py
└── custom-plugin/
    ├── __init__.py
    └── cli.py
```

### Symlink Support

The plugin discovery system fully supports symbolic links, enabling flexible plugin deployment architectures:

#### Centralized Plugin Management

You can centralize plugins in a designated location and use symlinks for discovery:

```
# Central plugin repository
/opt/sanctum/plugins/
├── demo_math/
├── demo_text/
└── custom-plugin/

# MCP server plugin directory with symlinks
plugins/
├── demo_math -> /opt/sanctum/plugins/demo_math
├── demo_text -> /opt/sanctum/plugins/demo_text
└── custom-plugin -> /opt/sanctum/plugins/custom-plugin
```

#### Benefits of Symlink Architecture

1. **Separation of Concerns**: Keep MCP server code separate from plugin implementations
2. **Centralized Management**: Manage plugins in a designated repository
3. **Dynamic Loading**: Add/remove plugins by creating/removing symlinks
4. **Version Control**: Maintain plugins in separate repositories
5. **Deployment Flexibility**: Deploy plugins independently of the MCP server

#### Symlink Examples

```bash
# Create symlink to centralized plugin
ln -s /opt/sanctum/plugins/demo_math plugins/demo_math

# Create symlink to user's custom plugin
ln -s /home/user/custom-plugins/my-plugin plugins/my-plugin

# Create symlink to network-mounted plugin
ln -s /mnt/network/plugins/enterprise-plugin plugins/enterprise-plugin
```

#### Environment Variable Override

You can override the plugin directory using the `MCP_PLUGINS_DIR` environment variable:

```bash
# Use custom plugin directory
export MCP_PLUGINS_DIR=/opt/sanctum/plugins
python smcp.py

# Or specify directly
MCP_PLUGINS_DIR=/opt/sanctum/plugins python smcp.py
```

### Plugin Execution

Plugins are executed as subprocesses with the following characteristics:

- **Isolation**: Each plugin runs in its own process
- **Discovery timeout**: plugin `--describe` / `--help` introspection at startup uses a short internal timeout so a misbehaving plugin cannot stall discovery
- **Execution timeout**: tool calls run with **no timeout by default**; set `MCP_PLUGIN_TIMEOUT` (seconds) or `--plugin-timeout` to bound them. On timeout the child is terminated (`terminate()` → `kill()`)
- **Cleanup on cancel**: if a client disconnects or the call is cancelled, the plugin subprocess is terminated rather than orphaned
- **Error Handling**: Failed plugins are logged but don't crash the server; a plugin that prints `{"error": ...}` and exits nonzero has that message surfaced to the caller
- **Arguments**: Plugin arguments are passed as command-line flags, rendered per each plugin's declared `--describe` schema (see the plugin development guide for boolean flag styles)

## SSE Events

### Connection Events

When a client connects to the SSE endpoint, the server may send:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/tools/list",
  "params": {
    "tools": [
      // List of available tools
    ]
  }
}
```

### Progress Events

For long-running operations:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/progress",
  "params": {
    "id": "operation-id",
    "progress": {
      "type": "indeterminate|percent",
      "value": 50
    }
  }
}
```

## Authentication

The HTTP/SSE transport supports optional shared-secret authentication. Configure one or more keys and
clients must present a valid key as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

```bash
export MCP_API_KEY="your-long-random-secret"
python smcp.py --allow-external
```

Behavior:

- **Fail closed on external binds:** binding `0.0.0.0` (`--allow-external`) **refuses to start** unless
  `MCP_API_KEY` / `MCP_API_KEYS` is set, or `MCP_AUTH_DISABLED=1` is explicitly provided (logged loudly).
- **Loopback convenience:** loopback clients (`127.0.0.1`, `::1`) bypass the key by default even when one
  is set. Require the key locally too with `--require-auth` or `MCP_AUTH_ALLOW_LOOPBACK=0`.
- **Unauthorized requests** receive `401 Unauthorized` with a `WWW-Authenticate: Bearer` header.
- Auth is enforced by a raw ASGI middleware, so SSE streaming is never buffered.
- The **STDIO transport** (`smcp_stdio.py`) has no network surface and is unaffected.

Multiple keys (for rotation or multiple clients) can be supplied via `MCP_API_KEYS` (comma-separated);
they are merged with `MCP_API_KEY`.

For production also consider terminating TLS at a reverse proxy and restricting access to trusted
networks (see the [Deployment Guide](deployment-guide.md)).

## Rate Limiting

The server does not currently implement rate limiting. For production use, consider:

1. **Request Rate Limiting**: Limit requests per client
2. **Concurrent Connection Limits**: Limit simultaneous SSE connections
3. **Tool Execution Limits**: Limit concurrent tool executions

## Logging

The server logs to both the console and a rotating log file:

- **Console**: `INFO` level and above, human-readable format.
- **File**: `logs/mcp_server.log` (created relative to the working directory), `DEBUG` level and above,
  rotated at **10 MB** with **5** backups kept.

Log lines use the format:

```
2026-07-08 15:21:07,215 - __main__ - INFO - Starting Sanctum Letta MCP Server...
2026-07-08 15:21:07,354 - smcp - INFO - Registered tool: demo_math.calculate
```

> **Note:** Logging destinations and levels are currently fixed (not yet configurable via environment
> variables). If you need JSON output, alternate paths, or level control, open an issue — this is on the
> roadmap and not wired up today.

## Health Check

### Health Tool

The built-in health tool provides server status:

```bash
curl -X POST http://localhost:8000/messages/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"health","arguments":{}}}'
```

**Response**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"status\":\"healthy\",\"plugins\":2,\"plugin_names\":[\"demo_math\",\"demo_text\"]}"
      }
    ]
  }
}
```

### Health Status

- **status**: `healthy` or `unhealthy`
- **plugins**: Number of discovered plugins
- **plugin_names**: List of plugin names
 - **metrics**: Basic runtime metrics (uptime, tool call counts)

## Configuration

### Command Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--allow-external` | `False` | Allow external connections (default: localhost only) |
| `--require-auth` | `False` | Require the API key even for loopback clients (`MCP_AUTH_ALLOW_LOOPBACK=0`) |
| `--port` | `8000` | Port to run the server on |
| `--host` | `127.0.0.1` | Host to bind to (default: localhost for security) |
| `--plugin-timeout` | none | Seconds before a plugin subprocess is terminated (`0`/negative = no timeout) |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_PORT` | `8000` | Server port |
| `MCP_HOST` | `127.0.0.1` | Host to bind to |
| `MCP_PLUGINS_DIR` | `plugins/` (next to `smcp.py`) | Plugin directory |
| `MCP_API_KEY` | — | Accepted API key for the HTTP/SSE transport |
| `MCP_API_KEYS` | — | Comma-separated accepted keys (merged with `MCP_API_KEY`) |
| `MCP_AUTH_DISABLED` | `0` | `1` disables auth **and** the external-bind guard |
| `MCP_AUTH_ALLOW_LOOPBACK` | `1` | `1` lets loopback clients skip the key; `0` requires it locally too |
| `MCP_PLUGIN_TIMEOUT` | — (none) | Seconds before a plugin subprocess is terminated (`0`/negative = none) |
| `SMCP_ATTACH_PROFILE` | `full` | Session attach governor profile (`full`, `admin`, `chatter`, `partner`) |

### Security Configuration

By default, the server binds to `127.0.0.1` (localhost only) for security. This ensures that only processes running on the same machine can connect to the MCP server.

**Examples**:
```bash
# Default: localhost only (secure)
python smcp.py

# Allow external connections (use with caution)
python smcp.py --allow-external

# Custom port with localhost-only
python smcp.py --port 9000

# Custom host and port
python smcp.py --host 0.0.0.0 --port 8000
```

### Server Configuration

The server uses the base MCP library with SSE transport. Configuration is handled through environment variables and command-line arguments:

```python
# Server configuration (from smcp.py)
from mcp.server import Server
from mcp.server.sse import SseServerTransport

# Create base MCP server
server = Server(name="sanctum-letta-mcp", version="3.0.3")

# Create SSE transport
sse_transport = SseServerTransport("/messages/")

# Server host/port configured via:
# - Command line: --host, --port
# - Environment: MCP_HOST, MCP_PORT
```

## Examples

### Complete Client Integration

```python
import httpx
import json
import asyncio

async def mcp_client_example():
    """Complete MCP client integration example."""
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient() as client:
        # Step 1: Initialize connection
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "example-client", "version": "1.0.0"}
            }
        }
        
        response = await client.post(f"{base_url}/messages/", json=init_request)
        print("Initialization:", response.json())
        
        # Step 2: Send initialized notification
        await client.post(f"{base_url}/messages/", json={
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {}
        })
        
        # Step 3: List available tools
        tools_response = await client.post(f"{base_url}/messages/", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        })
        
        tools = tools_response.json()["result"]["tools"]
        print(f"Available tools: {len(tools)}")
        
        # Step 4: Call health tool
        health_response = await client.post(f"{base_url}/messages/", json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "health",
                "arguments": {}
            }
        })
        
        health_result = health_response.json()["result"]
        print("Health check:", health_result)

# Run the example
asyncio.run(mcp_client_example())
```

### SSE Connection Example

```python
import httpx
import asyncio

async def sse_connection_example():
    """SSE connection example."""
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", f"{base_url}/sse") as response:
            print(f"SSE Status: {response.status_code}")
            print(f"Content-Type: {response.headers.get('content-type')}")
            
            # Read SSE events
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        try:
                            event = json.loads(data)
                            print(f"SSE Event: {event}")
                        except json.JSONDecodeError:
                            print(f"Raw SSE data: {data}")

# Run the example
asyncio.run(sse_connection_example())
```

## Troubleshooting

### Common Issues

1. **Connection Refused**: Server not running or wrong port
2. **404 Not Found**: Wrong endpoint URL
3. **Invalid JSON**: Malformed JSON-RPC request
4. **Method Not Found**: Unsupported MCP method
5. **Tool Not Found**: Plugin not loaded or tool not registered

### Debug Steps

1. **Check Server Status**: Verify server is running and listening
2. **Check Logs**: Review server logs for errors
3. **Test Endpoints**: Use curl to test individual endpoints
4. **Validate JSON**: Ensure JSON-RPC format is correct
5. **Check Plugins**: Verify plugins are discovered and loaded

---

For more information, see the [Plugin Development Guide](plugin-development-guide.md) and [README](../README.md). 