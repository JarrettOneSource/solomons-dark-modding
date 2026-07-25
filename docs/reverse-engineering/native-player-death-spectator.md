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
4. The original multiplayer path changed its own phase to `Spectating` after
   its grace interval, but it neither retired nor bounded the native timer.
   Remote participants received the `+0x160` death drive byte without the
   owner's advancing `+0x1BC` clock and then stopped running presentation
   reconciliation as soon as replicated HP was zero.

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
    actor +0x98 remains 1              constructor-owned countdown
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

The original `TickLocalDeathSpectator` changed only its loader phase when its
grace interval elapsed. A pre-fix live host trace showed `+0x160 = 1` and
`+0x1BC` continuing from 197 through 656 while phase was already `Spectating`.
The red blend therefore remained saturated indefinitely.

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

## Organic enemy damage and the native lethal threshold

A follow-up investigation on published beta.15 (`cdcd53b`) traced real wave
enemy damage because the earlier acceptance gate called a synthetic
1,000-damage magic probe directly on the victim. That probe crossed every
native threshold in one call and did not exercise host-authoritative damage on
a client-owned actor.

The retail organic path is:

```text
melee / projectile enemy hit
  damage-context builder
    |
    v
FUN_0063E7D0                       generic actor damage dispatcher
  [PlayerWizard vtable +0x4C]
    |
    v
FUN_00548150                       PlayerActor incoming damage
  resistance and damage-lane calculation
    |
    v
FUN_0052F540
  FUN_0052AC80(actor, -damage)
    actor +0x200 -> per-actor progression runtime
    progression +0x70 += delta
    clamp only to progression +0x74 maximum
    return terminal when HP <= DAT_00786824
```

`FUN_00627160`, the native poison-modifier tick, resets and fills the same
damage context, sets the poison/source flags, and enters `FUN_0063E7D0`.
Melee, projectile, and poison therefore converge on the same PlayerActor
terminal decision even though their context builders differ.

Headless data recovery establishes that `DAT_00786824` is
`0xC1200000`, or `-10.0f`. Retail does not arm death when the displayed life
first reaches zero. It permits negative per-actor HP and sets `actor +0x94`
only after a hit reaches `-10.0f` or lower. `FUN_006287D0` initializes
`actor +0x98` to one; `FUN_0052F540` does not replace it. The next common
actor tick decrements that constructor-owned countdown and invokes the
PlayerWizard death virtual.

This threshold explains a visible interval that a one-shot synthetic hit
cannot expose:

```text
ordinary enemy hits
  HP crosses 0
  more hits accumulate native overkill
  HP reaches -10
  +0x94 is armed
  next common tick invokes FUN_00534120
```

## Client-owned damage authority mismatch

Connected clients reject unsolicited local native damage. A stock enemy hits
the client's materialized PlayerWizard clone in the host process; the host
reads that clone's per-actor progression HP and sends a
`ParticipantVitalsCorrection` to the owner. The packet intentionally permits
only `0..max_hp`. A correction of exactly zero is the protocol's terminal
signal: the client calls `TryApplyAuthoritativeLocalPlayerDeath`, which primes
positive presentation life and re-enters the stock damage path with one lethal
hit so that the owner alone performs `FUN_00534120` and the staff drop.

The beta.15 observation predicate breaks that intended conversion in two
ways:

```text
native_damage_observed =
  native_max_matches_last_write &&
  !replicated_life_increased_since_last_write &&
  native_hp >= 0 &&
  native_hp + 0.05 < min(replicated_hp, last_written_hp)
```

- normal owner regeneration can make replicated life greater than the last
  host write, suppressing later legitimate enemy hits;
- when an enemy finally drives the host clone below zero, `native_hp >= 0`
  rejects the crossing instead of converting it to the protocol's zero-life
  terminal correction.

Normal vital reconciliation then writes the owner's nonnegative replicated HP
back to the clone. Small melee, projectile, or poison hits can repeatedly
approach zero but cannot retain negative overkill or send the zero correction.
The owner never enters death detection, presentation, staff drop, grace, or
spectator handoff.

