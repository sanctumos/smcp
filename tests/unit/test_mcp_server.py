"""
Unit tests for MCP server core functionality.
Tests plugin discovery, tool execution, and server components.
"""

import json
import pytest
import subprocess
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import sys
import os

# Import functions directly from smcp.py since they're not exported from the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Import the functions we want to test from smcp.py directly
import importlib.util
spec = importlib.util.spec_from_file_location("smcp_module", "smcp.py")
smcp_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smcp_module)

# Import the functions we want to test
discover_plugins = smcp_module.discover_plugins
get_plugin_help = smcp_module.get_plugin_help
get_plugin_describe = smcp_module.get_plugin_describe
parse_commands_from_help = smcp_module.parse_commands_from_help
parameter_spec_to_json_schema = smcp_module.parameter_spec_to_json_schema
execute_plugin_tool = smcp_module.execute_plugin_tool
create_tool_from_plugin = smcp_module.create_tool_from_plugin
register_plugin_tools = smcp_module.register_plugin_tools
plugin_registry = smcp_module.plugin_registry


@pytest.mark.unit
class TestPluginDiscovery:
    """Test plugin discovery functionality."""
    
    def test_discover_plugins_with_env_var(self, tmp_path):
        """Test plugin discovery with MCP_PLUGINS_DIR environment variable."""
        # Create test plugins directory
        plugins_dir = tmp_path / "test_plugins"
        plugins_dir.mkdir()
        
        # Create a mock plugin
        plugin_dir = plugins_dir / "test_plugin"
        plugin_dir.mkdir()
        cli_file = plugin_dir / "cli.py"
        cli_file.write_text("# Test plugin")
        
        with patch.dict(os.environ, {"MCP_PLUGINS_DIR": str(plugins_dir)}):
            plugins = discover_plugins()
            
        assert "test_plugin" in plugins
        assert plugins["test_plugin"]["path"] == str(cli_file)
        assert "commands" in plugins["test_plugin"]
    
    def test_discover_plugins_default_path(self, tmp_path):
        """Test plugin discovery with default path."""
        # Set environment variable to use our test directory
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        
        # Create a mock plugin
        plugin_dir = plugins_dir / "test_plugin"
        plugin_dir.mkdir()
        cli_file = plugin_dir / "cli.py"
        cli_file.write_text("# Test plugin")
        
        with patch.dict(os.environ, {"MCP_PLUGINS_DIR": str(plugins_dir)}):
            plugins = discover_plugins()
            
        assert "test_plugin" in plugins
        assert plugins["test_plugin"]["path"] == str(cli_file)
    
    def test_discover_plugins_nonexistent_directory(self):
        """Test plugin discovery with nonexistent directory."""
        with patch.dict(os.environ, {"MCP_PLUGINS_DIR": "/nonexistent/path"}):
            plugins = discover_plugins()
            
        assert plugins == {}
    
    def test_discover_plugins_empty_directory(self, tmp_path):
        """Test plugin discovery with empty directory."""
        plugins_dir = tmp_path / "empty_plugins"
        plugins_dir.mkdir()
        
        with patch.dict(os.environ, {"MCP_PLUGINS_DIR": str(plugins_dir)}):
            plugins = discover_plugins()
            
        assert plugins == {}
    
    def test_discover_plugins_missing_cli_file(self, tmp_path):
        """Test plugin discovery with directory missing cli.py."""
        plugins_dir = tmp_path / "test_plugins"
        plugins_dir.mkdir()
        
        # Create plugin directory without cli.py
        plugin_dir = plugins_dir / "test_plugin"
        plugin_dir.mkdir()
        
        with patch.dict(os.environ, {"MCP_PLUGINS_DIR": str(plugins_dir)}):
            plugins = discover_plugins()
            
        assert plugins == {}


@pytest.mark.unit
class TestPluginHelp:
    """Test plugin help functionality."""
    
    @patch("subprocess.run")
    def test_get_plugin_help_success(self, mock_run):
        """Test successful plugin help retrieval."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Available commands:\n  test-command\n  another-command"
        mock_run.return_value = mock_result
        
        help_text = get_plugin_help("test_plugin", "/path/to/cli.py")
        
        assert help_text == "Available commands:\n  test-command\n  another-command"
        mock_run.assert_called_once_with(
            [sys.executable, "/path/to/cli.py", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
    
    @patch.object(smcp_module, "subprocess")
    def test_get_plugin_help_failure(self, mock_run):
        """Test plugin help retrieval failure."""
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Command failed"
        
        help_text = get_plugin_help("test_plugin", "/path/to/cli.py")
        
        assert help_text == ""
    
    @patch.object(smcp_module, "subprocess")
    def test_get_plugin_help_timeout(self, mock_run):
        """Test plugin help retrieval timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)
        
        help_text = get_plugin_help("test_plugin", "/path/to/cli.py")
        
        assert help_text == ""


