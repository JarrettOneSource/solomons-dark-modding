# Bot Rendering Session State (2026-04-12)

Read this after context compaction or in a new session to resume instantly.

## Current Late-April 12 State
- Final April 13, 2026 status:
  - the user-facing element semantics were mislabeled in the loader
  - the decisive fix was a semantic remap, not another bot-only render workaround
  - create-screen action point indices now match the actual stock colors:
    - `fire` -> orange
    - `water` -> blue
    - `earth` -> green
    - `air` -> cyan
    - `ether` -> purple
  - gameplay-side bot/public wizard semantics now match those same user-facing colors:
    - fire -> slot `16`
    - water -> slot `32`
    - earth -> slot `40`
    - air -> slot `24`
    - ether -> slot `8`
  - verified on April 13:
    - `create_ready_fire_body_after_remap.png` shows orange fire preview
    - `fire_body_player_bot_after_semantic_remap_reroll.png` shows orange fire gameplay on the fixed lane
    - `water_body_player_bot_after_semantic_remap.png` shows blue water gameplay with both player and bot visible
    - direct Lua probes confirm same-slot player/bot parity for fire and water through `FUN_00660760`
  - current MVP scope is still **element-driven** bot presentation
    - the bot API still does not carry independent discipline/style selection
    - the visual fix in this session is therefore “correct element color semantics and bot parity”, not “full player-create replication”
  - historical notes below about the older robe/orb mismatch are useful RE history, but they are superseded by this semantic-remap fix
- Final late-April 12 root cause for the remaining orb/robe mismatch:
  - the bug was not missing element ids anymore
  - the bug was not the bare `0x1B5C` attachment contract anymore
  - the decisive divergence was **bot heading propagation**
  - `sd.bots.create` / `sd.bots.update` treated `position` as a full transform but did not track whether `heading` was explicitly provided
  - that meant a Lua request with `position={x,y}` but no `heading` still flowed through the runtime/gameplay sync path with `heading=0.0f`
  - the gameplay-slot bot actor was therefore materialized with `actor +0x6C = 0.0` while the local player in the same run carried `actor +0x6C = 180.0`
  - stock `ActorAnimation_Advance` uses `actor +0x6C` to derive the glyph-row index that reaches `ActorAnimation_MainPath (0x00538B80)` and the `0x1B5C` helper virtuals
  - in the verified water run:
    - player `ActorAnimation_MainPath` row input was `0x0C`
    - bot `ActorAnimation_MainPath` row input was `0x00`
    - player `item_s8` / `item_s9` helper calls used the same `0x0C` row
    - bot `item_s8` / `item_s9` helper calls used `0x00`
  - live patching the bot's `actor +0x6C` to the player's value immediately made the bot orb/robe presentation match
  - permanent fix:
    - add `has_heading` to bot create/update + pending sync structs
    - preserve omitted heading as omitted instead of silently becoming `0.0f`
    - when materializing a bot with position but without explicit heading, resolve heading from the current bot actor if it exists, otherwise inherit the local player's current heading
    - remove the patrol harness's forced `heading = 0.0`
- The bot now renders the **correct wizard sprite composition** again. The user explicitly confirmed that the bad extra props / wrong sprite composition are effectively fixed.
- The remaining visible issue is now narrower:
  - robe and orb colors still look wrong or at least suspicious
  - the problem no longer presents as “double staff + scroll bundle” or “completely wrong base sprite”
- The current visual bug should therefore be treated as a **color / visual-owner contract** bug, not an appearance-id bug and not a base-sprite composition bug.
- Architecture constraint going forward:
  - do not let bots inherit the local player's spells, inventory, or visual/loadout objects
  - the long-term multiplayer target is one participant rail where each participant owns its own wizard loadout and matching presentation
  - the current MVP bar is lower but still explicit: a bot's selected `wizard_id` must drive its own progression/loadout mapping and its own visible presentation
- The strongest current structural finding:
  - a stock slot-0 actor in `testrun` renders correctly with a much leaner contract than the loader had been assuming:
    - `actor +0x300` points at the gameplay slot wrapper
    - `actor +0x200 == 0`
    - `actor +0x304 == 0`
    - `actor +0x1FC == 0`
    - `actor +0x174 == 0`
    - `actor +0x178 == 0`
    - `actor +0x264 == 0`
    - actor selector window is `0/0/0/0/1`
- The gameplay-slot wrapper layout was corrected:
  - the slot wrapper is **not** the old 8-byte standalone wrapper shape
  - the real gameplay object pointer for slot wrappers is at `wrapper + 0x0C`
  - the shared helper `ReadSmartPointerInnerObject(...)` now supports both wrapper layouts
- The slot progression write path is now fixed:
  - the bot’s real slot-1 progression object now receives the correct water appearance ids:
    - `+0x82C = 3`
    - `+0x830 = 6`
    - `+0x86C = 32`
    - `+0x870 = 35`