The regeneration veto is unnecessary for distinguishing owner healing from
host-native damage. The comparison already uses
`min(replicated_hp, last_written_hp)` as its reference: an owner-only increase
leaves native HP at the last host write and cannot satisfy the damage delta,
while a simultaneous native hit still can.

## HP-zero is not a remote presentation epoch

`ApplyNativeRemoteParticipantDeathPresentationState` has a separate
beta.15 ordering error. It starts a remote death epoch from replicated
`life_current <= 0` and immediately writes `actor +0x160 = 1`, a zero
presentation clock, and a detached held attachment. It evaluates the owner's
replicated death-presentation flag only afterward.

For a host-owned actor taking small stock hits, participant HP reaches its
network-normalized zero while the owner is still accumulating native damage
from zero to `-10`. The client observer therefore renders a corpse before
`FUN_00534120` has run on the owner. Presentation must instead begin only from
the owner-authored death-presentation flag. Once that flag has started the
death epoch, replicated zero life may keep the bounded corpse state after the
configured grace flag clears; zero life alone must not start it.

## Beta.15 organic reproduction matrix

All runs used isolated loopback UDP groups, stock wave actors, their native
control brains, and exact-PID cleanup. No run called the native magic-hit
probe.

| Victim | Enemy path | Activity | Beta.15 result |
|---|---|---|---|
| host | Skeleton melee | idle | owner presentation at 2.348 s; observer corpse at 1.140 s |
| host | fire projectile | casting | owner presentation at 5.313 s; observer corpse at 4.021 s |
| host | poison cast | idle | owner presentation at 6.591 s; observer corpse at 5.457 s |
| client | Skeleton melee | idle | no death in 18 s; minimum owner HP 0.0030; one correction |
| client | fire projectile | idle | no death in 18 s; minimum owner HP 0.0060; one correction |
| client | poison cast | casting | no death in 18 s; minimum owner HP 0.0010; 15 corrections |

Casting was confirmed through the real mouse-input queue and native dispatcher
log before the poison attack. It did not change the divergence: host paths
split between network zero and native `-10`, while client paths stopped before
the zero-life authority signal.

## Beta.16 presentation, input, and spectator follow-up

Published beta.16 fixed the beta.15 organic-damage authority mismatch, but live
stock-wave testing exposed four additional boundaries that the earlier
scripted lethal-hit gate did not exercise: the terminal corpse frame, dead
spell dispatch, spectator-target camera ownership, and the render pass that
owns the spectator HUD.

### Native death animation frame selection

`FUN_0054BA80`, the PlayerWizard animation/render advance selected by
`actor_animation_advance`, sends an actor with `+0x160 == 0` through its normal
animation path. When `+0x160 != 0`, it calls `FUN_00538550`, the dedicated dead
sprite renderer.

`FUN_00538550` derives its four-frame death image directly from `actor +0x1BC`:

```text
frame = 0
if death_ticks > 150:
    frame = (death_ticks - 150) / 3
    frame = min(frame, 3)
```

The terminal corpse image is therefore first selected at tick 159 and remains
selected for every later tick. It is not a tick-300 animation. Tick 300 belongs
to the separate stock portrait/save path in `FUN_00533520`.

Beta.16 drives the replicated clock from 0 through 298 during its grace
interval, then writes zero when `DeathPresentation` becomes `Spectating`.
Remote reconciliation makes the same active-to-zero transition. Two organic
traces captured the exact rewind on both peers:

| Victim | Stock damage/activity | Native clock immediately before handoff | First clock after handoff |
|---|---|---:|---:|
| host | Skeleton melee, idle | 298 owner / observer | 0 owner / observer |
| client | fire projectile, held primary | 298 owner / observer | 0 owner / observer |

The death animation reaches frame 3 before handoff, but the zero write sends
the surviving corpse back to frame 0. That is one visible cut-short path.
Red-effect clearing and corpse rendering cannot share one raw timer value
after grace: Arena red is active above tick 150, while the terminal corpse
requires tick 159. The selector `+0x160` remains asserted until respawn.

