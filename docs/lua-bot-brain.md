# Autonomous Lua bot brain

`mods/bot-brain/` is the opt-in reference brain for a host-owned synthetic
participant. It creates one fire-class player named `Ember` through
`sd.bots.spawn` and controls only the returned participant handle. The mod is
disabled by default so starting an ordinary game does not add an unsolicited
session member; select `bot.brain` to run it.

Its manifest dogfoods every v1 launcher setting type. With no persisted settings
file, the effective values remain the original behavior exactly: `Ember`, a
250 ms think cadence, a 340-unit kite radius, offense enabled, and no camera
keybind. The launcher can change the host-scoped kite radius and offense toggle,
choose a local 250/400 ms think profile, bind a local focus key, or invoke the
confirmed host-only respawn action. Persona changes are persisted with
`requires_restart` and are not applied to the live participant.

The brain never creates a standalone actor, writes an actor transform, or
drives a second native AI loop. Its callback runs every 250 ms on the existing
`runtime.tick` service, and `sd.state.is_authority()` keeps decisions on the
transport host. Clients receive the ordinary participant State, Frame, and Cast
traffic.

## Movement policy

Each think tick reads the address-free authority snapshot from
`sd.world.get_replicated_actors()` and keeps live rows whose
`tracked_enemy` flag is true. Enemies within 340 world units contribute an
inverse-distance-weighted vector pointing away from the threat. This leaves a
usable band inside the native fire-primary range instead of repelling the bot
before it can attack.

`sd.nav.get_grid(1)` supplies the current connected arena bounds. The brain
blends threat repulsion with an inward vector whose weight rises near the
perimeter. If the inward component would point back through a threat, the brain
keeps only its tangential component and caps its weight, so center recovery
cannot reverse the escape vector. When live enemies are outside both the
threat radius and cast range, it approaches the nearest enemy with the same
center bias, shortening that move to stop just inside the live native attack
window rather than crossing through the target. With no live enemy it orbits
the arena center, so it keeps moving during spawn gaps and wave transitions.
Candidate destinations are short look-ahead points clamped to those bounds.
Each candidate must first pass the native
`sd.nav.test_segment` placement-and-path query; accepted candidates are then
submitted through `bot:move_to`. The brain never substitutes its own cell-grid
test. Long approach destinations are held for one second before retargeting so
native player movement can advance instead of being reset every think tick.
Once a threat enters the kite radius, and throughout flee mode, the brain
retargets every 250 ms.

At less than 35% HP the bot enters flee mode. It increases the repulsion and
look-ahead weights, expands threat sampling to 900 units, continues center
recovery, and issues no casts. It returns to normal kiting only above 45% HP.

## Offense and progression

The brain asks `sd.bots.get_primary_attack_window` for the live fire-primary
range. It selects the nearest live enemy in that window and attempts
`bot:cast(0, target.x, target.y, 80)` on a bounded 500 ms cadence. Rejected
attempts remain rejected; there is no alternate damage path.

When the bot receives a native level-up choice, the brain resolves the current
generation through `sd.bots.get_skill_choices` and
`sd.bots.choose_skill`. It prefers Health Up, then Fireball, Explode, and
Embers when those stock choices are present, otherwise the first native option.

## Operational diagnostics

The mod publishes an address-free, read-only `bot_brain_debug` table in its own
Lua state for acceptance tooling. It reports the current mode, participant ID,
wave, HP, target, accepted movement and casts, skill choices, and accumulated
kite distance. It is not a gameplay control API.

The live verifier launches only `bot-host` and `bot-client` on ports 48811 and
48812 with audio disabled:

```bash
python3 tools/verify_lua_bot_brain.py --runs 3
```

It uses the retail staged `data/wave.txt` with no wave override. Each fresh
pair must reach wave 5 with the bot alive. The verifier writes a
`result.json` for every run containing an HP timeline, casts issued and
accepted, kite-path distance, level-up choices, terminal HP, exact process
cleanup, and copied runtime logs/status. It also captures both peers at wave 3
or later immediately after an accepted cast while live enemies and a target
are present. For that evidence frame only, the verifier uses the
presentation-local camera focus seam on each peer to center the bot, then
releases both focus requests. Three consecutive successful runs are required.

The settings-specific loopback gate is separate:

```bash
python3 tools/verify_mod_settings_lifecycle.py
```

It launches only `mset-host` and `mset-client` on ports 49011/49012 with audio
disabled. It proves persisted startup values, a 100-to-900 kite-radius live
delta in the brain's threat telemetry, host-to-client value and callback
replication, client action rejection, host respawn success, and
`requires_restart` persistence without live application. It stops only the
launcher-returned PIDs after their executable paths resolve inside those exact
stages and writes results and logs to
`/mnt/d/codex-evidence/mod-settings-20260727/`.
