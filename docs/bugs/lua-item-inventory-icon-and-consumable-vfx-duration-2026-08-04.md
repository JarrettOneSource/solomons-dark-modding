# Lua item inventory icons and consumable VFX end early

## Investigation

The Invincibility Potion registers its sprite atlas before calling
`sd.items.register`. Its descriptor resolves the registered atlas and frame,
declares `duration_ms = 180000`, and receives native potion subtype `6`.
Existing two-peer acceptance also proves that the same atlas renders on the
ground, the drop enters the stock inventory, the item is consumed, and both
peers receive the replicated `item.consumed` event.

A beta.32 hosted-pair reproduction isolated the two presentation failures:

- the host's native inventory contained one type `0x1B59`, subtype `6` row;
- opening the real stock inventory showed the health and mana potion icons but
  no green custom-potion icon;
- the live Inventory potion-sprite array had grown to seven records, but record
  `6` retained a clear native validity byte;
- both peers initially rendered the green `SpellGlow`, with 2,962 and 3,037
  matching green pixels in the player crop;
- 13.5 seconds after use, both peer crops contained zero matching green
  pixels; and
- a native 12-damage trial at the same point remained completely canceled,
  leaving life at `50.0`.

The reproduction is recorded under
`/mnt/d/codex-evidence/potionvfx-20260804/baseline/focused/`. The earlier
loading-screen false-positive is retained separately under
`baseline/focused-failed-loading-screen-1/`.

## Inventory icon root cause

Stock potion inventory rendering enters `0x00579A90`. The function reads the
potion subtype from item `+0x1C`, grows the Inventory potion-sprite array
through `0x0043A6B0` when necessary, indexes the resulting `0xC4`-byte record,
and calls the translated, uniformly scaled sprite renderer at `0x00414EA0`.
Its three stack arguments are the two translations and the item scale from
`item +0x64`.

The Lua item presentation hook only intercepts `Glyph_Draw` at `0x004143D0`.
That is the correct native boundary for a potion carrier in the world, but the
stock inventory path does not call it. The custom subtype's dynamically grown
record is therefore passed to `0x00414EA0` unchanged with its validity byte
clear, so the inventory renderer has nothing to draw. The loader never gets an
opportunity to replace that record with the registered mod atlas.

This is a missing loader seam, not a canary registration bug. The repair must
intercept the scaled Inventory sprite draw and resolve registrations by native
subtype. It must not special-case the Invincibility Potion content ID. Every
registered custom item that carries icon metadata through this native path
must receive the same substitution while stock items continue through the
original renderer unchanged.

## VFX duration root cause

`LuaConsumableDefinition` stores the declared `duration_ms`, and the
`item.consumed` event exposes that value to the mod on every peer. The potion's
handler uses `event.duration_ms` for the table that drives its damage and mana
filters, so the gameplay effect remains active for three minutes.

The native presentation clock is independent. `LuaConsumableNativeVfxRequest`
contains only content, participant, and use IDs. When the gameplay pump accepts
the request, it creates an active pulse with
`expires_at_ms = now_ms + 12000`. The hard-coded
`kSpellGlowPulseDurationMs` came from the earlier activation-visibility repair;
it never represented the consumable's effect window.

The replicated event, target resolution, and mod timer all behaved correctly
in the live reproduction. The early disappearance is therefore entirely in
the loader's presentation lifetime. The generic `consume_vfx` contract must
refresh the native effect for the registered consumable's declared duration
on every peer. A zero-duration consumable may render only its initial native
frame; a nonzero duration must not be shortened by a loader-owned pulse
constant.

## Required repair and proof

- Add the correctly typed `0x00414EA0` scaled-sprite seam and substitute the
  registered atlas at the stock Inventory draw boundary for every matching
  registered custom subtype.
- Preserve the stock health-potion Inventory geometry, anchor, translation,
  and item scale; do not mutate the incomplete grown record.
- Derive `consume_vfx` expiry from immutable registered `duration_ms` and keep
  refresh/cleanup bounded by the existing runtime limits.
- Pin both paths with regression contracts that reject a canary-ID special
  case and reject a fixed presentation-duration constant.
- On the published commit, prove pickup and the green icon in the real native
  inventory, then prove the VFX on both peers immediately before the
  three-minute effect expiry, damage cancellation before expiry, VFX removal
  after expiry, and resumed damage after expiry.

These are loader presentation fixes. The mod's registered icon, declared
duration, and gameplay behavior are already correct, so this investigation
does not change the mod package or add mod features to loader release notes.
