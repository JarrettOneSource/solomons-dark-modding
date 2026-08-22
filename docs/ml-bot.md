# Learned bot

Lua Bots includes a learned policy that controls a real synthetic participant.
It chooses movement, a persisted enemy target, one mutually-exclusive ability,
and an aim offset. Native participant rails still own movement validation,
mana/cooldown checks, spell and consumable effects, damage, death, replication,
and collision.

## Use it in a normal game

Enable **Lua Bots**, add a row under **Bot roster**, set **Behavior** to
**Learned — ML movement and casting**, and choose its element and Discipline.
The bundled policy runs inside the mod's Lua state. Players do not need Python,
NumPy, a GPU, a model service, an account, or an internet connection. Learned
and scripted rows may coexist. Learned decisions occur every 100 ms of
simulation time; **Scripted bot cadence** affects only scripted behaviors.

## Web Port direction (2026-08-22)

The learned bot's runtime target is the Web Port; native bot-brain planning
is dropped. `docs/ml-bot-policy-web-port.md` amends the v3 contract for that
runtime (schema v5): it re-sources hostile hazards from the web simulation
and adds first-class blocks for the bot's own projectiles and persistent
areas (Block R) and for own and allied minions (Block S), none of which
v3/v4 observe; its same-day follow-ups re-source Blocks A-Q from the web
simulation (§6.2) and rule that the bot joins a session as a server-hosted
client through the ordinary `client-hello`/`client-input` path (W10), so
other clients see it as any other player. The sections below describe the
native v4 runtime as shipped.

## Policy v3 contract

The main policy has four masked heads:

- movement: idle or eight compass directions (9);
- target: keep the actor-ID-persisted target or choose one of eight enemy
  slots (9);
- ability: none, primary, eight secondaries, or twelve count-ranked potion
  slots (22); and
- aim: center or eight 60-world-unit compass offsets (9).

Lua selects the target before rebuilding ability legality against that target,
then rebuilds the aim mask against the selected ability. The composite action
log probability is the sum of all four selected-head log probabilities.
Movement uses `sd.nav.test_segment` only for its action mask. Native action
rails remain the final validators.

The policy receives exactly 1,333 ordered values. Schema v4 extends each of
the four pickup slots with Powerup and carried-item identity, and appends
Wizard Key count/possession to inventory. The existing blocks retain their
relative order: participant potion timers; enemy identity,
facing, telegraphs, and statuses; persisted-target motion/facing; eight exact
collision primitives; twelve hostile hazards; twelve ranked potion types;
seven equipped-item summaries; and bounded inventory taxonomy totals. Unknown
hostile hazards and carried items remain present without aliasing, using
`type_known=0` and `item_identity_known=0`. Inventory counts use
`log1p(min(count, 99)) / log(100)`. The canonical order is duplicated and
tested between `policy_spec.lua` and `tools/ml_bot/spec.py`.

Wizard Chug, Antidote, and Mind Chug are observable but permanently action
masked because no participant-scoped native effect route was proven. Health,
Mana, and Rejuvenation use proven native participant paths. A custom potion is
actionable only when its registration declares synthetic-safe
`policy_effects`. Equipment remains observation-only.

Aim offsets are available only to proven heading, point, line, and area spell
families. None, potions, homing, beam/cone, toggle, self, and radial families
are center-only.

Fixed scales are source-evidenced contract constants rather than fitted batch
statistics. Important values include mana 2,000, HP 1,000, velocity 1,000,
cooldown/status lifetime 60 seconds, range 1,000, radius 100, hazard contact
10 seconds, skill damage 500, skill duration 30 seconds, and count saturation
99. The complete list and evidence comments live in `policy_spec.lua`.

## Runtime and strict versioning

Architecture `mlp-tanh-four-head-v4` is:

1. 1,333 inputs;
2. shared tanh layers of 512 and 256 units;
3. masked 9/9/22/9 main heads and one scalar main value; and
4. a shared skill-option scorer.

At a pending native choice, the scorer joins the shared 256-value state latent
with each 56-value semantic option descriptor, applies one 128-unit tanh
option layer, and produces a shared scalar score. Masked softmax works over the
offered set, so option order and count do not change the parameter shape. A
separate scalar choice value uses the shared state latent.

Model, observation, main trajectory, and choice trajectory versions are all
4. Lua and Python validate every ordered name, tensor dimension, parameter
name, temperature, and finite value. Historical v1 and v2 JSON artifacts stay
in source history; both loaders reject versions 1-3 explicitly. There is no
adapter, migration shim, or reuse of old weights or data.

