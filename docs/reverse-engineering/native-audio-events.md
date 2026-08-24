# Native audio event census

## Result and identity

This is the G5 trigger contract for the browser rebuild. It maps native gameplay and UI events to the logical audio request made by the retail game, independently of whether a speaker produces output. An implementation can use this document with [`native-audio-catalog.json`](native-audio-catalog.json) and does not need to inspect `SolomonDark.exe`.

All addresses are preferred-image virtual addresses in the retail `SolomonDark.exe` with SHA-256 `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`. An address in a trigger table is the `CALL` instruction, not the return address recorded by a hook. The live fixture preserves both where applicable.

The asset and engine layers remain authoritative background:

- [`native-audio-system.md`](native-audio-system.md) defines the 233-slot registry, voices, dynamic sound, ambient wrappers, and music table.
- [`native-audio-engine-2026-07-26.md`](native-audio-engine-2026-07-26.md) defines wrapper/channel ownership and BASS lifecycle.
- [`audio-event-goldens.json`](../../tests/fixtures/webgame/audio-event-goldens.json) is the quiet live dispatch timeline for every event class below.

## Silence boundary and observation seam

`SDMOD_DISABLE_AUDIO=1` does not suppress gameplay trigger logic. `InitializeLaunchAudioDisable` intercepts the BASS initializer at `0x004450D0`, leaves `DAT_00B40239` zero, and frees an already-open BASS device if injection lost the startup race. The stock `Sound`, `SoundStream`, `SoundLoop`, and `Music` wrappers remain callable above that byte. In particular, loop reference counts and music transition state still advance while their BASS calls are gated.

The opt-in `SDMOD_CAPTURE_AUDIO_EVENTS=1` tap hooks these upstream request wrappers:

| Wrapper | Preferred address | Captured request |
| --- | ---: | --- |
| `Sound::Play(gain)` | `0x00407B70` | object/registry identity, gain, caller return |
| `Sound::Play(pitch,gain)` | `0x00407CD0` | object/registry identity, pitch, gain, caller return |
| `SoundLoop::Start` / `Stop` | `0x00408320` / `0x00408350` | object/registry identity, operation, post-call reference count |
| `SoundStream::Play` / `Pause` | `0x0040AF70` / `0x0040AFB0` | object/registry identity, gain/operation |
| `Music::PlayImmediate` | `0x00409A10` | song |
| `Music::PlayCrossfade` | `0x00409CD0` | song and transition ticks |
| `Music::Transition` | `0x00409FA0` | song, track, and transition ticks |
| `Music::Stop` | `0x0040A3F0` | stop request |

Capture is fail-closed: it requires `SDMOD_DISABLE_AUDIO=1`, reads `DAT_00B40239`, refuses an enabled engine, and rejects registry identities unless exactly one of the four rigid registry segments round-trips the pointer to the same index and class. The launch `aud-boundary` provided the end-to-end boundary witness: a Water primary transition called `icestart` and started/stopped registry 161 `sounds\iceloop__loop` while the runtime engine byte was zero; the start returned to `0x00549BB7`, the stop returned to `0x0054972A`, the logical loop count balanced, and no BASS channel existed. The clean golden launch independently captured natural in-image `prelude`, `selection`, `academy`, and `combat` Music requests with `engine_enabled=false`.

That establishes the ordering:

```text
gameplay/UI call site -> captured stock wrapper request -> DAT_00B40239 gate -> BASS mixer/device
```

A zero-event capture is therefore meaningful only after the capture-enabled flag, owned runnable PID, engine byte, and a known wrapper marker have been checked separately. The recorder does all four and reports a missing marker or scene transition as “broken, not busy.” Audible output is never a capture channel.

## Trigger census

`fixed` means no asset-selection RNG draw. A pool uses the active gameplay stream reached through `DAT_00818B08` and `Integer` at `0x00401170`; it therefore follows the G1 rule `seed = App[+0x28] * 0xEF3` and consumes the same stream word/order as every other gameplay draw. Pitch expressions which call the float primitive at `0x00401310` also advance that active stream. A browser must not move cosmetic audio selection to a separate RNG.

### Casts and projectile lifecycle

The five selectable player elements are Ether, Fire, Air, Water/Frost, and Earth. Light and Dark are internal replicated primary-state values, not selectable class elements; their shared replication path owns no independent player cast sound. A held phase with “no request” is intentionally silent at the dispatch seam: the loop started on the transition continues without being requested again.

