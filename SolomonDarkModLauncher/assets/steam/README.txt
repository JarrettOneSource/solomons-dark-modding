Place the 32-bit Steamworks runtime here when the mirrored Solomon Dark build does not
already ship one:

  assets/steam/win32/steam_api.dll

The launcher stages steam_appid.txt automatically with AppID 3362180 by default and
will copy this x86 steam_api.dll into the staged game root when needed.