- The gameplay-slot actor can now be forced onto the same stock actor-side baseline as the local player while still spawning the bot successfully.
- Multiple live render experiments were run after that fix:
  - stock slot contract only
  - stock slot contract + bot-owned attachment lane
  - stock slot contract + robe/hat helper links + attachment
  - source-only richer selector window on the temporary source actor while keeping the slot actor clean
- Result:
  - those experiments changed the frame, but none fully fixed the remaining robe/orb color issue
  - so the current unresolved problem is **visual owner / item / sink state**, not appearance ids or obvious actor selector contamination
- New guidance for the next pass:
  - do not treat raw `.bundle` memory as the primary seam
  - instead trace the higher-level asset/model accessors and sink/item builders that produce the live robe/hat/staff/orb objects for the stock player
- Tooling direction is now explicit:
  - expand the in-process Lua debug surface first
  - then use it to inspect the remaining color path without more blind render-state guessing
  - keep WinDbg CLI (`cdb.exe`) as an external fallback for breakpoint/stack work, but keep Lua as the primary day-to-day live-memory workflow
- Lua tooling reliability was narrowed to concrete causes and hardened:
  - startup traces were sometimes armed after the interesting startup function had already fired
  - the sandbox config parser was dropping newly added `trace_*` keys unless a second allowlist file was updated in lockstep
  - `query_memory` and `trace_function` were resolving addresses differently, which made some targets appear contradictory across APIs
  - the loader now queues/retries trace arming, preserves all numeric config keys, exposes `sd.debug.get_last_error()`, and reports resolved addresses from `query_memory`
  - sandbox preset resolution now really honors `config/active_preset.txt`; older runs that seemed to ignore the preset were not imagining it
  - the biggest trace crash cause was the old fixed 7-byte patch size; `EquipAttachmentSink_Attach (0x00575850)` begins with a 5-byte `cmp/jne` pair followed by a 5-byte `mov`, so the old default split the `mov` and crashed on first hit
  - trace hooks now auto-size their prologue patch on x86 instruction boundaries; live validation shows `trace_equip_attachment_sink_attach` arming safely with `patch=5`
  - the deeper trace-stub limitation is now explicit too: copied relative branches/calls are not relocated, so the hooker now rejects those prologues instead of crashing
  - for the stock startup attach investigation, the active trace seam is now `0x005758D2`, the taken non-type-7 fast path reached after the entry `cmp/jne` at `0x00575850`
- Harness caveat discovered during tooling validation:
  - the `lua_ui_sandbox_lab` patrol spawn still defaulted to `wizard_id = 0` (fire)
  - that means an orange robe/orb frame from the sandbox harness is not automatically a render bug
  - the harness now accepts `SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID` so color tests can be run against a chosen element intentionally
- New late-April 12 color-path result from a stable live run:
  - a forced water bot (`SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID=1`) really does create a blue source profile
  - live source-profile log proved cloth payload `0.300000,0.500000,1.000000`
  - current stable runtime also shows player and bot actor selector windows matching: `0/0/0/0/1` with actor-local source and attachment pointers both zero
  - despite that, the visible bot orb still reads orange in the captured frame
  - zeroing the bot-local equip runtime pointers at `actor +0x304` and `actor +0x1FC` did **not** remove that orange orb lane
  - conclusion: the remaining color mismatch is downstream of source-profile cloth and not explained solely by the bot-local equip runtime pointer
  - the new direct lane comparison from Lua is:
    - player attachment lane object: `0x1B5C` at one address
    - bot attachment lane object: `0x1B5C` at a different address with different payload bytes
    - player holder-kind/type ordering is `(1 -> 0x1B5D), (2 -> 0x1B5E)`
    - bot holder-kind/type ordering matches that stock order, but our current `primary` / `secondary` labels are reversed relative to it
  - practical meaning:
    - fix future naming first so RE notes do not keep smuggling in the wrong semantic labels
    - the remaining orb mismatch looks like an attachment-object payload mismatch, not just a lane-pointer mismatch
