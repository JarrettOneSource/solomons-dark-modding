# Bot polish wave: root causes and design

Date: 2026-07-28  
Owner items: `bot.brain` v1.0.1 and the `sd.bots` seams

This document records the findings made against `main` before implementation.
The changes below must fix the owning initialization, vocabulary, progression,
and movement seams. They must not add permanent aliases, actor-field patches,
or target-coordinate teleports.

## 1. Listing copy drift

### Finding

`mods/bot-brain/manifest.json` is still version `1.0.0` and has no summary or
description. The repository publication records still contain the earlier,
longer copy. The live listing was updated independently, so the manifest,
publication record, and next package can drift from the public source of
truth.

### Resolution

Version `1.0.1` has one canonical summary and description in the manifest and
staged listing metadata:

- Summary: `Bot teammates that play like real players.`
- Description: `Adds bot teammates to your lobby. Bots fill real player slots: they show up in the member list, enemies target them, and they fight, die, and respawn like human players. Name each bot and choose its element and how it fights in the launcher's mod settings. Changes apply live, and in multiplayer the host's roster syncs to everyone. Requires v0.1.0-beta.21 or newer.`

The v1.0.1 ZIP, checksum, and listing-update JSON are staged as evidence only.
This wave does not call the website, modify `solomondarker.com`, or submit a
production listing.

## 2. Behavior vocabulary and native Discipline

### 2.1 Root cause: one word currently names two unrelated concepts

The bot-brain roster currently calls its policy profile `discipline`.
`skirmisher`, `guardian`, and `striker` are Lua AI behaviors; they are not
Solomon Dark Disciplines. The stock game uses Discipline for a character
loadout/progression choice: Mind, Body, or Arcane.

The collision reaches all bot-brain-owned layers:

- the launcher renders the manifest field as **Discipline**;
- persisted roster rows store the AI profile under `discipline`;
- `roster.lua`, `brain.lua`, logging, debug state, and bot-brain docs repeat
  that meaning.

The lower-level `sd.bots` character profile already uses
`profile.discipline_id` for the native character concept. It does not contain a
Skirmisher/Guardian/Striker alias. The simple `sd.bots.spawn` surface, however,
always chooses Arcane and offers no way for the bot-brain roster to select the
native field.

### 2.2 Vocabulary cutover

The AI field becomes `behavior` everywhere it is owned by bot-brain:

- launcher label: **Behavior**;
- values: `skirmisher`, `guardian`, `striker` (unchanged);
- roster row key, parsing, equality/reconciliation, logs, debug fields, and
  docs: `behavior`.

Native `discipline` is a separate roster choice with values `mind`, `body`,
and `arcane`. The `sd.bots` profile continues to expose the native wire value
as `discipline_id`; the ergonomic `sd.bots.spawn` table accepts the native
Discipline by name.

There is no permanent dual read in Lua. After migration, bot-brain reads only
`behavior` for AI policy and only `discipline` for the native loadout choice.

### 2.3 One-time saved-roster migration

The old and new meanings share the same persisted key, so merely changing the
manifest would invalidate existing rows. The launcher owns persisted mod
settings and must migrate before the loader reads them.

For `bot.brain` only, an old roster row is identified by:

1. `discipline` is exactly `skirmisher`, `guardian`, or `striker`; and
2. `behavior` is absent.

The launcher atomically rewrites that row once:

```text
old discipline -> behavior
discipline     -> arcane
```

Arcane preserves the loader's previous implicit default. The migration runs
both when the settings UI loads the roster and during stage construction, so a
user does not have to open the settings dialog before launching. A second load
does not rewrite the file because the legacy values are gone. There is no
migration marker and no ongoing legacy alias.

### 2.4 Native Discipline reverse engineering

#### Game data

The shipped wizard-skill data defines three legal native rows:

| Character profile | Native skill row | Game data |
| --- | ---: | --- |
| Body (`CharacterDisciplineId::Body == 1`) | `5` | `data/wizardskills/body_discipline.cfg` |
| Mind (`CharacterDisciplineId::Mind == 0`) | `6` | `data/wizardskills/mind_discipline.cfg` |
| Arcane (`CharacterDisciplineId::Arcane == 2`) | `7` | `data/wizardskills/arcane_discipline.cfg` |

Each file describes spending a skill point to unlock that Discipline's skills.
The compiled catalog independently identifies rows 5, 6, and 7 as the Body,
Mind, and Arcane Discipline rows.

