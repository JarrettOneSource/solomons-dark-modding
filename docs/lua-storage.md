# Lua profile storage

`sd.storage` is a local, per-mod, per-launcher-profile key/value store. It is
for settings, unlocks, and other data that belongs to one player profile. Use
`sd.state` for shared run state: storage is never replicated and never grants
simulation authority.

Each enabled mod is isolated under its launcher-provided data root:

```text
.sdmod/runtime/sandbox/mods/<storage-key>/data/profile-storage.bin
```

The storage key is the launcher's SHA-256 identity for the manifest mod ID, so
one mod cannot choose or traverse into another mod's directory. Lua does not
receive a raw filesystem handle.

## API

```lua
local value = sd.storage.get("key", optional_default)
local stored = sd.storage.set("key", value)
local deleted = sd.storage.delete("key")
local cleared = sd.storage.clear()
local values = sd.storage.snapshot()
```

Keys are nonempty strings up to 128 bytes. Values use the same bounded codec as
`sd.state`: booleans, finite numbers, integers, strings, dense arrays, and
string-keyed objects. Tables may be at most 16 levels deep and 2,048 nodes;
strings are capped at 16 KiB and the complete file at 64 KiB. Values cannot
contain `nil`; call `delete` instead. Functions, userdata, mixed tables, sparse
arrays, cycles, NaN, and infinity are rejected before any write.

`set`, `delete`, and `clear` are synchronous. A candidate snapshot is encoded
and written to a sibling temporary file, then published with a replace-and-flush
operation. The in-memory snapshot changes only after publication succeeds.
Malformed or foreign storage files fail visibly and are not overwritten.

## Multiplayer

`sd.storage` advertises `storage.profile.local`. Every peer reads and writes its
own launcher profile. A mod that needs one authority-owned value shared with
peers must put it in `sd.state`; a one-shot shared signal belongs in
`sd.events.broadcast`.

The opt-in `sample.lua.storage_lab` mod demonstrates a persistent launch count.
The live verifier has separate `write`, `read`, and `clear` phases so its read
phase can run after a disposable process restart:

```powershell
py -3 tools/verify_lua_storage.py --phase write --token acceptance-1
# restart the disposable game process
py -3 tools/verify_lua_storage.py --phase read --token acceptance-1
py -3 tools/verify_lua_storage.py --phase clear
```

For the complete multiplayer-local lifecycle, use a disposable pair:

```powershell
py tools/verify_lua_storage_multiplayer.py `
  --launch-pair `
  --confirm-profile-mutation
```

The pair verifier preserves any existing storage files for both named launcher
instances before staging. It starts from empty acceptance profiles, writes
different nested values on host and client, proves that neither mutation,
delete, nor clear crosses to the other peer, and restarts both processes to
prove independent durable reads. It also exercises invalid keys, cyclic,
sparse, mixed, nil, NaN, and infinite values without changing the accepted
snapshot. Generated files are removed and any original bytes are atomically
restored after both exact process IDs stop. Window tiling and global process
cleanup are disabled.
