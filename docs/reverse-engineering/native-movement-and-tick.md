# Native movement integrator, tick graph, and RNG

Investigation date: 2026-08-04

## Result

The retail simulation is a fixed **100 Hz** simulation driven by `timeGetTime`.
One simulation tick is 10 ms. Rendering is a separate, at-most-60 Hz pass; one
render pass can therefore follow zero, one, or several fixed ticks. The 67 ms
run-world motion and 250 ms bot-mana values previously observed are loader
publication/service cadences, not native physics steps.

Player movement is a velocity accumulator. Each held unit direction adds
`0.1` velocity per fixed tick, the resulting vector is capped, collision moves
the actor, and velocity is then damped by `0.9` in the ordinary state. The
stock baseline reaches a pre-damping displacement of exactly `1.0` world unit
per tick, or **100 world units/s**. Enemies use a different, direct-step model:
their normalized direction is multiplied by `0.25 * base_speed * modifiers`
and by the number of fixed ticks represented by the enemy's cadence gate.

The native random generator is neither an LCG nor MT. It is a 55-word additive
lagged-Fibonacci generator modulo `2^30`, with lags 55 and 24. The executable
has a shared process stream, but several high-value selectors deliberately
seed private copies (offers, drops, some attacks, and game/run generation).

The live, machine-recorded conformance corpus is:

- `tests/fixtures/webgame/movement-goldens.json`
- `tests/fixtures/webgame/rng-goldens.json`
- `tests/fixtures/webgame/float-rng-goldens.json`

The movement/integer recorder is `tools/record_native_sim_goldens.py`. It
records positions from the native player-tick boundary and invokes retail RNG
code in an isolated recorder-owned state object. The float recorder is
`tools/record_native_float_rng_goldens.py`; its opt-in loader seam invokes both
retail float primitives on an isolated constructor-initialized `0xE8`-byte
object. Neither recorder replaces retail movement or RNG.

This work covers the retail `SolomonDark.exe` whose SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Addresses below are preferred-image virtual addresses for that executable.

## Evidence boundary

The claims combine three independent evidence classes:

1. read-only headless Ghidra decompilation from a campaign-owned project
   replica;
2. live reads and existing `lua-exec`/`sd.debug` raw-call probes in isolated
   `phr-*` solo instances; and
3. the live JSON traces produced by the recorder, including its source SHA,
   instance name, executable hash, capture method, and epsilon rationale.

No gameplay behavior was changed. The only new native seam,
`sd.debug.sample_native_rng`, is recorder-only: it allocates a private `0xE8`
byte state, calls the original initializer and integer sampler, and returns the
outputs and final state. It never reads or writes the active process stream at
`0x00818B08`. Movement, collision, actor placement, and Knockback use existing
Lua/debug seams.

## Coordinate and numeric conventions

- Actor center is the float pair at `actor+0x18/+0x1C`.
- Player accumulated velocity is the float pair at
  `actor+0x158/+0x15C`.
- Positive X is east; positive Y is south.
- Positions, velocities, radii, and movement scalars are binary32 values.
- This document writes `v_pre` for velocity after input/cap and before the
  move, and `v_post` for the value after damping.
- `TPS = 100`, so a per-tick displacement multiplied by 100 is world units/s.

The fixtures use an absolute position epsilon of `1e-4` world units. At the
captured arena coordinates this is above a binary32 ULP but far below any
meaningful movement step. Scalar comparisons use `1e-6`.

## Player movement pipeline

### Input -> intent

`PlayerControlBrain_Update` at `0x0052C910` forms a two-component movement
direction from the current controls. If its magnitude exceeds one, it divides
both components by the magnitude. Cardinal input is therefore unit length and
simultaneous full-strength orthogonal input is normalized; there is **no
sqrt(2) diagonal speed advantage**. Inputs with magnitude at most one are not
scaled up.

The normalized direction is published to the Player actor and consumed by
`PlayerActor_Tick` at `0x00548B00`. Discipline selection does not branch to a
different base movement constant in either function. Discipline/skill effects
can change the explicit modifier fields described below, but all stock player
disciplines share this integrator and baseline.

### Intent -> velocity

For each fixed tick, `PlayerActor_Tick` performs the following vector update:

```text
input = clamp_magnitude(raw_direction, 1)
v_pre = v_post_previous + input / 10
cap = actor[+0x120] * actor[+0x74]
    * progression[+0x90] * 1.25
if length(v_pre) > cap:
    v_pre = normalize(v_pre) * cap
```

The input divisor is the double `10.0` at `0x007DE810`; acceleration is thus
`0.1` velocity unit per tick, or 10 velocity units/s. The cap's global double
`1.25` is at `0x00784740`.

**Precision order is load-bearing — a port must divide before it narrows.**
`input / 10` is a *double* division on the incoming direction; only the sum
`v_post_previous + input/10` is narrowed to the stored `float`. Rounding the
direction to `float` first and then dividing shifts the result by roughly one
ulp, which is normally invisible but decides the `> 0.01` move gate below on
the first tick of a diagonal start: the correctly-ordered `|v_pre|^2` is
`0.010000000219…` and passes, while the prematurely-narrowed value is
`0.009999998814…` and fails. That single skipped step offsets the whole trace
and never recovers, so a port that gets this wrong diverges from every diagonal
golden while still matching all four cardinals.

