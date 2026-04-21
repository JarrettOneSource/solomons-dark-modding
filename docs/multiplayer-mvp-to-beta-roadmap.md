# Multiplayer MVP To Beta Roadmap

Date: 2026-04-13
Status: Drafted from current loader/runtime state

## Purpose

This roadmap turns the current bot/render MVP into a beta-ready multiplayer product.

It is intentionally opinionated:

- keep one participant rail for local player, Lua bot, and remote player
- stop overloading `wizard_id` into "the whole character"
- introduce a real replicated character profile model before networking gets deeper
- remove temporary MVP assumptions before beta instead of layering more fixes on top

## Current MVP State

What is already working:

- injected loader, Lua runtime, and `.sdmod` staging contract
- typed gameplay/UI/debug seams with live Lua memory tooling
- slot-backed bot creation and movement
- bot loadout data in the runtime layer
- first profile-centric cutover slice is already landed:
  - participants own `MultiplayerCharacterProfile`
  - bot Lua/runtime APIs now accept `profile = { element_id, discipline_id, appearance_choice_ids, loadout, level, experience }`
  - gameplay queue/materialization now carries profile identity instead of a bare top-level `wizard_id`
  - protocol structs now have profile-shaped identity fields instead of only `wizard_id`
- corrected public element semantics:
  - `fire` -> orange -> stock slot `16`
  - `water` -> blue -> stock slot `32`
  - `earth` -> green -> stock slot `40`
  - `air` -> cyan -> stock slot `24`
  - `ether` -> purple -> stock slot `8`
- player/bot parity for the verified element lanes through stock progression color helpers

What is not clean enough yet:

- discipline is not yet respected deeply enough in the stock-facing visual/materialization translators
- synthetic source-profile generation still carries hardcoded color inputs
- the runtime distinguishes "element" and "loadout", but not a full "character"
- docs still contain historical RE notes that should not be treated as current design

## End State For Beta

Beta should mean:

- two or more participants can join the same run and remain visually correct
- each participant owns their own:
  - element
  - discipline
  - appearance choices
  - spell loadout
  - core inventory-facing combat state needed for the run
- the same participant model works for:
  - local human
  - Lua bot
  - remote human
- player and remote/bot render paths do not depend on ad hoc donor state
- the networking contract is stable enough for external testers
- the runtime tools are good enough to diagnose desyncs and visual mismatches quickly

Suggested beta target:

- 2 players minimum, 4 participants preferred
- one host, one remote client as the first external test bar
- stable hub -> run -> hub lifecycle
- no known participant-spawn or teardown crashes in the supported flow

## Key Architectural Clarification

### Save File vs Character Profile

The game does not need a full save file on disk just to render a wizard, but it does expect stock character data in one of two forms:

1. Preview/source-profile form
- used by the create/preview pipeline
- `ActorBuildRenderDescriptorFromSource (0x005E3080)` consumes a source profile object at `actor + 0x178`
- that source profile contains:
  - visual source type
  - selector bytes
  - cloth/trim color blocks

2. Progression/appearance-choice form
- used by player-start / gameplay startup
- save data is unpacked into gameplay-owned arrays and then applied to progression/runtime state through `PlayerAppearance_ApplyChoice`

For multiplayer, we should not think in terms of "load other players' save files".

We should think in terms of a canonical **character profile** that can be:

- loaded from a local save for the local player
- synthesized for bots
- replicated over the network for remote players
- translated locally into the stock game's preview/source-profile inputs and progression/appearance-choice inputs

## Existing Runtime Model

Do not build a second parallel participant model.

The repo already has:

- `ParticipantInfo`
- `ParticipantRuntimeInfo`
- `ParticipantKind`
- bot-facing create/update/snapshot APIs

So the intended direction is:

- extend the existing participant/runtime structs
- or add one contained character-profile subobject under them
- do not create a disconnected duplicate state model

## Recommended Character Model