The checked-in runtime files are generated from one parameter map:

- `models/bot-brain/policy-v4.json`; and
- `mods/bot-brain/scripts/policy_weights.lua`.

The Lua artifact is larger than v2, so hot reload stages 512-KiB chunks under a
unique token. Lua compiles and validates the complete candidate before one
runtime swap and generation advance. A transfer failure clears staging without
changing the active policy.

## Bootstrap and validation

From a repository terminal:

```powershell
py -3 tools/train_bot_policy.py bootstrap
py -3 tools/train_bot_policy.py validate
```

Bootstrap starts from fresh v4 initialization. Its deterministic semantic
expert selects an enemy slot first, derives target-conditioned spell legality,
chooses potion use from vitals and ranked possession, labels aim from target
velocity and hazard context, and populates drop identities and key possession
independently of its action labels. It emits no skill-choice labels: the
retired scripted manager is never choice-head ground truth.

The checked-in seed used 6,000 samples and 20 epochs. Held-out accuracies are
movement 0.8692, target 0.7633, ability 0.7125, aim 0.9050, and four-head joint
0.4292. These are initialization checks, not a gameplay competence claim.
Main and choice value heads start at zero.

## Live PPO and choice SMDP training

Build the launcher and loader first, then run:

```powershell
py -3 tools/train_bot_policy.py live-ppo `
  --game-directory "C:\path\to\SolomonDarkAbandonware" `
  --iterations 10 `
  --rollout-steps 1024
```

Each environment episode owns a disposable headless authority session with
audio disabled. It receives a fresh native seed and logs the requested seed,
observed run nonce, layout hash, composition, and learned participant IDs.
Composition sizes come from `tools/ml_bot/team-compositions.json`; no parser or
training loop assumes the current participant cap.

`waves` is the default episode mode. It launches an isolated temporary profile
with the stock survival save, physically routes slot 0 through the exact
openable gate geometry, and invokes the real Solomon Dig conversation. It does
not call `start_waves`, spawn an enemy, or synthesize XP. The stock wave
spawner, enemy death reward, participant-owned synthetic progression, and
native skill-offer paths therefore remain intact. The retail reward helper is
hard-wired to slot 0. The host now lets that one stock call compute the
canonical scaled XP total, then synchronizes the exact level/XP/next-threshold
snapshot into every in-run participant's owned native progression. Any
participant's kill therefore advances the party and produces the ordinary
per-participant native choice flow at the same level cadence. Collection's
normal integration guard requires only a positive learned-participant XP delta;
an episode without a level or choice remains valid. The opt-in
`--require-natural-choice-proof` acceptance probe additionally requires one
natural level, learned choice apply, and complete choice interval in the first
episode only. `--episode-mode curriculum` retains the
direct-spawn, XP-free one-enemy arena for targeted observation/action drills;
it is not suitable for choice-head training.

The disposable trainer owner's stock slot levels with the party and can open
the host-self native picker. In headless collection, the bridge selects its
first native-valid option and waits for the multiplayer level-up barrier to
clear. That trainer-owned selection is logged separately and never becomes a
learned choice event, scripted label, or PPO batch row.

Training is enabled before the stock wave begins, so every natural XP and
native skill-offer event is captured. After the positive-XP integration gate,
setup-time main rows are cleared while any open choice interval and its
duration rewards are preserved; choice state is never reset. Every
learned participant sharing the policy emits two streams:

- main trajectory-v4: observations, four masks/actions, composite old log
  probability, value, reward, and terminal state; and
- choice-event-v4: frozen observation, variable option rows/mask, selected
  option, old log probability/value, next choice value, duration, per-step
  rewards, acceptance, and terminal state.

The episode-finalization API closes pending main and choice intervals before
drain. Scripted choice events stay tagged `trainable=false` through bridge
transport, then are partitioned out before choice PPO batching. This keeps
mixed-team drain counts exact without turning the scripted manager into a
training label. The trainer never sends an open interval to choice PPO. Main
rows drain in 16-record frames and choice intervals one at a time so the
expanded v4 payload stays below the loader's fixed 1-MiB Lua-exec response
limit. Live rollouts are bounded to 8,192 steps for the same reason.

The reward stream has no passive survival term. One policy decision receives
only the existing health/damage, wave, and terminal signals plus positive
killer-attributed native XP progress:

```text
reward = 1.25 * self_hp_ratio_delta
       + 0.65 * own_source_enemy_hp_ratio_damage
       + max(0, own_kill_xp_delta) / 25
       + 1.5 * min(max(wave_delta, 0), 1)
       - 2.0 when terminal and dead