@pytest.mark.unit
class TestToolExecution:
    """Test tool execution functionality."""
    
    @pytest.fixture
    def mock_ctx(self):
        """Create a mock context for testing."""
        ctx = AsyncMock()
        ctx.info = AsyncMock()
        ctx.error = AsyncMock()
        return ctx
    
    @patch("asyncio.create_subprocess_exec")
    async def test_execute_plugin_tool_success(self, mock_create_subprocess):
        """Test successful tool execution."""
        # Mock subprocess
        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(return_value=(b"Success output", b""))
        mock_process.returncode = 0
        mock_create_subprocess.return_value = mock_process
        
        # Mock plugin registry
        with patch.object(smcp_module, "plugin_registry", {"test_plugin": {"path": "/path/to/cli.py"}}):
            result = await execute_plugin_tool("test_plugin.test_command", {"arg1": "value1"})
        
        assert result == "Success output"
        mock_create_subprocess.assert_called_once()
    
    @patch("asyncio.create_subprocess_exec")
    async def test_execute_plugin_tool_failure(self, mock_create_subprocess):
        """Test tool execution failure."""
        # Mock subprocess
        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(return_value=(b"", b"Error output"))
        mock_process.returncode = 1
        mock_create_subprocess.return_value = mock_process
        
        # Mock plugin registry
        with patch.object(smcp_module, "plugin_registry", {"test_plugin": {"path": "/path/to/cli.py"}}):
            result = await execute_plugin_tool("test_plugin.test_command", {"arg1": "value1"})
        
        assert result == "Error: Error output"
        mock_create_subprocess.assert_called_once()
    
    async def test_execute_plugin_tool_invalid_name(self):
        """Test tool execution with invalid tool name."""
        result = await execute_plugin_tool("invalid_tool_name", {})
        
        assert "Invalid tool name format" in result
    
    async def test_execute_plugin_tool_nonexistent_plugin(self):
        """Test tool execution with nonexistent plugin."""
        with patch.object(smcp_module, "plugin_registry", {}):
            result = await execute_plugin_tool("nonexistent_plugin.command", {})
        
        assert "Plugin 'nonexistent_plugin' not found" in result
    
    @patch.object(smcp_module, "asyncio")
    async def test_execute_plugin_tool_exception(self, mock_subprocess):
        """Test tool execution with exception."""
        mock_subprocess.side_effect = Exception("Subprocess error")
        
        with patch.object(smcp_module, "plugin_registry", {"test_plugin": {"path": "/path/to/cli.py"}}):
            result = await execute_plugin_tool("test_plugin.test_command", {})
        
        assert "Error executing tool" in result


@pytest.mark.unit
class TestPluginDescribe:
    """Test plugin --describe functionality."""
    
    @patch("subprocess.run")
    def test_get_plugin_describe_success(self, mock_run):
        """Test successful plugin describe retrieval."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "plugin": {"name": "test_plugin", "version": "1.0.0"},
            "commands": [
                {
                    "name": "test-command",
                    "description": "Test command",
                    "parameters": []
                }
            ]
        })
        mock_run.return_value = mock_result
        
        spec = get_plugin_describe("test_plugin", "/path/to/cli.py")
        
        assert spec is not None
        assert "commands" in spec
        assert len(spec["commands"]) == 1
        assert spec["commands"][0]["name"] == "test-command"
        mock_run.assert_called_once_with(
            [sys.executable, "/path/to/cli.py", "--describe"],
            capture_output=True,
            text=True,
            timeout=10
        )
    
    @patch("subprocess.run")
    def test_get_plugin_describe_not_supported(self, mock_run):
        """Test plugin without --describe support."""
        mock_result = MagicMock()
        mock_result.returncode = 1  # Command fails
        mock_run.return_value = mock_result
        
        spec = get_plugin_describe("test_plugin", "/path/to/cli.py")
        
        assert spec is None
    
    @patch("subprocess.run")
    def test_get_plugin_describe_invalid_json(self, mock_run):
        """Test plugin describe with invalid JSON."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"
        mock_run.return_value = mock_result
        
        spec = get_plugin_describe("test_plugin", "/path/to/cli.py")
        
        assert spec is None
    
    @patch("subprocess.run")
    def test_get_plugin_describe_invalid_structure(self, mock_run):
        """Test plugin describe with invalid structure."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"invalid": "structure"})
        mock_run.return_value = mock_result
        
        spec = get_plugin_describe("test_plugin", "/path/to/cli.py")
        
        assert spec is None
    
    @patch("subprocess.run")
    def test_get_plugin_describe_timeout(self, mock_run):
        """Test plugin describe timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)
        
        spec = get_plugin_describe("test_plugin", "/path/to/cli.py")
        
        assert spec is None
    
    @patch("subprocess.run")
    def test_get_plugin_describe_exception(self, mock_run):
        """Test plugin describe with exception."""
        mock_run.side_effect = Exception("Unexpected error")
        
        spec = get_plugin_describe("test_plugin", "/path/to/cli.py")
        
        assert spec is None


