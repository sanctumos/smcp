# STDIO Transport Implementation Plan

## Overview

This document outlines the plan to add STDIO (standard input/output) transport support to the SMCP (Sanctum Letta MCP) server, enabling compatibility with local MCP clients like Claude Desktop and Cursor that use STDIO-based communication instead of Server-Sent Events (SSE).

## Goals

1. **Add STDIO transport mode** as an optional alternative to SSE transport
2. **Maintain backward compatibility** - SSE remains the default transport
3. **Enable local client support** - Allow Claude Desktop, Cursor, and other STDIO-based MCP clients to connect
4. **Minimal code changes** - Reuse existing server and plugin infrastructure
5. **Clean architecture** - Separate transport concerns from core server logic

## Current Architecture

### Transport Layer
- **Primary Transport**: SSE (Server-Sent Events) via `SseServerTransport`
- **Server Framework**: Starlette/uvicorn HTTP server
- **Use Case**: Remote connections (Letta AI framework)
- **Entry Point**: `async_main()` function in `smcp.py`

### Current Flow
1. Parse command-line arguments (`parse_arguments()`)
2. Create MCP server instance (`create_server()`)
3. Register plugin tools (`register_plugin_tools()`)
4. Create SSE transport (`SseServerTransport`)
5. Set up Starlette HTTP app with SSE endpoints
6. Start uvicorn server

### Key Functions
- `create_server(host, port)` - Creates MCP Server instance
- `register_plugin_tools(server)` - Discovers and registers all plugin tools
- `async_main()` - Main async entry point (currently SSE-only)

## Technical Requirements

### MCP Library Support
The `mcp` library provides STDIO support via:
- **Module**: `mcp.server.stdio`
- **Function**: `stdio_server(stdin=None, stdout=None)`
- **Type**: Async context manager
- **Streams**: Returns `(read_stream, write_stream)` tuple
- **Default**: Uses `sys.stdin` and `sys.stdout` if not specified

### Compatibility Requirements
- **Python Version**: 3.8+ (maintained)
- **Dependencies**: No new dependencies required (uses existing `mcp` library)
- **Platform**: Windows, Linux, macOS (stdio is cross-platform)

## Implementation Plan

### Phase 1: Argument Parsing Updates

**File**: `smcp.py`  
**Location**: `parse_arguments()` function (line ~475)

**Changes**:
1. Add `--stdio` boolean flag
2. Update parser description to mention both transports
3. Add validation logic for conflicting arguments
4. Update epilog with STDIO usage examples

**Code Changes**:
```python
parser.add_argument(
    "--stdio",
    action="store_true",
    help="Use STDIO transport instead of SSE (for local clients like Claude Desktop/Cursor)"
)

# Add validation in parse_arguments() or async_main()
if args.stdio and args.allow_external:
    parser.error("--stdio and --allow-external cannot be used together")
if args.stdio and (args.host != "127.0.0.1" or args.port != 8000):
    logger.warning("--host and --port are ignored in STDIO mode")
```

### Phase 2: Refactor Transport Logic

**File**: `smcp.py`  
**Location**: `async_main()` function (line ~512)

**Strategy**: Extract transport-specific code into separate functions

**New Functions to Create**:
1. `async def run_sse_mode(args)` - Current SSE/HTTP implementation
2. `async def run_stdio_mode(args)` - New STDIO implementation
3. `async def initialize_server(args)` - Common server initialization

**Function Signatures**:
```python
async def initialize_server(args) -> Server:
    """
    Common server initialization for both transport modes.
    
    Returns:
        Configured MCP Server instance with plugins registered
    """
    # Create server (host/port only used for logging in stdio mode)
    server = create_server(
        args.host if not args.stdio else "stdio",
        args.port if not args.stdio else 0
    )
    
    # Register plugin tools
    register_plugin_tools(server)
    
    return server

async def run_sse_mode(args, server: Server):
    """
    Run server in SSE transport mode (HTTP/SSE endpoints).
    
    Args:
        args: Parsed command-line arguments
        server: Initialized MCP Server instance
    """
    # Current SSE implementation code here
    
async def run_stdio_mode(args, server: Server):
    """
    Run server in STDIO transport mode (stdin/stdout).
    
    Args:
        args: Parsed command-line arguments
        server: Initialized MCP Server instance
    """
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting server with STDIO transport...")
    logger.info("Server ready for local MCP clients (Claude Desktop, Cursor, etc.)")
    
    # Use stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )
```

