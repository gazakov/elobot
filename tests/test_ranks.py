import unittest
from ranks import get_rank_info

class TestRanksSystem(unittest.IsolatedAsyncioTestCase):
    def test_unranked_calibration(self):
        """Проверка: игрок с менее чем 5 играми получает Unranked / Калибровка"""
        info = get_rank_info(rating=1500.0, rd=350.0, total_games=2)
        self.assertFalse(info["is_calibrated"])
        self.assertEqual(info["tier"], "Unranked / Калибровка")
        self.assertEqual(info["badge"], "🟤")
        self.assertTrue(info["display"].endswith("?"))

    def test_bronze_tier(self):
        """Проверка: игрок с рейтингом < 1300 получает Bronze"""
        info = get_rank_info(rating=1250.0, rd=100.0, total_games=10)
        self.assertTrue(info["is_calibrated"])
        self.assertEqual(info["tier"], "Bronze")
        self.assertEqual(info["badge"], "🥉")

    def test_silver_tier(self):
        """Проверка: игрок с рейтингом 1300–1499 получает Silver"""
        info = get_rank_info(rating=1350.0, rd=90.0, total_games=8)
        self.assertTrue(info["is_calibrated"])
        self.assertEqual(info["tier"], "Silver")
        self.assertEqual(info["badge"], "🥈")

    def test_gold_tier(self):
        """Проверка: игрок с рейтингом 1500–1699 получает Gold"""
        info = get_rank_info(rating=1620.0, rd=80.0, total_games=8)
        self.assertTrue(info["is_calibrated"])
        self.assertEqual(info["tier"], "Gold")
        self.assertEqual(info["badge"], "🥇")

    def test_platinum_tier(self):
        """Проверка: игрок с рейтингом 1700–1899 получает Platinum"""
        info = get_rank_info(rating=1780.0, rd=70.0, total_games=12)
        self.assertTrue(info["is_calibrated"])
        self.assertEqual(info["tier"], "Platinum")
        self.assertEqual(info["badge"], "🔘")

    def test_diamond_tier(self):
        """Проверка: игрок с рейтингом 1900–2099 получает Diamond"""
        info = get_rank_info(rating=1980.0, rd=70.0, total_games=15)
        self.assertTrue(info["is_calibrated"])
        self.assertEqual(info["tier"], "Diamond")
        self.assertEqual(info["badge"], "💎")

    def test_master_tier(self):
        """Проверка: игрок с рейтингом 2100–2249 получает Master"""
        info = get_rank_info(rating=2150.0, rd=65.0, total_games=20)
        self.assertTrue(info["is_calibrated"])
        self.assertEqual(info["tier"], "Master")
        self.assertEqual(info["badge"], "🔮")

    def test_grandmaster_tier(self):
        """Проверка: игрок с рейтингом 2250+ получает Grandmaster"""
        info = get_rank_info(rating=2280.0, rd=60.0, total_games=25)
        self.assertTrue(info["is_calibrated"])
        self.assertEqual(info["tier"], "Grandmaster")
        self.assertEqual(info["badge"], "👑")

    def test_top_10_special_role(self):
        """Проверка: игроки в топ-10 получают специальный титул Top 10"""
        top1 = get_rank_info(rating=2200.0, rd=50.0, total_games=30, rank_position=1)
        self.assertIsNotNone(top1["special_title"])
        self.assertIn("Top 10", top1["special_title"])
        self.assertIn("Чемпион #1", top1["special_title"])

        top5 = get_rank_info(rating=1900.0, rd=60.0, total_games=20, rank_position=5)
        self.assertIsNotNone(top5["special_title"])
        self.assertIn("Top 10 (#5)", top5["special_title"])

        top15 = get_rank_info(rating=1700.0, rd=70.0, total_games=15, rank_position=15)
        self.assertIsNone(top15["special_title"])

    async def test_ensure_all_rank_roles(self):
        """Проверка: ensure_all_rank_roles создает все недостающие роли лиги на сервере"""
        from ranks import ensure_all_rank_roles
        from unittest.mock import AsyncMock, MagicMock

        guild = MagicMock()
        me = MagicMock()
        me.guild_permissions.manage_roles = True
        guild.me = me
        guild.roles = [] # пустой сервер без ролей

        created_role_names = []
        async def fake_create_role(name, color=None, reason=None):
            role_mock = MagicMock()
            role_mock.name = name
            guild.roles.append(role_mock)
            created_role_names.append(name)
            return role_mock

        guild.create_role = AsyncMock(side_effect=fake_create_role)

        res = await ensure_all_rank_roles(guild)
        self.assertIn("Bronze", res)
        self.assertIn("Silver", res)
        self.assertIn("Gold", res)
        self.assertIn("Platinum", res)
        self.assertIn("Diamond", res)
        self.assertIn("Master", res)
        self.assertIn("Grandmaster", res)
        self.assertIn("Top 10", res)
        self.assertNotIn("Unranked / Калибровка", res)
        self.assertIn("Duck", res)
        self.assertIn("Duck Evade", res)

        # Повторный вызов не должен ничего создавать, так как роли уже есть
        res_second = await ensure_all_rank_roles(guild)
        self.assertEqual(res_second, [])

    async def test_sync_user_roles_skips_uncalibrated_players(self):
        """Проверка: игрокам на калибровке (< 5 матчей) не выдаются роли"""
        from ranks import sync_user_roles
        from unittest.mock import MagicMock

        guild = MagicMock()
        me = MagicMock()
        me.guild_permissions.manage_roles = True
        me.top_role.position = 100
        guild.me = me
        guild.owner_id = 999999

        member = MagicMock()
        member.id = 123456
        member.top_role.position = 10
        member.roles = []

        uncalibrated_rank_info = {
            "name": "Unranked / Калибровка",
            "tier": "Unranked / Калибровка",
            "is_calibrated": False,
            "color": 0x808080
        }

        assigned_role = await sync_user_roles(member, uncalibrated_rank_info, guild)
        self.assertIsNone(assigned_role)
        member.edit.assert_not_called()



if __name__ == "__main__":
    unittest.main()