@pytest.mark.unit
class TestParseCommandsFromHelp:
    """Test parsing commands from help text."""
    
    def test_parse_commands_from_help_success(self):
        """Test successful command parsing."""
        help_text = """usage: cli.py [-h] {command1,command2} ...

Plugin description

Available commands:
  command1    First command
  command2    Second command

Examples:
  python cli.py command1 --arg value
"""
        commands = parse_commands_from_help(help_text)
        
        assert "command1" in commands
        assert "command2" in commands
        assert len(commands) == 2
    
    def test_parse_commands_from_help_no_section(self):
        """Test parsing with no Available commands section."""
        help_text = "Just some help text without commands"
        commands = parse_commands_from_help(help_text)
        
        assert commands == []
    
    def test_parse_commands_from_help_empty_section(self):
        """Test parsing with empty commands section."""
        help_text = """Available commands:

Examples:
"""
        commands = parse_commands_from_help(help_text)
        
        assert commands == []
    
    def test_parse_commands_from_help_with_filtered_words(self):
        """Test parsing ignores filtered words."""
        help_text = """Available commands:
  usage:     Should be ignored
  options:   Should be ignored
  command1   Valid command
  Examples:  Should be ignored
"""
        commands = parse_commands_from_help(help_text)
        
        assert "command1" in commands
        assert len(commands) == 1
    
    def test_parse_commands_from_help_stops_at_examples(self):
        """Test parsing stops at Examples section."""
        help_text = """Available commands:
  command1   First command
  command2   Second command

Examples:
  command3   Should be ignored
"""
        commands = parse_commands_from_help(help_text)
        
        assert "command1" in commands
        assert "command2" in commands
        assert "command3" not in commands
        assert len(commands) == 2


@pytest.mark.unit
class TestParameterSpecToJsonSchema:
    """Test parameter spec to JSON Schema conversion."""
    
    def test_parameter_spec_to_json_schema_basic(self):
        """Test basic parameter schema conversion."""
        parameters = [
            {
                "name": "text",
                "type": "string",
                "description": "Text input",
                "required": True,
                "default": None
            }
        ]
        
        schema = parameter_spec_to_json_schema(parameters)
        
        assert schema["type"] == "object"
        assert "text" in schema["properties"]
        assert schema["properties"]["text"]["type"] == "string"
        assert schema["properties"]["text"]["description"] == "Text input"
        assert "text" in schema["required"]
    
    def test_parameter_spec_to_json_schema_optional(self):
        """Test optional parameter schema conversion."""
        parameters = [
            {
                "name": "optional_param",
                "type": "string",
                "description": "Optional parameter",
                "required": False,
                "default": "default_value"
            }
        ]
        
        schema = parameter_spec_to_json_schema(parameters)
        
        assert "optional_param" in schema["properties"]
        assert "optional_param" not in schema["required"]
        assert schema["properties"]["optional_param"]["default"] == "default_value"
    
    def test_parameter_spec_to_json_schema_multiple_types(self):
        """Test schema conversion with multiple parameter types."""
        parameters = [
            {"name": "text", "type": "string", "required": True},
            {"name": "number", "type": "number", "required": True},
            {"name": "integer", "type": "integer", "required": True},
            {"name": "flag", "type": "boolean", "required": False},
        ]
        
        schema = parameter_spec_to_json_schema(parameters)
        
        assert schema["properties"]["text"]["type"] == "string"
        assert schema["properties"]["number"]["type"] == "number"
        assert schema["properties"]["integer"]["type"] == "integer"
        assert schema["properties"]["flag"]["type"] == "boolean"
    
    def test_parameter_spec_to_json_schema_array(self):
        """Test schema conversion with array type."""
        parameters = [
            {
                "name": "items",
                "type": "array",
                "description": "List of items",
                "required": True
            }
        ]
        
        schema = parameter_spec_to_json_schema(parameters)
        
        assert schema["properties"]["items"]["type"] == "array"
        assert "items" in schema["properties"]["items"]
        assert schema["properties"]["items"]["items"]["type"] == "string"
    
    def test_parameter_spec_to_json_schema_empty(self):
        """Test schema conversion with no parameters."""
        schema = parameter_spec_to_json_schema([])
        
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["required"] == []
    
    def test_parameter_spec_to_json_schema_unknown_type(self):
        """Test schema conversion with unknown type falls back to string."""
        parameters = [
            {"name": "unknown", "type": "unknown_type", "required": True}
        ]
        
        schema = parameter_spec_to_json_schema(parameters)
        
        assert schema["properties"]["unknown"]["type"] == "string"


