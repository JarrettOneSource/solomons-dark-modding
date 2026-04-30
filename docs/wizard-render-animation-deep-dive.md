# Solomon Dark Wizard Render and Animation Deep Dive

## Scope

This document reconstructs the wizard visual pipeline from the recovered Solomon Dark binary, pseudo-source, runtime Ghidra dumps, and the current mod-loader bot implementation.

The goal is not just to list offsets. The goal is to separate the three distinct stock pipelines that currently get mixed together during bot spawning:

1. Source-profile render-descriptor build on a live wizard actor
2. Stock player-start equipment seeding
3. Stock standalone wizard cloning from an existing source actor

Those three pipelines share data, but they are not interchangeable.

## Primary sources

- `Decompiled Game/reverse-engineering/types/sd_state.h`
- `Decompiled Game/reverse-engineering/maps/functions.csv`
- `Decompiled Game/reverse-engineering/pseudo-source/gameplay/00548B00__PlayerActorTick.c`
- `Decompiled Game/reverse-engineering/pseudo-source/gameplay/005CFA80__Gameplay_FinalizePlayerStart.c`
- `Decompiled Game/reverse-engineering/pseudo-source/gameplay/005E3080__ActorBuildRenderDescriptorFromSource.c`
- `Mod Loader/runtime/ghidra-bot-animation-focus.txt`
- `Mod Loader/runtime/ghidra-player-descriptor-candidates.txt`
- `Mod Loader/runtime/equip-analysis-summary.md`
- `Mod Loader/SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization*.inl`
- `Mod Loader/SolomonDarkModLoader/src/mod_loader_gameplay/core/synthetic_wizard_source_profiles.inl`

## Executive summary

The stock game has one authoritative body-render path for wizards, but there are two different ways to feed it:

- Source/profile path: a live actor with `actor + 0x174 == 3` and a valid profile at `actor + 0x178` runs `0x005E3080`, which fills the actor-side selector bytes at `+0x23C..+0x240`, packs the actor-side descriptor block at `+0x244..+0x263`, and allocates an attachment item at `+0x264`.
- Clone path: `0x0061AA00` does not rebuild the clone from a profile. It allocates a new player actor, creates standalone progression and equip runtimes, allocates a `0x38` selection/control object at `+0x21C`, copies the source actor's descriptor block into robe/hat helper items, transfers the source actor's `+0x264` attachment into the clone's equip attachment sink, maps `source +0x23F` into a concrete `+0x21C` selection id, marks the progression entry active/visible, refreshes progression, and then attaches the actor to gameplay.

The important consequence is:

- `actor + 0x244..+0x263` drives the wizard body colors.
- `actor + 0x264` is a source-side attachment staging slot, not the long-term storage for cloned standalone wizards.
- standalone robe/hat visuals live in equip-linked `0xA8` objects, not directly on the actor.
- `actor + 0x23F` is a coarse render-selection byte, while `actor + 0x21C` is the concrete selection/control state consumed by the animation/render path.
- `actor + 0x22C` is a packed discrete frame offset/countdown field consumed by the frame selector, not a frame-table pointer.
- walking is driven by motion fields such as `+0x220/+0x224/+0x228/+0x234/+0x238/+0x268` and by which animation-advance branch is selected through `+0x160`.

The current bot path still mixes stock pipelines and still hard-forces gameplay slot `1`, but the April 10, 2026 fixes now do three important things in the stock direction: they stop donor-copying the bot's `+0x21C` / `+0x220..+0x263` animation state, restore stock staff ownership transfer into equip sink `+0x30`, and switch standalone actor allocation to `Object_Allocate` while removing the explicit slot-0 `actor + 0x04` alias write. Runtime validation of that `+0x04` change is still pending.

## 1. Render pipeline from actor creation to pixels

### 1.1 Actor must exist as a real player actor

The body renderer lives behind the player actor tick path:

