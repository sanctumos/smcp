# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Fixed

- **`create_server()` reports the real package version and drops dead params** (issue #49): the server no longer advertises a hardcoded `1.0.0`; it derives the version from the package `__version__`. Removed the unused `host`/`port` parameters. Narrowed two bare `except:` clauses in `execute_plugin_tool` to `except Exception:` (with debug logging) so `KeyboardInterrupt`/`SystemExit` are no longer swallowed.
- **Advertised Python 3.8/3.9 support is now real** (issue #48): added `from __future__ import annotations` to `smcp.py` and `smcp_stdio.py` (governor already had it) so the PEP 604 union annotations (`X | None`) are deferred and the modules import on 3.8/3.9. `requires-python >=3.8` is now truthful.
- **Structured (array/object) tool arguments now round-trip to plugins as clean JSON** (issue #56): `execute_plugin_tool` renders array/object arguments schema-aware. Arrays of objects are serialized as a single `--name <json>` (no more Python `repr` on argv), object params and bare dicts are JSON-encoded, and Letta's single-child `{"item": ...}` array coercion is normalized centrally so array-typed params receive a real list. Scalar arrays still render as repeated flags (argparse `nargs`/`action=append`). This is the root-cause fix behind the `kitchen_pos` catering "recipients array required" failures.

### Changed

- **Core is product-agnostic: argument-alias coalescing is now generic** (issue #44). `_coalesce_tool_argument_aliases` no longer hardcodes any plugin's field names (previously `payload_json` / `catering_invoice_id` / `invoice_command`). It collapses hyphen/underscore key variants to a single canonical key for *any* parameter, so new plugins plug in with zero core edits.

### Documentation

- Full documentation overhaul: rebranded this repository's docs to **Sanctum** (SanctumOS / `sanctumos.org`), leaving the Animus branding to the `AnimusUNO/smcp` fork. Corrected clone URLs to `sanctumos/smcp`, the default plugins directory to `plugins/`, and the MCP server name to `sanctum-letta-mcp`. Replaced the stale "no authentication" API-reference section with the real API-key auth, documented `--require-auth` / `--plugin-timeout` and the `MCP_API_KEY` / `MCP_PLUGIN_TIMEOUT` / `SMCP_ATTACH_PROFILE` environment variables across the guides, and removed references to the retired `botfather` / `devops` plugins in favor of the bundled `demo_math` / `demo_text`. Moved one-time transition notes to `docs/history/`.

## [3.0.3] - 2026-07-08

### Added

- **HTTP/SSE transport authentication** (issue #39): optional shared-secret auth via `Authorization: Bearer <key>` / `X-API-Key`, configured with `MCP_API_KEY` / `MCP_API_KEYS`. `--allow-external` now **fails closed** — it refuses to start without a key unless `MCP_AUTH_DISABLED=1`. Loopback clients bypass by default (`MCP_AUTH_ALLOW_LOOPBACK`, `--require-auth`). Enforced by a raw ASGI middleware so SSE streaming is never buffered. STDIO transport is unaffected.
- **`demo_math`** and **`demo_text`** bundled plugins: real behavior + `--describe` JSON for MCP tool schemas (replacing stub `botfather` / `devops`).
- **Session attach governor** (`sanctum__tools`) and argument-alias coalescing / dict→JSON argv handling, reconciled in from `master`.

### Fixed

- **Plugin stdout JSON errors round-trip on nonzero exit** (issue #42, mirrors AnimusUNO #8): confirmed and locked with regression tests — a plugin that prints `{"error": ...}` and exits nonzero surfaces that message to the client (`Error: <message>`); non-JSON output is returned raw; a silent nonzero exit falls back to `Plugin exited with code N (no output)`. No empty error strings.
- **Plugin subprocess cleanup on cancel/disconnect** (issue #40, mirrors AnimusUNO #18): `execute_plugin_tool` now terminates its child process on `asyncio.CancelledError` and via a `try/finally` guard, escalating `terminate()` → `kill()` after a grace period, so client disconnects/cancellations no longer orphan plugin processes.
- **Schema-aware boolean tool arguments** (issues #37 and #38): booleans are now rendered onto plugin argv per the parameter's `--describe` declaration. `store_true`/`store_false` flags emit a bare `--flag` only when `true` (no more `error: unrecognized arguments: false`, #38); value-style booleans emit `--flag true|false` so a `false` is never silently dropped (#37). Undeclared booleans default to value-style. See the plugin development guide for the convention.

### Testing

- Coverage raised to ~96% (`fail_under` ratcheted 35 → 90) across unit, integration, and e2e, including full coverage of the new auth code, the merged governor, and the schema-aware boolean rendering.

### Removed

- Stub **`botfather`** and **`devops`** plugin folders (they returned placeholder JSON only).

### Changed

- **Plugin subprocess timeout is now operator-configurable** (issue #41, mirrors AnimusUNO #10) via `MCP_PLUGIN_TIMEOUT` (seconds) and the `--plugin-timeout` CLI flag (flag takes precedence). **The default is now no timeout** (previously a hardcoded 300s), so long-running plugin operations are not cut off; set a value to protect against hung processes. On timeout the child is terminated (`terminate()` → `kill()`) and a structured timeout error is returned.
- **Broca MCP plugin** (`broca__*` tools) **removed from this repository**. It ships with **[sanctumos/broca](https://github.com/sanctumos/broca)** under `smcp/broca/`. Set `MCP_PLUGINS_DIR` to that repo’s `smcp/` directory (or symlink `broca` into your existing plugins root). See `plugins/README.md`.

## [3.0.0] - 2025-07-11

### 🎉 Major Release - Complete Overhaul

This release represents a complete rewrite and major upgrade of the Sanctum Letta MCP Server, addressing weeks of development challenges and providing a robust, production-ready solution.

### ✨ Added

- **Complete MCP Protocol Compliance**: Full implementation of Model Context Protocol specification
- **Base MCP Library Integration**: Uses official MCP Python SDK with proper SSE transport for bidirectional communication
- **Comprehensive Test Suite**: 100% test coverage with unit, integration, and E2E tests
- **Plugin Architecture**: Dynamic plugin discovery and registration system
- **SSE Transport**: Proper Server-Sent Events implementation for real-time communication
- **JSON-RPC 2.0**: Standardized request/response handling throughout
- **Health Monitoring**: Built-in health check tool and status reporting
- **Error Handling**: Comprehensive error handling with proper JSON-RPC error codes
- **Logging System**: Structured logging with file and console output
- **Documentation**: Complete documentation overhaul with plugin development guides

### 🔧 Changed

- **Server Implementation**: Complete rewrite using base MCP library (`mcp.server.Server`) with SSE transport instead of custom aiohttp implementation
- **Plugin System**: Redesigned plugin architecture with automatic discovery
- **Testing Infrastructure**: Rebuilt test suite from scratch with proper SSE understanding
- **Documentation**: Complete rewrite with comprehensive guides and examples
- **License**: Updated to dual licensing: AGPLv3 for code, CC-BY-SA 4.0 for documentation
- **Project Structure**: Reorganized for better maintainability and user experience

### 🐛 Fixed

- **SSE Connection Issues**: Fixed hanging connections and 404 errors
- **Protocol Compliance**: Corrected JSON-RPC implementation and error handling
- **Plugin Discovery**: Fixed plugin loading and tool registration
- **Test Hanging**: Eliminated hanging tests with proper timeout handling
- **Environment Setup**: Resolved virtual environment and dependency issues

### 🗑️ Removed

- **Legacy STDIO Protocol**: Removed outdated protocol implementation
- **Custom SSE Handler**: Replaced with base MCP library's SSE transport implementation
- **FastMCP Dependency**: Migrated away from FastMCP due to SSE limitations (see docs/history/FASTMCP-issue_update.md)
- **Problematic Tests**: Removed hanging and incompatible test files
- **Outdated Documentation**: Replaced with comprehensive, user-friendly guides

### 📚 Documentation

- **Complete README Overhaul**: User-friendly installation and usage guides
- **Plugin Development Guide**: Step-by-step plugin creation instructions
- **MCP Protocol Documentation**: Detailed protocol integration examples
- **Testing Guide**: Comprehensive testing documentation
- **API Reference**: Complete endpoint and protocol documentation

### 🧪 Testing

- **Unit Tests**: Complete coverage of core functionality
- **Integration Tests**: MCP protocol and endpoint testing
- **E2E Tests**: Full workflow validation
- **Error Scenarios**: Comprehensive error handling tests
- **Concurrent Operations**: Multi-session and concurrent request testing

### 🔌 Plugins

- **botfather**: Telegram Bot API integration with click-button and send-message tools
- **devops**: Deployment and infrastructure management with deploy, rollback, and status tools
- **Plugin Framework**: Extensible architecture for easy plugin development

### 🚀 Performance

- **Base MCP Library**: Uses official MCP Python SDK for optimized performance and protocol compliance
- **Efficient Plugin Loading**: Automatic discovery and registration
- **Proper SSE Handling**: Bidirectional SSE communication with no hanging connections or resource leaks
- **Concurrent Request Support**: Handles multiple simultaneous requests efficiently

### 🔒 Security

- **Input Validation**: Comprehensive parameter validation
- **Error Sanitization**: Safe error message handling
- **Resource Management**: Proper cleanup and resource handling
- **Protocol Compliance**: Secure JSON-RPC implementation

## [2.2.0] - 2025-01-15

### Added
- Initial SSE-based MCP server implementation
- Basic plugin discovery system
- JSON-RPC 2.0 message handling
- Health check endpoint

### Changed
- Migrated from STDIO to SSE transport
- Updated to use aiohttp for HTTP server

### Fixed
- Basic connection handling
- Plugin loading issues

## [2.1.0] - 2024-12-01

### Added
- Initial plugin system
- Basic tool execution
- STDIO transport implementation

### Changed
- Restructured project layout
- Improved error handling

## [2.0.0] - 2024-11-01

### Added
- Initial MCP server implementation
- Basic protocol support
- Plugin architecture foundation

---

## Version History

- **3.0.3** (Current): HTTP/SSE API-key auth, session attach governor, schema-aware boolean arguments, configurable plugin timeout, subprocess cleanup on cancel; coverage floor raised to 90%
- **3.0.0**: Complete overhaul with base MCP library, comprehensive testing, and production readiness
- **2.2.0**: SSE-based implementation with basic functionality
- **2.1.0**: Plugin system and STDIO transport
- **2.0.0**: Initial MCP server foundation

## Migration Guide

### From 2.x to 3.0.0

1. **Update Dependencies**: Install MCP Python SDK and new requirements
2. **Plugin Updates**: Plugins now use standardized CLI interface with optional `--describe` command
3. **Configuration**: Update environment variables if using custom paths
4. **Testing**: Run comprehensive test suite to verify functionality

### Breaking Changes

- **Server Implementation**: Complete rewrite using base MCP library (`mcp.server.Server`) with SSE transport
- **Plugin Interface**: Standardized CLI-based plugin system with optional structured introspection
- **Protocol Handling**: Updated to full MCP specification compliance
- **Testing Framework**: Complete test suite rebuild

---

**Note**: Version 3.0.0 represents a major milestone after weeks of development challenges. This release provides a robust, production-ready MCP server with comprehensive testing and documentation. 