### Phase 3: Update async_main()

**File**: `smcp.py`  
**Location**: `async_main()` function

**Changes**:
- Extract common initialization
- Branch based on `args.stdio` flag
- Route to appropriate transport mode

**New Structure**:
```python
async def async_main():
    """Main entry point."""
    args = parse_arguments()
    
    # Validate arguments
    if args.stdio and args.allow_external:
        logger.error("--stdio and --allow-external cannot be used together")
        sys.exit(1)
    
    # Warn about ignored arguments in stdio mode
    if args.stdio:
        if args.host != "127.0.0.1" or args.port != 8000:
            logger.warning("⚠️  --host and --port are ignored in STDIO mode")
    
    # Initialize server (common for both modes)
    global server
    server = initialize_server(args)
    
    # Route to appropriate transport mode
    if args.stdio:
        await run_stdio_mode(args, server)
    else:
        await run_sse_mode(args, server)
```

### Phase 4: Extract SSE Mode Code

**File**: `smcp.py`  
**Location**: Extract from `async_main()` to `run_sse_mode()`

**Code to Move** (lines ~516-611):
- Host binding logic
- SSE transport creation
- Starlette app setup
- Uvicorn server configuration
- Signal handling

**Note**: Keep all existing SSE functionality intact, just move it to a separate function.

## Detailed Code Changes

### 1. Update parse_arguments()

```python
def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Sanctum Letta MCP Server - Base MCP implementation with SSE and STDIO transport support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # SSE mode (default, for Letta/remote clients)
  python smcp.py                    # Run with localhost-only (secure default)
  python smcp.py --host 127.0.0.1   # Localhost-only (explicit)
  python smcp.py --allow-external   # Allow external connections
  python smcp.py --port 9000        # Run on custom port
  
  # STDIO mode (for local clients like Claude Desktop/Cursor)
  python smcp.py --stdio            # Use STDIO transport
        """
    )
    
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Use STDIO transport instead of SSE (for local MCP clients like Claude Desktop/Cursor)"
    )
    
    parser.add_argument(
        "--allow-external",
        action="store_true",
        dest="allow_external",  # Keep existing dest for compatibility
        help="Allow external connections (SSE mode only, ignored in STDIO mode)"
    )
    
    # ... existing --port and --host arguments ...
    
    return parser.parse_args()
```

### 2. Create initialize_server()

```python
async def initialize_server(args) -> Server:
    """
    Initialize MCP server and register plugins.
    
    This is common initialization for both SSE and STDIO modes.
    
    Args:
        args: Parsed command-line arguments
        
    Returns:
        Initialized MCP Server instance with all plugins registered
    """
    # Determine server name/identifier
    if args.stdio:
        server_name = "stdio"
        server_port = 0
        logger.info("Initializing MCP server for STDIO transport...")
    else:
        server_name = args.host
        server_port = args.port
        logger.info(f"Initializing MCP server for SSE transport on {server_name}:{server_port}...")
    
    # Create MCP server
    global server
    server = create_server(server_name, server_port)
    
    # Register plugin tools (same for both modes)
    register_plugin_tools(server)
    
    logger.info(f"Server initialized with {metrics['tools_registered']} tools from {metrics['plugins_discovered']} plugins")
    
    return server
```

### 3. Create run_stdio_mode()

