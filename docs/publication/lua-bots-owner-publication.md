# Lua Bots v1.0.3 owner staging handoff

Lua Bots v1.0.3 supersedes the staged, unpublished v1.0.2 package. This wave
does not create a listing, call a production endpoint, or use owner
credentials. It prepares an update for the owner to submit through the
existing listing's **Add version** flow.

## Prepared staging artifacts

The complete handoff is under:

```text
/mnt/d/codex-evidence/botmatch-20260728/package/
```

It contains:

- `lua-bots-1.0.3.zip`;
- `lua-bots-1.0.3.zip.sha256`;
- deterministic package metadata with the package and content hashes; and
- `listing-update-1.0.3.json` with the existing listing copy and the complete
  v1.0.3 mod changelog.

The v1.0.3 changelog includes all unpublished v1.0.2 Behavior, Discipline,
appearance, stuck-recovery, equipped-range, and applied-damage content. It also
records the pre-wave idle behavior needed to let a complete bot party navigate
and regroup in the hub before Solomon Dig starts. Loader implementation details
are not presented as Lua Bots features.

## Owner submission checklist

1. Verify the ZIP against `lua-bots-1.0.3.zip.sha256`.
2. Confirm the archive-root manifest reports id `bot.brain`, version `1.0.3`,
   and minimum loader `0.1.0-beta.22`.
3. Open the existing Lua Bots listing's **Add version** flow.
4. Upload `lua-bots-1.0.3.zip`; do not use the initial mod-creation endpoint.
5. Apply the description and changelog from `listing-update-1.0.3.json`.
6. Verify the resulting public version, hashes, and beta.22 compatibility from
   a separate launcher before announcing it.

Keep `manifest.id` equal to `bot.brain` for future updates, increment
`manifest.version` semantically, and upload the matching package. Installed
users receive the newest compatible semantic version through
`POST /api/mods/updates`.
