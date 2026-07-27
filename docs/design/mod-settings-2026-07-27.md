# Lua mod settings — declaration, persistence, live-apply, and launcher UI (2026-07-27)

Owner-requested system: the launcher's Mods tab lists installed mods; every mod
that declares settings gets a Settings button on its row; the settings form is
rendered dynamically from the mod's declaration. This document is the NORMATIVE
CONTRACT between the backend (loader parsing/validation/persistence/runtime API/
replication/IPC — codex) and the frontend (launcher WPF views — Claude/ATC).
Neither side may deviate without updating this document in the same commit.

Owner-locked decisions: surface = launcher Mods tab (not in-game); datatypes =
toggle, number, text, choice, keybind, action. Settings still live-apply into a
running game through the existing Lua exec pipe; action buttons invoke through
the same pipe and are disabled when no owned game instance is running.

## 1. Declaration — `settings` block in `manifest.json`

A sibling of `runtime`, statically readable without executing Lua:

```json
{
  "id": "bot.brain",
  "name": "Bot Brain",
  "settings": {
    "version": 1,
    "entries": [
      { "key": "kite_radius", "type": "number", "label": "Kite radius",
        "description": "Threat sampling distance in world units.",
        "default": 340, "min": 100, "max": 900, "step": 10, "integer": true,
        "scope": "host", "group": "Combat" },
      { "key": "offense_enabled", "type": "toggle", "label": "Cast at enemies",
        "default": true, "scope": "host", "group": "Combat" },
      { "key": "persona_name", "type": "text", "label": "Bot name",
        "default": "Ember", "max_length": 31, "scope": "host",
        "requires_restart": true },
      { "key": "think_profile", "type": "choice", "label": "Think cadence",
        "default": "standard",
        "choices": [ { "value": "standard", "label": "Standard (250 ms)" },
                     { "value": "relaxed",  "label": "Relaxed (400 ms)" } ] },
      { "key": "focus_bot_key", "type": "keybind", "label": "Focus camera on bot",
        "default": "NONE", "scope": "local" },
      { "key": "respawn_bot", "type": "action", "label": "Respawn bot",
        "confirm": true, "scope": "host" }
    ]
  }
}
```

### Common entry fields

| Field | Rule |
| --- | --- |
| `key` | required, `^[a-z0-9_]{1,48}$`, unique within the mod |
| `type` | required: `toggle` \| `number` \| `text` \| `choice` \| `keybind` \| `action` |
| `label` | required, 1–64 chars |
| `description` | optional, ≤256 chars, rendered as help text |
| `group` | optional, ≤32 chars; entries render grouped under section headers in declaration order |
| `scope` | optional, `local` (default) \| `host` — see §4 |
| `requires_restart` | optional bool, default false; persisted but never live-applied; UI badges "applies next launch" |
| `default` | required for every type except `action`; must itself validate |

### Per-type fields

- **toggle** — `default`: bool. UI: checkbox/switch.
- **number** — `min` and `max` required (min < max), `step` optional (>0,
  default 1), `integer` optional (default false; when true min/max/step/default
  must be integral). `default` within [min, max]. UI: slider + numeric box;
  values clamp to [min, max] and snap to step.
- **text** — `max_length` optional (1–1024, default 256), `placeholder`
  optional. Single line, UTF-8; the loader rejects values exceeding
  `max_length` bytes.
- **choice** — `choices` required: 2–32 objects `{ "value", "label" }`, values
  unique non-empty strings ≤64 chars; `default` ∈ values. UI: dropdown.
- **keybind** — `default` from the canonical key-name set below. UI: click,
  then press-to-capture; Esc cancels; Delete/Backspace clears to `NONE`.
- **action** — no `default`, never persisted. Optional `confirm`: bool (UI asks
  before invoking). UI: button; enabled only while an owned game instance is
  running (and, for `scope: "host"`, only when that instance is the session
  host).

Canonical keybind names (the single shared namespace; launcher captures WPF
keys into it, the loader maps it to Win32 VKs): `A`–`Z`, `0`–`9`, `F1`–`F24`,
`SPACE`, `TAB`, `ENTER`, `SHIFT`, `CTRL`, `ALT`, `UP`, `DOWN`, `LEFT`,
`RIGHT`, `MOUSE3`, `MOUSE4`, `MOUSE5`, `NONE` (unbound). v1 is a single key —
no modifier chords.

### Validation failure is fail-safe

