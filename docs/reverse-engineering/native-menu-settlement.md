# Native menu settlement specification v2.13

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

A standalone trace that begins after population cannot manufacture an earlier
generation witness. In that case promotion may use one uniquely resolving
primary/confirmation navigation-endpoint pair for the same layout, but only
when both fresh instances contain the landed generation and the resolved
endpoint layout equals the standalone. Multiple qualifying endpoint pairs are
an ambiguity STOP. Absolute layout-generation counters are capture-path local,
so the paired trace proves the generation change and screen structure; its
settled counter need not equal a different standalone recording's local
counter.

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

The only authorized G11 fork is Hub. It has three exact layouts:

- `hub_pristine_second_new_game` is selected under the pristine baseline by
  the same-process route first-run Hub -> Main Menu -> New Game -> Create ->
  Hub.
- `hub_new_game` is selected by direct New Game -> Create -> Hub only under
  the receipted two-action derived baseline described below.
- `hub_resumed` is selected by durable resumed-run state for the Hub source of
  `hub_to_pause` and the Hub destinations of `pause_to_hub_resume`,
  `profile_select_resume_to_hub`, and `settings_to_hub`.

Each layout cites its own accepted, hashed decision evidence. Their element
censuses and exact semantic multisets are measurements carried by the generated
binding contract and re-derived by the resolver; this document does not
duplicate those golden values.

## Hub baseline legitimacy and exact path bindings

Settlement v2.12 adds the `hub_pristine_second_new_game` state. Two independent
instances reproduced the same settled layout reached from the pinned pristine
baseline, in the same process, after returning from the first-run Hub to Main
Menu and entering New Game again. That state contains the five full-presence
`LevelPicker.0/.2/.4/.5/.6` members and motion-capable `UI.28`. It is a third
layout, not a replacement for either earlier fork, and the exact multiset is
valid only on that path and baseline.

Settlement v2.13 closes the provenance defect behind the retained
`hub_new_game` content. The old v7 captures copied retail durable state into
their stages, so their content could not establish a legitimate baseline even
though it settled. Starting independently from pristine profiles, the bounded
restart experiment and durable-variable bisection found a deterministic
in-game derivation. Contact with the unique type-5003 Annalist changes
`class_enabled[0]`; after a clean Leave Game, Quit, and relaunch, contact with
the unique type-5004 PotionGuy/Fomentius changes `class_enabled[1]`; a second
clean exit and relaunch then makes direct New Game reproduce the retained Hub
multiset in both instances. The first field suppresses `UI.28`; the second
promotes the five LevelPicker members from null to their reproduced visible
geometry. Write watches observed exactly one native change for each action,
and an isolated two-field replay reproduced the same result. Thus the v7
content is vindicated while its copied-profile provenance remains invalid.

No capture baseline may be made by copying profile or durable state from any
install. A baseline is either the pinned pristine `fresh_install` state or is
derived from it by a documented, deterministic, receipted in-game procedure.
Every layout and navigation edge records a baseline id; the recorder and
promoter match the capture's exact machine-derived profile identity to one
unambiguous registry witness and then enforce the binding's required baseline.
The fresh `create_discipline_to_hub.after` endpoint binds to
`hub_pristine_second_new_game`; the same endpoint under the two-action derived
baseline binds to `hub_new_game`. All resumed-Hub bindings remain pristine.
An unknown identity, wrong derivation receipt, wrong baseline for a binding,
or reuse of either exact multiset at another layout/path is a named STOP.

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

## Controls title capture defect

Settlement v2.10 adds one bounded landed-metadata correction. The old
`controls` fixture omitted both the player-visible title member and the
top-level `layout.screen_title`, leaving that field empty. Two independent
classifier-agreed Controls windows reproduced the exact case-sensitive title
`Wizard Controls`; the live Controls builder obtains it from the recovered
`surface.controls` definition, and snapshot construction copies that measured
semantic surface title into `layout.screen_title`. The accepted STOP audit is
`0377809414de5a1e5d0b8af01baaf1ee8221c5e586e81d7dfda95f18d1da703f`.

The correction applies only when the compared layout id and native screen id
are both exactly `controls`, the landed title is exactly empty, and the settled
title is exactly `Wizard Controls`. The title text member follows the ordinary
settled-content diagnosis paths; v2.10 authorizes only the top-level field.
Any case change, any other old or new value, any other field, or any other
layout still takes the unchanged mismatch STOP. The v2.1-v2.9 settlement and
diagnosis guardrails remain unchanged.

## Controls structural-core capture defect

Settlement v2.11 adds one exact, data-bound supersession for the `controls`
structural core. The superseded capture is preserved byte-for-byte in the
shellfix baseline snapshot and pinned by its committed-file hash. Its measured
semantic multiset contains the complete 15-draw G11 session-bleed block, ten
additional stale art draws, and no text member. The paired fresh captures
instead reproduce the full key-bindings page: panel and art, the visible title
and row texts, and the interactive Back affordance. The accepted structural
STOP audit is
`22fc8f3061a0f0577bf805ab1ddf750416744bc0097405187321b9feeae148f1`;
the title audit remains
`0377809414de5a1e5d0b8af01baaf1ee8221c5e586e81d7dfda95f18d1da703f`.

The generated contract pins the complete old and new semantic multisets,
their full fixture receipts, both independent classifier-agreed settlements,
and the regenerated `settings_to_controls.after` and
`controls_to_settings.before` endpoints. Promotion accepts the supersession
only when every receipt and every semantic member matches that contract and
both endpoints byte-equal the settled standalone. Dropping, moving, or adding
one member fails the same structural mismatch; claiming the contract for
another layout fails its Controls-only scope. A candidate with any other file
receipt—including the sealed main-menu surface-substitution candidate—never
enters v2.11 and still reaches the pre-existing wholesale-substitution STOP.
All v2.1-v2.10 rules remain active, and no general settled-only-member tolerance
was added.

## Changelog

- **v2.13 — 2026-08-08:** the accepted Hub provenance-boundary STOP was
  resolved by a two-instance, pristine-derived Annalist then
  PotionGuy/Fomentius procedure. Added the exact second baseline and
  per-binding qualification; copied install state is explicitly forbidden.
- **v2.12 — 2026-08-08:** the accepted pristine-path STOP added the exact
  second-New-Game Hub layout reached in the same process from the pristine
  first-run Hub. No existing Hub binding was widened or replaced.

- **v2.11 — 2026-08-07:** the accepted Controls structural-core STOP proved
  that the old fixture combined the complete G11 session-bleed block with
  stale art while omitting the live key-binding texts. Added the exact
  old-multiset-to-new-multiset supersession above; no count-, class-, or
  layout-general tolerance was added.

- **v2.10 — 2026-08-07:** the accepted Controls title STOP proved that the
  stale landed capture omitted its player-visible title and left
  `layout.screen_title` empty. Added the exact Controls-only correction above;
  no general title tolerance was added.

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
