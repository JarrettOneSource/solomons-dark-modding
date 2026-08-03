# Host-to-joiner mod transfer seam

Status: accepted implementation design for MODXFER (2026-08-03)

## Problem and invariant

The launcher can currently resolve a lobby's mod list through the website and
can reuse an exact local/cache copy. If the website is unavailable, the
launcher falls back to its local catalog. If the website knows the lobby but
cannot resolve a required package, the desktop launcher cancels the join.
There is no packet family for package bytes: `LuaModStream` is deliberately
limited to replicated Lua state and events, and the loader's content seams read
only locally staged content. A client that reaches the native handshake with a
different stage is rejected by the existing multiplayer fingerprint.

MODXFER fills only that acquisition gap. After the existing join prompt has
been accepted, the launcher may obtain an exact package from the host, install
it through the same validated package/cache path as a website download, build
the joiner's stage, and continue through the unchanged native fingerprint
handshake. Declining the existing prompt still cancels without downloading or
staging anything.

The authoritative identity remains the existing multiplayer compatibility
fingerprint. Direct transfer does not weaken exact parity, add a Lua fallback,
or allow a host to stream arbitrary files. The host serves only immutable
archives materialized from the enabled mod roots used to build its current
stage.

## Placement

The protocol belongs beside session hello/keepalive at the multiplayer session
layer, before gameplay authentication. It does not belong in `LuaModStream`, a
mod content seam, or a local-UDP-only helper.

Both backends use the same packet structs, validation, request state, package
index, bounded work queue, and response queue:

- local UDP accepts transfer packets only from the configured remote endpoint;
- Steam accepts them only from a current member of the host's current lobby;
- a backend adapter enqueues a validated packet into the shared transfer
  service and drains prepared responses through its existing send primitive.

Steam's session service thread and local UDP's app-thread dispatch therefore do
not fork the transfer state machine. Steam receives and sends the new session
packets on the existing reliable session/bulk channel. Local UDP uses the same
logical packets without depending on Steam. All packet sizes stay below the
1,200-byte local datagram limit, so the standalone launcher client does not
need the gameplay fragment envelope.

The launcher mirrors that shape behind `IHostModTransferTransport`: one transfer
client/state machine consumes either a local-UDP adapter or a Steam Networking
Messages adapter. The Steam adapter temporarily joins the selected lobby,
resolves the lobby owner, exchanges transfer packets, then leaves; the existing
desktop lobby-holder can subsequently retain membership as it does today. The
local adapter binds the configured joiner port, exchanges transfer packets with
the configured host endpoint, closes, and releases that port before the game is
launched.

No workstation-specific Steam behavior is assumed by the core service. Local
UDP is the required live acceptance leg for this wave. Steam must compile and
pass packet/routing/launcher contracts; its live workstation20 leg is a
follow-up because that machine is unavailable.

## Staged transfer packages

Host staging, and only host staging, creates:

```text
<stage>/.sdmod/mod-transfer/
  index.bin
  index.json
  packages/<package-sha256>.zip
```

The launcher enumerates the same enabled `DiscoveredMod` objects passed to the
runtime and multiplayer compatibility materializers. For each mod it creates a
deterministic ZIP from that mod root: portable relative paths in ordinal order,
fixed timestamps, no links/reparse points, no DLLs, and the same archive tree
and expanded-content rules used for website packages. Archive entries contain
the mod-root contents directly, including `manifest.json`.

`index.bin` is a fixed-width, bounds-checked loader input. Its header contains
schema version, multiplayer protocol version, the current stage fingerprint,
entry count, and checked total package bytes. Each entry contains mod id,
version, existing content SHA-256, package SHA-256, and package byte length.
There is no caller-controlled filesystem path: the loader derives the only
legal path as `packages/<package-sha256>.zip` under the stage directory.
`index.json` contains the same non-secret identities for stage reports and
evidence, but the native service never parses JSON.

The package index is materialized after the existing compatibility manifest so
it records that exact fingerprint. A host stage fails closed if an enabled mod
cannot be represented by the package contract. A non-host stage removes stale
transfer material. Stage mirroring, package construction, hashing, and index
writes happen in the launcher process, never in the game process.

At loader startup a dedicated transfer worker reads and validates `index.bin`,
checks every derived package path, size, and package digest, and publishes an
immutable in-memory index. Until that work finishes, metadata requests receive
`busy`; invalid material disables host transfer and is logged, but never
changes the host's gameplay stage or fingerprint.

