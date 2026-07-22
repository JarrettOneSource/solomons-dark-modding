# Native art and gameplay live validation

## Scope and isolation

This is the runtime counterpart to the static native-art decompilation. It
validates representative ownership and materialization contracts without
changing the stock executable or using another worker's game process.

| Property | Value |
| --- | --- |
| Date | 2026-07-21 |
| Research worktree | `Solomon Dark Native Asset RE 20260721/Mod Loader` |
| Research instance | `native-asset-re-20260721` |
| Research process | PID 11296 |
| Executable module base | `0x00510000` |
| Static image base | `0x00400000` |
| ASLR delta | `+0x00110000` |
| Enabled mod | `sample.lua.ui_sandbox_lab` only |
| Multiplayer | disabled |

PID 11296 was resolved to the executable staged beneath the research
worktree before every OS-level click. A separately staged `SolomonDark.exe`
was observed under a different checkout and PID and was never clicked,
stopped, traced, or otherwise controlled by this pass.

The live API distinction matters when reproducing this evidence:
`sd.debug.read_field_*` treats its first argument as a pointer slot and follows
it. Once an object pointer is already resolved, object fields must be read with
direct `sd.debug.read_u32(object + offset)`, `read_u8`, or `read_float` calls.
The original image addresses were also explicitly rebased by the observed
ASLR delta; a coincidentally readable unrebased address is not proof that it is
the active module location.

## Scene transition proof

The session exercised the stock Create, Hub, arena, Game Over, Hall of Fame,
and main-menu paths.

1. The Create owner reported element selection `3`, discipline controls
   enabled, and no discipline selected after a real click on Water.
2. A second real click on Arcane caused the Create surface to disappear and
   produced a stable Hub scene.
3. `sd.hub.start_testrun()` entered a stable arena. The first call correctly
   initialized the loader's scene-stability gate; a later call, after its
   4.5-second Hub settling interval, succeeded.
4. Starting waves produced stock Skeleton actors and the native Game Over
   screen. Clicking through it produced Hall of Fame and then the stock main
   menu.

The stable scene snapshots were:

| Scene | Kind | Region type | Region index | Representative native state |
| --- | --- | ---: | ---: | --- |
| Hub | `hub` | 4001 | 0 | gameplay `0x1C050380`, world `0x1BF065D0`, arena `0x1BFDBDA8`, local Player live |
| Test run | `arena` | 4006 | 5 | world `0x1BFDBDA8`, wave 1 reached, stock enemies materialized |

The Create automation overlay can report that an action was dispatched before
the native widget state has latched. The Water and Arcane observations above
therefore use the owner fields and resulting native scene transition, not the
dispatch response alone.

## Atlas acquisition and release

Every generated atlas singleton was sampled at its rebased global. For a live
bundle, `+0x1C` is the acquisition count, `+0x28` is the page count in this
retail single-page set, `+0x34` is the resident flag, and `+0x35/+0x36` are the
threaded/busy bytes. Every resident atlas below owned exactly one image page;
all sampled threaded/busy bytes were zero after the scene settled.

| Atlas | Create refs | Hub refs | Arena refs | Game Over refs |
| --- | ---: | ---: | ---: | ---: |
| BadGuys | 1 | 1 | 1 | 1 |
| Clothes | 1 | 1 | 1 | 1 |
| College | 0 | 1 | 0 | 0 |
| Create | 1 | 0 | 0 | 0 |
| DeadHawg | 0 | 0 | 2 | 2 |
| Fonts | 1 | 1 | 1 | 1 |
| GameOver | 0 | 0 | 0 | 1 |
| Inventory | 1 | 1 | 1 | 1 |
| LevelPicker | 0 | 1 | 0 | 0 |
| Skills | 1 | 1 | 1 | 1 |
| Solomon | 0 | 0 | 1 | 1 |
| UI | 1 | 1 | 1 | 1 |

All other sampled scene-specific atlases had a zero acquisition count and
zero resident/page state in these scenes. The transitions provide direct
runtime confirmation of the common acquire/release contract:

- leaving Create released the Create page;
- entering Hub acquired College and LevelPicker;
- entering the test run released those Hub pages and acquired DeadHawg and
  Solomon;
- displaying the death overlay acquired GameOver without releasing the arena
  presentation beneath it.

The Loader singleton is a special confirmed case. After startup its global
still contained `0x02C4A4F8`, but that allocation no longer had the atlas
vtable or coherent bundle fields. This is a dangling global left after the
startup owner destroys/releases its embedded Loader bundle; it is not a
resident singleton that later screens may safely dereference. That observation
agrees with the static proof that the retail loader renderer draws primitives
and never selects Loader records 0..4.

## Representative native objects

The first stable arena began with the expected graph:

| Type | Class | Runtime evidence |
| ---: | --- | --- |
| 1 | Player | slot 0, 50/50 HP before combat, live progression and world pointers |
| 5009 | Solomon_Dig | factory object present in the arena at world slot 3 |
| 5010 | Lantern | factory object present in the arena at world slot 2 |

After wave start, eleven live type-1001 actors were enumerated in one sample.
Each resolved to the rebased Skeleton vtable, carried 2.5/2.5 HP, occupied a
world slot, and was reported as a tracked enemy. This joins the static
factory/config map to the actual wave materialization path.

The live stock item-recipe registry contained exactly 47 definitions, matching
the parsed `items.cfg` catalog. The first entries demonstrated the runtime UID
assignment and native item classes: UID 1 was type 7002 Ring, UID 2 was type
7006 Robe, UID 3 was type 7011 Wand, and UID 4 was type 7003 Amulet.

Two ground-reward paths were then materialized through the loader's existing
native seams:

| World actor | Type | Live fields |
| --- | ---: | --- |
| Gold | 2012 | tier `+0x13C = 2`, amount `+0x140 = 7`; actor appeared in the stock world list |
| Sack carrier | 2013 | held-item pointer at `+0x148`; held object type 7002 with recipe UID 1 at item `+0x18` |

The Sack evidence is important: the ground object owned a concrete cloned Ring
pointer. It was not an icon-only or generic metadata representation. This is
the exact ownership relationship transferred into inventory by the native
pickup path documented in
[native-items-equipment-and-loot.md](native-items-equipment-and-loot.md).

## What this validation does and does not claim

The live pass validates the architectural boundaries with representative
objects: scene-driven atlas lifetime, compiled factory identity, stock wave
enemy materialization, the recipe registry, concrete ground-item ownership,
and overlay acquisition. Static exhaustive catalogs remain the source of truth
for every skill, spell, projectile, enemy family, NPC, item effect, sound, and
individual sprite-record consumer; spawning every finite member would add
runtime samples, not discover a different ABI.

An optional input-injection cast probe did not produce a cast in a resumed
post-Hall-of-Fame arena whose player selection pointer was null. The research
process later ended without an Application Error event or crash dump. This is
recorded as a harness/scene-readiness limitation, not evidence against the
statically recovered cast dispatch. No native claim in the coverage ledger
depends on that optional probe.