@pytest.mark.unit
class TestToolCreation:
    """Test tool creation functionality."""
    
    def test_create_tool_from_plugin_click_button(self):
        """Test creating click-button tool without spec."""
        tool = create_tool_from_plugin("botfather", "click-button")
        
        assert tool.name == "botfather.click-button"
        assert "click-button" in tool.description
        assert tool.inputSchema["type"] == "object"
        assert tool.inputSchema["properties"] == {}
    
    def test_create_tool_from_plugin_send_message(self):
        """Test creating send-message tool without spec."""
        tool = create_tool_from_plugin("botfather", "send-message")
        
        assert tool.name == "botfather.send-message"
        assert "send-message" in tool.description
        assert tool.inputSchema["type"] == "object"
    
    def test_create_tool_from_plugin_deploy(self):
        """Test creating deploy tool without spec."""
        tool = create_tool_from_plugin("devops", "deploy")
        
        assert tool.name == "devops.deploy"
        assert "deploy" in tool.description
        assert tool.inputSchema["type"] == "object"
    
    def test_create_tool_from_plugin_with_spec(self):
        """Test creating tool with command spec."""
        command_spec = {
            "name": "test-command",
            "description": "Test command description",
            "parameters": [
                {
                    "name": "param1",
                    "type": "string",
                    "description": "First parameter",
                    "required": True,
                    "default": None
                },
                {
                    "name": "param2",
                    "type": "number",
                    "description": "Second parameter",
                    "required": False,
                    "default": 10
                }
            ]
        }
        
        tool = create_tool_from_plugin("test_plugin", "test-command", command_spec)
        
        assert tool.name == "test_plugin.test-command"
        assert tool.description == "Test command description"
        assert "param1" in tool.inputSchema["properties"]
        assert "param2" in tool.inputSchema["properties"]
        assert "param1" in tool.inputSchema["required"]
        assert "param2" not in tool.inputSchema["required"]
        assert tool.inputSchema["properties"]["param2"]["default"] == 10
    
    def test_create_tool_from_plugin_with_spec_no_description(self):
        """Test creating tool with spec but no description."""
        command_spec = {
            "name": "test-command",
            "parameters": []
        }
        
        tool = create_tool_from_plugin("test_plugin", "test-command", command_spec)
        
        assert "test-command" in tool.description
        assert tool.inputSchema["properties"] == {}