#### Ghidra data path

Headless Ghidra decompilation of the retail executable establishes this path:

1. `0x005D0290`, the stock new-character setup, maps the create-screen
   Discipline selector to skill row `7`, `5`, or `6`.
2. It records that selected row at `Skills_Wizard +0x830`. At the end of the
   same stock initialization block it primes every base row `0..7`, including
   all three Discipline roots, to rank 1.
3. `0x00660320`
   (`PlayerAppearance_ApplyChoice(progression, choice_id,
   publish_gameplay_side_effects)`) performs the stock base-row increment only
   while `gameplay +0x1668+choice_id` is zero. A nonzero byte returns before
   touching the passed progression.
4. Once past that creation-only gate, `0x00660320` increments the permanent
   learned rank at row `+0x20` and clamps it against the native definition
   maximum at `*(row +0x6C) +0x5C`. Its third argument controls an additional
   gameplay-side-effect path through `0x005C85E0`; it does not initialize the
   per-progression row definition.
5. `0x0065F5B0` copies permanent ranks at row `+0x20` to effective ranks at
   row `+0x22`, resets derived scalars, and runs the skill/equipment passes.
6. `0x0065F9A0` performs the full progression refresh and recomputes the
   per-actor stat and skill state.
7. `0x0067CB70`, the native skill-option roll, reads the selected row at
   `+0x830` and compares it with each candidate's internal root id at row
   `+0x1C`. That per-book selection is what admits the chosen Discipline's
   skills to later level-up offers.

The profile enumeration order and native row order differ, so the loader must
use an explicit mapping:

```text
Mind (0)   -> row 6
Body (1)   -> row 5
Arcane (2) -> row 7
```

#### Per-character ownership proof

`0x005CB870` (`Gameplay_CreatePlayerSlot`) allocates a distinct PlayerActor and
a distinct `Skills_Wizard` progression object for each gameplay slot. The
progression wrapper is stored in the slot-strided gameplay table, and the inner
progression records its owning slot. The current bot materializer already
resolves that slot-owned inner object before applying the element selection and
primary loadout.

Therefore Discipline is a valid per-character loadout knob. Applying row
5/6/7 at `+0x830` on the bot's resolved progression object selects that bot's
own book; it does not require or justify changing slot 0 or a process-global
player book. The normal native progression refresh consumes the book's
permanent base ranks and recomputes effective ranks and derived state.

`MultiplayerCharacterProfile.discipline_id` is already validated as `0..2`,
serialized in participant state, received into remote participant profiles,
and exposed by `sd.bots` snapshots. The missing seam is materialization:
`PrimeGameplaySlotBotSelectionState` currently applies element and primary
loadout but never applies the profile's Discipline row to the slot-owned book.

#### Live gate correction

The first live implementation passed
`publish_gameplay_side_effects = 0`. A host/client probe then showed the mapped
selection cache at `+0x830` was correct for both bots, while rows 5, 6, and 7
remained zero on both machines. The same run proved that profile replication
and the bot-owned progression addresses were correct.

A second live probe read the native definition pointer and maximum for each
bot-owned row: all three definitions were present and each maximum was 1.
Changing the third argument to 1 still left all ranks at zero. The same probe
found `gameplay +0x1668+5`, `+6`, and `+7` were all 1. Decompilation confirms
that this is the creation-choice gate at the first instruction of
`0x00660320`, so both calls returned before the rank increment. The function is
valid during the stock new-character sequence and intentionally unavailable
after that sequence closes; bot materialization happens later.

The loader must not temporarily reopen this process-global gate. Doing so
would make local character-creation actions available while a bot is being
materialized and would couple one bot's book initialization to process-global
state. The established remote-progression hydration seam already writes owned
book entries directly and verifies them before a native refresh.

### 2.5 Resolution

The roster maps `mind/body/arcane` to the existing profile enum and passes the
choice into `sd.bots.spawn`. Materialization maps the enum to native row
`6/5/7`, validates the bot-owned native table and the native definition/max for
each stock base row, primes the complete stock `0..7` base-rank block, stores
the selected Discipline row at `+0x830`, verifies those writes, and runs the
native refresh. This restores the character-creation book initialization that
the late slot-clone path skipped, without opening a global gate or inventing
rank values beyond the native maxima. Roster replication needs no parallel
protocol: `discipline_id` is already part of the replicated character profile.

## 3. Black robes and incomplete appearance initialization

