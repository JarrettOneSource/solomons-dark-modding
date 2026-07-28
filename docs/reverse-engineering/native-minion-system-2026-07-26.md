# Native minion system reverse engineering

Date: 2026-07-26

## Scope and conclusion

This note is the Phase 1 characterization required before changing multiplayer
behavior for issue #53. It covers the Earth-class Raise Golem path in detail
and establishes the native shapes which a general minion replication seam must
support.

The central finding is that Solomon Dark does not have one native `Minion`
base class. Player-allied summons are heterogeneous stock actors:

- Golem (`0x07F4`) derives through `GoodGuy` and `Puppet`;
- Leviathan (`0x07F2`) derives directly through `Puppet`;
- Good Imp (`0x03ED`) is an enemy-family Imp converted into a temporary ally;
- Wizard clones remain player-family (`0x0001`) `PlayerWizard` actors and are
  not minions.

The durable common identity is not a raw summoner pointer. Native actors carry
an `ActorWorld` plus peer-local actor-group/world-slot coordinates. Golem AI
and damage authority are hard-gated on actor group zero. Consequently, replaying
the stock summon spell on every peer creates independently simulated local
actors; it does not create one replicated minion. The machine on which a Golem
was created runs its AI and damage, while the other copy is a passive observer.

The multiplayer framework must therefore own minion identity, owner identity,
simulation authority, state, health, and lifecycle. Stock spell replay may
remain a low-latency materialization/presentation path, but it cannot be the
authority model.

No product behavior was changed while producing this note.

## Evidence

All live runs used isolated `mini` instances on ports `48511` and `48512`, with
audio disabled, exact launcher-returned PID ownership, and exact staged
executable validation. The test did not kill or inspect unrelated game
processes.

Primary evidence:

- `/mnt/d/codex-evidence/minion-sync-20260726/baseline/result.json`
- `/mnt/d/codex-evidence/minion-sync-20260726/baseline/summary.json`
- `/mnt/d/codex-evidence/minion-sync-20260726/baseline/host_owned/contact-host.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/baseline/host_owned/contact-client.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/baseline/client_owned/contact-host.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/baseline/client_owned/contact-client.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/native-golem-field-transition-report.txt`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/mini-transport-log-analysis.txt`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/mini-focused-network-events.txt`

Fresh headless Ghidra output:

- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/ghidra-golem-core.log`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/ghidra-golem-dependencies.log`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/ghidra-actorworld-target-damage.log`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/ghidra-minion-taxonomy.log`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/golem-tick-decompile.txt`
- `/mnt/d/codex-evidence/minion-sync-20260726/investigation/golem-contact-death-decompile.txt`

The analysis used the repository's existing Ghidra project for the supported
retail executable. Addresses below are image-base addresses and must continue
to come from the verified binary-layout contract at runtime.

## Loopback symptom matrix

The matrix summoned a levelled Raise Golem at a frozen stock enemy and sampled
both processes for roughly 28 seconds. Both-peer contact sheets were inspected
at native game scale; the Golem assembled and visibly articulated in every
cell.

| Cast owner | Host existence / presentation | Client existence / presentation | Maximum peer position error | Enemy damage observed on each peer | Result |
| --- | --- | --- | ---: | ---: | --- |
| Host | one `0x07F4`, visible and articulating | one `0x07F4`, visible and articulating | `0.810420` | `147.022949` / `147.022949` | HP converged, host-local Golem was combat authority |
| Client | one `0x07F4`, visible and articulating | one `0x07F4`, visible and articulating | `5.952225` | `10.623047` / `10.623047` | HP converged, client-local Golem was combat authority |

Important observations:

- Clean loopback did not reproduce the owner's WAN report as complete
  invisibility. That does not invalidate the report: stock cast replay happened
  to materialize a peer-local Golem on both machines in this run.
- The direction-dependent damage is severe. The identical test geometry and
  Golem stats produced about fourteen times more damage for host-origin than
  client-origin.
- Enemy HP eventually agreed exactly in both directions. Host-origin native
  contact mutated host state directly. Client-origin native contact produced
  two generic enemy-damage claims (`5.918457` and `4.704590`) which the host
  accepted and corrected back to the client.
- Real Golem HP was `100/100` on both machines. The generic replicated world
  snapshot published `0/0`, proving that the existing actor extractor reads
  the wrong health layout for this class.
- The generic `anim_drive_state` remained zero in every sample even while the
  Golem visibly assembled, walked, turned, and attacked. Golem presentation is
  articulated native state, not the player/enemy animation-drive byte.
- The maximum age skew was ten ticks. Age proximity and matching visuals came
  from near-simultaneous independent stock ticks, not authoritative animation
  replication.
- The host assigned network IDs `281543696187393` and
  `281543696187394`. The same logical summon was actor group zero on its owner
  machine and group one on the observer machine. Actor-group coordinates are
  therefore peer-local and cannot be used as wire owner identity.
- The harness explicitly requested retirement on both peers and both copies
  disappeared. That only proves stock teardown can be requested safely; it
  does not prove authority-driven despawn or an omission tombstone.

### Live authority field transition

The field-transition trace sampled native state on both Golem copies without
writing it:

- for a host-origin Golem, the host group-zero actor acquired target `(0, 1)`,
  set its attack cooldown to `1200`, and changed gait/attack fields; the client
  group-one actor kept target `(255, -1)`, cooldown `0`, and idle gait state;
- for a client-origin Golem, those roles reversed.

This is direct runtime proof of the group-zero branch recovered statically. A
transform snapshot can reduce visual drift, but it cannot make a passive
observer copy perform authoritative target selection, attack emission, or
damage.

## Native taxonomy

### Golem

- factory/native type: `0x07F4` (`2036`)
- allocation size: `0x240`
- RTTI class: `Golem`
- vtable: `0x0079DE94`
- constructor: `0x005F57E0`
- initialization: `0x005F5B40`
- destructor cleanup: `0x005F5A20`
- tick: `0x00615CD0`
- contact/damage-in: `0x00607F60`
- death: `0x00619730`
- draw: `0x00617820`

The constructor calls `GoodGuy` construction at `0x0052A410`; `GoodGuy` calls
the `Puppet` constructor at `0x006287D0`. Golem is therefore neither:

- player-family type `0x0001`;
- the known enemy object types `{2012, 5010}`; nor
- `RegisteredGameNpc` / `GameNPC` type `0x1397`.

The constructor sets allied actor flag `0x800` at actor `+0x14` and inserts
the object in the gameplay hostile-target candidate list rooted at
`gameplay + 0x1388`. Its destructor removes it from that list.

### Leviathan

- factory/native type: `0x07F2`
- constructor: `0x005E8FB0`
- destructor: `0x005F4670`
- tick: `0x006145D0`

Leviathan is a direct `Puppet`-derived player summon with actor flag `0x200`.
It is a timed, three-phase emitter of Ether Bolt (`0x07F3`), rather than a
persistent `GoodGuy` melee actor. It does not share the Golem candidate-list
lifecycle.

### Good Imp

- factory/native type: `0x03ED`
- constructor: `0x00529FE0`
- initialization: `0x0052A050`
- tick: `0x0052C1A0`
- conversion path: Ember tick `0x0060D7E0`

Good Imp retains an Imp/`Badguy` inheritance shape and is converted into a
temporary ally by Ember. Creation is itself group-zero gated. Treating all
minions as `GoodGuy`, or treating them all as non-enemy actors, would therefore
be incorrect.

The constructor seeds a 300-tick lifetime at `+0x23C`. The tick resolves its
target from the durable actor-world group/slot pair at `+0x240/+0x242`, runs
the inherited Imp behavior at `0x00485DC0`, decrements the lifetime (twice
while its target is absent), and requests native retirement through virtual
slot `+0x18` when it expires. Its terminal group-zero branch creates the
native `0x07E3` effect. Good Imp therefore needs the same host-only native-tick
policy and explicit terminal replication as the other minion descriptors,
despite having a different inheritance family and lifetime model.

### Wizard clones and registered NPCs

`WizardCloneFromSourceActor` creates type-one player-family actors used for
participant materialization. Their ownership, health, animation, and death
contract is the participant protocol, not the minion protocol.

Type `0x1397` is the separate registered game-NPC/factory source actor shape.
It is not a summon superclass.

## Raise Golem creation and ownership

Raise Golem is spell/skill entry `0x2D` (`45`) in the secondary-skill
dispatcher at `0x0054CC50`.

The dispatch does the following:

1. validates the skill resource/mana state;
2. reads progression bit `caster progression + 0x878 & 0x08`;
3. enumerates the summoner's `ActorWorld` scene list at
   `actor_world + 0x318` / `+0x324`;
4. matches existing `0x07F4` actors with the same actor-group byte;
5. without the progression bit, kills every matching existing Golem;
6. with the bit, keeps a cap of two by killing the matching Golem with lower
   current HP at `+0x170`;
7. collision-adjusts the cursor-world placement;
8. invokes the object factory at `0x005B7080` for type `0x07F4`;
9. seeds position, heading, caster flavor byte, current/max HP, both damage
   values, Iron, and reflect; and
10. returns the new actor to the outer dispatcher for normal `ActorWorld`
    registration.

The cap is therefore one or two Golems depending on progression. It is scoped
by peer-local actor group inside the current `ActorWorld`, not by a durable
network owner ID.

### Native owner representation

Actor registration at `0x0063F6D0` writes:

- `actor + 0x58`: `ActorWorld`;
- `actor + 0x5C`: actor group;
- `actor + 0x5E`: world slot; and
- the reverse bucket entry rooted at
  `actor_world + 0x500 + (group * 0x800 + slot) * 4`.

Golem has no durable raw `PlayerWizard*` owner field. It resolves its summoner
through the gameplay player table rooted at `gameplay + 0x1358`, indexed by
actor group. The apparent "owner address" in the live probe was the process's
`ActorWorld`, not a wizard object.

This makes native group/slot useful only inside one process. Multiplayer must
store the summoner's participant ID in a sidecar and on the wire, then resolve
that participant to the peer-local actor-group/player entry only at a native
call boundary.

## Gameplay arrays and references

Golem participates in several different stock containers:

- `ActorWorld + 0x318/+0x324`: scene actor list used by the Raise Golem cap
  scan;
- `ActorWorld + 0x500 + group/slot index`: authoritative per-world actor
  bucket installed during registration;
- `gameplay + 0x1358 + group * 4`: summoner/player table used for following;
- `gameplay + 0x1388`: hostile-target candidate `PointerList` into which the
  `GoodGuy` constructor inserts the Golem and from which the destructor removes
  it.

The current Golem target is not retained as a durable raw pointer. Its
identity is actor group/world slot at `Golem + 0x164/+0x166`, resolved through
the current world bucket. The state near `+0x168` is target/steering validity.

Destructor helper `0x005F5C10` walks hostile actors, clears references whose
current target is the dying Golem, and marks those target states invalid.
Bypassing native teardown can therefore leave stock AI with dangling target
references. Authority-driven retirement must enter the class's native
lifecycle rather than merely unregistering its world bucket.

## Golem AI, animation, and lifetime

`Golem::Tick` at `0x00615CD0` first calls the `Puppet` base tick. Golem then
has two broad phases:

- assembly while `Golem + 0x208 < 201`, with milestones around ages
  `0`, `50`, `100`, and `200` which construct its articulated body;
- full follow, target acquisition, gait, and attack behavior after assembly.

Recovered Golem-specific state includes:

| Offset | Meaning |
| --- | --- |
| `+0x164/+0x166` | current target actor group/world slot |
| `+0x168` | steering heading/sentinel (`float`, `-1.0` means no turn requested) |
| `+0x16C` | steering angular step (`float`) |
| `+0x170/+0x174` | current/max HP |
| `+0x178` | target-resolution poll timer (`int32`, reset to `50`) |
| `+0x17C` | locomotion/interpolation sample counter (`int32`, consumed modulo `100`) |
| `+0x180..+0x1D4` | articulated-body interpolation points and phase accumulators |
| `+0x1E8/+0x1EC` | primary/secondary gait pose lanes (`int32`) |
| `+0x1F0/+0x1F4` | primary/secondary attack damage |
| `+0x1F8` | attack timer |
| `+0x200` | attack cooldown |
| `+0x208` | assembly/native age |
| `+0x210` | Iron |
| `+0x214` | reflect ratio |
| `+0x218` | ambient boulder/effect timer (`int32`, initialized to `300`, then reset to `100`) |
| `+0x21C` | cyclic animation phase (`float`) |
| `+0x220/+0x224` | randomized visual phase values (`float`) |
| `+0x228..+0x23C` | embedded articulated-part list |

Target acquisition and attack-driving branches require `actor + 0x5C == 0`.
This is the stock authority boundary behind the loopback directionality.

The field types above are not inferred from nearby values. In
`Golem::Tick`, `+0x178` is decremented as an integer and reset to `50`,
`+0x17C` is incremented as an integer and reduced modulo `100`, and `+0x21C`
is advanced and wrapped with floating-point operations. The loopback probe
independently observed `+0x21C` bit patterns `0x40DCCC4B` and `0x40D332B2`,
which decode to animation phases `6.899938` and `6.599938`, respectively.
Treating the first two fields as motion floats or the last field as an integer
therefore corrupts the replication contract.

Golem has no natural expiry timer. It persists until one of:

- HP death;
- Raise Golem cap eviction by a later cast;
- scene/`ActorWorld` teardown; or
- an external retirement request.

`Golem::Draw` at `0x00617820` renders articulated parts from Golem atlas
records, including records in the range `1..208`. The generic actor
`anim_drive_state` is not a sufficient presentation contract. A correct
replication seam must either publish Golem's semantic assembly/gait/attack
state or publish a compact, class-specific articulated pose derived from it.

## Damage dealt by Golem

When the attack state reaches counter `0x25`, Golem creates a Knockback actor
of type `0x07E9`. It seeds that effect from Golem damage fields
`+0x1F0/+0x1F4` and attaches it to the native attack.

Knockback tick at `0x00600220` dispatches contact damage only when its actor
group byte is zero. It resolves the source through
`gameplay + 0x1358 + group * 4`.

This creates two distinct beta.18 paths:

- a host-origin Golem is group zero on the host and directly mutates
  authoritative enemy HP;
- a client-origin Golem is group zero on the client, so the client performs
  contact locally and the generic client-enemy-damage seam in
  `client_enemy_damage_sync.inl` submits the observed HP delta as claims.

The generic claim seam can converge a delta after client-native contact. It
does not make minion AI host authoritative, cannot recover a missed remote
spawn, and does not remove the direction-dependent simulation.

## Damage received and native death

`Golem::Contact` at `0x00607F60` ignores contact until assembly age
`+0x208 >= 400`. It then subtracts the process-global primary and secondary
contact components at `0x0081C6E8` and `0x0081C6EC` from Golem HP at
`+0x170`.

If reflect at `+0x214` is positive, the source is valid, the source has the
required actor flag, and range permits, Golem creates a new contact from
itself back to the source for the reflected primary-damage fraction.

When HP crosses zero, contact runs modifier cleanup and arms the native death
countdown at `+0x94`. The next `Puppet` base tick dispatches the Golem death
virtual. `Golem::Death` at `0x00619730` calls the standard retirement helper
at `0x00622FD0`; that reaches the object retirement virtual at
`0x00401FD0`, marks pending removal at object `+0x05`, clears target links,
and emits Golem fragments/unbind presentation. Destructor cleanup then removes
the candidate-list entry and clears hostile references.

Beta.18 publishes Golem health as `0/0` because its generic scene actor
extractor does not use `+0x170/+0x174`. Both peer-local copies can also receive
stock contact independently. There is no host-owned Golem-health correction,
incoming-damage gate, or minion death transaction.

## What beta.18 currently does

Protocol 85 has a `WorldActorSnapshotFlagPlayerCreated` bit and recognizes
Raise Golem type `0x07F4` as a replicated player-created run actor. The target
resolver separately recognizes `0x03ED`, `0x07F2`, and `0x07F4` as
player-owned target types; that broader target taxonomy is not a minion
lifecycle implementation.

For Golem, the current flow is:

1. the caster runs the stock secondary dispatch;
2. the cast packet causes the remote peer to replay the same stock dispatch;
3. each machine therefore owns a separate native Golem;
4. host world snapshots assign one network actor ID and nearest-match/bind the
   replayed peer-local Golem;
5. reconciliation applies fresh transform/heading writes; and
6. on authoritative omission, reconciliation explicitly unbinds the Golem
   without retiring it, assuming stock lifetime will finish independently.

The omission behavior is intentional in the current source comment because raw
unregistration would bypass native teardown. It also means authoritative
despawn/expiry is not implemented. There is no owner participant ID, class
descriptor, real health, class animation state, authoritative incoming damage,
or lifecycle tombstone in the current Golem snapshot.

## Required framework authority model

The foundational seam should model `NativeMinion` as a multiplayer concept
over native class descriptors, not invent a false stock inheritance
relationship.

### Registry and wire identity

Each supported descriptor must provide:

- native type recognition;
- stock materialization and native teardown entrypoints;
- owner resolution/projection hooks;
- authority-tick and observer-tick policy;
- class-specific capture/apply functions;
- health and damage-contact policy; and
- presentation state requirements.

Every replicated minion needs:

- stable `network_actor_id`;
- durable owner participant ID;
- native type/class kind;
- authoritative transform and heading;
- authoritative health where the class is damageable;
- class-specific semantic/presentation state; and
- explicit lifecycle state and terminal reason.

The initial registry must describe Golem, Leviathan, and Good Imp even if
Golem is the first fully exercised behavior. A switch which recognizes only
`0x07F4` and embeds Golem offsets throughout the transport is not the required
class seam.

### Simulation and damage authority

The session host is the sole minion simulation and damage authority:

- host-created and client-created minions must both run their stock AI/damage
  path on the host;
- observers may run presentation-only native state but must not acquire
  independent targets, create authoritative attack contacts, or apply incoming
  damage;
- remote-owner native actor-group coordinates must be projected only at a
  narrow stock call boundary while durable owner identity remains the
  participant ID;
- damage Golems deal must originate once on the host and flow through the
  existing authoritative enemy snapshot/correction path;
- Golem incoming contact and reflected damage must execute once on the host;
  and
- real Golem HP/max HP and terminal state must be published to both peers.

The framework must not synthesize a second damage scalar to compensate for
missed stock AI. It must run the stock behavior once under the correct
authority and replicate the resulting exact state.

### Spawn, presentation, and recovery

Stock cast replay may remain the normal fast path because it preserves native
audio/visual construction and minimizes first-frame latency. It is not
sufficient by itself:

- an authoritative snapshot must materialize a missing minion through the
  class descriptor's native factory path;
- nearest matching must include owner participant identity, native type, and
  creation epoch rather than type/proximity alone;
- observer state must be reconciled from the host after binding;
- Golem assembly, gait, attack, and articulated presentation must be driven
  from class-specific authoritative state rather than generic
  `anim_drive_state`; and
- duplicate peer-local stock objects must be resolved through native teardown.

### Lifecycle

Authoritative lifecycle must distinguish at least:

- HP death;
- recast-cap eviction;
- timed expiry where a minion class has one;
- owner death;
- owner disconnect;
- scene exit; and
- explicit framework retirement.

For this implementation, owner death and disconnect should immediately retire
owned minions through their native teardown path on the host, publish a
terminal lifecycle record, and drive the same teardown on observers. This
prevents orphaned AI and provides deterministic test semantics. Scene exit may
clear the whole registry only after the run epoch changes.

An omission is not a safe tombstone. The host must retain a terminal record
long enough for every peer to observe it, following the same ordering lesson
as remote actor materialization and death presentation: lifecycle and
presentation are a transaction which must survive late materialization.

## Required verification

Focused regression coverage must pin:

- registry recognition and per-class descriptor routing for Golem, Leviathan,
  and Good Imp;
- durable owner participant identity independent of peer-local actor group;
- host authority for host-origin and client-origin Golem AI;
- observer suppression for attack/contact authority;
- real Golem HP/max HP capture and exact correction;
- class-specific Golem assembly/animation state capture/apply;
- missing-spawn materialization and duplicate resolution;
- HP death, recast eviction, explicit despawn, and late tombstone handling;
- owner death and disconnect cleanup;
- exact enemy-damage convergence in both cast directions; and
- exact incoming Golem-damage convergence.

Live acceptance must repeat the two-cell matrix and prove on both peers:
existence, position, visible assembly/animation, combat effectiveness, exact
enemy HP convergence, exact minion HP convergence, and synchronized terminal
absence. Both-peer screenshots must be retained with the machine-readable
timeline.

## Phase 2 implementation and acceptance

Phase 2 implements protocol 87 as a descriptor-backed native-minion authority
lane. The registry describes Good Imp, Leviathan, and Golem without claiming a
shared stock superclass. Golem is the first class with complete live behavior
coverage; Good Imp and Leviathan have typed capture/apply state and lifecycle
hooks ready for class-specific acceptance.

The implementation follows the authority model above:

- the host projects a minion and its durable participant owner into stock
  gameplay slot zero only around the native minion tick/contact boundary;
- clients keep their native copies in observer presentation mode and reject
  Golem contact damage;
- Raise Golem factory calls are tagged inside the exact skill-45 dispatch
  scope, so remote-cast replay cannot misidentify a client-owned Golem as
  host-owned while player globals are temporarily projected;
- protocol state carries owner participant ID, native type, real Golem HP,
  assembly age, gait/attack timers, animation phase, damage fields, and
  lifecycle state;
- the identity snapshot can materialize a missing observer through the native
  factory/register path, while matching uses native type, owner, and native-age
  proximity;
- terminal tombstones distinguish native death, expiry, recast replacement,
  owner death, owner disconnect, explicit retirement, and scene teardown;
- owner death retires host-owned minions immediately at the accepted native
  death transition, including the host-local player whose actor tick has
  stopped; and
- Steam disconnect events reuse participant teardown, while the development
  local-UDP transport now detects five seconds of packet silence after draining
  queued datagrams and runs the same teardown. The static configured endpoint
  remains available for a later local-UDP reconnect.

Final post-rebase live acceptance is recorded at:

- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/result.json`
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/acceptance-metrics.json`
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/verifier.log`
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/host_owned/host.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/host_owned/client.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/client_owned/host.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/client_owned/client.png`
- `/mnt/d/codex-evidence/minion-sync-20260726/live18-post-final-rebase/runtime/`

Both directional screenshot pairs were inspected at their native
`1600x900` resolution. Each peer visibly renders the same assembled,
articulated Golem at the same combat fixture. The harness used the
presentation-local camera seam only for the capture, verified both native
camera centers at the same world point, and released the focus before
lifecycle testing. Machine-readable results were:

| Cast owner | Stable owner ID on both peers | Maximum position error | Exact enemy HP after Golem damage | Exact Golem HP after host contact |
| --- | ---: | ---: | ---: | ---: |
| Host | `2305843009213698049` | `0.749943` | `4995.8481445312` / `4995.8481445312` | `92.75` / `92.75` |
| Client | `2305843009213698050` | `0.750004` | `4994.986328125` / `4994.986328125` | `92.75` / `92.75` |

The client observer contact probe left Golem HP exactly `100/100`; the same
`7.25` contact on the host authority converged to `92.75/92.75`. The harness
also removed an observer copy and proved authoritative rematerialization,
replaced a Golem with terminal reason `3`, delivered a terminal through a
`2400` ms exact-process suspension and explicit-retirement reason `6`, killed
a Golem through its native contact/death path with reason `1`, retired a
host-local owner's Golem on native player death with reason `4` on both peers,
and retired a client-owned Golem after exact client-process termination with
reason `5`. The local-UDP log records `silent_ms=5000` before disconnect
teardown. Both launches reported `audioDisabled=true`; the final staged crash
logs for both peers were empty.

## Cross-agent note for issue #54

The clean loopback trace provides no evidence that an unreplicated Golem
causes a transport retry storm:

- repeated `[bots] queued sync deferred` lines occurred while participant
  scene identity was settling before either summon;
- the high-frequency foundation-status lines were induced by the harness's
  own polling probes;
- after host-origin summon there was ordinary snapshot traffic and no
  client-damage claim loop;
- after client-origin summon there were exactly two accepted enemy-damage
  claims, not rejects or retries; and
- observed `250`, `422`, and `453` ms app-thread gaps occurred during
  scene/UI transitions before the Golem casts.

Therefore this run does not support minion-induced sync spam as the root cause
of issue #54. It also cannot exclude a WAN-only timing or loss path. The
directional dual-simulation defect and omission-without-tombstone behavior are
real and should be compared against the sibling WAN lag trace, but external
machine load must not be attributed to the product without matching
post-summon evidence.