Reproducing this document's integrator against
`../../tests/fixtures/webgame/movement-goldens.json` with the order above, the
float `0.9f` damping, and float-width position stores yields bit-exact
positions across all five open-ground scenarios (595 ticks) and bit-exact
velocities on the four cardinals. Diagonal velocity lands within 2 ulps,
because the native tick keeps the intermediate in an x87 register instead of
narrowing between the add and the damp; that residual does not reach position
at world-space magnitudes and can be ignored by a port that stores `float`.

The stock baseline terms are:

| Term | Stock baseline | Source and role |
| --- | ---: | --- |
| actor `+0x120` | `1.0` | Common actor construction; transient native movement/status multiplier. |
| actor `+0x74` | `1.0` | Common actor construction; native move-speed scale. |
| progression `+0x90` | `0.95` | Reset at `0x0065F5B0`; progression/concentration movement multiplier. |
| global | `1.25` | `0x00784740`; cap scale. |
| resulting cap | `1.1875` | `1 * 1 * 0.95 * 1.25`. |
| actor `+0x218` | `1.0` | Constructed/reset at `0x0052A500`; final move-step scale. |

Ranked Rush and concentration must not be folded into a new base speed. The
native concentration pass at `0x00661FD0`, case 67, multiplies progression
`+0x90` by its absolute concentration factor after the reset. The loader's
local-player Rush scope temporarily owns `actor+0x218` around the stock tick.
The ownership and non-accumulation proof is in
`../bugs/player-speed-rush-accumulation-2026-08-01.md`.

### Velocity -> placement -> position

`PlayerActor_Tick` only requests a move while
`vx*vx + vy*vy > 0.01`; the `0.01f` threshold is at `0x007DE890`. It supplies
this displacement to the common movement controller:

```text
delta = actor[+0x218] * v_pre
MoveStep(controller, delta)             // 0x00525800
v_post = damping * v_pre
```

Ordinary damping is `0.9f` at `0x00784970`. When the native flag at
`actor+0x21C` (parameter slot `0x87`) is active, damping is `0.95f` at
`0x00784E20`. Damping happens after placement.

This distinction explains why the `1.1875` velocity cap is not the ordinary
walking speed. Under a held unit direction and ordinary damping,
`v_pre[n] = 0.9*v_pre[n-1] + 0.1`; its fixed point is `1.0`, below the cap.
The live cardinal traces converge to one world unit per tick. A modifier can
raise the final move-step scale without changing the accumulator, while cap
modifiers matter once their resulting cap falls below or otherwise constrains
the recurrence.

There is no ordinary instant stop. On release, the previous post-damped
velocity continues to move and is multiplied by `0.9` each tick. Starting
from the steady baseline, physical placement continues for 21 release ticks
(`0.9`, `0.81`, ...), then the squared-magnitude threshold suppresses smaller
MoveStep calls. A forced native stop can still clear the vector directly; that
is a different state transition, not normal input deceleration.

### Player baseline and class/discipline answer

The executable does not have a per-discipline base-speed table for the player.
Every stock player uses the terms above. Baseline held movement is:

| Input | Steady `v_pre` | Steady displacement | Speed |
| --- | ---: | ---: | ---: |
| cardinal unit vector | length `1.0` | `1.0`/tick | `100` units/s |
| diagonal unit vector | length `1.0` | `1.0`/tick | `100` units/s |

The live diagonal golden supplies `(sqrt(0.5), sqrt(0.5))`; the static
`0x0052C910` contract additionally pins normalization of over-length raw
directions.

## Enemy movement pipeline

Enemy movement does not reuse the player's inertial accumulator. The common
`Badguy` constructor at `0x00473390` initializes inherited speed factors
`actor+0x70 = 1.0` and `actor+0x120 = 1.0`, plus the enemy-local factor
`badguy+0x1A4 = 1.0`.

Direction builders at `0x004763E0` and `0x00476B90` calculate:

```text
S = badguy[+0x1A4] * actor[+0x70] * actor[+0x120]
delta = normalize(target_or_steering_direction) * 0.25 * S * cadence_ticks
```

The scale `0.25` is the double at `0x007DE8F0`. `cadence_ticks` is one for the
single-step form and the represented tick count for the cadence-aware form.
Long-term unobstructed speed is consequently `25 * S` world units/s.

`Badguy_Tick` at `0x004835F0` chooses a cadence, phase-locks eligibility by
`actor_serial % N == global_tick % N`, aggregates/chooses direction, adds the
avoidance vector from `0x0047CB20`, and routes the result through the wrapper
at `0x00475FE0` to the same `MoveStep` at `0x00525800`. Normal active movement
uses `N=2`; observed state branches use `N=5`, `N=10`, or `N=15`. Multiplying
the eligible step by `N` preserves average speed. When a requested step is
large relative to the collision radius it is subdivided using `radius - 1`
before placement.

Direction changes therefore take effect on the next eligible enemy update;
there is no player-style acceleration tail or deceleration tail. The local
factor `+0x1A4` decays by `0.995` per eligible update toward a floor of `1.0`
when its timer at `+0x194` is inactive. `actor+0x120` remains the shared status
multiplier.

### Recovered enemy base-speed constructors

These are the arena-family constructors reached by the recovered enemy
factory. Random endpoints are reachable because native float sampling is
inclusive at both endpoints.

