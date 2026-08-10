# Native asset build

This directory owns the build-time lift of the shipped Solomon's Boneyard content. It does not
redraw, rename, or substitute assets. The builder copies every retail PNG byte-for-byte, decodes
every `.bundle` record through the existing `tools/extract_bundles.py` implementation, and decodes
the retail Boneyards and byscript stores through the existing repository decoders. `data/wave.txt`
is parsed without discarding repeated flags or signed values.

The retail install is an input and is always opened read-only. The output must be a new directory
outside that install and outside the repository. The builder refuses an existing output path and
builds in a sibling staging directory before one atomic rename.

## Build

From the repository root, with Node 22 and Python 3 available:

```text
npm --prefix webgame ci --ignore-scripts
npm --prefix webgame run assets:build -- \
  --retail-root <retail-install> \
  --output <new-output-directory>
```

The output contains:

- `atlases/`: the 28 shipped bundle PNGs, 12 shipped loose PNGs, and the committed loading image;
- `asset-manifest.json`: the renderer's only asset lookup;
- `packs/boneyards.json`: exact structural and script/recipe decodes of all four installed
  Boneyards, including original source bytes and undecoded compatibility fields;
- `packs/waves.json`: all 42 waves, ordered groups, repeated modifiers, raw source spans, and
  record provenance;
- `packs/recipes.json`: all 31 decoded Monster, Item, NPC, ItemSet, and UIDGroup recipes; and
- `build-report.json`: category weights and the complete relative-path tree hash.

Every JSON file is canonical UTF-8 with sorted object keys, two-space indentation, one terminal
newline, and no timestamps. PNG compression is not rerun: the shipped bytes are copied exactly.
Directory and record ordering is explicit. A build fails on an unknown record, duplicate lookup
candidate, inventory/hash mismatch, stale generated atlas span table, or decoder failure.

## Renderer lookup contract

Bundle sprites use the native `<Atlas>.<zero-based-record-index>` identifiers consumed by
`generated_atlas_spans.inl` and the landed scene-composition goldens. For example,
`DeadHawg.12` resolves directly; font address aliases resolve to their native `Fonts.<record>`
entry; loose/menu art keeps its recorded native identifier. Explicit non-atlas draws such as
`native.framebuffer-clear`, `native.textured-quad@0x41474C`, and `Segoe UI` are typed special
draws in the same lookup, so callers never guess among namespaces.

Each sprite entry gives an atlas rectangle, logical size, native points, rotation, pivot, and
record provenance. The pivot is the negative native trim origin: drawing the atlas rectangle at
`logicalTopLeft + pivot` reproduces its location in the native logical canvas. Provenance names
the source bundle/file, record index, SHA-256 of the exact source record bytes, byte offset, and
byte length. Pack entries carry the same source filename, record index, and source-byte SHA-256.

## Determinism and pinned output

Two production builds from the pinned retail inventory produced the same 46-file tree:

| Artifact | SHA-256 |
| --- | --- |
| Relative-path output tree | `3abd761d4047540d32bcf9b6f7a4c87404e0ac84417db2c708dbf346aa6409ea` |
| `asset-manifest.json` | `11e3d2041abb5117228064e73fcd02b9beb3b40dfeed735eafb7133ffd0c5fa3` |
| `build-report.json` | `9888c3d1baf5d429631a44ee7e7c0b7270ec0ea2eba35ed55171a03a4f9e2b30` |
| `packs/boneyards.json` | `ef3480941917d1337d943d5e016f448f1989575f6265327b524041c91722edda` |
| `packs/waves.json` | `fba1a0c2f68894d38914b1daf17fd5593b018fefe19309443b58c9aebfd118bb` |
| `packs/recipes.json` | `87757abfa262a20baa2f29ca17675e2cfc593f249efe6858d58d4c60f7a01b58` |

The committed
`webgame/assets/fixtures/asset-manifest-goldens.json` SHA-256 is
`078b770f7eea244a871ece1af8a178ccd1d8400456bccf9fd02ce774e0fd6c8b`.
It pins counts, every atlas dimension/hash, every output-file hash, one record from each bundle
family, and every record needed by the landed scene and menu goldens. The fixture lives here
rather than under `tests/fixtures/` because this workspace owns its schema, generator, and unit
battery; the native recordings it consumes remain under `tests/fixtures/webgame/`. Full atlases
and packs are build artifacts and are intentionally not committed.

Regenerate the subset only after two clean builds agree:

```text
npm --prefix webgame run assets:goldens -- \
  --first-build <first-output-directory> \
  --second-build <second-output-directory>
```

## Not Yet Reversed

The intended game-design meanings of retail wave tokens `FLAG_IGNITE` and
`FLAG_IMMORTALIZE` are not described by the reversed format documentation. A read-only static
check of the retail executable found neither token in the native modifier catalog. The native
parser at `0x0062E070` logs `Unknown Param: %s` and appends no modifier code for either token.
The web pack therefore preserves each occurrence in order with `nativeCode: null` and
`nativeBehavior: "logged-and-ignored"`; it does not invent behavior. Any other unknown token
hard-fails with its line and token instead of taking this reviewed exception.

The affected `data/wave.txt` records (zero-based byte offsets, token start) are:

| Token | Lines and byte offsets |
| --- | --- |
| `FLAG_IGNITE` | 965@21690, 991@22116, 1026@23475, 1035@23941, 1044@24411, 1063@25076, 1072@25527, 1081@25982, 1084@26094, 1106@26842, 1115@27304, 1124@27756, 1132@28077, 1146@28555 |
| `FLAG_IMMORTALIZE` | 1084@26116, 1132@28099 |
