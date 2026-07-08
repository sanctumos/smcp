# Getting Started with SMCP

Welcome to SMCP (Sanctum Model Context Protocol Server)! This guide gets you up and running quickly.

## 🚀 Installation

```bash
# Clone the repository
git clone https://github.com/sanctumos/smcp.git
cd smcp

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server (SSE transport)
python smcp.py
```

For local STDIO clients, run `python smcp_stdio.py` instead.

## 🔧 First-Time Setup

### Prerequisites Check
Before starting, ensure you have:
- **Python 3.8+** installed and accessible
- **pip** package manager available
- **Network access** for dependency installation

### Initial Configuration
SMCP comes with sensible defaults, but you can customize:

```bash
# Check available options
python smcp.py --help

# Run with custom port
python smcp.py --port 9000

# Run with custom host binding
python smcp.py --host 127.0.0.1
```

By default the server binds to `127.0.0.1` (localhost only). To accept external connections you must
also configure an API key — see [Enabling external access](#-enabling-external-access) below.

## 🌐 Accessing Your Server

### Default Endpoints
Once running, SMCP provides these endpoints:

- **Main Server**: `http://localhost:8000`
- **SSE Endpoint**: `http://localhost:8000/sse`
- **Message Endpoint**: `http://localhost:8000/messages/`

### Health Check
Verify your server is running:

```bash
curl -X POST http://localhost:8000/messages/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"health","arguments":{}}}'
```

Expected response (the health payload is returned as JSON text inside a content block):
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

## 🔒 Enabling external access

Binding to a non-loopback address requires an API key (the server otherwise refuses to start):

```bash
export MCP_API_KEY="your-long-random-secret"
python smcp.py --allow-external
```

Clients then present the key as `Authorization: Bearer <key>` or `X-API-Key: <key>`. See the
[README security section](../README.md#-installation) and [API Reference](api-reference.md#authentication)
for the full rules.

## 🔌 Your First Plugin

### Built-in Plugins
SMCP ships small **working** demos (structured JSON + `--describe` for tool schemas):

- **demo_math**: arithmetic, byte formatting, coin flip
- **demo_text**: echo, word count, slugify, short hash preview

### Testing a Plugin
```bash
python plugins/demo_math/cli.py --describe
python plugins/demo_math/cli.py calculate --operation add --a 2 --b 3

python plugins/demo_text/cli.py --describe
python plugins/demo_text/cli.py word_count --text "hello world"
```

## 🔗 Connecting Clients

### Letta Client Connection
For Letta clients, see the [Letta MCP Connection Guide](Letta-MCP-Connection-Guide.md).

### Custom Client Example
```python
import httpx
import asyncio

async def test_connection():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/messages/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"}
                }
            }
        )
        print(f"Connection status: {response.status_code}")
        print(f"Response: {response.json()}")

asyncio.run(test_connection())
```

## 🚨 Common Issues & Solutions

### Port Already in Use
```bash
# Error: Address already in use
# Solution: Use a different port
python smcp.py --port 9000
```

### Server exits immediately with --allow-external
```bash
# Cause: binding externally without an API key (fail-closed guard)
# Solution: set a key first
export MCP_API_KEY="your-long-random-secret"
python smcp.py --allow-external
```

### Plugin Not Found
```bash
# Error: Plugin directory not found
# Solution: point at your plugins directory
export MCP_PLUGINS_DIR=/path/to/your/plugins
python smcp.py
```

## 📚 Next Steps

1. **Explore Plugins**: Check out the [Plugin Development Guide](plugin-development-guide.md)
2. **API Reference**: Review the [Complete API Documentation](api-reference.md)
3. **Deployment**: See the [Deployment Guide](deployment-guide.md)
4. **Troubleshooting**: Visit the [Troubleshooting Guide](troubleshooting.md)

## 🆘 Need Help?

- **Documentation**: Check the [main documentation index](../README.md#-documentation)
- **Website**: https://sanctumos.org
- **Issues**: https://github.com/sanctumos/smcp/issues

---

**Ready to build?** Start with the [Plugin Development Guide](plugin-development-guide.md) to create your first custom plugin!
