# Lua Memory Tooling

This is the primary live-memory RE workflow for Solomon Dark.

Use it before attaching an external debugger. It is fast, game-aware, and already integrated with the loader's runtime pipe.

## Entry Points
- WSL / Python:
  - `python tools/lua-exec.py "<lua code>"`
- PowerShell:
  - `powershell.exe -NoProfile -File scripts/Invoke-LuaExec.ps1 -Code "<lua code>"`
- Higher-level helper:
  - `python tools/live_bot_render_debug.py`

## Core `sd.debug` APIs

### Scalar reads and writes
- `sd.debug.read_u8(address)`
- `sd.debug.read_u16(address)`
- `sd.debug.read_u32(address)`
- `sd.debug.read_i8(address)`
- `sd.debug.read_i16(address)`
- `sd.debug.read_i32(address)`
- `sd.debug.read_float(address)`
- `sd.debug.read_ptr(address)`
- `sd.debug.write_u8(address, value)`
- `sd.debug.write_u16(address, value)`
- `sd.debug.write_u32(address, value)`
- `sd.debug.write_float(address, value)`
- `sd.debug.write_ptr(address, value)`

### Pointer-chain helpers
- `sd.debug.resolve_ptr_chain(ptr_slot_address, {off0, off1, ...})`
- `sd.debug.resolve_object_ptr_chain(base_address, {off0, off1, ...})`
- `sd.debug.dump_ptr_chain(ptr_slot_address, {off0, off1, ...})`
- `sd.debug.dump_object_ptr_chain(base_address, {off0, off1, ...})`
- `sd.debug.snapshot_ptr_chain(name, ptr_slot_address, {off0, off1, ...}, size)`
- `sd.debug.snapshot_object_ptr_chain(name, base_address, {off0, off1, ...}, size)`

### Watches and diffs
- `sd.debug.watch(name, address, size)`
- `sd.debug.watch_ptr_field(ptr_slot_address, offset, size, name)`
- `sd.debug.watch_write(name, address, size)`
- `sd.debug.watch_write_ptr_field(ptr_slot_address, offset, size, name)`
- `sd.debug.list_watches()`
- `sd.debug.unwatch(name)`
- `sd.debug.snapshot(name, address, size)`
- `sd.debug.snapshot_ptr_field(name, ptr_slot_address, offset, size)`
- `sd.debug.snapshot_nested_ptr_field(name, ptr_slot_address, outer_offset, inner_offset, size)`
- `sd.debug.snapshot_double_nested_ptr_field(name, ptr_slot_address, outer_offset, middle_offset, inner_offset, size)`
- `sd.debug.diff(name_a, name_b)`

### Function tracing
- `sd.debug.trace_function(address, name[, patch_size])`
- `sd.debug.untrace_function(address)`
- `sd.debug.list_traces()`
- `sd.debug.get_last_error()`
- `sd.debug.get_trace_hits([name])`
- `sd.debug.clear_trace_hits([name])`

Each trace hit currently captures:
- requested and resolved address
- thread id
- register snapshot: `eax/ecx/edx/ebx/esi/edi/ebp`
- `esp_before_pushad`
- `eflags`
- `ret`
- `arg0..arg2`

### Write-watch history
- `sd.debug.get_write_hits([name])`
- `sd.debug.clear_write_hits([name])`

Each write hit currently captures:
- requested and resolved address
- base and value address
- exact access address
- thread id
- `eip/esp/ebp/eax/ecx/edx`
- `ret`
- `arg0..arg2`
- before/after bytes

### Struct and object helpers
- `sd.debug.dump_struct(address, field_defs)`
- `sd.debug.dump_vtable(object_or_vtable_address, count[, treat_as_object])`

`dump_vtable` defaults to treating the first argument as an object address and reading its vtable pointer from `object +0x00`. Pass `false` as the third argument to treat the first argument as the vtable address directly.

### Raw bytes and search
- `sd.debug.read_bytes(address, count)`
- `sd.debug.read_string(address, max_len)`
- `sd.debug.search_bytes(start_addr, end_addr, "AA BB ?? CC")`
- `sd.debug.copy_bytes(src_addr, dst_addr, count)`
- `sd.debug.query_memory(address)`