The first three-owner organic follow-up exposed a second, earlier cut. The
logical five-second clock was being written directly into `actor +0x1BC`.
Headless re-decompilation of `FUN_00533520` confirms that this field is both a
sprite-frame input and the CPU lifecycle counter. The PlayerWizard tick
increments it before exact equality checks. At `0x9F` (159) it performs all of
these owner-side mutations in one block:

```text
Arena +0x8E04 = 0.25f
actor +0x36 = 0
actor +0xA0 = -1000.0f
emit the finite additive corpse bursts
```

`FUN_00538550`, by contrast, only reads `+0x1BC` to choose death sprite
`min((ticks - 150) / 3, 3)`. A render call may therefore project tick 159
without executing the tick-159 CPU transition.

The distinction appeared exactly in the isolated `orgsf-fix1` and
`orgsf-fix2` traces. The target owner advanced from tick 157 to 162, changed
its render/sort field from `0.0` to `-1000.0`, and returned an all-black
1600x900 D3D9 backbuffer five consecutive times while its runtime phase was
still `DeathPresentation`. The dead client observing that same target kept
`+0xA0 = 0.0`, reached the replicated terminal frame, and produced a valid
corpse image at the unchanged death coordinate. Remote dead actors bypass the
owner-only `FUN_00533520` transition, explaining the peer split.

The foundational timer ownership is consequently:

1. the runtime/wire death epoch owns the full logical `0..298` clock;
2. the CPU-visible native timer is clamped at the red-safe tick 150 before
   every connected multiplayer death tick, so neither tick 159 nor tick 300
   can execute;
3. the PlayerWizard animation hook temporarily projects
   `min(logical_tick, 159)` for both active owner and replicated presentations,
   calls the stock dead-sprite renderer, and restores a value no greater than
   150;
4. after grace, rendering continues to project tick 159 while the stored timer
   stays at 150 until participant-scoped respawn clears the death selector.

The product grace contract is now 5,000 ms. The owner-authored 0..298 clock
therefore reaches the terminal corpse frame during the interval and holds it
for the remainder. At expiry, red presentation, staff-drop epoch accounting,
spectator handoff, and respawn eligibility all cross the same duration
boundary.

### Native spell dispatch is death-blind

The primary dispatcher at `FUN_00548A00` and the secondary dispatcher at
`FUN_0054CC50` do not read `PlayerWizard +0x160`. Both enter their progression,
resource, presentation, and behavior paths for a dead actor. The shared primary
presentation helper `FUN_0052DA80` is death-blind as well.

The default Ether right-click is secondary row `0x0B`, Call Leviathan.
`FUN_0054CC50` case `0x0B` allocates and registers the native `0x07F2` summon.
This proves that suppressing only spectator UI input cannot provide the
required guarantee: the stock authority path itself accepts and materializes a
world-affecting dead-player command.

The loader exposes the same missing boundary at two levels:

- `HookSpellCastDispatcher`, `HookPurePrimarySpellStart`, and
  `HookPlayerActorSecondarySpellCast` invoke the stock dispatcher without
  rejecting the process-local dead participant.
- `ApplyRemoteCastPacket` relays the packet and applies its position/heading
  before the later bot queue rejects a dead participant. Special secondary
  behavior can also run before that late rejection.

Death must therefore be rejected before the local original call, before any
outgoing queue is sent, and on the authority before relay, transform mutation,
or secondary behavior. Clearing held mouse input during the terminal
transition can synthesize a `Released` phase, so the outgoing queue needs the
same guard even when the native entry hook was not re-entered.

### Spectated death and camera ownership

`CollectAliveSpectatorTargetIds` requires both replicated and materialized HP
to be positive. `TickLocalSpectatorTarget` rebuilds that list every frame and
immediately selects another participant when the current target reaches zero.
It does not preserve a target whose owner-authored death-presentation flag is
still active.

