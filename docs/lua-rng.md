# Lua run RNG

`sd.rng` controls the native random seed used when the game constructs an arena run.
It is deliberately narrower than a general-purpose random-number API: Lua chooses the
run-generation seed, then the stock game consumes its native RNG normally.

Capability: `rng.run.seed`.

## API

### `sd.rng.get_seed() -> integer|nil`

Returns the run seed published for the local participant, or `nil` before one has been
chosen. During multiplayer, every participant converges on the host-authored value through
the existing `run_nonce` state.

### `sd.rng.set_seed(seed) -> integer`

Stores an exact seed for the next arena transition and returns it. `seed` must be an integer
from `1` through `0x3fffffff`.

The call is accepted only:

- by the simulation authority (offline or the multiplayer host); and
- before entering a run.

The last accepted call before the transition wins. The transition applies the seed through
the stock RNG initializer immediately before arena generation. Calling this from a client,
from inside a run, or with an out-of-range value raises a Lua error instead of silently
normalizing or forwarding the request.

```lua
assert(sd.runtime.has_capability("rng.run.seed"))

local daily_seed = 0x1234567
assert(sd.rng.set_seed(daily_seed) == daily_seed)
assert(sd.rng.get_seed() == daily_seed)
sd.hub.start_testrun()
```

## Multiplayer

The host publishes the seed as the run nonce. A client applies that authenticated nonce to
the same native RNG initializer before its matching arena switch, so Lua mods do not send or
receive seed messages themselves. A client cannot replace the host's choice.

This seam makes arena generation start from the same native seed. It does not by itself
promise full replay determinism after the run begins; native RNG call order and
nondeterministic inputs still need a separate determinism audit.

## Acceptance

With a loader-started game still in the hub, run:

```powershell
py -3 tools/verify_lua_rng.py
```

The verifier checks the capability, exact round trip, integer/range rejection, and the
documented return type. It intentionally leaves its accepted seed pending for the next run.

For the full two-peer authority and native-application acceptance, use a
disposable local pair:

```powershell
py tools/verify_lua_rng_multiplayer.py --launch-pair --confirm-mutation
```

The pair verifier stages only `sample.lua.rng_lab`, suppresses window tiling,
and leaves unrelated Solomon Dark processes untouched. It begins with no seed
on either peer and proves that the client cannot select one. While both peers
remain in the hub, the host owns the selected seed and the client sees it only
on the authenticated host participant row; the client's local seed remains
unset. The host's `Run` intent then authorizes the client to install the exact
nonce, and successful `testrun` entry is contingent on each process applying
that pending seed through the stock native initializer. After entry, the
verifier requires the same owner `run_nonce` and in-run state on both peers,
plus the correct authority-versus-already-in-run rejection on attempted
replacement. It stops only the two process IDs returned by its own launch.
