# Source Organization

This project favors small named source files grouped by subsystem. The loader
still uses `.inl` files for hook-heavy translation-unit fragments that need
anonymous-namespace access from a parent `.cpp`, but those files should not be
used as anonymous drawers for unrelated code.

## Verification

Run the organization guard before or with a normal workspace verification:

```powershell
scripts\Check-SourceOrganization.ps1
scripts\Verify-Workspace.ps1
```

`Verify-Workspace.ps1` runs the source organization check before building, so a
new source/header fragment must be represented in both
`SolomonDarkModLoader.vcxproj` and `SolomonDarkModLoader.vcxproj.filters`.

The guard checks:

- every `src/` and `include/` `.c`, `.cpp`, `.h`, `.hpp`, and `.inl` file is in the project
- every project item exists on disk
- every project item has a Visual Studio filter entry
- file size thresholds stay under the current policy unless explicitly allowlisted

Current thresholds are 700 lines for `.cpp`/`.c`, 500 lines for headers, and
700 lines for `.inl` fragments.

## Layout Rules

- Prefer a real `.cpp` and header when a subsystem has its own state boundary.
- Use `.inl` only when the code intentionally lives inside a parent translation unit.
- Keep parent `.inl` files as thin include aggregators after an area grows.
- Put grouped fragments under a named folder, for example:
  - `src/bot_runtime/helpers/`
  - `src/bot_runtime/public_api/`
  - `src/mod_loader_gameplay/core/`
  - `src/mod_loader_gameplay/bot_casting/`
  - `src/mod_loader_gameplay/bot_movement/`
  - `src/mod_loader_gameplay/execute_requests/`
  - `src/mod_loader_gameplay/gameplay_hooks/`
- Split on complete declarations or complete function boundaries.
- Do not hide pieces of one oversized function behind nested `#include` directives.
- When a single function is too large, extract named helper functions or a small context object first.

## Large Files

`Check-SourceOrganization.ps1` should normally have an empty large-file
allowlist. Treat any new allowlist entry as debt that needs a follow-up split or
helper extraction, not permission to add more monoliths.
