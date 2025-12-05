@echo off
REM Start SMCP server in STDIO mode for local MCP clients (Claude Desktop, Cursor, etc.)
REM This script activates the virtual environment and starts the STDIO server

REM Change to the script's directory to ensure relative paths work
cd /d "%~dp0"

REM Activate virtual environment silently
call venv\Scripts\activate.bat >nul 2>&1

REM Check if activation was successful
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment >&2
    echo Current directory: %CD% >&2
    echo Make sure venv exists in: %~dp0 >&2
    exit /b 1
)

REM Start the STDIO server
REM All output goes to stderr (WARNING/ERROR only) - stdout is for JSON-RPC only
python smcp_stdio.py

REM Exit with server's exit code
exit /b %errorlevel%
