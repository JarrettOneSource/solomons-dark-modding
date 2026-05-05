# Native Source Profile RE

## Scope

This note tracks the former loader-owned wizard source-profile workaround. The
old path allocated a fake `actor+0x178` profile buffer, filled selector/color
fields in C++, staged it on a temporary `0x1397` source actor, called
`0x005E3080`, then cloned through `0x0061AA00`.

That hardcoded workaround is removed. Bot materialization now creates the same
temporary `0x1397` source actor shell, builds a transient native-derived source
profile from live `Skills_Wizard` color output, lets `0x005E3080` publish the
stock descriptor window, then calls `0x0061AA00`. The transient profile is
cleared before clone publication; finalized player and bot actors still keep
`actor+0x178 == 0`.

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
  `0x00660320` (`PlayerAppearance_ApplyChoice`), but it is coupled to
  create-screen globals and a specific progression owner. It is evidence, not a
  production seam for arbitrary bot visuals.
- `0x00515290` was checked as an `actor+0x174/+0x178` writer candidate and
  rejected as an offset collision outside the wizard source-profile producer
  path.
- `0x00660760` is the native `Skills_Wizard` primary-color seam. The loader
  calls it through `CallSkillsWizardGetPrimaryColorSafe` using the profile's
  recovered native primary entry and feeds that native color directly into the
  transient source profile. `TryReadActorDescriptorColor` reads the live native
  visual actor's second descriptor color when available; otherwise the native
  primary color is reused for both descriptor color payloads. The old C++
  inverse luma/mix reconstruction is gone because those scalars were not
  recovered as native operands.

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
  from the visual actor, calls `0x00660760`, reads the live descriptor accent
  color when available, and fills only the staging fields consumed by
  `0x005E3080`.
- `SeedWizardCloneSourceActorFromNativeDerivedProfile` stages that transient
  buffer at source actor `+0x178`, calls `ActorBuildRenderDescriptorFromSource`,
  then clears `+0x178/+0x17C` before cloning.
- The source actor remains marked with `kWizardCloneSourceActorKind == 3` so
  `0x0061AA00` consumes the prepared descriptor window normally.
- The cloned bot receives a stock clone from a prepared native source actor.
  Gameplay-slot bots still attach their own staff item afterward through the
  existing native helper-lane path.

This removes the hardcoded source-profile template, element color table, and
default appearance-choice mapping from active runtime code while preserving
element-specific visuals from native live data.

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

## Remaining RE

A future cleanup can remove the transient adapter if one of these native seams
is recovered:

- a native create-screen/save-slot source-profile object pointer that can be
  copied or referenced safely;
- a native constructor/materializer that accepts appearance choice ids and fills
  the `0x005E3080` source-profile fields;
- a higher-level native actor materialization path that bypasses manual
  source-profile buffers entirely.