### Narrow native-call helpers
- `sd.debug.call_thiscall_u32(function_address, this_ptr, arg0)`
- `sd.debug.call_thiscall_u32_ret_u32(function_address, this_ptr, arg0)`
- `sd.debug.call_thiscall_out_f32x4_u32(function_address, this_ptr, arg0)`
- `sd.debug.call_cdecl_u32_ret_u32(function_address, arg0)`
- `sd.debug.call_cdecl_u32_u32(function_address, arg0, arg1)`

### Gameplay-specific typed helpers
- `sd.gameplay.get_selection_debug_state()`
  - returns:
    - `table_address`
    - `entry_count`
    - `slot_selection_entries[1..4]`
    - `player_selection_state_0`
    - `player_selection_state_1`

`query_memory` now resolves game-image addresses the same way `trace_function` does. The returned table includes:
- `requested_address`
- `resolved_address`
- `translated`
- `base/end/state/protect/type`
- `committed/guarded/no_access/readable/writable/executable`

## Common Workflows

### 1. Compare stock player vs bot sink-owned visuals
```lua
local player = sd.player.get_state()
local bot = sd.bots.get_state(BOT_ID)
print(string.format("player attach object = 0x%X", player.attachment_visual_lane.current_object_address or 0))
print(string.format("bot attach object    = 0x%X", bot.attachment_visual_lane.current_object_address or 0))
print(string.format("player primary type  = 0x%X", player.primary_visual_lane.current_object_type_id or 0))
print(string.format("bot primary type     = 0x%X", bot.primary_visual_lane.current_object_type_id or 0))
```

### 2. Snapshot and diff a render-owned window
```lua
sd.debug.snapshot("player_variants", player_actor + 0x23C, 8)
sd.debug.snapshot("bot_variants", bot_actor + 0x23C, 8)
sd.debug.diff("player_variants", "bot_variants")
```

### 3. Trace a stock accessor and inspect hits later
```lua
sd.debug.trace_function(0x00570D80, "equip_attachment_get")
-- trigger the behavior in-game
print(sd.inspect(sd.debug.get_trace_hits("equip_attachment_get")))
sd.debug.clear_trace_hits("equip_attachment_get")
```

### 4. Dump a live object's vtable
```lua
local object = 0x12345678
print(sd.inspect(sd.debug.dump_vtable(object, 16)))
```

## When To Use External Debugger Attach
- Use Lua first for:
  - state comparison
  - pointer chasing
  - watched writes
  - lightweight function tracing
- Use external debugger attach for:
  - single-step breakpoint work
  - full native call stacks
  - crash-time exception analysis
  - code paths that cannot be safely traced with a loader hook

Current external CLI fallback already installed:
- `/mnt/c/Program Files/WindowsApps/Microsoft.WinDbg_1.2601.12001.0_x64__8wekyb3d8bbwe/x86/cdb.exe`

## Reliability Notes
- The earlier “Lua tracing is flaky” behavior was caused by three concrete issues:
- The earlier “Lua tracing is flaky” behavior was caused by several concrete issues:
  - startup traces were sometimes armed too late, after the interesting stock function had already run
  - the sandbox config loader only copied a hardcoded allowlist of keys, so newly added `trace_*` addresses could exist in `probe-layout.ini` but still read back as `nil`
  - `query_memory` and `trace_function` were not using the same address-resolution behavior, which made some targets look invalid in one API and valid in the other
  - the sandbox claimed `active_preset.txt` support but `setup.lua` only read the environment variable, so preset-driven runs could silently use the wrong flow
  - `trace_function` used a fixed default 7-byte patch, which can split x86 instructions and crash immediately on first hit
