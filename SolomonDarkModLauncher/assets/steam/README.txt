Place the 32-bit Steamworks runtime here when the mirrored Solomon Dark build does not
already ship one:

  assets/steam/win32/steam_api.dll

The launcher stages steam_appid.txt automatically with Solomon Dark AppID 3362180.
It copies this x86 steam_api.dll into the staged game root when needed.

For local development, the launcher also checks STEAMWORKS_SDK_PATH and the local
SteamVR win32 runtime. The DLL is copied only into the disposable runtime stage;
no Steam credentials or account data are copied or packaged.