- Final April 12 orb fix:
  - the attachment-byte probes were a red herring for the visible orb color
  - the decisive stock seam was the gameplay selection-state rail, not the late `0x1B5C` bytes
  - a new typed Lua helper `sd.gameplay.get_selection_debug_state()` exposed the live gameplay index-state table plus the slot selection globals
  - stock create-ready runs recovered the real selection-state mapping:
    - earth -> `0x08`
    - ether -> `0x10`
    - fire -> `0x18`
    - water -> `0x20`
    - air -> `0x28`
  - the old loader mapping was wrong:
    - it wrote `wizard_id = 1` (water) as `0x10`, which is the stock ether/fire-adjacent lane, not stock water
    - that left water bots with blue robe appearance but an orange/fire orb
  - after correcting `ResolveStandaloneWizardSelectionState(...)` to the recovered stock mapping:
    - the spawned water bot now reads `slot1 = 32`
    - `player_selection_state_1 = 32`
    - the bot's resolved animation state also moved to `32`
    - fresh validation frame shows the bot orb rendering blue in:
      - `runtime/window_capture_water_bot_selectionfix.png`
      - `runtime/window_capture_water_bot_selectionfix_open.png`
    - a residual fire validation also matched cleanly:
      - `slot0 = 24`
      - `slot1 = 24`
      - `player_selection_state_1 = 24`
      - bot resolved animation state = `24`
- New mixed-element progression proof from a stable live run:
  - player remained water and read progression ids `3 / 6 / 32 / 35`
  - bot `wizard_id = 1` also read `3 / 6 / 32 / 35`
  - a second bot spawned live with `wizard_id = 0` read `2 / 6 / 24 / 27`
  - conclusion: the current bot path can already hold independent progression appearance ids per bot when wizard ids differ; the remaining bug is now specifically the final visual materialization of those bot-owned selections
- New attachment/orb RE findings:
  - `ActorBuildRenderDescriptorFromSource (0x005E3080)` only builds a **bare** `Item_Staff` / `Item_Wand`
    - ctor
    - type id
    - `item[7] = 0`
    - store at `actor +0x264`
    - no rich post-ctor item init
  - the bad bot `0x1B5C` object is already wrong on the temporary source actor before transfer into the bot lane
  - registering the temporary source actor before `0x005E3080` changed that payload and moved the path closer to stock preview behavior, but it still did not fix the visible orb
  - richer stock item setup exists in `0x004645B0` / `0x004699B0`; the caller at `0x0046A360` proves `0x004699B0` is a one-arg `cdecl` clone builder (`push template_ptr; call; add esp,4`)
  - a direct bot cutover to `0x004699B0(source_attachment)` was attempted and reverted because it regressed the bot out of the frame / attachment lane
  - conclusion:
    - the right direction is still the richer stock item path
    - but the missing piece is the **template/record contract** that those builders expect, not just the raw `0x1B5C` object pointer
