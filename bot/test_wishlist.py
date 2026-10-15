import unittest
from unittest.mock import patch

import handler


class WishlistTests(unittest.TestCase):

    @patch("handler.db.add_game", return_value=True)
    @patch("handler.steam.get_game_name", return_value="Portal 2")
    @patch("handler.steam.get_app_id", return_value=620)
    def test_game_found_is_added(self, get_id, get_name, add_game):
        status, msg = handler.add_to_wishlist(1, 2, "https://store.steampowered.com/app/620/")
        self.assertEqual(status, "added")
        self.assertIn("Portal 2", msg)
        add_game.assert_called_once_with(1, 2, 620, "Portal 2")

    @patch("handler.db.add_game")
    @patch("handler.steam.get_game_name", return_value=None)
    @patch("handler.steam.get_app_id", return_value=99999999)
    def test_game_not_found(self, get_id, get_name, add_game):
        status, msg = handler.add_to_wishlist(1, 2, "https://store.steampowered.com/app/99999999/")
        self.assertEqual(status, "not_found")
        add_game.assert_not_called()

    @patch("handler.db.add_game", return_value=False)
    @patch("handler.steam.get_game_name", return_value="Portal 2")
    @patch("handler.steam.get_app_id", return_value=620)
    def test_already_on_wishlist(self, get_id, get_name, add_game):
        status, msg = handler.add_to_wishlist(1, 2, "https://store.steampowered.com/app/620/")
        self.assertEqual(status, "duplicate")
        self.assertIn("already", msg)

    @patch("handler.db.add_game")
    @patch("handler.steam.get_app_id", return_value=None)
    def test_not_a_steam_link(self, get_id, add_game):
        status, msg = handler.add_to_wishlist(1, 2, "https://google.com")
        self.assertEqual(status, "bad_link")
        add_game.assert_not_called()

    @patch("handler.db.add_game")
    @patch("handler.steam.get_app_id", return_value=None)
    def test_empty_input(self, get_id, add_game):
        status, msg = handler.add_to_wishlist(1, 2, "   ")
        self.assertEqual(status, "bad_link")

    @patch("handler.db.add_game")
    @patch("handler.steam.get_game_name", side_effect=ConnectionError("steam down"))
    @patch("handler.steam.get_app_id", return_value=620)
    def test_steam_error_does_not_crash(self, get_id, get_name, add_game):
        status, msg = handler.add_to_wishlist(1, 2, "https://store.steampowered.com/app/620/")
        self.assertEqual(status, "error")
        add_game.assert_not_called()


if __name__ == "__main__":
    unittest.main()