- `0x00548B00` is `PlayerActorTick`
- player actor vtable slot `+0x08` points at `0x00548B00`
- player actor vtable slot `+0x1C` points at `0x0054BA80`, the animation-advance routine

Recovered pseudo-source for `0x00548B00` shows the key high-level requirements:

- `actor + 0x58` owner/world pointer must be valid
- `actor + 0x04` is seeded by `Object_Ctor` with a ctor sentinel and later overwritten with the actor-owned render-context/scene-attachment pointer reused by additive visuals
- movement and animation state are consumed from the `+0x160..+0x268` window
- skipping the real player tick path leaves even registered actors invisible

So the minimal statement is:

- a wizard is not rendered just because an object exists in memory
- it must be a fully initialized player-style actor that is being ticked through the stock path

### 1.2 Source-profile pipeline: build actor-side render state

Function: `0x005E3080` `ActorBuildRenderDescriptorFromSource`

This is the stock builder for actors that still carry a live appearance source profile.

Inputs:

- `actor + 0x174` source kind
- `actor + 0x178` `SdAppearanceSourceProfile*`

Required condition:

- `source->visual_source_type` at profile `+0x4C` must be `3`

Outputs:

- mirrors `source +0x56 -> actor +0x1C0`
- mirrors `source +0x74 -> actor +0x194`
- packs cloth/trim float4 colors from `source +0xB4` and `source +0xC4` into the actor-side descriptor block at `+0x244..+0x263`
- copies selector bytes:
  - `source +0x9C -> actor +0x23C`
  - `source +0x9D -> actor +0x23D`
  - `source +0xA0 -> actor +0x23F`
  - `source +0xA4 -> actor +0x23E`
  - `source +0xA8 -> actor +0x240`
- allocates a source-side attachment object at `actor + 0x264`
  - weapon type `1` creates a staff item
  - weapon type `2` creates a wand item

This is the key distinction:

- `0x005E3080` prepares a source actor for rendering
- it does not create standalone robe/hat visual links
- it does not populate standalone equip sinks

### 1.3 Wizard body rendering consumes actor-local descriptor state

Function: `0x00622430` dispatches to `0x00621780` for wizard bodies when `actor + 0x174 == 3`.

Recovered behavior for `0x00621780`:

- uses `actor +0x23C/+0x23D/+0x23E/+0x240` as sprite/variant selectors
- uses `actor +0x244..+0x263` as the active color payload
- repeatedly passes those packed descriptor dwords into the sprite-draw helpers
- draws multiple body layers from global atlas tables

So the actor-side wizard body render contract is:

- selectors choose which body parts/rows to sample
- the descriptor block provides the actual cloth/trim colors

This means the body color problem is not in the equip helper objects. The body renderer reads the actor-side descriptor block directly.

### 1.4 Attachment rendering is item-driven, not descriptor-driven

Recovered function: `0x0061AF10`

Observed behavior:

- reads `actor + 0x23E` weapon type
- reads `actor + 0x264` attachment object
- calls multiple vtable methods on that item object

High-confidence interpretation:

- the glowing staff orb and other weapon-specific visuals come from the staff/wand item's own rendering behavior
- `actor + 0x264` is the staging pointer that exposes that item to the source-side render path
- the orb is not generated by the actor color descriptor block itself

For cloned standalone wizards, stock behavior is different:

- `0x0061AA00` transfers the source actor's `+0x264` pointer into the clone equip attachment sink at equip `+0x30`
- then clears `source_actor +0x264`

So, for clones:

- long-term ownership should move to the equip attachment sink
- keeping the cloned actor's `+0x264` populated is not the stock design

### 1.5 Player-start path is equipment seeding, not descriptor building

Function: `0x005CFA80` `Gameplay_FinalizePlayerStart`

This is the player-start visual/equipment finalizer. It:

- allocates robe helper (`0xA8`)
- allocates hat helper (`0xA8`)
- allocates default staff (`0x88`)
- allocates two potions (`0x8C`)
- attaches them through gameplay-owned sink holders

Important detail:

- player-start builds the helper color float4s directly and writes them into `item +0x88..+0xA7`
- it is not just reusing `actor +0x244..+0x263`

So `Gameplay_FinalizePlayerStart` is a reference for helper-item construction order, but it is not the same pipeline as source-profile descriptor build or clone-from-source.

## 2. Relevant data structures and offsets

### 2.1 Actor render and animation window

`SdActorEntity` relevant fields from `sd_state.h`:

| Offset | Field | Meaning |
| --- | --- | --- |
| `+0x04` | `render_context` | ctor sentinel first, then scene/render-node attachment pointer reused by draw helpers |
| `+0x58` | `owner` | world/gameplay owner pointer; required by the live tick path |
| `+0x5C` | `slot_index` | gameplay slot/group byte |
| `+0x5E` | `world_slot_index` | resolved ActorWorld slot |
| `+0x6C` | `heading` | actor facing |
| `+0x74` | `move_speed_scale` | speed scalar reused by animation advance |
| `+0x138` | `render_drive_flags` | gates additive helpers and render-side effects |
| `+0x158` | `animation_config_word0` | part of the copied animation-drive config block |
| `+0x15C` | `animation_drive_parameter` | sign and magnitude feed render-side directional helpers |
| `+0x160` | `animation_drive_state` | branch selector for animation-advance logic |
| `+0x174` | `hub_visual_source_kind` | wizard/source-type discriminator; clone path requires `3` |
| `+0x178` | `hub_visual_source_profile` | appearance source profile pointer for `0x005E3080` |
| `+0x1BC` | `animation_move_duration_ticks` | movement-duration accumulator |
| `+0x1C0` | `source_profile_56_mirror` | mirror of source profile `+0x56` |
| `+0x1C4` | `render_drive_effect_timer` | visual effect timer |
| `+0x1D0` | `render_drive_effect_progress` | effect progress scalar |
| `+0x1F0` | `render_drive_idle_bob` | idle bob amount |
| `+0x1FC` | `equip_runtime_state` | standalone equip runtime pointer |
| `+0x200` | `progression_runtime_state` | progression runtime pointer |
| `+0x218` | `move_step_scale` | movement-driven render scalar |
| `+0x21C` | `animation_selection_state` | `0x38` selection/control object pointer |
| `+0x220` | `walk_cycle_primary` | walk-cycle driver |
| `+0x224` | `walk_cycle_secondary` | secondary walk-cycle driver |
| `+0x228` | `render_drive_stride_scale` | stride-length / walk-phase scale |
| `+0x22C` | `render_frame_state` | packed discrete frame offset + countdown state consumed by the frame selector; not a pointer |
| `+0x234` | `render_advance_rate` | frame advance speed |
| `+0x238` | `render_advance_phase` | current frame/phase accumulator |
| `+0x23C` | `render_variant_primary` | primary variant selector |
| `+0x23D` | `render_variant_secondary` | secondary variant selector |
| `+0x23E` | `render_weapon_type` | weapon-type selector |
| `+0x23F` | `render_selection_byte` | coarse render-selection byte |
| `+0x240` | `render_variant_tertiary` | tertiary variant selector |
| `+0x244..+0x263` | `render_descriptor` | packed cloth + trim color data used by body render |
| `+0x264` | `hub_visual_attachment` | source-side attachment item pointer |
| `+0x268` | `render_drive_move_blend` | movement blend scalar |
| `+0x300` | `progression_handle` | wrapper pointer, not the inner runtime |
| `+0x304` | `equip_handle` | wrapper pointer, not the inner runtime |

### 2.2 Source profile

`SdAppearanceSourceProfile` relevant fields:

| Offset | Field | Meaning |
| --- | --- | --- |
| `+0x4C` | `visual_source_type` | must be `3` for live wizard render descriptors |
| `+0x56` | `unknown_56` | mirrored into actor `+0x1C0` |
| `+0x74` | `unknown_74` | mirrored into actor `+0x194` |
| `+0x9C` | `variant_primary` | primary body/hat variant |
| `+0x9D` | `variant_secondary` | secondary body/robe variant |
| `+0xA0` | `render_selection` | coarse helper/pose selection |
| `+0xA4` | `weapon_type` | `1=staff`, `2=wand` |
| `+0xA8` | `variant_tertiary` | tertiary variant |
| `+0xB4` | `cloth_color` | cloth float4 |
| `+0xC4` | `trim_color` | trim float4 |

### 2.3 Actor-side render descriptor block

`SdActorRenderDescriptorBlock` at `actor +0x244..+0x263`:

- `+0x244..+0x253`: packed cloth color dwords
- `+0x254..+0x263`: packed trim color dwords
- `+0x248`: readable as `overlay_alpha` during render-drive overlay work

This block is not a float4 block. It is the actor-side packed sprite color payload used by the body renderer.

### 2.4 Standalone equip runtime and visual links

`SdStandaloneWizardEquipRuntime`:

| Offset | Meaning |
| --- | --- |
| `+0x18` | secondary/hat sink holder |
| `+0x1C` | primary/robe sink holder |
| `+0x30` | attachment/staff sink holder |

Each holder is indirect. The actual sink self pointer is the first pointer inside the holder.

`SdStandaloneWizardVisualLink` / `SdEquipVisualItem`:

- size `0xA8`
- base item object at `+0x00..+0x87`
- `+0x88..+0x97`: primary float4 color
- `+0x98..+0xA7`: secondary float4 color

For stock clone:

- those `0x20` bytes are copied from the source actor's already-packed descriptor block

For stock player-start:

- those `0x20` bytes are built directly as float4 helper colors

### 2.5 Selection/control object at `+0x21C`

`SdActorAnimationSelectionState` recovered size: `0x38`

Confirmed behavior:

- `0x0052A370` allocates `0x38` bytes and stores the pointer at `actor +0x21C`
- it seeds the first dword to `-2`
- the current `functions.csv` label for `0x0052A370` appears stale; direct decomp shows this allocation behavior clearly

The loader's own field tracing also shows the rest of the `0x38` block is not empty metadata. It behaves like a small selection/control brain:

- `+0x00`: selection id
- `+0x04/+0x06`: target slot/handle
- `+0x08/+0x10/+0x14/+0x18`: retarget and action timers
- `+0x1C..+0x34`: heading, pursuit, follow, desired facing, and move-input fields

So the best current name is:

- selection/control state object

## 3. Animation system and frame selection

## 3.1 `+0x23F` is coarse selection, `+0x21C` is the concrete state

Stock clone path `0x0061AA00` makes the relationship explicit:

- read `source_actor +0x23F`
- map it into a concrete selection id written through `actor +0x21C`

Recovered mapping:

| `source +0x23F` | `*(clone +0x21C)` |
| --- | --- |
| `0` | `0x08` |
| `1` | `0x10` |
| `2` | `0x18` |
| `3` | `0x20` |
| `4` | `0x28` |
| `5` | `-2` |

Then, if the mapped selection is non-negative, stock clone:

- ensures progression table capacity
- marks progression entry `+0x20` active
- marks progression entry `+0x22` visible
- calls `0x0065F9A0` `ActorProgressionRefresh`

That is the bridge from coarse render-selection byte to concrete live pose/progression state.

## 3.2 What actually drives standing vs walking

The large animation-advance path at `0x0054BA80` uses:

- `+0x160` branch selector
- `+0x1F0` idle bob
- `+0x220/+0x224` walk-cycle fields
- `+0x228` stride scale
- `+0x234` frame advance rate
- `+0x238` frame/phase accumulator
- `+0x268` movement blend
- `+0x22C` packed discrete frame offset/countdown state
- `+0x21C` selection/control state
- `+0x200` progression runtime

Observed high-level behavior:

