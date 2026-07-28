# Multiplayer local-player hit feedback

Date: 2026-07-28

Investigation base: `877339586b2659698ec7c79dae8d989c02150a47`

## Owner doctrine

Damage authority and hit presentation are different facts.

The authority remains the only machine that computes final multiplayer damage.
The owning client must not run stock damage application a second time merely to
obtain presentation. Instead, the authority publishes one explicit presentation
event for each completed, nonlethal damage event against a remote human
participant. The owner consumes that event once and reproduces only the native
presentation tail.

Consequences:

- HP snapshots and vitals corrections are state convergence, not hit events.
- A lower replicated HP value must never, by itself, synthesize feedback.
- A native damage call that did not reduce HP does not create an event.
- Healing does not create an event.
- The authority's own local player already ran the stock presentation tail, so
  the framework does not replay it there.
- Lethal owner correction continues through the existing stock death replay.
  It does not also receive a nonlethal hit-presentation event.
- Lua-brain/synthetic bot actors are not local-player presentation targets.

This rules out the tempting band-aids: calling stock damage with a duplicate or
zero-valued context on the owner, watching periodic HP snapshots, or adding a
special case to one enemy packet.

## Native local-player path

### Function and data map

| Role | Preferred address | Finding |
| --- | ---: | --- |
| `Player` constructor | `0x0052A500` | Constructs the `0x398`-byte Player object, installs `Player::vftable`, initializes Player fields, and registers every Player-family actor through the gameplay object's virtual `+0x10` call. It does not establish a unique local-player singleton. |
| `PlayerActorTick` | `0x00548B00` | Player-family per-actor tick. The loader detours this as `HookPlayerActorTick`, but ordinary hit feedback is not dispatched here. |
| incoming Player magic damage | `0x00548150` | Player vtable damage entry. It resolves the active context/resistance/source-facing work and calls the common Player damage resolver. |
| common Player damage resolver | `0x0052F540` | Resolves damage lanes and defenses, applies actor-owned HP, then runs the ordinary hit sound and local-only red-edge presentation inline. |
| actor HP mutation | `0x0052AC80` | Applies the final HP delta to the target Player's own progression/stat pool and arms terminal behavior when appropriate. |
| local damage-history record | `0x00528F10` | Records final damage only when the target equals `gameplay + 0x1358`. This is bookkeeping, not the red/sound presentation. |
| generic damage dispatcher | `0x0063E7D0` | Validates the active target and dispatches its vtable slot `+0x4C`. |
| damage-context reset | `0x006246F0` | Releases/resets the active native damage context and restores the hit-reaction defaults. |
| generic Actor hit-reaction latch | `0x00627F80` | For positive primary/secondary damage, arms the target Actor's two decaying hit fields and copies the context's intensity/color parameters. It then dispatches registered Actor damage reactions through `0x00625150`. |
| generic Actor tick | `0x00624AC0` | Subtracts `0.05` per tick from both Actor hit fields at `+0x78` and `+0x80`, clamping each to zero. |
| generic Actor render | `0x00624B40` | Uses `Actor + 0x78` and `Actor + 0x7C` for the stock red Actor/sprite overlay. |
| `Sound::Play` | `0x00407B70` | Receives the selected `Wizard_Ouch` `Sound` object and final gain. |
| inclusive integer random | `0x00448450` | Returns an integer in `[minimum, maximum]`; the sound gate uses `[20, 60]`. |
| native integer RNG | `0x00401170` | Selects one of three ouch sounds and supplies the red/cooldown jitter. |
| presentation-block predicate | `0x00462090` | Returns blocked when the object at `0x008199F8` has a non-null field at `+0x04` or a positive count at `+0x24`. |
| Arena tick | `0x0046E570` | Decays `Arena + 0x8EBC` by `0.007` per tick and clamps it to zero. |
| Arena render | `0x0046EC80` | Draws the four red screen-edge quads with opacity `local Actor + 0x78` multiplied by `Arena + 0x8EBC`; a nonzero Arena scalar alone is not visible. |

The active context globals used by this path are:

| Preferred address | Meaning |
| ---: | --- |
| `0x0081C6D8` | damage target |
| `0x0081C6E0` | damage source |
| `0x0081C6E4` | damage flags |
| `0x0081C6E8` | primary/projectile damage lane |
| `0x0081C6EC` | secondary/magic damage lane |
| `0x0081C6F0` | special/heal lane |
| `0x0081C6F8` | Actor hit-overlay intensity; context reset default `1.0` |
| `0x0081C6FC..0x0081C708` | Actor hit-overlay RGBA; context reset default `(0.65, 0, 0, 1)` |
| `0x0081C264` | gameplay runtime pointer |
| `0x0081F658` | stock frame/tick counter |
| `0x00807B58` | shared hit-presentation deadline |
| `0x008199D8` | compiled audio registry pointer |
| `0x00818B08` | active native RNG pointer |

### Exact ordinary-hit sequence

For an incoming Player hit, `0x00548150` reaches `0x0052F540`.
`0x0052F540` first rejects disabled/terminal actors (`actor + 0x160` and
`actor + 0x94` guards), resolves the context through resistance and modifier
lanes, and computes final damage. It calls `0x0052AC80` with the negative final
delta. The HP read and write are actor-relative: an actor with a private
progression pointer at `actor + 0x200` uses it; otherwise stock resolves the
actor's gameplay slot and its associated progression pool.

There is no independent positive minimum-damage threshold in the presentation
tail. Upstream immunity, defense, absorption, cancellation, and terminal guards
can make the final HP delta zero. The ordinary ouch/red tail follows only when
actor-owned HP actually fell. The shared presentation deadline is not an
invulnerability window: it throttles an ouch request and is re-armed by the red
effect, while damage application itself still runs.

Before HP mutation, the common resolver calls `0x00627F80` at
`0x0052FDF1` after defense/lane resolution. A separate conditional path calls
the same helper at `0x0052F9FF`. When resolved primary plus secondary damage is
positive, the helper writes:

```text
Actor + 0x78 = 1.0
Actor + 0x80 = (damage_flags & 0x08) ? 0.0 : 1.0
Actor + 0x7C = context hit-overlay intensity
Actor + 0x84..0x90 = context hit-overlay RGBA
```

The primary and secondary latches do not scale with damage magnitude.
`0x00624AC0` decays each by exactly `0.05` per Actor tick. The base Actor
renderer uses the primary latch and intensity for the red Actor/sprite
reaction. The Arena renderer independently multiplies the same primary latch
by the Arena red-edge scalar for its full-screen quads. Thus the Actor latch is
part of the native screen reaction, not merely an enemy sprite detail.

`0x00627F80` also invokes `0x00625150`, which dispatches registered Actor
damage reactions. That dispatch is part of the authority-side damage
transaction, not an owner-only presentation call: the authority already runs
it against its materialized remote actor. Re-running the dispatcher on the
owner would duplicate arbitrary gameplay/mod reactions. Owner replay must copy
the resolved Actor presentation fields but must not invoke this dispatcher or
reconstruct an active damage context.

The helper's positive-lane condition is independent of local-player identity
and of the later HP comparison. The framework's replicated event remains more
selective: it represents a completed hit only when actor-owned HP actually
fell. This prevents blocked/cancelled attempts from becoming network hit
events while preserving all presentation parameters for damage that landed.

After HP mutation, the ordinary ouch block requires all of:

1. the special/heal lane at `0x0081C6F0` is exactly zero;
2. actor-owned post-hit HP is lower than the saved pre-hit HP;
3. the actor terminal byte at `+0x94` is zero;
4. primary plus secondary damage is positive;
5. current tick `0x0081F658` is later than deadline `0x00807B58`; and
6. `0x00462090(0x008199F8)` says presentation is not blocked.

When eligible, stock:

1. selects an inclusive `[20, 60]` delay;
2. computes `health_factor = clamp((post_hp - 25) / 20, 0, 1)`;
3. computes `health_gain = (1 - health_factor) * 0.75 + 0.25`;
4. passes the target actor position (`actor + 0x18/+0x1C`) to the target
   world/Arena virtual at vtable `+0x104`;
5. multiplies that spatial result by `health_gain`;
6. chooses RNG index `0..2`; and
7. calls `0x00407B70` on compiled-registry object
   `registry + 0x2620 + index * 0x2C`.

Those objects are registry indices 228 through 230:

- `sounds/Wizard_Ouch/SAY_OUCH1.wav`
- `sounds/Wizard_Ouch/SAY_OUCH2.wav`
- `sounds/Wizard_Ouch/SAY_OUCH3.wav`