- The current fixes are:
  - startup traces are queued and retried until they arm or timeout
  - config loading now preserves all numeric keys in each section while still validating the required baseline keys
  - `sd.debug.get_last_error()` now exposes the last native trace-arm failure reason to Lua
  - `trace_function` now rejects non-executable targets up front instead of failing later with an opaque `VirtualProtect` error
  - sandbox preset resolution now falls back to `config/active_preset.txt` when the environment variable is absent
  - `trace_function` now auto-sizes its trampoline patch on x86 instruction boundaries; for example, `EquipAttachmentSink_Attach (0x00575850)` now arms with `patch=5` instead of the old crashing `patch=7`
  - the trace hook now explicitly rejects relative-branch/call instructions in the copied prologue, because the current stub does not relocate them
  - the startup attach probe now targets the taken non-type-7 fast path at `0x005758D2` instead of the branchy function entry at `0x00575850`
  - the separate automation/background-focus crash turned out to be the same class of bug in the generic hooker: the old background-focus bypass installed a raw fixed-size hook on the game window proc and split its prologue on a non-instruction boundary
  - the loader now has a dedicated safe x86 hook path for hooks that must execute through a copied trampoline, and the background-focus bypass uses that safe installer
- Practical takeaway:
  - when a trace fails, check `sd.debug.get_last_error()` immediately
  - when comparing an address across tools, prefer `query_memory(...).resolved_address`
  - if a trace target resolves to non-executable memory, treat that as an RE bug in the mapped address, not as a hook-installer bug

## Current Rendering Investigation Focus
- Final April 14, 2026 lifecycle finding:
  - the materialized bot destroy crash was a **phase bug**
  - gameplay-world actions were being pumped from the D3D9 frame action pump, which runs in a render-phase hook
  - destroying bots from that phase left the game inside the same-frame render/list sweep and reproduced the `0x002B9A8C` access violation
  - the current safe contract is:
    - hub/menu actions may still use the frame pump
    - gameplay-world actions are pumped from the local slot-0 `PlayerActorTick` safe phase
    - destroy supersedes stale syncs before they reach the gameplay queue
  - `EquipAttachmentSink_Attach` with `item = 0` is now used as the stock detach seam for gameplay-slot visual lanes during destroy
- Final April 13, 2026 status:
  - the loader-side sprite-composition bug is fixed
  - the remaining robe/orb bug was resolved by correcting the **public element semantics**
  - the bot/runtime API is now profile-centric:
    - `sd.bots.create({ profile = { element_id=..., discipline_id=..., loadout=... }, ... })`
    - `sd.bots.update({ id=..., profile = { ... } })`
    - `sd.bots.get_state(id).profile` is now the authoritative bot character identity in Lua
  - April 18, 2026 relocation caution:
    - `sd.bots.update({ id=..., position={x,y}, heading=... })` is **not** currently a stock-safe teleport for a materialized registered `GameNpc`
    - the current gameplay update path only writes actor `x/y/heading`; it does not yet implement the full native relocation contract
    - see `docs/bugs/registered_gamenpc_transform_update_instability.md` before using position updates as a live relocation tool
  - create-screen action ids and gameplay wizard mappings had been mislabeled relative to the stock colors
  - the current authoritative user-facing mapping is:
    - `fire` -> slot `16` -> orange
    - `water` -> slot `32` -> blue
    - `earth` -> slot `40` -> green
    - `air` -> slot `24` -> cyan
    - `ether` -> slot `8` -> purple
  - the current live-memory workflow is now primarily for:
    - validating player/bot parity on a chosen element slot
    - comparing helper-item float blocks when a deeper stock-contract question remains
    - tracing future work on full discipline/loadout ownership beyond the current element-only MVP
- Important harness note:
  - `sample.lua.ui_sandbox_lab` no longer auto-spawns patrol bots during `testrun`
  - enable `sample.lua.bots` when you want the current single-bot patrol harness, or use the live debug helpers to spawn targeted test bots on demand
- Current direct-Lua comparison result:
  - `sd.player.get_state()` now exposes `primary_visual_lane`, `secondary_visual_lane`, and `attachment_visual_lane`
  - in the current stable water-bot run, player vs bot attachment lanes were both `0x1B5C` but pointed at different live objects with different payload bytes
  - the player/bot lane labels are also a naming hazard: the recovered stock holder-kind/type ordering implies our current `primary` and `secondary` names are likely reversed relative to stock semantics
