# Discipline Replication and Stock Concentration Defects

Date: 2026-08-02
Baseline: `1497bf5`
Stock executable SHA-256: `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`

This note freezes the investigation before any implementation change. It covers
the human-player discipline replication defect and two suspected stock
concentration defects. The stock findings are descriptive only: this work does
not change Deflect or Creativity gameplay behavior.

## Method and evidence

The native findings came from a fresh direct headless Ghidra run against the
stock executable, using the repository's existing read-only Ghidra project. The
focused exports are in
`/mnt/d/codex-evidence/skillfix-20260802/ghidra/`:

- `deflect-decompile.txt`
- `deflect-concentration-instructions.txt`
- `concentration-switch-table.txt`
- `creativity-decompile.txt`
- `creativity-slot-check-instructions.txt`

The earlier complete skill catalog and Create-screen analysis remain in
`/mnt/d/codex-evidence/skillre-20260801/`. Targeted live observations are
recorded separately after the static implementation and battery are complete.

## Human discipline replication: loader defect

The wire format is not losing discipline. `StatePacket` and `CastPacket` both
carry the semantic `discipline_id`; the receiver copies it into the participant
profile; and remote materialization already maps semantic Mind, Body, and
Arcane to native roots 6, 5, and 7. Explicit bot profiles enter through that
semantic path, which explains why bots retain the right discipline.

The gap is on the local human capture side. A newly created local profile starts
with semantic Arcane. The live sampler refreshes level, experience, the selected
primary/element inferred from gameplay selection state, and belt secondaries,
but never reads the stock progression selection at `progression + 0x830`.
Consequently a human Mind or Body choice never replaces the default before the
profile is serialized. Peers faithfully receive and materialize that stale
Arcane value.

This is one instance of a wider capture/classification gap. Stock Create
finalization `0x005D0290` writes one native loadout quartet into progression:

| Progression field | Meaning |
| --- | --- |
| `+0x82C` | selected element-family root |
| `+0x830` | selected discipline-family root |
| `+0x86C` | starting primary row |
| `+0x870` | starting secondary row |

The loader configuration calls three of these fields "appearance primary"
values and the local sampler captures none of the quartet as a unit. The
profile's legacy `appearance_choice_ids[4]` storage is already wide enough for
the quartet, but remote priming currently consumes only indices 0..2 and writes
them to `+0x82C`, `+0x86C`, and `+0x870`; that incorrectly treats index 1 as a
primary row and drops index 3. Fixing only `discipline_id` would leave the same
broken path for the other stock-owned loadout selections. The repair therefore
must capture, validate, serialize, and prime the complete quartet while keeping
the semantic element and discipline fields authoritative.

There is a second domain mismatch at the Create UI boundary. Stock raw
discipline point 0 is Arcane, point 1 is Body, and point 2 is Mind. The loader
configuration and several automation maps label points 0 and 2 in reverse.
Those mappings must be corrected together; the semantic protocol enum remains
Mind 0, Body 1, Arcane 2 and must not be reused as a raw Create point index.

## Deflect concentration: confirmed stock defect

The concentration dispatcher is `0x00661FD0`. Its jump table begins at
`0x006623B8`; row 68 (Deflect) dispatches to `0x006621E8`. That case requests
the `mConcentration` property and then joins the arithmetic tail at
`0x006621C1`, which divides the returned value by 100 and adds it to progression
field `+0xA8`. Row 69 (Resist Poison) uses that same derived field, so `+0xA8`
is the poison-resistance lane rather than Deflect's physical-reflection chance.

The stock Deflect data has no `mConcentration` property. Property reader
`0x0065D540` returns numeric zero for an absent property. The Deflect case thus
adds zero to poison resistance and never modifies the Deflect chance or damage
reflection path. The advertised concentrated physical-reflection multiplier is
not implemented by this executable. This is stock behavior, not a loader
regression, and remains unchanged pending an owner decision.

## Creativity concentration: confirmed stock defect

The stock level-up offer builder is `0x0066F920`. At `0x0066FB57` it pushes the
literal index `0x10` (fixed concentration slot A), calls the gameplay-selection
accessor `0x0046B140`, and at `0x0066FB63` compares the returned row only with
`0x3F` (Creativity, row 63). It never queries fixed slot B/index `0x14` and does
not inspect the Mind Chug timer at progression `+0x828` before deciding whether
to run Creativity's Insight branch.

This differs from the central concentration refresh at `0x006623F0`, which
reads both A and B when the timer is zero and iterates every learned category-3
skill while Mind Chug is active. The concentration setter `0x005D5600` likewise
understands A, B, and the timer. Creativity's separate offer-builder check
bypasses those normal semantics, so Creativity works only when its row is in
slot A. It is ignored in slot B and during Mind Chug unless it also happens to
occupy slot A. This is stock behavior and remains unchanged pending an owner
decision.

## Planned regression boundary

The loader change is limited to the human/native loadout replication path and
the raw Create action mappings. Regression checks must prove all four native
selection fields, semantic Mind/Body mapping in both directions, unchanged bot
mapping, and the corrected raw UI indices. Live proof must show a Mind host and
Body client observing each other's true disciplines, plus an explicit bot
profile retaining its discipline. Deflect and Creativity receive observation
and documentation only.

## Post-implementation live observations