- if `actor +0x160 == 0`, `0x0054BA80` runs its main animation-advance branch
- if `actor +0x160 != 0`, it switches to `0x00538550`
- the body render path is `0x00622430 -> 0x00621780`
- the body renderer indexes prebuilt `0xC4` sprite records from the global sprite tables; it does not calculate UVs on demand

Within the main branch:

- `+0x234` and `+0x238` drive phase advance
- `+0x228` and `+0x268` influence stride and movement blending
- `+0x220/+0x224` are walk-cycle inputs reused by NPC property handlers
- `+0x1F0` contributes idle bob when not moving
- the record-selection math is:
  - `record_index = dir24 + (trunc(phase_scalar) * 24) + bank_offset`
  - `dir24 = wrap24(((int)angle + 7) / 15)`
  - `bank_offset` comes from the selector bytes at `+0x23C..+0x240`
  - `+0x22C` is the small discrete offset/countdown value feeding that selection path, not a pointer to a frame table

So:

- standing/idle is primarily the stationary case of the same render-drive system
- walking is the same state with nonzero walk/stride/phase progression
- `+0x21C` chooses the pose/progression lane
- the motion fields decide how that lane advances frame-to-frame

## 3.3 What likely causes the "laying flat" failure mode

The exact semantic names of every selection id are still not fully recovered, so "laying flat" must be stated carefully.

What is firmly supported:

- forcing `+0x160 = 1` changes which animation-advance routine runs
- leaving `+0x21C` null, dangling, or in an invalid state pushes the renderer onto fallback logic
- `0x0054BA80` explicitly falls back to a different frame-set path when selection resolves to `-1`
- stock clone allocates and seeds its own `+0x21C` object and progression selection before it ever relies on the clone visually

So the current best explanation is:

- wrong branch selection at `+0x160`
- or an invalid `+0x21C` selection/control object
- or missing/corrupt discrete frame state and progression state

can leave the actor in a bad pose lane that presents as dead, flat, or otherwise visually broken.

## 3.4 Fields that must be valid for stable animation display

For full stock-like wizard animation, the following fields must be coherent:

- `+0x58` owner/world
- `+0x04` render context / scene attachment
- `+0x1FC` equip runtime
- `+0x200` progression runtime
- `+0x21C` selection/control object
- `+0x22C` discrete frame offset/countdown state
- `+0x23C..+0x240` variant/selection bytes
- `+0x244..+0x263` packed render descriptor
- `+0x160/+0x1BC/+0x220/+0x224/+0x228/+0x234/+0x238/+0x268` motion and phase state

## 4. Visual link and equipment system

## 4.1 What the visual-link objects are

The robe and hat helpers are item-derived `0xA8` objects:

- robe helper ctor: `0x00461F70`
- hat helper ctor: `0x00461ED0`
- attach helper: `0x00575850`

They are attached to equip sinks, not left hanging directly from the actor.

Their visual payload is the `+0x88..+0xA7` block:

- primary float4 at `+0x88`
- secondary float4 at `+0x98`

These objects are descriptor carriers for attached wizard visuals.

## 4.2 Robe/hat sink offsets

Inside standalone equip runtime:

- `equip +0x1C`: primary/robe sink holder
- `equip +0x18`: secondary/hat sink holder
- `equip +0x30`: attachment/staff sink holder

Stock clone path:

- allocates robe helper
- writes active byte and reset field
- copies source actor descriptor into helper `+0x88..+0xA7`
- attaches through the primary sink
- repeats for the hat helper through the secondary sink

That means the robe/hat helper objects are downstream consumers of the already-resolved actor descriptor. They do not originate body colors.

## 4.3 Actor `+0x264` versus equip `+0x30`

These are different stages of the same attachment story:

- `actor +0x264`: source-side attachment pointer created by `0x005E3080`
- `equip +0x30`: standalone clone attachment sink that should own the staff/wand item long-term

Stock clone behavior:

1. take `source_actor +0x264`
2. attach it to clone equip sink `+0x30`
3. clear `source_actor +0x264`

So if a standalone clone still depends on actor-local `+0x264`, it is behaving more like a source actor than like a stock clone.

