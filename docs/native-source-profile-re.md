# Native Source Profile RE

## Scope

This note tracks the former loader-owned wizard source-profile workaround. The
old path allocated a fake `actor+0x178` profile buffer, filled selector/color
fields in C++, staged it on a temporary `0x1397` source actor, called
`0x005E3080`, then cloned through `0x0061AA00`.

That hardcoded workaround is removed. Bot materialization now creates the same
temporary `0x1397` source actor shell, builds a transient native-derived source
profile from live `Skills_Wizard` color output and the native source actor's
default trim color, lets `0x005E3080` publish the stock descriptor window, then
calls `0x0061AA00`. The transient profile is cleared before clone publication;
finalized player and bot actors still keep `actor+0x178 == 0`.

## Verified Native Contracts

- `0x005E3080` (`ActorBuildRenderDescriptorFromSource`) is the native consumer
  for actor `+0x178` source profiles. It reads source kind, selector bytes,
  weapon type, and cloth/trim color fields, then publishes actor render fields
  and helper attachments.
- `0x0061AA00` (`WizardCloneFromSourceActor`) does not require a live
  `actor+0x178` pointer. It gates on source actor `+0x174 == 3`, copies the
  prepared descriptor window at `+0x244..+0x260`, consumes source selector
  `+0x23F`, and transfers source attachment `+0x264` if present.
- `0x005E9A90` constructs the temporary source actor shell and zeroes
  `actor+0x174/+0x178`; it is still the right native constructor for the source
  actor, but not a source-profile producer.
- `0x005B7080` maps factory type `0x1397` to the temporary source actor
  allocation path that reaches `0x005E9A90`.
- `0x005D0290` documents the stock new-character choice mapping and calls
  `0x00660320` (`PlayerAppearance_ApplyChoice`). It maps create-screen choices
  through native entries before refreshing `Skills_Wizard`, but those entries
  were not a correct bot identity seam: applying them directly made all current
  all-bot trims discipline-colored instead of element-identifying.
- `0x00515290` was checked as an `actor+0x174/+0x178` writer candidate and
  rejected as an offset collision outside the wizard source-profile producer
  path.
- `0x00660760` is the native element color seam. The loader calls it through
  `CallSkillsWizardGetPrimaryColorSafe` with the profile's recovered native
  primary entry. That native output is a descriptor-facing target color, not a
  raw source-profile cloth color: live probes showed that writing it directly
  to profile `+0xB4` made `0x005E3080` apply the stock robe mix a second time,
  producing pale robes. The production path now converts the native target
  color back to the required source-profile preimage using the recovered
  `0x0040FC60` robe mix (`0.2 * source + 0.8 * luminance`, with
  `0.3086/0.6094/0.0820` channel weights), then lets `0x005E3080` run the
  native mix once. Trim comes from the native `0x005E9A90` source actor's own
  default trim block instead of being copied from the element color.
- The actor descriptor at `+0x244..+0x263` is helper-publication payload, not a
  stable finalized-player color source, so the production path does not read
  finalized actor descriptor bytes back as source colors.

Evidence artifacts:

- `runtime/ghidra_synthetic_source_profile_paths.txt`
- `runtime/ghidra_source_profile_candidate_producers.txt`
- `runtime/ghidra_source_profile_offset_accesses.txt`
- `runtime/ghidra_source_profile_negative_producer_scan.txt`
- `runtime/ghidra_source_profile_actor174_expanded_scan.txt`
- `runtime/ghidra_source_profile_field_candidate_decompiles.txt`
- `runtime/ghidra_source_profile_write_sites_expanded.txt`
- `runtime/live_source_profile_negative_probe.json`
- `runtime/live_source_profile_writer_probe.json`

## Resolution

The production replacement is native-derived source-profile staging:

- `CreateWizardCloneSourceActor` receives the live slot-0 visual actor and the
  bot character profile.
- `BuildNativeDerivedWizardSourceProfile` resolves the live progression runtime
  from the visual actor, calls `0x00660760` for the native element color seam,
  converts that native target color through the recovered `0x0040FC60` preimage
  for cloth, reads the source actor's native default trim color, and fills only
  the staging fields consumed by `0x005E3080`.
- `SeedWizardCloneSourceActorFromNativeDerivedProfile` stages that transient
  buffer at source actor `+0x178`, calls `ActorBuildRenderDescriptorFromSource`,
  then clears `+0x178/+0x17C` before cloning.
- The source actor remains marked with `kWizardCloneSourceActorKind == 3` so
  `0x0061AA00` consumes the prepared descriptor window normally.
- The cloned bot receives a stock clone from a prepared native source actor.
  Standalone bots keep the stock `0x0061AA00` publication: the source
  descriptor goes into robe/hat helper items and the source attachment moves
  through the equip attachment sink. The loader does not copy packed descriptor
  bytes onto clone actor `+0x244`, because that live actor window overlaps
  native animation/render counters. Gameplay-slot bots likewise publish the
  descriptor through native helper lanes before attaching their own staff item.
  Both paths publish only the safe source-built selector bytes at
  `+0x23C/+0x23D/+0x23F/+0x240` onto the target actor; the packed descriptor
  block remains helper-lane/source-side state.

This removes the hardcoded source-profile template, element color table, and
default appearance-choice mapping from active runtime code while preserving
element-specific visuals from native live data. The active code carries no
element-specific color table; the only color math is the documented inverse of
the native descriptor mix so the stock builder receives the kind of source
profile color it expects.

## Live Coverage

`tests/re/run_live_source_profile_negative_probe.py` validates that finalized
player and bot actors keep `actor+0x178 == 0`, and that logs contain
`native_derived_visual_seed_before`, `native_derived_visual_seed_after`,
`native-derived source profile`, `native-derived clone-source seeded`, and
`clone_source_ready`.

`tests/re/run_live_source_profile_writer_probe.py` keeps the finalized player
source-profile write watch and native traces. A passing run proves bot
materialization still reaches the known native source-actor constructor,
descriptor builder, and clone path without publishing a reusable source-profile
pointer or writing the finalized player's source-profile window.

The runtime log line includes the native target color, source-profile cloth
preimage, and native default trim so cloth and trim regressions are visible
without reading finalized actor descriptor bytes.

## Remaining RE

A future cleanup can remove the transient adapter if one of these native seams
is recovered:

- a native create-screen/save-slot source-profile object pointer that can be
  copied or referenced safely;
- a native constructor/materializer that accepts appearance choice ids and fills
  the `0x005E3080` source-profile fields;
- a higher-level native actor materialization path that bypasses manual
  source-profile buffers entirely.