- Current April 12 water-automation finding:
  - after the background-focus hook fix, the `map_create_water` harness again reaches stable `testrun`
  - both the local player and a spawned water-profile bot carry the same water progression appearance ids: `3 / 6 / 32 / 35`
  - the bot helper float4s read the expected stock-water values (`0.39679638 / 0.46394697 / 0.54945219`)
  - the automated local player helper float4s do **not** match that stock-water reference (`0.34542164 / 0.44866666 / 0.55803943`)
  - that means the automation harness is no longer crashing, but the automated local player is still not a trustworthy water visual reference
  - the new diagnostic preset family `create_ready_{earth,ether,fire,water,air}` now stops after the create-screen element/discipline clicks so stock create-state objects can be inspected before the harness transitions into gameplay
  - stock selection-state mapping was recovered from those create-ready runs through the new typed helper:
    - earth -> `0x08`
    - ether -> `0x10`
    - fire -> `0x18`
    - water -> `0x20`
    - air -> `0x28`
  - final late-April 12 heading-path finding:
    - the remaining player/bot divergence was proven with existing trace hits; no new debugger attach was needed
    - `ActorAnimation_MainPath (0x00538B80)` hits capture the glyph-row input in `arg0`
    - in the broken water run:
      - player row input was `0x0C`
      - bot row input was `0x00`
    - the same divergence reached the `0x1B5C` helper slots:
      - `item_s8` bot row input `0x00`
      - `item_s9` bot row input `0x00`
    - the direct cause was `actor +0x6C`:
      - player `+0x6C = 180.0`
      - bot `+0x6C = 0.0`
    - live patching the bot's `+0x6C` to the player's value changed the bot helper inputs from `0x00` to `0x0C` and made the visuals line up
    - the product fix was not in the orb renderer; it was in the bot request/sync layer:
      - add `has_heading`
      - do not treat `position` as “explicit heading too”
      - when heading is omitted, preserve current heading or inherit the local player's heading for first materialization
- direct mixed-element verification after the heading fix:
    - the old `prog88` trace reads were ambiguous because the function writes into a reused caller scratch buffer
    - `sd.debug.call_thiscall_out_f32x4_u32(...)` was added specifically to call `FUN_00660760` directly and return the written `vec4`
    - in a fresh `map_create_fire` stock-player run, `FUN_00660760(runtime, 0x18)` returned:
      - `0.628921 / 0.763921 / 0.763921 / 1.0`
    - in a fresh `map_create_water` run with a spawned fire bot, `FUN_00660760(fire_bot_runtime, 0x18)` returned the same:
      - `0.628921 / 0.763921 / 0.763921 / 1.0`
    - that means the current fire bot matches the stock fire player progression color path too
  - April 13, 2026 semantic remap:
    - the create-screen point indices were mislabeled in the loader metadata
    - create-screen captures and direct runtime probes now establish the correct user-facing mapping:
      - `fire`  -> stock slot `16` -> `0.600576 / 0.503076 / 0.465576 / 1.0`
      - `water` -> stock slot `32` -> `0.369926 / 0.429926 / 0.504926 / 1.0`
      - `earth` -> stock slot `40` -> `0.566191 / 0.701191 / 0.566191 / 1.0`
      - `air`   -> stock slot `24` -> `0.628921 / 0.763921 / 0.763921 / 1.0`
      - `ether` -> stock slot `8`  -> `0.533809 / 0.398809 / 0.533809 / 1.0`
    - the fixed loader now uses that semantic table consistently for:
      - create-screen automation
      - gameplay selection-state writes
      - bot appearance-choice id writes
      - stock progression color validation through `FUN_00660760`

  - April 29, 2026 frost-jet cone recovery:
    - water primary dispatches through `FUN_00543860`, then calls the shared
      cone query `FUN_00641B10`
    - live traces observed `cone=30.0`, `range=205.0`, `mask=0x1082`, and
      `self=<water bot actor>` as the query inputs for level-1 water
    - the cone query applies `cone * 0.5` around the actor heading, so level-1
      water is approximately a `30` degree total wedge (`+/-15` degrees)
    - the range input is derived as `205 + 4 * actor[0x290]`; level-1 water had
      `actor[0x290] = 0.0`, and the same field appears to drive upgraded wider
      frost behavior
    - `frost_jet.cfg` carries damage/mana only (`mDamage[1]=2.5`,
      `mManaCost[1]=12.5` per second), not geometry