| Event class | Native trigger | Exact call site(s) | Requested asset(s) | Selection and parameters |
| --- | --- | --- | --- | --- |
| `cast.ether.release` | Primary Magic Missile emission | `0x0053D9CA` | 57 `sounds\magicmissile`, pitch+gain one-shot | Fixed asset; cast-computed pitch and point gain. |
| `cast.fire.release` | Primary Fire Missile emission | `0x0053E4E0` | 97 `sounds\throwfire`, pitch+gain one-shot | Fixed asset; cast-computed pitch and point gain. |
| `cast.air.channel_start` | Primary selector `0 -> 0x18` | `0x005497EF`; `0x00549800` | 54 `sounds\lightningstart`; start 162 `sounds\lightningloop__loop` | Fixed; one transition edge only. |
| `cast.air.channel_hold` | Air stays selected | no call | no new request | Existing 162 loop persists. |
| `cast.air.channel_stop` | Primary selector `0x18 -> other/idle` | `0x00549714` | stop 162 | Fixed; decrements loop ownership. |
| `cast.water.channel_start` | Primary selector `0 -> 0x20` | `0x00549BA1`; `0x00549BB2` | 44 `sounds\icestart`; start 161 `sounds\iceloop__loop` | Fixed; one transition edge only. |
| `cast.water.channel_hold` | Water stays selected | no call | no new request | Existing 161 loop persists. |
| `cast.water.channel_stop` | Primary selector `0x20 -> other/idle` | `0x00549725` | stop 161 | Fixed; decrements loop ownership. |
| `cast.earth.charge_start` | Primary selector `0 -> 0x28` | `0x00549F57` | start 159 `sounds\gatherrocksloop__loop` | Fixed; one transition edge only. |
| `cast.earth.boulder_created` | Earth dispatcher allocates, registers, and stores the type `0x7D5` actor | `0x00544FA8` | 87 `sounds\startboulder` | Fixed; one trigger per actor creation, before release. |
| `cast.earth.charge_hold` | Held Boulder charge grows | no call | no new request | Existing 159 loop persists; reaching the charge cap also stops at `0x0054AD12`. |
| `cast.earth.release` | Native release and selector `0x28 -> 0` | `0x00549758` | stop 159 | Fixed; release must be one stock transition and has no direct one-shot. |
| `projectile.ether.flight` | Magic Missile birth | `0x0053D9CA` | 57 `sounds\magicmissile` | Launch request is the cast-release request; flight ticks are silent. |
| `projectile.ether.impact` | Magic Missile contact | `0x005F1FF2` (also `0x005F3F7B`, `0x005F412E`, `0x005F4206`, `0x005F6B60`, `0x005F6FDC` for sibling contact paths) | 58 `sounds\magicmissilehit` | Fixed asset; point gain and float-RNG pitch. |
| `projectile.fire.flight` | Fire Missile birth | `0x0053E4E0` | 97 `sounds\throwfire` | Launch request is the cast-release request; flight ticks are silent. |
| `projectile.fire.impact` | Fireball contact | `0x005E5288` inside `0x005E5160` | 30 `sounds\fireballhit` | Fixed asset; point gain and signed float-RNG pitch `1 + S(0.1)` on the inclusive native lattice `[0.9,1.1]`. The Fireball removal vslot runs first; null terrain contact owns the same request. |
| `projectile.air.flight` | Ball Lightning cast emission | `0x0053F155` | uniform pool 224 `sounds\throwlightning\1`, 225 `...\2` | `Integer(2)` on the active gameplay stream; cast point gain/pitch. |
| `projectile.air.impact` | Electric contact/Shock spawn | `0x005F365A` | uniform pool 203..205 `sounds\Shock\s1..s3` | `Integer(3)` on the active gameplay stream; point gain and float-RNG pitch. |
| `projectile.water.flight` | Frost Missile cast emission | `0x0053F741` | 38 `sounds\frostmissile` | Fixed asset; cast point gain/pitch. |
| `projectile.water.impact` | Frost Missile contact | `0x005F26F2`; secondary ice burst `0x005F2790` | 36 `sounds\freeze`; then 44 `sounds\icestart` when that branch creates the ice effect | Fixed assets; point gain and float-RNG pitch. |
| `projectile.earth.flight` | Moving Boulder renews global rolling ambience | producer `0x00620B60`; wrapper start `0x0040B161` | start 168 `sounds\rollingstoneloop__loop` | No RNG; `AmbientSound` starts only on requested gain `0 -> positive`. |
| `projectile.earth.flight_end` | Boulder stops renewing the wrapper | wrapper stop `0x0040B189` | stop 168 | No RNG; occurs on previous gain `positive -> 0`. |
| `projectile.earth.impact` | Boulder contact accumulator crosses its threshold | `0x0062141B` | 77 `sounds\rockhit` | Fixed; world point gain. |

The shared Fire-area helper `0x00642BF0` is a sibling reuse beneath the sealed
trigger census, not a new top-level event class. Explode, Immolate,
FireMissile-area, scripted explosion, special-death, and maximum Ring contact
request registry 30 `sounds\fireballhit` at `0x00642CE9`, then registry 97
`sounds\throwfire` at `0x00642D4F`. Both use twice Region point gain; the first
pitch is `1 + S(0.1)` and the second is exactly `0.8`. An Explode Fireball has
already requested the separate ordinary `projectile.fire.impact` row, so it
owns three total requests.

### Secondary and advanced right-click events

The complete per-member file hashes, registry indices, and wrapper classes are
in
[`native-secondary-ability-catalog.json`](native-secondary-ability-catalog.json).
This table pins event ownership; an ability snapshot is never itself an audio
event.

| Skill | Native event sequence |
| --- | --- |
| Call Leviathan `11` | Activation requests `LeviathanRoar__Stream`; the live actor renews `PlaneCross__Loop` until its scale-out teardown. |
| Planewalker `12` | Enable requests `planewalker__Stream`; removal/expiry at `0x0052F470` requests `PlanewalkerOff__Stream`; active plane state renews `PlaneCross__Loop`. Each forced Plane Orb birth requests `distortreality` at Region point gain, then `lightningstart` at exact pitch `2.0` with the same gain (`0x0052D9B1..0x0052DA1F`). |
| Phasing `15` | Accepted collision-tested relocation requests `phase`. |
| Ring of Fire `21` | Helper `0x0063F920` requests `bigfire`, then `nuke`, while creating the 30 fire segments and Shockwave. Each Burning Man first-contact explosion separately requests shared-helper `fireballhit`, then `throwfire`; overlapping contacts own independent pairs. |
| Firewalker `23` | Toggle-on activation requests the `ignite` gain/pitch sequence; toggle-off is silent. Live `Fire_Goodguy` patches renew `lowfire__loop` until the last independently retained patch retires. |
| Magic Storm `27` | Cast requests `magicstorm`; strikes request `lightningstart` and `thunder__Stream`; the cloud renews `rainfall__loop` and `steadywind__loop`. |
| Prismatic Shock `30` | Helper `0x00645540` requests `prismaticspray__stream` at Region point gain, then `lightningstart` at exact pitch `0.8` and the same gain. |
| Ring of Ice `35` | Helper `0x00644460` requests `ringofice` once while creating its bursts and FreezeWave. |
| Earthquake `41` | The first live tick requests `rockhit` and `QuakeCracks__Stream` in that order at Region perspective gain. Live intensity renews `earthquake__loop`; crossing floor phase `3.0` requests `QuakeCrackSmall__Stream`. The earlier `0.6` floor crossing has no sound. |
| Raise Golem `45` | Assembly milestones request `QuakeCrackSmall__Stream`; AI edges request `GolemProvoke__Stream`, `KnockbackGolem`, and `stonestep`. Terminal branch `0x0049A6FF..0x0049A785` requests `stonebreak`, `flamelashstart`, `GolemDie__Stream`, then `rockhit` in that exact order. |
| Stoneskin `46` | Accepted cast requests `StoneSkin__Stream`; modifier apply, refresh, and removal callbacks `0x00624490/0x006244C0/0x00626840` each request `stoneskin`. Natural expiry therefore owns one terminal `stoneskin` request. They do not request the adjacent loaded `stoneskinhit` or general `stonebreak` objects. |
| Teleport `48` | Burst helper `0x00644A00` requests `teleport` once at the source and once at the selected destination, in that order. |
| Magic Circle `49` | Actor tick requests `magiccircle` exactly when remaining lifetime equals `1498`. |
| Magic Trap `50` | Initialize `0x005E95D0` requests `settrap__Stream`, then the bound-primary start cue; terminal trigger requests `trap__stream`. An air-selector target's live 100-update `Mod_ElectricBurn` renews `electric__loop`; merge extends the existing target-owned modifier rather than adding a second loop owner. |
| Dampen `51` | Accepted helper requests `flash` and `dampen__stream` before its CastSpin presentation. |
| Magic Shield `54` | Install/refresh requests `magicshieldup`; absorbed contact requests `hitshield`; break `0x00546650` requests `popshield`; learned Explosive Shield adds `magicshieldexplode`. |
| Acid Rain `72` | Cast reuses `magicstorm`; authoritative damage pulses may request pitched `acidsizzle`. The tick tail submits `pointGain * cloudAlpha(+0x144)` to the shared maximum `rainfall__loop` request only while cloud alpha is positive. The later ground-residue-only phase `+0x158 > 0`, `+0x144 == 0` is silent. |
| Fire Wall `73` | Creation requests `ignite` and `fireballhit`; live fire patches renew `lowfire__loop`. |
| Ether Drain `74` | State transition requests `distortreality` and pitched `lightningstart`; the live field renews `PlaneCross__Loop` and `steadywind__loop`. |
| Call Comet `76` | Fall renews `comet__loop` and later requests `cometwhistle`; impact layers request `explodesteam`, `magicshieldexplode`, `bigfire`, and `ringofice`. |
| Turn Undead `77` | Helper `0x00647EF0` requests `levelup` at pitch `2.0`, then again at pitch `3.0`, before its target query. |
| Mindstar `78` / Regenerate `79` | Dispatcher calls `0x0054FF05` and `0x0054FFD4` both request `mindstar__stream` on either toggle edge; neither owns a persistent sound. |