An organic three-player trace killed an Ether target while a previously dead
client was spectating it. The target's owner and observer coordinates remained
exactly `(899.248, 150.000)` throughout the grace window and both native clocks
reached 298, but the client HUD immediately changed from `Observer Player` to
`Host Player`. The visible body jump is the camera retarget, not a corpse
transform mutation in that trace. A current target with an active replicated
death presentation remains a valid camera subject until that presentation
expires; manual cycling may still select a living target.

Cast packets nevertheless remain forbidden from mutating a dead participant's
transform. That authority rule closes the adjacent stale-packet race and makes
death-location stability independent of input timing.

### Spectator HUD render-pass leak

`DrawGameplayDeathSpectatorStatus` is screen-space and has no actor or summon
anchor. `RenderOverlayFrame`, however, runs from every observed D3D9
`EndScene` callback without proving that render target 0 is the swap-chain
backbuffer. A stock spell can introduce an offscreen world/effect pass that is
later composited into the final frame.

The three-player organic witness used the Ether preset's real belt slot 1 and
right-click Call Leviathan dispatcher. Before the summon, the spectator view
contained one crisp status box at the top of the 1600x900 backbuffer. After the
`0x07F2` summon materialized on all three peers, a second enlarged copy of the
status box appeared inside the world above the actors while the original
screen-space box remained. This is an offscreen render-target leak, not a
second spectator target or a minion-associated HUD instance.

The controls box is loader diagnostic status text, not stock spectator UI and
not an actor-owned surface. Normal player sessions run with
`loader.debug_ui=false`; `RegisterDiagnosticSurfaceFrame` returns before it
constructs the spectator text, and the normal-session log guard rejects any
successful spectator-status draw. The semantic spectator target and click
controls remain available through runtime state.

This is a stronger boundary than trying to associate the diagnostic quad with
a wizard: normal gameplay registers and draws no such diagnostic surface on the
backbuffer or on offscreen passes. Summons therefore cannot duplicate, migrate,
or appear to inherit it. The diagnostic implementation was subsequently
removed when the player-facing replacement moved to the native product-UI
path described below.

### Beta.17 missing spectator affordance and product UI boundary

Commit `a201d28` correctly placed every loader diagnostic status surface behind
`RegisterDiagnosticSurfaceFrame` and made the published `full` profile keep
`loader.debug_ui=false`. The death-spectator target/click bar was still the only
player-facing spectator affordance, however, so that change also removed the
bar from normal play. The beta.17 live log expressed the intended diagnostic
result—`enabled=0 registered=0 rendered=0`—while no independent product
spectator surface existed.

The two-owner host-death topology does not have a separate authority or camera
fault. A clean beta.17 organic melee trace held the host's death presentation
for 5.011 seconds, entered `Spectating`, selected the sole live client
participant, and set local camera focus to that participant's exact gameplay
coordinates. `SelectNextAliveSpectatorTarget` finds the current ID in the
alive-only sorted vector; with one entry, either click advances past the end and
wraps to `front()`, which is the same ID. The missing information was
presentation-only.

The player-facing replacement reuses the retail native UI seams already mapped
under `[lua_ui_authoring]`:

- `UiPanel_Render` at `0x005C3F40` draws the stock-style panel;
- `ExactText_Render` at `0x0043BCD0`, the native string assigner at
  `0x00402AE0`, and `UiRenderContext_SetColor` at `0x0041FE50` draw the target
  name and `Left / Right click: next player` instruction;
- the existing font bundle and render-context globals supply the same native
  objects used by authored UI.

This renderer owns an independent product-surface lifecycle. It registers and
draws only when the local runtime is active in `Spectating` and
`TryBuildDeathSpectatorStatusText` returns nonempty text. `Inactive` (menu,
lobby, alive, or respawned) and the five-second `DeathPresentation` phase both
emit a hidden state. A living peer never registers the surface. The old
`DrawGameplayDeathSpectatorStatus` filled-quad implementation is removed from
the diagnostic renderer rather than re-enabled. Phase, target ID, target name,
and display text are derived from one `DeathSpectatorRuntimeInfo` snapshot so a
render frame cannot straddle handoff and report a visible surface with the
preceding phase.