@pytest.mark.unit
class TestToolRegistration:
    """Test tool registration functionality."""
    
    @patch.object(smcp_module, "discover_plugins")
    @patch.object(smcp_module, "get_plugin_describe")
    def test_register_plugin_tools_with_describe(self, mock_describe, mock_discover):
        """Test plugin tool registration with --describe method."""
        # Mock discovered plugins
        mock_discover.return_value = {
            "test_plugin": {"path": "/path/to/cli.py"}
        }
        
        # Mock --describe output
        mock_describe.return_value = {
            "plugin": {"name": "test_plugin", "version": "1.0.0"},
            "commands": [
                {
                    "name": "test-command",
                    "description": "Test command",
                    "parameters": [
                        {
                            "name": "param1",
                            "type": "string",
                            "description": "First parameter",
                            "required": True
                        }
                    ]
                }
            ]
        }
        
        # Mock server
        mock_server = Mock()
        mock_list_tools = Mock()
        mock_call_tool = Mock()
        mock_server.list_tools = Mock(return_value=mock_list_tools)
        mock_server.call_tool = Mock(return_value=mock_call_tool)
        
        # Mock global plugin_registry
        with patch.object(smcp_module, "plugin_registry", {}):
            register_plugin_tools(mock_server)
            
            # Verify --describe was called
            mock_describe.assert_called_once_with("test_plugin", "/path/to/cli.py")
            
            # Verify server methods were called
            mock_server.list_tools.assert_called_once()
            mock_server.call_tool.assert_called_once()
    
    @patch.object(smcp_module, "discover_plugins")
    @patch.object(smcp_module, "get_plugin_describe")
    @patch.object(smcp_module, "get_plugin_help")
    @patch.object(smcp_module, "parse_commands_from_help")
    def test_register_plugin_tools_fallback(self, mock_parse, mock_help, mock_describe, mock_discover):
        """Test plugin tool registration with fallback to help scraping."""
        # Mock discovered plugins
        mock_discover.return_value = {
            "test_plugin": {"path": "/path/to/cli.py"}
        }
        
        # Mock --describe not supported (returns None)
        mock_describe.return_value = None
        
        # Mock help text parsing
        mock_help.return_value = "Available commands:\n  test-command\n  another-command"
        mock_parse.return_value = ["test-command", "another-command"]
        
        # Mock server
        mock_server = Mock()
        mock_list_tools = Mock()
        mock_call_tool = Mock()
        mock_server.list_tools = Mock(return_value=mock_list_tools)
        mock_server.call_tool = Mock(return_value=mock_call_tool)
        
        # Mock global plugin_registry
        with patch.object(smcp_module, "plugin_registry", {}):
            register_plugin_tools(mock_server)
            
            # Verify --describe was tried first
            mock_describe.assert_called_once_with("test_plugin", "/path/to/cli.py")
            
            # Verify fallback to help scraping
            mock_help.assert_called_once_with("test_plugin", "/path/to/cli.py")
            mock_parse.assert_called_once_with("Available commands:\n  test-command\n  another-command")
            
            # Verify server methods were called
            mock_server.list_tools.assert_called_once()
            mock_server.call_tool.assert_called_once()
    
    @patch.object(smcp_module, "discover_plugins")
    @patch.object(smcp_module, "get_plugin_describe")
    @patch.object(smcp_module, "get_plugin_help")
    @patch.object(smcp_module, "parse_commands_from_help")
    def test_register_plugin_tools_no_commands(self, mock_parse, mock_help, mock_describe, mock_discover):
        """Test plugin tool registration with no commands found."""
        # Mock discovered plugins
        mock_discover.return_value = {
            "test_plugin": {"path": "/path/to/cli.py"}
        }
        
        # Mock --describe not supported
        mock_describe.return_value = None
        
        # Mock help text without commands
        mock_help.return_value = "Just some help text"
        mock_parse.return_value = []
        
        # Mock server
        mock_server = Mock()
        mock_list_tools = Mock()
        mock_call_tool = Mock()
        mock_server.list_tools = Mock(return_value=mock_list_tools)
        mock_server.call_tool = Mock(return_value=mock_call_tool)
        
        # Mock global plugin_registry
        with patch.object(smcp_module, "plugin_registry", {}):
            register_plugin_tools(mock_server)
            
            # Server methods should still be called even with no tools
            mock_server.list_tools.assert_called_once()
            mock_server.call_tool.assert_called_once()
    
    @patch.object(smcp_module, "discover_plugins")
    @patch.object(smcp_module, "get_plugin_describe")
    def test_register_plugin_tools_describe_no_command_name(self, mock_describe, mock_discover):
        """Test plugin tool registration with --describe but missing command name."""
        # Mock discovered plugins
        mock_discover.return_value = {
            "test_plugin": {"path": "/path/to/cli.py"}
        }
        
        # Mock --describe output with missing command name
        mock_describe.return_value = {
            "plugin": {"name": "test_plugin", "version": "1.0.0"},
            "commands": [
                {
                    "description": "Test command without name",
                    "parameters": []
                }
            ]
        }
        
        # Mock server
        mock_server = Mock()
        mock_list_tools = Mock()
        mock_call_tool = Mock()
        mock_server.list_tools = Mock(return_value=mock_list_tools)
        mock_server.call_tool = Mock(return_value=mock_call_tool)
        
        # Mock global plugin_registry
        with patch.object(smcp_module, "plugin_registry", {}):
            register_plugin_tools(mock_server)
            
            # Server methods should still be called
            mock_server.list_tools.assert_called_once()
            mock_server.call_tool.assert_called_once()


# Health check tests removed - health_check function doesn't exist in current server implementation 