Secondary/welded casts use the same wrapper rules. The common primary cleanup fan-out also stops 157 fire (`0x00549736`), 160 ice beam (`0x00549747`), 172 steam (`0x00549769`), and 165 meteor (`0x0054977A`). Start sites include 33 `flamelashstart` plus 157 at `0x0054A2C8/0x0054A2D9`, 44 plus 160 at `0x0054A480/0x0054A491`, 172 plus 157 at `0x0054A5DB/0x0054A5EC`, 159 at `0x0054A76A`, 165 at `0x0054A89D`, and 160 plus 159 at `0x0054AA3F/0x0054AA50`. These are fixed choices; they do not create a second ownership model.

### Melee, movement, damage, and death

| Event class | Native trigger | Exact call site(s) | Requested asset(s) | Selection and parameters |
| --- | --- | --- | --- | --- |
| `melee.player.swing` | Player staff swing action | `0x0055024A` | 86 `sounds\staffswoosh` | Fixed asset; local gain and float-RNG pitch. |
| `melee.player.hit_world` | Staff contact with wood/world | `0x0053BE4F` | 85 `sounds\staffhitwood` | Fixed; hit-point attenuation. |
| `melee.enemy.hit` | Sword-family damage contact | `0x00477832` | uniform pool 220..221 `sounds\SwordStrike\strike1..2` | `Integer(2)` on the active gameplay stream; hit attenuation and float-RNG pitch. |
| `movement.footstep.wood` | Player cadence reaches frame multiple 25 on wood | `0x0054AF92` | 104 `sounds\woodstep` | Fixed asset; point gain times the global footstep scalar, float-RNG pitch. |
| `movement.footstep.stone` | Player cadence reaches frame multiple 25 on default ground | `0x0054AFEC` | uniform pool 214..215 `sounds\Step\step1..2` | `Integer(2)` on the active gameplay stream; point gain times footstep scalar. |
| `movement.footstep.splash` | Water/splash movement cadence | `0x0047634D` (parallel family sites include `0x0048664F`, `0x00487CCC`, `0x00533FB1`, `0x0060A222`) | uniform pool 216..219 `sounds\stepsplash\step1..4` | `Integer(4)` on the active gameplay stream; point gain. |
| `damage.player.taken` | Positive, nonterminal HP loss after the ouch deadline | `0x0053074A` | uniform pool 228..230 `sounds\Wizard_Ouch\SAY_OUCH1..3` | `Integer(3)`, then inclusive delay `Integer(20,60)`, same active stream. Gain is spatial gain times `0.25 + 0.75 * (1 - clamp((HP_after - 25)/20,0,1))`. Healing, terminal damage, and presentation-suppressed lanes make no request. |
| `death.player` | Terminal player death installs `GameOver`; its normal branch later advances `Solomon_Riff` | stop `0x005CAE3D`; narration `0x005CAE79` and Boneyard sibling `0x005CAEC8`; music `0x005CAFB9`; Riff `0x004757CB..0x004757DD` | stream 118 `sounds\DeathGuitar__Stream`; `SAY_SOLOMON_LAUGHBIG1`; Boneyard-only queued `SAY_SOLOMON_ANOTHERCORPSE`; immediate song `death` | Constructor stops music, queues the huge laugh in both modes and the second line only in Boneyard mode, then starts `death`. Normal-mode Riff alone restarts stream 118 at tick 550; it is not an individual death-start cue. |
| `death.skeleton` | Skeleton-family terminal branch | presenter `0x0048D2A0`; call `0x0048D368` | entry 79 / object `+0xDAC`, `sounds\skeleton_die` | Fixed asset; `RandomFloat(0.2, unsigned) + 0.8` gives pitch `[0.8,1.0)`. Entry 80 `skellyscream` is the adjacent `+0xDD8` object and is not this call. |
| `death.zombie` | Zombie terminal branch | `0x00494AEE`; rotten splats `0x00494883`, `0x004948ED`, `0x00494957`; groan `0x00494B57` | 105 `zombiedie`; 108 `zombiepoisonsplat` three times when rotten; 110 `zombie_die_groan` | Splats use `[0.9,1.05)`; die and groan use `[0.8,1.0)`. |
| `death.banshee` | Banshee/Wraith terminal branch | `0x0049612B`, `0x00496177`, `0x004961C1` | 8 `sounds\bansheedie` three times; preceding terminal flash uses 34 at `0x004960DF` | First two pitches `[0.9,1.1)`; third `[0.8,1.2)`; flash fixed-pitch. |
| `death.unholy` | Unholy/DemonSkull terminal branch | `0x0049645C`; effects `0x0049647F`, `0x0049649C`, `0x004964B3` | stream 146 `UnholyDie__Stream`; 54 `lightningstart`; 59 `magicshieldexplode` | Fixed branch sequence. |
| `death.demon` | Demon death state and terminal split | `0x0048760F`; split helper `0x00482930` | 34 `flash`, 20 `demondies`, then 31 `fireydeath` | Flash and demon die fixed-pitch; split fire uses `[0.8,1.0)`. |
| `death.imp` | Imp terminal branches | `0x004824A0`; fire call `0x00482A41` | permitted split: 47 `ImpSplit`; ordinary branch: 31 `fireydeath` | Split pitch `[0.9,1.1)`; ordinary fire pitch `[0.8,1.0)`. |
| `death.spider` | Spider terminal branch | `0x00482E13` | 82 `sounds\SpiderDie` | Fixed asset; point gain and float-RNG pitch. |
| `death.golem` | Golem terminal branch | `0x0049A6FF`, `0x0049A732`, `0x0049A74B`, `0x0049A785` | 89 `stonebreak`; 33 `flamelashstart`; stream 125 `GolemDie__Stream`; 77 `rockhit` | Fixed ordered sequence selected by the terminal branch. |
| `death.faculty` | Faculty terminal branch | `0x0049D19B` | stream 121 `FacultyDie__Stream` | Fixed; 122 `FacultyNo__Stream` at `0x0049D4C7` is a nonterminal reaction. |
| `death.heartmonger` | Heartmonger terminal branch | chain calls `0x004A08FC/0x004A0915`; terminal `0x004A0B6F` | pool 179..180 `Chain\clank1..2`; stream 111 `BreakHeartmonger__Stream` | Chain pool uses `Integer(2)` on the active stream; terminal stream fixed. |
| `death.portal` | Portal terminal branch | `0x004A2034` | 75 `sounds\PortalDie` | Fixed; world point gain. |
| `death.coffin` | Coffin terminal branch | `0x0049B549` | 15 `sounds\coffinbreak` | Pitch `[1.0,1.1)`. Coffin movement/room activity separately rolls 181..182 `CoffinCreak` at `0x004A2AAF`. |
| `death.crow` | Crow terminal/retirement branch | `0x00489226` | uniform pool 183..184 `sounds\Crow\crow1..2` | `Integer(2)` on the active gameplay stream; point gain and float-RNG pitch. |
| `death.maggot` | Maggot terminal branch | `0x0049C8E0..0x0049C9F0` | independent uniform pools 211..213 `sounds\Squish\*` and 199..200 `sounds\MaggotSqueak\squeak1..2` | `Integer(3)` then `Integer(2)` on the active gameplay stream; both pitches `[1.0,1.2)`. Squeak gain includes a `[0.25,0.5]` multiplier on point attenuation. |