## 5. Complete stock initialization sequences

## 5.1 Stock player-start path: `0x005CFA80`

This is the startup-player equipment path, not the clone path.

Sequence:

1. build helper color float4s
2. allocate robe helper `0xA8`, seed `+0x88..+0xA7`, attach
3. allocate hat helper `0xA8`, seed `+0x88..+0xA7`, attach
4. allocate default staff `0x88`, install staff vtable/type, attach
5. allocate potions `0x8C`, insert into inventory
6. dispatch gameplay attach/final startup routing

Why it matters:

- it shows the stock constructor/attach order for helper items
- it proves the helper items are real item objects, not actor-only fields
- it does not prove anything about source-profile `+0x264` ownership on clones

## 5.2 Stock standalone clone path: `0x0061AA00`

This is the authoritative wizard clone sequence.

Entry condition:

- `source_actor +0x174 == 3`

Sequence:

1. allocate fresh player actor `0x398`
2. call `0x0052B4C0` `PlayerActorCtor`
3. immediately call `0x0063F6D0` to register the new actor into the stock world/actor bookkeeping path
4. allocate progression inner object `0x8E4`
5. construct progression inner via `0x00674EE0`
6. allocate 8-byte wrapper and store it at `actor +0x300`
7. allocate equip inner object `0x64`
8. construct equip inner via `0x00552FB0`
9. allocate 8-byte wrapper and store it at `actor +0x304`
10. mirror wrapper-resolved inner pointers to:
    - `actor +0x200` progression runtime
    - `actor +0x1FC` equip runtime
11. call `0x0052A370`
    - allocates `0x38` selection/control object
    - stores it at `actor +0x21C`
    - seeds `*(actor +0x21C) = -2`
12. clear actor flag at `+0x38`
13. allocate robe helper `0xA8`, set active/reset, copy source actor `+0x244..+0x263` into helper `+0x88..+0xA7`, attach to equip primary sink
14. allocate hat helper `0xA8`, same descriptor copy, attach to equip secondary sink
15. attach source actor `+0x264` item into clone equip attachment sink `+0x30`
16. clear `source_actor +0x264`
17. copy source movement-facing data:
    - heading `+0x6C`
    - speed scale `+0x74`
    - position `+0x18/+0x1C`
18. map `source +0x23F` to concrete selection id written through `+0x21C`
19. if selection id is non-negative:
    - ensure progression table capacity
    - mark entry active
    - mark entry visible
    - call `0x0065F9A0` `ActorProgressionRefresh`
20. call gameplay attach through the gameplay-owned virtual path
21. call source actor virtual at slot `+0x18`

What the stock clone path does not do:

- it does not call `0x005E3080` on the clone
- it does not synthesize a new source profile for the clone
- it does not copy the donor's entire resolved render-state window
- it does not leave the transferred attachment at clone `+0x264`
- it does not patch the clone into gameplay slot `1`

## 5.3 Minimal stock-like requirements for a new wizard actor

To make a new standalone wizard actor behave like stock clone, the required order is:

1. create a real player actor
2. create progression wrapper + inner and assign them to `+0x300` and `+0x200`
3. create equip wrapper + inner and assign them to `+0x304` and `+0x1FC`
4. allocate the `+0x21C` selection/control object
5. provide valid selector bytes and descriptor payload
   - either by cloning from a source actor
   - or by recreating the same result cleanly
6. create and attach robe/hat helper items into equip sinks
7. ensure staff/wand item ownership ends up in equip sink `+0x30`
8. seed heading/position/speed fields
9. seed `+0x23F` and the mapped `+0x21C` selection id
10. mark the corresponding progression entry active/visible and refresh progression
11. register/attach the actor into world/gameplay so the real player tick path sees it
12. ensure render context `+0x04` and owner `+0x58` are valid

## 6. What was broken in the pre-fix bot implementation

## 6.1 The loader mixes incompatible stock paths

