# Native player death and multiplayer spectator boundary

This note records the additional native investigation completed before changing
the multiplayer death path. It covers the retail PlayerWizard terminal
dispatcher, the Arena game-over handoff, death presentation replication, the
staff/wand bouncer, and the fullscreen death effect.

The analysis used the read-only Ghidra replica workflow against the 4,723,200
byte retail `SolomonDark.exe` with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Headless decompilation and instruction listings were cross-checked against live
Lua traces on loader commit `1561407`.

## Verdict

Four native and loader-owned lifecycles currently overlap:

1. Retail lethal damage arms the actor's terminal dispatcher. The dispatcher
   invokes the PlayerWizard virtual at slot `+0x50` exactly when its countdown
   expires.
2. That virtual performs the one-shot corpse transition, including exactly one
   staff or wand bouncer allocation, and calls the Arena's game-over virtual for
   the local player.
3. The PlayerWizard tick then advances an unbounded death timer. Arena rendering
   derives the fullscreen red blend from that timer, and the stock
   portrait/save path runs at timer tick 300.
4. Multiplayer changes its own phase to `Spectating` after 3,000 ms, but it
   neither retires nor bounds the native timer. Remote participants receive the
   `+0x160` death drive byte without the owner's advancing `+0x1BC` clock and
   then stop running presentation reconciliation as soon as replicated HP is
   zero.

The host failure is therefore an authority-lifecycle problem, not a camera
problem. The local death virtual naturally hands the Arena to Game Over, which
replaces the surface that owns world simulation. Suppressing that surface swap
is necessary for every participant, and it is critical when the dying local
actor is the host. The surviving Arena also needs a bounded corpse clock so it
never enters the stock tick-300 end-of-life path.

The staff bouncer cannot create copies of itself. Every extra staff is evidence
that the PlayerWizard death virtual ran again for the same logical death. The
loader's existing guard is tied to a materialized actor binding and is reset on
actor replacement/unregistration; it is not a participant death-epoch guard.

## Native call graph

The terminal path is:

```text
lethal PlayerWizard damage
  FUN_0052F540
    actor +0x94 = 1                    terminal pending
    actor +0x98 = terminal countdown
      |
      v
common actor tick
  FUN_00624AC0
    actor +0x134 += 1
    if +0x94:
      +0x98 -= 1
      when +0x98 <= 0:
        tail-jump [vtable +0x50]
      |
      v
PlayerWizard::vftable 0x00793F74 +0x50
  FUN_00534120                       one-shot death transition
      |
      +-- local actor --> [Arena vtable +0xD8]
      |                   FUN_004633D0
      |                     audio 6
      |                     audio 4
      |                     Game_OnGameOver 0x005CB570
      |
      `-- remote actor --> participant-manager removal virtual