The native block also scales its initial deadline by the clamped health factor.
The later red-effect block re-arms the same deadline, so low-health rapid hits
retain stock throttling even though the ouch block's intermediate deadline can
collapse toward zero.

The red-edge block is separate from the ouch gate. It requires:

1. target actor identity exactly equals `*(gameplay + 0x1358)`;
2. special/heal lane is zero; and
3. actor-owned post-hit HP is below `30.0`.

It then deliberately reads slot-0 progression HP and writes:

```text
Arena.red_edge_alpha = (1 - post_hp / 40) * 0.7
```

to the target actor's world/Arena at `actor + 0x58`, offset `+0x8EBC`.
Finally it sets the shared presentation deadline to:

```text
current_tick + 20 + random(0, 11)
```

where the native integer RNG call has an exclusive upper bound for this direct
form. `0x0046E570` subtracts `0.007` each Arena tick. `0x0046EC80` multiplies
the field by the local Actor's decaying `+0x78` latch and draws the red
edge/vignette quads.

No ordinary-hit camera impulse or separate HUD animation occurs in this path.
The other local-only action is the `0x00528F10` damage-history record. Direction
does not feed the Actor latch, the red-edge magnitude, or the ouch selection.
Source/target position affects only the sound's world attenuation. The
full-screen red magnitude and base ouch gain are functions of post-hit HP, not
raw damage magnitude; the Actor reaction starts at `1.0` and uses the
context-resolved intensity/color.

If native HP mutation enters its terminal path, it returns before the ordinary
nonlethal tail. Multiplayer already handles an owner-side lethal correction by
priming positive HP and invoking the stock lethal path once. A replicated
nonlethal presentation replay must therefore exclude lethal events.

### Local-player identity and the alias trap

`0x0081D5BC` is named `local_player_actor` in the binary layout, but it is not a
usable identity source for this work. In the two live processes it read null
while:

- `sd.player.get_state().actor_address`, and
- `*( *(0x0081C264) + 0x1358 )`

matched the actual local actor on each process.

The clean pair observed:

| Process | actual local actor | remote actor | `0x0081D5BC` | `gameplay + 0x1358` |
| --- | ---: | ---: | ---: | ---: |
| host | `313649504` | `324977368` | `0` | `313649504` |
| client B | `283209944` | `284950296` | `0` | `283209944` |

This agrees with the constructor: `0x0052A500` registers every Player-family
actor and cannot, by itself, distinguish the process-local player. Loader code
must use `TryGetPlayerState`/the resolved slot-0 gameplay actor for local
identity and must read the target actor's own progression pool for remote
authority observations. `kLocalPlayerActorGlobal` must not be used to decide
which participant was damaged.

## Actual multiplayer damage flow

### Static flow

The current host-authoritative path is:

1. A hit reaches `HookPlayerActorMagicDamage` in
   `mod_loader_gameplay/gameplay_hooks/player_damage_authority_hook.inl`.
2. On a client, ordinary local native damage is rejected unless
   `g_client_owner_authorized_damage_target` names that actor. This prevents
   owner simulation from competing with authority.
3. On the host, the original `0x00548150` path executes against the materialized
   remote participant Player actor. Lua `damage.dealing` and `damage.taken`
   filters also run at this common hook before the original call.
4. `ApplyNativeRemoteParticipantVitalState` in
   `bot_movement/native_remote_vitals_and_playback.inl` observes the actor-owned
   HP drop relative to its last host write and queues
   `QueueHostParticipantVitalsCorrection`.
5. `participant_vitals_authority.inl` coalesces the strongest pending state per
   participant, allocates a correction sequence, sends
   `ParticipantVitalsCorrection`, and resends it until the owner acknowledges
   the sequence in its participant frame.
6. `ApplyParticipantVitalsCorrectionPacket` in
   `participant_vitals_correction.inl` authenticates authority, target, run
   nonce, and correction sequence. For nonlethal damage it writes
   `min(owner_hp, authority_hp)` directly through
   `TryWriteLocalPlayerOrbResource`.
7. `local_state_packet_sync.inl` publishes the owner's resulting HP and
   correction acknowledgement. `incoming_packet_sync.inl` consumes that frame
   on the host and retires/normalizes the pending correction.
8. `dispatch_and_hooks_participant_vitals_actions.inl` applies queued poison,
   Webbed, and Magic Shield native state. It is not the nonlethal HP write and
   currently has no ordinary hit-presentation action.

