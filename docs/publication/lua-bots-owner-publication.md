# Lua Bots owner publication checklist

The production website does not have draft or unlisted mod visibility. Creating
a mod through `POST /api/mods` makes it public immediately. Keep the production
submission until the v0.1.0-beta.20 loader release is live.

The prepared package is:

```text
/mnt/d/codex-evidence/botpub-20260727/package/lua-bots-1.0.0.zip
```

- Package SHA-256:
  `6382bde4adbaeefb648011e1feb43618fd6411d1f8bf22b63ad7c005c66b1974`
- Content SHA-256:
  `889373adfe0ab08641374b95689b35ea9c15965644df69da8ece39856b93f6bc`

Before submission, merge and deploy the Website compatibility work from
`codex/botpub-website-20260727`. It teaches the production package inspector,
resolve endpoint, and update endpoint about the beta.20 minimum-loader field.

1. Sign in to the owner account at `https://solomondarker.com`.
2. Open the mod submission form.
3. Upload the verified `lua-bots-1.0.0.zip` artifact.
4. Enter the exact values from `lua-bots-submission.json`.
5. Leave all screenshot slots empty. Screenshots can be added after creation.
6. Confirm the upload version is `1.0.0`; it must equal `manifest.version`.
7. Submit only after v0.1.0-beta.20 is public.
8. Verify the public detail response reports manifest id `bot.brain`, version
   `1.0.0`, and minimum loader `0.1.0-beta.20`.
9. From a beta.20 launcher, install the listing and verify the Mods-tab settings
   gear before announcing it.

Future updates use the listing's **Add version** flow
(`POST /api/mods/{slug}/versions`). Keep `manifest.id` equal to `bot.brain`,
increase `manifest.version` semantically, and upload the matching package.
Installed users receive the newest compatible semantic version through
`POST /api/mods/updates`.
