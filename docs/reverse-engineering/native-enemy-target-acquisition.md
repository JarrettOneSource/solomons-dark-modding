# Native Enemy Target Acquisition

This note records the retail target-selection, invalidation, and refresh chain
before the multiplayer retargeting behavior is changed. Addresses are for the
supported retail executable described by `config/binary-layout.ini`.

## Acquisition

`MonsterPathfinding_SelectNearestTarget (0x00481A60)` owns the stock candidate
scan. Its recovered control flow is:

1. Read the `PointerList` embedded at `gameplay + 0x1388`.
   `PointerList::count (+0x08)` and `PointerList::items (+0x14)` therefore
   appear at `gameplay + 0x1390` and `gameplay + 0x139C`.
2. Reject a candidate while `candidate + 0x160 != 0`.
3. Read the candidate's signed ActorWorld group at `candidate + 0x5C`.
4. Require
   `gameplay_index_state_table[candidate_group] == actor_world + 0x78`.
5. Choose the remaining candidate with the smallest Euclidean distance.
6. The retail final branch commits only a candidate in ActorWorld group zero.
   It calls `ActorWorld_RelocateHostileToGroupZero (0x0063F7A0)` for the
   hostile, then writes:
   - `hostile + 0x168`: selected actor pointer
   - `hostile + 0x164`: target bucket delta

If no candidate survives, the selector clears `hostile + 0x1D8`; it does not
reliably clear both the old target pointer and bucket delta.

`0x0063F7A0` relocates the **hostile**, by unregistering it through
`ActorWorld_Unregister (0x0063F600)` and registering it again in group zero.
It is not a target-registration API. Calling it to promote a standalone or
non-slot target changes ActorWorld ownership while pathfinding is active and
is prohibited; that experiment previously hung the pathfinder.

## Candidate-list ownership

`Gameplay_Ctor (0x005CC800)` constructs two adjacent `PointerList` objects,
the first at `gameplay + 0x1388`. The first list is the stock hostile-target
candidate list:

- `Player_HostileCandidateRegister (0x0052A500)` dispatches the list's
  `+0x10` add virtual.
- `Player_HostileCandidateUnregister (0x00529410)` dispatches its `+0x1C`
  remove virtual.
- `Golem_HostileCandidateRegister (0x005F57E0)` and
  `Golem_HostileCandidateUnregister (0x005F5A20)` use the same add/remove
  lane.

That makes living gameplay-slot players and Golem/player-derived allies native
candidates. It does not make every ActorWorld actor a target.

Two player-owned ally classes do not both inherit that list lifecycle:

- `GoodImp (0x3ED)`: constructor `0x00529FE0`, initialization `0x0052A050`
- `Leviathan (0x7F2)`: constructor `0x005E8FB0`, destructor `0x005F4670`

The player-owned-minion extension may inspect these explicit native types, but
must not scan arbitrary actors as hostiles. A sidecar candidate is valid only
when it is live, in the hostile's ActorWorld, has non-negative group/world
slots, and round-trips through the exact ActorWorld bucket entry. `Golem (0x7F4)`
is included in the explicit type policy for clarity even though its stock list
lifecycle already covers it.

`ActorWorld_Unregister (0x0063F600)` confirms the exact bucket lookup:

```text
actor_world + 0x500 + (actor_group * 0x800 + world_slot) * 4
```

The `0x800` stride and `world_slot` are entry indices; the final `* 4` selects
the 32-bit actor-pointer cell. A sidecar must round-trip through that cell
before it can be written as a target.

## Death and removal invalidation

`Player_DeathTransition (0x00534120)` first writes `1` to player `+0x160`, so
the stock selector rejects the corpse. It then treats the host slot
asymmetrically:

- a non-host player is removed from the candidate list;
- the actor stored at `gameplay + 0x1358` (slot 0) remains in the list, but is
  ineligible because `+0x160 == 1`.

The destructor removes a player through `0x00529410`. `ActorWorld_Unregister
(0x0063F600)` clears the ActorWorld bucket and owner state, but does not repair
every hostile's `+0x168/+0x164` reference to the removed target.

This is the beta.17 host-death asymmetry: the host corpse remains resident but
filtered, while the current target can be cleared or left dangling without an
event-driven nearest-target acquisition. The loader's beta.17 widening layer
then compounds it by scanning only participant bindings and by refusing to run
outside its active-wave lifecycle guard; it knows nothing about native
candidate-list allies or player-owned summons.