Other enemy contact families are parallel fixed/pool requests: Pike hit 71 at `0x0047766A`; bone attack 11 at `0x00477977`; zombie punch 109 at `0x0047DC33`; Bite pool 176..178 at `0x0048621E`; ArmorCrash pool 173..175 at `0x0048D1CF`; and bone crack 12 at `0x0048A690`. Every pool draw uses the active gameplay stream.

#### Player footstep owner and lifecycle

`PlayerActor::Tick` owns the complete player-footstep decision inside the
movement branch at `0x0054AD54..0x0054B080`. The branch first compares
`actor[+0x158]^2 + actor[+0x15C]^2` with the float at `0x007DE890`
(`0.01f`). If the squared displacement is not strictly greater, control jumps
to `0x0054B662`: no MoveStep, gait advance, surface query, RNG draw, or
footstep request occurs. Normal `0.9f` release damping therefore permits 21
more movement ticks from the steady cardinal baseline, then becomes silent
even though the retained velocity continues to decay.

The audio sub-branch additionally requires player slot byte `actor+0x5C` to
be zero and the shared application tick `DAT_0081F658` to be divisible by 25.
It is consequently a local-player, 4 Hz request on the global 100 Hz gameplay
clock, not an animation-frame callback or distance accumulator. Collision does
not suppress it: gait and sound remain owned by requested movement whenever
the threshold passed, even if placement was blocked.

Surface selection then follows region virtuals rather than a player-side map:

- special movement state `actor+0x154 == 2` draws uniformly from registry
  216..219, `sounds\\stepsplash\\step1..4`;
- otherwise region slot `+0x118` true requests fixed registry 104,
  `sounds\\woodstep`, through the pitch-and-gain wrapper; and
- slot `+0x118` false draws uniformly from registry 214..215,
  `sounds\\Step\\step1..2`, through the gain-only wrapper.

Both ordinary-surface paths multiply region slot `+0x100` attenuation by the
global footstep scalar `0.5`. The Courtyard vtable `0x00792644` resolves
`+0x100` to `0x005006C0` and `+0x118` to `0x005088F0`; the latter returns zero
unconditionally. Courtyard walking therefore uses only the two `Step` samples
at local gain `0.5`. Selection consumes `Integer(2)` from the active gameplay
RNG, so a browser may use a deterministic approximation but must not infer an
event later from a residual nonzero velocity or replay several missed cadence
ticks as a burst.

Arena resolves slot `+0x118` to `0x004679B0`. That query is true only inside
one of RegionLayout's derived style-zero-river bridge quads; it is not a Road,
Terrain, texture-color, or bounding-box heuristic. Rebuild `0x00653BF0`
derives those quads from the randomized river mesh generated by `0x0064FA90`
and Road intersections, and bridge materialization uses exact DeadHawg record
319. The twelve stock-generated Boneyards currently shipped in the Website's
default bank contain no Terrain records, so their ordinary player cadence
always selects Step1/Step2. `woodstep.wav` is reserved for an exact derived
bridge implementation; treating any generic Road overlap as wood would be a
new rule.