Current bot materialization code in `src/mod_loader_gameplay/standalone_materialization*.inl` still bridges:

- source-profile builder logic (`0x005E3080`)
- player-start helper construction logic
- clone-from-source logic
- until the residual fix, a non-stock raw allocation path using `_aligned_malloc` plus direct constructor invocation

The key bridge is `SeedGameplaySlotBotRenderStateFromSourceActor`, plus
`CreateWizardCloneSourceActor`, which:

- synthesizes a source profile
- calls `ActorBuildRenderDescriptorFromSource`
- then, before the April 10, 2026 fix, copied donor-owned animation state back over the bot anyway

Relevant loader sections:

- `standalone_materialization_slot_bot_creation.inl`
- `standalone_materialization_wizard_clone_source.inl`
- `core/synthetic_wizard_source_profiles.inl`

That is not the stock clone design.

## 6.2 Pre-fix donor resolved-render copying was too broad

Before the fix, the loader copied donor-owned windows that covered:

- `+0x138..+0x163`
- `+0x174..+0x1FB`
- `+0x21C..+0x263`

That means the bot may receive donor-owned or donor-derived state for:

- source kind/profile area
- selection/control state pointer
- discrete frame state and motion state
- attachment staging area up to but not including `+0x264`

Stock clone does not do that. Stock clone creates fresh control/runtime objects and transfers only specific visual payloads.

The loader fix removes that donor-window copy and keeps the bot's own `+0x21C`, `+0x220..+0x263`, and attachment ownership intact.

## 6.3 The branch-selector bug was already fixed

An earlier loader revision forced the idle bot onto the alternate animation branch by writing:

- `actor +0x160 = 1` unconditionally

See:

- `scene_and_animation_drive_profiles.inl`, `ClearLiveWizardActorAnimationDriveState`
- `bot_movement/locomotion_and_animation.inl`, `StopWizardBotActorMotion`

That directly conflicts with the recovered `0x0054BA80` behavior:

- main animation-advance branch only runs when `+0x160 == 0`
- nonzero `+0x160` routes to `0x00538550`

The current helper no longer does that. Idle writes `+0x160 = 0`, which keeps the bot on the main `0x0054BA80` branch.

## 6.4 Pre-fix staff ownership diverged from stock

Before the April 10, 2026 fix, bot finalization created robe/hat visuals but left the stock-built attachment parked on actor `+0x264` instead of transferring it into the equip sink.

The current loader now:

- creates robe helper
- creates hat helper
- transfers the stock-built attachment from `actor +0x264` into equip sink `+0x30`
- clears the actor staging slot after native attach

See:

- `FinalizeStandaloneWizardBotActorState` around `3320`

That matters because the source-side `+0x264` object is created by the same path that chose weapon type and source visual state.

April 11, 2026 runtime follow-up:

- keeping source-profile `weapon_type = 1` is still useful during the synthetic build because it creates the stock staff attachment item
- but leaving actor `+0x23E = 1` afterward creates a second visible weapon layer on the standalone bot
- the current loader now normalizes actor `+0x23E` back to the donor/player value after the synthetic source build while leaving the equip attachment intact

Live validation from the April 11 build:

- `bot.render_weapon_type = 0`
- equip `+0x30` still holds a non-null attachment object
- the staff orb still renders, which confirms the orb comes from the attachment path rather than actor-side `+0x23E`

## 6.5 World registration order differs from stock

Stock clone registers the new actor immediately after construction, before progression/equip/link priming.

Current loader path:

- constructor
- extensive priming
- world register later

See:

- loader spawn path around `5416`

This may not be the root visual bug, but it is a real sequencing difference from stock.

## 6.6 The loader still needs non-stock scene/render hacks

Before the residual fix, the loader:

- forced the bot into gameplay slot `1`
- wrote `gameplay + slot-table` entry
- copied slot-0 player's `actor +0x04` render-context pointer into the bot

See:

- `FinalizeStandaloneWizardBotActorState` around `3413`

