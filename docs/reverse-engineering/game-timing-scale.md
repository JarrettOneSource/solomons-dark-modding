# Game timing global investigation

Investigation date: 2026-07-22

The roadmap originally treated `0x00820230` (`kGameTimingScaleGlobal`) as a writable game
speed multiplier suitable for `sd.time.set_scale`. Static and live evidence do not support
that contract.

## Evidence

A read-only live Lua probe resolved the rebased address and read `100.0`. No write was
attempted.

Headless Ghidra xrefs were collected with:

```powershell
./scripts/Invoke-GhidraHeadless.ps1 `
  -ProjectRoot './Decompiled Game/ghidra_project' `
  -ReplicaRoot './Decompiled Game/ghidra_project_replicas' `
  -ScriptPath tools/ghidra-scripts/refs_to_addr_decompile.py `
  -ScriptArguments 0x00820230,40
```

The binary has 136 references across 78 containing functions (plus one reference outside a
function). Decompiled users repeatedly treat the value as ticks per second:

- duration construction multiplies seconds by the global;
- per-tick rates divide by the global;
- two-second timers add the global to itself; and
- wave and actor timing compares counters against values multiplied by the global.

Representative expressions include `1.0 / _DAT_00820230`,
`field / _DAT_00820230`, `_DAT_00820230 * constant`, and
`_DAT_00820230 + _DAT_00820230`.

## Conclusion

This address is a native tick-frequency conversion constant, not a general simulation speed
control. Setting it to zero would introduce divide-by-zero behavior throughout unrelated
systems. Changing it to another value would alter duration/rate conversions inconsistently
with already-created counters and cannot provide a trustworthy pause or frame step.

The implemented `sd.time` seam gates coherent world frames at the existing actor-world,
player-actor, and wave-spawner tick boundaries, composes with the multiplayer menu/level-up
pause predicate, and replicates authority-owned state. The resolved global is not used as
an implementation shortcut; see `../lua-time.md` for the public contract.