An invalid `settings` block (bad schema, duplicate keys, invalid defaults)
never blocks the mod: the loader logs one structured error, treats the mod as
having no settings, and the launcher shows a warning icon in place of the
Settings button with the validation message as tooltip. Both sides implement
identical validation from this section; the shared rules live in one C# service
class (launcher) and one C++ validator (loader) with a common test vector file
`tests/fixtures/mod-settings-validation-vectors.json` exercised by both suites.

## 2. Persistence

Per mod, per install stage: `.sdmod/mod-settings/<mod_id>.json`

```json
{ "schemaVersion": 1, "values": { "kite_radius": 400, "focus_bot_key": "F6" } }
```

- Writer: the launcher (and only the launcher) on Save.
- Reader: the loader at mod start and on live reload; the launcher on dialog open.
- Precedence: valid persisted value → else manifest default. Invalid or unknown
  persisted entries are ignored (logged), then pruned on the launcher's next
  write. `action` entries never appear.
- Atomic write (temp file + rename) so a mid-write game read never sees a torn file.

## 3. Runtime Lua API — capability `settings.self`

Mods that declare a `settings` block must list capability `settings.self` to
read them. All access is to the mod's OWN settings; there is no cross-mod read
in v1. Values from Lua are read-only in v1 (the UI is the single writer).

- `sd.settings.get(key)` → typed value (boolean | number | string | list
  array). A list is returned as a fresh array of fresh flat row tables on every
  read, so mutating the Lua copy cannot mutate effective settings. Unknown key
  → nil + error string.
- `sd.settings.get_all()` → table of key → value.
- `sd.settings.on_changed(fn(key, new_value, old_value))` — fires for each
  changed key on live-apply and on host-scope replication updates. Never fires
  for `requires_restart` entries mid-session.
- `sd.settings.on_action(key, fn())` — registers the handler an action button
  invokes. Invoking an unregistered action is a logged no-op that reports an
  error back to the launcher (§5).
- `sd.settings.is_keybind_down(entry_key)` → bool. The argument is the calling
  mod's declared `keybind` entry key, not a canonical key name. Unknown or
  non-keybind entries return nil + error string, matching `get`. `NONE` always
  returns false. The loader passively reads the mapped Win32 virtual-key state
  (including `MOUSE3`–`MOUSE5`) and returns true only while the game process owns
  the foreground window. It never consumes, injects, or changes the game's input
  queue. This remains under `settings.self`; per-mod entry lookup is the privacy
  boundary. Mods own rising/falling edge detection. Harness keyboard injection
  continues to coexist with this read path when it targets and foregrounds the
  game window.

## 4. Multiplayer scope (framework-owned, per the multiplayer-native mandate)

- `local` — per machine, no replication.
- `host` — host-authoritative session state. While a multiplayer session is
  live, the host's effective values replicate to every client on the existing
  reliable session-state seam (backend chooses the concrete channel and
  documents it); client-side `sd.settings.get` returns the replicated value and
  `on_changed` fires on updates. Client launcher UI renders host-scope entries
  read-only with a "(host)" badge while the client is in a session. On session
  end clients revert to their local persisted/default values. Host-scope
  `action` invokes are host-only; the loader rejects them elsewhere.

## 5. Live-apply IPC (launcher → running game)

Transport: the existing per-instance Lua exec pipe
(`SolomonDarkModLoader_LuaExec_<instance>`), which the launcher already owns
for the instances it launches. Two privileged internal bindings (NOT exposed to
mod capability grants; exec-pipe callers only):

- `sd.__settings_reload("<mod_id>")` — loader re-reads the persisted file,
  validates, diffs against effective values, applies, fires `on_changed` per
  changed key, and returns a result table
  `{ ok, changed = {...}, entry_errors = { [key] = message }, error }`
  serialized back over the pipe. `entry_errors` reports value rejection and a
  consumer's `on_changed` apply failure (for example, a roster row that cannot
  claim a gameplay slot) without crashing or suppressing other keys.
- `sd.__settings_invoke_action("<mod_id>", "<key>")` — runs the registered
  handler; returns `{ ok, error }` (unregistered handler or scope violation is
  `ok = false`).

Launcher flow on Save: persist file (§2) → if an owned instance is running,
send `__settings_reload` for that mod → surface the returned per-key result
(silent on success; inline error banner on failure). `requires_restart` keys
persist but are excluded from the live diff by the loader.

## 6. Launcher UI (frontend contract)

Mods tab: one row per installed mod (discovered from the managed stage's
`mods/` directory manifests): name, version, enabled state, and a Settings
(gear) button iff the manifest declares ≥1 valid settings entry (warning icon
on invalid block, §1). Settings dialog: mod name + version header; entries in
declaration order under group headers; per-type controls per §1; inline
validation (Save disabled while invalid); Reset to defaults (per-dialog,
confirm); "Live" indicator when an owned instance is running (else values save
for next launch); host-scope entries read-only "(host)" when this machine is an
in-session client; action buttons per §1. Keyboard navigable; keybind capture
per §1.

