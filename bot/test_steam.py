import unittest
import steam


class TestGetAppId(unittest.TestCase):

    def test_normal_link(self):
        self.assertEqual(steam.get_app_id("https://store.steampowered.com/app/620/Portal_2/"), 620)

    def test_link_without_name(self):
        self.assertEqual(steam.get_app_id("https://store.steampowered.com/app/440"), 440)

    def test_not_a_steam_link(self):
        self.assertIsNone(steam.get_app_id("https://google.com"))

    def test_steam_link_without_app_id(self):
        self.assertIsNone(steam.get_app_id("https://store.steampowered.com/"))

    def test_empty_string(self):
        self.assertIsNone(steam.get_app_id(""))

    def test_plain_text(self):
        self.assertIsNone(steam.get_app_id("portal 2"))


class TestGetGameName(unittest.TestCase):

    def test_known_game(self):
        self.assertEqual(steam.get_game_name(620), "Portal 2")

    def test_unknown_game(self):
        self.assertIsNone(steam.get_game_name(99999999))


if __name__ == "__main__":
    unittest.main()