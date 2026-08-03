# Skill Concentration and Discipline

Date: 2026-08-01
Scope: stock `SolomonDark.exe` plus the multiplayer loader at `v0.1.0-beta.29` (`777777d`)
Result: static RE was sufficient; no game instance was launched

## Answer at a glance

**Concentration is a per-player, per-run selection of one learned passive skill.** The Split Mind Charm raises the capacity to two. The choices are skill-row IDs held in process gameplay lanes, not fields in a durable character profile. A chosen skill keeps its ordinary ranked effect and gains a skill-specific compiled bonus; `mConcentration` is not one universal formula. Some skills use the CFG scalar, while others use hard-coded behavior. The stock choices are cleared by a new Create/loadout finalization and are not serialized. The loader snapshots and replicates them per participant and applies each participant's own skill book and concentration context.

**Discipline is the non-element skill family admitted to future level-up offers.** Arcane unlocks rows 48–55, Body unlocks rows 64–71, and Mind unlocks rows 56–63. It grants no immediate stat, spell, or starting-rank bonus beyond activating the discipline root. Element is independent: it chooses the elemental family and starting primary/secondary. The native discipline root is saved in the run's progression at `+0x830`. The original analysis found that local Mind/Body picks were serialized as the profile default Arcane; the 2026-08-02 follow-up in [`skillfix-discipline-and-concentration-2026-08-02.md`](skillfix-discipline-and-concentration-2026-08-02.md) closes that loader defect by capturing the complete native selection quartet.

## Evidence and notation

The analyzed stock executable is 4,723,200 bytes with SHA-256 `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`. Addresses below are preferred-image virtual addresses for that exact file. The committed native catalog used for names and parsed CFG properties has SHA-256 `7f1f777f738ed3fc1089a3c4f06ef0b8935cd2a3bc1b0fbcc671a0baff0e775b`.

The immutable evidence set is `/mnt/d/codex-evidence/skillre-20260801/`. The principal artifacts are:

- `ghidra/decompile-core-mechanics.txt`: Create finalization, selection UI, slot writes, validation, refresh, and the central concentration pass.
- `ghidra/decompile-concentration-effects.txt`: Meditation, Focus, Enchant Staff, Fortunate Flailing, Mind Chug, and Split Mind behavior.
- `ghidra/decompile-discipline-ui-gating-save.txt`: level-up family gating and progression serialization.
- `ghidra/decompile-progression-save-base-pass.txt`: rank copying, refresh baseline, absent-property semantics, and gameplay save behavior.
- `ghidra/decompile-create-render.txt` and `catalog/create-discipline-sprite-mapping.json`: the raw Create discipline index to displayed sprite mapping.
- `catalog/skill-values-and-byte-offsets.csv`: all 82 native IDs, source CFG hashes, parsed properties, and exact assignment byte spans.

This focused closure builds on the broader passive-skill groundwork in [`native-skills-and-spells.md`](../reverse-engineering/native-skills-and-spells.md) and the Rush-specific ownership proof in [`player-speed-rush-accumulation-2026-08-01.md`](../bugs/player-speed-rush-accumulation-2026-08-01.md). It adds the missing slot lifecycle, complete catalog extraction, Create discipline mapping, persistence, and multiplayer analysis.

In formulas, `r` is the effective rank, `V_r` is the `mValue` entry at that rank, and `C` is the skill's scalar `mConcentration`. Array values are absolute ranked totals, not per-rank increments. A CFG byte span `a..b` is zero-based and half-open: `[a,b)`.

## 1. Concentration

### Eligibility and UI flow

The stock constructor at `0x00674EE0` assigns category byte `3` to exactly rows 57–63 and 65–71. The `Skills_Wizard` predicate at vtable `0x007A0CD4`, slot `+0x24` (`0x0067BEE0`), tests that category. Thus Mana Up (56) and Health Up (64) are discipline-family passives but cannot be concentrated; the eligible set is the other fourteen Mind/Body passives.

The player opens Settings/Skills and invokes **Select Concentration**. `SettingsControl_HandleAction` at `0x005D8120` opens the skill picker at `0x0066F0B0`; the chosen row is passed to `0x005D5600`. That setter:

1. rejects a non-category-3 row;
2. rejects a row already present in either slot;
3. rejects manual changes while the timed all-skill override at progression `+0x828` is active;
4. fills slot A first; and
5. if Split Mind is owned, fills B next, then alternates replacement of A and B using gameplay `+0x1C24` when both are occupied.

There is no stock “empty this slot” action. A skill leaves by being replaced, by validation after its effective rank becomes zero, or when Create/reset clears the lanes. `0x0065F9A0` validates A and, when Split Mind is active, B against the current skill book, clearing an invalid row before rebuilding derived state. Health and mana ratios are preserved across that rebuild. Evidence: `ghidra/decompile-core-mechanics.txt`, targets `0x005D5600`, `0x0065F9A0`, and `0x005D0290`.