```

The tail jump is visible directly in the retail instructions:

```text
00624B0A  cmp byte ptr [esi + 94h], 0
00624B19  dec dword ptr [esi + 98h]
00624B28  mov eax, [esi]
00624B2A  mov edx, [eax + 50h]
00624B30  jmp edx
```

`FUN_00533520`, the PlayerWizard tick, calls `FUN_00624AC0` at
`0x00533809`. A live trace of `FUN_00534120` returned to `0x0053380E`,
confirming this exact dispatcher path. The similarly named function at
`0x00546650` is vtable slot `+0x68` and handles Magic Shield breakage; it is not
a player-death routine.

## Local death transition

`FUN_00534120` performs these observable operations:

- preserves the actor position and performs stock death audio/flag cleanup;
- calls `FUN_005BED10` only for the process-local actor to capture stock
  portrait/background presentation;
- writes `actor +0x160 = 1`;
- clears active actor resource/attachment bookkeeping;
- resolves the held attachment through `FUN_00570D80`;
- creates a staff or wand bouncer when the held type matches;
- invokes the Arena game-over virtual for the local actor, or the participant
  removal virtual for a non-local actor;
- writes `actor +0x160 = 1` again and clears terminal flag `actor +0x94`.

The terminal flag is cleared at the end, so a later damage path can arm another
terminal countdown unless multiplayer retains a logical-death latch outside the
ephemeral actor.

## Host authority and the Game Over surface

Arena vtable `0x00785934` uses slot `+0xD8` for `FUN_004633D0` at
`0x004633D0`.
That function performs two audio actions and calls `Game_OnGameOver` at
`0x005CB570`. `Game_OnGameOver` allocates and installs the Game Over surface,
replacing the Arena that owns run simulation, wave updates, world publication,
and participant authority.

For a client, that replacement visibly ends only the client's run. For the
host, the same replacement also removes the process that publishes shared
world/wave authority, making the match appear stopped to every peer.

The loader detours `Game_OnGameOver` and returns after
`BeginLocalDeathSpectatorPresentation` accepts a connected multiplayer death.
That is the correct native boundary: retail death audio, corpse setup, and the
staff drop have already happened, while the destructive surface replacement
has not.

The offline path does not enter multiplayer spectator state and continues
through the original Game Over call unchanged.

Keeping the Arena alone is not sufficient. `FUN_00533520` continues incrementing
`actor +0x1BC` while `actor +0x160` is nonzero. At exactly tick 300 it calls
`FUN_005BC400`, the stock portrait/save end-of-life path. That routine
temporarily clears `+0x160`, performs stock persistence/presentation work, and
restores `+0x160 = 1`. A spectator implementation must bound the native death
timer before this threshold while retaining the dead-state guard.

An isolated host-death trace on the pre-fix loader confirmed that the current
Game Over detour keeps the process alive and the PlayerWizard tick continues
past 300. That does not substitute for the missing authority acceptance gate:
host world/wave generations must be observed advancing by clients while the
host spectates.

## Death presentation and replication

The relevant PlayerWizard fields are:

| Offset | Native role |
|---:|---|
| `+0x94` | terminal-dispatch pending byte |
| `+0x98` | terminal-dispatch countdown |
| `+0x134` | common actor tick counter |
| `+0x160` | nonzero death/alternate-animation drive selector |
| `+0x1BC` | death presentation timer while `+0x160 != 0` |

At death timer tick 159, `FUN_00533520` updates corpse render state and creates
the stock additive burst. At tick 200 it evaluates a local-player perk path. At
tick 300 it invokes `FUN_005BC400` for the local player.

Multiplayer captures `+0x160` as `anim_drive_state` and sends it in participant
presentation state. On an observer, `ApplyNativeRemoteParticipantVitalState`
first writes replicated HP. `HookPlayerActorTick` then classifies HP-zero actors
as dead and returns through its dead branch. Normal
`ApplyNativeRemoteParticipantPlayback` and
`ApplyNativeRemoteParticipantPresentationState` no longer run on that actor.

Receive ordering can write the replicated `+0x160 = 1` just before HP-zero
classification, but the observer does not advance the matching native death
clock. In isolated live traces:

| Perspective | `+0x160` | `+0x1BC` | `FUN_00534120` hits |
|---|---:|---:|---:|
| dying owner after grace | `1` | advancing (`197` and higher) | `1` |
| observer after grace | `1` | frozen at `0` | `0` for host death |
| authoritative host clone of dying client | `1` | frozen at `0` | `1` |

This is a real presentation-state-machine split: peers agree that the actor is
dead but do not agree on the native presentation phase. The fix must establish
one participant death epoch, apply the death drive on every materialized view,
and derive a bounded presentation clock from that epoch. It must not call the
complete local death virtual merely to animate a remote actor, because that
virtual also performs actor removal and local/remote ownership side effects.

## Staff and wand drop lifecycle

The only PlayerWizard staff-bouncer allocation site is in `FUN_00534120`:

```text
held type 0x1B5C (Staff)
  0x0053424D  allocate 0x50 bytes
  0x0053426B  FUN_00453060             Anim_Bouncer base ctor
  0x00534270  vtable = 0x00793C4C      Anim_StaffBouncer
  0x00534286  FUN_004608D0             resolve staff visual
  initialize position/velocity/life
  0x0053436B  insert in owner world list at +0x2C4
  call bouncer virtual +0x1C