- later live validation tightened this further:
    - the bot attachment object survives temporary source-actor cleanup unchanged
    - transfer-boundary logs now show identical `0x1B5C` bytes before and after `cleanup_source()`
    - so the remaining orb mismatch is **not** an attachment lifetime bug
    - the remaining bug is that `ActorBuildRenderDescriptorFromSource (0x005E3080)` produces a structurally valid but underinitialized `0x1B5C` compared to the stock player-start item
  - full-object diff between stock player `0x1B5C` and bot `0x1B5C` is now recorded:
    - header differences at `+0x07/+0x0C/+0x15`
    - a second cluster of bot-zero / player-nonzero bytes in the mid-object region around `+0x34`, `+0x50`, `+0x58`, `+0x6A..+0x73`, `+0x7E..+0x85`
    - this points to a missing stock construction/finalization step inside the attachment-item contract, not to a bad sink pointer or a post-spawn mutation
  - robe/hat helper color blocks are valid and element-sensitive:
    - helper float4 block at `+0x88..+0xA4` is populated and differs between player and bot in a coherent way
    - that suggests the remaining mismatch is attachment-specific more than helper-color specific
  - later same-element manual runs proved the helper mismatch is real too:
    - stock player Fire helper colors: `0.55833697 / 0.37325415 / 0.34327835`
    - stock player Earth helper colors: `0.31089064 / 0.47474384 / 0.32349765`
    - stock player Air helper colors: `0.56981838 / 0.76835203 / 0.77172661`
    - same-element bots still produced different helper float4s for Fire/Earth/Air, so the remaining robe discrepancy is not just an attachment-item issue
  - the current stock clone diagnostic does **not** solve the attachment issue:
    - `WizardCloneFromSourceActor (0x0061AA00)` was called against the same temporary source actor after descriptor build
    - the clone attachment item was byte-identical to the source-built `0x1B5C`
    - conclusion: the stock clone rail is not where the missing `0x1B5C` mid-object state appears; that state is still specific to the stock player-start/richer item-build path
  - newer late-April 12 finding:
    - the temporary `stock_clone_diagnostic` call itself was mutating the source actor by stealing `source +0x264` before the gameplay-slot bot path could transfer it
    - removing that diagnostic restored the gameplay-slot bot attachment lane in fresh runs
    - that was a self-inflicted instrumentation regression, not a stock engine behavior
  - newer late-April 12 helper-color finding:
    - the synthetic source-profile palette must be seeded with the **pre-transform** source colors, not the already-transformed helper float4s
    - stock helper colors are produced by the grayscale mix path `helper = 0.2 * source + 0.8 * grayscale(source)` with weights `0.3086 / 0.6094 / 0.0820`
    - after replacing `GetWizardElementColor()` with reconstructed pre-transform source colors, a fresh Earth bot run produced helper float4s `0.31089064 / 0.47474384 / 0.32349765`, matching the measured stock Earth helper colors exactly
    - that fixes the helper-color side of the remaining bot visual mismatch; the attachment-item contract is still a separate open thread
  - newest water-automation pass after the background-focus hook fix:
    - the water harness now reaches stable `testrun` again without the old immediate `WM_ACTIVATEAPP` crash
    - both the automated local player and a spawned water bot (`wizard_id = 1`) read the same water progression appearance ids:
      - `+0x82C = 3`
      - `+0x830 = 6`
      - `+0x86C = 32`
      - `+0x870 = 35`
    - the spawned water bot helper float4s read the expected stock-water values:
      - `0.39679638 / 0.46394697 / 0.54945219`
    - the automated local player helper float4s still read a different set:
      - `0.34542164 / 0.44866666 / 0.55803943`
    - so the rebuilt automation harness is stable, but the automated local player is still not a trustworthy stock-water visual reference
    - direct frame captures with the bot moved into clearer arena positions still show an **orange** orb on the water bot
    - live copy probes narrowed the remaining orb branch further:
      - copying the player's sampled attachment mid-object fields into the bot did not change the visible orb
      - copying the broader `player_attach +0x0C .. +0x87` window into the bot made the sampled bot attachment fields match the player exactly, but the visible orb still did not flip
  - current best read:
    - either the remaining orb state is upstream of the sampled `0x1B5C` field window, or the orb renderer caches/resolves its state earlier than late live attachment copies can affect
  - newer stock-contract findings:
    - `0x004699B0` is a template clone path, not a live-item clone path; calling it on a live `0x1B5C` object returns `nil`
    - headless Ghidra now shows why: `0x004699B0` branches on `template +0x84`, copies template flags at `+0x88/+0x89/+0x8A`, clones child state through the manager at `object +0x6C`, and only then finishes the item
    - `0x0057A000` is the stock FX/child initializer for these items; it creates effect children, writes item flags like `+0x5A`, and derives orb/helper behavior from stock selection state
    - the only caller of `0x0057A000` is `0x004645B0`
    - raw disassembly of the rich build caller at `0x0046A917` shows the missing contract:
      - `ECX = [0x0081C264]` (gameplay)
      - stack arg = `(**(gameplay + 0x1654) + 0x30)`
      - call `0x004645B0`
    - this means the richer item build is seeded from gameplay/progression context, not from the actor or the late attachment object bytes
    - that is consistent with the current split-state symptom:
      - robe side is following wizard appearance
      - orb side is still following a separate stock progression/item-init path
  - create-state anchor added for the next pass:
    - a new sandbox preset family `create_ready_{earth,ether,fire,water,air}` now stops after the create-screen clicks instead of transitioning into `testrun`
    - in the rebuilt `create_ready_water` run, the live create owner used for the water + arcane clicks was `0x1417FAF8`
    - `owner +0x1A4 = 3` and `owner +0x22C = 2` matched the selected water + arcane state
    - `FUN_00683B90(owner, index)` now returns stable non-null entries for some indexes in that state, so the next branch is to decode which entry actually feeds the staff/helper templates
  - final stock-fire parity verification:
    - after the heading propagation fix, the remaining “fire bot orb should be orange” concern was checked against a stock fire player, not against memory guesses
    - a new direct debug helper (`sd.debug.call_thiscall_out_f32x4_u32`) was used to query `FUN_00660760` on live progression runtimes without relying on reused trace scratch buffers
    - result:
      - stock fire player (`map_create_fire`, selection `0x18`) returned `0.628921 / 0.763921 / 0.763921 / 1.0`
      - fire bot in a mixed water-player run (`selection 0x18`) returned the same `0.628921 / 0.763921 / 0.763921 / 1.0`
    - conclusion:
      - the loader is now matching the stock fire orb path too
      - the earlier “not orange” concern is not backed by a stock-vs-bot mismatch
  - April 13 automation parser fix:
    - the first attempt at combined presets like `create_ready_fire_body` / `map_create_fire_body` was broken
    - root cause: `setup.lua` used regex-style alternation such as `(earth|ether|fire|water|air)` and `(mind|body|arcane)`, but Lua patterns do not support `|`
    - those combined presets therefore silently fell through to the default water + arcane actions
    - after replacing that with explicit token parsing and table lookup, the live create-screen dispatch log now shows the correct combined actions, for example:
      - `create.select_element_fire`
      - `create.select_discipline_body`
  - April 13 semantic remap:
    - the parser fix proved a second deeper issue: the create-screen point indices were labeled with the wrong element names in the loader metadata
    - create-screen captures made the true stock visual order obvious:
      - point `0` -> purple -> user-facing `ether`
      - point `1` -> orange -> user-facing `fire`
      - point `2` -> cyan -> user-facing `air`
      - point `3` -> blue -> user-facing `water`
      - point `4` -> green -> user-facing `earth`
    - the loader now treats the public element names as:
      - fire -> stock slot `16` / appearance ids `1, 0x10, 0x15`
      - water -> stock slot `32` / appearance ids `3, 0x20, 0x23`
      - earth -> stock slot `40` / appearance ids `4, 0x28, 0x2D`
      - air -> stock slot `24` / appearance ids `2, 0x18, 0x1B`
      - ether -> stock slot `8` / appearance ids `0, 0x08, 0x0B`
    - `GetWizardElementColor(wizard_id)` was already aligned to the user-facing colors, so the final fix was:
      - remap the create-screen action point indices in `config/binary-layout.ini`
      - remap `ResolveStandaloneWizardSelectionState(...)`
      - remap `ResolveWizardAppearanceChoiceIds(...)`
    - validated April 13:
      - `create_ready_fire_body_after_remap.png` now shows an orange fire preview
      - `map_create_fire_body` now lands on `slot0 = 16`
      - a spawned fire bot now lands on `slot1 = 16`
      - player and bot both return `0.600576 / 0.503076 / 0.465576 / 1.0` from `FUN_00660760(..., 16)`
      - `map_create_water_body` still lands on `slot0 = 32`
      - a spawned water bot still lands on `slot1 = 32`
      - player and bot both return `0.369926 / 0.429926 / 0.504926 / 1.0` from `FUN_00660760(..., 32)`