```python
async def run_stdio_mode(args, server: Server):
    """
    Run server in STDIO transport mode.
    
    This mode communicates via stdin/stdout, suitable for local MCP clients
    like Claude Desktop and Cursor.
    
    Args:
        args: Parsed command-line arguments
        server: Initialized MCP Server instance
    """
    from mcp.server.stdio import stdio_server
    
    logger.info("=" * 60)
    logger.info("Starting SMCP server with STDIO transport")
    logger.info("=" * 60)
    logger.info("Server ready for local MCP clients:")
    logger.info("  - Claude Desktop")
    logger.info("  - Cursor IDE")
    logger.info("  - Other STDIO-based MCP clients")
    logger.info("")
    logger.info("Connect by configuring your MCP client to run:")
    logger.info(f"  {sys.executable} {Path(__file__).absolute()} --stdio")
    logger.info("=" * 60)
    
    try:
        # Use stdio transport (defaults to sys.stdin/sys.stdout)
        async with stdio_server() as (read_stream, write_stream):
            # Run the MCP server with stdio streams
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Error in STDIO mode: {e}", exc_info=True)
        raise
    finally:
        logger.info("STDIO server stopped")
```

### 4. Create run_sse_mode()

```python
async def run_sse_mode(args, server: Server):
    """
    Run server in SSE transport mode (HTTP/SSE endpoints).
    
    This is the original implementation, extracted into a separate function.
    
    Args:
        args: Parsed command-line arguments
        server: Initialized MCP Server instance
    """
    # Determine host binding
    if args.allow_external:
        host = "0.0.0.0"
        logger.warning("⚠️  WARNING: External connections are allowed. This may pose security risks.")
    else:
        host = args.host
        if host == "127.0.0.1":
            logger.info("🔒 Security: Server bound to localhost only. Use --allow-external for network access.")
    
    logger.info(f"Starting Sanctum Letta MCP Server on {host}:{args.port}...")
    
    # Create SSE transport
    sse_transport = SseServerTransport("/messages/")
    
    # Create Starlette app with SSE endpoints
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import Response
    
    async def sse_endpoint(request):
        """SSE connection endpoint."""
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],  # read_stream
                streams[1],  # write_stream
                server.create_initialization_options()
            )
        return Response()
    
    async def sse_post_endpoint(request):
        """Handle POST requests to /sse (for Letta compatibility)."""
        try:
            body = await request.body()
            if body:
                return Response(
                    "POST requests to /sse should be sent to /messages/ instead. "
                    "Use GET /sse to establish SSE connection, then POST to /messages/ to send messages.",
                    status_code=400,
                    media_type="text/plain"
                )
            else:
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
```

### 5. Update async_main()

```python
async def async_main():
    """Main entry point."""
    args = parse_arguments()
    
    # Validate arguments
    if args.stdio and args.allow_external:
        logger.error("❌ Error: --stdio and --allow-external cannot be used together")
        logger.error("   STDIO mode is for local clients only and doesn't use network connections")
        sys.exit(1)
    
    # Warn about ignored arguments in stdio mode
    if args.stdio:
        if args.host != "127.0.0.1":
            logger.warning(f"⚠️  --host={args.host} is ignored in STDIO mode")
        if args.port != 8000:
            logger.warning(f"⚠️  --port={args.port} is ignored in STDIO mode")
    
    # Initialize server (common for both modes)
    global server
    server = await initialize_server(args)
    
    # Route to appropriate transport mode
    if args.stdio:
        await run_stdio_mode(args, server)
    else:
        await run_sse_mode(args, server)
```

## Testing Plan

### Unit Tests

1. **Argument Parsing**
   - Test `--stdio` flag is recognized
   - Test `--stdio` conflicts with `--allow-external`
   - Test warnings for ignored arguments in stdio mode

2. **Server Initialization**
   - Test `initialize_server()` creates server correctly
   - Test plugins are registered in both modes
   - Test metrics are updated correctly

### Integration Tests

1. **STDIO Mode**
   - Test server starts in stdio mode
   - Test server responds to MCP protocol messages via stdin
   - Test server sends responses via stdout
   - Test graceful shutdown (SIGINT/SIGTERM)

2. **SSE Mode (Regression)**
   - Test SSE mode still works (no regressions)
   - Test HTTP endpoints are accessible
   - Test plugin tools are callable via SSE

3. **Mode Switching**
   - Test default mode is SSE
   - Test `--stdio` flag switches to stdio mode
   - Test both modes can discover and use plugins

### Manual Testing

1. **Claude Desktop Integration**
   - Configure Claude Desktop to use `python smcp.py --stdio`
   - Verify server connects and tools are available
   - Test calling plugin tools from Claude

