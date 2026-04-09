# Solomon Dark Mod Loader — TODO

## Phase 1: Gameplay Event Hooks

Break this into sub-sections by priority:

### 1a. Run Lifecycle
- [x] Find `run.started` dispatch point via Ghidra — `FUN_0046EA90` ("Create New ARENA", virtual method)
- [x] Find `run.ended` dispatch point via Ghidra — `FUN_005CB570` (GameOver trigger, `__cdecl`)
- [x] Implement C++ hooks and Lua bindings for `run.started` and `run.ended`
- [x] Verified: `run.started` fires on dungeon entry, `run.ended` fires on death with `reason=death`
- [ ] Add semantic payloads (run context, wave count, duration, etc.)
- [ ] Hook `run.ended` for "leave game" path (currently only catches death)
- [ ] Also hooked `FUN_004BED40` ("on START GAME") for menu-initiated new games

### 1b. Wave Hooks
- [x] Lua bindings implemented for `wave.started` and `wave.completed` (event registration, dispatch, payloads)
- [x] C++ hook infrastructure in place with wave counter and synthesized `wave.completed`
- [x] **Found correct wave dispatch point** — mid-function hook at `0x004DE670` inside FUN_004DDB00 (timeline executor), after the `CMP [EDI+0x18],4 / JNE` filter for wave-label events (type 4). Uses `__declspec(naked)` detour with PUSHAD/POPFD save/restore. Patches the `MOV EBP,[0x00B401A8]` instruction (6 bytes).
- [x] Old wrong hook at `FUN_004BC920` removed (was a generic scripting node allocator with 200+ callers)
- [ ] **Test wave hooks in-game** — verify wave.started/wave.completed fire when player walks to trigger zone
- [ ] Add semantic payloads (wave number, enemy count, etc.)

### 1x. Character Creation Automation (completed)
- [x] Implemented `dispatch_kind=owner_point_click` for create screen actions
- [x] Click handler at `0x0058BCE0` — `__thiscall(CreateWizardMenu*, int x, int y)`
- [x] Element points at `owner+0x7C` (stride 8), discipline points at `owner+0xA4` (stride 8)
- [x] Coordinates stored as floats, converted to int for the handler
- [x] Verified: element/discipline selection works cleanly, auto-advances to hub

### 1y. Testrun Automation (broken)
- [ ] `sd.hub.start_testrun()` dispatch crashes with `0xC0000005` (access violation)
- [x] Ghidra confirmed hub dispatcher `0x004BB3F0` takes the testrun branch when `param_2 == param_1 + 0xB8C0`
- [ ] Added settle/cooldown mechanism to prevent rapid-fire retries
- [ ] Investigate: direct hub dispatch still crashes, so the remaining issue is likely owner/context recovery rather than the control offset