held type 0x1B63 (Wand)
  0x00534387  allocate 0x50 bytes
  same shape with Anim_WandBouncer and FUN_00460920
```

`0x00534270`, the seven-byte staff-vtable assignment, is therefore an exact
live-safe trace point for a completed staff construction. It is inside the
staff-only branch, after allocation and the base constructor, and cannot be
reached by the tick-159 additive burst or the wand branch. The earlier
`0x0053424D` allocation instruction is followed by a relative call and is not
safe for the runtime trace trampoline.

The staff bouncer's recovered methods show no spawn recursion:

- `FUN_00456720` advances position, velocity, bounce state, rotation, and the
  finite lifetime at `+0x30`, then retires the object;
- `FUN_0045BE20` renders the expected shadow and staff layers for that one
  object;
- `FUN_00453160` reports completion when vertical motion reaches zero.

References to `Anim_StaffBouncer::vftable` identify only
`FUN_00534120` as a constructor site. Repeated visible drops therefore require
repeated terminal dispatch into `FUN_00534120`.

The loader currently attempts to limit remote death with
`death_transition_stock_tick_seen`, but resets that flag when:

- the binding returns to an HP-positive state;
- its actor address changes;
- its actor address becomes zero;
- materialization state is reset after world unregistration.

If an authoritative remote clone has already been terminalized by native
damage, its one allowed stock tick can enter `FUN_00534120`. The non-local death
branch may unregister it; rematerialization then clears the latch while the
participant is still authoritatively dead and still advertises a staff
attachment. That is the complete structural retrigger loop for repeated staff
bouncers. The guard must belong to the participant's alive-to-dead epoch, not
the current actor allocation, and dead remote equipment reconciliation must not
reattach an attachment that has already been consumed by that epoch.

Controlled loopback traces without scene churn produced one transition on the
dying owner and, for client death, one transition on the authoritative host
clone. This confirms the one-shot native behavior while leaving
rematerialization as the condition that exposes the faulty binding-scoped
guard. Acceptance must count transition/drop execution across the whole death
epoch, including a forced reconciliation/rematerialization opportunity.

## Fullscreen red effect lifecycle

Arena render function `FUN_0046EC80` reads the local PlayerWizard:

```text
if actor +0x160 != 0 and actor +0x1BC > 150:
    alpha = (death_ticks - 150) / DAT_007DE850
    alpha = min(alpha, 1.0)
    draw fullscreen death blend
```

There is no upper timer bound and no branch that clears the blend. Retail flow
normally replaces the Arena with Game Over, so the saturated blend disappears
with the surface. Multiplayer deliberately preserves the Arena, exposing the
otherwise hidden unbounded lifecycle.

`TickLocalDeathSpectator` currently changes only its loader phase after 3,000
ms. A pre-fix live host trace showed `+0x160 = 1` and `+0x1BC` continuing from
197 through 656 while phase was already `Spectating`. The red blend therefore
remains saturated indefinitely.

Clearing `+0x160` at grace expiry would hide the blend but also remove the native
dead-state guard, allowing later hits to arm another terminal transition and
spawn another staff. The safe boundary is to keep the dead selector asserted
while resetting and holding `+0x1BC` below the render threshold after grace
expiry. Respawn is the operation that clears the selector and returns the actor
to its alive presentation.

## Dead-player level-up presentation

Follow-up headless decompilation mapped why a participant can level while dead
without receiving a usable picker. Multiplayer authority is already
participant-specific: the host advances the dead participant's materialized
progression and rolls against that progression's own skill book. In the
pre-fix loopback trace, the client and the host-owned client progression both
advanced from level 1 to level 2 at 135 XP.

`FUN_0065F480` still creates the normal level-up screen for that progression:

- it merges the incoming pick count at `progression +0x48` into the pending
  count at `+0x44`;
- it allocates the `0x628`-byte screen through `FUN_00658620`;
- it stores the screen at `progression +0x83C`;
- it installs the screen in the normal UI owner.

The stall is in the screen's native tick, not its creation or multiplayer
authority. The level-up screen vtable begins at `0x0079FD4C`; slot `+0x08`
resolves to `FUN_0066F920`. Its entry gate is:

```text
if gameplay local-player pointer is null:
    run base screen tick