## Resume Checklist
- Build and stage `dist/launcher/SolomonDarkModLoader.dll` before trusting any new runtime result.
- Launch a fresh `testrun` process, then use `tools/lua-exec.py` or `scripts/Invoke-LuaExec.ps1` for live probes.
- Treat `runtime/helper_items_hybrid.png` and `runtime/helper_items_hybrid_zoom2.png` as the current reference for “sprites right, colors still wrong”.
- Start the remaining investigation by comparing the stock player and bot through the gameplay-owned sink chain, not by guessing at actor-side selector bytes.
- Prefer the new Lua pointer-chain and trace-hit APIs documented in `docs/lua-memory-tooling.md`.

## Lua Tooling Baseline
- The loader now exposes a stronger `sd.debug` surface for live RE:
  - pointer-chain helpers:
    - `resolve_ptr_chain`
    - `resolve_object_ptr_chain`
    - `dump_ptr_chain`
    - `dump_object_ptr_chain`
    - `snapshot_ptr_chain`
    - `snapshot_object_ptr_chain`
  - trace/watch history:
    - `list_traces`
    - `get_trace_hits`
    - `clear_trace_hits`
    - `get_write_hits`
    - `clear_write_hits`
  - structure helpers:
    - `dump_struct`
    - `dump_vtable`
  - scalar helpers:
    - `read_u16`
    - existing `read_u8/u32/i8/i16/i32/float`, `write_*`, `copy_bytes`, `search_bytes`
- Use those first. Only fall back to external debugger attach when the question is about call stacks, breakpoints, or faults that the in-process trace/watch path cannot answer safely.

## Latest Screenshots
- New baseline screenshot after the major sprite fix:
  - `runtime/helper_items_hybrid.png`
  - `runtime/helper_items_hybrid_zoom2.png`
- These are the current reference frames for “good sprite composition, still questionable robe/orb color.”

## Current State
Latest runtime verification on April 12, 2026: the gameplay-slot bot is stable, visible, and the bad extra-prop composition issue is no longer the primary problem. The remaining issue is color correctness in the robe/orb path.

