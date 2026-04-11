# Bot Rendering Session State (2026-04-11)

Read this after context compaction or in a new session to resume instantly.

## Current State
Last runtime-verified build: bot wizard **renders visibly** with **element-specific colored robes** and the April 10 animation desync fix keeps the bot on its own wizard animation lane. The stock-built staff attachment transfers into the equip sink instead of staying on actor `+0x264`. Game was stable and the bot patrolled near the player, but that build still borrowed slot-0 player's `+0x04`.

Current code after the April 11 audit:
- standalone actor creation uses `Object_Allocate(0x398)` plus normal scalar-deleting destruction
- bot gameplay slots are reserved from the first free slot in `1..3`, not hard-forced to slot `1`
- the loader **still contains a conditional slot-0 `actor +0x04` borrow fallback** inside `FinalizeStandaloneWizardBotActorState` when the bot render context still looks unresolved
- the loader **still calls** `ActorBuildRenderDescriptorFromSource` through a guarded wrapper when a synthetic or donor source profile is available
- the loader **still clears** the actor-side descriptor block at `+0x244..+0x263` after progression refresh, after gameplay attach, and again during standalone bot tick repair

## What's Working
- Direct standalone actor creation + `ActorWorld_Register` + proxy tick was the last runtime-verified visible bot path
- Bot spawns at player.x + 32 via `ResolveWizardBotTransform`
- `CreateStandaloneWizardVisualLinkObject` + `AttachStandaloneWizardVisualLinkObject` create and attach robe/hat visual links
- **Stock attachment transfer**: `TransferStockBuiltAttachmentToEquipSink` moves the source-built staff/wand from actor `+0x264` into equip sink `+0x30`
- **Element-specific colors**: `GetWizardElementColor(wizard_id)` returns proper RGB for fire/water/earth/air/mind
- **Animation ownership**: bot keeps its own `+0x21C` selection state and no longer donor-copies `+0x220..+0x263` after runtime wiring
- `ReserveWizardBotGameplaySlot` reserves the first free gameplay slot in `1..3`
- Position + heading + render-drive field freeze prevents ally AI input mirroring
- ALLY health bar displays correctly (one bar, not double)
- Bot patrol AI works — bot moves between patrol points around player
- Standalone actors are now allocated through `Object_Allocate`, matching recovered stock actor creation paths

## The Spawn Recipe (current code path)
``` 
1. `Object_Allocate(0x398)`            — stock allocator for player actors
2. `FUN_0052B4C0(self)`                — player actor ctor
3. `PrimeStandaloneWizardBotActor`
   - bot transform + movement seed
   - standalone progression/equip runtime creation
   - selection-state prime
   - `ApplyWizardElementAppearanceToDescriptor`
   - `ActorProgressionRefresh`
   - guarded source-profile descriptor build / donor selector fallback
4. `ActorWorld_Register(world, actor)` — world membership
5. `FinalizeStandaloneWizardBotActorState`
   - create + attach robe helper (ctor `0x00461F70`)
   - create + attach hat helper (ctor `0x00461ED0`)
   - transfer stock-built attachment from actor `+0x264` to equip sink `+0x30`
   - publish actor into reserved gameplay slot `1..3`
   - call gameplay attach
   - if bot `+0x04` still looks unresolved, borrow slot-0 player's render context as a fallback
   - restore world owner
6. `HookPlayerActorTick`
   - preserve position/heading
   - run stock tick
   - reapply bot-owned animation selection/state
   - clear actor descriptor block again
```

Important difference from the last runtime-verified build: allocation and destruction now follow the stock actor contract, but the code still has a conditional `+0x04` donor fallback if standalone render-node initialization does not complete on its own.

## Likely Remaining Rendering Bugs

### Render-context alias can still come back
- `NeedsBorrowedActorRenderContext` treats `0` and ctor-sentinel-looking values as unresolved render state
- `FinalizeStandaloneWizardBotActorState` still borrows slot-0 player's `actor +0x04` when that condition hits
- if this path triggers, the bot can render through the player's scene attachment again instead of owning an independent render node

### Actor-side body descriptor is still being wiped
- `ClearActorLiveDescriptorBlock` zeros `actor +0x244..+0x263`
- current code calls it after progression refresh, after gameplay attach, and during standalone tick repair
- recovered RE notes still say the wizard body render path reads `+0x244..+0x263` directly
- if that RE is correct, robe/hat helper objects can look fine while the actor body still renders with wrong or unstable colors

### Mixed Stock Pipelines (Structural Issue)
The loader mixes three incompatible stock pipelines:
1. Source-profile render-descriptor build (`0x005E3080`)
2. Player-start equipment seeding (`0x005CFA80`)
3. Stock standalone clone (`0x0061AA00`)

