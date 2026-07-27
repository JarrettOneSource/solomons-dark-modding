# Lua mod settings

Lua mods declare launcher-rendered settings in the top-level `settings` block of
`manifest.json`. The normative schema, persistence format, multiplayer rules,
and launcher contract are in
[`design/mod-settings-2026-07-27.md`](design/mod-settings-2026-07-27.md).

## Capability and ownership

A mod with a settings declaration lists `settings.self` in
`runtime.requiredCapabilities`. Every function below resolves against that
calling mod's declaration and effective values. There is no cross-mod read and
Lua cannot write settings.

An invalid declaration does not reject the mod. The loader emits one structured
`[mod-settings]` validation line and runs it without a settings declaration.
Persisted values live at `.sdmod/mod-settings/<mod_id>.json`; the launcher is the
only product writer.

## API

- `sd.settings.get(key) -> boolean | number | string`
  returns one non-action value. An unknown key or action returns
  `nil, error_string`.
- `sd.settings.get_all() -> table` returns every effective non-action value.
- `sd.settings.on_changed(fn) -> true` registers
  `fn(key, new_value, old_value)`. It fires once per live-applied local value or
  host replication update. It never fires for `requires_restart`.
- `sd.settings.on_action(key, fn) -> true` registers the calling mod's action
  handler. Registration rejects unknown and non-action keys.
- `sd.settings.is_keybind_down(entry_key) -> bool` resolves a declared keybind
  entry, then passively reads its canonical Win32 key. `NONE` is always false.
  Other/unknown entry types return `nil, error_string`.

`is_keybind_down` is true only while a window owned by the game process is the
foreground window. It uses the high bit from `GetAsyncKeyState`; it does not
consume messages, inject input, or perturb the stock input queue. Mods implement
their own rising/falling edge detection. Existing acceptance harnesses can still
inject keyboard messages or state into their exact game window; a foreground
key-state check simply observes the resulting state when that window is active.
The canonical names are `A`–`Z`, `0`–`9`, `F1`–`F24`, `SPACE`, `TAB`, `ENTER`,
`SHIFT`, `CTRL`, `ALT`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `MOUSE3`, `MOUSE4`,
`MOUSE5`, and `NONE`.

## Effective values

At launch, each value is the valid persisted value or its manifest default.
`local` values remain machine-local. During a live multiplayer session, `host`
values come from the authority's reliable mod-state stream; clients revert to
their launch-effective local values when the session ends. Host actions are
rejected on clients.

The launcher Save order is atomic persistence followed by the owned instance's
named-pipe reload call. Reload diffs only entries without `requires_restart`.
The internal `sd.__settings_reload` and `sd.__settings_invoke_action` functions
exist only during privileged exec-pipe requests. They are not mod API functions,
cannot be requested in a manifest, and are removed again before normal mod code
continues.

## Reference implementation and acceptance

`mods/bot-brain` declares all six v1 types and applies kite radius, offense,
think cadence, persona, focus key, and respawn behavior. Run the isolated
lifecycle acceptance after a Release build:

```bash
python3 tools/verify_mod_settings_lifecycle.py
```

It uses only `mset-host`/`mset-client`, UDP ports 49011/49012, disabled audio,
and exact launcher-returned staged process IDs. Results and copied runtime logs
are written under `/mnt/d/codex-evidence/mod-settings-20260727/`.
