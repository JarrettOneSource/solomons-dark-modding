# Lua Bots 1.2.0 publication record

Date: 2026-08-01

Status: fresh package prepared; production publication and downloaded-package
acceptance pending

Lua Bots 1.2.0 is built from the current `mods/bot-brain` source. It does not
reuse the superseded 1.2.0 staging package from 2026-07-31.

## Prepared package

- Path: `/mnt/d/codex-evidence/botlevel-20260804/packages/lua-bots-1.2.0.zip`
- Package SHA-256: `c29f61b4c94bcc1b8b122a7d458f8772bd3804a11e229de479134cf68f355b93`
- Content SHA-256: `503e0869e4c29db9e4d50d9b150cbd2fdbb8b8fd0bcce8b273b2904d553d8bda`
- Manifest ID: `bot.brain`
- Minimum loader: `0.1.0-beta.29`

The archive is rooted at `manifest.json`, contains only the Lua Bots README,
changelog, manifest, and Lua scripts, and has no native binaries or wrapper
directory. `docs/publication/lua-bots-listing.json` contains the player-facing
listing and `docs/publication/lua-bots-submission.json` describes the exact
PATCH plus Add Version requests.

## Player changelog

- Added Bot Play For Me with the F9 toggle and clean control handback.
- Bots choose a random offered skill at level-up.
- Bots stop casting at 10 percent mana and resume at 80 percent.
- Fixed bots getting stuck at exactly 10 percent mana while movement kept
  running.
- Fixed multiplayer skill choices targeting the wrong participant.
- Requires beta.29 for primary-skill handback and removal of the extra ally row
  during takeover.

Production completion requires the authenticated website flow, confirmation
that the live listing reports author `Generic` and version `1.2.0`, and a fresh
launcher download whose package hash matches this record.
