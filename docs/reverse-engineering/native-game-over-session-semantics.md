# Native Game Over session semantics

## Scope and evidence

This note separates the stock terminal Game Over transition from the
multiplayer death/spectator presentation. It intentionally does not redefine
the corpse timer, death animation, dropped staff, or red death effect covered
by [native-player-death-spectator.md](native-player-death-spectator.md).

The static findings below come from the analyzed retail executable:

- file: `SolomonDarkAbandonware/SolomonDark.exe`
- SHA-256:
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`
- Ghidra project: `Decompiled Game/ghidra_project/SolomonDark.gpr`
- headless workflow: `scripts/Invoke-GhidraHeadless.ps1` with a read-only
  replica and `tools/ghidra-scripts/decompile_targets.py`

The live baseline used the isolated `go-base-solo-a1` loader instance with one
participant and zero transport peers. A stock magic-hit dispatch reduced the
local player from positive life to negative life and reached the native corpse
drive state. The run-ended detour suppressed Game Over and, after the
presentation delay, displayed `Spectating - waiting for an alive player`.
`sd.ui.get_snapshot()` reported no native UI surface. This proves that an
initialized multiplayer transport is not evidence of a multiplayer session.

## Retail terminal call graph

The PlayerWizard terminal path eventually invokes the active arena's terminal
virtual. For the retail arena, that virtual is `FUN_004633D0`:

```text
PlayerWizard terminal dispatch
  -> Arena virtual +0xD8
     -> FUN_004633D0
        -> FUN_0068B6D0(6)
        -> FUN_0068B6D0(4)
        -> Game_OnGameOver (0x005CB570)
```

The two audio actions happen before `Game_OnGameOver`. The loader's existing
run-ended hook is installed at `0x005CB570`, so returning from that detour
preserves the native death/audio work while suppressing only the terminal
screen. Calling its trampoline later is the exact way to resume the retail
terminal transition; reimplementing the arena virtual or its audio work would
duplicate stock behavior.

`Game_OnGameOver` allocates `0xB0` bytes, constructs the object through
`FUN_005CAD40`, and installs it through the current application's surface
virtual at `+0xA8`. The constructed object uses vtable `0x0079B0CC` and builds
the stock `GameOver` presentation. Its renderer at `0x005C9030` draws the two
active Game Over atlas records, text, and the fullscreen fade layers.

## The Game Over object owns the post-death flow

The Game Over tick at `0x005CF4F0` owns input arming, timeout behavior, fade
progress, and completion. Once its close conditions are satisfied, it invokes
its native close virtual at `+0x18` and follows the stock global-state branch.
The normal retail branch:

1. performs the native Game Over cleanup, including `FUN_005C9670`;
2. creates native scene type `0xFA2` (`Mortuary`) through `FUN_005B7080`;
3. configures that native scene from the completed run globals;
4. switches the region through `FUN_005CDDD0`;
5. leaves subsequent Hall of Fame and main-menu progression to native UI.

Existing isolated retail validation observed the corresponding user-visible
sequence: arena, full Game Over, input, Hall of Fame, then the stock main menu.
The Game Over atlas becomes resident while the arena presentation remains
resident underneath it, which is part of the full stock screen rather than a
replacement scene assembled by the loader.

Therefore, “proceed normally” has one foundational implementation:
dispatch the original `Game_OnGameOver` trampoline exactly once on each local
process and allow the native Game Over object to own every step afterward.
Loader code must not manually create Mortuary, skip the fade, synthesize Hall
of Fame, or issue a competing leave-game transition.

## Session boundary

Spectator eligibility is a property of the active run membership, not of
transport initialization:

- A run with only one connected, ready participant on its run nonce is solo.
  Its lethal terminal callback must not activate any spectator state or
  spectator UI. The run-ended detour must immediately continue through the
  original trampoline.
- A run with at least two connected, ready participants on the same run nonce
  is multiplayer. A local death may suppress the Game Over trampoline and
  enter the multiplayer death/spectator presentation while another participant
  remains alive.

This cardinality test must include the local participant and use the active run
nonce. Session capacity, a configured UDP endpoint, Steam initialization, or a
stale participant from another run cannot make a solo run multiplayer.

## All-dead terminal transition

No participant process should independently infer and dispatch Game Over from
an incomplete disposable snapshot. The session authority must publish one
monotonic terminal command for the active run after all eligible participants
have valid life state and none remains alive. The command must carry the run
nonce, be accepted only from the configured authority, and be repeated over
the protocol's reliable checkpoint lane until peers acknowledge or retire the
run.

Every participant then consumes that command once on its game/application
thread and invokes the same original `Game_OnGameOver` trampoline. This gives
the host and every client an independently owned full native Game Over object
while keeping the decision host-authoritative. Dispatch also retires local
spectator camera/HUD state before the native surface is installed.

The terminal command is distinct from wave respawn and ordinary host run-exit:

- wave respawn is invalid once the session has terminalized;
- a normal host run-exit cannot substitute for local native Game Over because
  it does not construct the participant's Game Over surface;
- host run-exit following must not race ahead of an accepted all-dead command
  and navigate a client away from its native Game Over flow.

## Regression obligations

Static and live gates must prove both sides of the boundary:

- solo: exactly one active-run participant, a real native lethal dispatch,
  spectator state never active, full `game_over` surface visible, then native
  Hall of Fame/main-menu progression;
- multiplayer trio: the first two native deaths remain in the spectator
  system with a living target and no Game Over surface; the last death produces
  one authority terminal command and a full native Game Over surface on all
  three processes, followed by native post-game progression;
- protocol: terminal commands are authority-validated, run-nonce scoped,
  replay-safe, and present in the reliable state path;
- lifecycle: native Game Over dispatch occurs exactly once per participant and
  suppresses competing host-run-exit follow for that terminalized run.
