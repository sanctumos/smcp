## Issue #7 Resolution: Hardcoded Parameter Schemas

This issue has been **RESOLVED** as part of the plugin introspection system implementation.

### Solution Implemented

The hardcoded parameter schemas have been replaced with **dynamic schema extraction** from plugin `--describe` output.

### Changes Made

**Commit**: [See latest push for commit hash]

#### Key Changes

- **Removed**: Hardcoded `if/elif` switches per command name
- **Added**: Dynamic schema extraction from `--describe` command output
- **Fallback**: Empty schemas for plugins without `--describe` (backward compatible)

#### Implementation Details

1. **`parameter_spec_to_json_schema()`**: Converts plugin parameter specs to JSON Schema
   - Supports all types: string, number, integer, boolean, array, object
   - Handles required/optional parameters
   - Includes default values
   - Adds descriptions

2. **`create_tool_from_plugin()`**: Now extracts schemas from command specs
   - If `command_spec` provided: Extracts full parameter schemas
   - If no spec: Falls back to empty schema (backward compatible)

3. **`register_plugin_tools()`**: Automatically uses schemas when available
   - Plugins with `--describe`: Full parameter schemas
   - Plugins without `--describe`: Empty schemas (existing behavior)

### Benefits

✅ **No More Hardcoding**: Schemas derived from plugin metadata  
✅ **Extensible**: New commands automatically get proper schemas  
✅ **Type Information**: Full type support (string, number, boolean, array, object)  
✅ **Backward Compatible**: Existing plugins continue working  
✅ **Fixes Issue #5**: Part of the same solution addressing plugin discovery  

### Example

**Before** (Hardcoded):
```python
if command == "deploy":
    # Hardcoded schema
elif command == "rollback":
    # Hardcoded schema
```

**After** (Dynamic):
```python
# Schema extracted from --describe output
if command_spec:
    input_schema = parameter_spec_to_json_schema(command_spec["parameters"])
```

### Testing

✅ **Comprehensive test coverage**:
- Parameter type conversions (6 tests)
- Required vs optional parameters
- Default values
- Array and object types
- Edge cases (empty, unknown types)

### Related

This resolution is part of the larger plugin introspection system that also resolves **Issue #5**. Both issues were addressed together as they share the same root cause and solution.

### Status

✅ **RESOLVED** - Dynamic schema extraction implemented, fully tested, backward compatible

**Note**: Plugins need to implement `--describe` to get full schema benefits. Existing plugins continue working with empty schemas (same as before).

