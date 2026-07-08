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
import hmac
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

import governor

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


def _load_letta_dotenv() -> None:
    """
    If LETTA_SERVER_URL or LETTA_SERVER_PASSWORD are not already set, try to load them
    from ~/.letta/.env (same file Letta uses on the server). Sets default LETTA_SERVER_URL
    to http://127.0.0.1:8284 when we have password but no URL.
    """
    want = {"LETTA_SERVER_URL", "LETTA_SERVER_PASSWORD", "LETTA_API_KEY"}
    if all(os.getenv(k) for k in ("LETTA_SERVER_URL", "LETTA_SERVER_PASSWORD")):
        return
    if os.getenv("LETTA_SERVER_PASSWORD") or os.getenv("LETTA_API_KEY"):
        if os.getenv("LETTA_SERVER_URL"):
            return
    env_file = Path(os.path.expanduser("~")) / ".letta" / ".env"
    if not env_file.is_file():
        return
    try:
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("export "):
                continue
            rest = line[7:].strip()
            if "=" not in rest:
                continue
            key, _, value = rest.partition("=")
            key = key.strip()
            if key not in want or key in os.environ:
                continue
            value = value.strip().strip('"').strip("'")
            os.environ[key] = value
        if (os.getenv("LETTA_SERVER_PASSWORD") or os.getenv("LETTA_API_KEY")) and not os.getenv("LETTA_SERVER_URL"):
            os.environ["LETTA_SERVER_URL"] = "http://127.0.0.1:8284"
    except Exception as e:
        logger.debug(f"Could not load ~/.letta/.env: {e}")