## 7. Division of labor and acceptance

Backend (codex agent `mod-settings`): C++ manifest settings parse+validation +
fail-safe, persistence reader, `settings.self` capability + `sd.settings.*`,
privileged reload/invoke bindings over the exec pipe, host-scope replication on
the session seam, C# service layer in the launcher solution (manifest settings
model + shared validator, settings store read/write, pipe client calls) exposed
behind interfaces the UI consumes, the shared validation vector file + tests on
both sides, static contracts for any new native address, dogfood settings block
in `mods/bot-brain` wired to real brain constants (kite radius, offense toggle,
think profile, persona name w/ restart, focus keybind, respawn action), and a
loopback verifier proving: persisted values reach `sd.settings.get`; live
reload fires `on_changed` and measurably changes brain behavior (kite radius);
host-scope replication reaches a client mod; action invoke round-trips; restart
gating holds. Full battery green before push.

Frontend (Claude/ATC, personally): the WPF Mods tab row affordance + settings
dialog per §6, the dynamic form renderer over the C# service interfaces, the
keybind capture control, validation UX, live/host badges, and visual polish.
Frontend lands after the backend's service interfaces exist on main; visual
acceptance = screenshots of the dialog rendering the bot-brain dogfood block
(all six types) in idle, live, and in-session-client states.

## 8. Out of scope v1 (explicit)

In-game settings overlay; modifier-chord keybinds; multiline/rich text; color
type; cross-mod settings reads; Lua-side writes; per-profile setting sets;
website surface. Each is additive later without contract breaks. Structured
list entries were promoted out of this section into §10 (v2) on 2026-07-27 by
owner request.

## 10. v2 — structured `list` entries (owner-requested 2026-07-27)

Motivating case: the bot-brain roster — add/remove bots and pick each bot's
element and discipline. The general capability is an ordered list of composite
items; a `list` entry closes the whole "custom datatype" class (rosters, loot
tables, schedules) without new per-mod machinery.

### Declaration

```json
{ "key": "roster", "type": "list", "label": "Bot roster",
  "scope": "host", "group": "Bots",
  "min_items": 0, "max_items": 4,
  "item_label": "{name} · {element} {discipline}",
  "item": { "fields": [
    { "key": "name", "type": "text", "label": "Name",
      "default": "Ember", "max_length": 31 },
    { "key": "element", "type": "choice", "label": "Element",
      "default": "fire",
      "choices": [ { "value": "fire", "label": "Fire" },
                   { "value": "water", "label": "Water" },
                   { "value": "earth", "label": "Earth" },
                   { "value": "air", "label": "Air" },
                   { "value": "ether", "label": "Ether" } ] },
    { "key": "discipline", "type": "choice", "label": "Discipline",
      "default": "skirmisher",
      "choices": [ { "value": "skirmisher", "label": "Skirmisher — kite and cast" },
                   { "value": "guardian", "label": "Guardian — protect a player" },
                   { "value": "striker", "label": "Striker — aggressive pressure" } ] }
  ] },
  "default": [ { "name": "Ember", "element": "fire",
                 "discipline": "skirmisher" } ] }
```

### Rules

- `item.fields`: 1–12 fields; field types are `toggle` | `number` | `text` |
  `choice` ONLY (no keybind/action/list inside items — validation stays
  recursive-but-bounded and rows render as a flat sub-form). Field keys obey
  the §1 key rules, unique within the item.
- `min_items` (default 0) ≤ `max_items` (required, 1–32). `default` is an
  array whose every item validates against `item.fields` (missing fields take
  the field default; unknown fields are invalid) and whose length is within
  bounds.
- `item_label`: ≤64 chars; `{field_key}` placeholders substitute that field's
  display value (choice → its label) for row headers in the UI and for logs.
- One `list` value serializes as a JSON array of flat objects; the persisted
  form (§2), the replicated form (§4), and the Lua form are the same shape. A
  mod's total serialized list value is capped at 8192 UTF-8 bytes; the
  validator rejects declarations whose worst-case default exceeds it and the
  store/runtime reject oversized saves with a per-entry error.
- Lua: `sd.settings.get("roster")` returns an array of tables (copies, still
  read-only); `on_changed` fires once per changed list KEY with the whole new
  and old arrays. Item-level diffing is the mod's business.
- `requires_restart`, `scope`, and validation fail-safe behave exactly as for
  scalar entries.