**Current issues**:
- Still mixes source-profile, player-start, and clone concepts in one loader path
- Stock clone creates fresh objects (progression, equip, selection state), doesn't memcpy windows
- World registration order still differs from recovered stock
- Slot reservation is dynamic in `1..3`, but gameplay publication is still manual
- The allocator fix is present, but the `+0x04` fallback means independent render-node ownership is still not proven

See `wizard-render-animation-deep-dive.md` for comprehensive analysis.

## Recent Fixes
1. **Position fix**: Changed spawn to use `ResolveWizardBotTransform(gameplay, request, &x, &y, &heading)` instead of inline fallback to (0,0,0). Bot now spawns at player.x + 32.
2. **Allocator/destructor fix**: Standalone actors now use the same `Object_Allocate(0x398)` plus scalar-deleting-dtor contract as recovered stock player actors.
3. **Guarded descriptor build**: `ActorBuildRenderDescriptorFromSource` is still used, but only through a guarded wrapper around synthetic or donor source-profile staging.
4. **Visual-link fallback colors**: When the actor-side descriptor block is unavailable, robe/hat helpers fall back to `GetWizardElementColor(wizard_id)`.
5. **Element color system**: Added `GetWizardElementColor()` with colors for all 5 elements:
   - wizard 0: Fire (red/orange) `{1.0, 0.4, 0.2}`
   - wizard 1: Water (blue) `{0.3, 0.5, 1.0}`
   - wizard 2: Earth (green) `{0.5, 0.7, 0.3}`
   - wizard 3: Air (yellow) `{1.0, 0.9, 0.5}`
   - wizard 4: Mind (purple) `{0.7, 0.3, 0.9}`
6. **Stock attachment fix**: `TransferStockBuiltAttachmentToEquipSink()` moves the staff/wand item from actor `+0x264` into equip sink `+0x30`
7. **Animation desync fix**: Bot was showing the wrong wizard frames. Fixed by:
   - removing donor overwrites of bot-owned `+0x220..+0x263` state
   - reasserting `ResolveStandaloneWizardSelectionState(wizard_id)` instead of donor `+0x21C` values
   - keeping the same rule during per-tick standalone bot repair
8. **Full render path**: Added `PlayerAppearance_ApplyChoice` x4 calls for complete render initialization:
   - Write appearance IDs to source descriptor at +0x82C/+0x830/+0x86C/+0x870
   - Call `ApplyWizardElementAppearanceToDescriptor()` before `ActorProgressionRefresh`
   - This completes the stock render initialization path that was previously skipped

## Key Constraints (DO NOT violate)
- **No synthetic progression wrappers** on factory actors — crashes PlayerActorTick
- **Do not make the `+0x04` borrow fallback permanent** — it is still only a visibility stopgap
- **Do not write raw synthetic float color payloads directly into actor `+0x244..+0x263`** — that live region is not safe staging
- **Equip-only wrapper** works without crashing (synthetic equip without synthetic progression)
- **PlayerEquipmentAndVisuals_Init** crashes — do not call on bot gameplay object
- **Vtable addresses must be ASLR-resolved** — raw VAs like 0x007857BC crash

## Next Steps (in priority order)
1. **Runtime-validate independent `actor +0x04` ownership** — confirm the bot gets its own scene/render node and remove the donor fallback if that path is stable
2. **Verify whether descriptor clearing is the remaining body-visual bug** — capture the descriptor hash before attach, after attach, and after the first tick
3. **Keep reducing stock-pipeline mixing** — the current path still combines source-profile staging, clone-like helper creation, manual slot publish, and repair-time patches
4. **Verify staff orb** — confirm the orb now follows the stock attachment transfer path in all wizard types
5. **Test all element types** — spawn bots with wizard_id 0-4 to verify colors and animation lanes

## Key Files
- `SolomonDarkModLoader/src/mod_loader_gameplay.cpp` — all bot spawn code
- `runtime/equip-analysis-summary.md` — equip system analysis
- `../Decompiled Game/reverse-engineering/maps/functions.csv` — named functions
- `../Decompiled Game/reverse-engineering/maps/globals.csv` — named globals

## Build & Launch
```bash
cd "/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Mod Loader"
"/mnt/c/Program Files/Microsoft Visual Studio/2022/Community/MSBuild/Current/Bin/MSBuild.exe" \
  SolomonDarkModding.sln "/p:Configuration=Release" "/p:Platform=Win32" /t:SolomonDarkModLoader /v:minimal /nologo
cp bin/Release/Win32/SolomonDarkModLoader.dll dist/manual_launcher/SolomonDarkModLoader.dll
cd dist/manual_launcher && cmd.exe /C "start SolomonDarkModLauncher.exe"
```
