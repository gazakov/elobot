import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import discord
from discord import app_commands
import config
import locales
from database import Database
from cogs.ranked import RankedCog
from cogs.admin import AdminCog

class TestCountrySystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.bot = MagicMock()
        self.ranked_cog = RankedCog(self.bot, self.db)
        self.admin_cog = AdminCog(self.bot, self.db)

    async def asyncTearDown(self):
        self.db.close()

    def test_country_whitelist_and_exclusions(self):
        """Проверка белого списка стран и явных исключений (UZ, TJ)"""
        # Проверяем, что UZ и TJ исключены
        self.assertNotIn("UZ", config.COUNTRIES)
        self.assertNotIn("TJ", config.COUNTRIES)
        self.assertIsNone(config.get_country_info("UZ"))
        self.assertIsNone(config.get_country_info("TJ"))
        self.assertEqual(config.get_country_flag("UZ"), "")
        self.assertEqual(config.get_country_flag("TJ"), "")

        # Проверяем ключевые страны СНГ и Европы
        expected_countries = ["RU", "UA", "KZ", "BY", "GE", "AM", "AZ", "MD", "KG", "PL", "DE", "GB", "FR", "US"]
        for c in expected_countries:
            self.assertIn(c, config.COUNTRIES)
            info = config.get_country_info(c)
            self.assertIsNotNone(info)
            self.assertTrue(len(info["flag"]) > 0)
            self.assertTrue(len(info["name_ru"]) > 0)
            self.assertTrue(len(info["name_en"]) > 0)

        # Проверка get_country_flag
        self.assertEqual(config.get_country_flag("RU"), "🇷🇺 ")
        self.assertEqual(config.get_country_flag(None), "")
        self.assertEqual(config.get_country_flag("INVALID"), "")

    def test_database_country_operations_and_cooldown(self):
        """Тестирование установки страны, кулдауна 30 дней и админ-оверрайда"""
        user_id = 123456789
        self.db.get_or_create_user(user_id)

        # 1. Начальное состояние - страна не установлена
        self.assertIsNone(self.db.get_user_country(user_id))

        # 2. Первая установка страны - должна пройти успешно
        success, msg = self.db.set_user_country(user_id, "RU", cooldown_days=30)
        self.assertTrue(success)
        self.assertEqual(self.db.get_user_country(user_id), "RU")

        # 3. Повторная попытка смены страны немедленно - должна быть отклонена по кулдауну
        success2, msg2 = self.db.set_user_country(user_id, "KZ", cooldown_days=30)
        self.assertFalse(success2)
        self.assertIn("30", msg2)
        self.assertEqual(self.db.get_user_country(user_id), "RU") # Не изменилась

        # 4. Сброс страны пользователем (None) разрешен
        success3, msg3 = self.db.set_user_country(user_id, None, cooldown_days=30)
        self.assertTrue(success3)
        self.assertIsNone(self.db.get_user_country(user_id))

        # 5. Админ может установить страну без учета кулдауна
        # Сначала ставим RU
        self.db.set_user_country(user_id, "RU", cooldown_days=30)
        # Админ меняет на UA
        admin_res = self.db.admin_set_user_country(user_id, "UA")
        self.assertTrue(admin_res)
        self.assertEqual(self.db.get_user_country(user_id), "UA")

        # Админ может сбросить
        admin_res_reset = self.db.admin_set_user_country(user_id, None)
        self.assertTrue(admin_res_reset)
        self.assertIsNone(self.db.get_user_country(user_id))

    def test_locales_country_keys(self):
        """Проверка наличия всех переводов для системы стран в RU и EN"""
        keys = [
            "country_cmd_desc",
            "country_param_desc",
            "country_invalid",
            "country_confirm_title",
            "country_confirm_desc",
            "country_cooldown_error",
            "country_success",
            "country_reset_success",
            "country_profile_field",
            "country_cancelled"
        ]
        for k in keys:
            t_ru = locales.t(k, "ru", flag="🇷🇺", name="Россия", code="RU", days=30)
            t_en = locales.t(k, "en", flag="🇷🇺", name="Russia", code="RU", days=30)
            self.assertTrue(len(t_ru) > 0, f"Missing ru translation for {k}")
            self.assertTrue(len(t_en) > 0, f"Missing en translation for {k}")
            self.assertNotEqual(t_ru, k, f"Key {k} fell back to raw key name in ru")
            self.assertNotEqual(t_en, k, f"Key {k} fell back to raw key name in en")

    async def test_country_autocomplete_limit(self):
        """Discord требует не более 25 вариантов в автокомплите"""
        interaction = MagicMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.russian

        # Ranked cog country autocomplete
        choices = await self.ranked_cog.country_autocomplete(interaction, "")
        self.assertLessEqual(len(choices), 25)
        self.assertGreater(len(choices), 0)

        # Фильтрация
        filtered_choices = await self.ranked_cog.country_autocomplete(interaction, "рус")
        self.assertTrue(any(c.value == "RU" for c in filtered_choices))

        # Admin cog country autocomplete
        admin_choices = await self.admin_cog.admin_country_autocomplete(interaction, "")
        self.assertLessEqual(len(admin_choices), 25)
        self.assertTrue(any(c.value == "RESET" for c in admin_choices))

    async def test_profile_embed_displays_country(self):
        """Проверка отображения флага и страны в эмбеде профиля"""
        user_id = 999888
        self.db.get_or_create_user(user_id, roblox_username="TestPlayer")
        self.db.admin_set_user_country(user_id, "UA")

        interaction = MagicMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.russian
        interaction.guild = None

        target_user = MagicMock()
        target_user.id = user_id
        target_user.display_name = "TestPlayer"
        target_user.mention = "<@999888>"
        target_user.display_avatar = MagicMock(url="https://example.com/avatar.png")

        embed, _, _ = await self.ranked_cog.build_yba_embed(target_user, "ru")
        self.assertIn("🇺🇦", embed.title)
        field_values = " ".join(f.value for f in embed.fields)
        self.assertIn("🇺🇦", field_values)
        self.assertIn("Украина", field_values)

if __name__ == "__main__":
    unittest.main()