The render callback additionally compares D3D9 render target 0 with swap-chain
backbuffer 0 before it snapshots or registers the product surface. Offscreen
spell/minion `EndScene` passes return without drawing or changing the reported
surface state. This closes the original black-texture/migrating-overlay class
while restoring a legitimate screen-space player affordance on the real
backbuffer.

The acceptance boundary now requires both the state marker and pixels. A
normalized top-of-backbuffer region must contain the native gold exact-text
output for the dead owner and must not contain it for a living peer or a target
owner still in `DeathPresentation`. Gold output located only over a world actor
does not satisfy the region check. This closes the beta.17 gate hole where
semantic target/camera reads could pass despite the complete absence of visible
controls.

Post-fix isolated evidence:

- `shudh2a-0725` organically killed the host through melee. The product marker
  stayed hidden during `DeathPresentation` from `09:24:25.290` until
  `09:24:30.284`, then registered/rendered for sole target
  `2305843009213698050`. Left and right trials held that ID and exact camera
  position across 29 and 26 samples. The measured grace was 5.003 seconds;
  respawn retired the surface and red effect.
- `shudc2a-0725` killed the client through a stock projectile while it was
  casting. Its product transition was 4.991 seconds, both single-target click
  trials remained stable, the host never registered the surface, and respawn
  retired it.
- `shud3b-0725` retained one client product HUD before and after the Ether
  minion materialized on all three peers. The living Ether owner had no product
  pixels. The client held the dying target through the terminal corpse frame,
  both dead owners later rendered one HUD toward the surviving host, and all
  three peers returned to hidden state on wave respawn. Every diagnostic
  surface counter remained zero.

The corresponding backbuffer captures are
`runtime/multiplayer_organic_player_death/shudh2a-0725/`
`victim-spectator.png`,
`runtime/multiplayer_organic_player_death/shudc2a-0725/`
`victim-spectator.png`, and
`runtime/multiplayer_organic_spectator_followup/shud3b-0725/`
`after-ether-minion.png` plus `ether-minion-owner.png`.

### Native wave loading and organic-damage provenance

The original organic-death gate supplied a one-record `wave.txt` fragment and
then accepted the first live actor whose reported object type matched the
requested fixture. That does not prove the attacker came from the requested
native wave:

- `WaveData_LoadFromFile` at `0x006387F0` resolves and loads
  `data\wave.txt`, then enters `WaveData_Parse` at `0x00632730`.
- The module-directory resolver at `0x00444D50` calls
  `GetModuleFileNameA(NULL, ...)`; the path combiner at `0x00423A30` appends
  the relative data path. A live PID/path trace confirmed that each isolated
  process read the staged executable directory rather than the retail source
  directory.
- The parser's line reader at `0x00422470` accepts either CRLF or LF. Newline
  conversion therefore cannot explain selection of a stock-looking enemy.
- `WaveFlag_ParseModifiers` at `0x0062E070` maps `FLAG_CASTPOISON` to native
  modifier `0x24`; the poison fixture syntax reaches the stock flag parser.
- The retail file contains 42 `WAVE` records connected by their `NEXT:` graph
  plus one redundant trailing `ENDWAVE` token that the stock parser tolerates.
  One `WAVE` marker carries trailing tabs, so an exact-line text count reports
  only 41 even though the native grammar and headless parser both admit 42.
  Replacing one record cannot constrain whichever record the active Arena
  selects. A deterministic acceptance schedule must preserve every record and
  every `NEXT:` edge while replacing each record's spawn budget and group; the
  redundant terminator is not another record.

There is a second, independent provenance trap. Run construction creates nine
tracked Boneyard skeleton-family actors before `sd.gameplay.start_waves()`.
In the failed poison trace those actors had spawn serials 1 through 9. The
first actor selected by the verifier was `0x16628138`, spawned at
`00:46:59.107`; `start_waves` was not accepted until `00:47:03.632`, and the
first actor created after that boundary had spawn serial 10 at
`00:47:04.105`. The gate had therefore aimed a seeded melee skeleton at the
victim while claiming poison-wave coverage.

