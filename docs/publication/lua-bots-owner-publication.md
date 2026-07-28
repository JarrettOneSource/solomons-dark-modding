# Lua Bots v1.0.1 owner staging handoff

The Lua Bots listing already exists, and its live summary and description were
updated directly by ATC. This wave does not create a listing, call a production
endpoint, or use owner credentials. It prepares a v1.0.1 update for the owner
to submit through the existing listing's **Add version** flow.

## Prepared staging artifacts

The complete handoff is under:

```text
/mnt/d/codex-evidence/botpolish-20260727/package/
```

It contains:

- `lua-bots-1.0.1.zip`;
- `lua-bots-1.0.1.zip.sha256`;
- deterministic package metadata with the package and content hashes; and
- `listing-update-1.0.1.json` with the exact live description and staged
  changelog.

## Owner submission checklist

1. Verify the ZIP against `lua-bots-1.0.1.zip.sha256`.
2. Confirm the archive-root manifest reports id `bot.brain`, version `1.0.1`,
   and minimum loader `0.1.0-beta.22`.
3. Open the existing Lua Bots listing's **Add version** flow.
4. Upload `lua-bots-1.0.1.zip`; do not use the initial mod-creation endpoint.
5. Apply the description and changelog from `listing-update-1.0.1.json`.
6. Verify the resulting public version, hashes, and beta.22 compatibility from
   a separate launcher before announcing it.

Keep `manifest.id` equal to `bot.brain` for future updates, increment
`manifest.version` semantically, and upload the matching package. Installed
users receive the newest compatible semantic version through
`POST /api/mods/updates`.
