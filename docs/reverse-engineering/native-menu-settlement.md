# Native menu settlement specification v2.22

This specification governs every G11 native-menu standalone and navigation
endpoint recording. Its rule is: what two independent fresh instances
reproduce byte-exactly is contract; what they reproducibly vary is envelope;
anything else is a STOP finding.

A valid window contains at least 40 consecutive samples spanning at least two
seconds. Surface identity, semantic generation, and layout generation are
constant within that one instance's window. The projected
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
an ambiguity STOP. Absolute layout-generation counters are session-cumulative,
instance-local bookkeeping. A trace records its measured value, but structural
identity comes from the exact member multiset and relative sequence described
below.

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

The derived baseline identity is pinned after that final settled New Game
route, not before it. The first capture pass proved that entering New Game
rewrites only `settings.txt`; its other five durable files remain byte-identical,
and each post-route file set reproduced the separately recorded route-complete
receipt. The recapture registry therefore uses those post-route identities and
cites `hub-v213-recapture-baseline-refresh-audit.json`. This keeps the baseline
pristine-derived and action-receipted without copying durable state, while
avoiding a one-use pre-route identity that the capture itself necessarily
supersedes.

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

## Fresh-baseline skill-picker recapture

Settlement v2.14 supersedes only v2.8's permission to reuse the legacy
`skill-picker` windows. That permission predated the baseline-legitimacy rule
and could not prove that the loadout surface was captured from pristine state.
The fixture now comes from two new `pristine_fresh_install` instances. Their
launch receipts, traces, confirmations, and fixture headers all carry the
machine-derived profile identity selected by the committed baseline registry.
The old v7 windows remain diagnostics and cannot promote. The accepted
provenance STOP audit is
`b3e8fb6b2f3a1a89a616b57380e58a324af733c3ad070d8d6fe8af3434b95bc8`.

The v2.7 animated-family and v2.8 choice-slot rules are unchanged. The fresh
windows must independently re-prove the `UI.3` family rank crossing and all
five arithmetic choice-slot conditions against the renderer asset manifest.
Any fresh/legacy difference is recorded, and the fresh observation wins; no
legacy-provenance exception exists.

## Non-semantic overlay states

Settlement v2.15 distinguishes a player-visible overlay from a menu-layout
surface. A state is a non-semantic overlay only when two pristine instances
both fail the operator-tag agreement gate in the same way, their
machine-classified underlying surface settles with equal text/action payloads,
and their settled player-visible frames differ from that surface's accepted
visual. Such a state produces an overlay record containing the underlying
surface id and settled agreement, both visible frames, the measured activating
control and route, and an explicit declaration that it has no observable
semantic members of its own. A tag-agreeing state cannot use this class, and an
overlay record that claims a member payload is invalid.

The only authorized G11 record is
`dark_cloud_settings_credentials`. The measured Login Info / Modify action
opens a credentials panel whose widgets live outside the menu-member system;
the semantic classifier continues to report `main_menu`. The old
`dark-cloud-settings` screen fixture was therefore mischaracterized and is
retired, while the two activating navigation endpoints bind to the typed
overlay record. The evidence seam observes frames and settled underlay
semantics only: it never types credentials or changes durable Dark Cloud state.
Any other tag-disagreeing state requires its own audit.

## Multi-state path-dependent cores

Settlement v2.16 extends v2.6 for one native screen that has more than one
exact, history-selected core. Every state must settle independently in both
fresh instances under the unchanged text-membership guardrail. Every graph
endpoint touching the screen binds to exactly one measured state. Differences
between states must equal the enumerated retained-member set byte-for-byte;
geometry, payload, and all non-retained members remain invariant. A fourth
state, an extra heading, a wrong state at a bound endpoint, or any unbound
endpoint is a STOP. The binding set never learns or widens from a new sample.

The only authorized multi-state screen is `game-settings-gameplay`. Visiting a
child panel leaves that panel's full heading text member visible for the rest
of the Settings visit. The two instances reproduced this deterministic
accretion order:

1. `base`: the 28-member settled census used by the standalone,
   `pause_to_game_settings.after`, and `settings_to_performance.before`.
2. `performance_retained`: the base plus the exact `TWEAK PERFORMANCE`
   heading, used by `performance_to_settings.after` and
   `settings_to_dark_cloud_settings.before`.
