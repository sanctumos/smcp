## Issue #5 Resolution: Plugin Discovery Scraping

This issue has been **RESOLVED** with a backward-compatible implementation that addresses all the brittleness concerns.

### Solution Implemented

We've implemented a **dual-method approach** with automatic fallback:

1. **New Method (Preferred)**: `--describe` command that returns structured JSON
2. **Fallback Method**: Help text scraping (maintains backward compatibility)

### Changes Made

**Commit**: [See latest push for commit hash]

#### New Functions Added

- `get_plugin_describe()`: Calls `--describe` and parses structured JSON
- `parse_commands_from_help()`: Extracted help scraping logic (for fallback)
- `parameter_spec_to_json_schema()`: Converts plugin parameter specs to JSON Schema

#### Updated Functions

- `create_tool_from_plugin()`: Now accepts optional `command_spec` parameter to extract full schemas
- `register_plugin_tools()`: Implements fallback logic - tries `--describe` first, falls back to help scraping

### Benefits

✅ **No Breaking Changes**: Existing plugins (botfather, devops) continue working via fallback  
✅ **Reliable Discovery**: New plugins can use `--describe` for machine-readable contracts  
✅ **Parameter Schemas**: Fixes issue #7 by extracting full parameter information  
✅ **Automatic Fallback**: Tries new method first, gracefully falls back if not supported  
✅ **Comprehensive Logging**: Logs which discovery method was used per plugin  

### Plugin Specification Format

Plugins can now implement `--describe` that returns:

```json
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
          "type": "string|number|integer|boolean|array|object",
          "description": "Parameter description",
          "required": true,
          "default": null
        }
      ]
    }
  ]
}
```

### Testing

✅ **39 tests passing** - comprehensive test coverage added:
- `get_plugin_describe()`: 6 tests covering all scenarios
- `parse_commands_from_help()`: 5 tests covering edge cases
- `parameter_spec_to_json_schema()`: 6 tests covering type conversions
- `create_tool_from_plugin()`: 5 tests including with/without specs
- `register_plugin_tools()`: 4 tests covering fallback logic

### Documentation

Updated `docs/plugin-development-guide.md` with:
- Explanation of both discovery methods
- Complete example of implementing `--describe`
- Migration guidance for plugin developers

### Next Steps for Plugin Developers

Existing plugins continue to work without changes. To upgrade:

1. Add `--describe` flag to argparse
2. Implement function returning structured JSON
3. Plugin will automatically use new method when available

**Status**: ✅ **RESOLVED** - Backward compatible, fully tested, documented