## Refresh and re-evaluation

The selector is reached from these native paths:

- `MonsterPathfinding_RefreshTarget (0x00483480)`
- `Badguy_CommonChaseTick (0x004835F0)`
- `Badguy_RefreshTargetThenDispatch (0x00484AA0)`
- `Badguy_RefreshTargetLongCadence (0x00487F60)`
- `Badguy_ContactTargetScan (0x004881A0)`

`MonsterPathfinding_RefreshTarget` derives `hostile + 0x1E0` from the monster
definition's `+0xB9` byte, calls the selector, reloads the target pointer from
the ActorWorld bucket, faces it (or chooses a random heading when no target
exists), and stores the current tick modulo cadence at `hostile + 0x1DC`.

`Badguy_CommonChaseTick` re-evaluates periodically, including a 25-tick flag
lane, a missing-bucket lane, and class-specific cadence lanes. None is a
guaranteed target-death/removal event. `Badguy_ClearLinkedTargetAndNotifySlots
(0x00484B30)` clears the separate linked-target handle at `+0x236/+0x238`; it
does not clear or reacquire the current `+0x164/+0x168` pathfinding target.

The decompiler recovers `Badguy_CommonChaseTick` as
`uint __fastcall(int* hostile)` with no stack arguments. It is the Badguy
vtable `+0x08` tick, begins with a six-byte instruction boundary
(`push ebp; mov ebp,esp; and esp,0xfffffff8`), and calls the selector from its
periodic lanes before running chase movement. The branch ending at
`0x00483895` calls the selector and then unconditionally writes zero to
`hostile + 0x168`. A selector detour can therefore choose a valid extended
candidate only to have that pointer erased by its native caller. The common
chase return edge is the first native per-hostile boundary where both that
clear and any target mutation during a death transition are complete.

## Multiplayer authority contract

The host owns hostile AI and therefore owns nearest-target selection. Existing
run-enemy snapshots already carry either participant identity or native target
identity (`target_native_type_id`, ActorWorld group, world slot, and bucket
delta). A client resolves the equivalent local actor and applies that
host-authored target. The correction must preserve that single-authority path;
clients must not independently choose a nearest target.

Player-owned summon ActorWorld slots are peer-local. In a live client-owned
Leviathan case, the same summon was `(group=1, world_slot=1)` on the host and
`(group=0, world_slot=13)` on its owning client, so exact slot identity cannot
cross the wire. Protocol 84 already carries both `target_participant_id` and
`target_native_type_id`: for explicit player-owned ally types, the host records
the owner participant plus the native ally type. The client maps that
host-authored composite identity to the same owner's local ActorWorld group and
chooses the nearest live actor of that type only when the exact native slot is
not present. This is identity translation, not client-side hostile target
acquisition.

The runtime behavior change must therefore:

1. run the stock selector first;
2. on the host, deterministically choose the nearest valid candidate across
   the native candidate list plus the explicit player-owned ally types;
3. exclude dead/spectating players through the native `+0x160` state and
   multiplayer participant-death state;
4. reacquire after removal, or on the first safe native-player-tick boundary
   after death;
5. re-evaluate live run enemies on a bounded host cadence so a newly spawned or
   newly nearer valid target does not wait on a class-specific stock lane;
6. write only the hostile target pointer and bucket delta—never relocate or
   promote the target actor; and
7. leave Lua target overrides, Turn Undead locks, manual freeze behavior, and
   client-applied authoritative targets as higher-priority policies.

## Loader correction

The loader detours `MonsterPathfinding_SelectNearestTarget` itself, so all five
recovered stock re-evaluation paths share one correction:

1. manual freeze, Turn Undead, client snapshot authority, and an explicit Lua
   target override retain priority;
2. on the host's default policy, the retail selector runs first;
3. the host evaluates the native `gameplay + 0x1388` candidate list, all
   materialized wizard participants, and the explicit GoodImp/Leviathan/Golem
   sidecar types;
4. every candidate must be alive, have `+0x160 == 0`, share the ActorWorld,
   and round-trip through its exact ActorWorld bucket;
5. the nearest candidate wins and only `hostile + 0x168/+0x164` are written.

