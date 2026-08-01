# Lua Bots 1.2.0 publication record

Date: 2026-08-01

Status: fresh package prepared; production publication and downloaded-package
acceptance pending

Lua Bots 1.2.0 is built from the current `mods/bot-brain` source. It does not
reuse the superseded 1.2.0 staging package from 2026-07-31.

## Prepared package

- Path: `/mnt/d/codex-evidence/modpipe-20260801/phase-a/packages/lua-bots-1.2.0.zip`
- Package SHA-256: `5a53a8292d122e0e88d0243d334b26a4459032b5fd9096f34eee606cfa2ef14c`
- Content SHA-256: `41413291606f5b39396e918b087223d0eb568e8192ca8c44a021dadd04bb3c5b`
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
- Fixed multiplayer skill choices targeting the wrong participant.
- Requires beta.29 for primary-skill handback and removal of the extra ally row
  during takeover.

Production completion requires the authenticated website flow, confirmation
that the live listing reports author `Generic` and version `1.2.0`, and a fresh
launcher download whose package hash matches this record.
