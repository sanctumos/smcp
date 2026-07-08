# HTTP/SSE Transport Authentication (API key / bearer)

## Overview

The SMCP server exposes plugin tools over two transports:

- **STDIO** (`smcp_stdio.py`) — local process pipe; inherently reachable only by
  the parent process. No network exposure.
- **SSE / HTTP** (`smcp.py` → `async_main`) — a Starlette/uvicorn app with
  `GET /sse`, `POST /sse`, and the `/messages/` mount. When started with
  `--allow-external` it binds `0.0.0.0` and is reachable from the network.

Today the HTTP transport has **no authentication**. Anyone who can reach the
port can list tools and call them. When `--allow-external` is used, that means
*anyone on the internet*. Because plugins can wrap privileged operations
(deploy/deprovision, mail, infra), an unauthenticated externally-bound SMCP is a
remote-code-execution-class exposure.

This document specifies **Option 2**: application-level authentication on the
HTTP transport using a shared secret presented as a bearer token / API key, plus
a startup guard that refuses to serve externally without a credential.

## Goals

1. **Authenticate every HTTP request** to the SSE transport when a credential is
   configured, using a standard `Authorization: Bearer <key>` header (with an
   `X-API-Key` convenience alias).
2. **Fail closed on external bind**: refuse to start with `--allow-external`
   unless a key is configured or the operator has *explicitly* opted out.
3. **Preserve existing localhost workflows** — a plain `python smcp.py` bound to
   `127.0.0.1` must keep working with no configuration.
4. **Do not break SSE streaming** — auth must be enforced before the stream
   starts, without buffering the long-lived response.
5. **No secrets in logs, argv, or errors.** Keys come from the environment and
   are compared in constant time.
6. **STDIO transport is unaffected** (no network surface).

## Non-goals

- Per-user identity, scopes, or RBAC (single shared secret; rotation via
  multiple accepted keys).
- OAuth / token issuance / session management.
- TLS termination (handled by a fronting proxy or the network; out of scope).

## Current architecture (relevant seams)

`async_main()` already delegates to two extracted, unit-tested helpers:

- `resolve_host(args) -> str` — decides `0.0.0.0` vs the explicit host.
- `build_app(sse_transport) -> Starlette` — wires the routes.

Auth attaches at these seams:

- A new `resolve_auth_config()` reads the environment once at startup.
- A new `AuthMiddleware` (raw ASGI) wraps the app returned by `build_app()`.
- `async_main()` performs the **external-bind startup guard** after
  `resolve_host()`.

## Configuration

All credentials and toggles come from the environment (never argv, so keys don't
land in `ps`/process listings).

| Variable | Default | Meaning |
|---|---|---|
| `MCP_API_KEY` | — | A single accepted API key. |
| `MCP_API_KEYS` | — | Comma-separated list of accepted keys (rotation / multiple clients). Merged with `MCP_API_KEY`. |
| `MCP_AUTH_DISABLED` | `0` | Explicit escape hatch. `1`/`true` disables auth **and** the external-bind guard. Logged loudly at WARNING/CRITICAL. |
| `MCP_AUTH_ALLOW_LOOPBACK` | `1` | When `1`, requests from `127.0.0.1`/`::1` skip the header check (dev ergonomics). Set `0` to require the key even from localhost. |

Optional CLI convenience (no secret material on the command line):

- `--require-auth` — force enforcement even when bound to localhost (equivalent
  to `MCP_AUTH_ALLOW_LOOPBACK=0`). Useful for testing the auth path locally.

### Behavior matrix

| Bind | Keys configured? | `MCP_AUTH_DISABLED` | Result |
|---|---|---|---|
| `127.0.0.1` | no | no | Serves; loopback requests allowed (current behavior preserved). |
| `127.0.0.1` | yes | no | Serves; loopback bypasses unless `MCP_AUTH_ALLOW_LOOPBACK=0`; non-loopback needs key. |
| `0.0.0.0` | yes | no | Serves; **all non-loopback requests require a valid key**. |
| `0.0.0.0` | **no** | no | **Refuses to start** (exit code 2, CRITICAL log). Closes the open-server hole. |
| any | any | **yes** | Auth fully disabled; startup guard bypassed; loud warning. |

## Request handling