The retail `woodstep.wav` is PCM16 stereo at 44,100 Hz, duration
0.261927 seconds, SHA-256
`501bda33f36d538128cb7ebf2ef9594379524692f442ddb6da4f4cb3ac9f3cf5`.
Its wrapper samples pitch uniformly from `[0.9,1.25)` and applies the same
ordinary footstep gain `0.5`. Step1/Step2 use their gain-only wrapper.

### Pickups, progression, waves, dig, shop, and UI

| Event class | Native trigger | Exact call site(s) | Requested asset(s) | Selection and parameters |
| --- | --- | --- | --- | --- |
| `pickup.coin` | Coin pickup accepted | `0x005E6A1B` | 69 `sounds\pickupcoin` | Fixed, gain 1. Coin spawn uses 25 `dropcoins` at `0x005E67BD`. |
| `pickup.bag` | Loot bag accepted | `0x005E6D20` | 68 `sounds\pickupbag` | Fixed. Bag drop rolls pool 185..186 at `0x005E6C25`. |
| `pickup.orb` | Orb accepted | `0x005E659F` (player-side siblings `0x0053D079/0x0053D099`) | 2 `sounds\gotorb` | Fixed. |
| `pickup.potion` | Potion loot enters the generic bag pickup path | `0x005E6D20` | 68 `sounds\pickupbag` | Fixed. Potion drop itself uses 26 `droppotion` at `0x005E6C5F`. |
| `pickup.magic_book` | Magic-book acquisition | `0x0056D471` (sibling `0x0056D828`) | stream 129 `magicbookget__stream` | Fixed. The in-world book effect uses stream 130 at `0x006039EF`. |
| `potion.use` | Effect accepted and item consumed | `0x0056D246` | 24 `sounds\drink` | Fixed. |
| `potion.invalid` | Potion/action rejected | `0x0056D3D2` | 6 `sounds\badaction` | Fixed. |
| `level.up` | One local level-award invocation crosses at least one threshold | `0x0067C30B -> 0x005C88B0 -> 0x00528A3E` | 52 `sounds\levelup` | Gain `1.0`, once after `0x0067C250` has looped every threshold crossed by that award, paired with the PlayerActor's 180-tick sparkle/light timer. It is not replayed for each queued picker offer. |
| `skill.turn_undead.cast` | Accepted Turn Undead cast enters the skill handler before its target query | `0x00647F6B`; `0x00647FBE` | 52 `sounds\levelup`, twice | Fixed ordered pair: pitch `2.0`, then pitch `3.0`; each request separately recomputes point-derived gain. No RNG. |
| `skill.unlock` | Next queued level-up offer is rebuilt after the prior picker close | `0x00670CD3` | 102 `sounds\unlockskill` | Fixed gain 1; not card hover, card activation, or the first threshold screen. |
| `wave.start` | First arena wave enters combat state | `0x00465D22` (spawn-entry siblings `0x00469983`, `0x0046D506`, state site `0x00470E9D`) | Music transition to song `combat`, track `combat` | No RNG. Per-wave number increments have no one-shot stinger. |
| `wave.end` | Terminal arena completion | `0x00467AA0` | Music crossfade to empty song | No RNG and no wave-complete one-shot; empty song fades/stops the active lane. |
| `dig.shovel` | State-0 dig cursor first becomes strictly greater than constructor slot `4` while shovel byte `+0x240` is armed | `0x0048207A` | uniform pool 209..210 `sounds\shovel\shovel1..2` | `Integer(2)` on the active gameplay stream; gain-only `Sound::Play` at fixed pitch `1.0`, using one half of Region hit-point gain. |
| `dig.throw_dirt` | State-0 dig cursor first becomes strictly greater than constructor slot `15` while dirt byte `+0x248` is armed | `0x004820FE` | uniform pool 222..223 `sounds\throwdirt\throwdirt1..2` | `Integer(2)` on the active gameplay stream; gain-only `Sound::Play` at fixed pitch `1.0`, using full Region hit-point gain. The request precedes `Anim_Flydirt` construction. |
| `shop.purchase` | Debit and item transfer both succeed | `0x0056C10E` | 25 `sounds\dropcoins` | Fixed; dispatch follows the successful transaction. Registry 13 `buysell` is loaded but this retail path does not call it. |
| `shop.purchase_rejected` | Purchase precondition fails | `0x0056C1A6` | 6 `sounds\badaction` | Fixed. |
| `shop.storage_return_double` | Selected storage item is second-activated into backpack | common action `0x0055F054`, callback `0x0056CE80` | 0 `click`, then 4 `backpack_close` | The common action click precedes the accepted callback. Backpack second activation remains ordinary InventoryScreen use/equip behavior. |
| `shop.storage_drag_start` | Storage item crosses the drag threshold | `0x0056CF1A` | 0 `click` | Fixed. Backpack-to-storage is also drag-only but its ordinary InventoryScreen drag start has no separate sound request. |
| `shop.storage_drag_drop` | Either storage drag direction is accepted | `0x0056F55A` | 0 `click` | Pitch 0.75, gain 1. Invalid release restores the source silently. |
| `shop.dowsing_roll` | DOWSE fee accepted and result generation begins | `0x0055FAF0`, `0x0055FE17` | 1 `pickskill` through `SoundEcho`, then 23 `distortreality` | Echo requests at 0/250/500/750 ms use gains 1/0.25/0.0625/0.015625. Distortion pitch is `0.8 + Float(0.1,false)`; that Float precedes `Integer(2)` offer count. |
| `shop.dowsing_purchase` | Dowsing offer purchase succeeds | common `0x0056C10E`, callback `0x0056D18B` | 25 `dropcoins`, then 23 `distortreality` | Next-fee `Integer(10)` precedes the Float; distortion pitch is `1.0 + Float(0.1,false)`. |
| `ui.focus` | Pointer hover/focus changes without activation | no call | no request | Retail menus are mouse-driven and have no native focus sound. The designed browser focus graph must remain silent. |
| `ui.confirm` | Game Over continue/button activation | `0x005CF7BA` | 0 `sounds\click` | Fixed gain 1. Other action handlers use the same registry object. |
| `ui.shop_close` | Common Shop DONE closes the service | `0x0055EFA8` | 64 `sounds\openpanel` | Fixed; the close direction still uses the asset named `openpanel`. |
| `ui.inventory_close` | Standalone InventoryScreen closes | `0x00555853` | 64 `sounds\openpanel` | Fixed. |
| `music.menu_transition` | Scene/menu song selection | title `0x0058A033`; selection `0x00593CA6`; academy sites `0x00508AF2`, `0x00508B7F`, `0x0050F94B`, `0x00510E07`, `0x005110E7`, `0x00512CC7` | `prelude`, `selection`, or `academy` through `Music::PlayCrossfade` | No RNG; caller supplies transition duration. |

