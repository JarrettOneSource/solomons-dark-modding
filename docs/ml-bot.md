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

The policy receives exactly 1,279 ordered values. Positions 1-395 preserve the
v2 prefix. Blocks J-Q append participant potion timers; enemy identity,
facing, telegraphs, and statuses; persisted-target motion/facing; eight exact
collision primitives; twelve hostile hazards; twelve ranked potion types;
seven equipped-item summaries; and bounded inventory taxonomy totals. Unknown
hostile hazards remain present with `type_known=0`. Inventory counts use
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

Architecture `mlp-tanh-four-head-v3` is:

1. 1,279 inputs;
2. shared tanh layers of 512 and 256 units;
3. masked 9/9/22/9 main heads and one scalar main value; and
4. a shared skill-option scorer.

At a pending native choice, the scorer joins the shared 256-value state latent
with each 56-value semantic option descriptor, applies one 128-unit tanh
option layer, and produces a shared scalar score. Masked softmax works over the
offered set, so option order and count do not change the parameter shape. A
separate scalar choice value uses the shared state latent.

Model, observation, main trajectory, and choice trajectory versions are all
3. Lua and Python validate every ordered name, tensor dimension, parameter
name, temperature, and finite value. Historical v1 and v2 JSON artifacts stay
in source history; both loaders reject either version explicitly. There is no
adapter, migration shim, or reuse of old weights or data.

The checked-in runtime files are generated from one parameter map:

- `models/bot-brain/policy-v3.json`; and
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

Bootstrap starts from fresh v3 initialization. Its deterministic semantic
expert selects an enemy slot first, derives target-conditioned spell legality,
chooses potion use from vitals and ranked possession, and labels aim from
target velocity and hazard context. It emits no skill-choice labels: the
retired scripted manager is never choice-head ground truth.

The checked-in seed used 6,000 samples and 20 epochs. Held-out accuracies are
movement 0.8850, target 0.7617, ability 0.7175, aim 0.9158, and four-head joint
0.4583. These are initialization checks, not a gameplay competence claim.
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

Training is enabled before learned participants materialize, so their native
skill offers are captured instead of being consumed by trainer priming. Once
the curriculum arena is ready, setup-time main rows are cleared while their
already-closed rewards/durations remain in the open choice interval; choice
state is never reset. Every learned participant sharing the policy emits two
streams:

- main trajectory-v3: observations, four masks/actions, composite old log
  probability, value, reward, and terminal state; and
- choice-event-v3: frozen observation, variable option rows/mask, selected
  option, old log probability/value, next choice value, duration, per-step
  rewards, acceptance, and terminal state.

The episode-finalization API closes pending main and choice intervals before
drain. Scripted choice events stay tagged `trainable=false` through bridge
transport, then are partitioned out before choice PPO batching. This keeps
mixed-team drain counts exact without turning the scripted manager into a
training label. The trainer never sends an open interval to choice PPO. Main
rows drain in 16-record frames and choice intervals one at a time so the
expanded v3 payload stays below the loader's fixed 1-MiB Lua-exec response
limit. Live rollouts are bounded to 8,192 steps for the same reason.

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

For acceptance-only SMDP plumbing, `--validation-native-choice-event` invokes
one debug native level-up per episode. The learned scorer still chooses and
applies the option and the ordinary choice-event-v3 path owns duration, reward,
terminal close, transport, and PPO. The switch is off by default and should
not be used for normal training.

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
- The controlled one-enemy arena is curriculum plumbing, not a competence
  evaluation. Normal waves, elites, broader builds, and a multi-layout corpus
  belong to later evaluation.

## Install a trained checkpoint

```powershell
py -3 tools/train_bot_policy.py validate `
  --model runtime/ml-training/<instance>/policy-final.json `
  --lua mods/bot-brain/scripts/policy_weights.lua

Copy-Item `
  runtime/ml-training/<instance>/policy-final.json `
  models/bot-brain/policy-v3.json
```

Keep JSON and Lua exports from the same checkpoint. Contract, numerical PPO,
SMDP, strict-version, serialization, and inference-parity coverage lives in
`tests/test_ml_bot_policy.py`, `tests/lua/ml_bot_policy_contract.lua`, and
`tests/re/static_lua_ml_bot_contracts.py`.