That was strong evidence that the bot did not own its own clean render/scene attachment state. The current code removes the `+0x04` alias write and instead relies on stock actor allocation/init to populate that field. In-game validation is still needed.

In stock clone, those writes are not part of the recovered sequence.

## 6.7 Pre-fix finalization and per-tick repair reapplied donor animation state

Before the fix, the loader:

- copies donor animation state id into bot `+0x21C`
- and the per-tick repair helper also restored donor-derived animation ids while the bot moved/idle-switched
- calls `ApplyStandaloneWizardPuppetDriveState(actor, false)`

See:

- spawn tail around `5675`

Stock clone instead:

- maps `+0x23F` into `+0x21C`
- marks progression state active/visible
- refreshes progression once

That is much tighter and does not depend on donor post-copy patching.

The April 10 fix already reasserted `ResolveStandaloneWizardSelectionState(wizard_id)` after spawn/finalize and during standalone bot repair, which kept the bot on its own wizard lane while still allowing the stock movement/frame logic to run.

The April 11 cutover removed the remaining live player coupling from the drive-profile side:

- standalone bots now cache bot-owned animation-drive profiles at spawn/finalize
- per-tick standalone repair reapplies those cached bot profiles instead of the player's live observed profile globals
- the player globals are still useful for seeding new spawns, but they no longer drive already-materialized standalone bots

Live validation from April 11:

- writing obviously wrong walk/stride values into the player actor did not propagate into a stopped standalone bot on the next tick
- that confirms the remaining player-to-bot animation-drive leak is gone

## 7. What future fixes should treat as ground truth

The safest stock-aligned model is:

- treat `+0x174/+0x178/+0x244..+0x264` as the source-side visual staging area
- treat robe/hat helper items and equip sink `+0x30` as the standalone-clone equipment state
- treat `+0x23F` as input and `+0x21C` as the concrete live selection state
- treat `+0x160` as an animation-branch selector that must not be hard-forced incorrectly
- treat `+0x22C/+0x234/+0x238/+0x220/+0x224/+0x228/+0x268` as the motion/frame-driving state that must remain coherent

If the bot path reintroduces donor `+0x21C` writes or donor copies of `+0x220..+0x263`, fixes will remain fragile.

## 8. High-confidence conclusions

1. The wizard body renderer reads the actor-local descriptor block at `+0x244..+0x263` directly.
2. The glowing staff/wand visuals come from an item object, not from body descriptor colors.
3. `actor +0x264` is a source-side attachment slot. Stock standalone clones transfer that object into equip sink `+0x30`.
4. `actor +0x21C` is a required `0x38` live selection/control object, not just an optional cached int.
5. `actor +0x23F` is not the final active animation state. Stock clone maps it into concrete `+0x21C` ids.
6. The key animation desync bugs came from donor-clobbering bot-owned `+0x21C` and `+0x220..+0x263` state after runtime initialization, and later from per-tick reuse of the player's live observed drive profile. The current loader fix removes that overwrite, caches bot-owned drive profiles, and restores stock staff transfer.

## 9. Remaining uncertainty

One detail remains slightly inferential:

- the exact visual call chain that produces the visible glowing orb effect inside the staff/wand item rendering
- the exact stock step that repopulates clone-side actor fields `+0x23C..+0x263` after `0x0061AA00`

That second point matters because:

- the body renderer clearly consumes actor-local selector and descriptor state
- the recovered clone-factory slice explicitly shows descriptor copies into robe/hat helper items
- but the recovered slice does not yet show a direct clone-actor copy of that same `0x20` block

The most likely candidates are:

- constructor defaults in `PlayerActorCtor`
- later refresh work around `0x0065F9A0`
- gameplay attach side effects

That gap does not change the proven ownership model, but it does mean clone-side actor descriptor reconstruction is the remaining piece still worth tracing before making another low-level fix.

What is not uncertain is the ownership model:

- the orb comes from the attachment item path
- not from the actor body descriptor block
- and not from the robe/hat visual-link helpers