The final isolated run used instances `skf-host` and `skf-client`, UDP ports
47790/47791, and `SDMOD_DISABLE_AUDIO=1`. The complete machine-readable record
is `/mnt/d/codex-evidence/skillfix-20260802/live/skillfix-live.json`.

The host selected Fire/Mind. Its local native quartet was `1/6/16/21`; its
materialized view of the client carried semantic Water/Body (`1/1`) and the
native quartet `3/5/32/35`. The client selected Water/Body. Its local native
quartet was `3/5/32/35`; its materialized view of the host carried semantic
Fire/Mind (`0/0`) and the native quartet `1/6/16/21`. Both remote actors were
materialized with valid transforms. The host and client screenshots in
`live/screenshots/host-both-peers.png` and
`live/screenshots/client-both-peers.png` show both players from the respective
views.

An explicit Earth/Body bot retained semantic element/discipline `2/1` and
native discipline root 5 on both peers. Its four native-human choice IDs
remained unspecified (`-1/-1/-1/-1`), exercising the existing semantic bot
mapping rather than the new human quartet path.

For Deflect, the live fixture made row 68 active at effective rank 1, selected
it in concentration slot A, and called the stock refresh. A trace at
`0x00661FD0` observed argument 68 exactly once. Deflect chance remained
`0.0 -> 0.0`, and the poison-resistance lane also remained `0.0 -> 0.0`.
Together with the static case at `0x006621E8` and absent-property return at
`0x0065D540`, this confirms that the shipped branch executes but supplies no
Deflect bonus.

For Creativity, the first live fixture used A = -1, B = 63, timer = 0; the
second used A = -1, B = -1, Mind Chug timer = 3600. During each native picker
reveal, a trace at `0x0046B140` observed the fixed index 16 query. Every option
in both four-option offers had apply count 1. The live observations match the
static `PUSH 0x10` at `0x0066FB57`: this picker check does not recognize slot B
or the Mind Chug timer.

No Deflect or Creativity gameplay behavior was changed. Both game PIDs were
stopped only after their staged executable paths matched, and no `skf` process
or listener on either assigned port remained.

## Addendum: bot-retirement timeout disposition

The original post-implementation run reported `botRegression.clientRemoval`
as unobserved after ten seconds. That result did not mean that the remote bot
remained registered indefinitely, and it was not caused by polling the wrong
snapshot field. The wait called `sd.bots.get_participant_state(bot_id)` and
tested its `available` field. That API returns `nil` when
`ReadParticipantSnapshot` cannot find the participant; while a participant is
present, `FillBotSnapshot` sets `available = true`. A received
`ParticipantStateFlagRetired` packet calls
`ResetRemoteParticipantSessionEpoch`, which erases the participant from the
runtime registry. The polled key is therefore the direct public view of the
registry entry that retirement removes.

A short two-cycle probe repeated the add/remove operation at each relevant
revision. One cycle sampled the client continuously through the original
ten-second window and then continued until the transition; the other left the
client idle for three seconds before sparse sampling. The first observed absent
times were:

| Source revision | Loader build | Dense cycle | Idle cycle |
| --- | --- | ---: | ---: |
| `1497bf5` baseline | Release | 0.373 s | 3.355 s |
| `15f70cc` immediately before the loadout fix | Release | 0.328 s | 3.335 s |
| `f64c968` loadout fix | Release | 0.330 s | 3.336 s |
| `5363bd7` landed result | Release | 0.338 s | 3.344 s |
| `1497bf5` baseline | Debug | 15.378 s | 10.514 s |
| `5363bd7` landed result | Debug | 20.075 s | 12.876 s |

The idle-cycle figure includes the initial three-second no-query interval. In
both Debug runs the dense cycle still showed `participant_available=true`,
`participant_materialized=true`, `bot_available=true`, and `bot_count=1` at
ten seconds. Continuing the same probe then showed all three availability
views false and `bot_count=0`. The client retirement log independently records
the same transition. Baseline Debug host retirement at `22:53:36.277` reached
the client at `22:53:51.273`; the second cycle took 10.046 seconds. Landed Debug
took 18.907 and 13.385 seconds. Release host-to-client retirement log deltas
were 31--62 milliseconds across baseline, the pre-fix revision, the exact fix
commit, the refactor, and the landed result.

The build-mode difference explains why the original final run alone exposed
the timeout. `Verify-Workspace.ps1` defaults to Debug and invokes
`Build-All.ps1`, which replaces the loader beside the launcher in
`dist/launcher`. The campaign ran the Release build gate before the default
workspace verification, so its subsequent live harness injected the restaged
Debug loader. During the two Debug reproductions the client logged 92 and 120
app-thread gameplay tick gaps, commonly 400--900 ms, while each Release client
logged one. The retirement packet is reliable and repeatedly sent, but its
receipt and registry cleanup share that heavily delayed app-thread transport
service path. Dense live polling adds further Debug load. Ten seconds is not a
valid deadline for that diagnostic configuration.

Classification: **pre-existing harness-timeout artifact**. Baseline `1497bf5`
reproduces it under the identical Debug probe, while the exact `f64c968`
Release result is indistinguishable from its pre-fix Release parent. The bot
does eventually disappear, the wait used the correct snapshot key, and no
runtime behavior was changed. Future acceptance runs should explicitly restage
Release after a default workspace verification and treat Debug retirement as a
longer diagnostic observation rather than a ten-second assertion.