| Enemy family | Constructor | `actor+0x70` base | Unmodified speed at `+0x1A4=+0x120=1` |
| --- | ---: | ---: | ---: |
| Imp (and Green Imp inheritance) | `0x00473E30` (`0x00474D20`) | `4.5` (`0x00785E4C`) | `112.5` units/s |
| Zombie | `0x004740C0` | `1.0 * 0.85` (`0x00785858`) | `21.25` units/s |
| Wraith | `0x00474470` | `1.0` | `25` units/s |
| Demon Skull | `0x00474660` | `4.0` (`0x007849F8`) | `100` units/s |
| Dire Faculty | `0x00474E50` | `2.75` (`0x00786260`) | `68.75` units/s |
| Spider | `0x004759A0` | `3 + RandomFloat(2)` = `[3,5]` | `[75,125]` units/s |
| Skeleton | `0x004771B0` | `(1.25 + RandomFloat(1)) * 1.25^2` = `[1.953125,3.515625]` | `[48.828125,87.890625]` units/s |
| Demon | `0x00479150` | `1.0 * 0.75` | `18.75` units/s |
| Coffin | `0x00479940` | `1.0 * 0.75` | `18.75` units/s |
| Maggot | `0x0047E0F0` | `1 + RandomFloat(1)` = `[1,2]` | `[25,50]` units/s |
| Skeleton Archer | `0x0048A6B0` | Skeleton result `* 0.75` | `[36.621094,65.917969]` units/s |
| Skeleton Mage | `0x0048ABB0` | Archer result `* 0.65` | `[23.803711,42.846680]` units/s |
| Heartmonger | `0x0048B970` | Skeleton result `* 0.65 * 0.75` | `[23.803711,42.846680]` units/s |

The write at `0x004871F0` from a recipe/config field into `actor+0x238` is
class-overloaded state, not a universal movement-speed field. A browser port
must use the constructor-family mapping rather than treating `+0x238` as a
generic base speed.

## Collision response

### Radius ownership

Collision functions do not embed a player or enemy radius. They read the
current actor's float `actor+0x30`. Common construction at `0x0052A500` seeds
`15.0f` (global `0x00784998`); class/config initialization can overwrite it.
The live Player used for the goldens reports `25.0`. The fixture header records
that live radius so a replay does not silently substitute the constructor
default.

Knockback temporarily uses `0.6 * actor+0x30` for its separation pass; it does
not permanently change the actor radius.

### MoveStep dispatch

`MoveStep` at `0x00525800` has a deliberately cheap direct-add path only when
the controller has no collision world (`controller+0x120 == 0`), the actor is
not enrolled for collision (`actor+0x36 == 0`), **and** the controller's
dynamic-response lane is disabled (`controller+0x121 == 0`). If any of those
three lanes requires collision work, it:

1. saves the original center;
2. gathers nearby collision cells through `0x00521B80/0x005218C0`;
3. tentatively applies the full requested delta;
4. resolves primary contacts through `0x00522CE0`/`0x00522500`;
5. runs the selected secondary response (`0x00522C00` or `0x00522B20`); and
6. rebinds the actor to the spatial cells at its resolved center.

The native placement predicate exposed as
`movement_collision_test_circle_placement` is `0x00523C90`; its extended
worker is `0x005238C0`. It answers whether the actor-sized circle can be placed
at a candidate center against the same native geometry used by MoveStep.

### Region transitions retain dynamic actor collision

Arena entry does not replace the player with an arena-only movement body or
drop the shared dynamic-response stage. `Arena::Arena` at `0x00464EE0` and
`Courtyard::Courtyard` at `0x00506490` both begin by calling the common
`Region::Region` constructor at `0x00652830`. That base owns the participant
manager, actor lists, world-cell/collision substrate, and teardown used by both
fixed rooms and the Boneyard-backed Arena. The persistent gameplay-slot actor
is registered into the active Region through `0x00641090`, which assigns its
region owner and rebinds its world-cell membership; it is not reconstructed as
a collision-free Arena presentation object.

The scene-independent `PlayerActor::Tick` at `0x00548B00` continues to submit
the accumulated player movement lane to `PlayerActor_MoveStep` at
`0x00525800`. After authored-world response, `MoveStep` invokes
`MovementCollision_ResolveDynamicObjects` at `0x00526520` when the Region's
dynamic-collision lane is active. That pass walks the Region's nearby actor
list, filters collision membership/masks, and applies the shared radius,
resistance, push-strength, movement-epoch, and recursive placement rules.
There is no Arena-specific player-versus-player bypass in this owner chain.

Implementation consequence for ports: changing from a fixed Region to Arena
may replace the authored static geometry adapter, but it must keep the shared
actor-body response around that adapter. Applying Arena scenery collision
independently to each player omits a native downstream consumer and permits
players to overlap or pass through one another after Boneyard entry.

Evidence: fresh read-only headless Ghidra decompilation on 2026-08-14 from the
analyzed retail `SolomonDark.exe` project replica for `0x00652830`,
`0x00464EE0`, `0x00506490`, `0x00641090`, `0x00548B00`, `0x00525800`, and
`0x00526520`; retail SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Confidence is high for owner continuity, call order, and the absence of an
Arena-only movement path. An exact-coincident pair still has a zero normalized
separation vector in the shared solver; ordinary relative motion creates a
direction and resolves contact. A port must not invent per-player spawn
offsets to hide that boundary case.

### Walls, slides, stops, and corners

The primary resolver at `0x00522CE0` takes the closest point on each
rectangular wall feature and pushes the actor center outward until its
distance is the current radius. Consequences are geometric rather than
special-cased by input angle:

- On a flat wall, the normal component is clamped and the tangential component
  remains. A 0-degree approach stops at contact; 30- and 60-degree approaches
  wall-slide.
- At a convex corner, the closest point is the corner, so the correction is
  radial and the center follows a radius-sized arc around it.
- Multiple contacts are resolved sequentially in collision-list order. A
  concave or tight corner can remove both components and pin the actor.
- The secondary `0x00522C00` path restores the old center (full stop). The
  `0x00522B20` path restores it and calls the iterative alternative at
  `0x00522A30`, which searches a legal partial/alternate placement.

Contact math uses `0.5` at `0x007DE808`, `0.01f` at `0x00807884`, and an
iteration bound of 8 at `0x00807888`. A faithful implementation must retain
float32 rounding and ordered multi-contact resolution; replacing this with an
unordered overlap set changes corner outcomes.

The live wall goldens use the arena's deterministic north navigation boundary
at 0, 30, and 60 degrees. They record the boundary normal/tangent and every
native tick. The 0-degree trace loses normal displacement at contact; the
angled traces reach the same contact plane while retaining increasing tangent
displacement.

## Knockback

The stock `Knockback` actor (factory type `0x07E9`) is constructed at
`0x005E7B50` and ticks at `0x00600220`. Each tick, for every affected target,
it performs:

```text
step = min(remaining_distance_at_+0x13C, 10)
direction = normalize(target_center - knockback_origin)
MoveStep(target_controller, direction * step)
temporarily set target_radius = original_radius * 0.6
MoveStep(target_controller, (0, 0))       // native separation pass
restore original_radius
remaining_distance -= step
```

The last step may be fractional. Knockback is therefore collision-aware and
inherits the same wall-slide, corner, and stop behavior; it is not a position
teleport and it does not add to player `+0x158/+0x15C` velocity.

The live golden creates an isolated retail `0x07E9` through the existing
factory/raw-call probe, gives it one Player target and 100 remaining units,
then calls the original tick twice. The observed displacement is two 10-unit
steps in the unobstructed +X direction. It is destroyed through its retail
destructor immediately afterward. Zombie contact uses a separate
`Mod_Knockback` path, so an incidental Zombie hit would not prove this stock
actor contract.

## Native tick graph

### Scheduler and timing source

The outer application flow is:

```text
App_Run 0x0040C690
  -> Windows message pump 0x0040D130
  -> fixed-step scheduler 0x0040D3C0
       while due: fixed tick 0x0040D1B0
       once:      render pass 0x0040D230
       Sleep(1) when ahead
```

The scheduler reads WinMM `timeGetTime`. Application construction at
`0x0040B6B0` initializes the rate from `100.0f` at `0x007DE9B8`, the last-time
field at application `+0xC04`, and the next fixed-tick target at `+0xC08`.
Scheduler arithmetic uses `100.0` at `0x007DE908` and `10.0` at `0x007DE810`:
100 fixed ticks/s and 10 ms/tick. A catch-up loop can issue multiple fixed
ticks before the next render. Its guard uses `0.25` at `0x007DE8F0`, i.e. 25
ticks of catch-up budget.

Render at `0x0040D230` calls the application render virtuals at `+0xE4`,
`+0xE8`, and `+0xEC`, then `0x00440B40`. It is capped at 60 Hz. Rendering does
not advance actors and must not be used as the browser simulation clock.

`0x00820230`, live value `100.0`, is a ticks-per-second conversion global used
by gameplay duration/rate formulas. It agrees with the scheduler but does not
drive it and is not a writable time-scale control. This reconciles the earlier
investigation in `game-timing-scale.md`.

### Order inside one fixed tick

The statically recovered order is:

1. `0x0040D1B0` ticks the application-level ActorWorld through
   `0x004022A0`.
2. It dispatches the current scene through virtual `+0x20`; a pending scene
   transition instead runs `0x004284B0`.
3. Scene dispatcher `0x00427800` calls the scene object's tick virtual at
   `+0x08`, then increments scene/global tick `scene+0x28` and advances scene
   timers.
4. For the Game scene, `0x005D7EF0` runs the pre-world pass `0x004FDD50`,
   snapshots tracked actor centers and conditional bookkeeping/progression,
   calls the game-state pass `0x005CB360`, then ticks the Game ActorWorld via
   `0x004022A0`.
5. `ActorWorld_Tick` first initializes pending actors through virtual `+0x04`,
   then traverses the live actor list in **insertion order** and calls virtual
   `+0x08`, then removes actors marked for destruction. Player
   (`0x00548B00`), arena/wave (`0x0046E570`), enemies (`0x004835F0`),
   projectiles, loot, and effects therefore have no type-sorted global order;
   their relative order is their actor-list order.
6. The remainder of `0x005D7EF0` consumes the post-actor state for camera,
   tracked-player/UI/status work and end-of-tick scene bookkeeping.
7. The outer loop may render after the fixed-tick catch-up sequence.

This ordering has two porting consequences. Newly queued actors are initialized
before that world's live traversal, and same-tick producer/consumer behavior
depends on insertion order. A browser core that batches systems by entity type
will need an explicitly demonstrated equivalent ordering or will diverge.

### Gameplay cadence census

There are three timing domains. Only the first advances retail simulation:

| Domain/system | Cadence | Clock/ordering meaning |
| --- | ---: | --- |
| Native fixed simulation | 10 ms / 100 Hz | `timeGetTime` scheduler; actor state, movement, collisions, native timers. |
| Native render | at most 16.667 ms / 60 Hz | Once per outer loop after zero or more fixed ticks; presentation only. |
| Normal Badguy movement | 2 fixed ticks / 20 ms eligibility | Slot-phased by serial and global tick; step is multiplied by 2. |
| Badguy alternate states | 5, 10, or 15 fixed ticks | Same phase gate; state-dependent and cadence-compensated. |
| Loader app-thread/player hook | each native Player tick / 10 ms | Exact fixed-tick boundary, not a worker timer. |
| Loader multiplayer service loop | 16 ms | Transport/service worker; never a physics clock. |
| Loader runtime/scene binding workers | 50 ms | Runtime tick service and bot scene binding. |
| Participant frames / cast input / vitals / teardown | 50 ms | Multiplayer publication/retry. |
| Run-world motion snapshot | minimum 67 ms | Publication cadence; bandwidth limiting can stretch it. Immediate authoritative changes may flush it. |
| Full world snapshot | minimum 200 ms | Publication cadence; reliable checkpoint is 1000 ms. |
| Native spell-effect snapshot | minimum 16 ms | Publication only. Registered Lua spell effects publish at 50 ms; their effect default tick is 16 ms. |
| Loot snapshot | 250 ms static / 50 ms animated | Publication only; bandwidth limiting can stretch it. |
| Wave summary | 400 ms | Reliable checkpoint publication. |
| Hostile-target sidecar/nearest maintenance | 100 ms | Loader-owned app-thread maintenance. |
| Nav-grid snapshot rebuild | minimum 500 ms | Loader navigation observation cache. |
| Lua enemy AI | default 100 ms, allowed 16..5000 ms | Loader Lua decision schedule; native actors continue at fixed ticks. |
| Bot Brain standard think | 250 ms | Lua policy decision. Manager/learned-policy interval is 100 ms. Movement requests are profile-specific: approach 1000, kite/flee 250, orbit 500 ms. |
| Bot mana reserve recovery | 250 ms | Loader app-thread service; recovers 10% maximum mana/s, hence 2.5% max per step (2.5 MP for max 100). |
| Synthetic retirement / level-up barrier retry | 250 ms | Multiplayer retry/broadcast, not simulation. |
| Local session status | 500 ms | Multiplayer status publication. |
| State/reliable world/run-lifecycle checkpoint | 1000 ms | Multiplayer repair/control traffic. |
| Progression and Lua-mod checkpoints | 5000 ms | Reliable repair traffic. |

The 67 ms handoff in
`../bugs/beta32-bot-mana-and-lone-target-handoff-2026-08-04.md` is thus the
delay before a changed native target is normally published, not a 15 Hz
movement integrator. Likewise the documented 250 ms mana steps are a loader
service layered over 25 native fixed ticks. Transport timestamps and Lua
wall-clock timers must not enter the deterministic browser core; translate
authority actions onto fixed-tick boundaries and keep network publication
outside the sim.

Native actor abilities also use counters expressed through the 100 TPS global
and can choose their own integer-tick periods. Those data/state-machine periods
belong to the projectile, enemy-interpreter, progression, and loot gap
campaigns. Their timing source is nevertheless fixed ticks, not a fourth
clock.

## Native RNG

### State and recurrence

`NativeRng_Constructor` at `0x00401110` initializes a `0xE8`-byte object:

| Offset | Width | Meaning |
| --- | ---: | --- |
| `+0x00` | 32 bits | first ring index, initially 0 |
| `+0x04` | 32 bits | second ring index, initially 31 |
| `+0x08..+0xE0` | 55 x 32 bits | state words; only low 30 bits are used |
| `+0xE4` | 32 bits | float divisor, `100000` |

`NativeRng_Seed` at `0x00401120` sets:

```text
mask = 0x3fffffff
state[0] = seed & mask
state[1] = 1
state[i] = (state[i - 1] + state[i - 2]) & mask, i = 2..54
index_a = 0
index_b = 31
```

Each primitive draw at `0x00401170` adds the two indexed words modulo `2^30`,
stores the result back at the first index, and advances both indices modulo 55.
The 31-position separation is the conventional 55/24 lag pair (31 and 24 are
complements in the ring).

For a positive integer bound `n`, it selects the smallest power of two `P >= n`
starting at 2 and returns:

```text
u = (state[index_b] + state[index_a]) & 0x3fffffff
state[index_a] = u
advance both indices modulo 55
result = ((u >> 6) & (P - 1)) % n
```

`n == 0` returns zero. Negative bounds use the positive magnitude and consume
an additional bound-2 draw to choose the sign. The power-of-two mask followed
by `% n` is biased for non-power-of-two bounds; a port must reproduce it rather
than use rejection sampling.

The float primitive at `0x00401310` draws integer bound `100001`, divides by
the stored `100000`, and multiplies by the requested magnitude. Both `0.0` and
the positive endpoint are reachable. A signed request uses the integer
sampler's sign behavior. Public range wrappers are `0x00448450` (integer) and
`0x00448480` (float). The integer wrapper has an equal-endpoint fast path. The
float wrapper uses `fucomp` only for the equal-endpoint fast path; otherwise it
stores `f32(second-first)`, draws the inclusive primitive on that signed span,
then returns `f32(first+draw)`. It therefore preserves argument order rather
than sorting the endpoints, and an equal pair consumes no RNG word.

