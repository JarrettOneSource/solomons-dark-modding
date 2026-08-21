# Binary-layout gameplay globals section ownership (2026-08-21)

## Result

Current main placed `[gameplay.pause]` after only the first eleven
`[gameplay.globals]` keys. INI section ownership therefore assigned every
subsequent global, beginning with `cursor_secondary_at_mouse`, to
`gameplay.pause`. A current Release launch stopped with:

```text
Binary layout is missing [gameplay.globals].cursor_secondary_at_mouse.
```

The failure was configuration ownership, not a missing address or stale
binary. Moving the complete pause section before `[gameplay.globals]` restores
one contiguous globals section without changing any key or value.

## Evidence

- Source/current-main commit: `9ba0feb1453eaf4d98437c118f48c13dc4f4982c`.
- The unmodified Release build completed, then the staged loader rejected the
  first misplaced key during startup.
- The section correction allowed an owned retail process to launch and record
  the derived-stat HUD evidence described in
  [`native-hud.md`](../reverse-engineering/native-hud.md).
- That process used the pinned retail SHA-256
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`
  and ended with a path-matched owned-process cleanup receipt.

## Regression contract

`tests/test_native_derived_hud_contract.py` parses actual section ownership,
not token presence. It requires menu/belt keys, `cursor_secondary_at_mouse`,
`game_object`, Arena/damage globals, and `gameplay_index_state_table` to belong
to `gameplay.globals` while `game_tick` remains in `gameplay.pause`. Moving a
header into the middle of either family now fails the ordinary Python suite.
