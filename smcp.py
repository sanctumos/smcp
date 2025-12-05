#!/usr/bin/env python3
"""
Sanctum Letta MCP Server - Base MCP Implementation

A Server-Sent Events (SSE) server for orchestrating plugin execution using the base MCP library.
Compliant with Model Context Protocol (MCP) specification and compatible with Letta's SSE client.

Copyright (c) 2025 Mark Rizzn Hopkins

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Sequence
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

# Global variables
server: Server | None = None
plugin_registry: Dict[str, Dict[str, Any]] = {}
metrics: Dict[str, Any] = {
    "start_time": time.time(),
    "plugins_discovered": 0,
    "tools_registered": 0,
    "tool_calls_total": 0,
    "tool_calls_success": 0,
    "tool_calls_error": 0,
}

# Configure logging
def setup_logging():
    """Set up logging configuration."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "mcp_server.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Reduce noise from some libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    
    return logging.getLogger(__name__)

logger = setup_logging()


def discover_plugins() -> Dict[str, Dict[str, Any]]:
    """Discover available plugins in the plugins directory."""
    # Use environment variable if set, otherwise use relative path
    plugins_dir_env = os.getenv("MCP_PLUGINS_DIR")
    if plugins_dir_env:
        plugins_dir = Path(plugins_dir_env)
    else:
        # Use relative path from current script location
        plugins_dir = Path(__file__).parent / "plugins"
    plugins = {}
    
    if not plugins_dir.exists():
        logger.warning(f"Plugins directory not found: {plugins_dir}")
        return plugins
    
    logger.info("Discovering plugins...")
    
    for plugin_dir in plugins_dir.iterdir():
        if plugin_dir.is_dir():
            cli_path = plugin_dir / "cli.py"
            if cli_path.exists():
                plugin_name = plugin_dir.name
                plugins[plugin_name] = {
                    "path": str(cli_path),
                    "commands": {}
                }
                logger.info(f"Discovered plugin: {plugin_name}")
    
    metrics["plugins_discovered"] = len(plugins)
    logger.info(f"Discovered {len(plugins)} plugins: {list(plugins.keys())}")
    
    return plugins