The divisor is not a literal. It is a per-object field at `this+0xE4`, the dword
immediately after the 55 state words, which the constructor `0x00401110` sets to
`0x186A0` = `100000`; no other method of the class writes it. A port that hard
codes `100000` is right for every stock object but is encoding a default, not a
constant.

**The rounding schedule is load-bearing and is the easiest thing to get wrong.**
The primitive rounds to float32 three separate times, once after each step:

```text
00401327  mov   [ebp-4], eax          ; k = Integer(N+1)
0040132a  fild  dword ptr [ebp-4]
0040132d  fstp  dword ptr [ebp-4]     ; -> f32(k)
00401330  fld   dword ptr [ebp-4]
00401333  fidiv dword ptr [ecx+0xe4]  ; / N, in the x87 stack
00401339  fstp  dword ptr [ebp-4]     ; -> f32(f32(k) / N)
0040133c  fld   dword ptr [ebp-4]
0040133f  fmul  dword ptr [ebp+8]     ; * magnitude
00401342  fstp  dword ptr [ebp+8]     ; -> f32(f32(f32(k) / N) * magnitude)
```

so the result is `f32(f32(f32(k) / N) * magnitude)`, **not** `f32(k / N *
magnitude)` evaluated in double and rounded once at the end. The intermediate
store after the divide is the one that matters. Over all `100001` reachable `k`,
the two disagree for roughly a quarter of draws:

| magnitude | draws that differ | share |
| --- | --- | --- |
| `1.0` | 0 / 100001 | 0.00% |
| `0.5` | 0 / 100001 | 0.00% |
| `3.0` | 27,836 / 100001 | 27.84% |
| `4.5` | 25,225 / 100001 | 25.22% |
| `100.0` | 25,055 / 100001 | 25.05% |
| `1023.0` | 25,222 / 100001 | 25.22% |

Powers of two are exempt because the final multiply is then exact, which is why
a spot check against a unit magnitude will not reveal the bug. Everything else
diverges in the last ulp — for example `k = 5, magnitude = 3.0` gives
`0.00014999999257270247` natively against `0.0001500000071246177` for the
double-precision shortcut.

A signed float request costs **two** stream words, not one: after the value is
computed, `0x00401345` falls into an inlined copy of the same lagged-Fibonacci
step and takes bit 6 of that second word as the sign. It is inlined rather than
a call to the integer sampler, but it is numerically the same choice the integer
sampler's `Integer(2)` would make, and it advances the stream identically. Any
replay that treats a signed float draw as a single advance desynchronizes.

There is a second float primitive at `0x004011F0`, reached by one call site. It
is the same draw and the same divide with the same sign branch, but no magnitude
multiply and one stack argument instead of two (`ret 4`), so it returns `k / N`
on `[0, 1]` and rounds to float32 twice rather than three times.

### Active stream and seeding lifecycle

The active RNG pointer is stored at `0x00818B08` and normally points to the
global state object at `0x00818B10`. Retail startup at `0x0040CEB2` calls
`timeGetTime` and passes the 32-bit result to `0x00401120`. Thus ordinary
startup seeds are millisecond-clock-derived and are not replayable unless the
seed/state is observed.

On loader-created deterministic runs, `sd.rng.set_seed` calls the same native
initializer immediately before arena generation and again immediately before
the stock arena-create path. This makes the chosen seed observable and keeps
the subsequent native sequence authoritative.

Boneyard generation at `0x006388B0` is a special stream transfer. It draws
`Integer(999999)` from the active global at `0x006388FE`, seeds a private stack
RNG, performs generation from that private state, then copies all 58 dwords
back to the global object at `0x0063895B`. To an outside observer this is one
shared stream whose state jumps to the private generator's post-generation
state; it is not an independent persistent Boneyard stream.

#### The one recorded observation does not show that lifecycle

`rng-goldens.json` carries a single snapshot of the global object labelled
`active_state_after_world_generation`, with `published_seed`, `selected_in_hub`,
and `get_seed_in_hub` all equal to `19088743`, and a note claiming world
generation had already consumed the stream. The recorded words do not support
that reading, and a port must not treat this snapshot as evidence that
`sd.rng.set_seed` controls world generation.

Seeding and the primitive draw are both *linear* in the seed over `Z/2^30`, so
the snapshot can be inverted exactly rather than searched. Carrying each state
word as `p * seed + q (mod 2^30)` and solving the resulting congruence gives a
**unique** solution for every draw count up to 200000 that is consistent with
the recorded ring indices `index_a = 2`, `index_b = 33`:

```text
observed state == NativeRng_Seed(5683095) followed by exactly 2 primitive draws
```

The Fibonacci ladder is visible directly in the recorded words — `state[2] =
5683096`, `state[3] = 5683097`, `state[4] = 11366193`, `state[5] = 17049290` —
with only `state[0]` and `state[1]` overwritten, which is what two draws do.
Three consequences follow:

- The seed is **not** `19088743`. Whatever seeded this object, it was not the
  published/selected/hub-reported value that the loader chose.
- The seed cannot be the documented `Integer(999999)` result, because
  `5683095 >= 999999` is outside that generator's range — for *any* draw count.
  It also never appears as a raw 30-bit word in the first 500000 draws of a
  global seeded with `19088743`.
- Two draws is not a post-generation state. A stream that world generation had
  consumed cannot sit two steps past a fresh ladder.

