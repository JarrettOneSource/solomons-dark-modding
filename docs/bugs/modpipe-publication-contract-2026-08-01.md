# Mod publication contract and stale listings

Date: 2026-08-01

Status: root cause recorded before the content and packaging changes

## Owner report

The live Lua Bots listing is behind the mod currently on `main`, and the live
Invincibility Potion listing still presents the earlier canary release under a
temporary author account. The replacement packages must remain native to the
loader's existing multiplayer authority and replication seams.

## Investigation

The production API reported these live states before any write:

- `lua-bots` was authored by `Generic` and had only version `1.0.0`;
- `invincibility-potion-canary` was authored by
  `LuaCanary20260723` and had only version `0.1.0`; and
- the source Lua Bots manifest was already version `1.2.0`, so `1.2.0` had
  never been published.

The current Invincibility Potion implementation already uses the shared
framework paths: stable custom content identity, stock loot and inventory,
reliable replicated consumption, peer-local native `SpellGlow`, owner-side
resource mutation, authority-side damage filtering, and a local timer created
from the replicated duration. Its green PNG and reversed sprite bundle are
registered for both inventory and world rendering. The defect is not a missing
mod-specific network protocol. The package and listing were left in test-facing
canary form, and the behavior had never received downloaded-package acceptance.

The current Lua Bots manifest also contains `summary` and `description` at the
manifest root. Those are website listing fields, not launcher manifest fields.
The website package inspector on Website `origin/main` SHA
`a6460deb22e644320263c20612e29c29f5bed4f0` captures unknown manifest fields
through `JsonExtensionData` and rejects any non-empty extension data. The local
website packager validated semantic versions but did not enforce that strict
root-field contract. A fresh `1.2.0` package would therefore be deterministic
but rejected by the real publication endpoint.

Finally, the website PATCH endpoint can update a listing's name, summary,
description, and tags, but it cannot transfer authorship. Author identity comes
from the authenticated account used to create the listing. Moving the potion to
`Generic` must consequently use the website's authenticated delete-and-create
flow, with exact package and listing preflight, rather than a database edit.

## Root cause

Publication copy was duplicated into a runtime manifest that has a deliberately
closed schema, while the repository packager modeled only ZIP determinism and
version syntax. Separately, the canary was published as a temporary-account
artifact and was never promoted into a player-facing listing owned by Generic.
These are content-lifecycle and package-contract failures; adding client-only
state or bespoke synchronization would not address either one.

## Foundational correction

The correction is to keep player copy in explicit publication metadata, keep
runtime manifests inside the launcher's website contract, make the packager
reject unknown fields before upload, publish fresh packages built from the
current tree, and prove the downloaded bytes through solo, local multiplayer,
and real Steam runs. The potion keeps its stable internal content ID so existing
framework identity remains deterministic. Boneyard support is intentionally
unchanged.
