# Native `Select a Spell` boundary

This note records the verified native surface headed `Select a Spell` and why
registered Lua spells do not inject runtime selections into it. The symbols are
descriptive loader names applied to the stock 0.72.5 executable; addresses and
field behavior below were recovered from the shared Ghidra project.

## Surface identity

The surface class is cataloged as `SellSpell`:

- constructor: `0x004F82D0`
- destructor: `0x004F83A0`
- object size at its allocation site: `0x28C`
- vtable: `0x00790B04`
- input/action virtual: `0x004F90C0` at vtable slot `+0x10`
- tick virtual: `0x004FA3B0` at slot `+0x08`
- renderer: `0x004FA460` at slot `+0x0C`

The renderer references the `Select a Spell` string at `0x00791240` from
`0x004FA7F7`. The binary-layout surface declaration uses the same renderer and
vtable.

The constructor creates a `SellSpellBox` subobject at whole-object offset
`+0x140`. That subobject has vtable `0x00790934`; its virtual at `+0x04` is the
population routine `0x004F8480`.

## Population contract

`0x004F8480` appends one row for each of eight stock spells whose global unlock
byte is still zero. It maintains parallel arrays in the `SellSpellBox`:

| Subobject offset | Whole-object offset | Value |
|---|---:|---|
| `+0xDC` | `+0x21C` | names |
| `+0xEC` | `+0x22C` | descriptions |
| `+0xFC` | `+0x23C` | native spell IDs (`data +0x240`, count `+0x244`) |
| `+0x10C` | `+0x24C` | row integer metadata |
| `+0x120` | `+0x260` | selected row index |

The fixed rows are:

| Native ID | Name | Row integer |
|---:|---|---:|
| `0x48` | ACID RAIN | 3000 |
| `0x49` | FIRE WALL | 3500 |
| `0x4A` | ETHER DRAIN | 4200 |
| `0x4B` | IRON GOLEM | 5000 |
| `0x4F` | REGENERATE | 5100 |
| `0x4E` | MINDSTAR | 5300 |
| `0x4D` | TURN UNDEAD | 6100 |
| `0x4C` | CALL COMET | 10000 |

After filling the arrays, the same function allocates a `0xB4` child for every
row, constructs it with `0x00430430`, adds it to the subobject's child list at
`+0xC4`, attaches it through the parent virtual at `+0xA8`, and lays it out.
Appending only to the arrays after the original population call therefore
cannot add a visible row.

## Selection behavior

`0x004F90C0` handles the box callback while the close flag at whole-object
`+0x13C` is clear. It reads the selected index at `+0x260`, bounds it against
the ID-array count at `+0x244`, and reads the native ID from the data pointer at
`+0x240`.

The handler recognizes only IDs `0x48` through `0x4F`. Each recognized ID sets
its corresponding stock unlock byte in `0x00B3BDD8..0x00B3BDDF` to one. It then
closes the dialog through `0x0042AE00`, sets its close timing fields, and plays
the selection sound. An unrecognized ID still follows the close/sound tail but
does not mutate a stock unlock byte.

These bytes are acquisition/progression flags: the population function hides
rows whose byte is already one, and other stock progression routines validate
the same fixed ID range. No primary-selection field, belt-slot index, or generic
content identity participates in this surface.

## Loader decision

The stock surface is an acquisition dialog, not a runtime loadout picker.
Injecting registered definitions would require reproducing native child
construction, detouring the fixed-ID handler, inventing acquisition policy, and
still would not assign a primary or belt input. It would also make mod
availability depend on persistent stock unlock state.

Registered spells instead use an address-free loader selection model:

- one local primary selection;
- one local selection per live belt binding;
- no stock unlock, progression-row, or belt-content writes;
- exact content IDs route casts to the participant's simulation owner;
- the authored `sd.ui` picker will call the public selection API.

This preserves the verified native meaning of `SellSpell` and gives the future
visual picker a stable model that works for every registered content ID.