3. `performance_dark_cloud_retained`: the preceding state plus the exact
   `DARK CLOUD SETTINGS` heading, used by
   `dark_cloud_settings_to_settings.after` and `settings_to_hub.before`.

The corresponding structural-core censuses are 27, 28, and 29 because the
motion-capable `UI.28` member remains enveloped outside the core. This is native
player-visible retention, not a tolerance or a canonicalization filter. The
accepted cross-observation audit is
`74f125e8faca4624446907747fdad07250c788290d60fde95a3b91ddd81829a7`;
the exact endpoint question manifest is
`4d1708d1cbb49a69eb63aeb049ee4b404772a789aa8a058b3c4486a8a1fd0c7c`.

## Semantic dialog composite states

Settlement v2.17 distinguishes a semantic dialog composite from both an
ordinary screen and a v2.15 non-semantic overlay. A composite is legal only
when two pristine instances both classify the operator's dialog capture as one
specific underlay reached through capture surface `dialog`; the complete
machine-derived dialog semantic multiset is present; the two full canonical
multisets agree; and both the visible dialog frame and post-dismissal underlay
frame reproduce bit-exactly. Promotion pins the underlay fixture, dialog
multiset, zero-residual decomposition, measured dismissal control, both frames,
pixel-delta bounds, and a typed dismissal edge. A residual member, retagging,
or unqualified route remains a STOP.

The only authorized composite is `beta_notice_first_boot`: the 28-member beta
dialog over the five-member `control_scheme_picker` underlay on a pristine
first boot. The qualified pause-entry `beta-notice` remains an ordinary
28-member screen fixture. The contaminated 34-member legacy capture is retired
as evidence-of-era only. Its old paint-order contract was re-derived against
the qualified 28-member core, where the measured OK-plate trio remains the
final three relative core members. The accepted path-state audit is
`7253b6e0d853182aa7ea73500e4753eec5892a2a7ad449bfbdc23c4792073857`.

## Instance-local generation metadata

Settlement v2.18 first established that absolute layout generation and its
semantic mirror are non-rendered build bookkeeping. Their measured values are
never hand-edited and captures are never selected by counter value. Each value
must remain constant across its own 40-sample settled window; a mid-window
change is a rebuild and therefore unsettled. A fixture carries the primary
instance's measured value, and a generation-only landed correction is legal
only when the complete semantic multiset, relative sequence, and every bound
endpoint have zero residual. The Control Scheme Picker audit that established
the path-local case is
`17dda126fb37ff65d7cdba785cc628435d2059fcd20571f6c3b035377d86b313`.

Settlement v2.19 supersedes only v2.18's mistaken requirement that two fresh
instances reproduce the same absolute counter. The 34-pair corpus showed that
generation is a session-cumulative layout-rebuild counter whose value is
instance-timing-sensitive: drift of minus two through plus two occurred in
both directions at route depth, while the first-layout picker pair agreed
because no earlier rebuild could drift. For each pair, exclusion of generation
is conditional on a machine projection of both recorded windows proving the
same complete structural-core multiset and relative sequence, all other
member-system fields exact, every bound endpoint enumerated, and zero residual.
A pair with any non-generation difference remains an ordinary failed capture.

The v2.19 audit re-derived all ten disagreeing standalone pairs and all 24
disagreeing navigation endpoints from their sealed traces. All 34 core proofs
pass; each receipt records both measured counter values, the member-multiset
hash, relative-sequence hash, bound endpoints, and zero-residual verdict. This
also validates the v2.14 fresh `skill-picker` pair at generations 18 and 20,
so its semantic promotion stands without another capture. The accepted v2.18
pair-stop audit is
`e35798b681c1e13cf1626832307d010c906ce2fbc4d6fe234f07d76d0cd1940a`.
Recapturing until counters happen to agree remains forbidden counter-shopping;
no field other than `generation` and `semantic_generation` enters this rule.

## Dark Cloud login title capture defect

