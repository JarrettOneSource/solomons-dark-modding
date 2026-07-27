# Lua Bots owner publication checklist

The production website does not have draft or unlisted mod visibility. Creating
a mod through `POST /api/mods` makes it public immediately. Keep the production
submission until the v0.1.0-beta.21 loader release is live.

## Release decision

The owner decided that the published v0.1.0-beta.20 tag at `6776382` stays
exactly as released. Do not replace its assets or move its tag. Lua Bots is
retargeted to v0.1.0-beta.21 and must remain offline until that release is
public.

The prepared package is:

```text
/mnt/d/codex-evidence/botpub-20260727/package/lua-bots-1.0.0.zip
```

- Package SHA-256:
  `792e03211ab073d2c42c02ca660e4eb6be0569450cd39fc2f88a3cfb9edf1a40`
- Content SHA-256:
  `5d35c66ce289b0a281f0edb227dc54906fdc6b181f39d3040c8c883ccb2097f8`

Before submission, merge and deploy the Website compatibility work from
`codex/botpub-website-20260727`. It teaches the production package inspector,
resolve endpoint, and update endpoint about the beta.21 minimum-loader field.

1. Publish v0.1.0-beta.21 and verify its public launcher/runtime assets.
2. Merge and deploy `codex/botpub-website-20260727`.
3. Sign in to the owner account at `https://solomondarker.com`.
4. Open the mod submission form.
5. Upload the verified `lua-bots-1.0.0.zip` artifact.
6. Enter the exact values from `lua-bots-submission.json`.
7. Leave all screenshot slots empty. Screenshots can be added after creation.
8. Confirm the upload version is `1.0.0`; it must equal `manifest.version`.
9. Verify the public detail response reports manifest id `bot.brain`, version
   `1.0.0`, and minimum loader `0.1.0-beta.21`.
10. From a beta.21 launcher, install the listing and verify the Mods-tab
    settings gear before announcing it.

Future updates use the listing's **Add version** flow
(`POST /api/mods/{slug}/versions`). Keep `manifest.id` equal to `bot.brain`,
increase `manifest.version` semantically, and upload the matching package.
Installed users receive the newest compatible semantic version through
`POST /api/mods/updates`.
