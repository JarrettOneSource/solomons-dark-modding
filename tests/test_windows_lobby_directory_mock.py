from __future__ import annotations

import unittest

from tools.windows_lobby_directory_mock import (
    LOBBY_ANNOUNCE_RESPONSE,
    MOD_UPDATE_RESPONSE,
    _post_route,
)


class WindowsLobbyDirectoryMockTests(unittest.TestCase):
    def test_mod_update_route_returns_an_empty_valid_response(self) -> None:
        self.assertEqual(
            _post_route("/api/mods/updates"),
            (MOD_UPDATE_RESPONSE, True),
        )

    def test_lobby_announce_route_records_its_contract_body(self) -> None:
        self.assertEqual(
            _post_route("/api/lobbies/announce"),
            (LOBBY_ANNOUNCE_RESPONSE, True),
        )

    def test_unknown_routes_never_retain_request_bodies(self) -> None:
        self.assertEqual(
            _post_route("/api/auth/steam/session"),
            (None, False),
        )


if __name__ == "__main__":
    unittest.main()