else if local PlayerWizard +0x160 == 0:
    advance reveal timers, roll options, build children, and process selection
else:
    skip the complete level-up screen state machine
```

The authoritative picker object observed while spectating therefore had a
valid screen and `desired_count=3`, but its option array remained
`values=0/count=0`. The multiplayer option-roll hook could not run because the
native tick never reached the progression vtable call at `+0x74`.

The screen also owns a ten-tick reveal countdown at `screen +0x78`. Its full
tick body only decrements that countdown when this screen is the top entry in
the native UI stack rooted at `DAT_0081F674`; when the countdown reaches zero,
the same call rolls the options and builds their native children. A second
isolated dead-player trace observed the countdown move from 10 to 8 and then
stall: manually entering the virtual from the loader's gameplay reconciliation
advanced it only while incidental main-thread work ran. A dead actor no longer
provides the continuous `PlayerActor::Tick` pump that living-player acceptance
had relied upon. This means manually calling or fast-forwarding the virtual is
not a usable presentation path: later reveal and input frames would still
stall.

The correct bridge is therefore an exact detour of this UI virtual. While a
connected dead participant has an unresolved local offer and this exact screen
is ticking, the detour clears actor `+0x160`, calls the stock virtual at its
normal UI-frame cadence, and restores the exact selector before returning.
The spectator lifecycle remains dead for damage, rendering, and replication;
only the stock picker virtual sees the alive selector it requires. Spectator
target cycling must also yield ownership of left/right input until the picker
closes, including its release debounce, so a skill click cannot be consumed as
a camera-target click.

## Wave completion respawn and stale death authority

There is no retail round-respawn constructor in this multiplayer path. The
loader derives one command from the host's validated `WavePhase::Completed`
summary and applies it once per authenticated `wave_respawn_epoch`. Every
process calls `TryRespawnLocalPlayerAt` on its existing local PlayerWizard and
existing progression. The operation changes only current HP/MP, position,
cast/input state, and the native terminal/death fields `+0x94`, `+0x98`,
`+0x160`, and `+0x1BC`; it does not construct or replace the actor,
progression, inventory, skill book, stat book, or equipment.

The pre-fix immediate-transition trace exposed an authority ordering race:

```text
client death presentation begins
  |
  +-- host completes wave and publishes respawn epoch 1
  |
  +-- client applies epoch 1 to the same actor
  |     HP/MP restored; +0x94/+0x98/+0x160/+0x1BC cleared
  |     spectator phase retired
  |
  `-- an older host ParticipantVitalsCorrection(HP=0) arrives
        TryApplyAuthoritativeLocalPlayerDeath replays stock lethal damage
        FUN_00534120 runs a second time
        a second staff bouncer is allocated
        death presentation and red effect restart
```

The isolated trace completed the wave 0.694 seconds after lethal damage. The
client recorded `last_applied_respawn_epoch=1`, then crossed from 50 HP back to
zero, and both `FUN_00534120` and the exact staff allocation trace reached two
hits. Resetting the presentation fields again would only hide this second
authoritative death.

The respawn command must instead be an authority barrier. On wave completion,
the host retires pending pre-respawn vitals corrections before publishing the
command. The client records the host packet sequence that carried the accepted
respawn and rejects any correction packet from that authority whose transport
sequence is not newer. Packet header sequences are shared across packet kinds,
so a genuine post-respawn hit remains newer and legal while an in-flight
pre-respawn death correction cannot cross the boundary.

## Loadout identity across respawn

