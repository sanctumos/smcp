#!/usr/bin/env python3
"""
SMCP STDIO Server - Minimal MCP server for STDIO transport.

This is a minimal wrapper around smcp.py that runs in STDIO mode only.
All logging is suppressed to stderr (WARNING/ERROR only) to keep stdout
clean for JSON-RPC protocol messages.

Copyright (c) 2025 Mark Rizzn Hopkins
"""

import asyncio
import logging
import sys

# Configure minimal logging FIRST - WARNING/ERROR only, to stderr
# This must happen before importing smcp to catch all logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(levelname)s: %(message)s',
    stream=sys.stderr,
    force=True  # Override any existing configuration
)

# Import core functions from smcp.py AFTER logging is configured
import smcp

# Override smcp's logging configuration - ensure all handlers go to stderr
# Remove any handlers that might write to stdout
root_logger = logging.getLogger()
for handler in list(root_logger.handlers):
    if isinstance(handler, logging.StreamHandler):
        # If handler writes to stdout, remove it or redirect to stderr
        if hasattr(handler, 'stream') and handler.stream == sys.stdout:
            root_logger.removeHandler(handler)
        else:
            # Ensure it writes to stderr and is at WARNING level
            handler.stream = sys.stderr
            handler.setLevel(logging.WARNING)

# Set smcp logger to WARNING
smcp.logger.setLevel(logging.WARNING)
for handler in list(smcp.logger.handlers):
    if isinstance(handler, logging.StreamHandler):
        if hasattr(handler, 'stream') and handler.stream == sys.stdout:
            smcp.logger.removeHandler(handler)
        else:
            handler.stream = sys.stderr
            handler.setLevel(logging.WARNING)


async def main():
    """Main entry point for STDIO mode."""
    from mcp.server.stdio import stdio_server
    
    try:
        # Create server and register plugins (silently, before entering stdio_server)
        # This must happen before stdio_server context to avoid stdout pollution
        # Any errors here will be logged to stderr only
        try:
            server = smcp.create_server("stdio", 0)
            smcp.register_plugin_tools(server)
        except Exception as e:
            # Log plugin registration errors to stderr
            logging.error(f"Failed to initialize server or register plugins: {e}", exc_info=True)
            sys.exit(1)
        
        # Use stdio transport - this handles stdin/stdout wrapping
        # The context manager yields (read_stream, write_stream)
        # This is the correct pattern from MCP library example
        try:
            async with stdio_server() as (read_stream, write_stream):
                # Run the server with the stdio streams
                # server.run() will block and handle all JSON-RPC messages
                # It waits for the client's initialize message and responds
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options()
                )
        except ExceptionGroup as eg:
            # Handle ExceptionGroup from anyio TaskGroup (Python 3.11+)
            # On Windows, we get OSError [Errno 22] when flushing stdout
            # This is a known issue - the server works fine, but flush fails on exit
            if sys.platform == 'win32':
                flush_errors = [e for e in eg.exceptions if isinstance(e, OSError) and e.errno == 22]
                if len(flush_errors) == len(eg.exceptions):
                    # All errors are Windows flush errors - non-fatal
                    # The server has already done its job successfully
                    logging.warning(f"Windows stdout flush issue (non-fatal, server completed successfully)", exc_info=False)
                    return  # Exit gracefully
            # If not all errors are flush errors, re-raise
            raise
        except BaseExceptionGroup as eg:
            # Handle BaseExceptionGroup (Python 3.11+ alternative)
            if sys.platform == 'win32':
                flush_errors = [e for e in eg.exceptions if isinstance(e, OSError) and e.errno == 22]
                if len(flush_errors) == len(eg.exceptions):
                    logging.warning(f"Windows stdout flush issue (non-fatal, server completed successfully)", exc_info=False)
                    return
            raise
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C
        pass
    except Exception as e:
        # Log errors to stderr only - never to stdout
        logging.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
