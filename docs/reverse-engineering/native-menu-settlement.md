# Native menu settlement specification v2.9

This specification governs every G11 native-menu standalone and navigation
endpoint recording. Its rule is: what two independent fresh instances
reproduce byte-exactly is contract; what they reproducibly vary is envelope;
anything else is a STOP finding.

A valid window contains at least 40 consecutive samples spanning at least two
seconds. Surface identity and semantic generation are constant. The projected
structural core is byte-identical in relative draw order. Each non-core art
member must machine-classify as rect-animated, visibility-cycling, ephemeral,
or ambient-persistent under the v2.5 ambient-lifecycle rules. Text or controls
may never churn or visibility-cycle. Absolute draw ordinals and screen-local
synthetic element ordinals are bookkeeping, not native identity. Ambient
members may occupy at most 40 percent of the peak census, and a declared
ambient class with no measured event is a recorder defect. Motion capability
is asymmetric: one observed motion event proves capability, while a quiet
window does not prove immobility. The fixture therefore pins structural
identity, relative order, an honest anchor, and the union of measured
envelopes. Fixed-delay capture and operator-supplied provenance are forbidden.

Population, overlay-contamination, cross-window motion, and ambient-lifecycle
corrections remain the narrow v2.1, v2.4, v2.3, and v2.5 diagnosis paths. Every
leg requires paired evidence and zero unexplained residual fields. Canonical
cross-instance comparisons sort semantic members by relative draw order and
then deterministic element id; raw list position is never contractual.

## Path-dependent core

Settlement v2.6 adds one rule without weakening those predicates. When one
native screen id has two or more structural states, it may fork only when each
state independently settles in two fresh instances, a deterministic entry path
or durable session state selects it, and the states differ in element census.
Each fork carries the parent screen id and a path qualifier, has its own
standalone fixture and machine-derived provenance, and every graph endpoint
using the parent screen binds to one named fork. A time-selected state, an
equal-census payload variant, a one-instance state, or an unbound endpoint is a
STOP.

The fork predicate pins the full settled element census, not the projected
core count. In particular, a member such as resumed Hub's motion-capable
`UI.28` remains part of the state census even though v2.3 correctly envelopes
it outside the reproduced structural core. The resolver pins both values and
the core hash independently.

The only authorized G11 fork is Hub:

- `hub_new_game` is selected by `create_discipline_to_hub` entering a new-game
  session.
- `hub_resumed` is selected by durable resumed-run state for the Hub source of
  `hub_to_pause` and the Hub destinations of `pause_to_hub_resume`,
  `profile_select_resume_to_hub`, and `settings_to_hub`.

Both layouts cite the same hashed
`hub-path-dependent-core-stop-audit.json` decision evidence. Their element
censuses are measurements carried by the fixtures and re-derived by the
resolver; this document does not duplicate those golden values.

## Animated families

Settlement v2.7 covers repeated movers whose captured ordinals cannot name a
stable member. Two or more full-presence members of one art id collapse to one
animated-family record only when they are byte-identical outside `rect`,
`unclipped_rect`, and draw order; their captured ordinals rotate through a
constant collective relative-slot set; and their measured geometry ranks cross
in both fresh instances. The record pins the art id, exact per-sample member
count, non-geometric payload, collective slot set, and union envelope. Any
member-count change, non-geometric variance, non-constant collective slots, or
rank crossing not reproduced in both instances remains a STOP. Rank-stable
movers retain per-member envelopes.

The only authorized G11 animated family is the eight full-presence `UI.3`
members on `skill_picker`. The accepted STOP audit is
`6f88fc371b80add74888296fe84561b27facd047ab27097d415c3ec72675e5f3`;
its stop manifest is
`6bdf8525c5ed969a4e2ed3855d02376d68b5069254ec0e1ffc25ee52e4bb4f6c`.
The two `UI.62` movers remain independently enveloped because their measured
geometry ranks do not cross.

## Choice slots