The same-actor boundary is also the preservation mechanism. `FUN_00534120`
consumes the held attachment for its one visual bouncer, but it does not remove
the staff recipe from the progression-owned inventory or replace the
progression. `TryRespawnLocalPlayerAt` does not grant, clone, equip, or rebuild
items and does not mutate skill/stat rows. A respawn restore table would be
incorrect: it could duplicate the retained staff or overwrite a skill acquired
while dead.

Acceptance must compare stable identities and contents on the owning actor:

- actor and progression addresses remain identical;
- every inventory row and equipped slot, including the staff recipe, is
  identical;
- skill/stat books are identical except for the selected dead-time level-up
  row and its native derived-stat consequences;
- the staff inventory count is unchanged while the death-epoch allocation
  trace remains exactly one;
- level, XP, and the chosen skill survive the same-actor respawn.

## Stock Boneyard spawn publication and run-start placement

Follow-up headless decompilation mapped the authoritative run-start placement
path before changing respawn coordinates. The Boneyard `RegionLayout` player
spawn tuple is not inferred from the first actor position. `FUN_0046DC60`
publishes the loaded tuple into the live Arena:

| Arena offset | Native role |
|---:|---|
| `+0x88F4` | loaded `RegionLayout` player-spawn X |
| `+0x88F8` | loaded `RegionLayout` player-spawn Y |
| `+0x88FC` | loaded player-spawn facing |
| `+0x8ED0/+0x8ED4` | effective player-spawn slot 0 position |
| `+0x8EF0` | effective player-spawn slot 0 facing |

At the end of the load, `FUN_0046DC60` copies the loaded tuple to all four
effective position slots at `+0x8ED0`, `+0x8ED8`, `+0x8EE0`, and `+0x8EE8`
and copies the facing to `+0x8EF0` through `+0x8EFC`. The generated-arena
startup path in `Game_OnStartGame` (`FUN_004BED40`) can first synthesize the
loaded tuple from the arena bounds, but the same Arena fields remain the
published authority after loading.

`FUN_00462410` is the exact run-start actor placement consumer:

```text
Arena +0x8ED0/+0x8ED4
  |
  +-- copy to actor +0x18/+0x1C
  +-- copy Arena +0x8EF0 to actor +0x6C
  |
  `-- if multiplayer slots overlap:
        apply the stock per-slot collision-separation offset

">>>> Place %d at %.0f,%.0f"
```

The Boneyard spawn authority to reuse for a respawn command is therefore the
live Arena's effective slot-0 tuple, not a sampled PlayerWizard coordinate.
The command intentionally carries that exact tuple: respawn acceptance asks
for the Boneyard player spawn itself, while `FUN_00462410`'s later overlap
offset is a run-start separation policy rather than part of the serialized
spawn point.

The pre-fix loader instead captured the host actor's current X/Y once and
called it a run spawn anchor. An isolated two-process run demonstrated the
error directly: a client that died at `(750,150)` respawned at the host's
sampled `(707.675,150)`. Neither value was read from the Arena spawn tuple.

## Corpse registration and participant-scoped retirement

The persistent corpse is the dead PlayerWizard itself, not an independently
owned corpse entity. `FUN_00533520` changes two base-actor fields at death
timer tick 159:

```text
actor +0x36 = 0
actor +0xA0 = DAT_007DE974 = -1000.0f
```

The base actor constructor `FUN_006287D0` initializes the packed flags at
`+0x34` to `0x01010000`, which makes the grid-member byte at `+0x36` equal to
one, and initializes the render/sort field at `+0xA0` to zero. Tick 159
therefore deliberately changes a live actor into its corpse presentation:
the actor retains its grid-cell pointer at `+0x54`, but subsequent world-grid
rebinding is disabled and its render/sort bias becomes `-1000.0f`.

`WorldCellGrid_RebindActor` (`FUN_005217B0`) begins with:

```text
if actor +0x36 == 0:
    return
