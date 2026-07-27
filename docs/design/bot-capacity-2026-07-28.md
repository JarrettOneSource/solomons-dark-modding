# Bot capacity and lobby membership

Date: 2026-07-28  
Issue: #71  
Status: implemented against the retail four-participant ceiling

## Decision

Bots and humans consume the same lobby capacity:

```text
human lobby members + active bot participants <= maxParticipants <= 4
```

The framework does not impose a separate bot-count policy. It exposes
participant primitives, enforces the configured lobby capacity, publishes
membership, and replicates bot participants. The `bot.brain` Lua mod owns the
desired roster and all behavior policy.

The configured range is two through four participants. Four is the retail
binary's native actor ceiling, not a matchmaking preference. A value above four
is rejected during launcher/configuration validation and again by the loader;
it is never clamped. A bot spawn without an open seat returns
`nil, "lobby full"` to Lua.

## Native ceiling

The ceiling was recovered from the retail `SolomonDark.exe` before changing
capacity policy. Headless Ghidra output is archived under
`/mnt/d/codex-evidence/botcap-20260727/investigation/`.

### Player and progression slots

`Gameplay_Ctor` (`0x005CC800`) initializes exactly four player-slot records. Its
constructor loop terminates at `iStack_40 < 4`.

`Gameplay_CreatePlayerSlot` (`0x005CB870`) indexes two parallel fixed layouts
without a bounds check:

- actor pointer at `gameplay + 0x1358 + slot * 4`;
- progression pointer at `gameplay + 0x1654 + slot * 4`.

A fifth slot would write beyond both four-entry layouts. `FUN_005D7EF0`
independently reads the four actor fields at `+0x1358`, `+0x135C`, `+0x1360`,
and `+0x1364`. These are direct memory-safety and gameplay-consumer proofs that
the framework must not field a fifth participant.

### Ally HUD

The ally HUD does not introduce a lower ceiling. `FUN_0052C910` queues one
health-bar record per active remote player into the dynamic `Game::HealthBar`
list through `FUN_005CF480`; `FUN_005D2520` iterates that list. The five sprite
draws once suspected to be five ally rows are mixed UI assets, as recorded in
[`ally-healthbar-investigation.md`](../ally-healthbar-investigation.md).

The loader's multiplayer-name hook resolves the queued remote participants by
their occupied gameplay slots. With one local player, the native four-slot
layout can therefore produce at most three ally rows.

### Enemy targeting

`Player` construction at `0x0052A500` registers every player actor through the
gameplay-owned dynamic player collection at `gameplay + 0x1388`.
`FUN_00481A60`, the hostile target selector, iterates the collection using its
count at `+0x1390` and pointer storage at `+0x139C`; it does not stop after a
bot-specific count. Consequently every fieldable slot-0 through slot-3 player
actor is targetable.

The actor/progression slot layout is the limiting system. There is deliberately
no live run above four participants: attempting one would cross the proven
unguarded native array boundary. Capacity-four live acceptance exercises every
safe native slot instead.

## Capacity semantics

One runtime helper owns the arithmetic:

- humans are the greater of currently connected native-controlled participants
  and authoritative lobby membership;
- bots are active `LuaBrain` participants;
- occupied seats are humans plus bots;
- the effective capacity is the validated `session_max_participants`.

Using lobby membership as the human floor reserves a seat while a Steam member
is joining but has not yet materialized as a gameplay participant. This closes
the race where a bot could take the last seat between lobby entry and the
session hello.

Bot creation checks occupied seats before participant registration and returns
the structured `lobby full` error. Steam session hello applies the same
prospective-human-plus-bots calculation and returns the existing
`LobbyFull` result. Local UDP host ingress rejects a previously unknown native
participant while full. Despawning a bot removes its participant before the
next admission decision, immediately freeing that seat.

`maxParticipants` remains the session's total capacity. It is not dynamically
reduced when bots spawn. This keeps one stable advertised maximum while the
current `players` count truthfully changes with both member kinds.

## Membership schema and surfaces