Settlement v2.8 covers full-presence roster art in structurally fixed slots.
After ordinary core, lifecycle, motion, and animated-family resolution, a
cross-instance residual may become a choice slot only when every residual is a
pure art draw at the same one-based relative draw positions; instances differ
only in `art_id`, `rect`, and `unclipped_rect`; each position uses one atlas
namespace; and every observed rectangle has exactly the selected art entry's
`logicalSize` from the machine-built renderer asset manifest. Rectangle centers
must reproduce as the same slot anchor, and multi-draw copies must reproduce
the same count and exact center-offset vectors. A failure of any leg remains a
structural-core STOP.

A choice-slot fixture pins the anchor, relative positions, offset structure,
atlas namespace, manifest size witnesses, and per-instance roster evidence.
The primary instance's art and full payload are retained only as a
`choice_dependent` exemplar. Cross-instance confirmation is structural and
never asserts roster identity. Captured ids remain positional bookkeeping; a
consumer must not treat an exemplar ordinal as native identity.

The only authorized G11 choice slots are on `skill_picker`: positions
`{30,31}` at anchor `(604,386.5)` and positions `{40,41}` at anchor
`(1004,386.5)`, each with offsets `[(0,0),(-4,-4)]` in the `Skills` atlas.
The primary exemplars are `Skills.48` and `Skills.45`; the confirming roster
observed `Skills.83` and `Skills.92`. The ruling is re-derived from the sealed
settled windows and cites the choice-core audit
`f7669f7bebeaa0703af9af2fb49c86e59ccb62e9906e185c3f657ad8b90bbb5e`,
full resolver transcript
`da11a6d91171a0fec54cb414de2f4f1a6d88c3dcc8d4719a8476b09f0c2e2b22`,
and stop manifest
`6231eeda4710d557b99cbf6f7144c80635ceaf03b34f6c5dbe951e653b24d4a0`.

## Enumeration order is not paint order

Settlement v2.9 adds one bounded historical-correction rule for
`beta-notice`. The landed generation-13 hook snapshot contains the same
34-member structural core as the paired settled capture, but its element list
places the OK-plate `UI.101`, `UI.54`, `UI.54` group at relative core positions
8-10. That order came from G11 hook enumeration; it was not native paint
order. The independently sealed preview trace at
`webgame/client/ambient-title-data.json`, introduced by commit
`b3eafc6c4ebccd574f534796203c7c7bea702280` and hashing to
`58af8f9a851936db633e7660da19f9295c8040931315799fdb10a08a1a2721b7`,
places the exact art-and-rectangle trio at native paint positions 100-102.
That is the final three-member group reproduced by both settled instances.

The correction is data-bound and fail-closed. The generated contract joins
the sealed STOP audit to the paint table by exact `art_id` and rectangle, then
pins each member's full non-ordinal semantic hash. Promotion requires the
landed and settled cores to have exact set equality, an unchanged 31-member
LCS after removing the trio, the three members to belong to the derived
overlay reference, the landed positions to be exactly the audited positions,
and the settled positions to be the final three core positions. Removing or
changing one member, moving any other member, or placing the trio anywhere
else is still a STOP. No other layout or order permutation can enter this
path; all v2.1-v2.8 guardrails remain unchanged.

## Changelog

- **v2.9 — 2026-08-07:** the accepted beta-notice landed-core-order STOP
  proved that one generation-13 fixture encoded hook enumeration rather than
  native paint order. Added the exact three-member, beta-notice-only correction
  above; no general reordering tolerance was added.

- **v2.8 — 2026-08-07:** the accepted skill-picker choice-core STOP showed
  equal-census, full-presence roster art at two reproduced manifest-centered
  slot structures. Added manifest-arithmetic choice slots; all v2.1-v2.7
  guardrails remain unchanged.
- **v2.7 — 2026-08-07:** the accepted skill-picker varying-member-identity STOP
  showed an eight-member same-art mover set with ordinal rotation and geometry
  rank crossing in both instances. Added animated families while preserving
  per-member treatment for rank-stable movers.
- **v2.6 — 2026-08-07:** the accepted Hub path-dependent-core STOP showed two
  independently settled, different-census Hub states selected by entry path or
  durable session state. Added exact per-path layouts and exhaustive endpoint
  binding; all v2.1/v2.3/v2.4/v2.5 guardrails remain unchanged.
- **v2.5 — 2026-08-06:** added measured ambient-lifecycle classes, reproduced
  structural cores, relative draw order, overlay derivation, and union
  envelopes.