Introduce one authoritative type:

```cpp
struct MultiplayerCharacterProfile {
    int element_id;
    int discipline_id;
    std::array<int, 4> appearance_choice_ids;
    BotLoadoutInfo loadout;
    int level;
    int primary_entry_index;
    int primary_combo_entry_index;
    std::array<int, 3> secondary_entry_indices;
    // later: inventory ids, cosmetics, naming, meta progression
};
```

Rules:

- `wizard_id` becomes a legacy MVP field and should be phased out
- rendering should come from `MultiplayerCharacterProfile`, not from a raw element enum
- bots and remote humans should both materialize from this same profile

Integration rule:

- `MultiplayerCharacterProfile` should live inside the existing participant/runtime ownership model rather than replacing it with a parallel system

## What Still Needs To Be Built

### Phase 0: Structural Prerequisites

Before expanding the abstraction layer, resolve the low-level issues that would otherwise invalidate every later phase.

Tasks:

- resolve independent render-node ownership for non-local participants
- resolve the current teardown / PuppetManager delete-path mismatch
- resolve lifecycle correctness across:
  - hub
  - create preview
  - testrun
  - return to hub
- define the authoritative participant registration/unregistration contract

Acceptance criteria:

- multiple non-local participants can exist without borrowing local-player render ownership
- spawn and despawn are stable
- hub -> run -> hub transitions do not corrupt or leak participant state
- destruction is no longer a known architectural hazard

April 14, 2026 note:

- the first concrete Phase 0 root cause was a phase violation
- gameplay-world mutations were being pumped from the D3D9 frame action pump instead of a safe gameplay update phase
- the fix moved gameplay-world action execution onto the local player tick while keeping hub/menu automation on the frame pump

Why this is Phase 0:

- profile work on top of broken participant ownership will just force a rewrite later
- remote players will multiply these problems, not hide them

### Track 1: Character/Profile Layer

This is the most important remaining upstream work.

Tasks:

- add `element_id` and `discipline_id` to the participant model
- add explicit appearance-choice storage
- add explicit participant scene-membership state:
  - `shared_hub`
  - `private_region`
  - `run`
- add conversion helpers:
  - create-screen selection -> `MultiplayerCharacterProfile`
  - local save/startup state -> `MultiplayerCharacterProfile`
  - `MultiplayerCharacterProfile` -> stock preview/source-profile input
  - `MultiplayerCharacterProfile` -> stock progression/appearance-choice input
- stop treating `wizard_id` as the full character identity

Acceptance criteria:

- a participant can be described without relying on save-file paths or UI actions
- the same profile can drive:
  - create preview
  - bot spawn
  - remote player materialization
- scene presence is explicit and not inferred from whichever non-arena scene the
  local player happens to be standing in

April 15, 2026 note:

- first scene-membership cutover is now in progress
- the old `home_region_index/home_region_type_id` heuristic has been replaced by
  an explicit scene-intent model in the bot/runtime path
- `sd.bots.create/update` now accept:
  - `scene = { kind = "shared_hub" | "private_region" | "run", region_index = ..., region_type_id = ... }`
- current live validation already proves:
  - hub bots can materialize with `scene.kind = SharedHub`
  - a hub-started run flips that participant to `scene.kind = Run`
  - rematerialization into `testrun` now follows the participant-owned scene
    intent instead of the old home-region heuristic
  - the current residual on this slice is narrower:
    - hub co-presence and hub -> run promotion are working
    - private-scene divergence (for example, host enters library while other
      participants stay in shared hub) still needs direct live validation
    - hub pathfinding is active on the same A* stack, but the tested waypoint
      currently produced zero displacement and needs a separate movement
      follow-up

### Track 2: Visual Materialization Cleanup

Current MVP uses a synthetic source-profile seam because bots do not have stock save-slot data.

That is acceptable for MVP, but before beta we should make the path cleaner.

Tasks:

- isolate the source-profile builder behind a typed `BuildSourceProfileFromCharacterProfile(...)`
- isolate the progression/appearance-choice builder behind a typed `ApplyCharacterProfileToProgression(...)`
- stop exposing raw element/color assumptions outside those builders
- validate that each public element maps correctly in:
  - create preview
  - hub/startup
  - `testrun`

Acceptance criteria:

- no user-facing render logic depends on scattered switch statements
- all element semantics are defined in one authoritative mapping layer
- bot and player use the same stock-facing builders

### Track 3: Discipline Support

Current code does not prove that discipline is fully represented in the bot render path.

Important nuance:

- discipline may or may not visibly change the robe
- but it is still part of the create/startup selection context
- we should model it explicitly even if the visual effect is subtle or nil

Tasks:

- verify whether discipline affects:
  - appearance choices
  - helper/attachment setup
  - loadout defaults
  - progression/runtime flags
- if discipline is non-visual, encode that clearly
- if discipline affects startup contracts, materialize it through the new profile layer

Acceptance criteria:

- the system can truthfully say whether discipline is:
  - visual
  - gameplay-only
  - both
- a bot/remote profile can carry discipline without ambiguity

### Track 4: Loadout And Inventory Ownership

Current runtime already has `BotLoadoutInfo`, but beta needs this pushed into the shared participant model.

Tasks:

- move loadout ownership under `MultiplayerCharacterProfile`
- define the minimum beta inventory contract:
  - primary skill
  - primary combo
  - secondary skill slots
  - consumables if needed for co-op feel
- ensure remote/bot participants do not inherit local player skill/inventory state

Acceptance criteria:

- two participants can have different elements and different spell loadouts
- remote/bot casting behavior is driven by their own profile, not local-player leakage

Dependency:

- this track should land with or after working bot/participant casting on owned loadouts

### Track 5: Participant Rail Completion

Current repo already points in the right direction: one participant rail for local, bot, and remote.

We need to finish that cutover.

Tasks:

- define `ParticipantKind`:
  - local human
  - Lua bot
  - remote human
- make `ParticipantState` own:
  - runtime actor binding
  - character profile
  - movement/combat runtime state
- keep input source separate from participant state:
  - local device
  - Lua controller
  - network input

Acceptance criteria:

- there is one creation/update/destruction rail for all participant kinds
- remote players do not get a separate special-case render system

### Track 6: Multiplayer Transport For Beta

This is the first real external-facing beta threshold.

Tasks:

- finalize a minimal transport contract for:
  - participant join/leave
  - profile sync
  - movement
  - cast events
  - disconnect/rejoin cleanup behavior
- keep host-authoritative enemy simulation
- keep client-owned local movement for responsiveness
- replicate remote participants as ordinary participants using the shared profile/materialization path

Acceptance criteria:

- host + one client can:
  - enter a run
  - see each other correctly
  - move independently
  - cast independently
  - kill enemies
  - stay visually correct throughout the run

Open design items that must be explicit before beta:

- what happens when a client disconnects mid-run
- whether reconnect is supported in beta or deferred
- how remote participant slots are reclaimed safely

### Track 7: Enemy Replication

This is large enough to deserve its own track.

Tasks:

- define host-authoritative enemy replication packets:
  - spawn
  - snapshot burst
  - event
  - despawn
- define client interpolation / correction behavior
- define hit-confirmation rules for remote spell casts
- define acceptable bandwidth/update-rate bounds for beta

Acceptance criteria:

- enemy motion remains believable under normal latency
- remote casts resolve consistently enough for co-op play
- the host does not need per-enemy-type bespoke replication logic

### Track 8: Tooling And Debuggability

Beta testing without diagnostics is wasted time.

Tasks:

- keep the Lua live-memory tooling first-class
- add typed helpers around the new character profile where needed
- add a small set of multiplayer diagnostics:
  - participant profile dump
  - participant render-state dump
  - transport snapshot / last packet state
  - player-vs-remote parity checks

