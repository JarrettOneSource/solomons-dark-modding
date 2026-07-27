# Lua Bots website publication discovery (2026-07-27)

This note records the package, publication, update, and compatibility contracts
that must be satisfied before `mods/bot-brain` can be published as **Lua Bots**.
It was completed before changing the mod or either distribution implementation.

## Source of truth

The live production Website source is the clean repository at:

```text
/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Website
```

It is `JarrettOneSource/solomon-dark-website` `main` at
`dd248b2b71cb1ffb3c0f5b61c4db828bd21bb12a`. On 2026-07-27, read-only HTTPS
requests to `https://solomondarker.com` returned the following exact checked-in
files:

| Public file | Live and local SHA-256 |
| --- | --- |
| `/mod-package-format.md` | `ab20bee495b8f95865f530c22202bf54975c3482c7380b98182a1b8667e6266f` |
| `/mod-manifest.schema.json` | `ee79f7114bed5b702636a991459d3fac0a315e33fb6a6dcb4a9d6c0e73cf2e9b` |

The live service also exposes the `POST /api/mods/resolve` and
`POST /api/mods/updates` behavior implemented in that repository. The Mod
Loader's compiled launcher contracts named `website package install and cache`,
`automatic mod updates`, `website lobby preflight`, and
`lobby join preview classification` exercise the same response shapes and are
the client-side ground truth.

The similarly named directory at:

```text
/mnt/c/Users/User/Documents/GitHub/SB Modding/solomon-dark-website
```

is not a second product or the production checkout. It is an older working
clone of the same GitHub repository, checked out on
`agent/lobby-discovery-backend` at `0d32926e` with uncommitted lobby/frontend
work and a stale `origin/main` reference. It must not be used for this
publication job.

## Canonical package contract

A website mod is one ZIP with no wrapper directory:

```text
manifest.json
scripts/
  main.lua
  ...
```

`manifest.json` and every referenced file are at the archive root. Website
packages may contain Boneyard/data overlays under `files/`, art overlays, and
sandboxed Lua under `scripts/`; native DLL entry points are rejected. Archive
paths must be portable, unique case-insensitively, link-free, and bounded.

The website computes both integrity values:

- `packageSha256` is SHA-256 over the exact ZIP bytes.
- `contentSha256` is SHA-256 over the concatenation of
  `<ordinal-path>\0<lowercase-file-sha256>\n` for every file, sorted by path
  using ordinal comparison.

The launcher downloads to a transaction directory, verifies both hashes,
validates the extracted manifest and allowed file classes, then either reuses
the exact cached copy for a lobby or atomically replaces an installed website
mod during an update. The exact manifest `id`, semantic `version`, and content
hash are the multiplayer identity. Lua Bots must therefore keep
`id: "bot.brain"` permanently and publish as `1.0.0`.

## Listing, authentication, screenshots, and updates

The public submission UI is `/mods/upload`. Its API is authenticated
`POST /api/mods` with `multipart/form-data`:

| Field | Requirement |
| --- | --- |
| `name` | 3-60 characters |
| `summary` | at most 160 characters |
| `description` | at most 10,000 characters |
| `tags` | optional comma-separated list, at most five |
| `version` | must exactly equal `manifest.version` |
| `file` | non-empty ZIP, at most 100 MiB |
| `screenshots` | optional repeated PNG/JPG files, zero to ten, at most 2 MiB each |

The endpoint requires a normal website bearer token whose user becomes the mod
author. The local Development environment seeds ordinary test accounts, so the
complete flow can be exercised locally without production credentials.
Production owner credentials are not present in the local development setup and
must not be bypassed.

There is no draft or unlisted state for mods. `Mod` has no visibility field;
creation inserts directly into `Mods`, and all public list/detail/download
queries read that table without a publication filter. Consequently, calling the
production create endpoint would publish immediately. This job must instead
stage the exact payload in the isolated local Website and leave a beta.20
publication checklist for the owner/ATC.

Screenshots are optional at creation and can be appended later by the author
through authenticated `POST /api/mods/{slug}/screenshots`, reordered with
`PUT /api/mods/{slug}/screenshots/order`, or removed individually. Leaving all
slots empty is supported.

New releases use authenticated
`POST /api/mods/{slug}/versions`. Every release must retain
`manifest.id == "bot.brain"` and the form version must equal the manifest
version. `POST /api/mods/updates` selects the highest valid semantic manifest
version and returns its package hash, content hash, and version-download URL, so
a locally published `1.0.1` is the correct proof that installed `1.0.0` users
receive an automatic update.

## Compatibility finding

There is currently no minimum-loader field in either manifest implementation.
The current source identifies itself as `0.1.0-beta.19`; the post-beta.19
structured-list work keeps `runtime.apiVersion: "0.2.0"`, and beta.19 already
advertised the bot and scalar settings capabilities. API version and the
existing required-capability list therefore cannot distinguish the roster build
from released beta.19 by themselves.

Two additional current-contract gaps prevent publication:

1. The production Website inspector rejects the root `settings` block as an
   unknown manifest field, so the current Lua Bots ZIP cannot be uploaded.
2. A beta.19 launcher request contains no loader version, and the website's
   resolve/update responses do not carry compatibility metadata.

The beta.20 preparation must add one strict, semantic
`minimumLoaderVersion` manifest field and set Lua Bots to
`0.1.0-beta.20`. The launcher must reject an incompatible managed, cached, or
downloaded mod before it is selected or staged. The website inspector and JSON
Schema must accept and preserve the field, and resolve/update requests must
include the requesting loader version so the website does not offer an
incompatible package. A missing request version remains valid only for mods
that declare no minimum, preserving old clients for existing packages.

Because released beta.19 cannot be retroactively taught a new manifest field,
an absolute ban on a user manually extracting arbitrary ZIP bytes into that old
launcher is impossible. The enforceable official-distribution contract is:

- beta.19's website resolve/update request cannot obtain Lua Bots;
- beta.20 and newer reject it before install/staging when incompatible; and
- the mod declares a beta.20-only settings-list capability so beta.19's runtime
  cannot start it even after an out-of-band manual extraction.

The public listing must remain offline until the beta.20 launcher and the
matching Website contract are released.

## Owner retarget decision (2026-07-27)

The published v0.1.0-beta.20 tag at `6776382` remains immutable. The owner
explicitly rejected a beta.20 reissue so its installed population cannot fork.
Lua Bots is therefore retargeted to v0.1.0-beta.21:

- `minimumLoaderVersion` and the official-distribution compatibility floor are
  `0.1.0-beta.21`;
- the listing requirement sentence names v0.1.0-beta.21;
- the production listing remains offline until beta.21 is published; and
- `codex/botpub-website-20260727` remains undeployed until the owner/ATC merges
  it as part of the same-day publication flip.
