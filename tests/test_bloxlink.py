import unittest
from unittest.mock import patch, MagicMock
import io
import bloxlink
from database import Database

class TestBloxlink(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    @patch("config.BLOXLINK_API_KEY", None)
    def test_get_bloxlink_key_from_db(self):
        """Проверка получения ключа Bloxlink из базы данных"""
        self.assertIsNone(bloxlink.get_bloxlink_key(self.db))
        self.db.set_setting("bloxlink_api_key", "test_key_123")
        self.assertEqual(bloxlink.get_bloxlink_key(self.db), "test_key_123")

    @patch("urllib.request.urlopen")
    def test_resolve_discord_to_roblox_success(self, mock_urlopen):
        """Проверка успешного резолва Discord -> Roblox через Bloxlink + Roblox API"""
        # 1-й вызов: Bloxlink API
        mock_resp_bloxlink = MagicMock()
        mock_resp_bloxlink.status = 200
        mock_resp_bloxlink.read.return_value = b'{"robloxID": "4003087869"}'
        mock_ctx1 = MagicMock()
        mock_ctx1.__enter__.return_value = mock_resp_bloxlink

        # 2-й вызов: Roblox Users API
        mock_resp_roblox = MagicMock()
        mock_resp_roblox.status = 200
        mock_resp_roblox.read.return_value = b'{"id": 4003087869, "name": "drainworldtour", "displayName": "sunny"}'
        mock_ctx2 = MagicMock()
        mock_ctx2.__enter__.return_value = mock_resp_roblox

        mock_urlopen.side_effect = [mock_ctx1, mock_ctx2]

        res = bloxlink.resolve_discord_to_roblox(123456, 789012, "valid_key")
        self.assertIsNotNone(res)
        roblox_id, username = res
        self.assertEqual(roblox_id, 4003087869)
        self.assertEqual(username, "drainworldtour")

    @patch("urllib.request.urlopen")
    def test_resolve_discord_to_roblox_primary_account_support(self, mock_urlopen):
        """Проверка резолва через primaryAccount (Bloxlink v4 Global/Accounts формат)"""
        # 1-й вызов: Bloxlink API с primaryAccount
        mock_resp_bloxlink = MagicMock()
        mock_resp_bloxlink.status = 200
        mock_resp_bloxlink.read.return_value = b'{"primaryAccount": "10888640702", "accounts": ["10888640702"]}'
        mock_ctx1 = MagicMock()
        mock_ctx1.__enter__.return_value = mock_resp_bloxlink

        # 2-й вызов: Roblox Users API
        mock_resp_roblox = MagicMock()
        mock_resp_roblox.status = 200
        mock_resp_roblox.read.return_value = b'{"id": 10888640702, "name": "Frosco9100", "displayName": "Frosco"}'
        mock_ctx2 = MagicMock()
        mock_ctx2.__enter__.return_value = mock_resp_roblox

        mock_urlopen.side_effect = [mock_ctx1, mock_ctx2]

        res = bloxlink.resolve_discord_to_roblox(123456, 999888, "valid_key")
        self.assertIsNotNone(res)
        roblox_id, username = res
        self.assertEqual(roblox_id, 10888640702)
        self.assertEqual(username, "Frosco9100")

    @patch("urllib.request.urlopen")
    def test_resolve_roblox_to_discord(self, mock_urlopen):
        """Проверка обратного поиска Bloxlink для анти-твинков"""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"discordIDs": ["111222333", "444555666"]}'
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_ctx

        uids = bloxlink.resolve_roblox_to_discord(123456, 4003087869, "valid_key")
        self.assertEqual(uids, [111222333, 444555666])

    @patch("urllib.request.urlopen")
    def test_get_roblox_account_info_old_and_new(self, mock_urlopen):
        """Проверка расчета возраста аккаунта и флага <30 дней для правил лиги GangHub"""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        old_dt = now - timedelta(days=500)
        new_dt = now - timedelta(days=10)

        # 1. Старый аккаунт (>30 дней)
        mock_resp1 = MagicMock()
        mock_resp1.read.return_value = f'{{"id": 1001, "name": "VeteranPlayer", "displayName": "Vet", "created": "{old_dt.isoformat()}"}}'.encode("utf-8")
        mock_ctx1 = MagicMock()
        mock_ctx1.__enter__.return_value = mock_resp1

        mock_urlopen.side_effect = [mock_ctx1]
        info_old = bloxlink.get_roblox_account_info(1001)
        self.assertIsNotNone(info_old)
        self.assertEqual(info_old["username"], "VeteranPlayer")
        self.assertFalse(info_old["is_new"])
        self.assertGreaterEqual(info_old["days_old"], 499)

        # 2. Новый аккаунт (<30 дней)
        mock_resp2 = MagicMock()
        mock_resp2.read.return_value = f'{{"id": 1002, "name": "NewPlayer", "displayName": "Noob", "created": "{new_dt.isoformat()}"}}'.encode("utf-8")
        mock_ctx2 = MagicMock()
        mock_ctx2.__enter__.return_value = mock_resp2

        mock_urlopen.side_effect = [mock_ctx2]
        info_new = bloxlink.get_roblox_account_info(1002)
        self.assertIsNotNone(info_new)
        self.assertEqual(info_new["username"], "NewPlayer")
        self.assertTrue(info_new["is_new"])
        self.assertLess(info_new["days_old"], 30)

    @patch("urllib.request.urlopen")
    def test_fetch_roblox_full_avatar_bytes(self, mock_urlopen):
        """Проверка получения 3D HD скина и кэширования"""
        from cogs.ranked import fetch_roblox_full_avatar_bytes
        
        # 1. Ответ Roblox Users API (поиск по ID)
        mock_resp_user = MagicMock()
        mock_resp_user.read.return_value = b'{"id": 2001, "name": "SkinHero", "displayName": "Hero", "created": "2023-01-01T00:00:00Z"}'
        mock_ctx1 = MagicMock()
        mock_ctx1.__enter__.return_value = mock_resp_user

        # 2. Ответ Thumbnails API
        mock_resp_thumb = MagicMock()
        mock_resp_thumb.read.return_value = b'{"data": [{"targetId": 2001, "imageUrl": "https://tr.rbxcdn.com/test_skin"}]}'
        mock_ctx2 = MagicMock()
        mock_ctx2.__enter__.return_value = mock_resp_thumb

        # 3. Ответ с байтами изображения (PNG сигнатура \x89PNG)
        mock_resp_img = MagicMock()
        fake_png = b'\x89PNG\r\n\x1a\nfake_image_bytes'
        mock_resp_img.read.return_value = fake_png
        mock_ctx3 = MagicMock()
        mock_ctx3.__enter__.return_value = mock_resp_img

        mock_urlopen.side_effect = [mock_ctx1, mock_ctx2, mock_ctx3]

        res = fetch_roblox_full_avatar_bytes(2001)
        self.assertIsNotNone(res)
        img_bytes, acc_info, img_url = res
        self.assertEqual(img_bytes, fake_png)
        self.assertEqual(acc_info["username"], "SkinHero")
        self.assertEqual(img_url, "https://tr.rbxcdn.com/test_skin")

if __name__ == "__main__":
    unittest.main()