def get_plugin_help(plugin_name: str, cli_path: str) -> str:
    """Get help output from a plugin CLI."""
    try:
        result = subprocess.run(
            [sys.executable, cli_path, "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return result.stdout
        else:
            logger.error(f"Plugin {plugin_name} help command failed: {result.stderr}")
            return ""
    except Exception as e:
        logger.error(f"Error getting help for plugin {plugin_name}: {e}")
        return ""


def get_plugin_describe(plugin_name: str, cli_path: str) -> Dict[str, Any] | None:
    """
    Get plugin description using --describe command (new method).
    
    Returns structured plugin spec or None if not supported.
    Expected JSON format:
    {
        "plugin": {
            "name": "plugin_name",
            "version": "1.0.0",
            "description": "Plugin description"
        },
        "commands": [
            {
                "name": "command-name",
                "description": "Command description",
                "parameters": [
                    {
                        "name": "param-name",
                        "type": "string|number|boolean|array|object",
                        "description": "Parameter description",
                        "required": true,
                        "default": null
                    }
                ]
            }
        ]
    }
    """
    try:
        result = subprocess.run(
            [sys.executable, cli_path, "--describe"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            try:
                spec = json.loads(result.stdout.strip())
                # Validate basic structure
                if "commands" in spec and isinstance(spec["commands"], list):
                    return spec
                else:
                    logger.warning(f"Plugin {plugin_name} --describe returned invalid structure")
                    return None
            except json.JSONDecodeError as e:
                logger.warning(f"Plugin {plugin_name} --describe returned invalid JSON: {e}")
                return None
        else:
            # --describe not supported, return None to trigger fallback
            return None
    except subprocess.TimeoutExpired:
        logger.warning(f"Plugin {plugin_name} --describe command timed out")
        return None
    except Exception as e:
        logger.debug(f"Plugin {plugin_name} --describe failed (will use fallback): {e}")
        return None


def parse_commands_from_help(help_text: str) -> List[str]:
    """
    Parse command names from help text (fallback method for old plugins).
    
    Looks for "Available commands:" section and extracts command names.
    """
    lines = help_text.split('\n')
    commands = []
    in_commands_section = False
    
    for line in lines:
        if line.strip().startswith("Available commands:"):
            in_commands_section = True
            continue
        if in_commands_section:
            # End of commands section if we hit an empty line or Examples
            if not line.strip() or line.strip().startswith("Examples"):
                in_commands_section = False
                continue
            if line.startswith('  '):
                parts = line.strip().split()
                if parts and parts[0] not in ['usage:', 'options:', 'Available', 'Examples:']:
                    commands.append(parts[0])
    
    return commands


async def execute_plugin_tool(tool_name: str, arguments: dict) -> str:
    """Execute a plugin tool with the given arguments."""
    try:
        # Parse tool name to get plugin and command
        # Tool names use double underscore separator: "plugin__command"
        # Support both double underscore (new) and dot (legacy) for backward compatibility
        if '__' in tool_name:
            parts = tool_name.split('__', 1)  # Split on double underscore
            if len(parts) != 2:
                return f"Invalid tool name format: {tool_name}. Expected 'plugin__command'"
            plugin_name, command = parts
        elif '.' in tool_name:
            # Legacy dot format for backward compatibility
            plugin_name, command = tool_name.split('.', 1)
        else:
            return f"Invalid tool name format: {tool_name}. Expected 'plugin__command' or 'plugin.command'"
        
        if plugin_name not in plugin_registry:
            return f"Plugin '{plugin_name}' not found"
        
        plugin_info = plugin_registry[plugin_name]
        cli_path = plugin_info["path"]
        
        # Build command arguments
        cmd_args = [sys.executable, cli_path, command]
        
        # Add arguments
        # Convert underscores to dashes for command-line arguments (standard convention)
        for key, value in arguments.items():
            # Convert parameter name (use_ssl) to CLI argument (--use-ssl)
            arg_name = key.replace('_', '-')
            if isinstance(value, bool):
                if value:
                    cmd_args.append(f"--{arg_name}")
            else:
                cmd_args.extend([f"--{arg_name}", str(value)])
        
        # Suppress verbose logging in STDIO mode
        if logger.level <= logging.INFO:
            logger.info(f"Executing plugin command: {' '.join(cmd_args)}")
        
        # Execute the command with timeout
        # Default timeout: 5 minutes (300 seconds) for long-running operations like IMAP connections
        # This prevents indefinite hangs while allowing reasonable time for network operations
        timeout_seconds = 300
        
        process = None
        try:
            # Use unbuffered output to prevent hanging on stdout/stderr
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            # Also set unbuffered for subprocess Python
            env['PYTHONIOENCODING'] = 'utf-8'
            
            # Use PIPE for both to see what's happening
            # Explicitly set stdin to DEVNULL to prevent subprocess from waiting for input
            # We'll read them concurrently to avoid deadlock
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.DEVNULL,  # Don't inherit stdin - prevent hanging on input
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            # Read both streams concurrently with a single timeout for the whole operation
            async def read_output():
                """Read both streams concurrently."""
                stdout_data = b''
                stderr_data = b''
                
                async def read_stdout():
                    nonlocal stdout_data
                    if process.stdout:
                        while True:
                            chunk = await process.stdout.read(8192)
                            if not chunk:
                                break
                            stdout_data += chunk
                
                async def read_stderr():
                    nonlocal stderr_data
                    if process.stderr:
                        while True:
                            chunk = await process.stderr.read(8192)
                            if not chunk:
                                break
                            stderr_data += chunk
                
                # Read both streams concurrently
                await asyncio.gather(read_stdout(), read_stderr())
                
                # Wait for process to finish
                await process.wait()
                
                return stdout_data, stderr_data
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    read_output(),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                # Process is hanging - kill it and capture what we have
                if process.returncode is None:
                    process.kill()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
                # Try to get any partial output
                if process.stdout:
                    try:
                        partial_stdout = await asyncio.wait_for(process.stdout.read(), timeout=0.1)
                        if partial_stdout:
                            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ''
                            error_msg = f"Plugin command timed out. Partial output: {partial_stdout.decode('utf-8', errors='replace')[:200]}"
                            if stderr_text:
                                error_msg += f" Stderr: {stderr_text[:200]}"
                            metrics["tool_calls_error"] += 1
                            return error_msg
                    except:
                        pass
                raise  # Re-raise to be caught by outer handler
        except asyncio.TimeoutError:
            # Kill the process if it times out
            if process:
                try:
                    process.kill()
                    await process.wait()
                except:
                    pass
            error_msg = f"Plugin command timed out after {timeout_seconds} seconds"
            metrics["tool_calls_error"] += 1
            return error_msg
        
        if process.returncode == 0:
            result = stdout.decode().strip()
            metrics["tool_calls_success"] += 1
            return result
        else:
            # Plugin should output error as JSON to stdout, but if not, use returncode
            if stdout:
                try:
                    # Try to parse error from stdout JSON
                    error_data = json.loads(stdout.decode().strip())
                    if "error" in error_data:
                        error_msg = error_data["error"]
                    else:
                        error_msg = stdout.decode().strip()
                except:
                    error_msg = stdout.decode().strip() or f"Plugin exited with code {process.returncode}"
            else:
                error_msg = f"Plugin exited with code {process.returncode} (no output)"
            metrics["tool_calls_error"] += 1
            return f"Error: {error_msg}"
            
    except Exception as e:
        error_msg = f"Error executing tool {tool_name}: {e}"
        logger.error(error_msg)
        metrics["tool_calls_error"] += 1
        return error_msg


def parameter_spec_to_json_schema(parameters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert plugin parameter spec to JSON Schema for MCP tools.
    
    Args:
        parameters: List of parameter specs from --describe output
            Each parameter should have: name, type, description, required, default
    
    Returns:
        JSON Schema object with properties and required fields
    """
    properties = {}
    required = []
    
    for param in parameters:
        param_name = param.get("name", "")
        param_type = param.get("type", "string")
        param_desc = param.get("description", "")
        param_required = param.get("required", False)
        param_default = param.get("default")
        
        # Map plugin types to JSON Schema types
        json_type_map = {
            "string": "string",
            "number": "number",
            "integer": "integer",
            "boolean": "boolean",
            "array": "array",
            "object": "object",
        }
        
        json_type = json_type_map.get(param_type.lower(), "string")
        
        # Build property schema
        prop_schema = {"type": json_type}
        
        if param_desc:
            prop_schema["description"] = param_desc
        
        if param_default is not None:
            prop_schema["default"] = param_default
        
        # Handle arrays - assume array of strings if not specified
        if json_type == "array":
            prop_schema["items"] = {"type": "string"}
        
        properties[param_name] = prop_schema
        
        if param_required:
            required.append(param_name)
    
    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False
    }
    
    return schema


def create_tool_from_plugin(plugin_name: str, command: str, command_spec: Dict[str, Any] | None = None) -> Tool:
    """
    Create an MCP Tool from a plugin command.
    
    Args:
        plugin_name: Name of the plugin
        command: Name of the command
        command_spec: Optional command specification from --describe output
            If provided, will extract description and parameters for schema
    
    Note: Tool names use double underscore separator (e.g., "plugin__command") instead of dots
    to comply with Claude Desktop's validation pattern: ^[a-zA-Z0-9_-]{1,64}$
    Double underscore is unlikely to appear in plugin or command names.
    """
    # Use double underscore instead of dot for Claude Desktop compatibility
    # Claude Desktop requires: ^[a-zA-Z0-9_-]{1,64}$
    # Double underscore is safe because it's unlikely in plugin/command names
    tool_name = f"{plugin_name}__{command}"
    
    # Extract description from spec if available
    if command_spec:
        description = command_spec.get("description", f"Execute {plugin_name} {command} command")
        parameters = command_spec.get("parameters", [])
        
        # Build schema from parameters
        input_schema = parameter_spec_to_json_schema(parameters)
    else:
        # Fallback: simple description and empty schema
        description = f"Execute {plugin_name} {command} command"
        input_schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    
    return Tool(
        name=tool_name,
        description=description,
        inputSchema=input_schema
    )


def register_plugin_tools(server: Server):
    """
    Register all discovered plugin tools with the MCP server.
    
    Uses a backward-compatible fallback approach:
    1. Try --describe command first (new structured method)
    2. Fall back to help text scraping (old method for compatibility)
    """
    global plugin_registry
    
    # Discover plugins
    plugin_registry = discover_plugins()
    
    # Collect all tools
    all_tools = []
    
    # Create tools for each plugin
    for plugin_name, plugin_info in plugin_registry.items():
        cli_path = plugin_info["path"]
        
        # Try --describe first (new method)
        plugin_spec = get_plugin_describe(plugin_name, cli_path)
        
        if plugin_spec:
            # New method: use structured --describe output
            logger.info(f"Plugin {plugin_name}: Using --describe method for discovery")
            
            commands = plugin_spec.get("commands", [])
            for command_spec in commands:
                command_name = command_spec.get("name")
                if not command_name:
                    logger.warning(f"Plugin {plugin_name}: Skipping command with no name")
                    continue
                
                # Skip redundant connect/disconnect commands (all commands auto-connect)
                if command_name in ["connect", "disconnect"]:
                    if logger.level <= logging.INFO:
                        logger.info(f"Plugin {plugin_name}: Skipping redundant '{command_name}' command (use auto-connect instead)")
                    continue
                
                # Create tool with full spec
                tool = create_tool_from_plugin(plugin_name, command_name, command_spec)
                all_tools.append(tool)
                
                logger.info(f"Created tool: {tool.name} (with parameter schema)")
                metrics["tools_registered"] += 1
        else:
            # Fallback: use help text scraping (old method)
            logger.info(f"Plugin {plugin_name}: Using help scraping fallback (--describe not supported)")
            
            help_text = get_plugin_help(plugin_name, cli_path)
            commands = parse_commands_from_help(help_text)
            
            if not commands:
                logger.warning(f"Plugin {plugin_name}: No commands discovered via help scraping")
                continue
            
            for command in commands:
                # Create tool without spec (empty schema)
                tool = create_tool_from_plugin(plugin_name, command, None)
                all_tools.append(tool)
                
                logger.info(f"Created tool: {tool.name} (fallback method, no parameter schema)")
                metrics["tools_registered"] += 1
    
    # Register the list_tools handler
    @server.list_tools()
    async def list_tools_handler():
        """Return the list of available tools."""
        # Suppress verbose logging in STDIO mode to avoid blocking
        # Just return the tools immediately
        return all_tools
    
    # Register the call_tool handler
    @server.call_tool()
    async def call_tool_handler(tool_name: str, arguments: dict):
        """Handle tool calls."""
        # Suppress verbose logging in STDIO mode
        if logger.level <= logging.INFO:
            logger.info(f"Tool call: {tool_name} with args: {arguments}")
        metrics["tool_calls_total"] += 1
        try:
            result = await execute_plugin_tool(tool_name, arguments)
            if logger.level <= logging.INFO:
                logger.info(f"Tool result: {result[:200]}...")  # Truncate long results
            return [TextContent(type="text", text=str(result))]
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            metrics["tool_calls_error"] += 1
            return [TextContent(type="text", text=error_msg)]


def create_server(host: str, port: int) -> Server:
    """Create and configure the MCP server instance."""
    # Create base MCP server (not FastMCP)
    server = Server(name="sanctum-letta-mcp", version="1.0.0")
    
    return server


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Sanctum Letta MCP Server - Base MCP implementation with SSE transport",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python smcp.py                    # Run with localhost-only (secure default)
  python smcp.py --host 127.0.0.1   # Localhost-only (explicit)
  python smcp.py --allow-external   # Allow external connections
  python smcp.py --port 9000        # Run on custom port
        """
    )
    
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Allow external connections (default: localhost-only for security)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Port to run the server on (default: 8000 or MCP_PORT env var)"
    )
    
    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Host to bind to (default: 127.0.0.1 or MCP_HOST env var)"
    )
    
    return parser.parse_args()


async def async_main():
    """Main entry point."""
    args = parse_arguments()
    
    # Determine host binding
    if args.allow_external:
        host = "0.0.0.0"
        logger.warning("⚠️  WARNING: External connections are allowed. This may pose security risks.")
    else:
        host = args.host
        if host == "127.0.0.1":
            logger.info("🔒 Security: Server bound to localhost only. Use --allow-external for network access.")
    
    logger.info(f"Starting Sanctum Letta MCP Server on {host}:{args.port}...")
    
    # Create MCP server
    global server
    server = create_server(host, args.port)
    
    # Register plugin tools
    register_plugin_tools(server)
    
    # Create SSE transport
    sse_transport = SseServerTransport("/messages/")
    
    # Create Starlette app with SSE endpoints
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import Response
    
    async def sse_endpoint(request):
        """SSE connection endpoint."""
        # Use SSE transport's connect_sse method with proper streams
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            # Run the MCP server with the SSE streams
            await server.run(
                streams[0],  # read_stream
                streams[1],  # write_stream
                server.create_initialization_options()
            )
        # Return empty response to avoid NoneType error
        return Response()
    
    async def sse_post_endpoint(request):
        """Handle POST requests to /sse (for Letta compatibility)."""
        # Create a simple response for POST requests to /sse
        # This handles Letta's incorrect POST to /sse instead of /messages/
        try:
            # Try to parse the request body as JSON
            body = await request.body()
            if body:
                # If there's a body, it's likely a JSON-RPC message
                # Return a helpful error message
                return Response(
                    "POST requests to /sse should be sent to /messages/ instead. "
                    "Use GET /sse to establish SSE connection, then POST to /messages/ to send messages.",
                    status_code=400,
                    media_type="text/plain"
                )
            else:
                # Empty POST request
                return Response("Empty POST request", status_code=400)
        except Exception as e:
            return Response(f"Error processing request: {str(e)}", status_code=500)
    
    # Create Starlette app
    app = Starlette(routes=[
        Route("/sse", sse_endpoint, methods=["GET"]),
        Route("/sse", sse_post_endpoint, methods=["POST"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ])
    
    # Start server with proper signal handling
    logger.info("Starting server with SSE transport...")
    import uvicorn
    import signal
    
    # Create server config
    config = uvicorn.Config(
        app,
        host=host,
        port=args.port,
        log_level="info"
    )
    
    # Create server instance
    server_instance = uvicorn.Server(config)
    
    # Handle shutdown signals
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        server_instance.should_exit = True
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start server
    await server_instance.serve()


def main():
    """Synchronous entry point for console script."""
    asyncio.run(async_main())


if __name__ == "__main__":
    asyncio.run(async_main())