Skeleton variants also cannot be distinguished by the public actor object type
alone. `HookEnemySpawned` first calls `TryReadEnemyTypeFromActor`; the actor
reports the shared skeleton-family base type 1001, so the config fallback that
contains `SKELETONMAGE` and its cast flag is not consulted. Exact organic
provenance consequently requires all three conditions:

1. materialize a full staged schedule from the untouched retail schedule,
   preserving the complete `NEXT:` graph and replacing every group with the
   requested stock enemy/flag token;
2. snapshot all tracked enemy addresses before native wave start and select
   only an address absent from that snapshot; and
3. observe a real loss of victim HP while that exact new actor is the bound
   attacker before lowering the victim to a naturally lethal threshold.

The harness may reposition actors and raise the attacker's life to isolate the
trial, but it must not invoke a player-damage helper. Lethality must still pass
through the stock melee, projectile, or poison enemy behavior selected by the
materialized native schedule.

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
- A finite negative HP observation on the host clone is converted to the
  existing zero-life terminal correction; negative life is not added to the
  wire format.
- Owner regeneration cannot veto a simultaneously observed host-native damage
  delta.
- Replicated HP zero does not start an observer death animation. The
  owner-authored death-presentation flag starts the participant death epoch.
- Owner and observers use the same death-presentation epoch and agree on
  `+0x160`, the owner-authored bounded `+0x1BC` clock, and whether the grace
  presentation is active. Protocol 85 carries that clock explicitly rather
  than starting a peer-local timer when the death packet arrives.
- Presentation acceptance compares the native bounded clock on the first
  observer frame against the owner's clock, not packet-arrival wall time. A
  stalled peer cannot render during its app-thread gap; when it resumes,
  packet-age extrapolation must place its first rendered death frame within 12
  ticks of the owner without running the owner-only terminal/drop virtual.
- The single death-grace contract is 5,000 ms for owner and observers. It owns
  red-effect expiry, staff-drop epoch accounting, spectator handoff, and
  respawn eligibility.
- Throughout a connected multiplayer death, stored `+0x1BC` never exceeds the
  Arena red-safe boundary, so the owner-only tick-159 retirement block and
  tick-300 end-of-life path cannot execute. The runtime/wire clock still
  advances through 298, and the animation hook projects its clamped `0..159`
  value only for rendering on owners and observers.
- A current spectator target remains camera-valid while its replicated death
  presentation is active, so its complete death animation stays at the death
  location before automatic retarget.
- Local native dispatch, outgoing cast publication, and incoming authority
  reject dead participants before any spell, minion command, relay, transform
  mutation, or world effect.
- Normal player sessions do not register or draw diagnostic spectator-status
  surfaces. A separate product HUD registers only for the local owner in
  `Spectating`, uses native panel/text rendering on the swap-chain backbuffer,
  and cannot appear on a summon or other offscreen pass.
- Organic acceptance rewrites all 42 staged wave records while preserving the
  native `NEXT:` graph, excludes every pre-wave Boneyard actor by address, and
  observes a real HP decrement from the selected post-start actor before
  arming lethal life.
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
- Exact placement is asserted on the applied respawn epoch. After alive
  registration and collisions resume, stock controls and participant
  collision resolution may move the actor normally; later stability samples
  assert that death/grace state stays retired rather than pinning coordinates.
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
`tools/verify_multiplayer_organic_player_death.py` is the two-owner stock-wave
variant. It covers melee, projectile, and poison wave fixtures, host/client
victims, idle/casting input, synchronized presentation, owner-only one-shot
death/drop traces, grace expiry, spectator handoff, and respawn.
`tools/verify_multiplayer_organic_spectator_followup.py` is the three-owner
continuation. It organically creates a spectator, summons the default Ether
minion while that owner is the selected target, enforces the normal-session
zero-diagnostic-surface contract, then organically kills the selected target
and holds the camera on its position-stable corpse until the five-second
presentation expires.

## Beta.16 post-fix live evidence

The final x86 Release build was exercised through isolated loopback instance
groups with the stock 42-record wave graph:

