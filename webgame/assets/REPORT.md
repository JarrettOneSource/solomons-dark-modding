# P0 native asset pipeline report

- Campaign: `assetpack-20260805`
- Base: `acc4ef5d7a2a03ae4f4b7b3350cb06f13960836d`
- Workspace: `C:\sd-assetpack-20260805`
- Retail input: `C:\SolomonDarkAbandonware` (read-only)

## Result

The new top-level `webgame/` npm workspace mechanically lifts the shipped visual and data
content. The production build copied all 41 PNG inputs byte-for-byte, decoded all 10,511 bundle
records under their native identifiers, emitted all four installed Boneyards, all 42 waves, and
all 31 byscript recipes, and resolved every identifier referenced by the landed scene-composition
and menu goldens. No atlas, full manifest, or full data pack is committed; those 56,134,282 bytes
remain a build artifact.

The workspace owns its fixture under `webgame/assets/fixtures/` because it also owns the manifest
schema, fixture generator, and TypeScript battery. The native source recordings remain in
`tests/fixtures/webgame/`. Repo-side static contracts independently compare the fixture to those
recordings and to the native inventory.

## Measured baseline before edits

The clone was measured rather than inheriting the dispatch's hand-carried source/launcher values:

| Battery | Baseline result |
| --- | ---: |
| CI-eligible Python modules | 77/77 modules, 610 tests; 8 exclusions |
| CI-eligible static RE | 371/371 |
| Full local static RE | 374/384; the 10 failures required absent fresh-clone local artifacts |
| Source organization | 706 source/header fragments |
| Launcher contracts | 55/55 |

## Production build

Both runs used the documented `npm --prefix webgame run assets:build -- ...` command with separate,
initially absent output directories. The generator compared relative filenames, byte counts, and
per-file SHA-256 values, so absolute staging paths are not part of the result.

| Measurement | Result |
| --- | --- |
| First output | `/home/user/assetpack-build-final-a` |
| Second output | `/home/user/assetpack-build-final-b` |
| Files in each output | 46 |
| Relative-path tree SHA-256, both runs | `3abd761d4047540d32bcf9b6f7a4c87404e0ac84417db2c708dbf346aa6409ea` |
| Manifest SHA-256, both runs | `11e3d2041abb5117228064e73fcd02b9beb3b40dfeed735eafb7133ffd0c5fa3` |
| Manifest records | 10,511 sprites; 718 aliases; 10 font groups |
| Golden resolution | 485/485 unique references; 0 unresolved |
| Bundle fixture coverage | 28/28 families |

## Static-hosting asset weight

These are exact emitted file sizes, not estimates:

| Category | Bytes | MiB |
| --- | ---: | ---: |
| Atlases | 42,744,038 | 40.764 |
| Boneyards | 5,783,538 | 5.516 |
| Waves | 428,544 | 0.409 |
| Recipes | 52,423 | 0.050 |
| **Asset subtotal** | **49,008,543** | **46.738** |
| Manifest and build report metadata | 7,125,739 | 6.795 |
| **Complete build artifact** | **56,134,282** | **53.534** |

The static-hosting sizing question in roadmap section 11 therefore starts at 49,008,543 bytes of
served content, or 56,134,282 bytes if the full manifest/report overhead is counted. These values
are pre-transport-compression and do not assume a CDN or HTTP encoding ratio.

## Native-format boundary

Bundle decode delegates to `tools/extract_bundles.py`; Boneyard/script/recipe decode delegates to
the existing `tools/inspect_boneyard.py` and `tools/decode_boneyard_scripts.py` logic. Unknown
world objects, record shapes, trailing bytes, and wave modifiers hard-fail with record/offset
context. No decoder silently drops a record or chooses among duplicate candidates.

The retail wave contains `FLAG_IGNITE` at 14 byte offsets and `FLAG_IMMORTALIZE` at two. A
read-only Ghidra check found neither token in the native flag catalog and decompiled the parser at
`0x0062E070`: an unknown parameter logs `Unknown Param: %s` and appends no native modifier. The
pipeline preserves these two reviewed tokens as ordered records with `nativeCode: null` and
`nativeBehavior: "logged-and-ignored"`. Their exact lines/offsets are under **Not Yet Reversed**
in `README.md`; any new unknown token remains fatal.

No live game instance was launched for this campaign.

## Mutation audit

Before and after every mutation, `tests/re/__pycache__` was cleared and all four new contracts
were run as a green baseline. Each mutated run invoked the target contract directly and required
the listed message, so a neighboring gate could not earn the result.

| Claim | Deliberate mutation | Required observed failure | Before / after |
| --- | --- | --- | --- |
| Committed provenance is real | Changed the recorded schema-file SHA-256 | `asset manifest committed source webgame/assets/asset-manifest.schema.json does not match its file` | green / green |
| Two builds are identical | Changed only `secondOutputTreeSha256` | `double-build output tree hashes diverge, so asset emission is not deterministic` | green / green |
| Every golden ID resolves | Removed the `DeadHawg.12` resolution | `asset manifest leaves golden reference unresolved: DeadHawg.12` | green / green |
| CI runs the real ratchet | Added a trailing argument to the webgame typecheck command | `CI no longer runs the webgame typecheck ratchet as an isolated step` | green / green |
| CI can run the real decoder | Moved the existing Pillow install below the webgame test | `CI runs the real webgame decoder test before installing its Pillow dependency` | green / green |

The restored baseline reports:

- schema/provenance: eight committed hashes match their files;
- determinism/weight: both 46-file trees and all pack descriptors match;
- coverage/resolution: all 28 bundle families and all 485 golden lookups resolve; and
- workspace/CI: strict TypeScript plus five locked webgame CI steps at floors 21/18/6/14.

The first exact-SHA hosted run caught this dependency-order defect: the real bridge imported the
existing bundle extractor before Pillow was installed. The workflow now installs its already
pinned Pillow 12.2.0 dependency before the webgame battery, and the ordering is a mutated static
claim rather than an implicit step-order assumption.

## Landed battery

The final post-rebase local and exact-SHA CI results are recorded in the external evidence copy of
this report after landing.