`5683095` was previously read as `94.7` minutes in milliseconds — the shape of a
`timeGetTime` startup seed. That reading is wrong. The number factors exactly:

```text
5683095 = 1485 * 0xEF3        (0xEF3 = 3827; 5683095 % 3827 == 0)
```

and `0xEF3` is not an arbitrary factor. It is the multiplier in the binary's
**one and only** seeding idiom, which appears at exactly twelve call sites:

```text
seed = *(int *)(*(App **)0x00b401a8 + 0x28) * 0xEF3
```

All twelve were confirmed at the byte level rather than from decompiler output,
which renders the struct offset ambiguously for a typed global pointer. Each
site is `mov <reg>,[0x00b401a8]` (`a1 a8 01 b4 00`, `8b 0d …`, or `8b 15 …`)
immediately followed by `mov <dst>,[<reg>+0x28]` (`8b 40/41/42/51 28`) and then
`imul <reg>,<reg>,0xef3` (`69 c0/d2 f3 0e 00 00`):

`0x00465180`, `0x0046E672`, `0x00504261`, `0x00504BC6`, `0x0050664D`,
`0x0050917B`, `0x00509425`, `0x00509BA8`, `0x00509D32`, `0x00509F4E`,
`0x0050A3F7`, `0x0050CECA`.

`0x00B401A8` is the Raptisoft `App` singleton — written only by the `App`
constructor `0x0040B6B0` (`*this = App::vftable` at `0x007DB97C`, then
`String_Set("Unnamed App")` / `String_Set("Raptisoft")`, then
`DAT_00b401a8 = this`) and by `0x0040BF00`; 666 sites read it.

`App+0x28` is an **elapsed-tick counter**. Slot 8 of `App::vftable` is
`0x00427800`, the inherited base-class tick, which the `App` does not override:

```c
if ((char)this->field_0x2C == 0 && this->field_0x68 == 0)   // not paused, not skipping
    this->field_0x28 += 1;                                   // param_1[10]++
```

That function appears in ~40 vtables across the binary — it is the shared base
tick — but its presence at slot 8 of `App::vftable` specifically is what makes
`App+0x28` count unpaused application ticks.

So the observed snapshot is explained without a clock: something constructed a
level or screen when the app had run `1485` unpaused ticks. Divisibility by
`3827` is the discriminating evidence — a coincidence at odds of roughly
`1/3827` under the clock hypothesis, which predicts nothing about it.

**The portability consequence is the load-bearing part.** Native RNG streams are
a function of *elapsed unpaused application ticks at the moment of level
construction*, not of game state. Two players who reach the same room with the
same save, the same published seed, and the same inputs will seed different
streams if they spent different amounts of time getting there. A port therefore
cannot reproduce native world generation, trader inventories, or drops from game
state alone; it must either carry the tick count as explicit state or accept that
its streams diverge from retail. This also explains why the snapshot is neither
the published seed `19088743` nor a post-generation state: `sd.rng.set_seed`
writes a value that the next level construction simply overwrites.

### Shared versus private streams

Most gameplay uses the global pointer, but the binary deliberately constructs
private `0xE8`-byte RNG objects at several semantic boundaries:

| System | Function | Seed/source | Stream behavior |
| --- | ---: | --- | --- |
| Startup/general gameplay | `0x0040CEB2` | `timeGetTime` | Persistent shared global at `0x00818B10`. |
| Loader deterministic run | native `0x00401120` | explicit `sd.rng.set_seed` value | Re-seeds shared global before stock generation. |
| Boneyard/arena generation | `0x006388B0` | one global `Integer(999999)` draw | Temporary private state, copied back to global. |
| Game object/run state | `0x005CC800` | one global `Integer(1000000)` draw stored at Game `+0x1AC8` | Initializes Game-private state at `+0x1ACC`. |
| Level-up offers | `0x0067CB70` | progression `+0x834` | Private stack stream for deterministic offer selection. |
| Enemy/item drops | `0x0047C070` | source actor `+0x1C0` | Private stack stream for that drop decision. |
| Demon Skull SpitFire action | `0x00449880` | source actor `+0x1C0` | Private stack stream for the action. |

Private streams mean that reproducing only the global state is insufficient
for mid-run save/replay. Their seed-owning actor/progression fields are part of
deterministic state.

### Gameplay call-site census

Headless xref census found 942 calls/references to the integer primitive across
295 containing functions, 1,511 float-primitive references across 408
functions, and 2,601 active-pointer references across 521 functions. These
counts include helpers and presentation effects, so they are a coverage bound,
not a count of independent gameplay decisions.

| Gameplay family | Representative addresses | Stream and observable use |
| --- | --- | --- |
| Arena/wave spawning | WaveSpawner `0x0046D000`; Boneyard `0x006388B0` | Shared/global seed flow chooses waves, placement, and generated arena content; Boneyard performs the transfer above. |
| Enemy construction | Spider `0x004759A0`, Skeleton `0x004771B0`, Maggot `0x0047E0F0` | Shared global; chooses per-instance base speed and other randomized constructor state. |
| Drops/rewards | `0x0047C070` | Actor-seeded private stream selects the drop; related world spawn/effects may consume global draws. |
| Level-up offers | `0x0067CB70` | Progression-seeded private stream. |
| Enemy attacks | SpitFire action `0x00449880`; attack/effect families under the global xrefs | Mix of actor-private action streams and shared global draws. |
| Damage values | Magic Missile handler `0x0053CFE0`; Storm Cloud `0x006021A0` | No universal damage-variance roll. Magic Missile samples between configured `mDamage1/mDamage2`; Storm Cloud uses RNG for effect/target/timing and damage-associated values, while many direct damage paths are deterministic. |
| Presentation coupled to gameplay | hit/audio/visual effect constructors throughout float xrefs | Usually global; these draws can advance the same stream as later gameplay and cannot simply be deleted from a bit-exact replay without stream partitioning. |

