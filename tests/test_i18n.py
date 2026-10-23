import unittest
from unittest.mock import MagicMock
import locales
from ranks import get_rank_info

class TestLocalization(unittest.TestCase):
    def test_get_lang_detection(self):
        """Проверка определения языка по клиенту Discord"""
        # Русский клиент
        ru_interaction = MagicMock()
        ru_interaction.locale = "ru"
        self.assertEqual(locales.get_lang(ru_interaction), "ru")

        # Английский клиент (US / GB)
        en_interaction = MagicMock()
        en_interaction.locale = "en-US"
        self.assertEqual(locales.get_lang(en_interaction), "en")

        # Другие языки по умолчанию получают международный английский интерфейс
        other_interaction = MagicMock()
        other_interaction.locale = "es-ES"
        self.assertEqual(locales.get_lang(other_interaction), "en")

        # None / fallback
        none_interaction = MagicMock()
        none_interaction.locale = None
        self.assertEqual(locales.get_lang(none_interaction), "en")

    def test_t_function_translations(self):
        """Проверка корректности подстановки переводов"""
        # Профиль
        ru_title = locales.t("profile_title", "ru", badge="🥉", name="Dio")
        en_title = locales.t("profile_title", "en", badge="🥉", name="Dio")
        self.assertEqual(ru_title, "🥉 Профиль Dio")
        self.assertEqual(en_title, "🥉 Dio's Profile")

        # Винрейт и стрик
        self.assertIn("win streak", locales.t("streak_wins", "en", count=5))
        self.assertIn("побед(ы) подряд", locales.t("streak_wins", "ru", count=5))

        # Правила, VIP, Вызов
        self.assertIn("League Rules", locales.t("rules_title", "en"))
        self.assertIn("Официальные правила", locales.t("rules_title", "ru"))

        # Проверка категорий правил GangHub
        for cat in ["bans", "formats", "stands", "checks", "duck"]:
            self.assertTrue(len(locales.t(f"rules_cat_{cat}_desc", "ru")) > 100)
            self.assertTrue(len(locales.t(f"rules_cat_{cat}_desc", "en")) > 100)

        self.assertIn("VIP Server", locales.t("vip_title", "en"))
        self.assertIn("Приватный сервер", locales.t("vip_title", "ru"))

        self.assertIn("1v1 Duel Challenge", locales.t("challenge_title", "en"))
        self.assertIn("Вызов на 1v1 дуэль", locales.t("challenge_title", "ru"))

    def test_get_rank_info_multilingual(self):
        """Проверка локализации рангов и калибровки"""
        # Калибровка на русском
        ru_calib = get_rank_info(rating=1500.0, rd=350.0, total_games=2, lang="ru")
        self.assertEqual(ru_calib["tier"], "Unranked / Калибровка")

        # Калибровка на английском
        en_calib = get_rank_info(rating=1500.0, rd=350.0, total_games=2, lang="en")
        self.assertEqual(en_calib["tier"], "Unranked / Calibration")

        # Top 1 титул
        ru_top1 = get_rank_info(rating=2200.0, rd=60.0, total_games=20, rank_position=1, lang="ru")
        en_top1 = get_rank_info(rating=2200.0, rd=60.0, total_games=20, rank_position=1, lang="en")
        self.assertIn("Чемпион #1", ru_top1["special_title"])
        self.assertIn("Champion #1", en_top1["special_title"])

    def test_clean_server_name_purity(self):
        """Проверка строгой языковой чистоты названий серверов"""
        # Hesse
        self.assertEqual(locales.clean_server_name("Hesse (Германия)", "en"), "Hesse (Germany)")
        self.assertEqual(locales.clean_server_name("Hesse (Германия)", "ru"), "Hesse (Германия)")
        # North Holland
        self.assertEqual(locales.clean_server_name("North Holland (Нидерланды)", "en"), "North Holland (Netherlands)")
        self.assertEqual(locales.clean_server_name("North Holland (Нидерланды)", "ru"), "North Holland (Нидерланды)")
        # London
        self.assertEqual(locales.clean_server_name("London (Великобритания)", "en"), "London (United Kingdom)")
        self.assertEqual(locales.clean_server_name("London (Великобритания)", "ru"), "London (Великобритания)")
        # US East
        self.assertEqual(locales.clean_server_name("US East (Восток США)", "en"), "US East (United States)")
        self.assertEqual(locales.clean_server_name("US East (Восток США)", "ru"), "US East (Восток США)")
        # Custom
        self.assertEqual(locales.clean_server_name("По договоренности", "en"), "Mutual Agreement (Custom)")
        self.assertEqual(locales.clean_server_name("По договоренности", "ru"), "По договоренности")

    def test_clean_format_name_purity(self):
        """Проверка строгой языковой чистоты названий форматов"""
        # T1
        self.assertEqual(locales.clean_format_name("T1 - Any vs Any", "en"), "T1: Any vs Any")
        self.assertEqual(locales.clean_format_name("T1 - Any vs Any", "ru"), "T1 — Any vs Any (Любой в любой)")
        self.assertEqual(locales.clean_format_name("T1 - Any vs Any (Bo3)", "en"), "T1: Any vs Any (Bo3 Set)")
        self.assertEqual(locales.clean_format_name("T1 - Any vs Any (Bo3)", "ru"), "T1 — Any vs Any [Bo3 Сет]")
        # T2
        self.assertEqual(locales.clean_format_name("T2 - Main vs Main", "en"), "T2: Main vs Main")
        self.assertEqual(locales.clean_format_name("T2 - Main vs Main", "ru"), "T2 — Main vs Main (Мейн в мейн)")
        # T3
        self.assertEqual(locales.clean_format_name("T3 - Mirror", "en"), "T3: Mirror (Same Stand)")
        self.assertEqual(locales.clean_format_name("T3 - Mirror", "ru"), "T3 — Mirror (Зеркалка стендов)")
        # Blind
        self.assertEqual(locales.clean_format_name("Blind Pick (Вслепую)", "en"), "Blind Pick (Secret to Referee)")
        self.assertEqual(locales.clean_format_name("Blind Pick (Вслепую)", "ru"), "Blind Pick (Вслепую в ЛС респу)")
        # No TS
        self.assertEqual(locales.clean_format_name("No TS (Без Таймстопа)", "en"), "No TS (No Time Stop)")
        self.assertEqual(locales.clean_format_name("No TS (Без Таймстопа)", "ru"), "No TS (Без тайм-стопа)")

    def test_challenge_dm_no_language_mixing(self):
        """Проверка отсутствия русских букв в английских DM-сообщениях и битых markdown-символов"""
        import re
        cyrillic_pattern = re.compile(r"[\u0400-\u04FF]")

        en_desc = locales.t(
            "challenge_dm_desc",
            "en",
            user="warsaw",
            challenger="aXD (@k9wqO)",
            guild="GANGHUB",
            format=locales.clean_format_name("T2 - Main vs Main", "en"),
            server=locales.clean_server_name("Hesse (Германия)", "en"),
            expire_ts=1792528061
        )
        # Проверяем 100% отсутствие кириллицы в English DM
        self.assertFalse(bool(cyrillic_pattern.search(en_desc)), f"Обнаружена кириллица в English DM: {en_desc}")
        # Проверяем отсутствие битых звездочек вокруг Duck
        self.assertNotIn("Duck**", en_desc)
        self.assertIn("`Duck`", en_desc)
        # Проверяем отсутствие сырой ссылки (кнопка внизу)
        self.assertNotIn("http", en_desc)

        # Проверяем футтер в English DM
        en_footer = locales.t("challenge_dm_footer", "en")
        self.assertFalse(bool(cyrillic_pattern.search(en_footer)))

    def test_get_user_lang_priority(self):
        """Проверка приоритета определения языка пользователя"""
        mock_db = MagicMock()
        mock_db.get_user_language.return_value = "en"

        # Приоритет 1: настройка в БД перевешивает всё
        self.assertEqual(locales.get_user_lang(mock_db, 123, fallback="ru"), "en")

        # При отсутствии настройки в БД: fallback
        mock_db.get_user_language.return_value = None
        self.assertEqual(locales.get_user_lang(mock_db, 123, fallback="ru"), "ru")

    def test_rules_stand_names_accuracy(self):
        """Проверка точности названий стендов, ультимейтов и скиллов в правилах"""
        stands_desc_ru = locales.t("rules_cat_stands_desc", "ru")
        stands_desc_en = locales.t("rules_cat_stands_desc", "en")
        formats_desc_ru = locales.t("rules_cat_formats_desc", "ru")
        formats_desc_en = locales.t("rules_cat_formats_desc", "en")

        # KDR (Crazy Diamond Requiem) в стендах с ограничениями
        self.assertIn("KDR", stands_desc_ru)
        self.assertIn("KDR", stands_desc_en)

        # Коробка KCR — Box (без ошибочного Dimension Slash)
        self.assertIn("Box", stands_desc_ru)
        self.assertIn("Box", stands_desc_en)
        self.assertNotIn("Dimension Slash / Box", stands_desc_ru)
        self.assertNotIn("Box (Dimension Slash)", stands_desc_en)

        # Сон SCR — Сон СЧР / Conqueror's Will, а не Conquering Burn / Your Own Shadow
        self.assertIn("Conqueror's Will", formats_desc_ru)
        self.assertIn("Conqueror's Will", formats_desc_en)
        self.assertNotIn("Conquering Burn", formats_desc_ru)
        self.assertNotIn("Conquering Burn", formats_desc_en)

if __name__ == "__main__":
    unittest.main()