```

When the flag is enabled, it computes the cell from actor `+0x18/+0x1C`,
removes the actor from the old `+0x54` cell when the cell changed, inserts it
into the new cell, and updates `+0x54`. The existing respawn path wrote a new
position and called this function while `+0x36` was still zero. The call
returned successfully but did no work, leaving the old death-location cell
with the corpse registration and leaving the spawn cell without the actor.

The objects created later in the tick-159 block are
`Anim_FadeMoveAdditive_Perspective` bursts, not corpse owners.
`FUN_00452F20` decreases each burst's finite alpha/lifetime and invokes its
retirement virtual when the value reaches zero. Deleting or sweeping that
world lane would therefore target the wrong lifecycle and could disturb
unrelated player effects.

The foundational respawn transition is the inverse of the native tick-159
corpse transition on the same participant actor:

1. write the Arena-authored respawn position and clear terminal/death state;
2. restore `actor +0xA0` to the constructor value `0.0f`;
3. restore `actor +0x36` to the constructor value `1`;
4. call `WorldCellGrid_RebindActor` so it removes only that actor from its old
   cell and inserts it at the spawn cell.

The same reset is required when a remote participant changes from its death
epoch back to alive, before normal remote playback performs its grid rebind.
It is keyed to that participant's alive transition and actor address; it does
not enumerate world cells, delete other dead actors, or modify the staff
bouncer trace lane.

An isolated pre-fix live probe after grace expiry corroborated the recovered
fields on the owning actor: `+0x36` was zero, `+0x54` remained non-null, and
`+0xA0` contained `0xC47A0000` (`-1000.0f`). The loader had already bounded
`+0x1BC` for the red-effect fix, showing that corpse registration is a
separate native lifecycle that must be reversed explicitly on respawn.

## Required implementation and acceptance boundaries

The native findings impose these constraints:

- Game Over suppression applies identically to host and clients.
- The exact native Game Over hook admits a connected death from the asserted
  `+0x160` selector, not from a volatile HP sample that authoritative replay or
  stock regeneration can change before the terminal countdown completes.
- Host transport/world/wave authority must continue independently of the dead
  actor's normal gameplay actions.
- A participant death epoch survives actor replacement and owns exactly one
  native terminal/drop transition.
- Host-authoritative damage on a native remote clone clears that clone's
  `+0x94/+0x98` terminal dispatch immediately after stock damage capture; only
  the owning process may execute the side-effectful death virtual and create
  the staff bouncer.
- Owner and observers use the same death-presentation epoch and agree on
  `+0x160`, the owner-authored bounded `+0x1BC` clock, and whether the grace
  presentation is active. Protocol 84 carries that clock explicitly rather
  than starting a peer-local timer when the death packet arrives.
- After 3,000 ms, `+0x1BC` is held below the Arena red-effect threshold and can
  never reach the stock tick-300 end-of-life path.
- Dead remote presentation is reconciled explicitly; it is not obtained by
  invoking the side-effectful complete PlayerWizard death virtual.
- Respawn clears the death epoch, native death selector/timer, terminal pending
  state, and the consumed-attachment guard.
- A dead participant's native level-up screen advances through its stock
  build/input virtual without weakening the actor's death guard outside that
  call, and spectator input does not consume picker input.
- A wave-respawn packet is a sequencing barrier for older authoritative death
  corrections; the same epoch cannot respawn or terminalize an owner twice.
- The host reads the effective Boneyard slot-0 spawn from the live Arena and
  carries that exact state-derived coordinate in every wave-respawn command.
- Local and remote alive transitions restore the tick-159 grid-member and
  render/sort fields before rebinding the participant actor, removing only
  that participant's death-location corpse registration.
- Respawn preserves the existing actor-owned progression, inventory, stat
  book, skill book, and equipment rather than reconstructing them.

The live gate must kill the host as well as a client, observe world/wave
sequences advancing on every peer while the host spectates, respawn the host,
assert owner/observer death presentation agreement, trace exactly one
`FUN_00534120` execution per owning death, and prove the fullscreen blend
predicate is false after grace expiry.
`tools/verify_multiplayer_death_spectator_respawn.py` is the isolated
three-owner loopback acceptance entry point.