Current code after the April 11 audit:
- standalone actor creation uses `Object_Allocate(0x398)` plus normal scalar-deleting destruction
- bot gameplay slots are reserved from the first free slot in `1..3`, not hard-forced to slot `1`
- the loader **still calls** `ActorBuildRenderDescriptorFromSource` through a guarded wrapper when a synthetic or donor source profile is available
- `PrimeStandaloneWizardBotActor` now leaves the synthetic source profile's selector bytes wizard-owned instead of donor-copying `+0x23C/+0x23D/+0x23F/+0x240`
- the old standalone `ApplyWizardElementAppearanceToDescriptor()` path is gone; April 11 RE proved the slot-0 appearance pipeline is not a grouped `ApplyChoice x4` contract
- `PrimeStandaloneWizardBotActor` also no longer calls player vtable slot `+0x18`; that helper is `ActorVisual_SetInitFlag` and only writes `actor +0x05 = 1`
- the loader now treats the actor-side descriptor block at `+0x244..+0x263` as transient compiler input only: it is mirrored from the source actor long enough to seed the helper lanes and selector bytes, then cleared before slot registration / animation advance, again after slot attach, and again before/after tracked bot tick repair
- live clean-restart verification now shows `bot variants=1/1/0/0/1`, `bot +0x244..+0x263 == 0`, `bot +0x23E == 0`, `bot +0x264 == 0`
- the gameplay-slot path no longer builds or attaches a live standalone `Item_Staff` / `Item_Wand`
- crash forensics now write a richer minidump and append the recent loader log tail plus the last published wizard-bot crash summary into `solomondarkmodloader.crash.log`
- the current teardown investigation no longer treats `actor +0x04` as a proven render-node pointer; in the failing April 11 delete path it still reads as ctor/header-sentinel-like state (`0x14010101`)
- stock case `0x00512060` is now named `GameplayHud_RenderDispatch`; its case `100` builds a temporary gameplay-slot actor list and calls actor vtable slots `+0x28` then `+0x1C`
- actor vtable slot `+0x28` is now named `PlayerActor_SlotOverlayCallback` (`0x00528AD0`); recovered decompile shows overlay drawing and `+0x1F4/+0x1F8` writes, but no direct delete call
- `0x00641070` is no longer treated as a Region method; it is the embedded `PuppetManager` delete callback at `Region + 0x310`, and that manager owns the current live teardown path
- `Region_Ctor` (`0x00652830`) now anchors the ownership model: it installs `PuppetManager::vftable` (`0x0079F044`) at `Region + 0x310` and stores the owning Region pointer into the manager at subobject `+0x4C`
- `0x004022A0` is now named `ManagedPointerList_SweepParityLane`; it is the generic parity-lane sweep helper used by the embedded `PuppetManager` and other managed side lists
- `0x00402450` is now named `ManagedPointerList_RemoveFromAllLanes`; it removes one tracked pointer from the owner's main list and both parity side lanes
- `0x004024C0` is now named `PointerList_DeleteBatch`; it is the shared manager/list deleter that iterates a pointer-list and dispatches `this->vtable[+0x28]` per item
- `0x00641090` / `0x00641130` are now named `ActorWorld_RegisterGameplaySlotActor` / `ActorWorld_UnregisterGameplaySlotActor`; they are the recovered stock persistent-slot world bind / unbind helpers
- `0x005217B0` is now named `WorldCellGrid_RebindActor`; `ActorWorld_RegisterGameplaySlotActor` ends by binding the slot actor through the Region cell grid at `Region + 0x378`
- fresh decompile of `ActorWorld_Register` / `ActorWorld_Unregister` now shows the precise mismatch: the generic path keys Region storage by `(actor_group, resolved_world_slot)` at `Region + 0x500`, but the loader later rewrites `actor +0x5C` to the gameplay slot without rerunning stock registration
- the first live April 11 `PointerList_DeleteBatch` hook attempt crashed before gameplay because the hook copied 6 bytes and split the `mov esi, [ebp+0x8]` prologue instruction; the safe boundary is 5 bytes

## What's Working
- Gameplay-slot bot creation + stock slot registration + stock tick/render loops are now runtime-verified
- Bot spawns at player.x + 32 via `ResolveWizardBotTransform`
- `CreateStandaloneWizardVisualLinkObject` + `AttachStandaloneWizardVisualLinkObject` create and attach robe/hat visual links
- **Element-specific colors**: `GetWizardElementColor(wizard_id)` returns proper RGB for fire/water/earth/air/mind
- **Animation ownership**: bot keeps its own `+0x21C` selection state and no longer donor-copies `+0x220..+0x263` after runtime wiring
- **Animation-drive decoupling**: standalone bots cache bot-owned drive profiles and no longer consume the player's live observed drive profile during per-tick repair
- **Weapon overlay fix**: actor-side `+0x23E` stays normalized to `0` while the visible orb/staff presentation survives without a live standalone attachment item
- **Selector ownership fix**: synthetic wizard selector bytes now stay wizard-owned through `FUN_005E3080`, so the bot no longer inherits the player's body/accessory variant lane
- **Descriptor-bundle fix**: keeping the actor-local descriptor bundle live made the standalone bot disappear; clearing `+0x244..+0x263` before helper creation restored the visible bot
- `ReserveWizardBotGameplaySlot` reserves the first free gameplay slot in `1..3`
- Position + heading + render-drive field freeze prevents ally AI input mirroring
- ALLY health bar displays correctly (one bar, not double)
- Bot patrol AI works — bot moves between patrol points around player
- Standalone actors are now allocated through `Object_Allocate`, matching recovered stock actor creation paths