The level-up picker has a statically recovered screen-local sequence in
addition to the live census rows above. `0x0066FAA4` plays entry 64
`sounds\openpanel` at gain/pitch 1 when the build delay completes;
`0x00671635` plays entry 1 `sounds\pickskill` only when a card is activated;
and `0x00670D35` plays `openpanel` at gain 1, pitch 0.75 when closing begins.
Pointer hover/focus is silent. Sorceror's Charm ROLL AGAIN uses entry 93
`sounds\summon` at gain 1, pitch 0.8 (`0x00671532`); SAVE SKILL uses entry 0
`sounds\click` (`0x00671568`). A subsequent queued offer uses the existing
`skill.unlock` row. Entry 53 `sounds\levelupskill` remains loaded but has no
retail dispatch.

Standalone InventoryScreen opening is also silent. The keyboard edge at
`0x005CB3A3` and HUD callback at `0x005D8165` call opener `0x005C6F10`
directly, and neither that opener nor constructor `0x00560380` requests
audio. Registry 5 `sounds\backpack_open` is not an InventoryScreen-open
event; its filename must not be used to invent one.

Asset 52 has one distinct skill consumer: `skill.turn_undead.cast`, skill 77's
undead-area effect. `0x00647F6B` and `0x00647FBE` inside `0x00647EF0` issue
two point requests at pitch multipliers `2` then `3`. Those calls are not a
level threshold transition and must not be folded back into `level.up`.

## Playback semantics

### One-shots

All compiled `Sound` entries are loaded with a maximum of ten simultaneous channel records. `0x00407A20` reuses the first record whose channel is not active; if every record is active and fewer than ten exist, it allocates another; at ten it drops the new trigger. There is no oldest/quietest/priority stealing. A retrigger therefore overlaps up to ten copies and then becomes silent rather than restarting a shared cursor.

The gain-only and pitch+gain wrappers both acquire a record. The low body stores `caller_gain * Sound[+0x24]` in record `+0x08`, multiplies it by the record owner scalar copied from `Sound[+0x28]` into record `+0x0C`, applies BASS volume attribute 2, optionally applies `record_base_frequency * pitch` through attribute 1, then calls `BASS_ChannelPlay(handle, 1)`. The restart flag starts the chosen record at the beginning. `Sound::Stop (0x00407F90)` pauses every record and cancels delayed controllers for the same source.

### Loops and ambient loops

Each `SoundLoop` owns exactly one looping channel. `Start` plays only on reference transition `0 -> 1`, increments on every call, and sets transition gain to one. `Stop` decrements; a result below one pauses, clamps the count to zero, and clears transition gain. Repeated starts from different owners do not create more channels, and one owner's stop cannot end a loop while another reference remains. A later `0 -> 1` start calls `BASS_ChannelPlay(handle, 1)` and restarts from the beginning.

Fade state 1 adds the configured fade-in step to one; state 2 subtracts the fade-out step to zero and then stops. The applied volume is the loop's base gain times transition gain. No loop has a priority or steals another loop.

The 13 `AmbientSound` wrappers are one-frame gain accumulators. Producers renew a requested gain every gameplay frame. `AmbientSound_Tick (0x0040B120)` detects zero crossings, starts/stops the referenced `SoundLoop`, applies the requested gain, copies it to previous gain, then clears requested gain. This is why Boulder movement owns rolling-stone audio by renewal rather than by actor construction.

### Streams, music, channel model, and attenuation

`SoundStream` owns one handle. `Play` sets gain and calls `BASS_ChannelPlay(handle,1)`, so a retrigger restarts rather than overlaps; `Pause` pauses that handle. Voices use disposable `SoundStream` objects and the filename request `voices\%s.wav` rather than a compiled registry index.

There is no global SFX priority bus or voice-stealing rank in the stock wrapper. Concurrency is the per-`Sound` ten-record limit, one channel per `SoundLoop`, one handle per `SoundStream`, and two lanes in the single `Music` object. `Audio.SoundVolume` and `Audio.MusicVolume` are separate persisted user scalars; the manager applies effective sound gain through BASS configs 4/5 and music through config 6.

World call sites pass a scalar, not a pan vector. A quiet live vtable walk from the local actor through `actor+0x58` resolved the active world's virtual `+0x100` point-gain slot to `0x004621B0` and `+0x104` hit-point-gain slot to `0x004622D0`. Let `W=world[+0x8BD4]`, `H=world[+0x8BD8]`, and `C=(world[+0x8BCC]+0.5W, world[+0x8BD0]+0.5H)`. For source point `P`, let `d=length(P-C)` and

```text
linear_falloff(d, inner, outer) =
    1                              when d <= inner
    1 - (d - inner)/(outer-inner)  when inner < d < outer
    0                              when d >= outer
```

The point-gain method is `linear_falloff(d, 0.25W, 1.1W)`. When the local player at `*(Gameplay+0x1358)` has alternate/death animation byte `+0x160 != 0`, that result is multiplied by `0.1`. The hit-point method is `linear_falloff(d, 0.1W, 0.5W)`; its interpolated branch alone is multiplied by `0.1` while that same byte is nonzero because the strictly-inside full-gain and strictly-outside zero-gain branches return before the byte check. Exact equality at `0.1W` enters interpolation and is therefore death-damped even though its undamped result is one. This asymmetry is native behavior, not a simplification.

Event-specific envelopes such as the footstep scalar or low-life ouch factor multiply that spatial result. UI calls pass gain one. The wrapper then multiplies the caller scalar by the two per-sound scalars described above. No native stereo pan request was found at any gameplay call site.

