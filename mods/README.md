# Mods

This folder is the default mods root for `SolomonDarkModLauncher`.

Current support:

- each mod is discovered from `manifest.json`
- mods can be pure overlays, pure runtime mods, or hybrids
- overlay source files must live under `files/`
- runtime Lua entry scripts must live under `scripts/`
- runtime native DLL entry points must live under `native/`
- overlays are copied on top of the staged game tree in priority order
- runtime mods are staged into `.sdmod/runtime/` and loaded by the injected loader

Example manifest:

```json
{
  "id": "example.wave_override",
  "name": "Wave Override",
  "version": "0.1.0",
  "priority": 10,
  "overlays": [
    {
      "target": "data/wave.txt",
      "source": "files/data/wave.txt",
      "format": "plaintext-wave"
    }
  ]
}
```

Included sample mods:

- `item_gold_focus`
- `lua_bots` (spawns a single patrol bot for movement, facing, and animation diagnosis)
- `lua_dark_cloud_sort_bootstrap` (semantic dialog-dismiss bootstrap to the title menu checkpoint)
- `lua_ui_sandbox_lab` (semantic UI lab presets backed by live snapshots and engine-level action activation; preset selected via config file or environment)
- `skill_shock_nova`
- `story_custom_intro`
- `wave_fast_start`