`AuthMiddleware` is a raw ASGI wrapper (not `BaseHTTPMiddleware`, which buffers
and breaks SSE). For each `http` scope:

1. If auth is not enforced (no keys and not required, or `MCP_AUTH_DISABLED`),
   pass through untouched.
2. If the client is loopback and `allow_loopback` is true, pass through.
3. Otherwise extract the presented key:
   - `Authorization: Bearer <key>` (primary), or
   - `X-API-Key: <key>` (alias).
4. Compare against the configured key set with `hmac.compare_digest`
   (constant-time). On match → pass through.
5. On miss/absence → short-circuit with **`401 Unauthorized`**, header
   `WWW-Authenticate: Bearer`, body `{"error":"unauthorized"}`. No hint about
   whether the key was missing vs wrong.

Non-`http` scopes (e.g. `lifespan`) pass straight through.

### Loopback detection

Loopback is determined from the ASGI `scope["client"]` address
(`127.0.0.1`/`::1`). `X-Forwarded-For` is **not** trusted (SMCP binds directly;
there is no assumed reverse proxy). If SMCP is deliberately fronted by a proxy,
run it bound to localhost and let the proxy authenticate, or set
`MCP_AUTH_ALLOW_LOOPBACK=0` and require the key end-to-end.

## Proposed code shape (in `smcp.py`)

```python
class AuthConfig:
    keys: frozenset[str]
    enforce: bool          # True if keys present and not disabled
    allow_loopback: bool
    disabled: bool

def resolve_auth_config(require_auth: bool = False) -> AuthConfig: ...

def _extract_presented_key(headers) -> str | None: ...      # Bearer or X-API-Key

def is_authorized(headers, client_host, cfg) -> bool: ...    # pure, unit-testable

class AuthMiddleware:                                        # raw ASGI wrapper
    def __init__(self, app, cfg): ...
    async def __call__(self, scope, receive, send): ...
```

`build_app(sse_transport, auth_config=None)` wraps its `Starlette` instance in
`AuthMiddleware` when `auth_config.enforce` (or `disabled` is False and keys
exist). `async_main()`:

```python
host = resolve_host(args)
auth = resolve_auth_config(require_auth=args.require_auth)
if host == "0.0.0.0" and not auth.enforce and not auth.disabled:
    logger.critical("Refusing to bind externally without MCP_API_KEY. "
                    "Set MCP_API_KEY or MCP_AUTH_DISABLED=1 to override.")
    sys.exit(2)
...
app = build_app(sse_transport, auth)
```

## Test plan (target: 100% of new code)

**Unit**
- `resolve_auth_config`: single key, multiple keys, merge of `MCP_API_KEY` +
  `MCP_API_KEYS`, whitespace/empty trimming, disabled flag, allow-loopback
  default and override, `require_auth`.
- `_extract_presented_key`: bearer, x-api-key, both, neither, malformed
  `Authorization`.
- `is_authorized`: valid bearer, valid x-api-key, wrong key, missing key,
  loopback bypass on/off, multi-key acceptance, disabled short-circuit.

**Integration (ASGI via httpx)**
- Middleware over `build_app`: 401 on missing/wrong key (with
  `WWW-Authenticate`), pass on valid bearer, pass on valid x-api-key, loopback
  bypass, non-loopback client (simulated `scope["client"]`) requires key,
  `/messages/` mount and `POST /sse` shim both guarded.

**E2E / startup**
- `async_main` refuses `--allow-external` with no key (exit 2).
- `async_main` serves with `--allow-external` + `MCP_API_KEY` set.
- `MCP_AUTH_DISABLED=1` bypasses the guard.

## Rollout (explicitly deferred)

Production SMCP instances (e.g. the `:8010` root server) are **not** touched by
this feature branch. Patching live systems is a separate, later step once the
feature lands on `dev` with full coverage and review. Operators will set
`MCP_API_KEY` and update clients (Letta / Ada) to send the header before the
guard is relied upon externally.

## Backward compatibility

- Default `python smcp.py` (localhost, no env) is unchanged.
- Existing external deployments that *intended* to be open must set
  `MCP_AUTH_DISABLED=1` (a conscious choice) or, preferably, configure a key.
- No new runtime dependencies (`hmac`, `os` are stdlib; Starlette/uvicorn already
  present).