Ordinary native-list actors must also pass the retail group-to-region
comparison. Materialized remote wizard slots do not: live two-peer evidence
showed their exact ActorWorld group/slot bucket was valid while their
per-player region-table entry remained `-1` in region `5`. Wizard participant
slots and the three explicit player-owned ally types may therefore cross an
unset region-table entry after the stricter same-world/exact-bucket checks.
Arbitrary actors never receive that exception.

Slot 0 is not represented by a `ParticipantEntityBinding`; it is the stock
local player actor. The loader must append that actor explicitly and map it to
`GetLocalTransportParticipantId()` (or the offline local participant ID).
Without that mapping, the extended-candidate exception applied only to remote
players: a living host could be rejected by the retail region-table comparison
while the client remained eligible, making nearest selection asymmetric.

`HookActorWorldUnregister` captures hostile references before stock clears the
target's owner/bucket and runs re-acquisition after unregister returns. The
refresh detour also reapplies host selection after retail refresh logic,
because the native death transition can clear a hostile's target before the
loader observes the wizard's dead state.

Multiplayer participant `life_current <= 0` is latched on the 50 ms
materialized-participant service edge. A live organic-death trace established
an ordering constraint that the synthetic death gate did not expose: changing
the attacker's target on that life-zero edge happened before
`Player_DeathTransition`, the transition never ran, and the player remained at
negative health while regeneration continued. The corrected edge captures the
affected hostiles and excludes the dead participant immediately, but defers
loader target mutation for a dead slot-0 actor until stock sets the native
`+0x160` ineligible byte. The animation-drive byte cannot be used as a second
signal: ordinary cast, movement, and damage reactions also set it, and a live
hit trace proved that doing so released the grace period before
`Player_DeathTransition`. A 1,500 ms fallback bounds re-acquisition if the
native transition signal never arrives. Remote-player death does not need this
grace on host authority because its native death stack runs on the other peer.

The common-chase hook snapshots the current target pointer and bucket delta
before retail code runs. If life crosses zero during that tick, the hook
captures the affected hostile and restores those two fields until the native
death-transition signal. This closes the earlier race where the 100 ms
maintenance could observe progression HP at zero before the multiplayer
participant snapshot had published the death latch.

The affected hostile addresses remain latched for the logical death epoch
(with a 30-second stale-state safety bound); native `+0x160` alone does not
retire the latch because the actor can remain in the host slot. The local-player
tick return edge and Badguy common-chase return edge then apply bounded
maintenance. This covers host and remote-client deaths without relying on the
asymmetric retail slot removal. Clients never run nearest selection; they
continue resolving the host-authored participant, owner-plus-native-type, or
exact native target identity from world snapshots.

The common-chase return edge also repairs a missing, dead, or natively
ineligible current target outside a participant-death epoch. This is required
for the native `0x00483895` post-selector clear and for summon/allied-NPC
death. That repair alone is insufficient for the nearest-target contract:
live evidence showed a hostile retain a valid player target for the entire
2.5-second observation after a nearer Leviathan appeared because none of its
class-specific native selector lanes fired. The host therefore re-evaluates
every live scene-combat enemy at most once per 100 ms on the existing
materialized-participant service edge. This enumeration comes from validated
ActorWorld scene actors, not only the run-lifecycle spawn-hook map: a stock
wave actor can already be scene-visible and replicated without appearing in
that map's current snapshot. The same scene scan refreshes the ally sidecar, so
maintenance does not perform a second 8,192-bucket pass. Higher-priority manual
freeze, Turn Undead, and Lua policies still short-circuit the selection, and
clients still apply only host-authored target identity.

Loader death validation applies progression health only to native type `1`,
the player family. Native summons do not own those progression fields; treating
arbitrary readable bytes at the player offsets as a progression pointer made a
living Leviathan (`0x7F2`) appear dead despite `+0x160 == 0` and an exact live
ActorWorld bucket. The arena-enemy health and death-handled fields are likewise
restricted to native arena-enemy types. Other actor classes are invalidated
through the stock `+0x160` eligibility byte and ActorWorld removal instead of
guessing a class-specific health layout.

No behavior path calls `ActorWorld_RelocateHostileToGroupZero` for a target,
registers a target into a gameplay slot, or invokes the old standalone-bot
promotion experiment.