### 3.1 Reproduction

On current `main`, a host-owned Lua bot can materialize with a solid black robe
even when its profile element is Fire, Water, Earth, Air, or Ether. The
before-fix frame is retained under the bot-polish evidence root. The same bad
helper payload is published to a client; replication preserves the host's
mistake rather than causing it.

### 3.2 Native source/profile builder: `0x005E3080`

`ActorBuildRenderDescriptorFromSource` consumes a temporary source actor with
source kind `3` and an appearance profile at `actor +0x178`. Its complete
appearance-related output is:

| Source profile | Source-actor output | Meaning |
| --- | --- | --- |
| `+0x56` | actor `+0x1C0` | source-only idle behavior |
| `+0x74` | actor `+0x194` | source-only talk speed |
| `+0x9C` | actor `+0x23C` | primary render variant |
| `+0x9D` | actor `+0x23D` | secondary render variant |
| `+0xA4` | actor `+0x23E` | source weapon type |
| `+0xA0` | actor `+0x23F` | coarse element/render selection |
| `+0xA8` | actor `+0x240` | tertiary render variant |
| `+0xB4/+0xC4` | actor `+0x244..+0x263` | native-mixed cloth and trim descriptor |
| weapon type `1/2` | actor `+0x264` | source-side staff/wand object |

`0x0040FC60` performs the stock robe mix on the cloth source color. The
existing native-derived source-profile adapter already gets the bot element
color from live `Skills_Wizard` through `0x00660760`, converts it to the
required source-profile preimage, and retains the temporary source actor's
native trim. There is no element color table to maintain.

`+0x1C0` and `+0x194` belong to the temporary source/profile actor contract.
The clone path does not transfer them to the finalized player actor, so they
must not be copied as a supposed cosmetic block.

### 3.3 Native finalized-player and clone initialization

The stock player-start path `0x005CFA80` creates, seeds, and attaches:

1. a robe helper;
2. a hat helper;
3. a default staff;
4. the remaining starting inventory.

The stock clone path `0x0061AA00` allocates a fresh PlayerActor, progression
book, equip runtime, and selection/control object. Its complete visual transfer
is:

1. copy the source actor's 32-byte descriptor into a robe helper and attach it
   to equip lane `+0x1C`;
2. copy the same descriptor into a hat helper and attach it to equip lane
   `+0x18`;
3. move the source staff/wand from source actor `+0x264` into equip attachment
   lane `+0x30`;
4. consume source `+0x23F` to select the finalized actor's element/animation
   state and refresh its progression.

The packed source descriptor is helper-publication data. On a finalized player
actor, the same numeric window at `+0x244..+0x263` is live actor-local
animation/capacity state. It is not a stable color source and must not be read
or overwritten as one.

### 3.4 Actual bot-path difference and root cause

The gameplay-slot factory correctly creates an actor, progression, equip
runtime, and control brain. Its cosmetic seeding then diverges:

1. for a host-owned Lua participant,
   `SeedGameplaySlotBotRenderStateFromSourceActor` calls
   `CaptureActorRenderBuildSnapshot(native_visual_actor_address)`;
2. `native_visual_actor_address` is the already-finalized slot-0 player;
3. `CaptureActorRenderBuildSnapshot` reads slot 0's `+0x244..+0x263` as though
   it were the source descriptor;
4. those actor-local bytes are copied into both the bot robe and hat helpers;
5. a staff is attached independently and selector values are partly replaced.

This directly violates the repository's prior source-profile finding and
explains the black payload. The bot is not missing a single tint write; it is
missing the native appearance-production step that creates one coherent robe,
hat, attachment, and selector snapshot for the bot's own element.

The client branch consumes the host-published robe/hat helper color blocks.
That branch is structurally correct: it reproduces the bad host snapshot.

### 3.5 Name-label styling is a separate loader-owned seam

Native `0x005E3080`, `0x005CFA80`, and `0x0061AA00` contain no participant name
or label-style field. Bot nameplates and ally-HUD rows are loader-owned:

- the participant's replicated `display_name` is the text source;
- `gameplay_hud_hooks.inl` applies the common ally nameplate and health style;
- both host and client resolve the same participant identity and display name.

The appearance fix must preserve and verify this lane, but must not invent a
name-style actor offset or copy slot 0's name state.

### 3.6 Resolution

One appearance initialization result owns all bot visual outputs:

- host authority builds a short-lived native-derived source/profile actor for
  the bot's element and captures its prepared descriptor and selectors;