The ordinary incoming participant frame around
`incoming_packet_sync.inl` updates remote-participant state. It is not the
owner-client HP mutation seam. The owner-client visible HP edge occurs in
`ApplyParticipantVitalsCorrectionPacket`.

Vitals corrections are intentionally coalesced and periodically resent.
Therefore their sequence and payload cannot represent every real hit. Two
native hits can become one strongest HP correction, and one correction can be
received multiple times. This is why feedback cannot be inferred from that
packet or from the local participant frame.

### Instrumented two-instance proof

The clean local pair used only ports `50111/50112` with audio disabled. Both
instances entered the same manual-spawner run with no enemies, so the only
damage was the requested probe.

Traces were armed on:

- `0x0052F540` as `hitfx.damage_inner`;
- `0x0052AC80` as `hitfx.hp_mutation`; and
- the Arena red field at `+0x8EBC`.

The host invoked one `5.0` native magic hit against client B's participant.
Observed result:

| Observation | Host authority | client B owner |
| --- | ---: | ---: |
| actor HP | remote clone `50 -> 45` | local player converged to `45` |
| `0x0052F540` calls | exactly 1, ECX = remote actor | 0 |
| `0x0052AC80` calls | exactly 1, ECX = remote actor | 0 |
| red-field maximum | not local-target feedback | `0.0` across 5,737 ticks |
| correction | sequence 1, life `45/50` | authenticated direct HP write |

This proves that authority computed final damage through stock while the owner
only received state convergence and never entered the native feedback tail.

The reciprocal control lowered the host local player into the red threshold and
applied one native `5.0` hit. The host ran both traced functions exactly once
and wrote red value `0.31953176856041`, matching:

```text
(1 - 21.741043 / 40) * 0.7
```

client B remained at red `0.0`. Thus stock already gives exactly one local
presentation on the machine that natively simulates its own hit; the missing
case is specifically the owner of an authority-simulated remote actor.

### Visual-gate correction to the initial model

The first presentation-only prototype proved the event and audio paths but
failed actual image inspection. On client B it wrote
`Arena + 0x8EBC = 0.482489`; a backbuffer capture two rendered frames later
still had `0.475489`, yet showed no red edge. The matched host-native capture
at `0.478781` visibly showed the stock red wash. A live identity probe also
proved that the local Actor's owner Arena and the active render Arena were the
same object, ruling out an Arena alias.

The missing state was then recovered at raw render instruction
`0x00470538`: stock loads `*(local_actor + 0x78)`, multiplies it by
`*(Arena + 0x8EBC)`, and passes the product to the quad renderer. The owner
never ran `0x00627F80`, so its local Actor latch remained zero and multiplied
the otherwise-correct Arena scalar away. This visual gate is the reason the
resolved Actor presentation fields are mandatory in the wire event and replay
below.

## Fix contract

### Event origin

`HookPlayerActorMagicDamage` remains the authority and Lua-filter gate, but it
is not a reliable completed-event boundary. Live stock-skeleton instrumentation
showed the host applying real damage and publishing a vitals correction while
the outer hook's optional damage-context capture reported
`damage_context_unavailable`. Tying feedback capture to that optional outer
context silently missed a stock melee path.

The foundational event boundary is therefore
`HookPlayerActorDamageResolver`, the detour of the common resolver at
`0x0052F540`. Every Player-family damage route that reaches stock HP mutation
passes this point after the outer authority/filter work. For a host-side remote
participant whose controller kind is `Native`, the outermost resolver call on
the current thread captures the actor-owned HP and progression address before
stock runs. After stock returns, it reads the final resolved damage lanes and
the same actor-owned HP pool. Nested resolver calls remain part of their
outermost transaction rather than producing an inner event plus an aggregate
outer event.

The resolver hook publishes one hit-feedback event only when:

- both reads are finite and from the same actor-owned progression pool;
- post-hit HP is strictly lower than pre-hit HP;
- the special/heal lane was zero;
- the target remains the same authenticated remote human participant; and
- post-hit HP remains positive.

The HP transition and final lanes are sampled after Lua filters and stock
defense resolution, so the event describes completed damage, not requested
damage. It automatically covers stock enemies, stock spells, and mod-authored
damage that enters the framework's common Player damage/filter seam. It is not
tied to skeletons, a spell type, a vitals packet, or an enemy packet.