## Protocol 91

Adding this packet family increments the multiplayer protocol from 90 to 91 in
both native and launcher constants. All integers use the existing packed
little-endian protocol convention. Digests are 32 raw bytes. Text fields are
fixed-size UTF-8, NUL-padded, and must be NUL-terminated without invalid UTF-8.
Every request carries a cryptographically random 128-bit client transfer id;
responses echo it. Every packet carries the host stage fingerprint and, on
Steam, the selected lobby id (zero is the required local-UDP value).

New packet kinds are:

| Packet | Direction | Purpose |
|---|---|---|
| `ModTransferManifestRequest` | joiner -> host | Discover the host fingerprint, index digest, package count, and total bytes. The optional expected fingerprint must either be all zeroes or match the host. |
| `ModTransferManifestResponse` | host -> joiner | Return `ready`, `busy`, `not-host`, `fingerprint-mismatch`, `unavailable`, or `bounds-rejected`, plus immutable index summary. |
| `ModTransferDescriptorRequest` | joiner -> host | Request one descriptor by zero-based index and index digest. |
| `ModTransferDescriptorResponse` | host -> joiner | Return one id/version/content-digest/package-digest/size tuple. |
| `ModTransferChunkRequest` | joiner -> host | Request one aligned package range by descriptor index, package digest, byte offset, and length. |
| `ModTransferChunkResponse` | host -> joiner | Return that exact range and its SHA-256; status can also report stale identity or bounds failure. |
| `ModTransferComplete` | joiner -> host | Confirm that the full archive and extracted content matched, allowing immediate host request-state cleanup. |
| `ModTransferAbort` | either direction | End one transfer id with a bounded reason code; no free-form remote text is accepted. |

Manifest and descriptor requests are idempotent. A descriptor is accepted only
when its index digest still matches the response summary. A chunk request is
accepted only when all of these are true:

- the transfer id has a successful manifest request for the same endpoint;
- descriptor index, package digest, and total size match the immutable index;
- offset is aligned to the chunk size except for the final range;
- requested length is nonzero, at most 1,024 bytes, and stays inside the file;
- the package and the checked session total stay within the limits below.

The response contains at most 1,024 payload bytes and remains below 1,200 bytes
including all identity fields. A chunk is never pushed unsolicited.

## Backpressure, threading, and budgets

The request window is the acknowledgement and backpressure mechanism. The
joiner keeps at most eight chunk requests outstanding. Missing responses are
re-requested by exact offset after one second; duplicate responses are
idempotent. The host admits at most eight outstanding reads per transfer id and
at most three transfer ids, matching the maximum number of joiners in a
four-player lobby.

The native service has a dedicated worker thread. Session dispatch performs
only fixed-size validation and a bounded queue copy. File open, seek, read, and
hash work occurs only on the worker. Prepared responses return through a
bounded queue. The local-UDP app tick drains at most eight chunk responses and
8 KiB of payload; Steam applies the same budget per 16 ms service tick. Metadata
responses have a separate maximum of eight per tick. Full queues return or
implicitly preserve `busy`; they never block a network or game thread.

This is a hard ownership rule, not an optimization: no synchronous package,
index, receipt, log-evidence, or cache I/O may be added to
`TickGameplayTransportOnAppThread`, `TickLocalTransport`, or a packet dispatch
called by them. It preserves the fix established by 8c1af63, which moved
session-status I/O off the game thread.

## Explicit bounds

- maximum indexed packages: 128;
- maximum single archive: 100 MiB, matching the website installer;
- maximum expanded package: 256 MiB, matching the website installer;
- maximum aggregate advertised archives per host stage: 512 MiB;
- maximum archive entries: 2,048, matching the website installer;
- chunk payload: 1,024 bytes;
- joiner request window: 8 chunks / 8 KiB;
- host service: 8 chunk responses / 8 KiB per backend tick;
- host metadata responses: 8 per backend tick;
- outstanding worker reads: 8 per transfer id, 24 globally;
- prepared response memory: 64 KiB per transfer id, 192 KiB globally;
- retry interval: 1 second; maximum 10 attempts without progress;
- idle host transfer state expiry: 30 seconds;
- descriptor text: 128 bytes for id and 64 bytes for version.

Every byte/count addition is checked for overflow. A bound violation produces a
typed abort, no archive write, and no final cache promotion.