Active bots are session members on host and client. The session-status
`members[]` entry for a bot includes:

```json
{
  "participantId": 1152921504606851072,
  "name": "Ember",
  "isSynthetic": true,
  "isBot": true,
  "gameplaySlot": 2
}
```

`isBot` is additive and optional. Human entries omit it, and launchers that
deserialize an older status file default it to `false`. Existing consumers of
the other fields remain compatible.

The launcher roster renders `isBot` entries with a small uppercase `BOT` chip
to the right of the name. It uses the existing compact chip dimensions and the
subtle gold border/foreground idiom from the mod-settings dialog. The host chip
continues to use the same row template. The launcher lobby count and website
announcement both derive `players` from `members.length`, so bots contribute to
the displayed count and a capacity-filled lobby announces `4/4`.

Local UDP writes the same session-status schema as Steam. This is an
acceptance/debug surface for isolated staging and does not publish a local
session to the production directory.

## Framework/mod policy boundary audit

The loader retains only:

- spawn and despawn;
- movement destination and stop;
- cast ingress;
- participant state reads;
- shared capacity validation and admission;
- membership serialization;
- participant replication and retirement;
- native cast-mechanics guards needed to execute an already-requested cast
  safely.

The loader contains no desired roster size, discipline selection, target
preference, think cadence, kite/flee/guardian/striker behavior, or autonomous
decision loop. The old fixed `occupied_remote_slots >= 3` bot gate was removed.
The native slot search still covers slots 1 through 3 because slot 0 belongs to
the local human; that is actor materialization, not roster policy.

All roster and behavior policy remains in `mods/bot-brain`:

- its manifest permits zero through four desired rows, matching the honest
  total framework bound;
- Lua reconciles desired rows against available seats;
- `lobby full` is an expected capacity state, not a reconciliation failure;
- aggregate telemetry reports states such as
  `2 of 4 bots active — lobby full`;
- capacity-refused rows continue retrying, so a despawned human or bot frees a
  seat without changing the configured roster;
- host authority, settings replication, and late-join adoption are unchanged.

Four desired bot rows are useful for policy persistence even though at least
one human always occupies slot 0 and no more than three bots can be active in a
live game. The framework does not silently rewrite the mod's desired roster.

## Acceptance record

The final isolated acceptance artifacts and machine-readable summary are kept
under `/mnt/d/codex-evidence/botcap-20260727/`. The run uses only the `bcap`
instance prefix, local UDP ports 49811/49812, and audio-disabled staging.

The final run is recorded in `flow/result.json` with `success: true` and no
nonempty crash artifacts. It proved:

- host plus one human plus Ember and Bastion occupied all four seats;
- both peers published the same four `members[]` entries, with `isBot: true`
  only on Ember and Bastion;
- the host and client in-process WPF renders at
  `launcher-rosters/host-roster-4-of-4.png` and
  `launcher-rosters/client-roster-4-of-4.png` showed `Players: 4 of 4` and a
  gold-outline `BOT` chip beside both bot names;
- the local development directory announced `players: 4`,
  `maxPlayers: 4`, and rendered `4/4` in
  `website/lobby-row-4-of-4.png`;
- two further desired roster rows were capacity-refused, a raw framework spawn
  returned `nil, "lobby full"`, and host Lua telemetry exposed
  `2 of 4 bots active — lobby full` without a reconciliation error;
- a password-authorized join at `4/4` received the normal HTTP 409
  `That lobby is full.` decision and its existing launcher-facing
  `The class is full — every seat is taken.` UX;
- removing Bastion changed both peer rosters and the website announcement to
  `3/4`, after which the identical password authorization succeeded and issued
  a launch ticket;
- both bot names occupied valid ally HUD rows on both processes; and
- stock hostiles organically selected each bot in turn, while the matching
  live replicated enemy on the client carried the same bot participant target.

The join decisions used the local development website against the two staged
game processes; no third game process or unapproved port was introduced.

No above-four run is permitted because four is the proven native safety
ceiling.