- `orgdf-fix18` killed the host through melee while idle. Owner and observer
  logical presentation clocks reached 298, stored `+0x1BC` never exceeded
  150, both corpse-position deltas were zero, and spectator handoff occurred
  4.985 seconds after presentation began.
- `orgdf-fix19` killed the client through projectile damage while casting.
  Handoff occurred after 4.988 seconds; both peers held one corpse coordinate,
  and post-death primary/secondary input produced no accepted cast, replay,
  resource spend, summon, projectile, or damage effect.
- `orgdf-fix20` killed the host through poison while idle. Handoff occurred
  after 5.035 seconds with synchronized terminal presentation and zero corpse
  motion.
- `orgsf-fix5` exercised a previously dead spectator, the Ether owner's real
  Call Leviathan input, and then an organic death of that selected target.
  The first and second grace intervals were 5.050 and 5.057 seconds. The
  selected participant remained attached for 5.004 seconds across 89 samples;
  both owner and observer reached the terminal corpse frame without executing
  the native tick-159 CPU transition. All three peers materialized native type
  `0x07F2`, while every normal-session diagnostic surface count stayed zero.
- `dsr-fix1` retained host wave authority after host death, completed wave 1
  on all three peers, and respawned all three owners at the live Arena spawn.
  Host and client spectator delays were 5.111 and 5.060 seconds.
- `dpr-fix2` retained a dead-time level-up choice (`option 33`, active
  `0 -> 1`) through respawn. Skills, items, owned progression, and staff were
  exact on the same actor. Grace and immediate-round respawns both matched
  the independently read Arena spawn with zero coordinate delta on owner and
  observer; the old corpse was absent on both peers, the staff inventory delta
  was zero, and immediate wave completion canceled the death epoch after
  0.239 seconds.

The terminal-corpse captures for `orgsf-fix5` are
`runtime/multiplayer_organic_spectator_followup/orgsf-fix5/`
`spectated-target-terminal-corpse.png` and
`spectated-target-owner-terminal-corpse.png`. Dead-picker, spawn, and cleared
death-location captures for both respawn paths are under
`runtime/multiplayer_dead_progression_round_respawn/dpr-fix2-p/` and
`runtime/multiplayer_dead_progression_round_respawn/dpr-fix2-r/`.

## Spectator-target acceptance sampling

The spectator hold assertion must observe the selected target and that
target's replicated death-presentation flag from one runtime snapshot. Two
separate Lua exec calls can straddle the five-second transition: the first
call may still report the old target's presentation flag, while the gameplay
thread processes the terminal participant frame and legitimately retargets
before the second call. Treating those two different instants as one sample
produces a false early-retarget failure.

`query_spectator_target_death_state` therefore snapshots both values inside
one Lua execution. The hold gate includes only samples where that atomic view
still marks the expected target's presentation active, then requires the
spectator target ID to remain that participant for the entire sample set.
This preserves the strict early-handoff assertion without admitting a
boundary race in the harness.

Post-rebase `orgsf-rb4` held the organically dying selected target for 4.967
seconds across 82 atomic presentation samples. Its first and selected-target
grace intervals were 5.037 and 5.059 seconds, all three peers materialized
the Ether summon, and the target remained attached through its final
presentation sample. The complementary `orgdf-rb1`, `orgdf-rb2`, and
`orgdf-rb4` runs covered host melee/idle, client projectile/casting, and host
poison/idle respectively; every owner reached logical tick 298, every stored
`+0x1BC` value stayed at or below 150, both corpse-position deltas were zero,
and each owning death/drop trace delta was exactly one.

Terminal-corpse backbuffer capture must not consume the lifecycle poller's
deadline. The owner and spectator captures target different processes and run
concurrently; the bounded capture duration is added to the remaining polling
budget so the next sample can still observe `Spectating` and red-effect
retirement. The stock wave is also started immediately after the host enters
`testrun`, before remote relationship waits can let the short fixture spawn
ahead of the pre-wave address snapshot. The selected attacker is stabilized
and idled while the other peers finish joining. These are acceptance-harness
ordering rules only; they do not change the runtime presentation clock or its
five-second assertion.
