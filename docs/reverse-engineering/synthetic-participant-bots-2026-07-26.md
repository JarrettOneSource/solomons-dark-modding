# Synthetic participant bot seams

Date: 2026-07-26
Issues: #58 and #59

## Conclusion

A Lua bot can use the normal remote-player systems only when it is represented
as a host-authoritative synthetic participant with a stock gameplay slot. The
previous standalone actor rail cannot satisfy hostile targeting, stock ally
HUD, or standard multiplayer death semantics and is not used by the public
handle API.

The implemented path is:

1. `sd.bots.spawn` creates `ParticipantKind::RemoteParticipant` with
   `ParticipantControllerKind::LuaBrain`.
2. `RegisterSyntheticParticipantTransport` assigns a nonzero session nonce and
   host authority.
3. `ExecuteParticipantEntitySyncNow` enters
   `TrySpawnGameplaySlotBotParticipantEntity`,
   `CreateGameplaySlotBotActor`, and
   `FinalizeGameplaySlotBotRegistration`.
4. The actor occupies an ordinary stock gameplay slot 1..3.
5. The host ticks and samples that actor; clients consume authenticated
   participant state/frame packets through the ordinary remote playback path.
6. Despawn sends `ParticipantStateFlagRetired` before destroying the binding.

Protocol 86 carries the synthetic controller, authority, gameplay state, and
durable retirement flag. A client accepts a `LuaBrain` epoch only from its
configured host endpoint. The host rejects network peers that claim synthetic
authority.

## Native seams

| Purpose | Layout key | Address |
| --- | --- | ---: |
| create stock player slot | `gameplay_create_player_slot` | `0x005CB870` |
| world-register gameplay slot | `actor_world_register_gameplay_slot_actor` | `0x00641090` |
| world-unregister gameplay slot | `actor_world_unregister_gameplay_slot_actor` | `0x00641130` |
| stock player tick | `player_actor_tick` | `0x00548B00` |
| native player move step | `player_actor_move_step` | `0x00525800` |
| placement collision test | `movement_collision_test_circle_placement` | `0x00523C90` |
| extended placement test | `movement_collision_test_circle_placement_extended` | `0x005238C0` |
| pure-primary dispatch | `pure_primary_attack_dispatch` | `0x0054CAF0` |
| active cast cleanup | `cast_active_handle_cleanup` | `0x0052F3B0` |
| badguy damage | `badguy_damage` | `0x0048A290` |
| Fireball damage group gate | `fireball_hit_damage_projectile_group_gate_branch` | `0x005E5196` |

Movement still seeds actor `+0x218` and the `+0x158/+0x15C` movement
accumulators, then calls the native collision/move step. Lua never reproduces
the cell grid.

Cast control builds the same `CastPacket` fields and phases as a real peer and
calls `ApplyParticipantCastPacket`. The resulting request remains
`remote_input_controlled=true`. Dispatch happens once; the stock player tick
drives the active handler at actor `+0x160/+0x1EC`; cleanup remains
`0x0052F3B0`. The per-spell initialization predicate remains actor
`+0x5C == 0 && +0x27C == 0xFF`.

## Fire damage authority gap

The remote cast ingress correctly created and replicated Fireball projectiles,
but host-native enemy HP did not change. Fresh decompilation and live logs
localized the gap to `Fireball::Hit` (`FUN_005E5160`): the short `JNZ` at
`0x005E5196` (`75 6D`) skips stock damage for projectile group `0xFF`.
That rule is correct for observer presentation projectiles, but a host-owned
synthetic participant also enters through the remote ingress and therefore
has group `0xFF`.

The authority seam is narrow:

- the two-byte group gate is widened;
- `HookPurePrimaryAttackDispatch` records each newly created Fireball actor
  against the exact active host-owned synthetic participant and cast sequence;
- `HookBadguyDamage` allows stock damage only when the nonlocal source actor is
  present in that map and its participant remains active, host-owned, and
  `LuaBrain`;
- every other nonlocal Fireball remains rejected before stock damage; and
- unregister/run teardown retires the source mapping.

This does not write enemy HP and does not create a bot-only damage packet.
The authorized projectile calls the stock damage function on the host; the
normal authoritative world snapshot converges enemy HP to clients. Observer
peers keep presentation-only projectiles.

The new address has a binary-layout binding and static contract. The patch
descriptor explicitly uses two bytes because this branch is a short JNZ,
unlike the six-byte near gates in the same patch table.

## Live evidence

Evidence root:

`/mnt/d/codex-evidence/bot-players-20260726/`

Phase 1 (`phase1/result.json`) proved:

- the synthetic persona appears as a session member on host and client;
- both peers materialize an ordinary stock slot actor and nameplate;
- the stock ally-healthbar path renders the bot;
- a native hostile targets the synthetic participant ID; and
- reliable retirement removes the member and actor on both peers.

Phase 2 (`phase2/result.json`) proved:

- `success=true` for the full control/death verifier;
- native movement displaced the host bot 142.37 units and converged to zero
  cross-peer distance in the accepted sample;
- one Fire primary created native projectile type 2004 on both peers and
  reduced the stock Skeleton from 500 to 496 HP on both;
- a native incoming hit converged bot HP from 50 to 25 on both;
- before death a hostile selected participant
  `1152921504606851072` on both;
- the lethal stock hit produced the replicated remote death epoch, death
  presentation, terminal corpse, and peer screenshots;
- that hostile retargeted participant `2305843009213698049` on both; and
- cleanup stopped only the two exact staged `bot` processes after executable
  path validation.

The accepted death presentation reflects the two normal ownership views. The
host's authority metadata reaches terminal tick 159 while its stock slot actor
owns local presentation. The client drives its remote actor to native corpse
tick 150 from the replicated epoch. Both remain materialized at the same
position with zero HP and drive state 1.

## Rejected mechanisms

- no standalone actor materialization;
- no `local_player_actor`/slot-0 alias;
- no `HookMonsterPathfindingRefreshTarget` target promotion;
- no loader transform playback fighting the host stock tick;
- no cell-grid collision reimplementation;
- no direct enemy-health write; and
- no client-side synthetic damage authority.
