# Browser rebuild known issues

## G11 shellfix baseline interregnum

The settled menufix recordings intentionally replace all 28 webshell-era menu
fixtures before the shell itself changes. Until shellfix task #101 rebuilds the
shell, T2 layout replay compares it at epsilon zero with byte-exact pre-menufix
snapshots under `webgame-contracts/baseline-snapshots/`. The 18 reviewed-pass
and 10 reviewed-divergent visual records are bound to hashes of those same
snapshot bytes; they make no claim about the replacement recordings.

`webgame-contracts/menu-baseline.json` separately pins the archived shell
aggregate, all 28 layout snapshots, all 28 native reference captures, and 29
settled states as `pending_shellfix`. The pending set is exactly the historical
28 layouts minus the retired Dark Cloud Settings screen plus its non-semantic
overlay and the first-boot beta-notice composite. A missing entry, changed
snapshot, changed settled state, or census other than 28 snapshots and 29
pending states fails the gate. There is no stale-layout waiver or geometry
tolerance. Shellfix task #101 must remove this interregnum by rebuilding and
reviewing the shell against the settled fixtures.