## Loop-point and asset-format contract

All 233 compiled entries resolve to PCM WAV files. The catalog provides each path, byte size, and file SHA-256. One-shots and streams retain their source sample rate/channel/bit depth; the playback API receives their native base frequency and applies pitch as a frequency multiplier rather than resampling assets ahead of time.

The 22 looping WAVs are exact below. `smpl` is source-file metadata; “stock loop” is what the native engine actually does. `SoundLoop_Load` sets BASS flag 4 and no stock path calls `BASS_ChannelSetPosition` or reads WAV tags, so every loop spans the entire decoded buffer. Only `maggots__loop.wav` contains an explicit `smpl` record, and its `0..290304` inclusive range is exactly the whole 290305-frame file.

| Registry | Asset | Hz | Channels | Bits | Frames | WAV `smpl` | Stock effective loop |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| 151 | `sounds\beam__loop` | 44100 | 2 | 16 | 220500 | none | `[0,220500)` |
| 152 | `sounds\comet__loop` | 44100 | 1 | 16 | 27230 | none | `[0,27230)` |
| 153 | `sounds\deepthunder__loop` | 44100 | 2 | 16 | 93246 | none | `[0,93246)` |
| 154 | `sounds\earthquake__loop` | 22050 | 1 | 16 | 84504 | none | `[0,84504)` |
| 155 | `sounds\eerie__loop` | 44100 | 1 | 16 | 203197 | none | `[0,203197)` |
| 156 | `sounds\electric__loop` | 22255 | 1 | 8 | 15763 | none | `[0,15763)` |
| 157 | `sounds\fire__loop` | 33557 | 1 | 16 | 75763 | none | `[0,75763)` |
| 158 | `sounds\flyblown__loop` | 11025 | 1 | 8 | 39976 | none | `[0,39976)` |
| 159 | `sounds\gatherrocksloop__loop` | 44100 | 2 | 16 | 108620 | none | `[0,108620)` |
| 160 | `sounds\icebeam__loop` | 44100 | 1 | 16 | 57835 | none | `[0,57835)` |
| 161 | `sounds\iceloop__loop` | 11025 | 1 | 16 | 45845 | none | `[0,45845)` |
| 162 | `sounds\lightningloop__loop` | 22050 | 1 | 16 | 58956 | none | `[0,58956)` |
| 163 | `sounds\lowfire__loop` | 44100 | 2 | 8 | 450560 | none | `[0,450560)` |
| 164 | `sounds\maggots__loop` | 44100 | 2 | 16 | 290305 | `0..290304` inclusive | `[0,290305)` |
| 165 | `sounds\meteor__loop` | 44100 | 1 | 16 | 27230 | none | `[0,27230)` |
| 166 | `sounds\PlaneCross__Loop` | 44100 | 1 | 16 | 38011 | none | `[0,38011)` |
| 167 | `sounds\rainfall__loop` | 22050 | 1 | 16 | 63207 | none | `[0,63207)` |
| 168 | `sounds\rollingstoneloop__loop` | 11025 | 1 | 16 | 32431 | none | `[0,32431)` |
| 169 | `sounds\shockblast__loop` | 22255 | 1 | 8 | 10509 | none | `[0,10509)` |
| 170 | `sounds\Soul__Loop` | 44100 | 2 | 16 | 420589 | none | `[0,420589)` |
| 171 | `sounds\steadywind__loop` | 44100 | 2 | 16 | 49116 | none | `[0,49116)` |
| 172 | `sounds\steam__loop` | 22050 | 1 | 16 | 26093 | none | `[0,26093)` |

## Music

`Music_Load (0x004088A0)` parses `music\music.txt`, prefers `music.mo3`, and falls back to `music.it`. It loads two handles with flag 4, so module playback loops; a song selection positions the inactive lane at the song's tracker order and starts it. The table defines start orders, not separate files or per-song PCM loop points. Track names control channel envelopes inside that same module. A browser port must preserve tracker order/channel behavior or render equivalent stems; treating each track name as a standalone song is wrong.

| Song | Module order | Track sets (module channels kept audible) | Scene/trigger |
| --- | ---: | --- | --- |
| `prelude` | 0 | none | title at `0x0058A033`; run prelude paths |
| `combatprelude` | 5 | `base` 1..6; `combat` 1..20; `heavycombat` 7..20; `danger` 17..24; `glory` 25,26,27,28,29,31,31,32 | combat lead-in/state selection |
| `combat` | 6 | same five sets as `combatprelude` | first wave `0x00465D22`; combat states `0x00469983`, `0x0046D506`, `0x00470E9D`, `0x0047D80F` |
| `boss_aggressive` | 58 | `base` 1..6; `combat` 7..16; `heavycombat` 7..20 | boss selector `0x0068AD05` family |
| `boss_squirmy` | 70 | same three sets | boss selector family |
| `boss_gargantuan` | 82 | same three sets | boss selector family |
| `solomondarktheme` | 95 | none | Solomon Dark theme paths `0x0058F28F`, `0x0058D9E5` |
| `academy` | 101 | none | hub/academy sites `0x00508AF2`, `0x00508B7F`, `0x0050F94B`, `0x00510E07`, `0x005110E7`, `0x00512CC7` |
| `selection` | 116 | none | profile/class selection `0x00593CA6` |
| `death` | 118 | none | Game Over immediate play `0x005CAFB9` |
| `deathguitar` | 122 | none | defined alternate death song; no independent scene selector recovered beyond death paths |
| `academyold` | 126 | none | defined legacy academy song; no current retail scene selector recovered |

`Music::PlayImmediate (0x00409A10)` replaces/starts without a crossfade. `PlayCrossfade (0x00409CD0)` and `Transition (0x00409FA0)` set the per-tick step to `1 / transition_ticks`, swap the active/inactive lane, and start the requested song; `Transition` additionally selects a named track envelope. The tick at `0x00409610` raises the new-lane gain at `+0x68`, lowers the old-lane gain at `+0x6C`, writes module-channel envelopes via attributes `0x200 + channel`, and stops the faded lane when it reaches zero. `Music::Stop (0x0040A3F0)` stops both lanes. A transition argument of `-1` is replaced by the application music-transition setting; natural witnesses include title `prelude` with 200 ticks, selection with `-1`, academy with 2, and combat with `-1`.