## Resume and abort

The launcher writes incoming bytes asynchronously to an operation-owned file
outside the final mod cache. Beside it, an atomic receipt records host
fingerprint, index digest, package digest, total size, and contiguous verified
length. A retry may resume only if every identity field still matches; it asks
for the first missing aligned offset. The host is random-access and stateless
with respect to file position, so a new validated transfer id can resume the
same package without trusting old host process state.

A transport timeout or website-to-host fallback interruption retains the
matching partial file for retry. Explicit user cancellation, protocol or
identity change, malformed data, chunk hash failure, final package hash
failure, extracted content mismatch, or remote abort deletes the receipt and
partial archive. `ModTransferComplete` and `ModTransferAbort` release host
request state immediately; idle expiry is the crash/disconnect cleanup.

There is no partially installed target. Cache promotion is a directory rename
only after all integrity and package validation succeeds. A resumed archive is
hashed in full before installation, including the retained prefix.

## Consent and resolution order

The preview path may request host metadata and descriptors before consent; it
does not request a chunk or create a partial archive. Preview resolves each
required host descriptor in this order:

1. exact enabled local/manual copy;
2. exact validated cache copy;
3. website package metadata;
4. matching descriptor in the host transfer index.

The existing single join-consent prompt remains the only consent surface. Its
wording identifies how many packages are expected from the website and how many
are expected directly from the host. Accepting that prompt passes an explicit
host-transfer authorization into the existing stage/launch command. Without
that authorization, synchronization may query metadata but cannot send a chunk
request. Decline keeps the current `Join canceled - nothing was downloaded.`
path and starts no transfer.

After consent, synchronization first reuses exact local/cache content and tries
the website for packages it resolved. An unpublished package, a website miss,
or a website transport failure falls back to the host descriptor. A website
descriptor and host descriptor for the same requirement must agree on id,
version, and content digest; disagreement aborts rather than choosing one.
If neither source can supply every required package, the existing clean
pre-launch cancel remains.

## Integrity and staging

The host declaration binds two layers:

1. SHA-256 of the exact archive bytes (`packageSha256`);
2. the existing directory content SHA-256 included in the host compatibility
   fingerprint (`contentSha256`).

The joiner hashes each received chunk for corruption diagnostics, hashes the
complete archive and compares it with the declared package digest, then invokes
the same archive validation/extraction/content-validation/cache-promotion code
used by `WebsiteModPackageInstaller`. The extracted manifest must match the
declared id and version, and `ModContentHasher.HashDirectory` must match the
declared content digest. Only then is the cached `DiscoveredMod` admitted to
the session-scoped catalog and staged.

Any mismatch sends a typed abort, deletes temporary data, writes a clear
launcher/loader log event, and prevents game launch. The final stage still runs
the existing `RequireHostCompatibleStage` check, and native session hello still
compares the complete 32-byte stage fingerprint. Direct transfer never treats
a package digest alone as permission to play.

## Multiplayer-native rules

The transfer seam changes acquisition only. Once installed, a mod follows
`docs/lua-seam-roadmap.md` unchanged:

- exact enabled-mod parity is mandatory;
- simulation stays host-authoritative where the Lua seam requires it;
- replicated semantic state/events use their existing bounded native packet
  families, not the package-transfer channel;
- presentation-local effects remain local on both peers;
- no raw pointers, local paths, arbitrary files, or Lua source bytes are
  requested after staging.

The transfer service shuts down before gameplay teardown completes, but cached
packages remain ordinary validated launcher cache entries. It is unavailable
to mods and exposes no Lua API.

## Verification contract

Static and executable contracts must cover packet sizes/kinds/version alignment,
endpoint/lobby authorization, index and path bounds, worker ownership, queue and
per-tick budgets, retries/resume/abort, final digest rejection and partial
cleanup, common website/host installer promotion, preview source selection, and
the unchanged decline string/path. Steam contracts must prove transfer packets
are handled as session/bulk messages before gameplay authentication and use the
same shared service as local UDP.

The mandatory live leg uses isolated local-UDP instances and an unpublished
fixture. Evidence must show the existing prompt naming host sourcing, archive
transfer and both digest matches, identical final fingerprints, both peers in
the arena with a visible fixture effect in actual-window captures, clean decline
without transfer, and a test-harness-corrupted chunk or archive producing a
digest abort with no promoted cache entry. No fixture is published or included
in a release package.
