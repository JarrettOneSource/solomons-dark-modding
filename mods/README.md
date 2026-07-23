# Mods

This folder is the default mods root for `SolomonDarkModLauncher`.

Current support:

- each mod is discovered from `manifest.json`
- local overlay source files live under `files/`
- website-distributed overlays are Boneyards or art assets
- runtime Lua entry scripts must live under `scripts/`
- overlays are copied on top of the staged game tree in priority order
- Lua mods are staged into `.sdmod/runtime/` and loaded by the injected loader

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
- `lua_damage_filter_lab` (opt-in owner-side incoming-damage rewrite example)
- `lua_hud_showcase` (opt-in immediate-mode text, primitives, stock sprites, and world marker)
- `lua_spell_cast_filter_lab` (opt-in one-shot owner-side primary-cast cancellation example)
- `lua_ui_sandbox_lab` (semantic UI lab presets backed by live snapshots and engine-level action activation; preset selected via config file or environment)
- `skill_shock_nova`
- `story_custom_intro`
- `wave_fast_start`