2. **Cursor Integration**
   - Configure Cursor MCP settings
   - Verify server connects
   - Test tool execution

3. **Letta Integration (Regression)**
   - Verify SSE mode still works with Letta
   - Test remote connections
   - Verify plugin tools work via SSE

## Documentation Updates

### Files to Update

1. **README.md**
   - Add STDIO mode to features list
   - Add usage examples for both modes
   - Update installation/configuration instructions

2. **docs/getting-started.md**
   - Add section on choosing transport mode
   - Add Claude Desktop/Cursor configuration examples
   - Update server startup instructions

3. **docs/api-reference.md**
   - Document `--stdio` command-line argument
   - Update transport mode descriptions
   - Add STDIO mode examples

4. **docs/deployment-guide.md**
   - Add STDIO mode deployment considerations
   - Update client configuration examples
   - Add troubleshooting for STDIO mode

### New Documentation

1. **docs/claude-desktop-setup.md** (optional)
   - Step-by-step Claude Desktop configuration
   - Example MCP server configuration
   - Troubleshooting common issues

2. **docs/cursor-setup.md** (optional)
   - Cursor IDE MCP configuration
   - Example settings
   - Integration examples

## Risk Assessment

### Low Risk
- ✅ STDIO support is built into MCP library
- ✅ No new dependencies required
- ✅ SSE mode remains unchanged (backward compatible)
- ✅ Plugin system is transport-agnostic

### Medium Risk
- ⚠️ Signal handling in stdio mode (needs testing)
- ⚠️ Logging behavior in stdio mode (may need adjustment)
- ⚠️ Error handling differences between modes

### Mitigation Strategies
1. **Comprehensive Testing**: Test both modes thoroughly
2. **Graceful Degradation**: Ensure errors are handled cleanly
3. **Clear Documentation**: Document mode differences clearly
4. **Default Behavior**: Keep SSE as default (proven, stable)

## Implementation Checklist

### Phase 1: Core Implementation
- [ ] Add `--stdio` argument to `parse_arguments()`
- [ ] Add argument validation logic
- [ ] Create `initialize_server()` function
- [ ] Create `run_stdio_mode()` function
- [ ] Create `run_sse_mode()` function
- [ ] Update `async_main()` to route by mode

### Phase 2: Testing
- [ ] Unit tests for argument parsing
- [ ] Integration test for stdio mode
- [ ] Regression test for SSE mode
- [ ] Manual test with Claude Desktop
- [ ] Manual test with Cursor

### Phase 3: Documentation
- [ ] Update README.md
- [ ] Update getting-started.md
- [ ] Update api-reference.md
- [ ] Update deployment-guide.md
- [ ] Add client setup guides (optional)

### Phase 4: Polish
- [ ] Review error messages
- [ ] Review logging output
- [ ] Test signal handling
- [ ] Code review
- [ ] Update CHANGELOG.md

## Success Criteria

1. ✅ Server can run in STDIO mode with `--stdio` flag
2. ✅ Server can run in SSE mode (default, no regressions)
3. ✅ Both modes discover and register plugins correctly
4. ✅ Both modes can execute plugin tools
5. ✅ Claude Desktop can connect via STDIO mode
6. ✅ Cursor can connect via STDIO mode
7. ✅ Letta can still connect via SSE mode
8. ✅ Documentation is updated and accurate
9. ✅ No breaking changes to existing functionality

## Timeline Estimate

- **Phase 1 (Implementation)**: 2-3 hours
- **Phase 2 (Testing)**: 2-3 hours
- **Phase 3 (Documentation)**: 1-2 hours
- **Phase 4 (Polish)**: 1 hour

**Total Estimated Time**: 6-9 hours

## Notes

- STDIO mode is simpler than SSE mode (no HTTP server needed)
- Plugin system is already transport-agnostic (no changes needed)
- MCP library handles transport details (we just need to use the right one)
- This is primarily a refactoring + new transport mode addition

## Future Enhancements (Out of Scope)

- Auto-detect transport mode based on environment
- Support for both transports simultaneously
- Transport mode configuration via environment variables
- Health check endpoints for STDIO mode (if needed)