## The Spawn Recipe (current gameplay-slot code path)
``` 
1. `Gameplay_CreatePlayerSlot(slot)`   — stock slot actor + stock slot progression wrapper
2. `PrimeGameplaySlotBotActor`
   - bot transform + movement seed
   - vitals copy from slot progression
   - actor-owned progression/equip runtime cutover
   - selection-state prime
   - `ActorProgressionRefresh`
3. `SeedGameplaySlotBotRenderStateFromSourceActor`
   - create temporary stock source actor
   - compile canonical wizard render window from stock source-profile staging
   - build robe helper (ctor `0x00461F70`) from built descriptor
   - build hat helper (ctor `0x00461ED0`) from built descriptor
   - mirror selector bytes from the source actor onto the gameplay-slot bot
   - clear the actor-local descriptor block immediately after seeding
   - destroy the temporary source actor/profile
4. `ActorWorld_RegisterGameplaySlotActor(region, slot)`
5. gameplay attach virtual
6. `HookActorAnimationAdvance` / `HookPlayerActorTick`
   - keep the transient descriptor block zeroed before/after stock animation/tick
   - preserve bot-owned transform / drive state
```

Important current difference from the older standalone branch: gameplay-slot bots now ride the stock slot actor tables and slot registration rails, but still use a temporary stock source actor as a visual compiler step for robe/hat helper seeding.

## Active Teardown Finding

- The stock delete path is still unresolved at the contract level, but two older assumptions are now falsified:
- `PlayerActor_SlotOverlayCallback` itself does not contain a direct delete call, and the latest live run showed a matching `player_vslot_28 exit` before the bot hit the delete callback.
- `0x00641070` is not a direct Region method in the live path. The hook `self` is the embedded `PuppetManager` subobject at `Region + 0x310`, whose vtable slot `+0x28` deletes tracked puppets.
- The strongest current hypothesis is now more specific: `ActorWorld_Register(world, 0, actor, -1, 0)` already inserts the bot into Region manager storage using `(actor_group=0, resolved_world_slot=N)`, and the loader then overwrites `actor +0x5C` to the gameplay slot while leaving the Region-side bucket identity and stock slot-active byte path untouched.
- That means the remaining problem is now a Region/PuppetManager ownership-contract failure: the standalone bot is entering a stock puppet-manager delete path immediately after spawn because it is not satisfying the stock slot-owned registration contract.

## Verified Root Cause

- Leaving the actor-side descriptor bundle at `+0x244..+0x263` live caused the standalone bot to disappear from the rendered frame.
- Reintroducing `ClearActorLiveDescriptorBlock(...)` before helper creation, after gameplay attach, and during standalone tick repair restored the visible standalone bot.
- The working path therefore uses source-profile descriptor build only as a temporary setup step. The live actor descriptor bundle is not safe to keep.

## Confirmed Prop-Duplication Root Cause

- The extra side staff / scroll bundle are **not** the orb/staff attachment path miscoloring or double-owning itself.
- The stock orb/staff attachment is real and separate:
  - source build creates it at actor `+0x264`
  - `TransferStockBuiltAttachmentToEquipSink()` moves it into equip sink `+0x30`
  - actor `+0x23E` is then normalized back to donor value `0`
  - the orb/staff stays visible even with actor `+0x23E == 0`
- The remaining duplicate props came from the actor-side body sprite lane:
  - `PrimeStandaloneWizardBotActor` used to copy donor `+0x23C/+0x23D/+0x23F/+0x240` into the synthetic source profile before `FUN_005E3080`
  - that contaminated the bot's actor-side base sprite selectors with the local player's structural body/accessory variant
  - in the pre-fix validated run the player and bot both sat at `variants=0/0/0/1`
- The strongest live proof is the reversible `+0x240` probe:
  - baseline bot had extra right-side staff + left-side scroll bundle
  - `sd.debug.write_u8(bot + 0x240, 0)` removed those extra props while the orb/staff attachment remained
  - restoring `sd.debug.write_u8(bot + 0x240, 1)` brought the extra props back
- Conclusion: the current standalone bot is a hybrid of two stock visual lanes:
  1. actor-side body sprite selection driven by `+0x23C..+0x240`
  2. standalone equip attachment ownership through equip sink `+0x30`

That hybrid was the real remaining art bug. The fix is to keep the synthetic selector bytes wizard-owned and let the standalone attachment sink remain the only attachment-owner lane.

## Remaining Rendering Bugs

### Render-context ownership is unresolved, not currently shared in source
- current loader source no longer writes the local player's `actor +0x04` into the bot during standalone finalization
- the failing April 11 delete run shows the bot reaching the PuppetManager delete callback with `actor +0x04 == 0x14010101`, so the bot dies before any stable stock transition away from the ctor/header lane is observed
- independent render-context ownership is therefore still unresolved, but the older “shared `+0x04` fallback is still active” note is stale

