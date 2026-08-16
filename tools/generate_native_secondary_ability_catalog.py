#!/usr/bin/env python3
"""Build the closed stock right-click ability catalog from checked-in RE data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RE = ROOT / "docs" / "reverse-engineering"
OUTPUT = RE / "native-secondary-ability-catalog.json"
SKILLS = RE / "native-skill-catalog.json"
AUDIO = RE / "native-audio-catalog.json"

SECONDARY_IDS = (
    11, 12, 15, 21, 23, 27, 30, 35, 41, 45, 46, 48,
    49, 50, 51, 54, 72, 73, 74, 76, 77, 78, 79,
)


def actor(type_id: str, name: str) -> dict[str, str]:
    return {"type_id": type_id, "name": name}


def art(atlas: str, records: str, owner: str, mode: str) -> dict[str, str]:
    return {"atlas": atlas, "records": records, "owner": owner, "mode": mode}


def sound(path: str, trigger: str, mode: str = "one_shot") -> dict[str, str]:
    return {"path": path, "trigger": trigger, "mode": mode}


CONTRACTS: dict[int, dict[str, Any]] = {
    11: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7F2", "Leviathan"), actor("0x7F3", "EtherBolt")],
        "gameplay": "Scale in, maintain mQuantity independently tracking appendages, fire straight EtherBolts with mDamage, then scale out; bolts live 100 ticks plus fade and contact only under caster authority.",
        "timing": {"phases": ["scale_in", "active", "scale_out"], "bolt_lifetime_ticks": 100},
        "art": [
            art("BadGuys", "343..372", "Leviathan appendage/body compositor", "world_depth_sorted"),
            art("BadGuys", "11,39", "Leviathan child flashes and EtherBolt", "additive"),
        ],
        "audio": [
            sound("sounds/LeviathanRoar__Stream.wav", "Leviathan activation", "stream"),
            sound("sounds/PlaneCross__Loop.wav", "renewed while the ether actor is active", "ambient_loop_request"),
        ],
        "authority": "Caster authority selects targets, creates EtherBolts, and applies their contacts; presentation actors are replicated snapshots.",
        "cleanup": "Leviathan owns its appendage list and retires after scale-out; EtherBolts retire on contact or post-100-tick fade; region teardown stops loop renewal.",
        "evidence": ["0x0054CC50", "0x006145D0", "0x006151D0", "0x006034F0"],
    },
    12: {
        "targeting": "self",
        "trigger": "toggle_or_expiry",
        "actors": [actor("0x1B75", "Mod_Planewalker"), actor("0x7EF", "PlaneOrb")],
        "gameplay": "Enable matterless plane state for mDuration, save the prior primary, force runtime skill 80 Plane Orb, merge by maximum remaining duration, and restore the saved primary on toggle-off or expiry.",
        "timing": {"duration": "mDuration * 100 fixed ticks"},
        "art": [art("BadGuys", "PlaneOrb actor contract", "forced Plane Orb primary", "additive_world")],
        "audio": [
            sound("sounds/planewalker__Stream.wav", "enable", "stream"),
            sound("sounds/PlanewalkerOff__Stream.wav", "disable or modifier expiry", "stream"),
            sound("sounds/PlaneCross__Loop.wav", "renewed while plane state is active", "ambient_loop_request"),
        ],
        "authority": "The authoritative player owns modifier duration, collision flag 0x10, saved-primary restoration, and Plane Orb contacts.",
        "cleanup": "Modifier removal at 0x00623810 calls 0x0052F470, clears plane state, restores selection, and stops renewing plane ambience.",
        "evidence": ["0x0054CC50", "0x00548700", "0x00623800", "0x00623810", "0x0052F470", "0x00626A60"],
    },
    15: {
        "targeting": "aim_heading_forward_probe",
        "trigger": "press_edge_with_skill_cooldown",
        "actors": [],
        "gameplay": "Probe at most 20 forward positions along cast heading, relocate to the first collision-clear point, and update world membership atomically.",
        "timing": {"probe_limit": 20, "cooldown": "mCooldown * 100 fixed ticks"},
        "art": [art("BadGuys", "53", "Anim_FadeAdditive traversal markers", "additive_world")],
        "audio": [sound("sounds/phase.wav", "accepted relocation")],
        "authority": "Only the authoritative simulation resolves collision and commits the destination; observers consume the resulting position and traversal event.",
        "cleanup": "Traversal children are world-owned and self-expire; rejected probes spend no extra cooldown beyond the native cast gate.",
        "evidence": ["0x0054CC50", "0x0052A0B0", "0x0063FEE0"],
    },
    21: {
        "targeting": "caster_center",
        "trigger": "press_edge",
        "actors": [actor("0x7E6", "MovingFire"), actor("0x7E7", "Shockwave")],
        "gameplay": "Create exactly 30 moving fire segments at 12-degree steps with jitter and one expanding Shockwave; the wave damages, dazzles once per target, and pushes tracked targets radially.",
        "timing": {"segment_count": 30, "angle_step_degrees": 12, "shockwave_query_period_ticks": 10},
        "art": [art("DeadHawg", "46..77", "MovingFire frame strip", "additive_world")],
        "audio": [
            sound("sounds/bigfire.wav", "ring creation"),
            sound("sounds/nuke.wav", "shockwave creation"),
        ],
        "authority": "Caster authority creates segments and the wave, owns unique-target contact, and applies radial displacement.",
        "cleanup": "Each fire segment follows Fire lifetime/fade; Shockwave removes itself after expansion and releases its unique-target list.",
        "evidence": ["0x0054CC50", "0x0063F920", "0x005FF8C0", "0x00610F90"],
    },
    23: {
        "targeting": "self_trail",
        "trigger": "toggle",
        "actors": [actor("0x7EE", "Fire_Goodguy")],
        "gameplay": "Toggle progression +0x8DC; while active the player tick emits damaging Fire_Goodguy trail patches and reserves exactly 50 MP as an absolute hoard.",
        "timing": {"patch_lifetime_ticks": 200, "contact_period_ticks": 3, "mana_reserve": 50},
        "art": [
            art("DeadHawg", "46..77", "Fire_Goodguy animation", "additive_world"),
            art("BadGuys", "11", "player-tick moving additive ember", "additive_world"),
        ],
        "audio": [
            sound("sounds/ignite.wav", "toggle activation with native pitch triplet"),
            sound("sounds/lowfire__loop.wav", "renewed by live fire patches", "ambient_loop_request"),
        ],
        "authority": "The authoritative player owns toggle, reserve, trail cadence, and Fire contacts; patches carry owner identity.",
        "cleanup": "Toggle-off stops new patches and removes the reserve; existing patches complete their own 200-tick fade/contact lifetime.",
        "evidence": ["0x0054CC50", "0x00548B00", "0x005FF050", "0x005FF1D0", "0x00610F90"],
    },
    27: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7F0", "StormCloud")],
        "gameplay": "Spawn a stationary storm for 1000 active ticks, randomly select hostile targets at the native 30..120 cadence, roll mDamage1..mDamage2, and generate lightning geometry; Magic Tornado upgrades frequency and duration without changing the base placement contract.",
        "timing": {"active_ticks": 1000, "strike_reset_ticks": "uniform integer 30..120, divided by tornado frequency factor"},
        "art": [art("BadGuys", "cloud particles plus record 11 lightning children", "StormCloud tick/draw", "alpha_ramp_additive_world")],
        "audio": [
            sound("sounds/magicstorm.wav", "accepted cast"),
            sound("sounds/lightningstart.wav", "each strike"),
            sound("sounds/thunder__Stream.wav", "strike presentation", "stream"),
            sound("sounds/rainfall__loop.wav", "renewed while cloud is active", "ambient_loop_request"),
            sound("sounds/steadywind__loop.wav", "renewed while cloud is active", "ambient_loop_request"),
        ],
        "authority": "Caster authority chooses targets, consumes RNG, and applies damage; all strike points and short energy state are snapshot-visible.",
        "cleanup": "After 1000 active ticks the cloud fades, ceases target queries, then retires and stops ambient renewal.",
        "evidence": ["0x0054CC50", "0x005E22E0", "0x006021A0", "0x005E8970"],
    },
    30: {
        "targeting": "caster_center_rectangle",
        "trigger": "press_edge",
        "actors": [actor("0x1B76", "Mod_Prismatic")],
        "gameplay": "Emit the prismatic cast wave, query the hostile rectangle, and attach/merge a duration modifier that doubles lightning susceptibility.",
        "timing": {"duration": "mDuration * 100 fixed ticks"},
        "art": [art("BadGuys", "10,11", "prismatic additive wave children", "additive_world")],
        "audio": [
            sound("sounds/prismaticspray__stream.wav", "accepted cast", "stream"),
            sound("sounds/lightningstart.wav", "wave spark with native pitch"),
        ],
        "authority": "Caster authority owns rectangle membership and modifier attachment; modifier duration/status is replicated with the target.",
        "cleanup": "World-owned wave children self-expire; the target-owned modifier expires or merges by native modifier rules.",
        "evidence": ["0x0054CC50", "0x00645540", "0x00627230"],
    },
    35: {
        "targeting": "caster_center",
        "trigger": "press_edge",
        "actors": [actor("0x7E8", "FreezeWave")],
        "gameplay": "Create three ice-blast bursts, radial debris, and an expanding wave which applies ColdSlow or Frozen once per target, optional FrostBurn, and configured freeze payload.",
        "timing": {"query_period_ticks": 10, "ice_blast_count": 3},
        "art": [art("DeadHawg", "16,17", "radial ice burst/debris", "additive_world")],
        "audio": [sound("sounds/ringofice.wav", "wave creation")],
        "authority": "Caster authority owns the unique-target list, status selection, contact, and optional item-effect branch.",
        "cleanup": "FreezeWave and registered burst children self-expire after expansion/fade and release target references.",
        "evidence": ["0x0054CC50", "0x00644460", "0x005FFDC0"],
    },
    41: {
        "targeting": "caster_center",
        "trigger": "press_edge",
        "actors": [actor("0x7F1", "Earthquake")],
        "gameplay": "Shake the world for mDuration, every 30 ticks query hostile actors and disrupt up to half after shuffling; it deals no direct damage.",
        "timing": {"duration": "mDuration * 100 fixed ticks", "disrupt_period_ticks": 30},
        "art": [
            art("DeadHawg", "200..202", "registered floor crack fragments", "world_depth_sorted"),
            art("BadGuys", "2008..2010,62", "boulder debris and lit children", "additive_world"),
        ],
        "audio": [
            sound("sounds/earthquake__loop.wav", "renewed while intensity is nonzero", "ambient_loop_request"),
            sound("sounds/QuakeCracks__Stream.wav", "large crack event", "stream"),
            sound("sounds/QuakeCrackSmall__Stream.wav", "small crack event", "stream"),
            sound("sounds/rockhit.wav", "debris impact"),
        ],
        "authority": "Caster authority shuffles targets and cancels/pauses actions; world shake and debris are presentation state.",
        "cleanup": "Counter zero retires the actor, clears world-shake contribution, releases its pointer list, and stops quake-loop renewal.",
        "evidence": ["0x0054CC50", "0x005E8EA0", "0x00613200", "0x00613E10"],
    },
    45: {
        "targeting": "collision_adjusted_aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7F4", "Golem"), actor("0x7E9", "Knockback")],
        "gameplay": "Enforce one summon or two with Iron Golem, assemble at ages 0/50/100/200, activate contact at age 400, acquire/chase/attack hostiles, and reflect incoming primary damage when upgraded.",
        "timing": {"assembly_milestones": [0, 50, 100, 200], "contact_enable_age": 400, "natural_expiry": False},
        "art": [
            art("Golem", "1..208", "articulated body-part compositor", "world_depth_sorted"),
            art("BadGuys", "15,36,62,86,238..245,2008..2010", "assembly, attack, and child effects", "mixed_world"),
            art("DeadHawg", "78..87", "death fragments", "world_depth_sorted"),
            art("UI", "23", "summon status marker", "screen_overlay"),
        ],
        "audio": [
            sound("sounds/QuakeCrackSmall__Stream.wav", "assembly milestones", "stream"),
            sound("sounds/GolemProvoke__Stream.wav", "provoke", "stream"),
            sound("sounds/KnockbackGolem.wav", "attack impact"),
            sound("sounds/stonestep.wav", "movement step"),
            sound("sounds/GolemDie__Stream.wav", "death", "stream"),
            sound("sounds/stonebreak.wav", "death fragment release"),
            sound("sounds/rockhit.wav", "assembly/death impact"),
        ],
        "authority": "Caster authority owns cap replacement, AI, target identity, contact, reflection, death, and child Knockback creation.",
        "cleanup": "No natural expiry; replacement, death, disconnect, or region teardown retires body/AI and releases child collections while registered fragments finish independently.",
        "evidence": ["0x0054CC50", "0x005F57E0", "0x005F5B40", "0x00615CD0", "0x00617820", "0x00607F60", "0x00619730"],
    },
    46: {
        "targeting": "self",
        "trigger": "press_edge_refreshable",
        "actors": [actor("0x1B71", "Mod_StoneSkin")],
        "gameplay": "Attach a duration modifier which sets actor flag 0x1 and makes the wizard impervious; reapplication retains the greater remaining duration.",
        "timing": {"duration": "mDuration * 100 fixed ticks"},
        "art": [art("player", "actor flag 0x1 material treatment", "target-owned modifier presentation", "actor_overlay")],
        "audio": [
            sound("sounds/StoneSkin__Stream.wav", "accepted cast", "stream"),
            sound("sounds/stoneskin.wav", "modifier apply/refresh callbacks"),
        ],
        "authority": "The authoritative player owns modifier duration and rejects physical/magical damage while active.",
        "cleanup": "Expiry or teardown clears invulnerability/tint and emits the removal presentation exactly once.",
        "evidence": ["0x0054CC50", "0x006237A0", "0x00624490", "0x006244C0", "0x00626840"],
    },
    48: {
        "targeting": "safe_relocation_near_aim",
        "trigger": "press_edge_with_skill_cooldown",
        "actors": [],
        "gameplay": "Ask the world relocation query for a safe nearby destination and atomically move the wizard to the accepted point.",
        "timing": {"cooldown": "mCooldown * 100 fixed ticks"},
        "art": [art("BadGuys", "90", "teleport additive burst", "additive_world")],
        "audio": [sound("sounds/teleport.wav", "accepted teleport")],
        "authority": "Only authoritative world collision selects and commits the destination; observers render the relocation event.",
        "cleanup": "Registered burst children self-expire; rejected relocation leaves no persistent actor.",
        "evidence": ["0x0054CC50", "0x00644A00"],
    },
    49: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7EA", "MagicCircle"), actor("0x1B70", "Mod_CircleSlow")],
        "gameplay": "Maintain a 1500-tick circle, every 10 ticks slow eligible enemies and restore local MP at twice normal recovery; retain the shipped inert HP branch.",
        "timing": {"lifetime_ticks": 1500, "effect_period_ticks": 10},
        "art": [
            art("BadGuys", "48", "per-tick ring particle", "additive_world"),
            art("BadGuys", "7", "Anim_SpinAwayAdditive effect child", "additive_world"),
        ],
        "audio": [sound("sounds/magiccircle.wav", "actor lifetime reaches 1498")],
        "authority": "Caster authority owns slow attachment and local MP recovery; circle/color/lifetime state is replicated.",
        "cleanup": "At zero lifetime the circle unregisters; world-owned spin-away children finish independently.",
        "evidence": ["0x0054CC50", "0x0063FDE0", "0x006006E0", "0x005F3CA0", "0x005FB020"],
    },
    50: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7F5", "MagicTrap"), actor("0x1B73", "Mod_Burn"), actor("0x1B6B", "Mod_ElectricBurn"), actor("0x1B69", "Mod_ColdSlow")],
        "gameplay": "Bind the current primary element and base damage into a trap, charge linearly to full over 800 ticks, poll every 25 ticks, then detonate once for charge-scaled damage and the element-specific status.",
        "timing": {"full_charge_ticks": 800, "trigger_poll_period_ticks": 25},
        "art": [
            art("BadGuys", "393..400,16", "charging trap body and shimmer", "additive_world"),
            art("BadGuys", "158..167,15", "element-colored trigger burst", "additive_world"),
        ],
        "audio": [
            sound("sounds/settrap__Stream.wav", "trap initialization", "stream"),
            sound("sounds/trap__stream.wav", "one-shot trigger", "stream"),
        ],
        "authority": "Caster authority derives the primary payload, owns charge/query RNG, applies contacts/statuses, and removes the trap.",
        "cleanup": "Trigger is terminal and removes the trap after emitting world-owned children; ordinary teardown releases the Puppet without replaying trigger effects.",
        "evidence": ["0x0054CC50", "0x005E95D0", "0x00603710", "0x005F5C80", "0x00619CD0"],
    },
    51: {
        "targeting": "caster_center_rectangle",
        "trigger": "press_edge",
        "actors": [actor("action:21", "Action_PlayerWizard_CastSpin")],
        "gameplay": "Remove hostile guided/fire/dark missiles in range, disrupt hostile casters, roll RandomInt(100) < 0x33 (51 accepted values despite the authored 50 percent display text) to dispel shields, and queue the 73-tick cast-spin action.",
        "timing": {"cast_spin_ticks": 73, "shield_dispel_numerator": 51, "shield_dispel_denominator": 100},
        "art": [art("BadGuys", "10,11,48", "dampen flash and additive wave children", "additive_world")],
        "audio": [
            sound("sounds/flash.wav", "accepted cast"),
            sound("sounds/dampen__stream.wav", "accepted cast", "stream"),
        ],
        "authority": "Caster authority owns projectile removal, action disruption, and shield-dispel RNG; action pose is replicated presentation.",
        "cleanup": "World children self-expire; cast spin is atomic except death and completes after its strict phase boundary.",
        "evidence": ["0x0054CC50", "0x00648DF0", "0x00448860"],
    },
    54: {
        "targeting": "self",
        "trigger": "press_edge_refreshable",
        "actors": [],
        "gameplay": "Install or refresh mAbsorb on the wizard; incoming damage drains the pool and drives a 40-tick hit pulse. If Explosive Shield is learned, break damage is absorb times mDamage/100.",
        "timing": {"hit_pulse_ticks": 40, "hit_pulse_start": 2.0, "hit_pulse_decay_per_tick": 0.05},
        "art": [art("BadGuys", "68", "20 Anim_FadeAdditive particles on shield break", "additive_world")],
        "audio": [
            sound("sounds/magicshieldup.wav", "install or refresh"),
            sound("sounds/hitshield.wav", "absorbed hit"),
            sound("sounds/popshield.wav", "shield break"),
            sound("sounds/magicshieldexplode.wav", "Explosive Shield radial contact"),
        ],
        "authority": "Authoritative damage contact drains absorb and conditionally creates the radial break contact; pulse/break sequence is snapshot-visible.",
        "cleanup": "Break clears absorb and explosive factor after one particle/contact event; death, disconnect, and region teardown clear the residual pulse.",
        "evidence": ["0x0054CC50", "0x00529EE0", "0x00546650", "0x00648790", "0x0054BA80"],
    },
    72: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x7FE", "AcidRain"), actor("animation", "Anim_AcidRaindrop")],
        "gameplay": "Rain for 1500 active ticks, emit two drops per tick or five with Enhanced Effects, and after the startup delay shuffle hostile candidates and damage exactly min(n, floor(n/3)+1) every 25 ticks; damage is direct, not poison.",
        "timing": {"active_ticks": 1500, "damage_period_ticks": 25, "drops_per_tick": 2, "enhanced_drops_per_tick": 5, "targets_per_pulse": "min(n, floor(n/3)+1)"},
        "art": [art("BadGuys", "10 plus AcidRaindrop child art", "rain/drop/residue renderers", "additive_world")],
        "audio": [
            sound("sounds/magicstorm.wav", "accepted cast"),
            sound("sounds/acidsizzle.wav", "damage/residue pulses with native pitch"),
            sound("sounds/rainfall__loop.wav", "renewed through active rain and residue", "ambient_loop_request"),
        ],
        "authority": "Caster authority shuffles candidates and applies direct periodic damage; drops/residue are presentation state.",
        "cleanup": "The actor retires only after active lifetime and residue fade both end; loop renewal stops with residue ownership.",
        "evidence": ["0x0054CC50", "0x005E3540", "0x00604E90", "0x005E3600", "0x005EB290", "0x005EB1D0"],
    },
    73: {
        "targeting": "line_perpendicular_to_aim",
        "trigger": "press_edge",
        "actors": [actor("0x7EE", "Fire_Goodguy")],
        "gameplay": "Create eleven independently damaging Fire_Goodguy patches at 30-unit intervals across the 300-unit line perpendicular to aim; each patch contacts nearby hostiles every third tick.",
        "timing": {
            "patch_count": 11,
            "line_length": 300,
            "patch_spacing": 30,
            "patch_lifetime_scalar": 7,
            "patch_lifetime_ticks": 700,
            "contact_period_ticks": 3,
        },
        "art": [art("DeadHawg", "46..77", "Fire_Goodguy strip for every wall patch", "additive_world")],
        "audio": [
            sound("sounds/ignite.wav", "wall creation"),
            sound("sounds/fireballhit.wav", "wall creation accent"),
            sound("sounds/lowfire__loop.wav", "renewed while patches are live", "ambient_loop_request"),
        ],
        "authority": "Caster authority resolves wall geometry, creates patches, and owns their repeated contacts.",
        "cleanup": "Patches fade and retire independently after the overwritten life scalar 7 reaches zero at 0.01 per tick (700 ticks); teardown stops their low-fire renewal.",
        "evidence": ["0x0054CC50", "0x005FF050", "0x005FF1D0", "0x00610F90"],
    },
    74: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x807", "EtherDrain")],
        "gameplay": "Scale in for 40 ticks, refresh covered-cell candidate identities, pull actors and eligible loot inward, apply mDamage close to center for 1000 active ticks, consume empty/ordinary loot at center, then scale out for 20 ticks.",
        "timing": {
            "scale_in_ticks": 40,
            "active_ticks": 1000,
            "scale_out_ticks": 20,
            "phases": ["scale_in", "active", "scale_out"],
        },
        "art": [art("DeadHawg", "177..179", "pressure-field animated core", "additive_world")],
        "audio": [
            sound("sounds/distortreality.wav", "state transition"),
            sound("sounds/lightningstart.wav", "state transition with native pitch"),
            sound("sounds/PlaneCross__Loop.wav", "renewed while field is active", "ambient_loop_request"),
            sound("sounds/steadywind__loop.wav", "renewed while field is active", "ambient_loop_request"),
        ],
        "authority": "Caster authority owns candidate identity arrays, forces, contacts, and loot consumption; visual children are replicated.",
        "cleanup": "Scale-out precedes retirement; destructor releases both PuppetRef arrays and cell lists while registered children self-expire.",
        "evidence": ["0x0054CC50", "0x005F8360", "0x006060C0", "0x0061CF20", "0x00606580", "0x005F8620", "0x005EE120", "0x005EE780"],
    },
    76: {
        "targeting": "aimed_world_point",
        "trigger": "press_edge",
        "actors": [actor("0x80C", "Comet"), actor("0x7E8", "FreezeWave")],
        "gameplay": "Count down a falling comet while emitting ice-blast children, impact for mDamage, create the shared FreezeWave with mFreeze, query the area, restore world color, and retire.",
        "timing": {"impact": "when actor +0x14C countdown reaches zero"},
        "art": [
            art("DeadHawg", "5", "falling comet body", "world_depth_sorted"),
            art("BadGuys", "51,15", "trail and impact children", "additive_world"),
            art("DeadHawg", "203..207,6", "impact burst/debris", "mixed_world"),
        ],
        "audio": [
            sound("sounds/comet__loop.wav", "renewed while falling", "ambient_loop_request"),
            sound("sounds/cometwhistle.wav", "late fall countdown"),
            sound("sounds/explodesteam.wav", "impact layers"),
            sound("sounds/magicshieldexplode.wav", "impact layer"),
            sound("sounds/bigfire.wav", "impact layer"),
            sound("sounds/ringofice.wav", "FreezeWave creation"),
        ],
        "authority": "Caster authority owns countdown, impact query, damage/freeze contacts, and the spawned FreezeWave.",
        "cleanup": "Impact is terminal, restores world color, stops loop renewal, and leaves only registered debris/wave children to finish.",
        "evidence": ["0x0054CC50", "0x0063FD00", "0x005F0C50", "0x006220D0", "0x0061E9C0", "0x005E3CD0", "0x005F0DB0"],
    },
    77: {
        "targeting": "aimed_area",
        "trigger": "press_edge",
        "actors": [],
        "gameplay": "Affect only Skeleton, SkeletonArcher, SkeletonMage, and Zombie: turn them away, stamp flee timing, and scale attack strength by mWeaken once.",
        "timing": {"flee_duration": "mFlee * 100 fixed ticks"},
        "art": [art("BadGuys", "48", "turn-undead additive burst", "additive_world")],
        "audio": [
            sound("sounds/levelup.wav", "accepted cast at pitch 2.0"),
            sound("sounds/levelup.wav", "accepted cast at pitch 3.0"),
        ],
        "authority": "Caster authority owns area membership, eligible-type filtering, one-time weaken stamp, heading, and flee deadline.",
        "cleanup": "The cast burst self-expires; each target returns to its ordinary behavior when its flee deadline elapses or it dies.",
        "evidence": ["0x0054CC50", "0x00647EF0"],
    },
    78: {
        "targeting": "self",
        "trigger": "toggle",
        "actors": [],
        "gameplay": "Toggle progression +0x8DD, temporarily add one effective rank to every learned skill ID 8..77 except Mindstar itself, clamp to each compiled maximum, and reserve the configured percentage of MP.",
        "timing": {"refresh": "immediate on toggle and every normal progression refresh"},
        "art": [art("player", "caster-centered activation flash", "dispatcher presentation", "actor_overlay")],
        "audio": [sound("sounds/mindstar__stream.wav", "toggle on or off", "stream")],
        "authority": "The authoritative progression component owns the toggle, temporary ranks, mana reserve, and overload shutdown.",
        "cleanup": "Toggle-off, mana overload, death/session reset, or actor teardown removes temporary ranks and reserve in one progression refresh.",
        "evidence": ["0x0054CC50", "0x00661E40", "0x006639D0", "0x006623F0"],
    },
    79: {
        "targeting": "self",
        "trigger": "toggle",
        "actors": [],
        "gameplay": "Toggle progression +0x8DE, reserve the configured percentage of MP, and while active add 1.5/tickRate HP per fixed update in addition to ordinary regeneration, capped at max HP.",
        "timing": {"healing_per_update": "1.5 / tickRate", "refresh": "fixed update while active"},
        "art": [art("player", "caster-centered activation flash", "dispatcher presentation", "actor_overlay")],
        "audio": [sound("sounds/mindstar__stream.wav", "toggle on or off", "stream")],
        "authority": "The authoritative progression component owns toggle, reserve, healing, cap, and overload shutdown.",
        "cleanup": "Toggle-off, mana overload, death/session reset, or actor teardown stops healing and removes reserve immediately.",
        "evidence": ["0x0054CC50", "0x006614D0", "0x006639D0", "0x006623F0"],
    },
}


def main() -> int:
    skills_document = json.loads(SKILLS.read_text(encoding="utf-8"))
    skills = {row["id"]: row for row in skills_document["skills"]}
    audio_document = json.loads(AUDIO.read_text(encoding="utf-8"))
    audio = {
        row["file"]["path"].replace("\\", "/"): {
            "registry_index": row["registry_index"],
            "registry_member_offset": row["registry_member_offset"],
            "native_class": row["native_class"],
            "sha256": row["file"]["sha256"],
        }
        for row in audio_document["compiled_registry"]
        if row.get("file")
    }

    if tuple(CONTRACTS) != SECONDARY_IDS:
        raise SystemExit("secondary contract membership/order drifted")

    abilities = []
    for skill_id in SECONDARY_IDS:
        skill = skills[skill_id]
        contract = CONTRACTS[skill_id]
        audio_rows = []
        for event in contract["audio"]:
            resolved = audio.get(event["path"])
            if resolved is None:
                raise SystemExit(f"unresolved audio path for skill {skill_id}: {event['path']}")
            audio_rows.append({**event, **resolved})
        abilities.append(
            {
                "skill_id": skill_id,
                "name": skill["name"],
                "family": skill["family"],
                "category": 2,
                "skills_atlas_icon_record": skill["skills_atlas_icon_record"],
                "config_path": skill["config_path"],
                "config_sha256": skill["config_sha256"],
                "rank_config": skill["config"],
                "dispatcher": "0x0054CC50",
                "action": (
                    {"mode": 21, "name": "Action_PlayerWizard_CastSpin", "ticks": 73}
                    if skill_id == 51
                    else {"mode": None, "name": "immediate_secondary_dispatch"}
                ),
                **{key: value for key, value in contract.items() if key != "audio"},
                "audio": audio_rows,
                "disposition": "closed_native_contract",
            }
        )

    document = {
        "schema": "solomon-dark-native-secondary-ability-catalog-v1",
        "source": {
            "executable": "SolomonDarkAbandonware/SolomonDark.exe",
            "size": 4723200,
            "sha256": "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
            "image_base": "0x00400000",
            "dispatcher": "0x0054CC50",
            "skill_catalog": SKILLS.relative_to(ROOT).as_posix(),
            "audio_catalog": AUDIO.relative_to(ROOT).as_posix(),
        },
        "summary": {
            "ability_count": len(abilities),
            "skill_ids": list(SECONDARY_IDS),
            "fixed_tick_hz": 100,
            "input_slots": 8,
            "default_right_click_slot": 0,
            "default_secondary_binding": "0x201",
            "keyboard_slot_bindings": ["0x02", "0x03", "0x04", "0x05", "0x06", "0x07", "0x08"],
        },
        "abilities": abilities,
    }
    OUTPUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
