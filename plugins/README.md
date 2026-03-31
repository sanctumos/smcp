# Optional SMCP plugins (this repository)

Third-party and site-specific plugins may live here. **`MCP_PLUGINS_DIR`** defaults to this directory when unset.

**Broca administration tools (`broca__`*)** ship with **Broca**, not with this repo: use the `smcp/` directory in [sanctumos/broca](https://github.com/sanctumos/broca) and set:

```bash
export MCP_PLUGINS_DIR=/path/to/broca/checkout/smcp
```

See `broca/smcp/broca/README.md` in that repository.