reward = clamp(reward, -4, 4)
```

`XP_SCALE=25` comes from a stock-wave calibration over waves 1–10: 39
learned-attributed kills credited 3.442497–3.825001 XP, median 3.824997, so a
typical early kill contributes 0.153 reward. An unchanged bot facing live
enemies earns exactly zero. Shared XP from a teammate still advances the bot's
level and choices, but neither that XP nor teammate-sourced enemy damage enters
its reward counters. Choice-event intervals continue to consume the same
per-decision rewards without a separate shaping path. This changes the
meaning of all future reward curves but does not change the trajectory schema
or its version.

Main PPO uses ordinary per-participant GAE and four clipped policy heads. The
choice stream uses the adjudicated semi-Markov calculation for duration `d`:

```text
R = sum(k=0..d-1) gamma^k reward[k]
delta = R + gamma^d (1-done) V_next - V
A = delta + (gamma lambda)^d (1-done) A_next
```

Choice batches accumulate complete intervals across disposable sessions until
`--minimum-choice-batch` (default 32), then update the shared trunk, option
scorer, and choice value. Main and choice optimizers have independent Adam
state. Every checkpoint contains all parameters and choice-coverage state;
JSON and Lua files are each written through a temporary file and atomically
replaced before chunked hot reload. Each live episode also writes an atomic
`episode-NNNN.json`; `live-training-report.json` records the complete seed,
nonce, layout, composition, participant, trajectory, loss, and reload evidence.
Per-episode JSON also records the exact final XP delta for every learned
participant and the aggregate positive-XP guard result.

Without an explicit `--rollout-timeout`, collection allows
`max(180, 60 + rollout_steps / 10 * 1.25)` seconds. This covers the worst-case
single-learned-bot 10-Hz record cadence with 25 percent headroom and 60 seconds
of session allowance; the explicit flag remains an exact override. For
example, 1,024 steps allow 188 seconds and 8,192 steps allow 1,084 seconds.

Main entropy coefficients are movement 0.01, target 0.02, ability 0.01, and
aim 0.01. Target receives twice the pressure because `keep_current` is often
legal. Choice entropy is 0.05 after normalization by `log(valid option count)`;
a one-option event contributes zero normalized entropy. Choice softmax starts
at temperature 1.25. It changes to 1.0 only after every observed offered
family and weld-pair key has been selected at least 20 times. Coverage and the
current temperature persist in checkpoint metadata.

## Known limitations

- The v3 seed and short V3-5 PPO smoke are pipeline validation, not a learned
  competence claim.
- Wizard Chug, Antidote, and Mind Chug cannot be selected until a proven
  synthetic participant native effect path exists.
- Equipment is observed but cannot be equipped by the policy.
- The main trunk is feed-forward; actor-ID persistence and velocity histories
  are maintained in Lua, not recurrent model state.
- Native descriptor coverage remains explicit: unresolved secondary
  range/cooldown fields are not invented, and native action validation remains
  authoritative.
- Stock Arrow hazards currently expose neither a resolved target participant
  nor a positive time to contact. They remain observable as known hostile
  projectiles; Lua and verifiers do not invent those fields.
- The controlled one-enemy arena intentionally has no stock XP reward context
  and is curriculum plumbing only. Default training uses stock waves; broader
  builds and a multi-layout corpus remain evaluation work.
- The policy does not observe its own projectiles or persistent areas
  (Block N is hostile-only), nor its own or allied golems (neither
  `tracked_enemy` nor participants, and no script reads `native_minion*`).
  `ml-bot-policy-web-port.md` §1 records the gap; the Web Port amendment
  closes it with Blocks R and S.
- Enemy wind-up/strike/recovery is resolved for 3 of 19 species (DemonSkull,
  Dire Faculty, Imp Portal); the rest expose only the raw animation byte.
  The Web Port amendment (§6.1) replaces this with the exact web action
  clock.

## Install a trained checkpoint

```powershell
py -3 tools/train_bot_policy.py validate `
  --model runtime/ml-training/<instance>/policy-final.json `
  --lua mods/bot-brain/scripts/policy_weights.lua

Copy-Item `
  runtime/ml-training/<instance>/policy-final.json `
  models/bot-brain/policy-v4.json
```

Keep JSON and Lua exports from the same checkpoint. Contract, numerical PPO,
SMDP, strict-version, serialization, and inference-parity coverage lives in
`tests/test_ml_bot_policy.py`, `tests/lua/ml_bot_policy_contract.lua`, and
`tests/re/static_lua_ml_bot_contracts.py`.