- finalized actor `+0x244..+0x263` is never used as a descriptor donor;
- the descriptor is published through both robe and hat helper lanes;
- the native source weapon choice produces the corresponding finalized
  attachment lane (the default bot loadout is staff);
- only the verified safe finalized-actor selector fields are seeded;
- the participant display-name/nameplate path remains participant-owned;
- the captured helper/selector/attachment state is published in the existing
  participant presentation packet and rebuilt identically on client B.

This closes the whole appearance initialization class instead of writing a robe
tint after spawn.

## 4. Stuck-bot teleport failsafe

### 4.1 Current movement ownership

`sd.bots.move_to` stores a final destination and increments a movement-intent
revision. The gameplay thread:

1. builds/rebuilds a loader-owned path;
2. steers through `path_waypoints`;
3. applies each step through the stock PlayerActor movement executor;
4. publishes the authority actor transform to peers.

Two existing contracts are important:

- an exhausted `path_waypoints` list is not proof of final arrival; if the
  actor is still farther than the final-arrival threshold, the path must be
  rebuilt;
- stopping loader movement must clear stock PlayerActor walk inputs at actor
  `+0x158/+0x15C`, or `PlayerActorTick` continues consuming a stale vector.

There is currently no bounded recovery when valid path/repath activity never
makes spatial progress.

### 4.2 Why a simple timer is wrong

Bot-brain periodically calls `move_to` again. Every accepted call receives a
new revision, even if the effective destination remains the same. A timer
reset on revision would never fire. Conversely, a timer based only on an empty
waypoint list would misclassify segment-exhaustion oscillation as arrival or
progress.

### 4.3 Rolling progress model

The authority binding owns a rolling sample window for one continuous active
target. Revisions do not reset it. A material target-coordinate change does.
Samples contain:

- monotonic timestamp;
- distance from the actor to the active final target;
- a monotonic **meaningful waypoint progress** generation.

Meaningful target progress means a decrease larger than the movement epsilon
within the rolling window. Meaningful waypoint progress requires reaching a
new steering waypoint after real actor displacement; incrementing an index
over a waypoint that is already within its threshold does not count. Emptying
the segment never counts by itself.

The bot is stuck only when a full 30-second rolling window shows both:

1. no meaningful decrease in final-target distance; and
2. no meaningful waypoint progress.

Reachable movement, including slow movement and ordinary path rebuild churn,
keeps at least one progress condition true.

### 4.4 Validated landing and authority

Only the authority-owned Lua participant evaluates or executes the failsafe.
Packet-driven remote actors never do.

At timeout, the loader passes the target to the existing bounded outward
placement search. Every candidate is checked by the existing native
`movement_collision_test_circle_placement` and extended placement calls, the
actor collision radius/mask, and existing bot reservations. A raw target write
is forbidden.

If a valid landing is found, the authority:

1. writes the bot actor transform to the validated landing;
2. rebinds the actor to the owner world's cell grid;
3. clears the loader path and stock walk vector at `+0x158/+0x15C`;
4. ends the satisfied movement intent;
5. publishes the normal participant gameplay snapshot for replication;
6. starts a cooldown so a new failed request cannot loop;
7. emits exactly one clear `[bots] stuck teleport` line containing the bot id,
   requested target, validated landing, elapsed window, and placement search
   distance.

If no valid placement exists, no coordinate is written and the normal path
retry behavior continues.

Human click-to-move never enters `ParticipantEntityBinding` or this
Lua-participant authority branch, so it is outside the failsafe by
construction.

## 5. Verification and evidence

The dedicated live verifier uses only ports `50011` and `50012`, launches every
game process with `SDMOD_DISABLE_AUDIO=1`, and labels the second machine
`client B` in committed output.

Required evidence:

- before-fix black-robe frame;
- host and client B frames of a four-slot lobby with at least two bot elements;
- host/client B profile agreement for native Discipline;
- a walled fixed-target scenario that teleports after approximately 30 seconds
  to a placement accepted by the native search and converges on both machines;
- a slow reachable target that remains active for at least 30 seconds without
  teleport;
- a local human click-to-move check with no stuck-teleport log;
- targeted tests plus the complete release battery on the rebased landed SHA;
- staged v1.0.1 ZIP, SHA-256, listing update, and an
  `evidence-sha256.txt` inventory.

No legacy local-multiplayer sync verifier and no production publication path is
part of this wave.