### Capacity, scope, and native state

Each player has **one** usable slot by default and **two** after Hagatha's selector 21, **Split Mind Charm**, whose stock description is “Concentrate on two skills at once.” The charm costs 4,000 and sets progression flag `+0x7CC + 21 = +0x7E1`; the refresh at `0x0067C360` reads and applies that flag. The existing catalog records the same selector and behavior in [`native-hagatha-perk-catalog.json`](../reverse-engineering/native-hagatha-perk-catalog.json).

The choices themselves live in a native process/gameplay integer array:

| Native location | Meaning |
| --- | --- |
| array object `0x00819E70` | process gameplay selection-state owner |
| pointer `0x00819E84`, count `0x00819E88` | current integer table and entry count |
| index `16 + p` | Concentration A for gameplay player slot `p` |
| index `20 + p` | Concentration B for gameplay player slot `p` |
| value `-1` | empty |
| value `0..81` | native skill/progression row ID |

There are four preallocated player lanes (`p = 0..3`), not four concentration choices for one player. Stock local UI and progression refresh use lane 0 directly (indices 16 and 20). `0x005BC8E0` clears both concentration groups, together with the other gameplay selection groups, across all four player lanes. The loader exposes the same table/count addresses in [`binary-layout.ini`](../../config/binary-layout.ini#L1224-L1225) and defines the four-player layout and A/B bases in [`gameplay_constants.inl`](../../SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl#L109-L151).

The selected IDs are therefore not stored inside an actor. The skill book and derived effects are actor/progression-owned: the gameplay object has progression wrappers at `gameplay + 0x1654 + 4*p`; an actor exposes runtime progression at `actor + 0x200` and its progression handle at `actor + 0x300`. Inside progression, the row table pointer is `+0x20`, count is `+0x24`, and each row is `0x70` bytes with base/permanent rank at row `+0x20`, effective rank at row `+0x22`, and category at row `+0x26`. These loader-known offsets are catalogued in [`binary-layout.ini`](../../config/binary-layout.ini#L1275-L1290) and [`binary-layout.ini`](../../config/binary-layout.ini#L1610-L1629).

### Ranks and temporary all-skill concentration

Refresh `0x0065F5B0` first copies every row's base/permanent rank (`+0x20`) to effective rank (`+0x22`). Mindstar may then add one effective rank, clamped to the skill maximum, at `0x00661E40`. The concentration slot stores only the row ID, so its ordinary ranked effect automatically follows the current effective rank. `mConcentration` itself is a single, unranked scalar.

Mind Chug potion subtype 4 starts the progression `+0x828` counter for the stock 60-second duration. While nonzero, the refresh at `0x006623F0` applies concentration to every learned category-3 row instead of only A/B, and `0x00660220` decrements the counter and refreshes when it expires. The timer is not among the serialized progression fields. Direct skill handlers also test it, with the Creativity exception described below. Existing item RE independently identifies Mind Chug in [`native-items-equipment-and-loot.md`](../reverse-engineering/native-items-equipment-and-loot.md).

### Exact effect semantics

There is no generic “add `mConcentration` percent” rule. `0x006623F0` builds the ordinary ranked fields, then dispatches selected rows to `0x00661FD0`; several special skills instead check A/B/timer in their own gameplay functions. Missing properties return numeric zero through `0x0065D540`.

| ID | Skill | Not concentrated | Concentrated gain | Implementation evidence |
| ---: | --- | --- | --- | --- |
| 57 | Channel Mana | recovery factor `1 + V_r/100` | `(1 + V_r/100) * (1 + C/100)`; `C=15` | `0x006623F0`, `0x00661FD0`, progression `+0x98` |
| 58 | Meditation | ranked idle delay and `V_r` recovery multiplier require standing/not firing | walking or acting no longer clears the lesser meditation ramp; rank still controls its delay/multiplier | `0x00659A40`, progression `+0x884..+0x88C` |
| 59 | Battle Mage | offensive mana factor `1 - V_r/100` | `1 - (V_r + C)/100`; `C=15` | `0x00661530`, `0x00661FD0`, progression `+0x3D4` |
| 60 | Focus | secondary recharge factor `1 + V_r/100` | hard-coded 25% chance to bypass normal recharge and be immediately available | `0x00661530`, `0x00661F40`; CFG `C=25` matches the hard-coded roll |
| 61 | Siege Mage | offensive damage factor `1 + V_r/100` | `1 + (V_r + C)/100`; `C=15` | `0x00661530`, `0x00661FD0`, progression `+0xF8` |
| 62 | Resist Magic | resistance `V_r/100` | `(V_r + C)/100`; `C=20` | `0x00661530`, `0x00661FD0`, progression `+0xA4` |
| 63 | Creativity | +1 offer and requirements -2 | 20% chance that one eligible offer becomes an Insight; choosing it applies that choice twice | `0x0066F920`; **bug:** tests A/index 16 only, not B or Mind Chug |
| 65 | Enchant Staff | ranked `mDamage` melee bonus | staff attack timing/action field `+0x34` is multiplied by **1.75**, despite UI saying 2x | `0x00537AA0`, float at `0x00785870` |
| 66 | Telekinesis | pickup-range field `V_r * 1.25` | doubles that field: `V_r * 2.5` | `0x00661530`, `0x00661FD0`, constant `1.25` at `0x00784740` |
| 67 | Rush | ranked movement factor `1 + V_r/100` | multiplies by `1 + C/100 = 1.25`; total `(1 + V_r/100) * 1.25` | `0x00661FD0`, progression `+0x90`; full movement ownership in [`player-speed-rush-accumulation-2026-08-01.md`](../bugs/player-speed-rush-accumulation-2026-08-01.md) |
| 68 | Deflect | with a staff, `V_r` percent chance to deflect | **no working bonus**: handler reads absent `mConcentration` as zero and adds it to poison resistance; advertised physical reflection x5 is not implemented | `0x00661530`, `0x00661FD0` case 68, progression `+0xA8` |
| 69 | Resist Poison | resistance/duration reduction `V_r/100` | `(V_r + C)/100`; `C=10` | `0x00661530`, `0x00661FD0`, progression `+0xA8` |
| 70 | Faster Caster | cast-speed factor `1 + V_r/100` | `1 + (V_r + C)/100`; `C=25` | `0x00661530`, `0x00661FD0`, progression `+0x94` |
| 71 | Fortunate Flailing | ranked `mChance` selects accidental melee effects | every non-normal proc's damage is multiplied by `1.2` | `0x0053B9F0`, float at `0x00785360` |

The “practical gain” is the fourth column, not merely the catalog scalar. In particular, Focus's 25, Creativity's 20%, Enchant Staff's 1.75, Telekinesis's doubling, and Fortunate Flailing's 1.2 are compiled behavior. Deflect's advertised gain is broken. Creativity also has a slot-B/Mind-Chug recognition defect.

### Persistence and lifecycle

Concentration A/B are **per-run/process gameplay state**, not durable profile state:

- Create finalization `0x005D0290` writes `-1` to fixed A/B and refreshes.
- gameplay reset `0x005BC8E0` clears A/B for all four lanes;
- gameplay save `0x005CE3D0` serializes the primary selection at index 12 but never indices 16/20; and
- progression serializer `0x0065EE80` stores ranks, the selected element/discipline, and Hagatha's `+0x7CC` flags, but not process A/B or the Mind Chug `+0x828` timer.

Split Mind itself persists with the progression/Hagatha flag set because `0x0065EE80` serializes the `+0x7CC..+0x7FD` byte range. The currently chosen skill IDs do not. Under the re-pick-every-match lifecycle, the new Create/progression generation therefore starts with empty concentration choices even when the previous raw loadout is shown as a convenience preselection.

### Multiplayer semantics

Concentration is replicated as participant-owned state, not a shared local player's choice:

- [`ParticipantOwnedProgressionState`](../../SolomonDarkModLoader/include/multiplayer_runtime_state.h#L191-L218) carries revision, validity, A, and B.
- [`StatePacket`](../../SolomonDarkModLoader/include/multiplayer_runtime_protocol.h#L601-L610) carries the same fields.
- the local sampler reads lane 0, bumps the revision on a change, and writes the packet in [`local_state_packet_sync.inl`](../../SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl#L144-L287) and [`local_state_packet_sync.inl`](../../SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl#L621-L628);
- the receiver accepts newer participant state in [`incoming_participant_state_sync.inl`](../../SolomonDarkModLoader/src/multiplayer_local_transport/incoming_participant_state_sync.inl#L336-L349); and
- remote native actors receive their persistent `16+p`/`20+p` runtime lanes in [`native_progression_sync.inl`](../../SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl#L521-L553).

Stock stat refresh reads only fixed A/B indices 16/20. To refresh or invoke a stock callback for a remote actor, the loader transactionally swaps that participant's A/B into the fixed lanes, calls against that actor's progression, and restores the local lanes. The implementation is in [`scene_and_animation_gameplay_state.inl`](../../SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_gameplay_state.inl#L306-L385) and [`public_api_debug_and_spawn.inl`](../../SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl#L126-L223). Direct combat handlers such as Enchant Staff and Fortunate Flailing read `16+p`/`20+p`, so persistent per-gameplay-slot lanes are also reconciled. Derived stat fields are replicated separately as absolute owner state. The result is one skill book and one concentration selection set per materialized participant/entity.

## 2. Discipline

### What the Create choice is

The Create owner has five element points at `+0x7C`, element enabled/selected at `+0x18C/+0x1A4`, and three discipline points at `+0xA4`, discipline enabled/selected at `+0x228/+0x22C`. `0x0058BCE0` hit-tests those point arrays. Finalizer `0x0058A820` copies the raw element and discipline indices to globals `0x0080807C` and `0x00808080`, then calls gameplay finalization `0x005D0290`.

The displayed discipline sprites and native mappings are:

| Raw Create index | Displayed choice | Create asset record / atlas rectangle | Native root written at progression `+0x830` | Family admitted to level-up |
| ---: | --- | --- | ---: | --- |
| 0 | Arcane | record 0; `(664,0,218,238)` | 7 | rows 48–55 |
| 1 | Body | record 1; `(266,330,238,229)` | 5 | rows 64–71 |
| 2 | Mind | record 5; `(60,0,227,241)` | 6 | rows 56–63 |

The mapping is evidenced jointly by render function `0x0059AD40`, `images/Create.bundle` SHA-256 `b1f5c2ed54daa5ee2260fa179f04a3d51f0eae6b167149c3a2561d160e872d53`, `images/Create.png` SHA-256 `9c629ccd3d859384446363ac50e90c19e55f8d5ef8cd17d25604f5a67f3d08eb`, and `0x005D0290`'s raw-index switch.

This exposes a loader configuration defect: [`binary-layout.ini`](../../config/binary-layout.ini#L2030-L2052) labels point 0 as Mind and point 2 as Arcane. The stock screen and finalizer prove those two labels are reversed. Body/point 1 is correct.

The multiplayer enum is a separate semantic domain: Mind `0`, Body `1`, Arcane `2` in [`multiplayer_runtime_state.h`](../../SolomonDarkModLoader/include/multiplayer_runtime_state.h#L34-L38). It must not be interpreted as the raw Create index. The remote materializer correctly maps the semantic enum to native roots 6/5/7 in [`standalone_materialization_selection_priming.inl`](../../SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_selection_priming.inl#L1-L12).

### What each discipline actually does

Finalizer `0x005D0290` calls `0x00660320` to activate/rank the selected discipline root, then stores the root ID at progression `+0x830`. Rows 48–71 carry their family root at row `+0x1C`. The level-up candidate builder `0x0067CB70` accepts a normal skill when that root equals either selected element `progression + 0x82C` or selected discipline `progression + 0x830`, subject to its other rank, requirement, and availability checks.

Therefore the practical choices are:

| Discipline | Future level-up family enabled | Immediate gameplay change |
| --- | --- | --- |
| Arcane | Teleport (48), Magic Circle (49), Magic Trap (50), Dampen (51), Spell Welding (52), Flash (53), Magic Shield (54), Explosive Shield (55) | none beyond activating Arcane root 7 |
| Body | Health Up (64), Enchant Staff (65), Telekinesis (66), Rush (67), Deflect (68), Resist Poison (69), Faster Caster (70), Fortunate Flailing (71) | none beyond activating Body root 5 |
| Mind | Mana Up (56), Channel Mana (57), Meditation (58), Battle Mage (59), Focus (60), Siege Mage (61), Resist Magic (62), Creativity (63) | none beyond activating Mind root 6 |

It does **not** directly grant health, mana, damage, a spell, a passive, or an initial rank in those eight skills. It makes that family eligible for future random level-up offers.

### Interaction with element and starting loadout

Element is selected independently and does two jobs: it supplies the other family root at progression `+0x82C`, and it creates the starting primary/secondary rows at `+0x86C/+0x870`.

| Raw element | Root | Starting primary | Starting secondary |
| ---: | ---: | --- | --- |
| 0 Ether | 0 | Magic Missile (8) | Call Leviathan (11) |
| 1 Fire | 1 | Fireball (16) | Ring of Fire (21) |
| 2 Air | 2 | Lightning (24) | Magic Storm (27) |
| 3 Water | 3 | Frost Jet (32) | Ring of Ice (35) |
| 4 Earth | 4 | Boulder (40) | Raise Golem (45) |

Thus an Earth + Mind player starts with Earth's two attacks, receives Earth-family and Mind-family level-up offers, and gains no Mind passive until one is actually chosen. `0x005D0290` contains the complete element and discipline switches.

### Storage, save, and re-pick-every-match

The raw UI selection exists transiently at Create owner `+0x22C` and global `0x00808080`. The gameplay-semantic value is root 5, 6, or 7 at progression `+0x830`. Serializer `0x0065EE80` serializes integer slots `param + 0x20B`, `+0x20C`, and `+0x20D`, which are byte offsets `+0x82C`, `+0x830`, and `+0x834`; discipline therefore survives the stock run/save progression lifecycle.

The loader's match lifecycle intentionally creates a new pick generation at game over in [`phase_state.inl`](../../SolomonDarkModLoader/src/multiplayer_join_flow/phase_state.inl#L11-L24) and resets commit state in [`loadout_picker.inl`](../../SolomonDarkModLoader/src/multiplayer_join_flow/loadout_picker.inl#L57-L76). A fresh Create surface may copy the last raw element/discipline into the UI as a preselection, but this is only convenience state ([`loadout_picker.inl`](../../SolomonDarkModLoader/src/multiplayer_join_flow/loadout_picker.inl#L185-L264)). The hook masks discipline until the generation is allowed to commit, replays the retained element through the stock click path, clears discipline when element changes, and commits only after both selections are complete ([`loadout_picker.inl`](../../SolomonDarkModLoader/src/multiplayer_join_flow/loadout_picker.inl#L329-L560)). The new stock finalizer seeds a fresh base book/progression; old learned ranks are not retained merely because the old raw choices were preselected.

### Replication and repaired capture path

The protocol is designed to replicate discipline:

- `StatePacket` has `element_id` and `discipline_id`, and `CastPacket` repeats them in [`multiplayer_runtime_protocol.h`](../../SolomonDarkModLoader/include/multiplayer_runtime_protocol.h#L578-L580) and [`multiplayer_runtime_protocol.h`](../../SolomonDarkModLoader/include/multiplayer_runtime_protocol.h#L872-L887).
- packet construction copies `participant.character_profile.discipline_id` in [`local_state_packet_sync.inl`](../../SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl#L564-L576).
- receivers rebuild the semantic profile in [`incoming_participant_state_sync.inl`](../../SolomonDarkModLoader/src/multiplayer_local_transport/incoming_participant_state_sync.inl#L180-L205).
- native remote materialization maps that enum to root 6/5/7 and writes progression `+0x830` in [`standalone_materialization_selection_priming.inl`](../../SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_selection_priming.inl#L206-L220) and [`standalone_materialization_selection_priming.inl`](../../SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization_selection_priming.inl#L297-L429).

The 2026-08-02 repair reads all four stock Create selections from local
progression: element root `+0x82C`, discipline root `+0x830`, starting primary
`+0x86C`, and starting secondary `+0x870`. It validates their stock pairing,
converts roots to the semantic protocol fields, and stores the native quartet
in the profile's legacy four-choice array before packet construction. Remote
priming consumes the same four positions and rejects a quartet that disagrees
with the semantic profile. Profiles without explicit native rows, including
the normal bot path, continue to use semantic element and discipline mapping.

The raw Create actions were repaired at the same boundary: Arcane is stock
point 0, Body point 1, and Mind point 2. Those raw indices remain deliberately
separate from the semantic protocol enum Mind 0, Body 1, Arcane 2. See the
focused investigation and acceptance record in
[`skillfix-discipline-and-concentration-2026-08-02.md`](skillfix-discipline-and-concentration-2026-08-02.md).

Bots/synthetic participants are different: their profiles explicitly carry a semantic discipline and the materializer maps it correctly. No live claim is needed for the human defect because the complete local assignment graph is statically closed.

## 3. Loader seam quality

### Concentration seams

- **Good read seams:** `gameplay_index_state_table/count` (`0x00819E84/0x00819E88`), progression table/count/row ABI, actor progression offsets, the gameplay selection debug API, participant concentration state, and packet fields already expose all selected IDs and current actor-owned effects.
- **Good balance seams with limits:** the shipped CFGs and [`native-skill-catalog.json`](../reverse-engineering/native-skill-catalog.json) expose ranked arrays and scalars. Editing `mValue` or `mConcentration` changes behavior only where the compiled handler reads that property. Channel Mana, Battle Mage, Siege Mage, Resist Magic, Rush, Resist Poison, and Faster Caster read `mConcentration`. Focus's chance is hard-coded at 25 even though the CFG also says 25.
- **Compiled behavior seams:** Meditation, Creativity, Enchant Staff, Telekinesis, Focus, and Fortunate Flailing require hooks to change their concentration bonus. Deflect needs a real reflection implementation; merely adding `mConcentration` would feed the poison-resistance accumulator, not physical reflection. Creativity needs a branch fix to honor B and Mind Chug.
- **Eligibility/extension limits:** adding `mConcentration` does not make a row selectable. Category 3 is assigned in the compiled constructor, and per-row handlers are compiled switches. A new skill needs ID/name/constructor/picker/icon/handler coverage. More than two slots needs UI, native storage, refresh, action replacement, participant state, and protocol changes.

### Discipline seams

- **Good read seams:** raw Create owner offsets, globals `0x0080807C/0x00808080`, progression element/discipline fields `+0x82C/+0x830`, the row family-root field `+0x1C`, semantic profile enum, packet fields, and native materialization are all known.
- **CFG limitation:** the three discipline CFGs contain descriptions, not family membership. Roots 5/6/7, row families, the Create switches, and level-up admission are compiled. Adding a fourth discipline requires Create point/assets/render/click/finalizer work, catalog/root/family changes, level-up gating, save validation, semantic enum, protocol, and materialization changes.
- **Immediate defects at the seam:** fix the raw-action labels so point 0 is Arcane and point 2 is Mind. For human replication, capture native progression `+0x830` after Create commit and map root 6→Mind, 5→Body, 7→Arcane before packet construction. These are documented only; this RE pass makes no product-code change.

## Appendix A: every native skill's `mValue` and `mConcentration`

`-` means the property is absent from the shipped CFG, not an inferred zero. Rows 80–81 have no shipped CFG. The exact source hashes for every CFG are in the evidence CSV.

| ID | Skill | Family | Cap/max | mValue by rank | mConcentration | CFG and 0-based byte spans |
| ---: | --- | --- | ---: | --- | ---: | --- |
| 0 | Element of Ether | element | -/- | `-` | - | `data/wizardskills/element_of_ether.cfg`; mValue `-`, mConcentration `-` |
| 1 | Element of Fire | element | -/- | `-` | - | `data/wizardskills/element_of_fire.cfg`; mValue `-`, mConcentration `-` |
| 2 | Element of Air | element | -/- | `-` | - | `data/wizardskills/element_of_air.cfg`; mValue `-`, mConcentration `-` |
| 3 | Element of Water | element | -/- | `-` | - | `data/wizardskills/element_of_water.cfg`; mValue `-`, mConcentration `-` |
| 4 | Element of Earth | element | -/- | `-` | - | `data/wizardskills/element_of_earth.cfg`; mValue `-`, mConcentration `-` |
| 5 | Body Discipline | discipline | -/- | `-` | - | `data/wizardskills/body_discipline.cfg`; mValue `-`, mConcentration `-` |
| 6 | Mind Discipline | discipline | -/- | `-` | - | `data/wizardskills/mind_discipline.cfg`; mValue `-`, mConcentration `-` |
| 7 | Arcane Discipline | discipline | -/- | `-` | - | `data/wizardskills/arcane_discipline.cfg`; mValue `-`, mConcentration `-` |
| 8 | Magic Missile | ether | 20/25 | `-` | - | `data/wizardskills/magic_missile.cfg`; mValue `-`, mConcentration `-` |
| 9 | Smart Missiles | ether | 5/10 | `-` | - | `data/wizardskills/smart_missiles.cfg`; mValue `-`, mConcentration `-` |
| 10 | More Missiles | ether | 8/12 | `-` | - | `data/wizardskills/more_missiles.cfg`; mValue `-`, mConcentration `-` |
| 11 | Call Leviathan | ether | 5/10 | `-` | - | `data/wizardskills/call_leviathan.cfg`; mValue `-`, mConcentration `-` |
| 12 | Planewalker | ether | 8/12 | `-` | - | `data/wizardskills/planewalker.cfg`; mValue `-`, mConcentration `-` |
| 13 | Piercing | ether | 3/8 | `-` | - | `data/wizardskills/piercing.cfg`; mValue `-`, mConcentration `-` |
| 14 | Ether Blast | ether | 4/6 | `-` | - | `data/wizardskills/ether_blast.cfg`; mValue `-`, mConcentration `-` |
| 15 | Phasing | ether | 1/1 | `-` | - | `data/wizardskills/phasing.cfg`; mValue `-`, mConcentration `-` |
| 16 | Fireball | fire | 20/25 | `-` | - | `data/wizardskills/fireball.cfg`; mValue `-`, mConcentration `-` |
| 17 | Embers | fire | 5/10 | `-` | - | `data/wizardskills/embers.cfg`; mValue `-`, mConcentration `-` |
| 18 | Explode | fire | 6/12 | `-` | - | `data/wizardskills/explode.cfg`; mValue `-`, mConcentration `-` |
| 19 | Embers to Imps | fire | 8/12 | `-` | - | `data/wizardskills/embers_to_imps.cfg`; mValue `-`, mConcentration `-` |
| 20 | Immolate | fire | 5/8 | `-` | - | `data/wizardskills/immolate.cfg`; mValue `-`, mConcentration `-` |
| 21 | Ring of Fire | fire | 5/10 | `-` | - | `data/wizardskills/ring_of_fire.cfg`; mValue `-`, mConcentration `-` |
| 22 | Burn | fire | 3/8 | `-` | - | `data/wizardskills/burn.cfg`; mValue `-`, mConcentration `-` |
| 23 | Firewalker | fire | 3/8 | `-` | - | `data/wizardskills/firewalker.cfg`; mValue `-`, mConcentration `-` |
| 24 | Lightning | air | 20/25 | `-` | - | `data/wizardskills/lightning.cfg`; mValue `-`, mConcentration `-` |
| 25 | Chaining | air | 6/12 | `-` | - | `data/wizardskills/chaining.cfg`; mValue `-`, mConcentration `-` |
| 26 | Stun | air | 5/10 | `-` | - | `data/wizardskills/stun.cfg`; mValue `-`, mConcentration `-` |
| 27 | Magic Storm | air | 5/10 | `-` | - | `data/wizardskills/magic_storm.cfg`; mValue `-`, mConcentration `-` |
| 28 | Magic Tornado | air | 5/10 | `-` | - | `data/wizardskills/magic_tornado.cfg`; mValue `-`, mConcentration `-` |
| 29 | Hurricane | air | 5/10 | `-` | - | `data/wizardskills/hurricane.cfg`; mValue `-`, mConcentration `-` |
| 30 | Prismatic Shock | air | 3/8 | `-` | - | `data/wizardskills/prismatic_shock.cfg`; mValue `-`, mConcentration `-` |
| 31 | Disintegrate | air | 3/8 | `-` | - | `data/wizardskills/disintegrate.cfg`; mValue `-`, mConcentration `-` |
| 32 | Frost Jet | water | 20/25 | `-` | - | `data/wizardskills/frost_jet.cfg`; mValue `-`, mConcentration `-` |
| 33 | Chill Wind | water | 5/10 | `-` | - | `data/wizardskills/chill_wind.cfg`; mValue `-`, mConcentration `-` |
| 34 | Cone of Ice | water | 6/11 | `-` | - | `data/wizardskills/cone_of_ice.cfg`; mValue `-`, mConcentration `-` |
| 35 | Ring of Ice | water | 5/10 | `-` | - | `data/wizardskills/ring_of_ice.cfg`; mValue `-`, mConcentration `-` |
| 36 | Harden | water | 5/10 | `-` | - | `data/wizardskills/harden.cfg`; mValue `-`, mConcentration `-` |
| 37 | Cold Aura | water | 4/10 | `-` | - | `data/wizardskills/cold_aura.cfg`; mValue `-`, mConcentration `-` |
| 38 | Hail | water | 5/10 | `-` | - | `data/wizardskills/hail.cfg`; mValue `-`, mConcentration `-` |
| 39 | Permafrost | water | 1/1 | `-` | - | `data/wizardskills/permafrost.cfg`; mValue `-`, mConcentration `-` |
| 40 | Boulder | earth | 20/25 | `-` | - | `data/wizardskills/boulder.cfg`; mValue `-`, mConcentration `-` |
| 41 | Earthquake | earth | 5/10 | `-` | - | `data/wizardskills/earthquake.cfg`; mValue `-`, mConcentration `-` |
| 42 | Hasten Rocks | earth | 5/10 | `-` | - | `data/wizardskills/hasten_rocks.cfg`; mValue `-`, mConcentration `-` |
| 43 | Bind Rocks | earth | 5/10 | `-` | - | `data/wizardskills/bind_rocks.cfg`; mValue `-`, mConcentration `-` |
| 44 | Rock Surge | earth | 3/8 | `-` | - | `data/wizardskills/rock_surge.cfg`; mValue `-`, mConcentration `-` |
| 45 | Raise Golem | earth | 8/12 | `-` | - | `data/wizardskills/raise_golem.cfg`; mValue `-`, mConcentration `-` |
| 46 | Stoneskin | earth | 3/10 | `-` | - | `data/wizardskills/stoneskin.cfg`; mValue `-`, mConcentration `-` |
| 47 | Gargantuan | earth | 3/8 | `-` | - | `data/wizardskills/gargantuan.cfg`; mValue `-`, mConcentration `-` |
| 48 | Teleport | arcane | 3/8 | `-` | - | `data/wizardskills/teleport.cfg`; mValue `-`, mConcentration `-` |
| 49 | Magic Circle | arcane | 3/8 | `-` | - | `data/wizardskills/magic_circle.cfg`; mValue `-`, mConcentration `-` |
| 50 | Magic Trap | arcane | 8/12 | `-` | - | `data/wizardskills/magic_trap.cfg`; mValue `-`, mConcentration `-` |
| 51 | Dampen | arcane | 1/1 | `-` | - | `data/wizardskills/dampen.cfg`; mValue `-`, mConcentration `-` |
| 52 | Spell Welding | arcane | 1/1 | `-` | - | `data/wizardskills/spell_welding.cfg`; mValue `-`, mConcentration `-` |
| 53 | Flash | arcane | 1/1 | `-` | - | `data/wizardskills/flash.cfg`; mValue `-`, mConcentration `-` |
| 54 | Magic Shield | arcane | 7/12 | `-` | - | `data/wizardskills/magic_shield.cfg`; mValue `-`, mConcentration `-` |
| 55 | Explosive Shield | arcane | 1/1 | `-` | - | `data/wizardskills/explosive_shield.cfg`; mValue `-`, mConcentration `-` |
| 56 | Mana Up | mind | 8/12 | `[0,100,200,300,400,500,600,700,800,900,1000,1100,1250]` | - | `data/wizardskills/mana_up.cfg`; mValue `164..226`, mConcentration `-` |
| 57 | Channel Mana | mind | 5/10 | `[0,25,50,75,100,125,150,175,200,225,250]` | 15 | `data/wizardskills/channel_mana.cfg`; mValue `236..284`, mConcentration `286..304` |
| 58 | Meditation | mind | 3/8 | `[0,4,4,4,5,5,5,5,6]` | - | `data/wizardskills/meditation.cfg`; mValue `330..357`, mConcentration `-` |
| 59 | Battle Mage | mind | 6/11 | `[0,10,15,20,25,30,35,40,45,50,55,60]` | 15 | `data/wizardskills/battle_mage.cfg`; mValue `258..302`, mConcentration `304..322` |
| 60 | Focus | mind | 1/1 | `[0,100]` | 25 | `data/wizardskills/focus.cfg`; mValue `267..282`, mConcentration `284..302` |
| 61 | Siege Mage | mind | 5/10 | `[0,20,40,60,80,100,120,140,160,180,225]` | 15 | `data/wizardskills/siege_mage.cfg`; mValue `245..292`, mConcentration `294..312` |
| 62 | Resist Magic | mind | 3/8 | `[0,25,35,45,50,55,60,65,70]` | 20 | `data/wizardskills/resist_magic.cfg`; mValue `259..294`, mConcentration `209..227` |
| 63 | Creativity | mind | 1/1 | `-` | - | `data/wizardskills/creativity.cfg`; mValue `-`, mConcentration `-` |
| 64 | Health Up | body | 8/12 | `[0,50,100,150,200,250,300,350,400,450,500,550,650]` | - | `data/wizardskills/health_up.cfg`; mValue `170..228`, mConcentration `-` |
| 65 | Enchant Staff | body | 10/15 | `-` | - | `data/wizardskills/enchant_staff.cfg`; mValue `-`, mConcentration `-` |
| 66 | Telekinesis | body | 1/1 | `[1,5]` | - | `data/wizardskills/telekinesis.cfg`; mValue `233..246`, mConcentration `-` |
| 67 | Rush | body | 3/8 | `[0,10,20,25,30,35,40,45,50]` | 25 | `data/wizardskills/rush.cfg`; mValue `226..261`, mConcentration `263..281` |
| 68 | Deflect | body | 1/1 | `[0,10]` | - | `data/wizardskills/deflect.cfg`; mValue `277..291`, mConcentration `-` |
| 69 | Resist Poison | body | 3/8 | `[0,20,25,30,35,40,45,50,60]` | 10 | `data/wizardskills/resist_poison.cfg`; mValue `266..301`, mConcentration `212..230` |
| 70 | Faster Caster | body | 5/10 | `[0,10,20,30,40,50,55,60,65,70,75]` | 25 | `data/wizardskills/faster_caster.cfg`; mValue `229..270`, mConcentration `272..290` |
| 71 | Fortunate Flailing | body | 4/9 | `-` | - | `data/wizardskills/fortunate_flailing.cfg`; mValue `-`, mConcentration `-` |
| 72 | Acid Rain | advanced | 5/10 | `-` | - | `data/wizardskills/acid_rain.cfg`; mValue `-`, mConcentration `-` |
| 73 | Fire Wall | advanced | 5/10 | `-` | - | `data/wizardskills/fire_wall.cfg`; mValue `-`, mConcentration `-` |
| 74 | Ether Drain | advanced | 5/10 | `-` | - | `data/wizardskills/ether_drain.cfg`; mValue `-`, mConcentration `-` |
| 75 | Iron Golem | advanced | 4/8 | `-` | - | `data/wizardskills/iron_golem.cfg`; mValue `-`, mConcentration `-` |
| 76 | Call Comet | advanced | 5/10 | `-` | - | `data/wizardskills/call_comet.cfg`; mValue `-`, mConcentration `-` |
| 77 | Turn Undead | advanced | 5/10 | `-` | - | `data/wizardskills/turn_undead.cfg`; mValue `-`, mConcentration `-` |
| 78 | Mindstar | advanced | 3/8 | `-` | - | `data/wizardskills/mindstar.cfg`; mValue `-`, mConcentration `-` |
| 79 | Regenerate | advanced | 3/8 | `-` | - | `data/wizardskills/regenerate.cfg`; mValue `-`, mConcentration `-` |
| 80 | Plane Orb | runtime_only | -/- | `-` | - | `-`; mValue `-`, mConcentration `-` |
| 81 | Reserved | runtime_only | -/- | `-` | - | `-`; mValue `-`, mConcentration `-` |