The key browser-port contract is draw order, not just distribution. Until call
sites are deliberately partitioned in a new protocol, every shared-stream
presentation draw must either be replayed or represented by an equivalent
advance or later gameplay will diverge.

## Live goldens

`movement-goldens.json` contains one native-tick sample series for each of:

- held east, west, south, and north, followed by release/coast;
- held southeast diagonal, followed by release/coast;
- the north wall at 0, 30, and 60 degrees; and
- a native `Knockback` event.

Each sample records native tick, center, per-tick delta and magnitude, the
native accumulated velocity, `actor+0x218`, live radius, observed intent, and
the scripted input applied for the next stock tick. The header also captures
all live baseline factors and the derived cap. The script resets placement and
velocity between trials and validates direction, diagonal distance, contact
plane, tangential slide, and Knockback displacement before writing JSON.

`rng-goldens.json` records isolated retail sequences for explicit reachable
seeds and positive bounds, plus all 55 final state words and indices. It also
records a read-only snapshot of the active stream. The recorder independently
replays the recovered recurrence in Python and refuses to write a fixture if any
output, index, or state word differs.

`float-rng-goldens.json` records 1,284 live calls across both retail float
primitives. The scaled primitive has 256-draw sequences at magnitudes `1`, `3`,
and `4.5` (including unsigned and signed requests), while the unit primitive has
256-draw unsigned and signed sequences; one-draw captures pin zero and positive
endpoints for both. Every draw records request parameters, exact pre-call and
post-call 55-word state, the object-local divisor, and the returned float32 bit
pattern. Independent replay reproduces every bit pattern, observes the expected
non-power-of-two one-rounding divergences, and proves that signed calls advance
two stream words while unsigned calls advance one. The fixture header
cross-links each sequence to its sealed raw recording and uses exact bit
patterns with no epsilon.

The integer corpus self-check covers the four recorded **sequences** only. It does not cover
the `observed_run_seed` snapshot, which is why the snapshot's `post-generation`
label survived capture despite being inconsistent with its own numbers — see
the subsection above. The four sequences are trustworthy and were independently
re-derived from this document's prose alone: 352 outputs, all 55 final state
words, and both ring indices reproduce bit-exactly across seeds `1`,
`19088743`, and the boundary seed `1073741823`, at ranges `16`, `100`, `1001`,
and `999999` — so the biased power-of-two-then-modulo mapping is pinned at both
power-of-two and non-power-of-two bounds.

The fixture `source` SHA names the clean recorder commit used for capture. The
later fixture/contract commit may therefore differ; this is intentional and
preserves the exact executable code that produced the recordings.

## Not Yet Reversed

One RNG lifecycle observation remains outside the recorded corpus.

| Element | State | What is missing |
| --- | --- | --- |
| Seeding lifecycle / run determinism | **Closed 2026-08-05** | The seeding idiom is `App[+0x28] * 0xEF3` at twelve byte-verified sites, `App+0x28` counts unpaused application ticks, and the recorded snapshot's `5683095` factors exactly as `1485 * 0xEF3`. See *Active stream and seeding lifecycle* above. What remains is not a gap in the mechanism but a consequence of it: run determinism is **not achievable from game state**, so `sd.rng.set_seed` cannot control world generation and no capture will ever show it doing so. The Boneyard `0x006388B0` private-stream transfer is still unobserved. |

Closing this remaining observation needs a live capture that seeds a run with a known value and
then reads the global at `0x00818B10` **before** generation, **after**
generation, and **after** the `0x0063895B` copy-back, so the three states can be
chained by replay. It is not reachable from the fixtures as they stand and must
not be guessed: a port that assumes `set_seed` is authoritative will produce
runs that diverge from native on the very first generated world. The float
primitive is no longer part of this section; its live corpus and exact replay
are documented under *Live goldens* above.

## Browser implementation contract

For G1 conformance, the browser simulation must:

1. advance gameplay at exactly 100 fixed ticks/s, independently of rendering
   and network publication;
2. preserve player input normalization, `+0.1` acceleration, vector cap,
   collision-before-damping ordering, `0.9/0.95` damping branches, and the
   `0.01` squared movement threshold using float32-equivalent math;
3. keep the final player move-step scalar distinct from the velocity cap;
4. use cadence-compensated direct movement for enemies and recover each
   constructor family's base-speed expression rather than inventing one
   generic speed field;
5. use the actor's live radius and ordered circle-vs-geometry resolution,
   including wall slide, convex radial corners, and secondary stop/alternate
   placement;
6. implement Knockback as bounded collision-aware radial MoveStep calls;
7. reproduce the 55/24 additive generator, seeding, biased bounded-integer
   mapping, inclusive float mapping, and shared/private stream boundaries; and
8. replay both JSON fixtures within their declared epsilon before claiming
   native movement/RNG parity.

The static contracts in `tests/re/static_re_native_sim_core_contracts.py` pin
these constants, addresses, fixture provenance, scenario coverage, and RNG
recurrence.