The hook does not publish for the host's own local actor: stock just presented
that hit. It does not publish for `LuaBrain` participants, so bot damage never
causes a screen flash. It does not publish a lethal event; the existing
owner-side stock death replay remains the sole killing-blow presentation.

### Wire event and reliability

Protocol 87 adds `ParticipantHitFeedback`, a small authority-to-owner packet
containing:

- authenticated authority participant id;
- target participant id;
- target run nonce;
- per-target hit event sequence;
- pre-hit, post-hit, and maximum HP;
- an ouch-eligible bit captured from the native primary/secondary lane gate;
- the resolved Actor hit fields at `+0x78/+0x7C/+0x80`; and
- the resolved hit-overlay RGBA at `+0x84..+0x90`.

This packet contains no damage-apply instruction.

The authority keeps every event in a bounded per-target pending queue and
resends unacknowledged events for the local UDP lane. Steam sends the same
packet reliably. The target's participant frame carries its highest contiguous
hit-feedback acknowledgement. The client tracks out-of-order arrivals until
the gap closes, so acknowledging event N can never discard an unseen event
below N.

The owner authenticates authority, target, run nonce, finite HP bounds, and
event sequence before queueing presentation on the gameplay-thread action
pump. Target identity uses `GetLocalTransportParticipantId`; the runtime-state
local participant deliberately uses the internal slot id `1` and is consulted
only for validity, in-run state, and run nonce. A live diagnostic caught this
identity-domain distinction: the requested 64-bit transport id and run nonce
were correct while comparing them to runtime slot `1` rejected every event.

A successfully queued sequence becomes idempotent immediately; duplicate
retransmissions do not queue again. If the local actor is temporarily
unavailable, the gameplay action remains pending rather than converting a
later snapshot into a new event.

The authority sends the HP correction before newly queued presentation events
in each transport service pass. The event carries authoritative post-hit HP,
so the native gain and red magnitude remain correct even if UDP delivery
reorders the two datagrams by a frame.

### Presentation-only replay

The gameplay-thread action:

1. resolves the true local actor with `TryGetPlayerState`;
2. verifies it is still the target run and is live/nonterminal;
3. copies the authority-resolved Actor presentation fields at
   `+0x78..+0x90`, without invoking `0x00627F80` or its reaction dispatcher;
4. reproduces the stock ouch gate, RNG choice, health gain, world attenuation,
   and `Sound::Play` request when the event's captured lane bit permits it;
5. reproduces the local red threshold/formula by writing only
   `Arena + 0x8EBC`; and
6. updates the same stock presentation deadline exactly as the native blocks
   do.

It never calls `0x00548150`, `0x0052F540`, `0x0052AC80`, or any HP-write helper.
The authoritative vitals correction remains the sole nonlethal HP mutation on
the owner.

Each accepted event emits one structured log record including authority,
target, run nonce, event sequence, HP transition, whether an ouch request was
made, selected ouch index, and written red value. This is presentation
observability, not a second source of damage truth. With
`SDMOD_DISABLE_AUDIO=1`, the stock `Sound::Play` request still reaches the
loader's observability hook before the audio backend is suppressed, allowing
the harness to prove the request without audible output.

Rapid events are individually consumed, but stock's shared deadline controls
ouch cadence and every red write replaces the existing scalar rather than
adding to it. That preserves native rapid-hit behavior and prevents artificial
strobe stacking.

## Required proof

Static and focused tests must establish:

- the new packet is protocol-authenticated and owner-targeted;
- events have a per-target sequence, resend state, contiguous ACK, and
  duplicate rejection;
- ordinary snapshots and vitals corrections contain no feedback inference;
- HP increase/heal cannot enqueue feedback;
- host-local and bot targets cannot enqueue replicated local feedback;
- lethal damage remains on the stock death replay only;
- gameplay replay calls no damage/HP mutation function;
- ouch asset selection/gain, Actor reaction fields, and red
  threshold/formula match the recovered constants and offsets.

The two-instance harness must then prove:

1. every completed authority-simulated damage event on client B produces
   exactly one sequenced owner event and one gameplay replay record;
2. a duplicate event/resend and periodic vitals/snapshot traffic produce no
   additional replay;
3. healing produces none;
4. damage to the other participant produces none on client B;
5. a host-local native hit remains exactly one native hit with no framework
   replay; and
6. the client B view visibly contains the native red-edge frame.