def load_letta_env_vars() -> None:
    """
    On startup, optionally fetch agent environment variables (secrets) from the Letta API
    and set them in this process's environment. Plugin subprocesses will then inherit them.

    Uses LETTA_SERVER_URL and LETTA_SERVER_PASSWORD (or LETTA_API_KEY). If not set in the
    environment, tries ~/.letta/.env (same file Letta uses). Default URL is http://127.0.0.1:8284.
    Optionally set LETTA_AGENT_ID to load only that agent's vars; otherwise all agents' vars
    are merged (later agent wins on key collision).
    """
    _load_letta_dotenv()
    base_url = (os.getenv("LETTA_SERVER_URL") or "").strip().rstrip("/")
    password = (os.getenv("LETTA_SERVER_PASSWORD") or os.getenv("LETTA_API_KEY") or "").strip()
    agent_id = (os.getenv("LETTA_AGENT_ID") or "").strip() or None

    if not base_url or not password:
        return

    merged: Dict[str, str] = {}
    try:
        if agent_id:
            url = f"{base_url}/v1/agents/{agent_id}?include=agent.secrets"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {password}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            agents = [data] if isinstance(data, dict) and data.get("id") else []
        else:
            url = f"{base_url}/v1/agents?limit=100&include=agent.secrets"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {password}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                agents = json.loads(resp.read().decode())
        if not isinstance(agents, list):
            agents = []

        for agent in agents:
            for env_list_name in ("tool_exec_environment_variables", "secrets"):
                env_list = agent.get(env_list_name)
                if not isinstance(env_list, list):
                    continue
                for item in env_list:
                    if isinstance(item, dict) and "key" in item:
                        key = (item.get("key") or "").strip()
                        value = item.get("value")
                        if key:
                            merged[key] = value if value is not None else ""

        if merged:
            os.environ.update(merged)
            logger.info(f"Loaded {len(merged)} env var(s) from Letta: {list(merged.keys())}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning(f"Letta env vars: HTTP {e.code} - {body[:200]}")
    except Exception as e:
        logger.warning(f"Letta env vars: {e}")


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


def _coalesce_tool_argument_aliases(arguments: dict) -> dict:
    """Letta/models often send hyphenated JSON keys; plugins use argparse dest with underscores."""
    if not isinstance(arguments, dict):
        return arguments
    out = dict(arguments)
    if "payload_json" in out and "payload-json" in out:
        del out["payload-json"]
    elif "payload-json" in out and "payload_json" not in out:
        out["payload_json"] = out.pop("payload-json")
    if "catering_invoice_id" in out and "catering-invoice-id" in out:
        del out["catering-invoice-id"]
    elif "catering-invoice-id" in out and "catering_invoice_id" not in out:
        out["catering_invoice_id"] = out.pop("catering-invoice-id")
    if "invoice_command" in out and "invoice-command" in out:
        del out["invoice-command"]
    elif "invoice-command" in out and "invoice_command" not in out:
        out["invoice_command"] = out.pop("invoice-command")
    return out


_FLAG_STYLE_ACTIONS = frozenset({"store_true", "store_false"})


def _command_param_specs(plugin_name: str, command: str) -> Dict[str, Dict[str, Any]]:
    """Return this command's parameter specs keyed by normalized (hyphenated) name.

    Reads the cached --describe spec from plugin_registry. Returns an empty dict
    when the plugin/command was discovered without a structured spec (e.g. the
    help-scraping fallback), in which case callers use safe defaults.
    """
    plugin_info = plugin_registry.get(plugin_name) or {}
    commands = plugin_info.get("commands") or {}
    spec = commands.get(command) or {}
    out: Dict[str, Dict[str, Any]] = {}
    for param in spec.get("parameters", []) or []:
        name = str(param.get("name", "")).replace("_", "-")
        if name:
            out[name] = param
    return out


def _arg_declared_type(param_spec: Optional[Dict[str, Any]]) -> str:
    """Return the lowercased declared JSON ``type`` for a parameter (``""`` if unknown).

    Read from the plugin's cached ``--describe`` spec. Drives schema-aware
    serialization of structured (array/object) arguments (issue #56).
    """
    if not param_spec:
        return ""
    return str(param_spec.get("type", "")).strip().lower()


def _unwrap_item_array(value: Any) -> list:
    """Coerce Letta's single-child ``{"item": X}`` array encoding into a real list.

    Letta/XML tool-argument serialization commonly renders a one-element array as
    an object ``{"item": {...}}`` (or ``{"item": [...]}``). For a parameter the
    plugin declares as an array, normalize that back to a list so plugins receive
    clean JSON and don't each have to reinvent this unwrap (issue #56):

    - a real list passes through unchanged;
    - ``{"item": [...]}`` -> the inner list;
    - ``{"item": {...}}`` -> ``[{...}]``;
    - any other dict/scalar -> a single-element list.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if set(value.keys()) == {"item"}:
            inner = value["item"]
            return inner if isinstance(inner, list) else [inner]
        return [value]
    return [value]


def _render_tool_argument(
    arg_name: str, value: Any, param_spec: Optional[Dict[str, Any]]
) -> List[str]:
    """Render one tool argument to argv fragments, schema-aware (issues #37/#38/#56).

    - ``bool`` -> flag-style (bare ``--name`` when true) or ``--name true|false``
      per the plugin's ``--describe`` declaration.
    - declared ``array`` -> a single ``--name <json>`` after normalizing Letta's
      ``{"item": ...}`` wrappers; a ``str`` value is passed through untouched
      (already-serialized JSON).
    - declared ``object`` or a ``dict`` value -> a single ``--name <json>``.
    - an untyped ``list`` -> a single ``--name <json>`` when it holds structured
      items (dict/list), otherwise repeated ``--name value`` for scalar lists
      (backward-compatible with argparse ``nargs``).
    - anything else -> ``--name str(value)``.
    """
    declared = _arg_declared_type(param_spec)
    if isinstance(value, bool):
        if _boolean_is_flag_style(param_spec):
            return [f"--{arg_name}"] if value else []
        return [f"--{arg_name}", "true" if value else "false"]
    if declared == "array":
        # Already-serialized JSON string: pass through untouched.
        if isinstance(value, str):
            return [f"--{arg_name}", value]
        # Normalize Letta's single-child {"item": ...} wrapper to a real list.
        value = _unwrap_item_array(value)
    if declared == "object":
        if isinstance(value, (dict, list)):
            return [f"--{arg_name}", json.dumps(value, separators=(',', ':'))]
        return [f"--{arg_name}", str(value)]
    if isinstance(value, dict):
        # Letta/MCP often pass objects; plugins expect JSON on argv (not Python repr).
        return [f"--{arg_name}", json.dumps(value, separators=(',', ':'))]
    if isinstance(value, list):
        # Decide by content: arrays of structured items must be valid JSON;
        # scalar arrays render as repeated flags (argparse nargs / action=append).
        if any(isinstance(item, (dict, list)) for item in value):
            return [f"--{arg_name}", json.dumps(value, separators=(',', ':'))]
        fragment: List[str] = []
        for item in value:
            fragment.extend([f"--{arg_name}", str(item)])
        return fragment
    return [f"--{arg_name}", str(value)]


def _boolean_is_flag_style(param_spec: Optional[Dict[str, Any]]) -> bool:
    """Decide how a boolean argument should be rendered on argv.

    Flag-style (bare ``--name`` only when true; issue #38) when the plugin
    declares an argparse ``store_true``/``store_false`` action (or the
    ``arg_style: flag`` / ``takes_value: false`` aliases). Otherwise value-style
    (``--name true|false``; issue #37), which is also the default when the
    parameter makes no declaration.
    """
    if not param_spec:
        return False
    action = str(param_spec.get("action", "")).strip().lower()
    if action in _FLAG_STYLE_ACTIONS:
        return True
    arg_style = str(param_spec.get("arg_style", "")).strip().lower()
    if arg_style == "flag":
        return True
    if arg_style == "value":
        return False
    if param_spec.get("takes_value") is False:
        return True
    return False


def _resolve_plugin_timeout() -> Optional[float]:
    """Resolve the plugin execution timeout in seconds (issue #41).

    Reads MCP_PLUGIN_TIMEOUT (set directly or from the --plugin-timeout CLI flag).
    Unset, empty, ``0``, negative, or unparseable => ``None`` (no timeout), the
    default, so long-running plugin operations are not cut off.
    """
    raw = os.getenv("MCP_PLUGIN_TIMEOUT")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid MCP_PLUGIN_TIMEOUT=%r; running with no timeout.", raw)
        return None
    if value <= 0:
        return None
    return value


async def _terminate_process(process, grace: float = 5.0) -> None:
    """Terminate a still-running subprocess: SIGTERM, then SIGKILL after a grace.

    No-op when the process already exited. Used to guarantee we never orphan a
    plugin child on cancellation, timeout, or unexpected errors (issue #18).
    """
    if process is None or process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    except Exception:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=grace)
        return
    except asyncio.TimeoutError:
        pass
    except Exception:
        return
    try:
        process.kill()
        await process.wait()
    except Exception:
        pass


async def execute_plugin_tool(tool_name: str, arguments: dict) -> str:
    """Execute a plugin tool with the given arguments."""
    try:
        arguments = _coalesce_tool_argument_aliases(arguments)
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

        # Per-command parameter specs (from --describe) drive schema-aware
        # boolean rendering; empty for help-scraped/legacy plugins.
        param_specs = _command_param_specs(plugin_name, command)

        # Add arguments
        # Convert underscores to dashes for command-line arguments (standard convention)
        for key, value in arguments.items():
            if value is None:
                continue
            # Convert parameter name (use_ssl) to CLI argument (--use-ssl)
            arg_name = key.replace('_', '-')
            # Schema-aware rendering (booleans #37/#38; arrays/objects #56).
            cmd_args.extend(
                _render_tool_argument(arg_name, value, param_specs.get(arg_name))
            )
        
        # Suppress verbose logging in STDIO mode
        if logger.level <= logging.INFO:
            logger.info(f"Executing plugin command: {' '.join(cmd_args)}")
        
        # Execute the command with an operator-configurable timeout (issue #41).
        # Default is no timeout (None) so long-running plugin operations are not
        # cut off; set MCP_PLUGIN_TIMEOUT or --plugin-timeout to enforce one.
        timeout_seconds = _resolve_plugin_timeout()
        
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
                if timeout_seconds is None:
                    stdout, stderr = await read_output()
                else:
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
            await _terminate_process(process)
            error_msg = f"Plugin command timed out after {timeout_seconds} seconds"
            metrics["tool_calls_error"] += 1
            return error_msg
        except asyncio.CancelledError:
            # Client disconnected / request cancelled — never orphan the child (#18).
            await _terminate_process(process)
            metrics["tool_calls_error"] += 1
            raise
        finally:
            # Belt-and-suspenders: any exit path leaves no running subprocess (#18).
            await _terminate_process(process)
        
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

                # Cache the command spec so execute_plugin_tool can render
                # arguments (notably booleans) per the plugin's declaration.
                plugin_info.setdefault("commands", {})[command_name] = command_spec

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
    
    governor.set_catalog(t.name for t in all_tools)
    all_tools.append(governor.governor_tool())

    # Register the list_tools handler
    @server.list_tools()
    async def list_tools_handler():
        """Return attached tools (+ governor)."""
        return governor.filter_tools(all_tools)

    # Register the call_tool handler
    @server.call_tool()
    async def call_tool_handler(tool_name: str, arguments: dict):
        """Handle tool calls."""
        if logger.level <= logging.INFO:
            logger.info(f"Tool call: {tool_name} with args: {arguments}")
        metrics["tool_calls_total"] += 1
        if tool_name == governor.GOVERNOR_TOOL_NAME:
            return [TextContent(type="text", text=governor.handle_governor(arguments))]
        blocked = governor.gate_tool_call(tool_name)
        if blocked is not None:
            metrics["tool_calls_error"] += 1
            return [TextContent(type="text", text=blocked)]
        try:
            result = await execute_plugin_tool(tool_name, arguments)
            if logger.level <= logging.INFO:
                logger.info(f"Tool result: {result[:200]}...")
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
        "--require-auth",
        action="store_true",
        help="Require the API key even for loopback clients (equivalent to MCP_AUTH_ALLOW_LOOPBACK=0)"
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

    parser.add_argument(
        "--plugin-timeout",
        type=float,
        default=None,
        help="Seconds before a plugin subprocess is terminated (default: no timeout; "
             "also settable via MCP_PLUGIN_TIMEOUT). 0 or negative means no timeout."
    )
    
    return parser.parse_args()


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class AuthConfig:
    """Resolved authentication settings for the HTTP transport."""
    keys: frozenset
    allow_loopback: bool
    disabled: bool

    @property
    def enforce(self) -> bool:
        """True when the middleware should actually check credentials."""
        return (not self.disabled) and bool(self.keys)


def _env_truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_auth_config(require_auth: bool = False) -> AuthConfig:
    """
    Read authentication settings from the environment.

    - MCP_API_KEY / MCP_API_KEYS (comma-separated) define accepted keys.
    - MCP_AUTH_DISABLED explicitly turns auth (and the external-bind guard) off.
    - MCP_AUTH_ALLOW_LOOPBACK (default on) lets loopback clients skip the key;
      --require-auth (require_auth=True) forces it off.
    """
    disabled = _env_truthy(os.getenv("MCP_AUTH_DISABLED"))

    raw_keys: List[str] = []
    single = (os.getenv("MCP_API_KEY") or "").strip()
    if single:
        raw_keys.append(single)
    for part in (os.getenv("MCP_API_KEYS") or "").split(","):
        part = part.strip()
        if part:
            raw_keys.append(part)
    keys = frozenset(raw_keys)

    allow_loopback = True
    if os.getenv("MCP_AUTH_ALLOW_LOOPBACK") is not None:
        allow_loopback = _env_truthy(os.getenv("MCP_AUTH_ALLOW_LOOPBACK"))
    if require_auth:
        allow_loopback = False

    return AuthConfig(keys=keys, allow_loopback=allow_loopback, disabled=disabled)


def _extract_presented_key(headers: Dict[str, str]) -> Optional[str]:
    """
    Pull the presented credential from request headers (lower-cased keys).

    Accepts 'Authorization: Bearer <key>' (primary) or 'X-API-Key: <key>'.
    """
    auth = headers.get("authorization")
    if auth:
        prefix, _, token = auth.partition(" ")
        if prefix.lower() == "bearer" and token.strip():
            return token.strip()
    api_key = headers.get("x-api-key")
    if api_key and api_key.strip():
        return api_key.strip()
    return None


def is_authorized(headers: Dict[str, str], client_host: str, cfg: AuthConfig) -> bool:
    """Decide whether a request may proceed under the given AuthConfig."""
    if not cfg.enforce:
        return True
    if cfg.allow_loopback and client_host in _LOOPBACK_HOSTS:
        return True
    presented = _extract_presented_key(headers)
    if not presented:
        return False
    # Constant-time comparison against every configured key.
    authorized = False
    for key in cfg.keys:
        if hmac.compare_digest(presented, key):
            authorized = True
    return authorized


class AuthMiddleware:
    """
    Raw ASGI middleware that guards the HTTP transport.

    Implemented at the ASGI level (not Starlette BaseHTTPMiddleware) so the
    long-lived SSE response stream is never buffered.
    """

    def __init__(self, app, cfg: AuthConfig):
        self.app = app
        self.cfg = cfg

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not self.cfg.enforce:
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        client = scope.get("client")
        client_host = client[0] if client else ""

        if is_authorized(headers, client_host, self.cfg):
            await self.app(scope, receive, send)
            return

        body = b'{"error":"unauthorized"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


def resolve_host(args) -> str:
    """
    Determine the bind host from parsed arguments.

    --allow-external binds 0.0.0.0 (with a warning); otherwise the explicit
    --host value is used (default 127.0.0.1, localhost-only).
    """
    if args.allow_external:
        logger.warning("⚠️  WARNING: External connections are allowed. This may pose security risks.")
        return "0.0.0.0"
    host = args.host
    if host == "127.0.0.1":
        logger.info("🔒 Security: Server bound to localhost only. Use --allow-external for network access.")
    return host


def build_app(sse_transport, auth_config: Optional[AuthConfig] = None):
    """
    Build the Starlette ASGI app that exposes the MCP SSE transport.

    Routes:
      GET  /sse        -> establish SSE stream and run the MCP server over it
      POST /sse        -> Letta-compat shim (messages belong on /messages/)
      /messages/*      -> SSE transport POST handler (JSON-RPC ingress)

    When auth_config enforces credentials, the app is wrapped in AuthMiddleware
    so every HTTP request is checked before it reaches a route.
    """
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

    app = Starlette(routes=[
        Route("/sse", sse_endpoint, methods=["GET"]),
        Route("/sse", sse_post_endpoint, methods=["POST"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ])

    if auth_config is not None and auth_config.enforce:
        return AuthMiddleware(app, auth_config)
    return app


async def async_main():
    """Main entry point."""
    load_letta_env_vars()
    args = parse_arguments()

    # --plugin-timeout takes precedence over the environment for this process.
    if getattr(args, "plugin_timeout", None) is not None:
        os.environ["MCP_PLUGIN_TIMEOUT"] = str(args.plugin_timeout)

    # Determine host binding
    host = resolve_host(args)

    # Resolve authentication and fail closed on an unauthenticated external bind
    auth_config = resolve_auth_config(require_auth=getattr(args, "require_auth", False))
    if host == "0.0.0.0" and not auth_config.enforce and not auth_config.disabled:
        logger.critical(
            "Refusing to bind externally (0.0.0.0) without authentication. "
            "Set MCP_API_KEY (or MCP_API_KEYS) to require a key, or set "
            "MCP_AUTH_DISABLED=1 to explicitly run open (not recommended)."
        )
        sys.exit(2)
    if auth_config.disabled and host == "0.0.0.0":
        logger.warning("⚠️  Auth is DISABLED (MCP_AUTH_DISABLED) while bound externally — server is open.")
    elif auth_config.enforce:
        logger.info(
            "🔐 API-key authentication enabled (%d key(s); loopback %s).",
            len(auth_config.keys),
            "allowed" if auth_config.allow_loopback else "also required",
        )

    logger.info(f"Starting Sanctum Letta MCP Server on {host}:{args.port}...")
    
    # Create MCP server
    global server
    server = create_server(host, args.port)
    
    # Register plugin tools
    register_plugin_tools(server)
    
    # Create SSE transport
    sse_transport = SseServerTransport("/messages/")
    
    # Create Starlette app with SSE endpoints
    app = build_app(sse_transport, auth_config)
    
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
