# Staged Release loader acceptance

## Investigation

`Verify-Workspace.ps1` defaults to Debug and `Build-All.ps1` copies that
configuration's `SolomonDarkModLoader.dll` into `dist/launcher`. A later live
acceptance script therefore cannot infer safety from an earlier Release build.

The current DLLs contain a CodeView PDB path with `Debug` or `Release`, but that
path is incidental linker metadata rather than a supported build-flavor
contract. The loader does not otherwise identify its configuration in the DLL
or startup log.

## Design

The native build will embed one explicit ASCII stamp,
`SDMOD_BUILD_FLAVOR=Debug` or `SDMOD_BUILD_FLAVOR=Release`, selected from the
same `NDEBUG` configuration boundary that enables the Release build. Startup
will log the same flavor so live evidence remains human-readable.

One shared PowerShell assertion will read the DLL beside the launcher, require
exactly one recognized stamp, and refuse anything except `Release`. Every
PowerShell acceptance path that issues the launch command will pass through
that assertion immediately before starting the launcher. Refusal is the
uniform behavior: acceptance scripts will never silently rebuild or restage.

Static contracts will keep the native stamp, shared assertion, and complete
launcher wiring registered. Executable PowerShell coverage will exercise a
Release stamp, a Debug stamp, a missing stamp, and a missing DLL without
starting the game.