Settlement v2.20 adds one exact field correction for
`dark-cloud-login-settings`. The committed landed fixture and its byte-identical
shellfix baseline snapshot leave `layout.screen_title` empty. Two qualified
pristine-profile instances instead settled with the case-sensitive title
`Dark Cloud Browser` for all 40 samples; their complete 77-member cores and
relative sequences are equal under v2.19 despite measured generations 25 and
24. The two bound endpoints, `dark_cloud_to_login_settings.after` and
`dark_cloud_login_to_browser.before`, reproduce the same structural-core hash,
title, and player-visible frame. The machine-derived correction contract is
`native-menu-dark-cloud-login-title-v220.json`; it cites the accepted STOP
audit `4eb60e30e5f5e9d1db77fd9ae67fbba2d445077007d26b60cc08eefbb1ce4f5a`
and both raw trace receipts.

The correction applies only to that layout and native screen, only from the
empty landed value to exactly `Dark Cloud Browser`, and only while the landed
fixture, qualified candidate, pristine profile identity, both settled traces,
and both navigation bindings still match their pinned receipts. A case change,
another layout or field, a second differing layout field, another candidate
receipt, or a settled title other than the pinned value remains the unchanged
screen-title STOP. No title tolerance or candidate rewrite exists.

The same ruling introduced a no-write exhaustive diagnostic mode for landed
comparison. It executes the same gates and classifiers as production but
records every difference outside authorized classes rather than returning at
the first one. Production promotion still stops at the first unclassified
difference. The diagnostic is dry-run-only, records `candidate_applied: false`,
and cannot select captures or mutate fixtures. Recorder `capture_method` text
remains provenance annotation, not a player-visible semantic-core field, so it
cannot manufacture a landed generation or member difference. This makes later
rulings operate on one machine-derived corpus census without weakening any
production gate.

## Sealed census-era disposition

Settlement v2.21 binds the corrective classes to the sealed 326-row no-write
census
`b6d91abab8eaf67dfb9c4f92c688bf5ea027db8132e470c8fe4c763a6db08a72`.
It is an exact disposition, not a pattern matcher. Class A supersedes 261
landed-only era members across ten named layouts, with one record per layout;
every member is pinned by element id and semantic hash and must be absent from
every qualified standalone and endpoint occurrence. Class B adopts 38
settled-only members across seven layouts only when each member occurs in both
paired qualified traces. Removing, adding, partially applying, or moving any
record to another layout is a STOP. The committed contract also checks each
embedded Class-A member against the corresponding landed fixture, so the two
copies cannot silently disagree.

The occurrence audit
`e327294f0aff85710e238dce6e0967afe0814a26908de3a0cfe8643d35e7dca2`
found exactly two landed-only rows that fail the Class-A absence predicate:
`skill_picker.art.skills_84.1` and `.2`. Their measured rectangles reproduce
the two-layer `Skills.84` roster draw at `skill_picker.choice_slot.1`: atlas
`Skills`, anchor `(604, 386.5)`, relative positions 30 and 31, and offsets
`(0, 0)` and `(-4, -4)`. They therefore reconcile only through the already
proven v2.8 choice-slot rule. They are explicitly excluded from the
skill-picker Class-A record; a future row requires a new QUESTION and cannot
auto-extend this exception.

Class C applies the v2.18 generation doctrine to the 13 enumerated
landed-versus-settled counter rows only after all semantic members, relative
sequence, population witnesses, and bound endpoints resolve exactly. The
no-native-inbound-edge precondition is vacuous only for the machine-checked
`game-over` standalone. Class D consists of six exact, case-sensitive
one-field corrections: five measured titles and the `dark-cloud-menu`
`simple_menu` to `dark_cloud_menu` screen id. The latter requires aggregate
regeneration with zero stale references. Class E lets four old chrome/Item-1
guards be subsumed only by a complete Class-A record and treats the two equal
pause-menu witness routes as one proven equivalence class without selecting
between them. An uncovered pattern or divergent route still emits its original
named STOP.

Class F supplies the two missing paired population witnesses and nothing else.
Two pristine instances for `performance` and two for `profile-save-select`
each held a 40-sample, two-second-or-longer window and projected exactly onto
their qualified 23- and 33-member cores. Their measured generation counters
remain provenance; no capture was selected to match a landed counter. The
machine audit is
`66db25b623bdcf6ea82694e70a8ca662cc4a0567ceceb4b52f1eaaf0a46d6870`.
All six classes are evaluated by production's existing stop-at-first path;
enumerate-all remains diagnostic-only and no-write.