### 1c. Combat Hooks
- [ ] Find `enemy.spawned` dispatch point via Ghidra
- [ ] Find `enemy.death` dispatch point via Ghidra
- [ ] Find `spell.cast` dispatch point via Ghidra
- [ ] Find `damage.applied` dispatch point via Ghidra (SB doesn't have this yet — SD can lead)
- [ ] Implement C++ hooks and Lua bindings for all combat events
- [ ] Add semantic payloads (enemy type, position, spell id, damage amount, etc.)

### 1d. Economy Hooks
- [ ] Find `gold.changed` dispatch point via Ghidra
- [ ] Find `drop.spawned` / `item.drop_spawned` / `gold.drop_spawned` dispatch points
- [ ] Find `consumable.drop_spawned` and `orb.spawned` dispatch points
- [ ] Implement C++ hooks and Lua bindings
- [ ] Add semantic payloads (gold amount, item type, drop position, etc.)

### 1e. Progression Hooks
- [ ] Find `level.up` dispatch point via Ghidra
- [ ] Find `skill.granted` / `skill.level_changed` dispatch points
- [ ] Find `item.equipped` / `item.unequipped` / `item.used` dispatch points
- [ ] Find `powerup.triggered` dispatch point
- [ ] Implement C++ hooks and Lua bindings
- [ ] Add semantic payloads

### 1f. Events SB Doesn't Have Yet (SD can lead)
- [ ] `player.death` event
- [ ] `item.picked_up` event
- [ ] `item.rolled` event (when item stats are determined)
- [ ] `ui.action` event (when UI actions are performed)

## Phase 2: Gameplay Control APIs

### 2a. `sd.player`
- [ ] `get_state()` — health, mana, position, level, XP, gold
- [ ] `grant_xp(amount)`
- [ ] Investigate: teleport, heal, damage, stat modification

### 2b. `sd.world`
- [ ] `get_state()` — current wave, enemies alive, drops on ground
- [ ] `spawn_enemy(type, position)` — spawn known enemy types
- [ ] `spawn_reward(type, position)` — spawn items/gold/orbs

### 2c. `sd.skills` / `sd.abilities`
- [ ] `get_state()` — current skills and levels
- [ ] `grant(skill_id)` — grant a skill
- [ ] `cast_primary()` / `cast_queued()` — trigger skill usage
- [ ] `register()` — register custom skills (later)

### 2d. `sd.items`
- [ ] `get_state()` — equipped items, inventory
- [ ] `equip(item_id)` / `unequip(item_id)`
- [ ] `use(item_id)`
- [ ] `register()` — register custom item types (later)

### 2e. `sd.waves`
- [ ] `get_state()` — current wave info
- [ ] `set_enabled(bool)` — pause/resume wave spawning
- [ ] `set_definition(wave_config)` — override wave contents
- [ ] `override_first(wave_config)` — override next wave

### 2f. `sd.entities`
- [ ] `get_state()` — query all entities (enemies, pickups, bots, players)

### 2g. `sd.nav`
- [ ] `plan_path(from, to)` — pathfinding
- [ ] `pick_waypoint()` — get navigation waypoint

## Phase 3: Hub & Shop UI Interactions
- [ ] Identify trader NPC interaction entry points
- [ ] Map shop UI surfaces (buy/sell/browse)
- [ ] Expose shop/trader interactions via `sd.ui` surfaces
- [ ] Inventory management from Lua (equip, drop, use)

## Phase 4: Custom Content
- [ ] Reverse engineer item/spell data formats
- [ ] Reverse engineer enemy definitions
- [ ] Build Lua API for injecting custom items/spells (`sd.items.register`, `sd.spells.register`)
- [ ] Build Lua API for injecting custom enemies
- [ ] Asset loading hooks for custom sprites/assets
- [ ] `sd.wizards.register()` — custom wizard types

## Phase 5: Multiplayer Exploration & PoC
- [ ] RE existing SD network/transport code
- [ ] Compare SD multiplayer architecture with SB
- [ ] Identify what's implemented vs stubbed in SD
- [ ] Build PoC using bot rails + event hooks from phases 1-4
- [ ] Sync game state (enemies, items, player positions)
- [ ] Evaluate authority model (host-authoritative vs peer)

## Reference: SB Parity Checklist

### Events SD needs (SB has these working):
- [ ] `loader.ready` ✅ (SD has this as `runtime.tick` currently)
- [x] `run.started` / `run.ended` ✅ (hooked and verified — arena creation + game over)
- [ ] `run.tick` ✅ (SD has `runtime.tick`)
- [ ] `wave.started` / `wave.completed`
- [ ] `skill.granted` / `skill.level_changed`
- [ ] `ability.granted` / `ability.level_changed`
- [ ] `spell.cast`
- [ ] `enemy.death`
- [ ] `item.equipped` / `item.unequipped` / `item.used`
- [ ] `potion.used`
- [ ] `level.up`
- [ ] `gold.changed`
- [ ] `drop.spawned` / `gold.drop_spawned` / `item.drop_spawned` / `consumable.drop_spawned`
- [ ] `orb.spawned`
- [ ] `powerup.triggered`

### API namespaces SD needs (SB has these):
- [ ] `sd.player` (SB: `sb.player`)
- [ ] `sd.world` (SB: `sb.world`)
- [ ] `sd.skills` (SB: `sb.skills`)
- [ ] `sd.abilities` (SB: `sb.abilities`)
- [ ] `sd.spells` (SB: `sb.spells`)
- [ ] `sd.wizards` (SB: `sb.wizards`)
- [ ] `sd.items` (SB: `sb.items`)
- [ ] `sd.entities` (SB: `sb.entities`)
- [ ] `sd.nav` (SB: `sb.nav`)
- [ ] `sd.waves` (SB: `sb.waves`)
