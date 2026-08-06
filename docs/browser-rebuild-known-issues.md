# Browser rebuild known issues

## Temporary G11 visual waiver

ATC's 2026-08-05 evening decision keeps exact landed-layout replay as the T2
truth while menufix task #97 re-captures the G11 corpus with settle-gated,
machine-derived provenance. The current standalone fixtures for the following
screens literally carry the `stale controls omitted` marker and can disagree
with their paired reference captures:

- `controls`
- `dark-cloud-login-settings`
- `dark-cloud-search`
- `dark-cloud-settings`
- `game-over`
- `game-settings-dark-cloud`
- `game-settings-gameplay`
- `game-settings-title`
- `hall-of-fame`
- `performance`

Only those ten side-by-side divergences are temporarily waived. The other 18
screens still require the same assetpack art at exact G11 positions, with only
font rasterization allowed to differ. The waiver is self-expiring: once a
listed fixture loses the literal marker, the registered contract fails until
its entry is removed and that screen passes the ordinary visual review. Never
reconstruct missing geometry from a PNG; menufix #97 is the corrective source.