## Final four-row exact disposition

Settlement v2.22 binds the last four rows of the no-write census
`b6adf78aa2cadb671e8a6d337db5de0cc4cf1478928b4250e365f1f8d7d276b0`.
It adds two exact relative-sequence supersessions and one closed endpoint-
vacuity list; it adds no order or generation tolerance.

The sequence records apply only to `dark-cloud-login-settings` and
`game-settings-dark-cloud`. For each layout, the landed and settled relative-
sequence identities, every moved member with its duplicate-aware occurrence
and old/new index, the immutable landed snapshot, the qualified candidate,
both standalone traces, and the pristine profile identity are pinned. The
settled order reproduces independently in the standalone and the named
transition source (`dark_cloud_login_to_browser.before` and
`dark_cloud_settings_done.before`, respectively). The generator refuses a
record if either layout has any membership delta or if any qualified
occurrence disagrees. Promotion carries the captured settled order; neither
the generator nor promoter rewrites an element list.

The v2.18 bound-endpoint precondition is vacuous only for the closed named set
`game-over`, `map-picker`, and `skill-picker`. Promotion re-enumerates the
resolved native navigation graph and requires zero inbound edges for each
named layout every time. It also requires the exact paired standalone core and
window-constant measured generation already recorded for that layout. An
inbound edge disables vacuity, and an edge-free layout outside the named set
cannot claim it. Promoted fixtures retain their own measured counters; no
counter is edited or selected by value.

## Changelog

- **v2.22 — 2026-08-10:** disposed the sealed final four-row census with two
  exact, two-context relative-sequence supersessions and extended endpoint
  vacuity to the closed machine-checked set `game-over`, `map-picker`, and
  `skill-picker`. Cites census `b6adf78a`; no order tolerance, counter rewrite,
  or property-based vacuity rule was added.

- **v2.21 — 2026-08-10:** disposed the sealed 326-row census through exact
  Classes A-F, excluding the two measured `Skills.84` choice-slot rows from
  era supersession and adding paired bounded witnesses for `performance` and
  `profile-save-select`. Cites census `b6d91aba`, occurrence audit `e327294f`,
  and Class-F audit `66db25b6`; no count or pattern tolerance was added.

- **v2.20 — 2026-08-09:** two pristine instances and both bound endpoints
  reproduced the player-visible `Dark Cloud Browser` title omitted by the
  landed `dark-cloud-login-settings` fixture. Added the exact one-field
  correction cited by audit `4eb60e30`; also added a dry-run-only exhaustive
  difference census while preserving production stop-at-first behavior.
- **v2.19 — 2026-08-09:** the accepted paired-generation STOP proved that the
  session-cumulative generation counter drifts by -2 through +2 across fresh
  instances even on equal routes. Replaced only v2.18(c) with a per-pair exact
  semantic-core precondition, citing stop audit `e35798b6`; all 34 disagreeing
  points pass that proof and no other field is excluded.
- **v2.18 — 2026-08-09:** the accepted Control Scheme Picker generation-only
  STOP identified the absolute counter as non-rendered bookkeeping and made
  its within-window constancy, primary-value provenance, field-bounded
  cross-path exclusion, and no-counter-shopping rules explicit, citing audit
  `17dda126`.
- **v2.17 — 2026-08-09:** the accepted beta-notice path-state STOP added the
  exact first-boot dialog composite over Control Scheme Picker, promoted the
  qualified pause-entry beta screen, and retired the contaminated legacy core,
  citing audit `7253b6e0`.

- **v2.16 — 2026-08-09:** the accepted Settings cross-observation STOP showed
  deterministic retained-heading accretion. Added three exact
  `game-settings-gameplay` states and exhaustive endpoint bindings, citing
  audit `74f125e8` and question manifest `4d1708d1`; no other screen or member
  is authorized.
- **v2.15 — 2026-08-09:** the accepted Dark Cloud Settings surface STOP proved
  the credentials panel is outside the menu-member system. Added the typed,
  zero-member overlay record and retired the mischaracterized screen fixture.
- **v2.14 — 2026-08-09:** the accepted skill-picker provenance STOP replaced
  the legacy-window reuse permission with a two-instance pristine-baseline
  recapture. Animated-family and choice-slot predicates remain unchanged.

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
