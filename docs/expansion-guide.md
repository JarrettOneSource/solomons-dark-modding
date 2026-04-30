# Expansion Guide

This workspace is intentionally split so new Solomon Dark functionality has one obvious place to land.

## Ownership boundaries

### Launcher

Path: `SolomonDarkModLauncher/src`

Owns:

- workspace discovery and instance layout
- mod discovery and enable/disable state
- staging and stage reports
- staging `.sdmod/config/binary-layout.ini`
- staging `.sdmod/config/debug-ui.ini`
- process launch and DLL injection
- user-facing CLI commands
- the machine-readable command contract consumed by the separate GUI wrapper

Does not own:

- raw game memory reads or writes
- binary compatibility rules
- runtime hooks
- Lua host APIs

If a change needs raw pointers, offsets, or in-process engine behavior, it belongs in the loader, not the launcher.

### Loader

Path: `SolomonDarkModLoader/src` and `SolomonDarkModLoader/include`

Owns:

- injected runtime bootstrap
- `.sdmod` runtime layout usage
- logging
- binary compatibility and seam verification
- parsing the staged binary layout metadata
- typed memory readers and writers
- Lua runtime hosting
- hook-backed runtime capabilities
- future native plugin ABI

Does not own:

- mod enable/disable persistence
- stage tree mirroring
- command-line UX

### Docs and scripts

Paths:

- `docs/`
- `scripts/`

Own:

- rebuild planning
- extension rules
- repeatable build and verification commands

Every new runtime subsystem should leave behind one doc entry point and one verification path.

## Recommended path for new runtime functionality

When adding new SD mod functionality, follow this order:

1. Recover or verify the binary seam in Ghidra.
2. Encode the verified seam in `config/binary-layout.ini`.
   Use `config/debug-ui.ini` for debug overlay-only runtime seams such as draw helpers or renderer globals.
3. Add or extend the loader-side typed reader/writer layer.
4. Add a small loader-owned runtime module for the capability.
5. Expose a narrow semantic surface to Lua or the launcher only after the capability is stable.
6. Add a verification step that proves the new module initializes or behaves correctly.
7. Update the rebuild roadmap or README if the new system changes the project shape.

## Rules for keeping the project hygienic

- Keep the launcher as orchestration only.
- Keep the CLI authoritative and make any launcher UI a separate wrapper project over the same command surface.
- Keep raw Win32 interop in dedicated launcher `Native` files instead of scattering `DllImport` declarations.
- Keep raw offsets and function addresses in `config/binary-layout.ini`, not in loader source files.
- Keep raw pointer math inside loader internals and move callers toward typed helper APIs.
- Prefer one small capability module per feature area over a single expanding runtime file.
- Do not expose raw addresses or offsets directly to Lua mods.
- Do not add fallback paths for multiple runtime models unless you intentionally decide to support them.

## Loader `.inl` organization

The loader uses `.inl` files as translation-unit fragments for hook-heavy code
that needs access to anonymous-namespace state in a parent `.cpp`. Treat those
files as a compatibility tool, not as a substitute for normal module design.

Rules:

- Keep parent `.inl` files as thin aggregators when an area grows beyond a few cohesive functions.
- Put grouped fragments in a named folder that describes the feature area, such as `bot_runtime/public_api/`, `mod_loader_gameplay/core/`, `mod_loader_gameplay/gameplay_hooks/`, or `mod_loader_gameplay/bot_casting/`.
- Split only on real declarations or complete function boundaries. Do not hide sections of one large function behind nested `#include` directives.
- If one function grows into a monolith, extract named helpers or a small context object before splitting files; do not hide pieces of one oversized function behind nested textual includes.
- Add every new fragment to `SolomonDarkModLoader.vcxproj` and `SolomonDarkModLoader.vcxproj.filters` so Visual Studio mirrors the source layout.
- Prefer a real `.cpp` and header when a subsystem no longer needs parent anonymous-namespace access.

The enforceable source layout policy is in `docs/source-organization.md`.
Run `scripts/Check-SourceOrganization.ps1` before adding new loader fragments.

## Near-term extension points

The next clean additions are:

- typed SD state readers on top of `ProcessMemory`
- config-driven gameplay seams that can be promoted cleanly into typed readers instead of one-off probes
- first-class gameplay UI surfaces for `pause_menu`, `inventory`, `skills`, `spell_picker`, and `book_picker`
- a broader Lua/runtime API built on top of the existing `sd.ui`, `sd.input`, `sd.hub`, and future typed gameplay/state readers

The longer-term roadmap is in `docs/sd-framework-rebuild-roadmap.md`.
