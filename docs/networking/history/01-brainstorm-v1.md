# Solomon's Dark: Netcode Brainstorm (pre-Codex review)

Date: 2026-04-19

## User's non-negotiables

1. Synchronize enemies, players, and drops.
2. Support both a dedicated server AND peer-to-peer hosting.

## What exists in the code today

### Participant rail (real, working for bots)

- `Mod Loader/SolomonDarkModLoader/include/multiplayer_runtime_state.h`
- `ParticipantInfo` with `ParticipantKind{LocalHuman, RemoteParticipant}` and `ParticipantControllerKind{Native, LuaBrain}`.
- Bots flow through as `RemoteParticipant + LuaBrain`.
- Remote humans will be `RemoteParticipant + Native`.
- Per-participant state: steam_id, name, ready, transform (pos/heading), HP/MP, element/discipline, level/xp, scene intent (SharedHub/PrivateRegion/Run), run_nonce, queued cast IDs.

### Protocol header (drafted, not wired)

- `Mod Loader/SolomonDarkModLoader/include/multiplayer_runtime_protocol.h`
- Magic: `SDMP`, Version 5.
- PacketKind: State (108B), Launch (56B), Cast (60B), Progression (32B).
- Binary packed, size-asserted.
- NO enemy, drop, or damage packets exist yet.

### Service loop (pumps Steam, no transport)

- `Mod Loader/SolomonDarkModLoader/src/multiplayer_service_loop.cpp`
- 50 ms tick pumping Steam callbacks and mirroring into `RuntimeState`.
- No peer connections, no session, no replication.

### Foundation (initializes RuntimeState, that's all)

- `Mod Loader/SolomonDarkModLoader/src/multiplayer_foundation.cpp`

### Bot runtime (proves the participant abstraction works)

- Bots materialize real `PlayerActor` entities via ctor chain (`_aligned_malloc(0x398)` → `PlayerActor` ctor at 0x0052B4C0 → `ActorWorld_Register`).
- Register into gameplay slots 1-3; get targeted by hostiles; take damage; move via native movement collision path.
- Documented in `Mod Loader/docs/bot-and-multiplayer-plan.md` "Current Bot Status (2026-04-09)".
- Known bug: `actor + 0x04` render node still shared with local player (parenting bug).

### Prior netcode decisions (from docs/bot-and-multiplayer-plan.md)

- Player movement: client-owned, zero input lag, remote pos interpolation.
- Enemy state: host-owned, snapshot interpolation at 10-20 Hz, clients render 100-150 ms behind.
- Client casts: optimistic animation, host hit validation via position history buffer.
- Boss/death: host-confirmed broadcast.
- Transport plan: Steam P2P primary, loopback for testing, direct IP fallback.
- Session: lobby browser in Dark Cloud UI tab, party formation in hub, synchronized run launch.

## What the SolomonDark codebase forces on us

- x86 process, 32-bit.
- Single-threaded around D3D9 frame pump — sim appears entangled with rendering.
- Native DLL loader can hook anything in the exe.
- Lua runtime hosts mod API; the `sd.*` API was designed single-player, not sandboxed for multiplayer trust.
- Named-pipe Lua exec server already exists (dev-mode backdoor — must disable in multiplayer).
- `Arena_Create` at `0x0046EA90`, region switch at `0x005CDDD0`.
- `Enemy_Create` at `0x00469580`, spell cast hook at `0x0054CC50`.

## My proposal (to critique)

### Authority model

| Entity | Authority | Sync | Rate |
|---|---|---|---|
| Local player | Self | Pose stream to others; reliable events for casts / item use | 20-30 Hz |
| Remote player | Their owner | Pose interpolation | as received |
| Enemies | Host | Snapshot burst (pos + vel + hp_delta + state) | 10-20 Hz |
| Drops | Host | Reliable spawn / pickup / despawn events only | event-driven |
| Spells | Caster optimistic, host validated for hits | reliable | event-driven |

### Unified NetEntity abstraction

Rather than three replication paths (player / enemy / drop), one `NetEntity` table with:
- `net_id` (64-bit)
- `kind` (Player | Enemy | Drop | Projectile | VFX?)
- `authority` (LocalOwner | HostAuthoritative | ClientAuthoritativeWithHostValidation)
- `transform`, `hp`, `state_flags`
- Bot already proves this shape works for actors — enemies slot in identically.

### Dedicated server options

- **(a) Headless-ish exe** — run `SolomonDark.exe` with a stub D3D9 device, no window, `--server` flag injected by the loader. Cheapest. Pays for ignored render ticks. Must stub `HWND` / input. What Valheim / 7DTD effectively do.
- **(b) Authoritative-client-as-server** — no true dedicated; one client flagged "server-mode." Really P2P with a lonely host. Skip if we want true dedicated.
- **(c) Extracted sim loop** — pull gameplay tick out of renderer path into standalone. Biggest lift. Probably overkill for co-op.

Leaning toward **(a)**. P2P host runs the same code alongside a local player.

### Transport abstraction

```
ITransport {
    send_reliable(peer, channel, bytes)
    send_unreliable(peer, channel, bytes)
    broadcast_reliable/unreliable(channel, bytes)
    poll() -> events
}
```

- Steam P2P impl.
- Raw UDP / ENet impl (for dedicated-over-internet).
- Loopback impl (for testing).
- Everything above this line is identical in dedicated and P2P.

### Tick decoupling

Game runs at frame rate. Netcode tick must be fixed (30 Hz or 60 Hz on host). Otherwise a 200 FPS host and 60 FPS client desync in subtle ways.

## Open questions

1. Is "headless-ish exe" (option a) realistic given D3D9 entanglement?
2. Is unified NetEntity the right call, or does each entity type deserve its own replication strategy?
3. Does the current protocol header need rearchitecting (it has no enemy / drop / damage packets)?
4. Is 10-20 Hz enemy snapshot enough for ARPG feel?
5. Bot-to-remote-human swap path: does the existing code allow swapping input source without re-spawning the actor?
6. Cheat surface: Lua API was single-player; what audit is needed before multiplayer?
7. Reconnection + full-state resync: what's in the baseline packet catalog?
8. Progression sync: XP, loot roll determinism, boss phase transitions?
