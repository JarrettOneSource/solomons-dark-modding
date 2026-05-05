# Native Ally HP Defaults RE

## Scope

This note covers the old allied wizard HP workaround in:

- `SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_standalone_wizard.inl`

The removed registered GameNpc rail had the same historical issue before the
rail itself was deleted from active code. The standalone path previously cloned
a wizard actor and then overwrote the clone
progression HP and max HP with `25.0f`. That write was not a native value. It
hid the constructor/recompute contract instead of proving it, and has been
removed.

## Verified Native Constructor Path

- `0x0061AA00` is the native clone-from-source actor path used by the loader.
- `0x0061AA00` allocates the clone's progression object through `0x00674EE0`.
- `0x00674EE0` initializes progression offsets:
  - `0x70` current HP from global `0x00784CF8`.
  - `0x74` max HP from the same global.
  - `0x7C` current MP from global `0x007DE9B8`.
  - `0x80` max MP from the same global.
- The staged binary constants are:
  - `0x00784CF8`: `50.0f` native wizard HP default.
  - `0x007DE9B8`: `100.0f` native wizard MP default.

## Verified Native Recompute Path

`0x0061AA00` marks the selected element progression entry active, then calls
`0x0065F9A0`. That recompute path snapshots current/max HP and current/max MP,
runs the native stat recompute vtable calls, then restores current values by
ratio:

- HP: `new_max_hp * (old_hp / old_max_hp)`
- MP: `new_max_mp * (old_mp / old_max_mp)`

Because `0x00674EE0` initializes current and max together before this call, the
clone enters recompute with full HP and full MP. The loader should preserve that
native result instead of overwriting it.

## Evidence Artifacts

- `runtime/ghidra_ally_hp_progression_paths.txt`
- `runtime/ghidra_ally_hp_recompute_candidate.txt`
- `runtime/ghidra_synthetic_source_profile_paths.txt`
- `runtime/live_ally_hp_hardcoded_baseline_probe.json`
- `runtime/live_ally_hp_native_defaults_probe.json`
- `tests/re/run_static_re_tests.py`
- `tests/re/run_live_ally_hp_native_defaults_probe.py`

The live probe has two modes:

- `--allow-hardcoded-baseline` records the pre-cleanup behavior where the clone
  materializes through the standalone rail but HP/max HP are forced to `25.0f`.
- default strict mode fails unless the shared-hub standalone clone materializes
  with native `50.0f` HP/max HP and native `100.0f` MP/max MP.

Post-cleanup validation:

- The pre-change baseline recorded `gameplay_slot=-1`, HP/max HP `25.0f`, and
  MP/max MP `100.0f`.
- The strict post-change probe recorded `gameplay_slot=-1`, HP/max HP `50.0f`,
  and MP/max MP `100.0f`.
