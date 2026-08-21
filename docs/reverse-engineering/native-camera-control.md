# Native gameplay camera control

Investigation date: 2026-07-22

This investigation used the configured Solomon Dark 0.72.5 executable and the
existing headless Ghidra project. It establishes the native fields and update
phase used by `sd.camera`; it does not infer a standalone camera object that the
binary does not have.

## Region view layout

The gameplay camera is Region-owned. The confirmed `ActorWorld`/Region fields
used by the seam are:

| Offset | Meaning |
|---:|---|
| `+0x80` | world-to-screen scale |
| `+0x8BCC/+0x8BD0` | primary view origin x/y |
| `+0x8BD4/+0x8BD8` | primary view width/height |
| `+0x8BDC/+0x8BE0` | expanded view origin x/y |
| `+0x8BEC/+0x8BF0` | culling view origin x/y |
| `+0x8E04/+0x8E08` | shake magnitude/accumulator |

`0x0063ED80` projects a world point as `(world - origin) * scale`.
`0x00462110` performs the inverse as `screen / scale + origin`. Translating the
three rectangle origins together therefore moves presentation and hit
projection without moving actors or changing viewport dimensions.

## Stock update phase

Six Region subclass ticks write the stock view late in their update:

| Region tick | Address |
|---|---:|
| Arena | `0x0046E570` |
| Courtyard | `0x0050C970` |
| Mortuary | `0x00509330` |
| StoreRoom | `0x00504220` |
| Library | `0x00504BB0` |
| Office | `0x00509F10` |

The safe override point is after each original tick. A pre-tick write would be
immediately replaced by stock tracking. The loader consequently detours each
entry, calls its trampoline first, then applies one shared translation delta to
the primary, expanded, and culling origins. Clearing the request performs no
write and lets the next stock tick take over.

## Shake path

`Region::ApplyCameraShake` at `0x0063EEB0` writes the magnitude at `+0x8E04`
from the accumulator clamped to `1` times the requested intensity. It advances
the accumulator at `+0x8E08` by the native increment and caps it at the native
maximum. `Region::Tick` at `0x0063EFC0` damps these feedback lanes; native render
paths consume the magnitude. Skeleton death independently calls this routine
with `0.1`, corroborating the path documented in
[`../skeleton-death-effects-re.md`](../skeleton-death-effects-re.md).

The exact constants and Arena consumer are now closed. Construction writes
both fields to zero. The apply call uses
`magnitude = min(accumulator, 1) * requestedIntensity`, adds
`0.20000000298023224` to the accumulator, and caps it at `3.5`. Each Region
tick subtracts `0.0025` from the accumulator with a `0.1` floor, multiplies
magnitude by `0.94`, and zeros it below `0.001`. Arena render
`0x0046F100..0x0046F276` applies a uniform XY scale of `1 + magnitude` around
the local Player's projected point. It is therefore a local-player-anchored
world pulse, despite the historical shake name, and has no random offset.
Coffin death independently requests intensity `0.2`. The full death-member
closure matters beyond presentation because Hall Awesomeness reads this same
accumulator: Skeleton/Archer/Mage and Zombie request `0.1`; accepted Imp split
requests `0.05` while terminal Imp requests `0.1`; Wraith requests `0.1`
twice; and Demon, Coffin, Dire Faculty, and Heartmonger request `0.2`.

## Reproduction

The analysis was run through the repository's replica-pool wrapper so the
canonical Ghidra project remained untouched:

```powershell
./scripts/Invoke-GhidraHeadless.ps1 `
  -ProjectRoot './Decompiled Game/ghidra_project' `
  -ReplicaRoot './Decompiled Game/ghidra_project_replicas' `
  -ScriptPath tools/ghidra-scripts/decompile_at.py `
  -ScriptArguments 0x0063EEB0
```

Equivalent decompilation passes at the six tick addresses, `0x0063EFC0`,
`0x0063ED80`, and `0x00462110` recover the update order, damping, and projection
formulas above. The layout keys live in `config/binary-layout.ini`; the public
contract intentionally exposes no addresses or pointers.
