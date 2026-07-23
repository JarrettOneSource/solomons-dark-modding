# Lua UI authoring

`sd.ui` can retain mod-owned surfaces and render them with Solomon Dark's
native panel and exact-text helpers. The authored API sits beside the existing
read-only snapshot and semantic automation API; it does not expose native
pointers, controls, Direct3D objects, or game addresses to Lua.

## API

Create a surface first. Coordinates and sizes are normalized from `0` through
`1`; a surface is relative to the viewport, while child elements are relative
to their parent surface or panel.

```lua
local surface = sd.ui.create_surface({
  id = "settings",
  title = "My mod",
  x = 0.25,
  y = 0.2,
  width = 0.5,
  height = 0.6,
  modal = true,
  close_on_escape = true,
})

local body = sd.ui.create_panel(surface, {
  id = "body", x = 0.05, y = 0.15, width = 0.9, height = 0.75,
})

local status = sd.ui.create_label(body, {
  id = "status", text = "Ready", x = 0.05, y = 0.08,
  width = 0.9, height = 0.12,
})

local apply = sd.ui.create_button(body, {
  id = "apply",
  label = "Apply",
  x = 0.15, y = 0.65, width = 0.7, height = 0.16,
  execution = "presentation",
  on_activate = function(action)
    sd.ui.set_text(status, "Applied request " .. action.request_id)
  end,
})

sd.ui.show(surface)
```

The authored functions are:

- `create_surface(options) -> handle`
- `create_panel(parent, options) -> handle`
- `create_label(parent, options) -> handle`
- `create_button(parent, options) -> handle`
- `show(surface)`, `hide(surface)`, and `destroy(surface)`
- `set_text(element, text)`, `set_enabled(button, enabled)`, and
  `focus(button)`
- `get_authored_state(surface) -> table|nil`

`sd.ui.activate_action(action_id, surface_id)` and
`sd.ui.perform({surface_id=..., action_id=...})` resolve visible authored
buttons before falling back to stock semantic UI navigation. Keyboard, mouse,
and programmatic activation all enter the same queued action path. Modal
surfaces consume the corresponding game-window input. Up/Down/Tab changes the
selected enabled button, Enter/Space activates it, and Escape applies the
surface's `close_on_escape` policy.

## Action execution classes

Every button declares one of two execution classes:

- `presentation` is the default. Its callback executes only on the local peer
  and never produces a network packet.
- `simulation` is for callbacks that mutate shared state. A host or standalone
  game executes it locally. A multiplayer client automatically sends a bounded
  reliable request to the authority instead of running the callback.

The authority accepts a routed action only when the source endpoint,
participant identity, participant session nonce, monotonically increasing
request id, mod id, surface id, and enabled simulation-class action all match
its live registrations. Lua runs later in the normal game-thread pump, never in
the window procedure, render hook, socket receive path, or Steam callback.

The callback receives:

```lua
{
  surface_id = "settings",
  action_id = "apply",
  execution = "presentation", -- or "simulation"
  participant_id = 0,          -- nonzero in an active MP transport
  request_id = 1,
  routed = false,
}
```

`close_on_activate` hides the surface on the peer that pressed the button. It
does not close the authority's local presentation when a remote simulation
request arrives.

## Ownership and limits

Handles are positive opaque integers scoped to the creating mod. Passing a
foreign or stale handle fails. Unknown option fields fail rather than being
ignored. IDs contain 1–64 lowercase letters, digits, `_`, `-`, or `.`.

Limits are enforced before retention:

- 8 surfaces per mod and 64 globally
- 16 panels, 64 labels, and 32 buttons per surface
- 256 bytes per title, 1,024 bytes per label/button string, and 8 KiB total
  text per surface
- 128 pending semantic actions and 64 pending client-to-authority requests

Destroying a surface or unloading its mod removes its render model, pending
actions, and Lua registry references. Disabled buttons cannot receive focus or
activation.

## Native rendering seam

The loader retains the semantic model, but presentation uses the game's own UI
engine helpers from `[lua_ui_authoring]` in `binary-layout.ini`:

- `UiPanel_Render` (`0x005C3F40` for 0.72.5)
- `ExactText_Render` (`0x0043BCD0`)
- the game `String` assignment helper (`0x00402AE0`)
- the exact-text object under the live UI/font bundle
- the live UI render-context color helper (`0x0041FE50`)

The shared D3D9 EndScene hook supplies frame timing and state preservation; it
does not replace panels or text with loader-drawn primitives. Native calls are
SEH-guarded, D3D state is restored after the authored pass, and a native draw
fault disables further authored rendering for the process.

## Capabilities and verification

The seam advertises `ui.authoring.native`, `ui.action.presentation`, and
`ui.action.simulation.route`. `tools/verify_lua_ui_authoring.py` checks the live
address-free API and ownership/error contract. It also captures the real D3D9
backbuffer before and after showing its authored surface and requires localized
pixel changes inside the surface bounds:

```bash
py -3 tools/verify_lua_ui_authoring.py --game-path-kind windows
```

Use `--game-path-kind proton` for a Proton launch. The static contract
additionally checks the native layout, callback lifecycle, input queue, protocol
envelope, authority validation, docs, and opt-in sample.
Live presentation verification must be run when the game desktop is
available; build/static success alone does not prove the native panel and text
calls on a rendered frame.