### UI (frontend contract)

A list entry renders as a card: header row (label, badges, "n of max" count),
one row per item showing its `item_label` with expand/edit, remove, and
move-up/down affordances, and an Add button (disabled at `max_items`; new items
are created from field defaults and open expanded). Expanded rows reuse the §1
per-type controls verbatim. Inline validation per field; the entry is invalid
(Save gated) while any row field is invalid or the count is out of bounds.
Read-only/host lock dims the whole card and disables all affordances.

### Bot-brain roster semantics (reference consumer, binding for the mod)

The dogfood `roster` above replaces the single hard-coded bot. On apply (start
or live reload/replication), the brain reconciles running bots against the
roster by list order: missing bots spawn (subject to free gameplay slots —
spawn rejection surfaces in the entry error, not a crash), removed bots
despawn, and a row whose element or discipline changed respawns that bot. The
`persona_name` scalar entry is superseded by per-row names and is removed from
the dogfood block in the same commit. Disciplines are brain profiles (ATC
spec): `skirmisher` = the shipped kite-and-cast behavior; `guardian` = anchor
within a leash radius of the nearest human player, engaging only threats that
approach the ward; `striker` = tighter engage range, faster cast cadence,
flee threshold at 20% instead of 35%. All three keep native traversability,
the replicated cast ingress, and the wave-transition movement rules.

### Sequencing note

v2 work lands only after the v0.1.0-beta.19 tag is verified; the release is
pinned to main `9720424` and this addendum ships in the first post-release
commit.

## 9. Implementation notes

- Native declaration, value, and persistence validation lives in
  `SolomonDarkModLoader/src/mod_settings*.cpp`; Lua/runtime behavior lives in
  `lua_settings_runtime.cpp` and `lua_engine_bindings_settings.cpp`.
  `settings.self` is grantable, but the two `sd.__settings_*` functions are
  installed only for a currently executing named-pipe request and are never
  capability-grantable.
- Host values use the existing reliable Lua mod-state stream:
  `SetLuaModStateValue` plus `PublishAuthoritativeLuaModStateSet`, including its
  ordered revisions and periodic/late-join checkpoints. Framework settings use
  the reserved, manifest-impossible state identifier `SDMOD:settings`, with each
  key prefixed by the owning mod's staged storage hash. A client considers the
  session live only after it has a nonzero authority participant ID; it then
  reads host values from this stream and reverts to its launch-effective local
  values when that ID clears. `requires_restart` host values can change the
  read-only effective view on session join/end without a callback, but a Save
  never replaces or republishes the launch-effective value.
- Launcher backend files are under
  `SolomonDarkModLauncher/src/ModSettings/`. Discovery reads the launcher's
  managed installed-mods root (`WorkspacePaths.ModsRootPath`); persistence
  reads/writes the selected instance stage's `.sdmod/mod-settings/`.
  `ModSettingsService` keeps those roots explicit and composes discovery,
  storage, owned-instance state, reload, and action calls behind the interface
  consumed by a thin WPF adapter. Shared vectors are
  `tests/fixtures/mod-settings-validation-vectors.json`.
- Structured-list declarations are represented by the existing
  `ModSettingEntry` / `ModSettingDefinition` models: list bounds, row label,
  and bounded scalar item fields are properties of the same entry. Values use
  the existing `ModSettingValue` discriminated model with an ordered list of
  flat objects. Both validators normalize missing row fields from their
  declared defaults before validating the 8192-byte compact UTF-8 JSON cap.
  Persistence writes JSON arrays of flat objects; host scope converts that
  same normalized shape to an array of Lua mod-state objects on the reserved
  `SDMOD:settings` stream. Save validation failures and runtime callback
  failures are returned in the reload result's `entry_errors` map.
- `mods/bot-brain/scripts/roster.lua` owns list-order reconciliation and
  `brain.lua` owns one behavior context per roster row. Changed rows are
  retired before replacements spawn; failed spawns remain desired and retry
  on later authority ticks while the immediate reload reports the numbered row
  error. All mutations still use bot handles, native path tests, and slot-0
  replicated cast ingress.
- `mods/bot-brain/` exercises every v1 type. End-to-end acceptance is
  `tools/verify_mod_settings_lifecycle.py`, fixed to the isolated `ms2` pair
  and ports 49211/49212. It also exercises the v2 roster on both peers,
  ordered despawn/respawn, all three disciplines, and slot-exhaustion errors.
  No new Solomon Dark native address or layout offset was added. Keybind reads
  use only the operating-system `GetForegroundWindow`,
  `GetWindowThreadProcessId`, and `GetAsyncKeyState` APIs.
