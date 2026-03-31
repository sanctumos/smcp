# SMCP plugins (this repository)

**`MCP_PLUGINS_DIR`** defaults here when unset.

| Folder | Purpose |
|--------|---------|
| **`demo_math/`** | Bundled demo: `calculate`, `format_bytes`, `coin_flip` — run `python cli.py --describe`. |
| **`demo_text/`** | Bundled demo: `echo`, `word_count`, `slugify`, `hash_preview`. |

**Broca** admin tools (`broca__*`) ship in the [sanctumos/broca](https://github.com/sanctumos/broca) repo (`smcp/broca/`). Point `MCP_PLUGINS_DIR` at a directory that includes both demos and Broca if you need both (e.g. symlinks).

```bash
export MCP_PLUGINS_DIR=/path/to/broca/checkout/smcp
```

See `broca/smcp/broca/README.md` in that repository.