Acceptance criteria:

- a visual mismatch or desync can be diagnosed from:
  - logs
  - Lua exec
  - one or two captured screenshots

## Proposed Delivery Phases

### Phase 0: Structural Stability

Goal:

- make participant ownership and lifecycle stable enough that later abstractions are built on real footing

Deliverables:

- render-node ownership fix
- stable registration/unregistration contract
- lifecycle validation across hub/create/run/return
- teardown-path validation

Exit criteria:

- no known structural participant-spawn or teardown blocker remains

### Phase A: Character Profile Cutover

Goal:
- replace `wizard_id`-centric bot rendering with `MultiplayerCharacterProfile`

Deliverables:
- new profile type
- parser/runtime support
- conversion helpers
- docs for profile semantics

Exit criteria:
- bots spawn from full profiles, not just `wizard_id`

### Phase B: Visual/Loadout Fidelity

Goal:
- ensure element + discipline + loadout are owned by the participant and render/play correctly

Deliverables:
- discipline validation and support
- loadout cutover under profile
- stock-facing preview/progression builders

Exit criteria:
- two different participant profiles can coexist without leaking visuals or loadouts

### Phase C: Remote Participant Rail

Goal:
- remote humans use the same participant/profile/materialization rail as bots

Deliverables:
- network profile replication
- remote participant creation/update/destruction
- movement/cast sync

Exit criteria:
- host and client can see each other's correct wizard presentation and combat behavior

### Phase D: Enemy Replication And Multiplayer Flow

Goal:

- finish the host/client gameplay loop for real runs

Deliverables:

- participant transport
- enemy replication
- disconnect handling
- host/client gameplay validation

Exit criteria:

- host and client can complete real co-op runs with stable player and enemy state

### Phase E: Beta Hardening

Goal:
- reduce crash/desync risk and make the build testable by non-authors

Deliverables:
- logging and diagnostics
- replay/test presets
- known-issues list
- beta checklist and test scenarios

Exit criteria:
- external testers can run co-op scenarios and report issues without needing live RE help

## Beta Checklist

Before calling the product beta-ready:

- participant ownership/lifecycle issues from Phase 0 are closed
- player and remote/bot participants can use different elements and both render correctly
- if discipline affects gameplay or appearance, it is modeled explicitly and tested
- character/profile sync is stable across connect/spawn/scene change/run start
- no local-player visual/loadout leakage into remote/bot participants
- join/leave/despawn are stable
- enemy replication is stable enough for real runs
- logging and live tooling are sufficient for support
- the roadmap assumptions about discipline are resolved explicitly

Suggested measurable beta targets:

- 2-player external test sessions complete without a participant render/state mismatch
- repeated hub -> run -> hub transitions complete without spawn or teardown corruption
- disconnect during a run has a defined, tested cleanup outcome
- at least one mixed-profile session is validated:
  - different elements
  - different loadouts
  - independent rendering and casts

## Explicit Non-Goals For This Beta

Do not block beta on these unless they become unavoidable:

- polished save editor UX
- full mod/plugin ABI redesign
- all content systems becoming network-replicated
- long-tail cosmetic customization beyond what the stock game already supports cleanly

## Immediate Next Step

Start Phase 0 and Track 1 in parallel where safe.

Concrete first cut:

1. Close the participant ownership/lifecycle blocker:
   - render-node ownership
   - stable teardown path
   - scene-transition contract
2. Add `element_id` and `discipline_id` to the participant API.
3. Introduce `MultiplayerCharacterProfile` under the existing participant/runtime model.
4. Move current `wizard_id` mapping logic behind profile conversion helpers.
5. Treat current `wizard_id` as legacy compatibility only until the full cutover is complete.

That is the smallest sequence that moves the system from MVP hacks toward a multiplayer-clean architecture without building on known broken ownership rules.