### Mixed Stock Pipelines (Structural Issue)
The loader mixes three incompatible stock pipelines:
1. Source-profile render-descriptor build (`0x005E3080`)
2. Player-start equipment seeding (`0x005CFA80`)
3. Stock standalone clone (`0x0061AA00`)

**Current issues**:
- Still mixes source-profile, player-start, and clone concepts in one loader path
- Stock clone creates fresh objects (progression, equip, selection state), doesn't memcpy windows
- Slot reservation is dynamic in `1..3`, but gameplay publication is still manual and still bypasses `ActorWorld_RegisterGameplaySlotActor`
- The allocator fix is present, but the `+0x04` fallback means independent render-node ownership is still not proven

See `wizard-render-animation-deep-dive.md` for comprehensive analysis.

## Recent Fixes
Historical timeline note:
- the numbered items below are preserved as the investigation timeline
- any statements that conflict with the April 12 final gameplay-slot cutover are superseded by the top-of-file update and current-state sections
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
8. **Appearance-pipeline correction**: Removed the attempted standalone `PlayerAppearance_ApplyChoice` recreation.
   - April 11 decompile proved `0x00660320` does not take a group index
   - `0x005D0290` maps the selected wizard to three primary ids plus one secondary id and feeds them through a slot-0-only contract
   - the loader's fake grouped helper was contaminating appearance state and has been removed instead of preserved
9. **Standalone animation-drive cutover**: standalone bots now snapshot their own cached drive profiles at spawn/finalize and reapply those during tick repair instead of reusing the player's live observed drive profile.
10. **Actor weapon normalization**: after the synthetic source profile builds the stock attachment item, `NormalizeStandaloneWizardActorWeaponTypeFromDonor()` restores actor `+0x23E` to the donor/player value so the visible staff stays attachment-owned instead of double-rendered.
11. **Descriptor-bundle rollback**: the attempted “keep `+0x244..+0x263` live” change regressed the bot back to a one-wizard frame. Reintroducing `ClearActorLiveDescriptorBlock()` restored the visible standalone bot.
12. **Remaining-prop root cause confirmed**: a live April 11 probe proved the extra staff / scroll props are selected by actor `+0x240`, not by the standalone equip attachment. `+0x240 = 1` produced the duplicate-prop frame; `+0x240 = 0` removed it while leaving the orb/staff attachment visible.
13. **Selector ownership cutover**: `PrimeStandaloneWizardBotActor` no longer donor-copies selector bytes into the synthetic source profile. The validated live bot now comes up as `variants=0/0/0/0`, keeps a non-null equip attachment sink, and no longer shows the duplicate side props.
14. **Gameplay-slot progression cutover**: gameplay-slot bots now keep their own actor progression wrapper/runtime instead of sharing the slot-table progression wrapper.
15. **Actor render snapshot cutover**: gameplay-slot bots now use a temporary stock source actor only to compile the canonical actor-side wizard render window, then stamp that snapshot onto the bot actor.
16. **Staff ctor RE confirmed**: `Gameplay_FinalizePlayerStart` constructs the starter staff by `Object_Allocate(0x88)`, `Item_Staff_Ctor (0x00462050)`, `active=1`, `reset=0`, then `EquipAttachmentSink_Attach`.
17. **Superseded dead end**: the earlier “repair the live `0x1B5C` attachment contract” thread was real investigation work, but the April 12 final gameplay-slot cutover proved the correct path is to avoid keeping that live item on gameplay-slot bots at all.

## Key Constraints (DO NOT violate)
- **No synthetic progression wrappers** on factory actors — crashes PlayerActorTick
- **Do not make the `+0x04` borrow fallback permanent** — it is still only a visibility stopgap
- **Do not write raw synthetic float color payloads directly into actor `+0x244..+0x263`** — that live region is not safe staging
- **Equip-only wrapper** works without crashing (synthetic equip without synthetic progression)
- **PlayerEquipmentAndVisuals_Init** crashes — do not call on bot gameplay object
- **Vtable addresses must be ASLR-resolved** — raw VAs like 0x007857BC crash

## Next Steps (in priority order)
1. **Cut over to the stock slot-owned registration contract** — compare the current loader path to `ActorWorld_RegisterGameplaySlotActor` / `ActorWorld_UnregisterGameplaySlotActor` and stop publishing the bot as a transient world actor plus manual slot table patch
2. **Runtime-validate independent `actor +0x04` ownership** — once the stock slot-owned path is in place, confirm the bot gets its own stable scene/render transition and remove any remaining stale donor assumptions
3. **Keep reducing stock-pipeline mixing** — the current path still combines source-profile staging, clone-like helper creation, manual slot publish, and repair-time patches
4. **Test all element types** — spawn bots with wizard_id `0..4` to verify that body/accessory selectors, colors, and attachment ownership all stay wizard-correct

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
