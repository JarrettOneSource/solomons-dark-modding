# Fieldbreak25 existing-wizard save fixture

This fixture is a launcher-owned test profile created by the isolated
`fb25-cal13-client` loopback instance. It is not copied from an owner
installation. First-run setup and the wizard's hub cache are already present,
while both an in-progress `gamestate.sav` and the Boneyard `Region4._cache`
are deliberately absent.
The native multiplayer quick-start flow can therefore select the run loadout
without replaying the tutorial, resuming stale combat, or restoring an
exhausted Boneyard arena.

The verifier copies `solomondark/` into a separate writable save root for each
peer before launch. The checked-in fixture remains read-only input.

SHA-256:

- `solomondark/darkdata.cfg`:
  `0a9dd9c222b61df4930495aea50a65ebe2e057811092080451fee94a6594ea06`
- `solomondark/savegames/ARTORIUS/Region0._cache`:
  `b161e5ee2db912f55b6086b562f1dff797e81176a69c887fc1eb2324bd0bf15e`
