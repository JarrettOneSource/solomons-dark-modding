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

- `sd.settings.get(key) -> boolean | number | string | table`
  returns one non-action value. An unknown key or action returns
  `nil, error_string`. A `list` value is an array of flat row tables. Each call
  returns fresh tables; changing them does not change the effective value.
- `sd.settings.get_all() -> table` returns every effective non-action value.
- `sd.settings.on_changed(fn) -> true` registers
  `fn(key, new_value, old_value)`. It fires once per live-applied local value or
  host replication update. It never fires for `requires_restart`.
  A list change fires once for the list key with the complete new and old
  arrays; there are no row-level callbacks.
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

## Structured lists

A `list` declaration contains `min_items`, required `max_items` (1–32), an
optional 64-character `item_label`, and `item.fields`. Each list has 1–12
flat fields, and each field reuses the existing `toggle`, `number`, `text`, or
`choice` schema. Keybinds, actions, and nested lists are rejected. Missing row
fields take their field defaults; unknown fields are rejected.

```json
{
  "key": "roster",
  "type": "list",
  "label": "Bot roster",
  "scope": "host",
  "min_items": 0,
  "max_items": 3,
  "item_label": "{name} · {element}",
  "item": {
    "fields": [
      {
        "key": "name",
        "type": "text",
        "label": "Name",
        "default": "Ember",
        "max_length": 31
      },
      {
        "key": "element",
        "type": "choice",
        "label": "Element",
        "default": "fire",
        "choices": [
          { "value": "fire", "label": "Fire" },
          { "value": "water", "label": "Water" }
        ]
      }
    ]
  },
  "default": [
    { "name": "Ember", "element": "fire" }
  ]
}
```

The default, persisted value, replicated value, and Lua value all have the same
ordered JSON-array shape. The normalized compact serialization is limited to
8192 UTF-8 bytes at declaration and at Save/reload. Host replication uses the
existing reliable `SDMOD:settings` mod-state stream and preserves list order.
Invalid persisted list values fall back to the manifest default like invalid
scalar values.

## Effective values

At launch, each value is the valid persisted value or its manifest default.
`local` values remain machine-local. During a live multiplayer session, `host`
values come from the authority's reliable mod-state stream; clients revert to
their launch-effective local values when the session ends. Host actions are
rejected on clients.

The launcher Save order is atomic persistence followed by the owned instance's
named-pipe reload call. Reload diffs only entries without `requires_restart`.
Reload returns `entry_errors`, keyed by setting key, when a value is rejected
or a mod's live-apply callback cannot reconcile it. Other valid keys still
apply, and a callback failure is reported rather than crashing the game.
The internal `sd.__settings_reload` and `sd.__settings_invoke_action` functions
exist only during privileged exec-pipe requests. They are not mod API functions,
cannot be requested in a manifest, and are removed again before normal mod code
continues.

## Reference implementation and acceptance

`mods/bot-brain` declares the v1 scalar/action controls plus the v2 `roster`
list. It applies kite radius, offense, think cadence, per-row bot identity,
focus key, and roster respawn behavior. The cadence selector applies to
Skirmisher, Guardian, and Striker; Learned rows use a fixed 100 ms
simulation-time decision interval. Run the isolated lifecycle acceptance after
a Release build:

```bash
python3 tools/verify_mod_settings_lifecycle.py
```

It uses only `ms2-host`/`ms2-client`, UDP ports 49211/49212, disabled audio,
and exact launcher-returned staged process IDs. It proves two-row startup and
replication, copied Lua list reads, ordered removal and element respawn,
guardian/striker/skirmisher behavior and a slot-exhaustion `entry_errors`
result without a crash. Results and copied runtime logs are written under
`/mnt/d/codex-evidence/mod-settings-v2-20260727/`. Learned policy operation and
training are documented in [`ml-bot.md`](ml-bot.md); its settings shape is
covered by the static ML bot contract.