Arena initialization has its own scene transition at `0x00470A90`. The branch
reads Arena wave/combat byte `+0x8F14`. When it is zero, instructions
`0x00470E07..0x00470E20` request song `prelude` through
`Music::PlayCrossfade (0x00409CD0)` with literal float `-1.0` from
`0x007DE858`, so the application default supplies the duration. When the byte
is nonzero, `0x00470E83..0x00470EA2` instead calls
`Music::Transition (0x00409FA0)` with both song and track named `combat`.
Later wave-state owner `0x0047D570` selects song `combat` with track
`combatprelude` while moving into the combat lifecycle. Entering an ordinary
Boneyard therefore crossfades Academy to module-order-0 `prelude`; continuing
Academy merely because the menu state still says Hub has no native owner.

## Multiplayer ownership

The normative rule is:

> A peer plays a stock gameplay sound only when that peer's local stock simulation consumes the corresponding actor, lifecycle, or UI transition. Receiving or applying a network snapshot is never an audio trigger.

Consequences:

- The locally owned player produces sound from its stock cast, movement, hit, pickup, and death paths on the owner peer.
- A remote participant or enemy produces sound locally when that peer's materialized stock actor consumes the same transition. The network packet does not call `Sound`, `SoundLoop`, `SoundStream`, `Music`, or BASS directly.
- Persistent network identity binds to the existing actor. Snapshot convergence may update transform, health, status, target, and presentation, but must not rewrite already-consumed current/previous primary selection fields or re-run a lifecycle edge.
- A genuinely absent lifecycle-owned actor may be materialized once behind the existing guarded catch-up path. Repeated snapshots update that actor; they do not construct a new audio owner.
- UI and music selection are peer-local presentation. A local menu action or local scene transition requests them once; no peer relays UI sound.

The Earth regression is the negative contract. `ProcessPendingBotCast` once rewrote the remote caster's current and previous primary fields after stock had consumed them. The next stock tick saw another artificial `0 -> Earth` transition, repeatedly called `gatherrocksloop__loop`, and restarted the loop although the press/release packet and Boulder actor each occurred once. The repair re-arms only a missing startup for which stock produced no native activity, latches one bounded release edge, and then leaves transition fields stock-owned. Rebuilding “sound on snapshot,” “sound on actor update,” or “keep writing selected spell while held” recreates that bug.

The invariant for a replicated held cast is one accepted press edge, at most one stock loop start, persistent local loop ownership while held, one accepted release edge, and a stock-balanced stop. The live fixture records post-call loop reference counts so a renderer cannot hide an ownership leak by merely muting the output.

## 2026-08-15 low-mana primary audio

The pure-primary underpowered return from mana helper `0x0052B150` has
spell-specific audio consumers:

- Ether plays registry entry 32 / audio-registry offset `+0x598`,
  `sounds\\fizzle.wav`, at pitch/gain `1`, then registry 57
  `sounds\\magicmissile` at pitch `1`, gain `.75`.
- Fire plays the same full-gain fizzle, then registry 97
  `sounds\\throwfire` at pitch `1`, gain `.75`.
- Air calls loop-attribute helper `0x00407500` with `.75` rather than one for
  registry 162 `sounds\\lightningloop__loop`.
- Water calls the same helper with `.5` rather than one for registry 161
  `sounds\\iceloop__loop`.
- Earth does not apply a persistent weak-loop gain. Inside the weak/release
  branch, every global tick divisible by 50 plays `fizzle` at pitch `.5` and
  one half of the ordinary Region point attenuation.

These calls happen at emission/sustain time. Ether/Fire must order the fizzle
before the launch cue; channel gain changes must update the existing owned loop
without inventing an extra press edge, and Earth's periodic cue must not
restart either gathering or rolling loops.

## Not Yet Reversed

- Exact sub-frame device latency, BASS resampler interpolation, and OS/driver mixing are below the permanently disabled campaign boundary. They do not alter trigger order, asset identity, loop ownership, or native-tick timing and are not required by the deterministic browser simulation.

## 2026-08-20 enemy ambient loop ownership

Three survival-enemy ticks feed the stock `AmbientSound` one-frame request
accumulator. Every producer submits a point-attenuated gain during the current
tick. The accumulator retains the maximum, starts its one global loop on a
zero-to-positive edge, updates that loop's gain without restarting it, and
stops it on the positive-to-zero edge. Enemy replication therefore carries
producer state; a snapshot arrival is not itself an audio edge.

| Owner | Tick consumer | Registry wrapper/request | Gain recipe | Untouched PCM |
| --- | --- | --- | --- | --- |
| Rotten Zombie (`+0x24E`) | `0x004863A0` | `0x0081CB8C` / `0x0081CB90`, entry 158 `sounds\\flyblown__loop` | native point attenuation | 11025 Hz, mono, 8-bit, 39976 frames, SHA-256 `e4dd23bbe5a2d36762ec54587dacb7cd5465dba64268b0b4b1db198b953422d6` |
| Wraith | `0x00486C30` | `0x0081CB9C` / `0x0081CBA0`, entry 170 `sounds\\Soul__Loop` | native point attenuation | 44100 Hz, stereo, 16-bit, 420589 frames, SHA-256 `661515f9ac51cfb7be5aaa08d7d87667f5b06b6a1e7a530e1a8863b1c46450b4` |
| Coffin | `0x004A2760` | `0x0081CBFC` / `0x0081CC00`, entry 164 `sounds\\maggots__loop` | point attenuation times `min(actor +0x2E0 / 200, 1) * 0.5`; `+0x2E0` is the live owned-Maggot count | 44100 Hz, stereo, 16-bit, 290305 frames, full-file `smpl`, SHA-256 `725332465d0f7d85bd84043ae4a691f0827b227c3ee2aa9fd3226d72bece40db` |

These loops are not attack one-shots and do not belong to individual DOM or
sprite instances. The browser equivalence is one stable audio owner per cue,
one max-gain reduction across the authoritative world snapshot per render
update, and balanced start/update/stop edges as producers enter, move, spawn
Maggots, die, or leave the scene.
